"""Selected input provenance for claim_gate. Does not grant scientific effect claims."""
import hashlib
import json
from pathlib import Path

OPTION_INPUTS = {
    'bench/aci/results/latest.json':'bench', 'eval/metrics.json':'metrics',
    'eval/compact_ratio.json':'compact_ratio', 'eval/cross_shell.json':'cross_shell',
    'eval/tf45_envelope_replay.json':'envelope_replay', 'eval/read_path_breakdown.json':'read_path_breakdown',
    'eval/exec_failure_breakdown.json':'exec_failure_breakdown', 'eval/aci_learning_probe.json':'learning_probe',
    'eval/live_uncertainty.json':'live_uncertainty', 'eval/projection_contract.json':'projection_contract',
    'eval/token_proxy_calibration.json':'token_proxy_calibration', 'eval/acceptance_power.json':'acceptance_power',
    'eval/task_admissibility.json':'task_admissibility', 'eval/task_set_audit.json':'task_set_audit',
    'bench/aci/results/live_ab_without_read_files.json':'without_arm',
    'eval/statistics_crosscheck.json':'statistics_crosscheck',
}


def selected_paths(root, args, registered):
    """Exact allow-listed logical artifacts; explicit CLI and map conflicts fail."""
    root=Path(root).resolve();allowed=set(registered)|set(OPTION_INPUTS)
    overrides={};map_path=getattr(args,'artifact_map',None)
    if map_path:
        map_path=Path(map_path).resolve();data=json.loads(map_path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict) or data.get('schema')!='verseshell.claim-input-map/v1' or not isinstance(data.get('artifacts'),dict):
            raise ValueError('invalid claim input map')
        for key,value in data['artifacts'].items():
            normalized=key.replace('\\','/')
            if normalized not in allowed or normalized in overrides or not isinstance(value,str) or not value:
                raise ValueError('unknown, duplicate or malformed artifact mapping: '+key)
            overrides[normalized]=(map_path.parent/value).resolve()
    for logical,option in OPTION_INPUTS.items():
        explicit=getattr(args,option,None)
        if explicit is not None:
            value=Path(explicit).resolve()
            if logical in overrides and overrides[logical]!=value:
                raise ValueError('conflicting CLI/map input: '+logical)
            overrides[logical]=value
    return {name:overrides.get(name,root/name) for name in sorted(allowed)},set(overrides)


def file_hashes(paths):
    out={}
    for name,path in paths.items():
        try:out[name]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:out[name]=None
    return out


