"""Offline round selection contracts; model and process dispatch are forbidden."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'bench/aci/runners')]
import live_round as round
import study_inference


class TaskSelectionTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.ids = [f'task_{i:02d}' for i in range(35)]
        self.task_set = self.root / 'tasks.json'
        self.task_set.write_text('{}')
        self.freeze = self.root / 'study' / 'collection.json'
        stack.enter_context(patch.dict(os.environ, ACI_STORAGE_RESERVES='{}'))
        stack.enter_context(patch.object(round, 'RESULTS', self.root))
        stack.enter_context(patch.object(round, 'load_env', return_value={
            'ACI_BENCH_MODEL': 'offline', 'ACI_BENCH_BASE_URL': 'http://offline.invalid/v1/responses',
            'ACI_BENCH_API_KEY': 'offline-test'}))
        stack.enter_context(patch.object(round, 'load_tasks', return_value=(
            {'tasks': self.ids, 'task_set_version': 'offline-fixture'},
            {tid: {'id': tid} for tid in self.ids})))
        self.dispatch = stack.enter_context(patch.object(round, 'run', return_value=0))
        self.native = stack.enter_context(patch.object(round.harness, 'run_bounded', side_effect=AssertionError('real process forbidden')))
        self.agent = stack.enter_context(patch.object(round.harness, 'run_agent_loop', side_effect=AssertionError('real agent forbidden')))
        self.model = stack.enter_context(patch.object(round.harness, 'chat_completion', side_effect=AssertionError('network forbidden')))
        self.readiness = stack.enter_context(patch.object(round, 'verify_readiness'))
        stack.enter_context(patch.object(study_inference, 'read_plan', return_value={'minimum_tasks': 30, 'minimum_seeds': 5}))
        self.args = ['live_round.py', '--tag', 'study', '--model', 'offline',
                     '--env-file', str(self.root / 'unused.env'), '--task-set', str(self.task_set),
                     '--conditions', 'raw_shell', '--seeds', '42', '--arms', 'with']

    def tearDown(self):
        self.native.assert_not_called()
        self.agent.assert_not_called()
        self.model.assert_not_called()

    def invoke(self, *extra):
        output = io.StringIO()
        self.dispatch.reset_mock()
        with patch.object(sys, 'argv', self.args + list(extra)), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                code = round.main()
            except SystemExit as error:
                code = error.code
        self.last_output = output.getvalue()
        return code

    def assert_runner_tasks(self, selected):
        commands = [call.args[1] for call in self.dispatch.call_args_list if str(round.RUNNER) in call.args[1]]
        self.assertTrue(commands)
        for cmd in commands:
            self.assertNotIn('--full', cmd)
            self.assertIn('--tasks', cmd)
            self.assertEqual(cmd[cmd.index('--tasks') + 1], ','.join(selected))

    def formal_args(self):
        plan = self.root / 'analysis.json'
        plan.write_text('{}')
        return ['--analysis-plan', str(plan), '--preflight', str(self.root / 'readiness.json'),
                '--probe-report', str(self.root / 'probe.json'), '--seeds', '42,43,44,45,46']

    def test_default_freezes_full_manifest_and_passes_explicit_tasks(self):
        self.assertEqual(self.invoke(), 0, self.last_output)
        self.assertEqual(json.loads(self.freeze.read_text())['tasks'], self.ids)
        self.assert_runner_tasks(self.ids)
        self.assertEqual(self.dispatch.call_count, 2)

    def test_subset_order_and_six_treatment_schedule_exclude_other_tasks(self):
        selected = [self.ids[4], self.ids[1]]
        self.assertEqual(self.invoke('--tasks', ','.join(selected), '--conditions',
                                   'raw_shell,raw_shell_coached,verseshell_aci',
                                   '--prompt-variants', 'baseline,compact_all'), 0, self.last_output)
        self.assertEqual(json.loads(self.freeze.read_text())['tasks'], selected)
        schedule = json.loads((self.freeze.parent / 'schedule.json').read_text())
        self.assertEqual(schedule['tasks'], selected)
        self.assertEqual(len(schedule['cells']), 12)
        self.assertEqual({cell[0] for cell in schedule['cells']}, set(selected))
        expected = {(condition, variant) for condition in ('raw_shell', 'raw_shell_coached', 'verseshell_aci')
                    for variant in ('baseline', 'compact_all')}
        for tid in selected:
            self.assertEqual({(cell[1], cell[4]) for cell in schedule['cells'] if cell[0] == tid}, expected)
        self.assert_runner_tasks(selected)

    def test_empty_duplicate_and_unknown_selections_are_rejected(self):
        for value in ('', 'task_00,task_00', 'not_in_manifest'):
            with self.subTest(tasks=value):
                self.assertEqual(self.invoke('--tasks', value), 2)
                self.assertNotIn('unrecognized arguments', self.last_output)
                self.dispatch.assert_not_called()
                self.assertFalse(self.freeze.exists())

    def test_same_selection_reuses_freeze_but_changed_order_or_set_is_rejected(self):
        selected = [self.ids[3], self.ids[0]]
        self.assertEqual(self.invoke('--tasks', ','.join(selected), '--dry-run'), 0, self.last_output)
        original = self.freeze.read_bytes()
        self.assertEqual(self.invoke('--tasks', ','.join(selected), '--dry-run'), 0, self.last_output)
        self.assertEqual(self.freeze.read_bytes(), original)
        self.dispatch.assert_not_called()
        for changed in (list(reversed(selected)), [self.ids[3], self.ids[2]]):
            with self.subTest(changed=changed):
                self.assertEqual(self.invoke('--tasks', ','.join(changed)), 2)
                self.assertEqual(self.freeze.read_bytes(), original)
                self.dispatch.assert_not_called()

    def test_formal_floor_counts_29_selected_not_the_35_task_manifest(self):
        self.assertEqual(self.invoke('--tasks', ','.join(self.ids[:29]), *self.formal_args()), 2)
        self.assertNotIn('unrecognized arguments', self.last_output)
        self.readiness.assert_called_once()
        self.dispatch.assert_not_called()
        self.assertFalse(self.freeze.exists())

    def test_formal_floor_accepts_30_selected_tasks(self):
        selected = self.ids[:30]
        self.assertEqual(self.invoke('--tasks', ','.join(selected), *self.formal_args()), 0, self.last_output)
        self.assertEqual(json.loads(self.freeze.read_text())['tasks'], selected)
        self.assert_runner_tasks(selected)
        self.assertEqual(self.dispatch.call_count, 6)


if __name__ == '__main__':
    unittest.main()
