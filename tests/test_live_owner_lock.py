"""Offline owner exclusion regressions; only the test-owned child is terminated."""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bench/aci/runners'))
import live_journal as journal


class OwnerLockTests(unittest.TestCase):
    def test_stale_lock_takeover_cannot_admit_two_owners(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as owners:
            status = Path(tmp) / 'run.status.json'
            lock = Path(str(status) + '.lock')
            lock.write_text(json.dumps({'pid': 0, 'generation_id': 'stale-initial'}))
            a, b = journal.RunStatus(status), journal.RunStatus(status)
            entered, rejected = [], []
            interleaved = False
            real_replace = Path.replace

            def enter(owner, label):
                try:
                    owners.enter_context(owner)
                except RuntimeError:
                    rejected.append(label)
                else:
                    entered.append((label, owner.value['generation_id']))

            def replace(path, target):
                nonlocal interleaved
                if path == lock and not interleaved:
                    interleaved = True
                    enter(b, 'B')
                return real_replace(path, target)

            with patch.object(Path, 'replace', replace):
                enter(a, 'A')
            # Retain the exclusion check if a fix no longer uses Path.replace.
            if not interleaved:
                enter(b, 'B')
            print(json.dumps({'takeover_entered': entered, 'rejected': rejected,
                              'interleaved_once': interleaved}))
            self.assertEqual(len(entered), 1, 'exactly one RunStatus owner must enter the output')
            if entered:
                generation = entered[0][1]
                self.assertEqual(json.loads(lock.read_text())['generation_id'], generation)
                self.assertEqual(json.loads(status.read_text())['generation_id'], generation)

    def test_uncertain_pid_probe_cannot_steal_an_active_owner(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as owners:
            status = Path(tmp) / 'run.status.json'
            lock = Path(str(status) + '.lock')
            owners.enter_context(journal.RunStatus(status))
            original_lock = lock.read_bytes()
            generation = json.loads(status.read_text())['generation_id']
            with patch.object(journal, 'pid_alive', return_value=False):
                with self.assertRaises(RuntimeError):
                    owners.enter_context(journal.RunStatus(status))
            self.assertEqual(lock.read_bytes(), original_lock)
            self.assertEqual(json.loads(status.read_text())['generation_id'], generation)

    def test_reentrant_enter_keeps_outer_owner_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / 'run.status.json'
            lock = Path(str(status) + '.lock')
            with journal.RunStatus(status) as owner:
                original_lock = lock.read_bytes()
                original_status = status.read_bytes()
                generation = json.loads(original_status)['generation_id']
                with contextlib.ExitStack() as nested:
                    with self.assertRaises(RuntimeError):
                        nested.enter_context(owner)
                self.assertEqual(lock.read_bytes(), original_lock)
                self.assertEqual(status.read_bytes(), original_status)
                self.assertEqual(json.loads(status.read_bytes())['generation_id'], generation)
                # PID checks must not conceal loss of the outer native exclusion.
                with patch.object(journal, 'pid_alive', return_value=False):
                    with contextlib.ExitStack() as contender:
                        with self.assertRaises(RuntimeError):
                            contender.enter_context(journal.RunStatus(status))
                self.assertEqual(lock.read_bytes(), original_lock)
                self.assertEqual(status.read_bytes(), original_status)
            self.assertFalse(lock.exists())
            with journal.RunStatus(status):
                self.assertNotEqual(json.loads(status.read_bytes())['generation_id'], generation)

    def test_live_child_blocks_takeover_then_dead_child_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status = root / 'run.status.json'
            lock = Path(str(status) + '.lock')
            ready = root / 'ready.json'
            child_code = """import os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import live_journal as journal
with journal.RunStatus(Path(sys.argv[2])) as owner:
    journal.atomic_json(Path(sys.argv[3]), {'pid':os.getpid(),'generation_id':owner.value['generation_id']})
    while True:
        time.sleep(0.1)
"""
            proc = subprocess.Popen(
                [(getattr(sys, '_base_executable', None) or sys.executable), '-c', child_code, str(ROOT / 'bench/aci/runners'),
                 str(status), str(ready)],
                cwd=ROOT, env=os.environ.copy(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), 'test child did not signal readiness within 5s')
                signal = json.loads(ready.read_text())
                self.assertEqual(signal['pid'], proc.pid)
                old_lock = lock.read_bytes()
                generation = signal['generation_id']
                with contextlib.ExitStack() as contender:
                    with self.assertRaises(RuntimeError):
                        contender.enter_context(journal.RunStatus(status))
                self.assertEqual(lock.read_bytes(), old_lock)
                self.assertEqual(json.loads(status.read_text())['generation_id'], generation)

                # Terminate only this Popen's exact child, then wait before takeover.
                proc.kill()
                proc.wait(timeout=5)
                with journal.RunStatus(status):
                    recovered = json.loads(status.read_text())['generation_id']
                    self.assertNotEqual(recovered, generation)
                    self.assertEqual(json.loads(lock.read_text())['generation_id'], recovered)
                    archived = [p for p in root.glob(lock.name + '.abandoned-*')
                                if p.is_file() and p.read_bytes() == old_lock]
                    self.assertTrue(archived, 'dead owner lock bytes must remain archived')
                self.assertFalse(lock.exists())
                with journal.RunStatus(status):
                    self.assertNotEqual(json.loads(status.read_text())['generation_id'], recovered)
            finally:
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                stdout, stderr = proc.communicate(timeout=5)
                print(json.dumps({'test_child_pid': proc.pid, 'exit_code': proc.returncode,
                                  'stdout': stdout.decode('utf-8', errors='replace'),
                                  'stderr': stderr.decode('utf-8', errors='replace')}))


if __name__ == '__main__':
    unittest.main()
