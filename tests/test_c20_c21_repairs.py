"""Offline regressions for the October 5 handoff; no endpoint calls."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bench/aci/runners'))
sys.path.insert(0, str(ROOT / 'tools'))
import live_agent_loop as h
import run_suite
import task_set_audit as audit
import three_arm_report as report
import claim_gate
from live_uncertainty import ratio_bootstrap
from acceptance_power import apply_multiplicity
from task_sets import load_tasks
from grading_contract import freeze_fixture_verifiers


class HandoffRepairs(unittest.TestCase):
    def test_missing_effect_interval_cannot_bypass_multiplicity(self):
        verdicts, summary = apply_multiplicity({
            'cost_per_success_D_cheaper': {'claimable': True},
            'success_paired_can_claim_MDE_0.15': {'claimable': True},
            'token_ratio_level1_D_cheaper': {'claimable': True, 'point': 0.5,
                                           'ci95_lower': 0.4, 'ci95_upper': 0.6, 'threshold': 1.0},
        })
        self.assertFalse(verdicts['cost_per_success_D_cheaper']['claimable'])
        self.assertTrue(verdicts['success_paired_can_claim_MDE_0.15']['claimable'])
        self.assertEqual(summary['families']['live_model']['hypothesis_count'], 2)
        self.assertEqual(verdicts['token_ratio_level1_D_cheaper']['holm_alpha'], 0.025)

    def test_dual_estimators_expose_opposite_directions(self):
        result = ratio_bootstrap([(100, 1), (1, 2)], kind='usage', keys=['a', 'b'], iterations=100)
        self.assertLess(result['point_estimate'], 1)
        self.assertGreater(result['mean_of_ratios']['point_estimate'], 1)
        self.assertEqual(result['mean_of_ratios']['bootstrap_unit'], 'task')
        zero = ratio_bootstrap([(0, 1), (1, 2)], kind='usage', iterations=100)
        self.assertEqual(zero['mean_of_ratios']['excluded_nonpositive_baseline'], 1)

    def test_whitespace_equivalence_does_not_accept_wrong_content(self):
        _, tasks = load_tasks(ROOT / 'bench/aci/tasks', ROOT / 'bench/aci/task_sets/3.1.0.json')
        pred = tasks['windows_batch_capture_diag']['success']
        self.assertEqual(pred['type'], 'file_matches')
        with tempfile.TemporaryDirectory() as tmp:
            for text, expected in [('src/main.rs:12  \r\n', True),
                                   ('\ufeff src\\main.rs:12\t\n', True),
                                   ('other:12', False), ('src/main.rs:123', False),
                                   ('src/main.rs:12\nextra', False),
                                   ('src/main.rs: 12', False)]:
                (Path(tmp) / 'ERR.txt').write_bytes(text.encode('utf-8'))
                for evaluator in (h.check_success, run_suite.check_success):
                    self.assertIs(evaluator(pred, Path(tmp))[0], expected)

    def test_audit_uses_override_and_fails_process_on_bad_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'rows.json'
            source.write_text('{"rows": []}')
            for expected, passed in [(0, True), (1, False)]:
                entry = {'pass': passed, 'pristine': {'pass': False}, 'golden': {'pass': passed}}
                with patch.object(audit, 'fixture_consistency', return_value={'task': entry}) as check, \
                     patch.object(audit, 'predicate_changes', return_value={}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(audit.main(['--with-arm', str(source)]), expected)
                tasks = check.call_args.args[0]
                self.assertEqual(tasks['windows_batch_capture_diag']['success']['type'], 'file_matches')
                self.assertFalse(any('modes' in t for t in tasks.values()))

    def test_compact_all_preserves_schema_and_controls_shared_descriptions(self):
        descriptions = []
        for condition in h.PROMPT_BY_CONDITION:
            before = h.prompt_and_tools(condition, 'baseline')
            after = h.prompt_and_tools(condition, 'compact_all')
            self.assertEqual(before[:2], after[:2])
            def contract(tools):
                return [{**t, 'function': {k: v for k, v in t['function'].items()
                                           if k != 'description'}} for t in tools]
            self.assertEqual(contract(before[2]), contract(after[2]))
            descriptions.append({t['function']['name']: t['function']['description'] for t in after[2]})
        for name in ('run_command', 'task_complete'):
            self.assertEqual(len({d[name] for d in descriptions}), 1)
        self.assertEqual(h.prompt_and_tools('raw_shell', 'compact'), h.prompt_and_tools('raw_shell'))
        with self.assertRaises(ValueError):
            h.prompt_and_tools('raw_shell', 'typo')

    def test_gate_rejects_old_predicate_even_with_pass_label(self):
        manifest, tasks = load_tasks(ROOT / 'bench/aci/tasks', ROOT / 'bench/aci/task_sets/3.1.0.json')
        evidence = {'task_set_version': manifest['task_set_version'],
                    'fixture_consistency': {t: {'pass': True, 'predicate': task['success'],
                                               'protected_verifiers': freeze_fixture_verifiers(task['success'], ROOT/'bench/aci/fixtures'/task['workspace_fixture']),
                                               'pristine': {'pass': False}, 'golden': {'pass': True}}
                                            for t, task in tasks.items()}}
        self.assertTrue(claim_gate.task_set_consistency_claim(evidence)['pass'])
        evidence['fixture_consistency']['windows_batch_capture_diag']['predicate'] = {'type': 'file_contains'}
        self.assertFalse(claim_gate.task_set_consistency_claim(evidence)['pass'])
        del evidence['fixture_consistency']['windows_batch_capture_diag']
        self.assertFalse(claim_gate.task_set_consistency_claim(evidence)['pass'])

    def test_job_success_skips_taskkill_and_failure_uses_bounded_fallback(self):
        for success in (True, False):
            proc, k32 = Mock(pid=123), Mock()
            k32.TerminateJobObject.return_value = success
            with patch.object(h.subprocess, 'run') as kill:
                h._terminate_tree(proc, k32, 1)
            self.assertEqual(kill.call_count, int(not success))
            if not success:
                self.assertLessEqual(kill.call_args.kwargs['timeout'], 2)

    def test_job_handle_closed_and_failed_assignment_blocks_workload(self):
        if h.os.name != 'nt':
            self.skipTest('Windows job assignment')
        for assigned in (True, False):
            proc = Mock(_handle=123, returncode=0)
            proc.communicate.return_value = (b'ok', b'')
            k32 = Mock()
            k32.AssignProcessToJobObject.return_value = assigned
            with patch.object(h.subprocess, 'Popen', return_value=proc), \
                 patch.object(h, '_create_kill_on_close_job', return_value=(k32, 1)):
                if assigned:
                    self.assertEqual(h.run_bounded([sys.executable], timeout=1), (0, b'ok', b'', False))
                else:
                    with self.assertRaisesRegex(OSError, 'assignment failed'):
                        h.run_bounded([sys.executable], timeout=1)
                    proc.kill.assert_called_once()
                    self.assertNotIn('input', proc.communicate.call_args.kwargs)
            k32.CloseHandle.assert_called_once()

    def test_pair_exclusions_include_completion_caps_and_ignore_third_arm(self):
        rows = []
        for task in range(3):
            for cond in ('raw_shell', 'raw_shell_coached', 'verseshell_aci'):
                rows.append(dict(task_id=str(task), seed=42, run_index=0, condition=cond,
                                 success=True, turns=1, observation_tokens=10, tool_calls=1,
                                 llm_prompt_tokens=20, llm_completion_tokens=5))
        rows[0]['turns'] = 80
        rows[4]['completion_truncated_turns'] = 1
        rows[8]['completion_truncated_turns'] = 1
        with patch.object(report, 'ratio_bootstrap', return_value={}):
            for baseline in ('raw_shell', 'raw_shell_coached'):
                result = report.contrast(rows, baseline, 80)
                self.assertEqual(result['cap_excluded_dropped'], 2)
                self.assertEqual(result['cap_excluded']['n_pairs'], 1)


if __name__ == '__main__':
    unittest.main()
