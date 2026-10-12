"""Offline pre-live requirements: inference, provenance and grading isolation."""
import contextlib
import ctypes
import gc
import hashlib
import io
import json
import os
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'bench/aci/runners')]
import live_agent_loop as h
import test_live_recovery as recovery
from crossed_inference import t_critical,summarize,interaction
from grading_contract import freeze_verifiers,freeze_fixture_verifiers,guarded_success
from fixture_deps import materialize_deps
import task_admissibility as admission
from study_inference import read_plan
from study_inference import evaluate
import study_inference
from prelive_probe import probe
import repeated_run_uncertainty as repeated
from live_uncertainty import row_class,row_policy
import run_task_plan as driver
from live_journal import ObservationStore


class PreliveRepairs(unittest.TestCase):
    def current_test_plan(self, directory):
        # Keep the production frozen plan unchanged; isolate tests of later gates.
        data=json.loads((ROOT/'bench/aci/studies/prelive-v1/analysis-plan.json').read_text())
        data['analysis_code_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                      for name in data['analysis_code_sha256']}
        path=Path(directory)/'test-plan.json'
        path.write_text(json.dumps(data))
        return path

    def test_prospective_plan_pins_analysis_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.current_test_plan(tmp)
            data=json.loads(path.read_text())
            data['analysis_code_sha256']['tools/crossed_inference.py']='0'*64
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'implementation changed'):read_plan(path)

    def test_historical_acquisition_cannot_receive_a_new_analysis_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cal.json'
            path.write_text(json.dumps({'calibration_approved':True,'configuration':{'method':'axis_t','repetitions':2000,'runs':3},
                'source_sha256':{'crossed_inference.py':hashlib.sha256((ROOT/'tools/crossed_inference.py').read_bytes()).hexdigest()},
                'scenarios':{'control':{'unavailable':0,'rejection_fraction_ci95_mc':[0,.01]}},
                'joint_controls':{'control':{'unavailable':0,'mc95':[0,.01]}}}))
            historical={'tasks':list(range(30)),'seeds':list(range(5)),
                        'runs':[{'config':{'analysis_plan_sha256':'old'}} for _ in range(3)]}
            with patch.object(study_inference,'load_study',return_value=historical):
                with self.assertRaisesRegex(ValueError,'not frozen'):
                    evaluate(Path(tmp)/'study.json',self.current_test_plan(tmp),[path])

    def test_verifier_discovery_cannot_be_disabled_by_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cargo=root/'Cargo.toml';cargo.write_text('[package]\nname="test"\nversion="0.1.0"')
            pred={'type':'command_exit_0','argv':['cargo','test']}
            frozen=freeze_verifiers(pred,root);cargo.write_text(cargo.read_text()+'\nautotests=false')
            with patch.object(h,'check_success',return_value=(True,'fake')) as evaluator:
                self.assertFalse(guarded_success(pred,root,frozen,evaluator)[0]);evaluator.assert_not_called()
            pred={'type':'command_exit_0','argv':['python','-m','pytest']}
            frozen=freeze_verifiers(pred,root);(root/'pyproject.toml').write_text('[tool.pytest.ini_options]\naddopts="--ignore=tests"')
            with patch.object(h,'check_success',return_value=(True,'fake')) as evaluator:
                self.assertFalse(guarded_success(pred,root,frozen,evaluator)[0]);evaluator.assert_not_called()

    def test_analysable_ratio_uses_complete_pairs_and_informative_clusters(self):
        rows={}
        for task,a,d in [('a',1,100),('b',10,20)]:
            for condition,value in [('raw_shell',a),('verseshell_aci',d)]:
                rows[(task,condition,42,0)]={'condition':condition,'task_id':task,'success':True,
                    'turns':80 if task=='a' and condition=='raw_shell' else 1,'observation_tokens':value}
        study={'tasks':['a','b'],'seeds':[42],'indices':[0],
               'runs':[{'rows':rows,'config':{'max_turns':80}} for _ in range(3)]}
        matrix=repeated.metric_cells(study,'raw_shell','analysable','observation_token_ratio')
        self.assertEqual(matrix[0][0],(0,0,0,0))
        self.assertEqual(repeated.estimate([c for row in matrix for c in row],'ratio'),2)
        self.assertFalse(summarize(matrix,'ratio')['available'])

    def test_custom_candidate_audit_hashes_actual_inputs_and_not_its_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);candidate=root/'candidates'/'one';candidate.mkdir(parents=True)
            task=candidate/'task.json';task.write_text('{"id":"one"}')
            report=root/'candidates'/'admission.json'
            audited={'candidate':'one','admissible':True,'kind':'capability','checks':{},'reasons':{}}
            with patch.object(admission,'audit_candidate',return_value=audited),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(admission.main(['--candidates',str(candidate.parent),'--out',str(report)]),0)
            data=json.loads(report.read_text())
            self.assertEqual(data['evidence']['input_sha256'],{str(task.resolve()):hashlib.sha256(task.read_bytes()).hexdigest()})
            self.assertNotIn(str(report.resolve()),data['evidence']['input_sha256'])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(admission.main(['--candidates',str(root/'absent'),'--out',str(root/'empty.json')]),2)

    def test_materialized_compiler_is_in_the_same_grading_contract(self):
        fixture=ROOT/'bench/aci/fixtures/ts_fix_type_error'
        predicate=json.loads((ROOT/'bench/aci/tasks/ts_fix_type_error.json').read_text())['success']
        expected=freeze_fixture_verifiers(predicate,fixture)
        self.assertIn('node_modules/typescript/lib/tsc.js',expected)
        self.assertIn('tsconfig.json',expected)
        workspace=h.prepare_workspace('ts_fix_type_error')
        try:
            self.assertEqual(expected,freeze_verifiers(predicate,workspace))
            config=workspace/'tsconfig.json';original_config=config.read_bytes()
            config.write_text('{"files":["safe.ts"]}');(workspace/'safe.ts').write_text('export {};')
            with patch.object(h,'check_success',return_value=(True,'fake')) as evaluator:
                self.assertFalse(guarded_success(predicate,workspace,expected,evaluator)[0])
                evaluator.assert_not_called()
            config.write_bytes(original_config)
            (workspace/'node_modules/typescript/lib/tsc.js').write_text('process.exit(0)')
            with patch.object(h,'check_success',return_value=(True,'fake')) as evaluator:
                self.assertFalse(guarded_success(predicate,workspace,expected,evaluator)[0])
                evaluator.assert_not_called()
        finally:
            import shutil
            shutil.rmtree(workspace)

    def test_dependency_archive_traversal_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'fixture';(fixture/'deps').mkdir(parents=True)
            workspace=root/'workspace';workspace.mkdir()
            outside=root/'outside.txt';outside.write_text('preserve')
            archive=fixture/'deps/bad.tgz'
            with tarfile.open(archive,'w:gz') as tar:
                for name,body in [('package/package.json',b'{"name":"safe"}'),('package/../../outside.txt',b'corrupt')]:
                    info=tarfile.TarInfo(name);info.size=len(body);tar.addfile(info,io.BytesIO(body))
            with self.assertRaisesRegex(RuntimeError,'unsafe'):materialize_deps(fixture,workspace)
            self.assertEqual(outside.read_text(),'preserve')

    def test_recovery_at_request_response_observation_and_committed_row_boundaries(self):
        for phase in ('request_sent','response_received','observation','row_committed'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);work=root/'work';work.mkdir();out=root/'run.json'
                args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error',
                      '--conditions','raw_shell','--seed','42','--out',str(out)]
                armed=[True];calls=[0]
                original_diag=h._record_turn_diagnostics;original_atomic=h.atomic_json
                def crash_if(name):
                    if phase==name and armed[0]:armed[0]=False;raise KeyboardInterrupt
                def response(*args,**kwargs):
                    calls[0]+=1;crash_if('request_sent')
                    if calls[0]%2:
                        msg={'tool_calls':[{'id':'call','type':'function','function':{'name':'run_command','arguments':'{"command":"echo ok"}'}}]}
                    else:msg={'content':'done'}
                    return {'usage':{'prompt_tokens':2,'completion_tokens':1},'choices':[{'finish_reason':'tool_calls' if 'tool_calls' in msg else 'stop','message':msg}]}
                def diagnostic(*args,**kwargs):crash_if('response_received');return original_diag(*args,**kwargs)
                def save(*args,**kwargs):crash_if('observation');return {'synthetic_reference':True}
                def atomic(path,value):
                    if str(path).endswith('.attempts.json') and any(a.get('state')=='recorded' for a in value.get('attempts',[])):
                        crash_if('row_committed')
                    return original_atomic(path,value)
                with patch.object(h,'prepare_workspace',return_value=work),patch.object(h,'chat_completion',side_effect=response), \
                     patch.object(h,'execute_shell_cmd',return_value='ok'),patch.object(h,'check_success',return_value=(True,'synthetic')), \
                     patch.object(h,'_record_turn_diagnostics',side_effect=diagnostic),patch.object(ObservationStore,'save',side_effect=save), \
                     patch.object(h,'atomic_json',side_effect=atomic),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(KeyboardInterrupt):h.main(args)
                    before=calls[0]
                    if phase!='row_committed':self.assertEqual(h.main(args),75)
                    self.assertEqual(h.main([*args,'--resume-paused']),0)
                    if phase=='row_committed':self.assertEqual(calls[0],before)
                data=json.loads(out.read_text(encoding='utf-8'))
                self.assertEqual(len(data['rows']),1)
                self.assertEqual(data['partial'],phase!='row_committed')
                self.assertEqual(bool(data['rows'][0].get('recovery_uncertain')),phase!='row_committed')

    def test_probe_round_trip_does_not_mutate_collector_budget(self):
        prior=h.API_TIMEOUT_SEC
        def response(messages,tools,**kwargs):
            nonce=json.loads(messages[1]['content'])['nonce']
            msg=({'tool_calls':[{'id':'call-1','type':'function','function':{'name':'probe_echo','arguments':json.dumps({'nonce':nonce})}}]}
                 if len(messages)==2 else {'content':nonce})
            return {'usage':{'prompt_tokens':2,'completion_tokens':1},'choices':[{'finish_reason':'tool_calls' if len(messages)==2 else 'stop','message':msg}]}
        with patch.object(h,'chat_completion',side_effect=response) as call:
            result=probe('offline','http://offline.invalid/v1','private',budget=7)
        self.assertTrue(result['pass']);self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.kwargs['request_budget'],7)
        self.assertEqual(h.API_TIMEOUT_SEC,prior)
        with patch.object(h,'chat_completion') as call:
            with self.assertRaises(ValueError):probe('','http://offline.invalid/v1','private')
            call.assert_not_called()

    def test_calibration_label_cannot_override_adverse_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cal.json'
            value={'calibration_approved':True,'configuration':{'method':'axis_t','repetitions':2000,'runs':3},
                   'source_sha256':{'crossed_inference.py':hashlib.sha256((ROOT/'tools/crossed_inference.py').read_bytes()).hexdigest()},
                   'scenarios':{'bad':{'unavailable':0,'rejection_fraction_ci95_mc':[.2,.4]}},
                   'joint_controls':{'ok':{'unavailable':0,'mc95':[0,.01]}}}
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'contradicts'):
                evaluate(Path(tmp)/'missing-study.json',self.current_test_plan(tmp),[path])

    def test_student_t_reference_quantiles_and_family_width(self):
        for df,ref in [(1,12.706204736),(2,4.302652730),(9,2.262157163),(23,2.068657610)]:
            self.assertAlmostEqual(t_critical(df,.05),ref,places=7)
        matrix=[[(10,1,10*(1+.1*r+.02*t),1) for t in range(4)] for r in range(3)]
        one=summarize(matrix,'ratio');family=summarize(matrix,'ratio',.005)
        self.assertEqual(one['point_estimate'],family['point_estimate'])
        self.assertLess(family['headline_ci95'][0],one['headline_ci95'][0])
        self.assertGreater(family['headline_ci95'][1],one['headline_ci95'][1])
        self.assertEqual(interaction(matrix,matrix,'ratio')['headline_ci95'],[0,0])

    def test_grading_runs_in_disposable_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp);(original/'test_subject.py').write_text('assert True')
            contract=freeze_verifiers({},original)
            seen=[]
            def evaluator(pred,workspace):
                seen.append(workspace)
                self.assertNotEqual(workspace,original)
                (workspace/'grader-output.txt').write_text('temporary')
                return True,'ok'
            self.assertEqual(guarded_success({},original,contract,evaluator),(True,'ok'))
            self.assertFalse((original/'grader-output.txt').exists())
            self.assertFalse(seen[0].exists())
            (original/'conftest.py').write_text('skip every test')
            self.assertFalse(guarded_success({},original,contract,evaluator)[0])

    def test_analysis_family_rejects_cycles_and_duplicate_ids(self):
        plan=json.loads((ROOT/'bench/aci/studies/prelive-v1/analysis-plan.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan.json'
            plan['hypotheses'][0]['requires']=[plan['hypotheses'][1]['id']]
            plan['hypotheses'][1]['requires']=[plan['hypotheses'][0]['id']]
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError,'cyclic'):read_plan(path)
            plan['hypotheses'][1]['id']=plan['hypotheses'][0]['id']
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError,'duplicate'):read_plan(path)

    def test_interrupted_recovery_cannot_invent_complete_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run.json'
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                with patch.object(h,'run_agent_loop',side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):h.main(args)
                with patch.object(h,'run_agent_loop',side_effect=recovery.RecoveryTests.row):
                    self.assertEqual(h.main([*args,'--resume-paused']),0)
            payload=json.loads(out.read_text(encoding='utf-8'));row=payload['rows'][0]
            self.assertTrue(payload['partial']);self.assertIsNone(row['success'])
            self.assertTrue(row['raw_success']);self.assertFalse(row['usage_complete'])
            self.assertEqual(row_class(row,80),'endpoint_failure')

    @unittest.skipUnless(os.name=='nt','Windows handle ownership')
    def test_managed_commands_do_not_leak_one_handle_per_call(self):
        k32=ctypes.WinDLL('kernel32',use_last_error=True)
        k32.GetCurrentProcess.restype=ctypes.c_void_p
        k32.GetProcessHandleCount.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        def count():
            gc.collect();value=ctypes.c_ulong()
            self.assertTrue(k32.GetProcessHandleCount(k32.GetCurrentProcess(),ctypes.byref(value)))
            return value.value
        before=count()
        for _ in range(20):self.assertEqual(h.run_bounded([sys.executable,'-c','pass'],timeout=5)[0],0)
        self.assertLessEqual(count()-before,3)


if __name__=='__main__':unittest.main()
