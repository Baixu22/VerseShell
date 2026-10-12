"""Binary integrity unit controls: no compiler, subprocess, endpoint, or model runs.

Fake readiness/calibration JSON is confined to a TemporaryDirectory and labelled
UNIT CONTROL ONLY. Only unittest logs, never these fake receipts, are retained.
"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'bench/aci/runners')]
import prelive_check as prelive
import claim_gate

ORIGINAL = b'UNIT CONTROL ONLY: candidate binary placeholder\n'
RUST_TEST_BINARY = b'UNIT CONTROL ONLY: cargo test binary placeholder\n'
PYTHON_MUTATION = b'UNIT CONTROL ONLY: python stage changed candidate\n'
SIMULATION_MUTATION = b'UNIT CONTROL ONLY: simulation changed candidate\n'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ReadinessBinaryIntegrityTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='unit-readiness-control-')))
        self.out = self.root / 'readiness-output'
        self.target = self.root / 'candidate-target'
        self.candidate = self.target / 'debug/ae.exe'
        self.candidate.parent.mkdir(parents=True)
        self.candidate.write_bytes(ORIGINAL)
        self.tool = self.root / 'fake-tool'
        self.tool.write_bytes(b'UNIT CONTROL ONLY: non-executable tool')
        self.plan = self.root / 'analysis-plan.json'
        self.plan.write_text('{"unit_control_only":true}')
        self.task_set = self.root / 'task-set.json'
        self.task_set.write_text('{"unit_control_only":true,"tasks":["unit-task"]}')
        (self.root / 'tools').mkdir()
        (self.root / 'tools/unit_control.py').write_text('# UNIT CONTROL ONLY\n')
        self.events = []
        self.rust_calls = []
        self.mutate_stage = None
        self.rust_writes = True
        stack.enter_context(patch.dict(os.environ, CARGO_TARGET_DIR=str(self.target),
                                       UNIT_READINESS_ENV_SENTINEL='must-survive-rust-env'))
        self.original_env = dict(os.environ)
        self.fake_h = SimpleNamespace(AE=self.candidate, EVIDENCE_GLOBS=[],
                                      evidence_fingerprint=lambda _: sha(b'UNIT CONTROL ONLY SOURCE'))
        self.fake_h.run_bounded = Mock(side_effect=self.run_bounded)
        self.fake_h.execute_aci_op = Mock(side_effect=self.aci_smoke)
        stack.enter_context(patch.object(prelive, 'ROOT', self.root))
        stack.enter_context(patch.object(prelive, 'h', self.fake_h))
        stack.enter_context(patch.object(prelive.sys, 'executable', str(self.tool)))
        stack.enter_context(patch.object(prelive.shutil, 'which', return_value=str(self.tool)))
        stack.enter_context(patch.object(prelive, 'read_plan', return_value={'minimum_tasks': 30, 'minimum_seeds': 5}))
        stack.enter_context(patch.object(prelive, 'check_blueprint', return_value={
            'development_slots': 18, 'holdout_slots': 30, 'actual_tasks_generated': False,
            'purpose': 'UNIT CONTROL ONLY'}))
        stack.enter_context(patch.object(claim_gate, 'task_set_consistency_claim', return_value={
            'pass': True, 'unit_control_only': True}))
        self.simulation = stack.enter_context(patch.object(prelive, 'simulate_grid', side_effect=self.simulate))

    def assert_candidate_path(self):
        self.assertEqual(Path(prelive.h.AE).resolve(), self.candidate.resolve(),
                         'the candidate path must not be replaced to hide mutation')

    def run_bounded(self, command, **kwargs):
        self.assert_candidate_path()
        command = list(map(str, command))
        if command[-1] == '--version':
            self.events.append('version')
            return 0, b'UNIT CONTROL ONLY version 0.0\n', b'', False
        if 'unittest' in command:
            self.events.append('python-tests')
            if self.mutate_stage == 'python-tests':
                self.candidate.write_bytes(PYTHON_MUTATION)
            # The real checked_python_test_count minimum is 192; no skips.
            return 0, b'Ran 192 tests in 0.001s\n\nOK\n', b'', False
        if command[:2] == ['cargo', 'test']:
            self.events.append('rust-tests')
            self.rust_calls.append((command, kwargs))
            target_arg = None
            for index, arg in enumerate(command):
                if arg == '--target-dir':
                    target_arg = command[index + 1]
                elif arg.startswith('--target-dir='):
                    target_arg = arg.split('=', 1)[1]
            env = kwargs.get('env')
            if env is None:
                env = os.environ
            target = Path(target_arg or env.get('CARGO_TARGET_DIR', str(self.target))).resolve()
            self.assertTrue(target.is_relative_to(self.root.resolve()), 'fake compiler writes must stay in this unit temp root')
            if self.rust_writes:
                binary = target / 'debug/ae.exe'
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(RUST_TEST_BINARY)
            # The current Rust parser requires a nonempty successful suite.
            return 0, b'test result: ok. 1 passed; 0 failed; 0 ignored\n', b'', False
        script = next((Path(arg).name for arg in command if arg.endswith('.py')), '')
        if script in ('task_set_audit.py', 'calibrate_repeated_intervals.py'):
            output = Path(command[command.index('--out') + 1]).resolve()
            self.assertTrue(output.is_relative_to(self.root.resolve()))
            if script == 'task_set_audit.py':
                self.events.append('task-audit')
                payload = {'fixture_consistency': [{'unit_control_only': True}], 'unit_control_only': True}
            else:
                self.events.append('calibration')
                payload = {'calibration_approved': True, 'unit_control_only': True}
            output.write_text(json.dumps(payload), encoding='utf-8')
            return 0, b'UNIT CONTROL ONLY\n', b'', False
        self.fail('unexpected fake command; never fall back to real execution')

    def simulate(self, *args):
        self.assert_candidate_path()
        self.events.append('simulate-grid')
        if self.mutate_stage == 'simulate-grid':
            self.candidate.write_bytes(SIMULATION_MUTATION)
        return {'synthetic_cells': 1, 'resumed_duplicate_calls': 0, 'merged_runs': 3,
                'live_endpoint_calls': 0, 'synthetic_claims_blocked': True, 'unit_control_only': True}

    def aci_smoke(self, op, args, workspace):
        self.assert_candidate_path()
        self.events.append('aci-smoke')
        marker = 'prelive-aci-ready' if op == 'file.view' else 'prelive-exec-ready'
        return {'ok': True, 'data': marker, 'unit_control_only': True}

    def invoke(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = prelive.main(['--out-dir', str(self.out), '--plan', str(self.plan), '--task-set', str(self.task_set)])
        self.assert_candidate_path()
        report = json.loads((self.out / 'readiness.json').read_text(encoding='utf-8'))
        return code, report

    def test_unchanged_candidate_control_can_complete_every_stage(self):
        self.rust_writes = False
        code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(report['ready_for_live'])
        self.assertEqual(report['schema'], 'verseshell.prelive-readiness/v1')
        self.assertEqual(report['python_tests'], 192)
        self.assertEqual(report['rust_tests']['passed'], 1)
        self.assertEqual(report['binary_sha256'], sha(ORIGINAL))
        self.assertEqual(self.candidate.read_bytes(), ORIGINAL)
        self.simulation.assert_called_once()
        self.assertEqual(self.fake_h.execute_aci_op.call_count, 2)

    def test_cargo_tests_use_separate_env_and_cli_target_without_touching_candidate(self):
        code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(report['ready_for_live'])
        self.assertEqual(len(self.rust_calls), 1)
        command, kwargs = self.rust_calls[0]
        target = (self.out / 'rust-tests-target').resolve()
        with self.subTest(binding='environment'):
            self.assertIsNotNone(kwargs.get('env'), 'Rust must receive an explicit inherited environment')
            env = kwargs['env']
            self.assertEqual(Path(env['CARGO_TARGET_DIR']).resolve(), target)
            self.assertTrue(all(env.get(k) == v for k, v in self.original_env.items() if k != 'CARGO_TARGET_DIR'),
                            'non-target environment variables must survive')
        with self.subTest(binding='CLI'):
            self.assertTrue(('--target-dir' in command and Path(command[command.index('--target-dir') + 1]).resolve() == target)
                            or ('--target-dir=' + str(target)) in command)
        with self.subTest(binding='candidate bytes and receipt'):
            self.assertEqual(self.candidate.read_bytes(), ORIGINAL)
            self.assertEqual(report['binary_sha256'], sha(ORIGINAL))
            self.assertEqual((target / 'debug/ae.exe').read_bytes(), RUST_TEST_BINARY)

    def test_python_stage_mutation_fails_immediately_even_with_exit_zero(self):
        self.mutate_stage = 'python-tests'
        code, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(report['ready_for_live'])
        self.assertEqual(self.events[-1], 'python-tests')
        self.assertEqual(self.rust_calls, [])
        self.simulation.assert_not_called()
        self.fake_h.execute_aci_op.assert_not_called()
        diagnostic = json.dumps(report)
        self.assertIn('python-tests', diagnostic)
        self.assertIn(sha(ORIGINAL), diagnostic)
        self.assertIn(sha(PYTHON_MUTATION), diagnostic)

    def test_simulation_mutation_is_refused_before_aci_smoke_or_ready(self):
        self.mutate_stage = 'simulate-grid'
        code, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(report['ready_for_live'])
        self.simulation.assert_called_once()
        self.assertEqual(self.events[-1], 'simulate-grid')
        self.fake_h.execute_aci_op.assert_not_called()
        diagnostic = json.dumps(report)
        self.assertRegex(diagnostic, r'simulat|synthetic')
        self.assertIn(sha(ORIGINAL), diagnostic)
        self.assertIn(sha(SIMULATION_MUTATION), diagnostic)


if __name__ == '__main__':
    unittest.main()
