"""Live CLI long-option abbreviation contract; no endpoint calls, no collection.

Three parsers defaulted to argparse allow_abbrev=True: live_control.main,
live_round._main and live_round.main. Abbreviations were therefore accepted as
the real flags, so `--pub` reached the child as `--publish` and live_round.main
labelled an abbreviated dry-run 'completed' via its `'--dry-run' in sys.argv`
membership test.

The controller forwards child arguments verbatim (nargs=REMAINDER), so the
closed bypass is measured end to end: the controller still forwards, and the
child parser now refuses the abbreviation before any env, task-set or
collection work happens.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import live_control as control
import live_round as round_

# Unambiguous prefixes of options argparse used to accept by abbreviation.
ABBREVIATIONS = ('--pub', '--dry-r', '--forc')
# Every option the controller refuses to forward, in full form.
FORBIDDEN = ('--publish', '--dry-run', '--force', '--tag', '--task-set')
# Abbreviations of the controller's OWN options, which the controller parses itself.
CONTROLLER_OWN = ('--work', '--tas', '--fin')


class StopAtEnv(Exception):
    """Stands in for load_env to prove parsing ended before any env read."""


def call(argv, entry, name):
    """Run main()/_main() under patched argv; return its exit code.

    argparse refusals raise SystemExit(2); the entry points that are meant to be
    called in-process return their exit code instead. Both are exit code 2 here.
    """
    with mock.patch.object(sys, 'argv', [name, *argv]):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return entry()
            except SystemExit as exc:
                return exc.code


class ControllerParserTests(unittest.TestCase):
    """live_control.main keeps its exact-name guard and no longer abbreviates its own options."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.forwarded = []
        self.finalized = []
        for name, value in (('storage_policy', lambda: {}),
                            ('storage_check', lambda policy: {'ok': True}),
                            ('finalize', self.finalize)):
            self.addCleanup(setattr, control, name, getattr(control, name))
            setattr(control, name, value)
        self.addCleanup(setattr, control, 'launch', control.launch)
        control.launch = self.launch

    def launch(self, command, workspace, collection, control_dir, policy):
        self.forwarded.append(list(command))
        receipt = collection/'launch.receipt.json'
        receipt.write_text('{"resolved_exit_code":0,"state":"completed"}', encoding='utf-8')
        return receipt

    def finalize(self, receipt, workspace, collection, task_set):
        self.finalized.append(receipt)
        return 0

    def run_main(self, *own, extra=()):
        """`own` tokens go before the `--` separator; `extra` tokens are forwarded to the child."""
        argv = ['--workspace', str(self.root), '--tag', 'offline', *own, '--', *extra]
        return call(argv, control.main, 'live_control.py')

    def test_controller_own_option_abbreviations_are_rejected(self):
        for abbreviation in CONTROLLER_OWN:
            with self.subTest(abbreviation=abbreviation):
                self.forwarded.clear()
                self.assertEqual(self.run_main(abbreviation), 2)
                self.assertEqual(self.forwarded, [], 'abbreviation of a controller option was accepted')

    def test_full_controller_options_are_still_accepted(self):
        """Full controller options before the separator keep parsing and still succeed."""
        task_set = self.root/'tasks.json'
        task_set.write_text('{}', encoding='utf-8')
        self.forwarded.clear()
        self.assertEqual(self.run_main('--task-set', str(task_set)), 0)
        self.assertEqual(len(self.forwarded), 1, 'accepted --task-set must reach the child command')
        self.assertEqual(self.forwarded[0][-2:][0], '--task-set')
        self.assertEqual(Path(self.forwarded[0][-1]).resolve(), task_set.resolve())

    def test_full_finalize_option_is_still_accepted(self):
        """--finalize stays a controller-owned report-only path: no launch, one finalize."""
        receipt = self.root/'launch.receipt.json'
        receipt.write_text('{"resolved_exit_code":0,"state":"completed"}', encoding='utf-8')
        self.finalized.clear()
        self.assertEqual(self.run_main('--finalize', str(receipt)), 0)
        self.assertEqual(self.forwarded, [], '--finalize must not launch a collection')
        self.assertEqual(len(self.finalized), 1)

    def test_full_forbidden_options_are_still_rejected(self):
        for option in FORBIDDEN:
            with self.subTest(option=option):
                self.forwarded.clear()
                self.assertEqual(self.run_main(option), 2)
                self.assertEqual(self.forwarded, [], 'forbidden option reached the child command')

    def test_bare_dispatch_still_works(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.forwarded), 1)


