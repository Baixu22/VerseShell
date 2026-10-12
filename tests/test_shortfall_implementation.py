"""Offline implementation acceptance; real process tests never call an endpoint."""
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'bench/aci/runners'), str(ROOT/'tools')]
import live_agent_loop as h
import claim_gate
import task_set_audit
from live_identity import validate_run
from live_journal import pid_alive
from live_schedule import make_schedule, validate_schedule
from report_inputs import select_prompt_variant
from live_uncertainty import cost_per_success_interval
import refresh_live_artifacts as refresh
from merge_live_runs import refresh_summaries
import test_live_recovery as recovery


class ImplementationTests(unittest.TestCase):
    def test_partial_mixed_variants_cannot_hide_an_approved_comparison(self):
        rows=[]
        for variant in ('baseline','compact_all'):
            for condition in ('raw_shell','verseshell_aci'):
                row=recovery.RecoveryTests.row({'id':'task'},condition)
                row.update(prompt_variant=variant, tool_calls=1, observation_tokens=1)
                rows.append(row)
        payload={'rows':rows,'partial':True}
        refresh_summaries(payload)
        for block in payload['comparison']['by_prompt_variant'].values():
            for contrast in block['comparisons']:
                self.assertFalse(contrast['claimable'])
                self.assertFalse(contrast['meets_acceptance'])

    def test_cpst_zero_success_and_unknown_are_not_imputed(self):
        rows=[]
        for task in ('a','b'):
            for condition in ('raw_shell','verseshell_aci'):
                rows.append(dict(task_id=task, condition=condition, seed=42, run_index=0,
                                 success=True, observation_tokens=10 if condition=='raw_shell' else 5))
        result=cost_per_success_interval(rows,'raw_shell',80,iterations=100)
        self.assertEqual(result['ci95'],[.5,.5])
        self.assertFalse(result['claimable'])
        rows[1]['success']=False;rows[3]['success']=False
        self.assertFalse(cost_per_success_interval(rows,'raw_shell',80,iterations=100)['available'])
        rows[1]['success']=None
        self.assertIn('unverified',cost_per_success_interval(rows,'raw_shell',80,iterations=100)['reason'])

    def test_collection_refresh_never_marks_partial_bundle_complete(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'collection';source.mkdir();(source/'latest_live.json').write_text('{}')
            calls=[]
            def run(argv,**kw):
                calls.append(argv)
                Path(argv[argv.index('--out')+1]).write_text('{}')
                return SimpleNamespace(returncode=0 if len(calls)==1 else 3)
            out=root/'failed'
            self.assertEqual(refresh.refresh_collection(source,out,root/'tasks.json',runner=run),3)
            self.assertEqual(len(calls),2)
            self.assertFalse(json.loads((out/'refresh-status.json').read_text())['complete'])
            def success(argv,**kw):
                output=Path(argv[argv.index('--out')+1])
                output.write_text('{}')
                if output.name in ('cost_attribution.json','anomaly_audit.json'):
                    output.with_suffix('.md').write_text('diagnostic')
                return SimpleNamespace(returncode=0)
            self.assertEqual(refresh.refresh_collection(source,root/'ok',root/'tasks.json',runner=success),0)
            self.assertTrue(json.loads((root/'ok/refresh-status.json').read_text())['complete'])

    def test_interrupted_attempts_pause_and_have_finite_resume_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'run.json'
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                for i in range(3):
                    with patch.object(h,'run_agent_loop',side_effect=KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):h.main(args+(['--resume-paused'] if i else []))
                    with patch.object(h,'run_agent_loop') as call:
                        self.assertEqual(h.main(args),75)
                        call.assert_not_called()
                with patch.object(h,'run_agent_loop') as call:
                    self.assertEqual(h.main([*args,'--resume-paused']),75)
                    call.assert_not_called()
            history=json.loads(Path(str(out)+'.attempts.json').read_text())
            self.assertEqual(len(history['attempts']),3)

    def test_actual_input_outside_globs_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'eval').mkdir()
            source = root/'actual.json'; source.write_text('{}')
            (root/'code.py').write_text('pass')
            with patch.object(claim_gate, 'ROOT', root), patch.object(claim_gate, 'EVIDENCE_ARTIFACTS', ['eval/three_arm_report.json']):
                evidence = {'globs': ['code.py'], 'fingerprint': claim_gate.evidence_fingerprint(['code.py']),
                            'input_sha256': {'actual.json': hashlib.sha256(source.read_bytes()).hexdigest()}}
                (root/'eval/three_arm_report.json').write_text(json.dumps({'evidence': evidence}))
                self.assertTrue(claim_gate.freshness_entries()[0]['pass'])
                source.write_text('{"changed":true}')
                self.assertFalse(claim_gate.freshness_entries()[0]['pass'])
                source.unlink()
                self.assertFalse(claim_gate.freshness_entries()[0]['pass'])

    def test_missing_golden_is_failure_not_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(task_set_audit, 'FIXTURES', root):
                report = task_set_audit.fixture_consistency({'t': {'workspace_fixture': 'missing', 'success': {}}}, root/'work')
            self.assertIn('t', report)
            self.assertFalse(report['t']['pass'])

    def test_schedule_is_balanced_frozen_and_variant_safe(self):
        schedule = make_schedule([str(i) for i in range(12)], list(h.PROMPT_BY_CONDITION), [42], ['baseline','compact_all'])
        self.assertEqual(validate_schedule(schedule), schedule)
        self.assertEqual(len({tuple(c) for c in schedule['cells']}), 72)
        for position in range(6):
            counts = {}
            for cell in schedule['cells'][position::6]:
                key = (cell[1], cell[4]); counts[key] = counts.get(key, 0)+1
            self.assertEqual(set(counts.values()), {2})
        schedule['cells'][0], schedule['cells'][1] = schedule['cells'][1], schedule['cells'][0]
        with self.assertRaises(ValueError): validate_schedule(schedule)

    def test_mixed_variants_require_explicit_selection(self):
        payload = {'rows': [{'prompt_variant': v} for v in ('baseline','compact_all')]}
        with self.assertRaises(ValueError): select_prompt_variant(payload)
        self.assertEqual(len(select_prompt_variant(payload, 'baseline')['rows']), 1)
        with self.assertRaises(ValueError): select_prompt_variant(payload, 'compact')

    def test_six_treatment_runner_resume_preserves_every_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); out=root/'run.json'; plan=root/'schedule.json'
            tasks=['rust_fix_compile_error','rust_add_unit_test']
            conditions=list(h.PROMPT_BY_CONDITION)
            schedule=make_schedule(tasks,conditions,[42],['baseline','compact_all'])
            plan.write_text(json.dumps(schedule))
            args=['--model','offline','--api-key','test','--tasks',','.join(tasks), '--conditions',','.join(conditions),
                  '--seed','42','--out',str(out),'--schedule',str(plan)]
            order=[]
            def result(task,condition,**kw):
                order.append((task['id'],condition,42,kw['run_index'],kw['prompt_variant']))
                return recovery.RecoveryTests.row(task,condition,**kw)
            with patch.object(h,'run_agent_loop',side_effect=result) as call, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h.main(args),0)
                self.assertEqual(call.call_count,12)
                self.assertEqual(h.main(args),0)
                self.assertEqual(call.call_count,12)
            self.assertEqual(order,[tuple(c) for c in schedule['cells']])
            payload=json.loads(out.read_text(encoding='utf-8'))
            validate_run(payload)
            self.assertEqual(payload['comparison']['comparisons'],[])
            payload['rows'][0]['prompt_variant']='unknown'
            with self.assertRaises(ValueError): validate_run(payload)

    @unittest.skipUnless(os.name=='nt','Windows Job lifecycle')
    def test_barrier_assignment_failure_cannot_execute_workload(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'started'
            real_create=h._create_kill_on_close_job
            def broken_job():
                k32,job=real_create()
                k32.AssignProcessToJobObject=lambda *_: 0
                return k32,job
            with patch.object(h,'_create_kill_on_close_job',side_effect=broken_job):
                with self.assertRaisesRegex(OSError,'assignment failed'):
                    h.run_bounded([sys.executable,'-c',f'open({str(marker)!r},"w").write("ran")'], timeout=2)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name=='nt','Windows Job lifecycle')
    def test_binary_stdin_and_exit_code_survive_barrier(self):
        data=b'\x00\x01\xff\r\n'
        rc,out,err,timed=h.run_bounded([sys.executable,'-c','import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());sys.exit(7)'],timeout=3,stdin_data=data)
        self.assertEqual((rc,out,err,timed),(7,data,b'',False))

    @unittest.skipUnless(os.name=='nt','Windows Job lifecycle')
    def test_parent_death_kills_workload(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'child.pid'
            child=f'import os,time;open({str(marker)!r},"w").write(str(os.getpid()));time.sleep(60)'
            parent=f'import sys;sys.path.insert(0,{str(ROOT/"bench/aci/runners")!r});import live_agent_loop as h;h.run_bounded([sys.executable,"-c",{child!r}],timeout=60)'
            proc=subprocess.Popen([sys.executable,'-I','-c',parent],creationflags=subprocess.CREATE_NO_WINDOW,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+8
                marker_text=""
                while time.monotonic()<deadline:
                    if marker.exists():
                        marker_text=marker.read_text(encoding="utf-8", errors="replace").strip()
                        if marker_text:
                            break
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                self.assertTrue(marker_text, "child PID marker was created before its content was written")
                pid=int(marker_text)
                self.assertTrue(pid_alive(pid))
                proc.kill();proc.wait(timeout=3)
                deadline=time.monotonic()+3
                while pid_alive(pid) and time.monotonic()<deadline:time.sleep(.02)
                self.assertFalse(pid_alive(pid),'workload survived Job owner death')
            finally:
                if proc.poll() is None:proc.kill();proc.wait(timeout=3)


if __name__=='__main__': unittest.main()
