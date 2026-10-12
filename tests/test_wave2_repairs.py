"""Verifier integrity and synchronized interaction regressions, no live calls."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'bench/aci/runners'),str(ROOT/'tools')]
from grading_contract import freeze_verifiers, guarded_success
import live_agent_loop as h
import repeated_run_uncertainty as repeated
import task_admissibility as admission
from calibrate_repeated_intervals import calibrate


class WaveTwoTests(unittest.TestCase):
    def test_preserving_marker_does_not_preserve_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'test_subject.py';p.write_text('# expected marker\nassert False\n')
            frozen=freeze_verifiers({},root)
            p.write_text('# expected marker\nassert True\n')
            with patch.object(h,'check_success',return_value=(True,'fake')) as evaluator:
                self.assertFalse(guarded_success({},root,frozen,evaluator)[0])
                evaluator.assert_not_called()
            p.unlink()
            self.assertFalse(guarded_success({},root,frozen,h.check_success)[0])

    def test_scoring_side_effect_is_detected_without_modifying_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);test=root/'check.mjs';test.write_text('assert(result===1)')
            subject=root/'subject.js';subject.write_text('export const result=1;')
            predicate={'type':'command_exit_0','argv':['node','check.mjs']}
            frozen=freeze_verifiers(predicate,root)
            self.assertEqual(set(frozen),{'check.mjs'})
            def evaluator(*args):test.write_text('process.exit(0)');return True,'fake'
            self.assertFalse(guarded_success(predicate,root,frozen,evaluator)[0])
            self.assertEqual(subject.read_text(),'export const result=1;')

    def test_live_loop_uses_contract_frozen_before_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);test=root/'test_subject.py';test.write_text('assert False')
            task={'id':'offline','workspace_fixture':'unused','prompt':'repair subject','success':{}}
            def response(*args,**kwargs):
                test.write_text('assert True')
                return {'usage':{'prompt_tokens':1,'completion_tokens':1},
                        'choices':[{'finish_reason':'stop','message':{'content':'done'}}]}
            with patch.object(h,'prepare_workspace',return_value=root),patch.object(h,'chat_completion',side_effect=response),patch.object(h,'check_success',return_value=(True,'fake')):
                row=h.run_agent_loop(task,'raw_shell',model='offline',api_key='test',base_url='invalid://offline')
            self.assertFalse(row['success'])
            self.assertIn('protected verifier',row['success_reason'])
            self.assertIn('test_subject.py',row['protected_verifiers'])

    def test_admission_uses_pristine_contract_before_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'fixture').mkdir();(root/'GOLDEN').mkdir()
            (root/'fixture/test_x.py').write_text('assert False')
            (root/'GOLDEN/test_x.py').write_text('assert True')
            (root/'task.json').write_text(json.dumps({'success':{'type':'command_exit_0','argv':['python','test_x.py']}}))
            with patch.object(admission,'verdict',return_value=(True,'fake')) as evaluator:
                result=admission.run_predicate_on(root,[root/'GOLDEN'],tamper=False)
            self.assertFalse(result['verdict'])
            evaluator.assert_not_called()

    def test_synchronized_draw_cancels_common_noise_exactly(self):
        a=[[(10,1,10*(r+t+1),1) for t in range(4)] for r in range(3)]
        result=repeated.interaction_interval(a,a,'ratio',200,42)
        self.assertEqual(result['headline_ci95'],[0,0])
        b=[[(10,1,c[2]+5,1) for c in row] for row in a]
        result=repeated.interaction_interval(a,b,'ratio',200,42)
        self.assertAlmostEqual(result['point_estimate'],.5)
        self.assertAlmostEqual(result['headline_ci95'][0],.5)
        self.assertFalse(result['claimable'])

    def test_complete_six_cell_interaction_and_missing_cell_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tasks=['a','b'];conditions=['raw_shell','raw_shell_coached','verseshell_aci']
            (root/'tasks.json').write_text(json.dumps({'task_set_version':'test','tasks':tasks}))
            entries=[]
            for run in range(3):
                rows=[]
                for task in tasks:
                    for variant in ('baseline','compact_all'):
                        for condition in conditions:
                            value=5 if variant=='compact_all' and condition=='verseshell_aci' else 10
                            rows.append(dict(task_id=task,condition=condition,prompt_variant=variant,model='offline',
                                             seed=42,run_index=0,success=True,turns=1,tool_calls=value,
                                             observation_tokens=value,llm_prompt_tokens=value,llm_completion_tokens=value))
                payload={'mode':'live','synthetic_test_only':True,'generated_at':str(run),'task_set_version':'test','git_rev':'test',
                         'evidence':{'fingerprint':'test'},'rows':rows,
                         'live_config':dict(model='offline',api_base='invalid://offline',caps='test',max_turns=80,max_tokens=16384,
                                            temperature=0,exclude_tools=[],prompt_variants=['baseline','compact_all'],schedule_sha256='test')}
                (root/f'{run}.json').write_text(json.dumps(payload))
                entries.append({'run_id':str(run),'artifact':f'{run}.json'})
            spec={'task_manifest':'tasks.json','seeds':[42],'conditions':conditions,'runs':entries}
            path=root/'study.json';path.write_text(json.dumps(spec))
            report=repeated.analyse_interaction(path,50,42)
            for baseline in ('raw_shell','raw_shell_coached'):
                metric=report['comparisons'][baseline]['views']['analysable']['metrics']['usage_token_ratio']
                self.assertEqual(metric['headline_ci95'],[-.5,-.5])
            self.assertFalse(report['claimable'])
            bad=json.loads((root/'0.json').read_text());bad['rows'].pop();(root/'0.json').write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'variant grid'):repeated.analyse_interaction(path,50)

    def test_calibration_is_reproducible_and_never_approves_claims(self):
        result=calibrate(repetitions=3,draws=20,tasks=4,runs=3,seed=9)
        self.assertEqual(result,calibrate(repetitions=3,draws=20,tasks=4,runs=3,seed=9))
        self.assertEqual(result['controls']['identical_variant_interaction']['headline_ci95'],[0,0])
        self.assertFalse(result['controls']['zero_success_denominator']['available'])
        self.assertFalse(result['calibration_approved'])


if __name__=='__main__':unittest.main()