def source_snapshot(root):
    # Reuse the established readiness source boundary instead of a second code glob list.
    from prelive_check import source_hashes
    root=Path(root)
    result=source_hashes(root)
    for name in ('README.md','docs/claims-and-evidence.md','docs/acceptance-criteria.md'):
        if (root/name).is_file():result[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    return result


def changed_sources(before, after):
    return sorted(name for name in before.keys()|after.keys() if before.get(name)!=after.get(name))


def apply_stability_guard(claims, before, after, input_before, input_after, generated=()):
    code_drift=changed_sources(before,after)
    expected_inputs=dict(input_before)
    for name in generated:
        expected_inputs[name]=generated[name].get('sha256')
    input_drift=changed_sources(expected_inputs,input_after)
    if code_drift or input_drift:
        c12=next(c for c in claims if c['id']=='C12')
        c12.update(value=0.0, **{'pass':False})
        c12.setdefault('detail',{})['changed_during_gate']={'source':code_drift,'inputs':input_drift}
        c12['notes']+=' | source or selected input changed during gate; no current-state certification'
    return {'stable':not code_drift and not input_drift,'source_drift':code_drift,'input_drift':input_drift,
            'source_sha256':after,'selected_input_sha256':input_after}


def build_inventory(claims, registry, selected, freshness, stability, generated, root):
    root=Path(root).resolve()
    fresh={x['artifact']:x for x in freshness}
    artifacts={}
    for logical,path in selected.items():
        path=Path(path).resolve();record={'path':str(path),'sha256':stability['selected_input_sha256'].get(logical)}
        try:
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict):raise ValueError('artifact must be an object')
            record['version']={k:data.get(k) for k in ('schema','generated_at','task_set_version','git_rev','mode','model','protocol','prompt_variant','collection_id') if k in data}
            config=data.get('live_config') or {}
            record['collection']={k:config.get(k) for k in ('collection_id','model','protocol','prompt_variant','prompt_variants','seeds','max_turns','max_tokens') if k in config}
            identity=data.get('run_identity') or {}
            record['binary']={k:v for k,v in {
                'path':data.get('ae_binary'),
                'sha256':data.get('ae_binary_sha256') or identity.get('binary_sha256') or data.get('binary_sha256')
            }.items() if v is not None}
            record['rows']=len(data['rows']) if isinstance(data.get('rows'),list) else None
            record['declared_input_sha256']=(data.get('evidence') or {}).get('input_sha256')
            record['source_identity']=data.get('source_identity')
            if logical in generated:
                record.update(currency='generated_in_this_gate' if generated[logical].get('exit_code')==0 else 'producer_failed_or_unverified',
                              producer=generated[logical])
            elif logical in fresh:
                record.update(currency='fresh' if fresh[logical]['pass'] else 'historical_or_unverified',freshness=fresh[logical])
            elif logical.startswith('@'):
                record['currency']='definition_or_execution_receipt'
            else:
                record['currency']='unverified_source_binding'
        except (OSError,ValueError,TypeError,AttributeError) as error:
            record.update(currency='missing_or_unreadable',error=str(error))
        artifacts[logical]=record
    inverse={str(Path(p).resolve()):name for name,p in selected.items()}
    def input_names(sources):
        names=[]
        for source in sources:
            normalized=source.replace('\\','/')
            if normalized in selected: name=normalized
            else: name=inverse.get(str((root/source).resolve()))
            if name and name not in names:names.append(name)
        return names
    existing={c['id']:c for c in claims}
    inventory=[]
    for cid in sorted(set(registry)|set(existing),key=lambda v:int(v[1:])):
        c=existing.get(cid);entry=registry.get(cid,{'gated':True,'caliber':'no_token_field_published'})
        sources=(c or {}).get('source',entry.get('source',[]))
        inputs=input_names(sources)
        if c:
            c['declared_source']=list(sources)
            c['source']=[str(selected[s.replace('\\','/')]) if s.replace('\\','/') in selected else s for s in sources]
            c['input_artifacts']=inputs
        verdict=c.get('pass') if c else None
        direct=bool(c and ((c.get('mode')=='cargo_test' and c.get('exit_code')==0
                          and (c.get('test_totals') or {}).get('passed',0)>0)
                         or (c.get('execution') or {}).get('exit_code')==0))
        currencies=[artifacts[n]['currency'] for n in inputs]
        if verdict is False:status='not_met'
        elif not c:status='diagnostic_only'
        elif not stability['stable']:status='unverified'
        elif direct:status='verified_current_check'
        elif currencies and all(v in ('fresh','generated_in_this_gate','definition_or_execution_receipt') for v in currencies):
            status='verified_selected_measurement'
        elif any(v=='historical_or_unverified' for v in currencies):status='historical_only'
        else:status='unverified'
        inventory.append({'id':cid,'gated':bool(entry['gated']),'claim':(c or {}).get('claim',entry.get('measured_by')),
            'status':status,'gate_pass':verdict,'threshold':(c or {}).get('threshold'),
            'value':(c or {}).get('value'),'sample_size':(c or {}).get('sample_size',((c or {}).get('test_totals') or {}).get('passed')),'mode':(c or {}).get('mode','diagnostic'),
            'evaluated_at':(c or {}).get('measured_at'),'platform':(c or {}).get('platform'),
            'input_artifacts':inputs,'token_caliber':entry['caliber'],
            'producer_command_not_necessarily_run':(c or {}).get('command',entry.get('measured_by')),
            'boundary':(c or {}).get('notes',entry.get('note'))})
    return {'schema':'verseshell.claim-inventory/v1','claims':inventory,'artifacts':artifacts,
        'stability':stability,
        'research_boundary':{'formal_effect_verdict':'not_granted_by_this_inventory',
            'authority':'tools/study_inference.py with frozen plan, calibrated complete repeated runs and independent acceptance evidence',
            'remaining_task_evidence':['TF-0112','TF-0114','TF-0115','TF-0120','TF-0132','TF-0135','TF-0136'],
            'warning':'A current consistency check on historical data does not recertify acquisition, author independence, or product effectiveness.'}}


def markdown(inventory):
    lines=['# Claim / selected-input / version map','',
           'Gate predicates and thresholds are unchanged. Status is scoped to the selected evidence; no formal effect claim is granted here.','',
           '| claim | gate result | scoped status | recorded n | value / threshold | actual inputs |','|---|---|---|---:|---|---|']
    for c in inventory['claims']:
        result='not gated' if c['gate_pass'] is None else ('pass' if c['gate_pass'] else 'FAIL')
        inputs='<br>'.join(inventory['artifacts'][k]['path'] for k in c['input_artifacts']) or 'current source/test receipt or missing binding'
        measurement='diagnostic' if not c['gated'] else f"{c['value']} / {c['threshold']}"
        lines.append(f"| {c['id']} | {result} | {c['status']} | {c['sample_size']} | {measurement} | {inputs} |")
    lines+=['','## Input versions','']
    for name,a in inventory['artifacts'].items():
        lines += [f"- {name}: {a['path']}",f"  - sha256: {a.get('sha256')}; currency: {a['currency']}",
                  '  - version: '+json.dumps(a.get('version',{}),ensure_ascii=False),
                  '  - source identity: '+json.dumps(a.get('source_identity'),ensure_ascii=False),
                  '  - binary: '+json.dumps(a.get('binary',{}),ensure_ascii=False)]
    lines+=['',inventory['research_boundary']['warning']]
    return '\n'.join(lines)+'\n'


def require_current_evidence(claims, inventory):
    """C12 cannot approve a gate whose passing measurements still lack current binding."""
    unsupported=[c['id'] for c in inventory['claims'] if c['gated'] and c['gate_pass'] is True
                 and c['status'] in ('historical_only','unverified')]
    inventory['current_binding_missing_for']=unsupported
    if unsupported:
        c12=next(c for c in claims if c['id']=='C12')
        c12.update(value=0.0, **{'pass':False})
        c12.setdefault('detail',{})['current_binding_missing_for']=unsupported
        c12['notes']+=' | some passing predicates have historical or unverified inputs'
        next(c for c in inventory['claims'] if c['id']=='C12').update(status='not_met',gate_pass=False,value=0.0)
