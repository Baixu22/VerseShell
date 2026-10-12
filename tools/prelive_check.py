"""Complete offline readiness gate. Does not call any model endpoint.

Writes ready_for_live only after current-source tests, grading, calibration and
the full synthetic acquisition/merge/inference chain have passed.
"""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import shutil
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'bench/aci/runners'),str(ROOT/'tools')]
import live_agent_loop as h
import merge_live_runs as merger
from live_journal import atomic_json
from live_schedule import make_schedule
from task_sets import load_tasks
from study_inference import read_plan,evaluate


def source_hashes(root=None):
    root=Path(root) if root is not None else ROOT
    patterns=['src/**/*.rs','Cargo.toml','Cargo.lock','bench/aci/runners/*.py',
              'bench/aci/scorers/*.py',
              'build.rs','tools/*.py','tests/**/*','bench/aci/fixtures/**/*','bench/aci/tasks/*.json','bench/aci/task_sets/*.json',
              'bench/aci/studies/prelive-v1/*.json',
               'audit-r12-scratch/verify_core.py','audit-r12-scratch/verify_part2.py',
               'audit-r12-scratch/verify_part3.py','audit-r12-scratch/verify_part4.py','audit-r12-scratch/audit_inputs.py',
               'audit-r12-scratch/r12-inputs.json','audit-r12-scratch/r12-reference/*.json',
               'audit-r12-scratch/r12-inputs/*.json']
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for pattern in patterns for p in sorted(root.glob(pattern)) if p.is_file() and '__pycache__' not in p.parts}


def checked_python_test_count(body):
    """An exit-zero suite with skipped/expected-failing checks is not full readiness."""
    matches = re.findall(r'^Ran (\d+) tests? in .+$', body, flags=re.MULTILINE)
    if len(matches) != 1 or int(matches[0]) < 192:
        raise ValueError('Python regression scope unexpectedly shrank or is ambiguous')
    if not re.search(r'^OK\s*$', body, flags=re.MULTILINE) or re.search(
            r'^OK \(', body, flags=re.MULTILINE):
        raise ValueError('Python readiness requires a clean suite without skips or expected failures')
    return int(matches[0])


def check_blueprint(path):
    b=json.loads(Path(path).read_text(encoding='utf-8'))
    dev=b['development'];held=b['holdout'];seen=set()
    for slot in dev+held:
        if slot['index'] in seen:raise ValueError('development/holdout slot collision')
        seen.add(slot['index'])
    categories={x['topic'] for x in held}
    if len(held)<30 or len({x['lang'] for x in held})<3 or len(categories)<4:
        raise ValueError('holdout composition below protocol')
    if any(sum(x['topic']==c for x in held)<5 for c in categories):raise ValueError('category quota missing')
    if 3*sum(x['tier']=='large' for x in held)<len(held):raise ValueError('large slot quota missing')
    if b['source_policy'].get('unknown_family_allowed') is not False:raise ValueError('unknown family permitted')
    return {'development_slots':len(dev),'holdout_slots':len(held),'actual_tasks_generated':False,
            'purpose':'offline blueprint; authors and real admission remain required before capability collection'}


