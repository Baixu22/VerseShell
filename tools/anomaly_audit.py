"""Read-only all-cell evidence census: observable mechanisms are not causal root proofs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench/aci/runners'))
from live_journal import load_observation
from live_turn_diagnostics import classify_cell
from live_uncertainty import row_class, usage_exclusion_reasons
from task_sets import load_tasks
from usage_audit import audit_row, paired_cells

EXEC_OPS={'run_command','exec.run'}
IDENTITY=('cell_id','task_id','model','condition','prompt_variant','seed','run_index')
SHELL_MARKERS=('is not recognized as an internal or external command', 'the syntax of the command is incorrect',
               '不是内部或外部命令', '命令语法不正确')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


def observation_facts(step, observed):
    """Markers describe the saved output; even exit 0 does not certify task success."""
    text=observed['text'];envelope=observed.get('envelope') or {}
    if not isinstance(envelope,dict):raise ValueError('malformed envelope')
    data=envelope.get('data') or {}
    if not isinstance(data,dict):raise ValueError('malformed envelope data')
    flags=[]
    code=data.get('exit_code') if type(data.get('exit_code')) is int else None
    if code is None and step['op'] in EXEC_OPS:
        match=re.search(r'\[EXIT: (-?\d+)\]\s*$',text)
        if match:code=int(match.group(1))
    if code is not None and code!=0:flags.append('nonzero_command_exit')
    if data.get('timed_out') is True or '[TIMEOUT after ' in text:flags.append('timeout_recorded')
    if any(marker in text.lower() for marker in SHELL_MARKERS):flags.append('shell_syntax_or_command_lookup_diagnostic')
    if '\ufffd' in text:flags.append('replacement_character_present')
    if '[TRUNCATED' in text:flags.append('text_cut_marker_present')
    error=envelope.get('error')
    error_code=error.get('code') if isinstance(error,dict) else None
    if error_code is not None:flags.append('structured_tool_error')
    streams={name:value.get('status') for name in ('stdout','stderr')
             if isinstance(value:=data.get(name),dict)}
    if any(v in ('reduced','truncated') for v in streams.values()):flags.append('reduced_or_truncated_stream')
    if any(isinstance(data.get(name),dict) and data[name].get('decoding_lossy') is True for name in ('stdout','stderr')):
        flags.append('lossy_decoding_reported')
    args_text=json.dumps(step.get('args'),sort_keys=True,ensure_ascii=False)
    if 'cargo_target_dir' in args_text.lower() or '--target-dir' in args_text.lower():flags.append('build_environment_override_mentioned')
    test_hint=re.search(r'\b(pytest|unittest|cargo\s+test|npm\s+test)\b',args_text,re.I)
    test_marker=re.search(r'test result: ok\.|\b[1-9]\d* passed\b|\b[1-9]\d* passing\b',text,re.I)
    if step['op'] in EXEC_OPS and code==0 and test_hint and test_marker:
        flags.append('successful_test_output_marker')
    return {'exit_code':code,'error_code':error_code,'stream_status':streams,
            'redacted':bool(observed.get('redacted')),'flags':flags,
            'raw_capture_metadata_present':bool(observed.get('raw_streams'))}


def audit_steps(row, root):
    steps=row.get('trajectory')
    if not isinstance(steps,list):
        return {'expected':None,'verified':0,'complete':False,'errors':[{'reason':'trajectory missing or malformed'}],
                'records':[],'signals':{},'longest_identical_call_streak':None,'max_identical_recorded_calls':None,'max_identical_visible_observations':None,
                'call_turn_alignment':'unknown','calls_after_test_success_marker':None}
    records=[];errors=[];signals=Counter();texts=Counter();calls=Counter();previous=None;streak=longest=0
    call_turns=[]
    turns=row.get('turn_diagnostics')
    alignment=isinstance(turns,list) and len(turns)==row.get('turns')
    for position,turn in enumerate(turns if isinstance(turns,list) else []):
        if not isinstance(turn,dict) or type(turn.get('tool_call_count')) is not int or turn['tool_call_count']<0:
            alignment=False;continue
        if turn.get('turn')!=position+1 or type(turn.get('turn')) is not int:
            alignment=False
        if turn['tool_call_count']>len(steps)-len(call_turns):
            alignment=False;continue
        call_turns.extend([turn.get('turn')]*turn['tool_call_count'])
    alignment=alignment and len(call_turns)==len(steps)
    first_test=None
    for index,step in enumerate(steps):
        record={'index':index}
        try:
            if not isinstance(step,dict) or not isinstance(step.get('op'),str):raise ValueError('invalid step')
            signature=digest([step['op'],step.get('args')]);calls[signature]+=1
            streak=streak+1 if signature==previous else 1;longest=max(longest,streak);previous=signature
            reference=step.get('observation')
            if not isinstance(reference,dict):raise ValueError('observation reference missing')
            observed=load_observation(root,reference)
            if observed.get('cell_id')!=row['cell_id']:raise ValueError('observation cell identity mismatch')
            if observed.get('op')!=step['op']:raise ValueError('observation operation mismatch')
            binding='redacted_not_checked' if observed.get('redacted') else 'matched'
            if step['op']=='task_complete' and 'args' not in observed:
                ack=json.loads(observed['text'])
                if not isinstance(ack,dict) or set(ack)!={'ok','acknowledged'} or ack['ok'] is not True or ack['acknowledged'] is not True:
                    raise ValueError('invalid legacy completion acknowledgement')
                binding='legacy_ack_arguments_not_recorded'
            elif not observed.get('redacted') and digest(observed.get('args'))!=digest(step.get('args')):
                raise ValueError('observation arguments mismatch')
            facts=observation_facts(step,observed)
            texts[reference['text_sha256']]+=1
            signals.update(facts['flags'])
            if 'successful_test_output_marker' in facts['flags'] and first_test is None:first_test=index
            record.update(op=step['op'],call_signature_sha256=signature,turn=call_turns[index] if alignment else None,
                          observation=reference,verified=True,
                          argument_binding=binding,**facts)
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
            record.update(verified=False,reason=str(error))
            errors.append({'index':index,'reason':str(error)})
        records.append(record)
    return {'expected':len(steps),'verified':len(steps)-len(errors),'complete':not errors,
            'errors':errors,'records':records,'signals':dict(signals),
            'longest_identical_call_streak':longest,'max_identical_recorded_calls':max(calls.values(),default=0),
            'max_identical_visible_observations':max(texts.values(),default=0),
            'call_turn_alignment':'matched' if alignment else 'unknown',
            'calls_after_test_success_marker':len(steps)-first_test-1 if first_test is not None else None}


def audit_cell(row, task, config, root):
    issues=[]
    try:usage_reasons=usage_exclusion_reasons(row)
    except (ValueError,TypeError,KeyError,AttributeError):usage_reasons=['malformed_usage_record']
    try:
        ledger=audit_row(row)
        unknown_attempts=[{k:a.get(k) for k in ('turn','attempt','attempt_id','status','request_id','request_body_sha256')}
                          for a in ledger['attempts'] if a['usage_status']=='unknown']
    except (ValueError,TypeError,KeyError,AttributeError):
        unknown_attempts=None;issues.append('usage_ledger_unreadable')
    try:kind=row_class(row,config['max_turns'])
    except (ValueError,TypeError):kind='unknown';issues.append('row_class_unreadable')
    try:
        diagnostic=classify_cell(row,config['max_tokens'])
        budget={'classification':diagnostic['classification'],'reason':diagnostic['reason'],
                'truncated_turn_numbers':diagnostic['evidence']['truncated_turn_numbers'],
                'unusable_turn_numbers':diagnostic['evidence']['unusable_turn_numbers']}
    except (ValueError,TypeError,KeyError,AttributeError):
        budget={'classification':'unknown_malformed','reason':'invalid per-turn records'}
    membership=[]
    if row.get('success') is False:membership.append('recorded_scoring_failure')
    if kind=='cap_truncated':membership.append('cap_truncated')
    if usage_reasons:membership.append('usage_gap')
    if type(row.get('success')) is not bool:membership.append('unknown_scoring')
    if kind in ('endpoint_failure','unknown'):membership.append(kind)
    mechanisms=[]
    if type(row.get('turns')) is int and row['turns']>=config['max_turns'] and row.get('stop_reason')=='turn_limit':
        mechanisms.append({'domain':'budget','code':'recorded_turn_limit_termination','basis':['turns','stop_reason','live_config.max_turns']})
    if budget.get('truncated_turn_numbers'):
        mechanisms.append({'domain':'budget','code':'completion_length_recorded','turns':budget['truncated_turn_numbers']})
    if row.get('api_error'):
        mechanisms.append({'domain':'endpoint','code':'terminal_api_error_recorded','status':row.get('endpoint_status')})
    if row.get('harness_fault'):
        mechanisms.append({'domain':'harness','code':'harness_fault_recorded'})
    if unknown_attempts:
        mechanisms.append({'domain':'endpoint_accounting','code':'usage_unknown_after_attempt','count':len(unknown_attempts)})
    observations=audit_steps(row,root)
    domains={
        'platform_interface':[f for f in ('shell_syntax_or_command_lookup_diagnostic','replacement_character_present',
            'lossy_decoding_reported','structured_tool_error','reduced_or_truncated_stream') if f in observations['signals']],
        'scoring':['recorded_failure_not_independently_rescored'] if row.get('success') is False else
                  ['unknown_recorded_score'] if type(row.get('success')) is not bool else [],
        'model_actions':[],
        'endpoint':(['terminal_api_error'] if row.get('api_error') else [])+(['unknown_attempt_usage'] if unknown_attempts else []),
        'budget':(['cap_truncated_policy_class'] if kind=='cap_truncated' else []),
        'harness':(['recorded_harness_fault'] if row.get('harness_fault') else [])}
    if (observations['max_identical_recorded_calls'] or 0)>1:domains['model_actions'].append('repeated_recorded_call')
    if (observations['max_identical_visible_observations'] or 0)>1:domains['model_actions'].append('repeated_visible_output')
    if (observations['calls_after_test_success_marker'] or 0)>0:domains['model_actions'].append('calls_after_test_output_marker')
    language=task.get('lang')
    if not isinstance(language,str) or not language:
        language='unknown';issues.append('task_language_unknown')
    return {**{k:row.get(k) for k in IDENTITY},'language':language,'row_class':kind,'membership':membership,
            'success_control':not membership and row.get('success') is True,
            'recorded_scoring':{'success':row.get('success'),'reason':row.get('success_reason'),
                                'independent_rescore':'not_run','original_value_unchanged':True},
            'budget':budget,'recorded_mechanisms':mechanisms,
            'underlying_task_cause':{'status':'unknown','reason':'Recorded termination, repeated calls and diagnostics do not identify a unique causal driver; '
                                    'final inputs, environment and counterfactual execution are not reconstructed here.'},
            'usage':{'eligible':not usage_reasons,'reasons':usage_reasons,'unknown_attempts':unknown_attempts},
            'observations':observations,'domain_evidence':domains,
            'blind_spots':{'final_workspace_reference_present':isinstance(row.get('final_workspace'),dict) and bool(row['final_workspace'].get('path')),
                'final_workspace_hash_checked':False,
                'build_environment_receipt_present':isinstance(row.get('workspace_build_environment'),dict),
                'build_environment_runtime_verified':False,
                'historical_shared_cargo_target_inheritance':'unknown' if language=='rust' else 'not_examined',
                'process_tree_cleanup_verified':False,'disk_boundary_verified':False},
            'record_issues':issues}


def analyse(payload, tasks, root, variant=None):
    config=payload.get('live_config') or {}
    if any(type(config.get(k)) is not int or config[k]<=0 for k in ('max_turns','max_tokens')):
        raise ValueError('positive frozen max_turns and max_tokens required')
    source_rows=payload.get('rows')
    if not isinstance(source_rows,list) or not source_rows:raise ValueError('non-empty rows required')
    if any(not isinstance(r,dict) for r in source_rows):raise ValueError('malformed row')
    ids=[r.get('cell_id') for r in source_rows]
    if any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):raise ValueError('missing/duplicate cell identity')
    paired_cells(source_rows)
    rows=source_rows if variant is None else [r for r in source_rows if r.get('prompt_variant')==variant]
    if not rows:raise ValueError('prompt variant not present')
    cells=[audit_cell(row,tasks.get(row['task_id'],{}),config,root) for row in rows]
    primary=[c for c in cells if c['membership']]
    failed={c['cell_id'] for c in cells if 'recorded_scoring_failure' in c['membership']}
    capped={c['cell_id'] for c in cells if 'cap_truncated' in c['membership']}
    gaps={c['cell_id'] for c in cells if 'usage_gap' in c['membership']}
    groups={}
    for axis in ('task_id','language','condition','prompt_variant','seed'):
        groups[axis]=[]
        for value in sorted({c[axis] for c in cells},key=str):
            sub=[c for c in cells if c[axis]==value]
            groups[axis].append({'value':value,'rows':len(sub),'primary_anomalies':sum(bool(c['membership']) for c in sub),
                'successful_controls':sum(c['success_control'] for c in sub),
                'cells_with_observation_gaps':sum(not c['observations']['complete'] for c in sub),
                'cells_with_signals':dict(Counter(flag for c in sub for flag in c['observations']['signals']))})
    return {'schema':'verseshell.anomaly-audit/v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'claimable':False,'scope':'all selected cells: immutable observation inspection only, no historical command execution or score rewriting',
        'summary':{'source_rows':len(source_rows),'selected_rows':len(rows),'audited_rows':len(cells),
            'recorded_scoring_failures':len(failed),'cap_truncated':len(capped),'usage_gaps':len(gaps),
            'failure_cap_intersection':len(failed&capped),'failure_or_cap_union':len(failed|capped),
            'primary_anomaly_union':len(primary),'primary_cell_ids':sorted(c['cell_id'] for c in primary),
            'successful_controls':sum(c['success_control'] for c in cells),
            'recorded_successful_rows_audited':sum(c['recorded_scoring']['success'] is True for c in cells),
            'unknown_language_rows':sum(c['language']=='unknown' for c in cells),
            'rust_rows_audited':sum(c['language']=='rust' for c in cells),
            'rust_successful_rows_audited':sum(c['language']=='rust' and c['recorded_scoring']['success'] is True for c in cells),
            'argument_bindings_not_verified':sum(r.get('verified') and r.get('argument_binding')!='matched' for c in cells for r in c['observations']['records']),
            'legacy_ack_argument_gaps':sum(r.get('argument_binding')=='legacy_ack_arguments_not_recorded' for c in cells for r in c['observations']['records']),
            'verified_observations':sum(c['observations']['verified'] for c in cells),
            'recorded_observations':sum(c['observations']['expected'] or 0 for c in cells),
            'cells_with_observation_gaps':sum(not c['observations']['complete'] for c in cells),
            'cells_with_recorded_mechanism':sum(bool(c['recorded_mechanisms']) for c in cells),
            'underlying_cause_unknown':len(cells),
            'domain_signal_cells':{scope:{domain:sum(bool(c['domain_evidence'][domain]) for c in subset)
                for domain in ('platform_interface','scoring','model_actions','endpoint','budget','harness')}
                for scope,subset in (('all',cells),('primary',primary),('successful_controls',[c for c in cells if c['success_control']]))},
            'observed_signal_counts':dict(Counter(flag for c in cells for record in c['observations']['records'] for flag in record.get('flags',[])))},
        'groups':groups,'cells':cells,
        'limits':['Legacy completion acknowledgements bind hash/cell/operation but did not record arguments; this limitation is counted separately and never certifies task success.',
                  'Observable terminal mechanisms are separate from underlying task causes; repetition and co-occurrence are not causal proof.',
                  'An exit-0 test-output marker does not certify the full task or prove that subsequent calls were unnecessary.',
                  'Scores are original recorded values, not independently recertified. Snapshot references and environment receipts are not verified by this audit.',
                  'Process-tree cleanup, disk boundaries and untested operating systems require their own acceptance evidence.',
                  'No absence-of-defect claim follows from complete observation coverage. Historical Rust cache inheritance remains unknown.',
                  'Hash checks prove consistency with supplied references, not authenticity or a same-user security sandbox.']}


def markdown(report):
    s=report['summary']
    lines=['# All-cell anomaly evidence audit — not formal acceptance','',
           f"Audited {s['audited_rows']}/{s['selected_rows']} selected rows; primary anomaly union {s['primary_anomaly_union']}; successful controls {s['successful_controls']}.",
           f"Observations: {s['verified_observations']}/{s['recorded_observations']} verified; cells with gaps {s['cells_with_observation_gaps']}.",'',
           '| cell | task | condition / variant | recorded memberships | recorded mechanisms | observations | underlying cause |',
           '|---|---|---|---|---|---:|---|']
    for c in report['cells']:
        if not c['membership']:continue
        mechanisms=', '.join(m['code'] for m in c['recorded_mechanisms']) or 'unknown'
        lines.append(f"| {c['cell_id']} | {c['task_id']} | {c['condition']} / {c['prompt_variant']} | {', '.join(c['membership'])} | {mechanisms} | {c['observations']['verified']}/{c['observations']['expected']} | unknown |")
    return '\n'.join(lines+['',*['- '+s for s in report['limits']]])+'\n'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--with-arm',type=Path,required=True);p.add_argument('--task-set',type=Path,required=True)
    p.add_argument('--task-dir',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--prompt-variant')
    args=p.parse_args(argv)
    try:
        source=args.with_arm.resolve();output=args.out.resolve();text_output=output.with_suffix('.md')
        if output.parent==source.parent or output==text_output or output.exists() or text_output.exists():
            raise ValueError('choose new JSON/Markdown files in a separate report directory')
        task_dir=(args.task_dir or args.task_set.resolve().parents[1]/'tasks').resolve()
        before=source.read_bytes()
        task_sources=[args.task_set.resolve(),*sorted(task_dir.glob('*.json'))]
        hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in task_sources}
        _,tasks=load_tasks(task_dir,args.task_set)
        report=analyse(json.loads(before.decode('utf-8-sig')),tasks,source.parent,args.prompt_variant)
        report['source']={'path':str(source),'sha256':hashlib.sha256(before).hexdigest()}
        report['task_source_sha256']=hashes
        report['analysis_source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'tools/anomaly_audit.py','tools/live_turn_diagnostics.py','tools/live_uncertainty.py','tools/usage_audit.py','bench/aci/runners/live_journal.py')}
        if source.read_bytes()!=before or any(hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h for f,h in hashes.items()):
            raise ValueError('source changed during audit')
        serialized=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
        readable=markdown(report)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8') as f:f.write(serialized)
        with text_output.open('x',encoding='utf-8') as f:f.write(readable)
        print(json.dumps({k:v for k,v in report['summary'].items() if k!='primary_cell_ids'},ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(f'ERROR: {error}',file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