class RoundMainParserTests(unittest.TestCase):
    """live_round._main refuses abbreviations at parse time, before env/task/collection work."""

    def setUp(self):
        self.env_reads = []
        self.addCleanup(setattr, round_, 'load_env', round_.load_env)
        round_.load_env = self.load_env

    def load_env(self, path):
        self.env_reads.append(str(path))
        raise StopAtEnv()

    def run_main(self, argv):
        self.env_reads.clear()
        try:
            code = call(argv, round_._main, 'live_round.py')
        except StopAtEnv:
            self.fail('parser accepted the option and reached load_env')
        self.assertEqual(self.env_reads, [], 'env was read before the parse failed')
        return code

    def test_abbreviations_exit_2_before_env_task_or_collection(self):
        for option in ABBREVIATIONS:
            with self.subTest(option=option):
                self.assertEqual(self.run_main(['--tag', 'offline', option]), 2)

    def test_option_with_value_abbreviation_is_rejected(self):
        self.assertEqual(self.run_main(['--tag', 'offline', '--max-tok', '7']), 2)

    def test_full_options_still_parse_and_reach_the_env_read(self):
        seen = {}
        self.addCleanup(setattr, round_, 'load_env', round_.load_env)

        def capture(path):
            seen['env_file'] = str(path)
            seen['args'] = sys._getframe(1).f_locals.get('args')
            raise StopAtEnv()

        round_.load_env = capture
        for argv in (['--tag', 'offline', '--dry-run'],
                     ['--tag', 'offline', '--publish'],
                     ['--tag', 'offline', '--force'],
                     ['--tag', 'offline', '--arms', 'with,without'],
                     ['--tag', 'offline', '--max-tokens', '7']):
            with self.subTest(argv=argv):
                seen.clear()
                with mock.patch.object(sys, 'argv', ['live_round.py', *argv]):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        self.assertRaises(StopAtEnv, round_._main)
                self.assertEqual(seen['args'].tag, 'offline')
                self.assertEqual(seen['env_file'].endswith('.env.local'), True)

    def test_full_flag_values_are_preserved(self):
        seen = {}
        self.addCleanup(setattr, round_, 'load_env', round_.load_env)
        round_.load_env = lambda path: (seen.update(args=sys._getframe(1).f_locals.get('args')), (_ for _ in ()).throw(StopAtEnv()))[0]
        with mock.patch.object(sys, 'argv', ['live_round.py', '--tag', 'offline', '--dry-run', '--max-tokens', '7']):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertRaises(StopAtEnv, round_._main)
        self.assertTrue(seen['args'].dry_run)
        self.assertEqual(seen['args'].max_tokens, 7)


class RoundObserverTests(unittest.TestCase):
    """live_round.main never records 'completed' for a run the round parser refused."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.results = Path(self.tmp.name)/'results'
        (self.results/'offline').mkdir(parents=True)
        self.states = []
        recorder = self

        class Status:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def update(self, **kwargs):
                if kwargs.get('state'):
                    recorder.states.append(kwargs['state'])

        for name, value in (('RESULTS', self.results), ('RunStatus', Status)):
            self.addCleanup(setattr, round_, name, getattr(round_, name))
            setattr(round_, name, value)

    def offline_env(self, path):
        """Enough env for the frozen-plan path; no key, no endpoint, no call."""
        self.assertFalse(self.reads.get('env_secrets'), 'test must not read .env')
        return {'ACI_BENCH_MODEL': 'offline-model', 'ACI_BENCH_BASE_URL': 'https://invalid.local'}

    def offline_tasks(self, tasks_dir, task_set):
        self.reads['tasks'] = True
        return ({'tasks': ['t1'], 'task_set_version': 'offline'}, None)

    def setUp_reads(self):
        self.reads = {'env_secrets': False, 'tasks': False}
        for name, value in (('load_env', self.offline_env), ('load_tasks', self.offline_tasks)):
            self.addCleanup(setattr, round_, name, getattr(round_, name))
            setattr(round_, name, value)

    def observed(self, argv):
        """Run the real main() and report (exit code, last observer state)."""
        self.states.clear()
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['live_round.py', *argv]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    code = round_.main()
                except SystemExit as exc:
                    code = exc.code
        return code, (self.states[-1] if self.states else None), out.getvalue()

    def test_legitimate_dry_run_stays_planned(self):
        """A real --dry-run still freezes the plan, returns 0 and is recorded as planned."""
        self.setUp_reads()
        code, state, out = self.observed(['--tag', 'offline', '--dry-run'])
        self.assertEqual(code, 0)
        self.assertEqual(state, 'planned')
        self.assertIn('frozen ', out)
        self.assertIn('cells', out)
        self.assertNotIn('ERROR', out)

    def test_abbreviated_dry_run_is_not_labelled_completed(self):
        self.setUp_reads()
        for option in ('--dry-r', '--pub'):
            with self.subTest(option=option):
                code, state, _ = self.observed(['--tag', 'offline', option])
                self.assertEqual(code, 2)
                self.assertNotEqual(state, 'completed')
                self.assertIsNone(state, 'observer must not record a state for a refused option')


if __name__ == '__main__':
    unittest.main()