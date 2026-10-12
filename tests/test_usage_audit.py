"""Offline TF-0135 tests: unknown attempts never become zero-cost or valid pairs."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import live_agent_loop as harness
import live_uncertainty as uncertainty
import usage_audit
import three_arm_report
import acceptance_power
import repeated_run_uncertainty


def row(condition='raw_shell', task='first', retry=False):
    attempts = [{'attempt': 1, 'attempt_id': 'returned', 'status': 200}]
    if retry:
        attempts.insert(0, {'attempt': 0, 'attempt_id': 'unknown', 'status': None, 'error': 'no response'})
    return {'cell_id': task+condition, 'task_id': task, 'model': 'offline', 'condition': condition,
            'prompt_variant': 'baseline', 'seed': 42, 'run_index': 0, 'success': True,
            'turns': 1, 'usage_complete': True, 'llm_prompt_tokens': 10, 'llm_completion_tokens': 2,
            'observation_tokens': 5, 'tool_calls': 1,
            'turn_diagnostics': [{'turn': 1, 'prompt_tokens': 10, 'completion_tokens': 2,
                                  'transport_attempts': attempts}]}


class UsageTests(unittest.TestCase):
    def test_stale_complete_flag_cannot_hide_unknown_retry(self):
        value = row(retry=True)
        self.assertFalse(uncertainty.valid_usage(value))
        self.assertTrue(math.isnan(uncertainty.reported_usage(value)))
        result = usage_audit.audit_row(value)
        self.assertEqual(result['received_total_tokens'], 12)
        self.assertEqual(result['unknown_usage_attempts'], 1)
        self.assertEqual(result['turns_with_unknown_usage'], 1)
        self.assertIsNone(result['attempts'][0]['usage']['prompt_tokens'])
        self.assertEqual(result['attempts'][1]['usage']['prompt_tokens'], 10)
        self.assertTrue(result['success'])
        self.assertTrue(value['usage_complete'])  # read-only: never repair the input flag

    def test_explicit_zero_is_not_missing_and_unknown_is_not_zero(self):
        zero = {'llm_prompt_tokens': 0, 'llm_completion_tokens': 0, 'usage_complete': True}
        self.assertEqual(uncertainty.reported_usage(zero), 0)
        self.assertEqual(usage_audit.audit_row(zero)['received_total_tokens'], 0)
        missing = usage_audit.audit_row({'success': True})
        self.assertIsNone(missing['received_total_tokens'])
        self.assertFalse(missing['attempt_ledger_complete'])
        self.assertFalse(missing['usage_eligible'])
        partial = usage_audit.audit_row({'turn_diagnostics': [{'turn': 1, 'completion_tokens': 2}]})
        self.assertEqual(partial['received_total_tokens'], 2)
        self.assertFalse(partial['received_fields_complete'])
        self.assertFalse(partial['usage_eligible'])

    def test_fault_recovery_and_contradictory_totals_are_excluded(self):
        changes = [{'measurement_complete': False}, {'recovery_uncertain': True}, {'api_error': True},
                   {'harness_fault': 'failed'}, {'llm_prompt_tokens': 11}, {'turns': 2}]
        for change in changes:
            value = {**row(), **change}
            with self.subTest(change=change):
                self.assertFalse(uncertainty.valid_usage(value))
        for invalid in (None, True, -1, float('nan'), float('inf'), '10'):
            self.assertFalse(uncertainty.valid_usage({**row(), 'llm_prompt_tokens': invalid}))

    def test_prior_received_usage_is_counted_but_cannot_disappear_from_totals(self):
        value = row(retry=True)
        value['turn_diagnostics'][0]['transport_attempts'][0].update(
            usage={'prompt_tokens': 3, 'completion_tokens': 1}, usage_complete=True)
        result = usage_audit.audit_row(value)
        self.assertEqual(result['received_total_tokens'], 16)
        self.assertEqual(result['unknown_usage_attempts'], 0)
        self.assertIn('turn_usage_total_mismatch', result['exclusion_reasons'])
        value.update(llm_prompt_tokens=13, llm_completion_tokens=3)
        self.assertTrue(uncertainty.valid_usage(value))

    def test_null_partial_and_mismatched_attempt_receipts_are_rejected(self):
        for usage in (None, {}, {'prompt_tokens': 10}, {'prompt_tokens': 11, 'completion_tokens': 2}):
            value = row()
            value['turn_diagnostics'][0]['transport_attempts'][0]['usage'] = usage
            self.assertFalse(uncertainty.valid_usage(value))
        value = row()
        value['turn_diagnostics'][0]['request_error'] = 'response not received'
        self.assertFalse(uncertainty.valid_usage(value))

    def test_all_cost_wrappers_report_same_effective_denominator(self):
        rows = [row(c, task, retry=(task=='second' and c=='verseshell_aci'))
                for task in ('first', 'second') for c in ('raw_shell', 'verseshell_aci')]
        pairs = [(uncertainty.reported_usage(rows[i]), uncertainty.reported_usage(rows[i+1])) for i in (0, 2)]
        stats = uncertainty.ratio_bootstrap(pairs, kind='usage', iterations=50)
        power = acceptance_power.bootstrap_ratio(pairs, iterations=50)
        with patch.object(three_arm_report, 'ratio_bootstrap', side_effect=lambda values, **kw: uncertainty.ratio_bootstrap(values, iterations=50, **kw)):
            three = three_arm_report.contrast(rows, 'raw_shell', 80)['all_rows']['usage_token_ratio_D_over_baseline']
        for result in (stats, power, three):
            self.assertEqual((result['candidate_pairs'], result['n_pairs'], result['excluded_nonfinite_pairs']), (2, 1, 1))
        study = {'tasks': ['second'], 'seeds': [42], 'indices': [0], 'runs': [
            {'config': {'max_turns': 80}, 'rows': {('second', r['condition'], 42, 0): r for r in rows[2:]}}]}
        for metric in ('usage_token_ratio', 'usage_mean_of_ratios', 'usage_cost_per_success'):
            with self.assertRaisesRegex(ValueError, 'incomplete endpoint usage'):
                repeated_run_uncertainty.metric_cells(study, 'raw_shell', 'all', metric)

    def test_audit_reports_pair_gaps_without_touching_scoring(self):
        payload = {'rows': [row(), row('verseshell_aci', retry=True), row(task='second')]}
        original = copy.deepcopy(payload)
        result = usage_audit.audit(payload)
        pair = next(p for p in result['pairs'] if p['baseline']=='raw_shell')
        self.assertEqual((pair['matched_pairs'], pair['usage_eligible_pairs'], pair['missing_partner_pairs']), (1, 0, 1))
        self.assertEqual(result['billing']['status'], 'unknown')
        self.assertIsNone(result['billing']['reconciled_billed_tokens'])
        self.assertEqual(payload, original)
        self.assertTrue(all(r['success'] for r in result['rows']))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            usage_audit.audit({'rows': [row(), row()]})

    def test_transport_records_usage_and_unknown_attempt_identity(self):
        class Response(io.BytesIO):
            status = 200
            headers = {'x-request-id': 'server-request'}
        response = {'id': 'response-id', 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}, 'choices': []}
        with patch.object(harness.urllib.request, 'urlopen', side_effect=[urllib.error.URLError('offline'), Response(json.dumps(response).encode())]), \
             patch.object(harness.time, 'sleep'):
            result = harness.chat_completion([], [], model='offline', api_key='not-a-real-key', base_url='http://offline')
        attempts = result['_transport_attempts']
        self.assertEqual(len(attempts), 2)
        self.assertIsNone(attempts[0]['usage'])
        self.assertFalse(attempts[0]['usage_complete'])
        self.assertEqual(attempts[1]['usage'], response['usage'])
        self.assertEqual(attempts[1]['request_id'], 'server-request')
        self.assertEqual(attempts[1]['response_id'], 'response-id')
        self.assertNotEqual(attempts[0]['attempt_id'], attempts[1]['attempt_id'])
        self.assertEqual(attempts[0]['request_body_sha256'], attempts[1]['request_body_sha256'])

    def test_invalid_response_retains_unknown_attempt_without_new_retry(self):
        class Response(io.BytesIO):
            status = 200
            headers = {'x-request-id': 'malformed-response'}
        for body in (b'not-json', b'[]', b'\xff'):
            with patch.object(harness.urllib.request, 'urlopen', return_value=Response(body)) as request:
                with self.assertRaises(RuntimeError) as caught:
                    harness.chat_completion([], [], model='offline', api_key='test', base_url='http://offline')
                self.assertEqual(request.call_count, 1)
                attempt = caught.exception.attempts[0]
                self.assertEqual(attempt['status'], 200)
                self.assertEqual(attempt['request_id'], 'malformed-response')
                self.assertIsNone(attempt['usage'])
                self.assertFalse(attempt['usage_complete'])

    def test_null_usage_does_not_crash_or_change_task_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)/'work'; workspace.mkdir()
            task = {'id': 'offline', 'workspace_fixture': 'offline', 'prompt': 'x', 'success': {}}
            response = {'usage': None, 'choices': [{'finish_reason': 'stop', 'message': {'content': 'done'}}]}
            with patch.object(harness, 'prepare_workspace', return_value=workspace), \
                 patch.object(harness, 'check_success', return_value=(True, 'offline')), \
                 patch.object(harness, 'chat_completion', return_value=response):
                result = harness.run_agent_loop(task, 'raw_shell', model='offline', api_key='test', base_url='http://offline')
            self.assertTrue(result['success'])
            self.assertFalse(result['usage_complete'])
            self.assertIsNone(result['llm_prompt_tokens'])
            self.assertIsNone(result['harness_fault'])

    def test_readonly_cli_rejects_input_directory_and_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); source = base/'source'/'run.json'; source.parent.mkdir()
            source.write_text(json.dumps({'rows': [row(), row('verseshell_aci')]}), encoding='utf-8')
            output = base/'audit.json'
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(usage_audit.main(['--input', str(source), '--out', str(output)]), 0)
                for target in (output, source.parent/'audit.json'):
                    with self.assertRaises(SystemExit) as error:
                        usage_audit.main(['--input', str(source), '--out', str(target)])
                    self.assertEqual(error.exception.code, 2)
            self.assertEqual(json.loads(output.read_text())['summary']['rows'], 2)
            self.assertEqual(len(json.loads(source.read_text())['rows']), 2)


if __name__ == '__main__':
    unittest.main()
