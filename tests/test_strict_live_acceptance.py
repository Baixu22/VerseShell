"""TF-0137: offline acceptance consumers; no model requests or historical writes."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'bench/aci/runners')]
import live_agent_loop as live
import live_uncertainty as uncertainty
from merge_live_runs import refresh_summaries


def fixture(n=10):
    rows = []
    for task in range(n):
        for condition in ('raw_shell', 'verseshell_aci'):
            rows.append(dict(task_id=str(task), condition=condition, model='offline', seed=42,
                             run_index=0, prompt_variant='baseline', success=True, success_reason='control',
                             tool_calls=10 if condition == 'raw_shell' else 1,
                             observation_tokens=100 if condition == 'raw_shell' else 10,
                             turns=1, elapsed_ms=1, trajectory=[], llm_prompt_tokens=10,
                             llm_completion_tokens=10, usage_complete=True))
    return dict(mode='live', rows=rows, live_config={'max_turns': 20})


class StrictAcceptanceTests(unittest.TestCase):
    def test_descriptive_advantage_is_not_acceptance(self):
        c = live.compare_a_vs_d(fixture()['rows'])['comparisons'][0]
        self.assertFalse(c['meets_acceptance'])
        self.assertTrue(c['descriptive_advantage'])
        self.assertFalse(c['claimable'])
        self.assertIn('complete_repeated_study_not_evaluated', c['policy_blocked_reasons'])
        self.assertIn('frozen_family_inference_not_evaluated', c['policy_blocked_reasons'])

    def test_report_recomputes_stale_pass(self):
        p = fixture()
        p['comparison'] = {'comparisons': [{'meets_acceptance': True}]}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'report.md'
            live.write_report(p, target)
            text = target.read_text(encoding='utf-8')
        self.assertNotIn('**PASS** (ACI advantage', text)
        self.assertIn('NOT CLAIMABLE', text)
        self.assertIn('frozen_family_inference_not_evaluated', text)

    def test_exclusion_boundary_not_rounded(self):
        for count, eligible in ((1, True), (2, False)):
            p = fixture()
            for r in p['rows'][:count * 2:2]:
                r['turns'] = 20
            c = uncertainty.comparison_eligibility(p['rows'], 'raw_shell', 20)
            self.assertEqual(c['row_policy_eligible'], eligible)
            self.assertEqual('exclusion_rate_above_10pct' in c['policy_blocked_reasons'], not eligible)

    def test_cap_usage_unknown_and_partial_reasons_are_preserved(self):
        p = fixture()
        p['partial'] = True
        p['rows'][0]['success'] = None
        p['rows'][0]['usage_complete'] = False
        for r in p['rows'][:4:2]:
            r['turns'] = 20
        refresh_summaries(p)
        reasons = p['comparison']['comparisons'][0]['policy_blocked_reasons']
        for expected in ('partial_artifact', 'unknown_scoring_rows', 'incomplete_usage_rows',
                         'exclusion_rate_above_10pct'):
            self.assertIn(expected, reasons)

    def test_missing_usage_cannot_be_saved_by_complete_label(self):
        p = fixture()
        del p['rows'][0]['llm_prompt_tokens']
        c = uncertainty.comparison_eligibility(p['rows'], 'raw_shell', 20)
        self.assertFalse(c['data_eligible'])
        self.assertEqual(c['incomplete_usage_rows'], 1)

    def test_synthetic_and_mixed_variants_are_not_promoted(self):
        p = fixture()
        more = copy.deepcopy(p['rows'])
        for r in more:
            r['prompt_variant'] = 'compact_all'
        p['rows'] += more
        p['synthetic_test_only'] = True
        refresh_summaries(p)
        self.assertFalse(p['comparison']['claimable'])
        for block in p['comparison']['by_prompt_variant'].values():
            c = block['comparisons'][0]
            self.assertFalse(c['meets_acceptance'])
            self.assertIn('synthetic_test_only', c['policy_blocked_reasons'])

    def test_missing_or_duplicate_pairs_block_data_eligibility(self):
        for change in ('missing', 'duplicate'):
            p = fixture()
            if change == 'missing': p['rows'].pop()
            else: p['rows'].append(copy.deepcopy(p['rows'][0]))
            c = uncertainty.comparison_eligibility(p['rows'], 'raw_shell', 20)
            self.assertFalse(c['data_eligible'])
            self.assertIn('incomplete_or_duplicate_pairs', c['policy_blocked_reasons'])

    def test_unknown_scores_are_not_published_as_zero_in_any_variant(self):
        p = fixture()
        more = copy.deepcopy(p['rows'])
        for r in more: r.update(prompt_variant='compact_all', success=None)
        p['rows'] += more
        p['partial'] = True
        refresh_summaries(p)
        block = p['comparison']['by_prompt_variant']['compact_all']
        self.assertIsNone(block['comparisons'][0]['success_rate_A'])
        self.assertTrue(all(r['success_rate'] is None for r in
                            p['aggregate']['by_prompt_variant']['compact_all']['aggregates']))

    def test_empty_comparison_fails_closed(self):
        c = live.compare_a_vs_d([])
        self.assertFalse(c['claimable'])
        self.assertIn('no_comparable_arms', c['policy_blocked_reasons'])

    def test_score_cli_rejects_legacy_pass_but_preserves_mock_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'results.json'
            for mode, code in [('live', 1), ('unknown', 1), ('mock', 0)]:
                p = fixture()
                p['mode'] = mode
                p['comparison'] = {'comparisons': [{'meets_acceptance': True}]}
                target.write_text(json.dumps(p), encoding='utf-8')
                result = subprocess.run([sys.executable, str(ROOT / 'bench/aci/scorers/score.py'),
                                         str(target), '--require-accept'], capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                if mode == 'mock': self.assertIn('mock regression only', result.stdout)
                else: self.assertIn('NOT CLAIMABLE', result.stderr)

    def test_product_gate_detects_legacy_affirmative(self):
        import claim_gate
        p = fixture()
        p['comparison'] = {'comparisons': [{'meets_acceptance': True}]}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'results.json'
            target.write_text(json.dumps(p), encoding='utf-8')
            c = claim_gate.live_run_composition(target)
        self.assertEqual(len(c['affirmative_collection_verdicts']), 1)


class StudyVerdictTests(unittest.TestCase):
    """Unit controls stub calibrated inference; they are NOT real study evidence."""
    def evaluate(self, mutation=None):
        import hashlib
        import study_inference as study
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp)/'plan.json'
            plan_path.write_text('{}', encoding='utf-8')
            digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            plan = dict(alpha=.05, minimum_tasks=30, minimum_seeds=5, minimum_complete_runs=3,
                        method='crossed_axis_t_union/v1', hypotheses=[dict(
                            id='a', baseline='raw_shell', metric='endpoint_total_tokens_ratio',
                            kind='variant', variant='baseline', rule='upper_below', threshold=1)])
            # Use an actual supported metric name while stubbing its numerical matrix.
            plan['hypotheses'][0]['metric'] = next(iter(study.METRICS))
            runs = [dict(rows={i:r for i,r in enumerate(fixture(30)['rows'])}, partial=False,
                         config={'max_turns':20, 'analysis_plan_sha256':digest}) for _ in range(3)]
            data = dict(tasks=list(range(30)), seeds=list(range(5)), runs=runs, sources=[])
            if mutation: mutation(data, plan)
            calibration = dict(calibration_approved=True,
                configuration={'method':'axis_t', 'repetitions':1000, 'runs':3},
                source_sha256={'crossed_inference.py': hashlib.sha256((ROOT/'tools/crossed_inference.py').read_bytes()).hexdigest()},
                scenarios={'control': {'unavailable':0, 'rejection_fraction_ci95_mc':[0,.04]}},
                joint_controls={'control': {'unavailable':0, 'mc95':[0,.04]}})
            calibration_path=Path(tmp)/'calibration.json'
            calibration_path.write_text(json.dumps(calibration), encoding='utf-8')
            with patch.object(study, 'read_plan', return_value=plan),                  patch.object(study, 'load_study', return_value=data),                  patch.object(study, 'metric_cells', return_value=[]),                  patch.object(study, 'axis_summary', return_value={
                     'available':True, 'headline_ci95':[.1,.3], 'point_estimate':.2}):
                return study.evaluate('stubbed-manifest', plan_path, [calibration_path])

    def test_positive_calibrated_evaluator_is_not_blanket_false(self):
        self.assertTrue(self.evaluate()['verdicts']['a']['claimable'])

    def test_shared_missing_usage_unknown_and_partial_blocks_formal_path(self):
        controls = [('usage_complete', False, 'incomplete_usage_rows'),
                    ('success', None, 'unknown_scoring_rows')]
        for field, value, reason in controls:
            result = self.evaluate(lambda d,p: d['runs'][0]['rows'][0].update({field:value}))
            self.assertFalse(result['verdicts']['a']['claimable'])
            self.assertIn(reason, result['verdicts']['a']['policy_blocked_reasons'])
        result = self.evaluate(lambda d,p: d['runs'][0].update(partial=True))
        self.assertFalse(result['verdicts']['a']['claimable'])
        self.assertIn('partial_artifact', result['verdicts']['a']['policy_blocked_reasons'])

    def test_unrepeated_or_unfrozen_study_is_rejected(self):
        for mutation, reason in (
            (lambda d,p: d['runs'].pop(), 'sample-size floors'),
            (lambda d,p: d['runs'][0]['config'].update(analysis_plan_sha256='old'), 'not frozen')):
            with self.assertRaisesRegex(ValueError, reason): self.evaluate(mutation)

    def test_family_correction_uses_the_entire_frozen_family(self):
        result = self.evaluate(lambda d,p: p['hypotheses'].append(
            dict(p['hypotheses'][0], id='b')))
        self.assertEqual(result['family_size'], 2)
        self.assertEqual(result['per_hypothesis_alpha'], .025)

    def test_failed_family_interval_cannot_pass(self):
        result = self.evaluate(lambda d,p: p['hypotheses'][0].update(threshold=.2))
        self.assertFalse(result['verdicts']['a']['claimable'])
        self.assertIn('family_interval_not_passed:analysable',
                      result['verdicts']['a']['policy_blocked_reasons'])


if __name__ == '__main__': unittest.main()
