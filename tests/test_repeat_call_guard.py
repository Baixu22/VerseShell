"""Offline, opt-in repeat budgets: all conditions share the same stopping rule."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import live_agent_loop as h
import live_identity as identity
import live_uncertainty as policy
import final_workspace_audit as audit
from live_journal import ObservationStore
import test_live_preflight as preflight
import test_live_recovery as recovery
import test_live_task_selection as selection
import test_repeated_run_uncertainty as repeated_tests


class RepeatCallGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.sequence = 0

    @staticmethod
    def call(condition='raw_shell', *, value='same', name='run_command'):
        args = {'argv': ['echo', value]} if condition == 'verseshell_aci' else {'command': 'echo '+value}
        if name == 'task_complete':args = {'success': True, 'summary': 'done'}
        return {'id': 'call', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}

    def trial(self, batches, *, condition='raw_shell', variant='baseline', limit=3,
              outputs=None, answer='ok', reference=False, module=h, persistent=True):
        self.sequence += 1
        base = self.root/str(self.sequence); base.mkdir()
        workspace = base/'work'; workspace.mkdir(); (workspace/'answer.txt').write_text(answer)
        source = base/'frozen'; source.mkdir()
        if reference:
            marker = b"HEADER = 'Bearer public-repeat-control'\n"
            (workspace/'test_check.py').write_bytes(marker); (source/'test_check.py').write_bytes(marker)
        task = {'id': 'repeat-control', 'workspace_fixture': 'offline', 'prompt': 'offline control',
                'success': {'type': 'file_equals', 'path': 'answer.txt', 'equals': 'ok'}}
        messages = []; executed = []; emitted = iter(batches); output = iter(outputs or ['same']*100)
        def model(*args, **kwargs):
            messages.append(copy.deepcopy(args[0] if args else kwargs['messages']))
            self.last_tools = copy.deepcopy(args[1] if len(args)>1 else kwargs['tools'])
            batch = copy.deepcopy(next(emitted))
            for index, call in enumerate(batch):call['id'] = f'call-{len(messages)}-{index}'
            return {'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
                    'choices': [{'finish_reason': 'tool_calls', 'message': {'content': '', 'tool_calls': batch}}]}
        def shell(*args, **kwargs):executed.append(args); return next(output)
        def aci(*args, **kwargs):executed.append(args); return {'ok': True, 'data': {'exit_code': 1, 'stdout': next(output)}}
        settings = {} if limit is None else {'repeat_call_limit': limit}
        with patch.object(module, 'prepare_workspace', return_value=workspace), \
             patch.object(module, 'chat_completion', side_effect=model), \
             patch.object(module, 'execute_shell_cmd', side_effect=shell), \
             patch.object(module, 'execute_aci_op', side_effect=aci), contextlib.redirect_stdout(io.StringIO()):
            row = module.run_agent_loop(task, condition, model='offline', api_key='offline-runtime-secret',
                  base_url='http://offline.invalid', max_turns=8, prompt_variant=variant, cell_id='cell',
                  observation_store=ObservationStore(base/'observations') if persistent else None, **settings)
        return row, messages, executed, base, task, source

    def test_same_limit_for_three_conditions_and_two_variants(self):
        notices = []
        for condition in ('raw_shell', 'raw_shell_coached', 'verseshell_aci'):
            for variant in ('baseline', 'compact_all'):
                with self.subTest(condition=condition, variant=variant):
                    call = self.call(condition)
                    row, messages, executed, _, _, _ = self.trial([[call]]*5, condition=condition, variant=variant)
                    self.assertEqual(row['stop_reason'], 'repeat_call_limit')
                    self.assertEqual((len(messages), len(executed), row['tool_calls']), (3, 3, 3))
                    self.assertTrue(row['success'])  # Independent scoring, not the stopping policy.
                    self.assertFalse(row['agent_declared_success'])
                    self.assertEqual(row['repeat_call_limit'], 3)
                    self.assertEqual(row['trajectory'][-1]['identical_call_run'], 3)
                    self.assertIn('observation', row['trajectory'][-1])
                    notices.append(next(s for s in messages[0][0]['content'].splitlines() if s.startswith('REPEAT CALL BUDGET:')))
        self.assertEqual(len(set(notices)), 1)

    def test_default_off_keeps_requests_and_tools_unchanged(self):
        call = self.call(); done = self.call(name='task_complete'); batches = [[call]]*5+[[done]]
        baseline, original, _, _, _, _ = self.trial(batches, limit=None)
        original_tools = copy.deepcopy(self.last_tools)
        disabled, current, executed, _, _, _ = self.trial(batches, limit=0)
        self.assertEqual(disabled['stop_reason'], 'task_complete')
        self.assertEqual(len(executed), 5)
        self.assertEqual(current, original)
        self.assertEqual(self.last_tools, original_tools)
        self.assertNotIn('REPEAT CALL BUDGET:', current[0][0]['content'])

    def test_argument_observation_and_operation_changes_reset_counter(self):
        call = self.call(); changed = self.call(value='different'); done = self.call(name='task_complete')
        scenarios = [([[call], [call], [changed], [call], [call], [done]], None),
                     ([[call]]*5+[[done]], ['same', 'same', 'different', 'same', 'same']),
                     ([[call], [call], [self.call(name='unknown')], [call], [call], [done]], None)]
        for batches, outputs in scenarios:
            with self.subTest(batches=batches, outputs=outputs):
                row, messages, _, _, _, _ = self.trial(batches, outputs=outputs)
                self.assertEqual(row['stop_reason'], 'task_complete')
                self.assertEqual(len(messages), 6)

    def test_json_key_order_is_not_progress(self):
        first = self.call(); first['function']['arguments'] = '{"command":"same","extra":1}'
        second = copy.deepcopy(first); second['function']['arguments'] = '{"extra":1,"command":"same"}'
        row, _, executed, _, _, _ = self.trial([[first], [second], [first], [second]])
        self.assertEqual(row['stop_reason'], 'repeat_call_limit'); self.assertEqual(len(executed), 3)

    def test_stop_inside_batch_does_not_execute_remaining_tools(self):
        call = self.call(); done = self.call(name='task_complete')
        row, messages, executed, _, _, _ = self.trial([[call]*4+[done]])
        self.assertEqual(row['stop_reason'], 'repeat_call_limit')
        self.assertEqual((len(messages), len(executed)), (1, 3))
        self.assertEqual(row['turn_diagnostics'][-1]['tool_calls_skipped_by_repeat_limit'], 2)
        self.assertFalse(row['agent_declared_success'])

    def test_task_complete_keeps_immediate_stop_and_independent_failure(self):
        done = self.call(name='task_complete')
        row, messages, executed, _, _, _ = self.trial([[done, self.call()]], answer='wrong')
        self.assertEqual(row['stop_reason'], 'task_complete')
        self.assertEqual((len(messages), len(executed)), (1, 0))
        self.assertTrue(row['agent_declared_success']); self.assertFalse(row['success'])

    def test_stopped_row_preserves_v2_snapshot_and_explicit_source_requirement(self):
        row, _, _, base, task, source = self.trial([[self.call()]]*5, reference=True)
        self.assertEqual(row['final_workspace']['state'], 'requires_verifier_source')
        self.assertIsNone(audit.review_row(row, base, task=task, rescore=True)['independent_success'])
        checked = audit.review_row(row, base, task=task, rescore=True, verifier_source=source)
        self.assertTrue(checked['independent_success']); self.assertTrue(checked['matches_recorded'])
        self.assertEqual(policy.row_class(row, 8), 'cap_truncated')
        report = policy.row_policy([row], ['raw_shell'], 8)
        self.assertEqual(report['per_arm']['raw_shell']['success_intention_to_treat'], 0)

    def test_repeat_fingerprint_handles_json_surrogate_without_new_harness_error(self):
        call = self.call(value='\ud800')
        row, _, executed, _, _, _ = self.trial([[call]]*5, persistent=False)
        self.assertEqual(row['stop_reason'], 'repeat_call_limit')
        self.assertEqual(len(executed), 3)
        self.assertIsNone(row['harness_fault'])

    def test_invalid_limit_rejected_before_workspace_or_endpoint(self):
        for value in (-1, 1, True, '3', None):
            with self.subTest(value=value), patch.object(h, 'prepare_workspace') as prepare, patch.object(h, 'chat_completion') as model:
                with self.assertRaises(ValueError):
                    h.run_agent_loop({}, 'raw_shell', model='offline', api_key='offline', base_url='http://offline.invalid', repeat_call_limit=value)
                prepare.assert_not_called(); model.assert_not_called()


class RepeatCallIdentityTests(unittest.TestCase):
    def test_identity_requires_same_policy_in_config_and_every_row(self):
        original = preflight.payload(); identity.validate_run(original)
        enabled = copy.deepcopy(original)
        for location in (enabled['run_identity'], enabled['live_config'], *enabled['rows']):location['repeat_call_limit'] = 3
        identity.validate_run(enabled)
        for place in ('live_config', 'row'):
            for invalid in (None, False, -1, 1, 0, 4):
                candidate = copy.deepcopy(enabled)
                target = candidate['rows'][0] if place == 'row' else candidate[place]
                if invalid is None:target.pop('repeat_call_limit')
                else:target['repeat_call_limit'] = invalid
                with self.subTest(place=place, invalid=invalid), self.assertRaisesRegex(ValueError, 'repeat'):
                    identity.validate_run(candidate)

    def test_merge_rejects_different_limits_and_keeps_previous_output(self):
        first, second = preflight.payload(42), preflight.payload(43)
        for data, limit in ((first, 3), (second, 4)):
            for location in (data['run_identity'], data['live_config'], *data['rows']):location['repeat_call_limit'] = limit
        code, output = preflight.PreflightTests().merge([first, second])
        self.assertEqual(code, 2); self.assertEqual(output, 'sentinel')

    def test_controller_freezes_dispatches_and_refuses_changed_limit(self):
        fixture = selection.TaskSelectionTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups); self.addCleanup(fixture.tearDown)
        self.assertEqual(fixture.invoke('--tasks', fixture.ids[0], '--repeat-call-limit', '3'), 0, fixture.last_output)
        self.assertEqual(json.loads(fixture.freeze.read_text())['repeat_call_limit'], 3)
        commands = [call.args[1] for call in fixture.dispatch.call_args_list if str(selection.round.RUNNER) in call.args[1]]
        self.assertTrue(commands)
        for cmd in commands:self.assertEqual(cmd[cmd.index('--repeat-call-limit')+1], '3')
        self.assertEqual(fixture.invoke('--tasks', fixture.ids[0], '--repeat-call-limit', '4'), 2)
        fixture.dispatch.assert_not_called()

    def test_collector_records_policy_and_rejects_resume_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)/'run.json'
            args = ['--model','offline','--api-key','offline','--tasks','rust_fix_compile_error',
                    '--conditions','raw_shell','--seed','42','--out',str(out),'--repeat-call-limit','3']
            received = []
            def fake(task, condition, **kwargs):
                received.append(kwargs['repeat_call_limit'])
                return {**recovery.RecoveryTests.row(task, condition), 'repeat_call_limit': kwargs['repeat_call_limit']}
            helper = recovery.RecoveryTests()
            self.assertEqual(helper.invoke(args, fake), (0, 1), helper.last_output)
            data = json.loads(out.read_text())
            self.assertEqual(received, [3])
            self.assertEqual(data['run_identity']['repeat_call_limit'], 3)
            self.assertEqual(data['live_config']['repeat_call_limit'], 3)
            self.assertEqual(data['rows'][0]['repeat_call_limit'], 3)
            before = out.read_bytes()
            self.assertEqual(helper.invoke(args[:-1]+['4'], fake), (2, 0))
            self.assertEqual(out.read_bytes(), before)

    def test_legacy_and_new_policy_cannot_mix_in_repeated_study(self):
        fixture = repeated_tests.RepeatedRunTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        def enabled(data):
            data['live_config']['repeat_call_limit'] = 3
            for row in data['rows']:row['repeat_call_limit'] = 3
        fixture.alter(1, enabled)
        with self.assertRaisesRegex(ValueError, 'configuration'):
            repeated_tests.repeated.load_study(fixture.manifest)
        fixture.alter(0, enabled); fixture.alter(2, enabled)
        self.assertEqual(len(repeated_tests.repeated.load_study(fixture.manifest)['runs']), 3)
        fixture.alter(0, lambda data: data['rows'][0].update(repeat_call_limit=0))
        with self.assertRaisesRegex(ValueError, 'repeat'):
            repeated_tests.repeated.load_study(fixture.manifest)

    def test_disabled_policy_cannot_claim_a_repeat_termination(self):
        data = preflight.payload(); data['rows'][0]['stop_reason'] = 'repeat_call_limit'
        with self.assertRaisesRegex(ValueError, 'repeat'):identity.validate_run(data)
        rows = [{'condition': condition, 'success': True, 'turns': 1}
                for condition in ('raw_shell', 'verseshell_aci') for _ in range(20)]
        rows[0]['stop_reason'] = 'repeat_call_limit'
        with self.subTest(layer='row_policy'):
            result = policy.row_policy(rows, ['raw_shell','verseshell_aci'], 8, [('raw_shell','verseshell_aci')])
            self.assertIn('repeat_call_policy_mismatch', result['comparisons']['verseshell_aci_vs_raw_shell']['policy_blocked_reasons'])
        fixture = repeated_tests.RepeatedRunTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.alter(0, lambda data: data['rows'][0].update(stop_reason='repeat_call_limit'))
        with self.subTest(layer='repeated_study'), self.assertRaisesRegex(ValueError, 'repeat'):
            repeated_tests.repeated.load_study(fixture.manifest)

    def test_every_policy_consumer_rejects_mixed_or_invalid_row_limits(self):
        rows = [{'condition': c, 'success': True, 'turns': 1} for c in ('raw_shell','verseshell_aci')]
        for invalid in (3, True, 1, -1, None, []):
            with self.subTest(value=invalid):
                mixed = copy.deepcopy(rows); mixed[1]['repeat_call_limit'] = invalid
                result = policy.row_policy(mixed, ['raw_shell','verseshell_aci'], 8, [('raw_shell','verseshell_aci')])
                verdict = result['comparisons']['verseshell_aci_vs_raw_shell']
                self.assertFalse(verdict['claimable'])
                self.assertIn('repeat_call_policy_mismatch', verdict['policy_blocked_reasons'])
        limited = {**rows[0], 'stop_reason': 'repeat_call_limit', 'repeat_call_limit': 3}
        self.assertEqual(policy.row_class(limited, 8), 'cap_truncated')
        self.assertEqual(policy.row_class({**limited, 'api_error': True}, 8), 'endpoint_failure')


if __name__ == '__main__':unittest.main()
