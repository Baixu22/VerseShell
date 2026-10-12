"""Offline terminal-boundary regressions; no runner or round subprocess dispatch."""
import contextlib
import errno
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
sys.path[:0] = [str(ROOT / 'bench/aci/runners'), str(ROOT / 'tools')]
import live_agent_loop as h
import live_round as round
import live_storage


class BoundaryRecoveryTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.enter = stack.enter_context
        self.tmp = self.enter(tempfile.TemporaryDirectory())
        self.root = Path(self.tmp)
        self.enter(patch.dict(os.environ, ACI_STORAGE_RESERVES='{}'))
        self.model = self.enter(patch.object(h, 'run_agent_loop', side_effect=self.row))
        self.dispatch = self.enter(patch.object(round, 'run', return_value=0))
        self.enter(contextlib.redirect_stdout(io.StringIO()))
        self.enter(contextlib.redirect_stderr(io.StringIO()))
        self.enter(patch.object(round, 'RESULTS', self.root))
        self.env = self.root / '.env.local'
        self.env.write_text('ACI_BENCH_MODEL=offline\nACI_BENCH_BASE_URL=http://offline.invalid/v1/responses\nACI_BENCH_API_KEY=test\n')
        self.out = self.root / 'run.json'
        self.args = ['--model', 'offline', '--api-key', 'test', '--base-url',
                     'http://offline.invalid/v1/responses', '--tasks', 'rust_fix_compile_error',
                     '--conditions', 'raw_shell', '--seed', '42', '--out', str(self.out)]
        self.round_args = ['live_round.py', '--tag', 'study', '--env-file', str(self.env),
                           '--arms', 'with', '--seeds', '42', '--conditions', 'raw_shell']

    @staticmethod
    def row(task, condition, **kwargs):
        return dict(task_id=task['id'], condition=condition, model='offline', run_index=0,
                    success=True, success_reason='offline control', tool_calls=0,
                    observation_tokens=0, elapsed_ms=1, turns=1, trajectory=[],
                    api_error=False, endpoint_status=None, last_error=None)

    def invoke(self, resume=False):
        self.model.reset_mock()
        code = h.main(self.args + (['--resume-paused'] if resume else []))
        return code, self.model.call_count

    def invoke_round(self, dry=False):
        with patch.object(sys, 'argv', self.round_args + (['--dry-run'] if dry else [])):
            return round.main()

    def checkpoint(self):
        return [json.loads(line) for line in Path(str(self.out) + '.rows.jsonl').read_text().splitlines()]

    def check_resume(self, checkpoint):
        stop = self.root / 'STOP'
        original = stop.read_bytes()
        self.model.side_effect = self.row
        for resume in (False, True):
            with self.subTest(stage='global STOP retained', resume=resume):
                self.assertEqual(self.invoke(resume), (75, 0))
                self.assertEqual(stop.read_bytes(), original)
                self.assertFalse(self.out.exists())
                self.assertEqual(self.checkpoint(), checkpoint)
        stop.rename(self.root / 'STOP.acknowledged-offline')
        with self.subTest(stage='explicit acknowledgement and resume'):
            self.assertEqual(self.invoke(True), (0, 0))
            data = json.loads(self.out.read_text())
            self.assertEqual(data['rows'][0]['cell_id'], checkpoint[1]['cell_id'])
            self.assertEqual(self.checkpoint(), checkpoint)
            self.assertEqual(data['rows'], checkpoint[1:])

    def test_last_cell_stop_requires_explicit_ack_before_checkpoint_only_resume(self):
        def complete(task, condition, **kwargs):
            (self.root / 'STOP').write_text('offline operator stop')
            return self.row(task, condition, **kwargs)
        self.model.side_effect = complete
        result = self.invoke()
        checkpoint = self.checkpoint()
        with self.subTest(stage='last row committed then paused'):
            self.assertEqual(len(checkpoint), 2)
            self.assertTrue(checkpoint[1]['cell_id'])
            self.assertEqual(result, (75, 1))
            self.assertFalse(self.out.exists())
        self.check_resume(checkpoint)

    def test_last_cell_storage_reserve_requires_recovery_and_ack(self):
        low = [False]
        def complete(task, condition, **kwargs):
            low[0] = True
            return self.row(task, condition, **kwargs)
        self.model.side_effect = complete
        with patch.dict(os.environ, ACI_STORAGE_RESERVES=json.dumps({str(self.root.resolve()): 10})), \
             patch.object(live_storage.shutil, 'disk_usage', side_effect=lambda p: SimpleNamespace(free=9 if low[0] else 10)):
            result = self.invoke()
            checkpoint = self.checkpoint()
            with self.subTest(stage='last row committed then storage pause'):
                self.assertEqual(len(checkpoint), 2)
                self.assertEqual(result, (75, 1))
                self.assertFalse(self.out.exists())
            with self.subTest(stage='storage marker and reason'):
                self.assertTrue((self.root / 'STOP').exists())
                self.assertEqual(json.loads((self.root / 'STOP').read_text())['reason'], 'storage_reserve')
                self.assertEqual(json.loads(Path(str(self.out) + '.pause.json').read_text())['reason'], 'storage_reserve')
            with self.subTest(stage='low space blocks checkpoint-only resume'):
                self.assertEqual(self.invoke(True), (75, 0))
                self.assertEqual(self.checkpoint(), checkpoint)
            low[0] = False
            self.check_resume(checkpoint)

    def test_round_last_shard_stop_blocks_merge(self):
        def complete(label, cmd):
            if str(round.RUNNER) in cmd:
                (self.root / 'study' / 'STOP').write_text('offline final shard stop')
            return 0
        self.dispatch.side_effect = complete
        result = self.invoke_round()
        with self.subTest(stage='pause exit'):
            self.assertEqual(result, 75)
        with self.subTest(stage='no merge dispatch'):
            self.assertEqual(self.dispatch.call_count, 1)
            self.assertIn(str(round.RUNNER), self.dispatch.call_args_list[0].args[1])
            self.assertFalse(any(str(round.MERGER) in call.args[1] for call in self.dispatch.call_args_list))

    def test_matching_freeze_is_not_rewritten(self):
        self.assertEqual(self.invoke_round(dry=True), 0)
        freeze = self.root / 'study' / 'collection.json'
        # Semantically identical but byte-distinct: matching must preserve these bytes.
        freeze.write_text(json.dumps(json.loads(freeze.read_text()), separators=(',', ':')) + '\n\n')
        original = freeze.read_bytes()
        real_open = Path.open
        real_atomic = round.atomic_json
        attempts = []
        def deny_open(path, mode='r', *args, **kwargs):
            if path == freeze and any(flag in mode for flag in 'wax+'):
                attempts.append(str(path))
                raise OSError(errno.ENOSPC, 'offline freeze rewrite forbidden')
            return real_open(path, mode, *args, **kwargs)
        def deny_atomic(path, value):
            if Path(path) == freeze:
                attempts.append(str(path))
                raise OSError(errno.ENOSPC, 'offline freeze rewrite forbidden')
            return real_atomic(path, value)
        with patch.object(Path, 'open', deny_open), patch.object(round, 'atomic_json', side_effect=deny_atomic):
            try:
                result = self.invoke_round(dry=True)
            except OSError as error:
                result = ('OSError', error.errno)
        with self.subTest(stage='matching freeze succeeds without writes'):
            self.assertEqual(result, 0)
        with self.subTest(stage='no attempted rewrite'):
            self.assertEqual(attempts, [])
        self.assertEqual(freeze.read_bytes(), original)
        self.dispatch.assert_not_called()

    def test_new_freeze_atomic_enospc_leaves_no_collection_or_dispatch(self):
        freeze = self.root / 'study' / 'collection.json'
        real_atomic = round.atomic_json
        attempts = []
        def no_space(path, value):
            if Path(path) == freeze:
                attempts.append(str(path))
                raise OSError(errno.ENOSPC, 'offline atomic freeze publication')
            return real_atomic(path, value)
        with patch.object(round, 'atomic_json', side_effect=no_space):
            try:
                result = self.invoke_round()
            except OSError as error:
                self.assertEqual(error.errno, errno.ENOSPC)
                result = 'ENOSPC'
        with self.subTest(stage='existing atomic_json publication used'):
            self.assertEqual(attempts, [str(freeze)])
        with self.subTest(stage='not successful'):
            self.assertNotEqual(result, 0)
        with self.subTest(stage='no partial collection'):
            self.assertFalse(freeze.exists())
        with self.subTest(stage='no dispatch'):
            self.dispatch.assert_not_called()


    def test_round_last_shard_low_space_blocks_merge(self):
        low = [False]
        def complete(label, cmd):
            if str(round.RUNNER) in cmd:
                low[0] = True
            return 0
        self.dispatch.side_effect = complete
        with patch.dict(os.environ, ACI_STORAGE_RESERVES=json.dumps({str(self.root.resolve()): 10})), \
             patch.object(live_storage.shutil, 'disk_usage', side_effect=lambda p: SimpleNamespace(free=9 if low[0] else 10)):
            self.assertEqual(self.invoke_round(), 75)
        self.assertEqual(self.dispatch.call_count, 1)
        self.assertIn(str(round.RUNNER), self.dispatch.call_args.args[1])
        stop = json.loads((self.root / 'study' / 'STOP').read_text())
        self.assertEqual(stop['reason'], 'storage_reserve')
        self.assertFalse((self.root / 'study' / 'latest_live.json').exists())

    def test_round_stop_during_last_merge_is_not_completed(self):
        def complete(label, cmd):
            if str(round.MERGER) in cmd:
                (self.root / 'study' / 'STOP').write_text('offline stop during merge')
            return 0
        self.dispatch.side_effect = complete
        self.assertEqual(self.invoke_round(), 75)
        self.assertEqual(self.dispatch.call_count, 2)
        self.assertIn(str(round.MERGER), self.dispatch.call_args.args[1])
        status = json.loads((self.root / 'study' / 'round.status.json').read_text())
        self.assertEqual(status['state'], 'paused')
        self.assertEqual(status['exit_code'], 75)
        self.assertTrue((self.root / 'study' / 'STOP').exists())

    def test_last_cell_local_stop_is_archived_by_resume_without_new_calls(self):
        stop = Path(str(self.out) + '.stop')
        def complete(task, condition, **kwargs):
            stop.write_text('offline local stop')
            return self.row(task, condition, **kwargs)
        self.model.side_effect = complete
        self.assertEqual(self.invoke(), (75, 1))
        checkpoint = self.checkpoint()
        self.assertEqual(len(checkpoint), 2)
        self.assertFalse(self.out.exists())
        self.model.side_effect = self.row
        self.assertEqual(self.invoke(), (75, 0))
        self.assertTrue(stop.exists())
        self.assertEqual(self.invoke(True), (0, 0))
        self.assertFalse(stop.exists())
        archived = list(self.root.glob('run.json.stop.acknowledged-*'))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_text(), 'offline local stop')
        self.assertEqual(self.checkpoint(), checkpoint)
        self.assertEqual(json.loads(self.out.read_text())['rows'], checkpoint[1:])

    def test_new_freeze_enospc_at_replace_cleans_temporary_file(self):
        # Unlike the atomic-entry test, execute real serialization/fsync/cleanup.
        freeze = self.root / 'study' / 'collection.json'
        real_replace = os.replace
        staged = []
        def no_space(source, target):
            if Path(target) == freeze:
                source = Path(source)
                self.assertTrue(source.exists())
                self.assertEqual(json.loads(source.read_text())['collection_id'], 'study')
                staged.append(source)
                raise OSError(errno.ENOSPC, 'offline freeze commit failure')
            return real_replace(source, target)
        with patch.object(os, 'replace', side_effect=no_space):
            try:
                result = self.invoke_round()
            except OSError as error:
                self.assertEqual(error.errno, errno.ENOSPC)
                result = 'ENOSPC'
        self.assertEqual(len(staged), 1)
        self.assertNotEqual(result, 0)
        self.assertFalse(freeze.exists())
        self.assertFalse(staged[0].exists())
        self.assertEqual(list(freeze.parent.glob('collection.json.*.tmp')), [])
        self.dispatch.assert_not_called()

    def test_on_start_failure_waits_for_child_even_when_kill_raises(self):
        original = OSError(errno.ENOSPC, 'offline receipt publication failed')
        proc = SimpleNamespace(
            _handle=123,
            kill=Mock(side_effect=OSError(errno.EACCES, 'process already terminating')),
            communicate=Mock(return_value=(b'', b'')),
        )
        job = SimpleNamespace(
            AssignProcessToJobObject=Mock(return_value=True),
            CloseHandle=Mock(),
        )
        def fail_on_start(child):
            self.assertIs(child, proc)
            job.AssignProcessToJobObject.assert_called_once()
            raise original
        with patch.object(h, '_create_kill_on_close_job', return_value=(job, 456)), \
             patch.object(h.subprocess, 'Popen', return_value=proc) as popen:
            with self.assertRaises(OSError) as caught:
                h.run_bounded([sys.executable, '-c', 'pass'], timeout=5,
                              on_start=fail_on_start)
        self.assertIs(caught.exception, original)
        popen.assert_called_once()
        proc.kill.assert_called_once_with()
        job.CloseHandle.assert_called_once()
        self.assertEqual(job.CloseHandle.call_args.args[0].value, 456)
        proc.communicate.assert_called_once_with(timeout=2)

if __name__ == '__main__':
    unittest.main()