def simulate_grid(output,plan_path,task_set,calibrations):
    """Exercise production scheduling/checkpoint/merge with explicit synthetic rows."""
    manifest,_=load_tasks(ROOT/'bench/aci/tasks',task_set)
    conditions=['raw_shell','raw_shell_coached','verseshell_aci']
    seeds=list(range(42,42+read_plan(plan_path)['minimum_seeds']))
    output.mkdir(parents=True,exist_ok=True);entries=[]
    fingerprint=h.evidence_fingerprint(h.EVIDENCE_GLOBS)
    binary=output/'synthetic-binary.txt';binary.write_text('NOT AN EXECUTABLE; synthetic grid identity only')
    def row(task,condition,**kw):
        amount=100 if condition!='verseshell_aci' else (25 if kw['prompt_variant']=='compact_all' else 50)
        return {'task_id':task['id'],'condition':condition,'model':'offline-preflight','run_index':kw['run_index'],
                'success':True,'success_reason':'SYNTHETIC CONTROL ONLY','turns':2,'tool_calls':max(1,amount//10),
                'observation_tokens':amount*5,'elapsed_ms':1,'trajectory':[], 'usage_complete':True,
                'llm_prompt_tokens':amount*10,'llm_completion_tokens':amount,'notes':['synthetic_test_only']}
    with (output/'simulation.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log), \
         patch.object(h,'AE',binary),patch.object(h,'evidence_fingerprint',return_value=fingerprint), \
         patch.object(h,'run_agent_loop',side_effect=row) as agent, \
         patch.object(h,'chat_completion',side_effect=AssertionError('network forbidden in preflight')):
        for run in range(3):
            folder=output/f'run-{run}';folder.mkdir()
            schedule=make_schedule(manifest['tasks'],conditions,seeds,['baseline','compact_all'],order_seed=42+run)
            schedule_path=folder/'schedule.json';atomic_json(schedule_path,schedule)
            shards=[]
            for seed in seeds:
                shard=folder/f'seed-{seed}.json'
                argv=['--full','--conditions',','.join(conditions),'--model','offline-preflight','--api-key','synthetic-key',
                      '--seed',str(seed),'--out',str(shard),'--collection-id',f'synthetic-{run}',
                      '--task-set',str(task_set),'--schedule',str(schedule_path),'--analysis-plan',str(plan_path),
                      '--max-turns','80','--max-tokens','16384']
                if h.main(argv)!=0:raise ValueError('synthetic runner failed')
                calls=agent.call_count
                if h.main(argv)!=0 or agent.call_count!=calls:raise ValueError('resume replayed committed cells')
                payload=json.loads(shard.read_text(encoding='utf-8'));payload['synthetic_test_only']=True
                atomic_json(shard,payload);shards.append(shard)
            merged=folder/'latest_live.json'
            if merger.main(['--out',str(merged),*map(str,shards)])!=0:raise ValueError('synthetic merge failed')
            entries.append({'run_id':str(run),'artifact':str(merged.resolve())})
        expected=3*len(manifest['tasks'])*len(seeds)*len(conditions)*2
        if agent.call_count!=expected:raise ValueError('synthetic grid count mismatch')
    task_manifest=output/'task-manifest.json';atomic_json(task_manifest,manifest)
    study=output/'study.json';atomic_json(study,{'task_manifest':str(task_manifest.resolve()),'seeds':seeds,'conditions':conditions,'runs':entries})
    report=evaluate(study,plan_path,calibrations,draws=80)
    if any(v['claimable'] for v in report['verdicts'].values()):raise ValueError('synthetic data obtained a live claim')
    if not all(v['views']['analysable'].get('available') for v in report['verdicts'].values()):
        raise ValueError('synthetic inference chain lacks required estimates')
    atomic_json(output/'inference.json',report)
    return {'synthetic_cells':expected,'resumed_duplicate_calls':0,'merged_runs':3,'live_endpoint_calls':0,
            'family_size':report['family_size'],'synthetic_claims_blocked':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--task-set',type=Path,default=ROOT/'bench/aci/task_sets/3.1.0.json')
    parser.add_argument('--plan',type=Path,default=ROOT/'bench/aci/studies/prelive-v1/analysis-plan.json')
    args=parser.parse_args(argv);out=args.out_dir.resolve()
    if out.exists() and any(out.iterdir()):parser.error('use a new empty readiness output directory')
    out.mkdir(parents=True,exist_ok=True);before=source_hashes();steps=[]
    report={'schema':'verseshell.prelive-readiness/v1','ready_for_live':False,'endpoint_verified':False,'steps':steps}
    atomic_json(out/'readiness.json',report)
    candidate=Path(h.AE).resolve()
    def candidate_digest():
        if Path(h.AE).resolve()!=candidate:raise ValueError('candidate binary path changed')
        return hashlib.sha256(candidate.read_bytes()).hexdigest()
    def stage(name,command,timeout=900,env=None):
        binary_before=candidate_digest()
        if binary_before!=expected_binary:raise ValueError(f'candidate binary changed before {name}')
        started=time.monotonic();rc,stdout,stderr,timed=h.run_bounded(command,cwd=ROOT,timeout=timeout,env=env)
        body=(stdout+stderr).decode('utf-8','replace');(out/(name+'.log')).write_text(body,encoding='utf-8')
        binary_after=candidate_digest()
        entry={'name':name,'exit_code':rc,'timeout':timed,'seconds':round(time.monotonic()-started,3),
               'binary_sha256_before':binary_before,'binary_sha256_after':binary_after}
        steps.append(entry);atomic_json(out/'readiness.json',report)
        print(f'{name}: exit={rc}, timeout={timed}',flush=True)
        if rc!=0 or timed:raise ValueError(f'{name} failed')
        if binary_after!=expected_binary:raise ValueError(f'candidate binary changed during {name}')
        return body
    try:
        expected_binary=candidate_digest()
        report.update(binary_path=str(candidate),binary_sha256_before=expected_binary)
        atomic_json(out/'readiness.json',report)
        for path in before:
            if path.endswith('.py'):ast.parse((ROOT/path).read_text(encoding='utf-8-sig'),filename=path)
        read_plan(args.plan)
        report['blueprint']=check_blueprint(ROOT/'bench/aci/studies/prelive-v1/task-blueprint.json')
        report['toolchain']={}
        for name in ('python','node','cargo','rustc','npm'):
            executable=sys.executable if name=='python' else shutil.which(name)
            if not executable:raise ValueError(f'missing toolchain: {name}')
            version=stage('version-'+name,[executable,'--version'],60).strip()
            report['toolchain'][name]={'path':str(Path(executable).resolve()),'version':version,
                                      'sha256':hashlib.sha256(Path(executable).read_bytes()).hexdigest()}
        body=stage('python-tests',[sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-p','test_*.py'])
        report['python_tests']=checked_python_test_count(body)
        rust_target=out/'rust-tests-target'
        report['rust_test_target_dir']=str(rust_target)
        body=stage('rust-tests',['cargo','test','--lib','--tests','--offline','--target-dir',str(rust_target)],
                   env=dict(os.environ,CARGO_TARGET_DIR=str(rust_target)))
        suites=re.findall(r'test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored',body)
        if not suites or sum(int(x[1]) for x in suites):raise ValueError('Rust tests missing or failed')
        report['rust_tests']={'passed':sum(int(x[0]) for x in suites),'ignored':sum(int(x[2]) for x in suites)}
        empty=out/'audit-input.json';atomic_json(empty,{'rows':[],'purpose':'no historical rescoring in readiness'})
        stage('task-audit',[sys.executable,'-X','utf8',str(ROOT/'tools/task_set_audit.py'),'--task-set',str(args.task_set),
                            '--with-arm',str(empty),'--out',str(out/'task-audit.json')])
        audit=json.loads((out/'task-audit.json').read_text(encoding='utf-8'))
        import claim_gate
        if not claim_gate.task_set_consistency_claim(audit,args.task_set)['pass']:raise ValueError('effective scoring audit failed')
        report['task_audit_passed']=len(audit['fixture_consistency'])
        calibrations=[]
        for runs in (3,10,30):
            path=out/f'calibration-r{runs}.json'
            stage(f'calibration-r{runs}',[sys.executable,'-X','utf8',str(ROOT/'tools/calibrate_repeated_intervals.py'),
                  '--method','axis_t','--extended','--runs',str(runs),'--repetitions','2000','--seed','20261006','--out',str(path)])
            c=json.loads(path.read_text())
            if not c.get('calibration_approved'):raise ValueError('specified calibration scenarios failed')
            calibrations.append(path)
        report['simulation']=simulate_grid(out/'synthetic',args.plan,args.task_set,calibrations)
        report['binary_sha256_after_synthetic']=candidate_digest()
        if report['binary_sha256_after_synthetic']!=expected_binary:raise ValueError('candidate binary changed during synthetic acquisition')
        with tempfile.TemporaryDirectory(prefix='prelive-aci-') as tmp:
            workspace=Path(tmp);(workspace/'probe.txt').write_text('prelive-aci-ready',encoding='utf-8')
            view=h.execute_aci_op('file.view',{'path':'probe.txt','cursor':1,'window':5},tmp)
            execution=h.execute_aci_op('exec.run',{'argv':[sys.executable,'-c','print("prelive-exec-ready")']},tmp)
            if not view.get('ok') or 'prelive-aci-ready' not in json.dumps(view) or not execution.get('ok') or 'prelive-exec-ready' not in json.dumps(execution):
                raise ValueError('real ACI smoke failed')
            atomic_json(out/'aci-smoke.json',{'view':view,'execution':execution})
        if before!=source_hashes():raise ValueError('source changed during readiness; rerun against stable code')
        report['binary_sha256_after_smoke']=candidate_digest()
        if report['binary_sha256_after_smoke']!=expected_binary:raise ValueError('candidate binary changed during ACI smoke')
        report.update(ready_for_live=True,source_sha256=before,runner_fingerprint=h.evidence_fingerprint(h.EVIDENCE_GLOBS),
                      binary_sha256=expected_binary,
                      analysis_plan_sha256=hashlib.sha256(args.plan.read_bytes()).hexdigest(),
                      scope='offline engineering and prospective analysis readiness; run explicit endpoint probe before collection',
                      empirical_claims_approved=False)
        atomic_json(out/'readiness.json',report);print('OFFLINE PRE-LIVE READINESS PASSED',flush=True);return 0
    except Exception as error:
        report['error']=str(error);atomic_json(out/'readiness.json',report)
        print(f'PRE-LIVE READINESS FAILED: {error}',flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
