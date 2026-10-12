"""Offline fault boundaries for TF-0133/0134 and the remaining readiness gate."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import live_agent_loop as harness
import live_control as control
import live_journal as journal
from prelive_check import checked_python_test_count


class RemainingBoundaryTests(unittest.TestCase):
    def test_readiness_rejects_skips_expected_failures_and_ambiguous_suites(self):
        body = 'Ran 350 tests in 1.234s\n\nOK\n'
        self.assertEqual(checked_python_test_count(body), 350)
        for bad in (body.replace('OK', 'OK (skipped=1)'),
                    body.replace('OK', 'OK (expected failures=1)'),
                    body.replace('OK', 'FAILED (failures=1)'),
                    body.replace('350', '1'), body + body, 'OK\n'):
            with self.subTest(body=bad), self.assertRaises(ValueError):
                checked_python_test_count(bad)

    def test_status_write_failure_releases_owner_at_entry_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'status.json'
            for phase in ('entry', 'exit'):
                owner = journal.RunStatus(path)
                with self.subTest(phase=phase):
                    if phase == 'exit':
                        owner.__enter__()
                    with patch.object(journal, 'atomic_json', side_effect=OSError(errno.ENOSPC, 'injected')):
                        with self.assertRaises(OSError):
                            if phase == 'entry':
                                owner.__enter__()
                            else:
                                owner.__exit__(OSError, OSError('injected'), None)
                    self.assertFalse(owner.lock_path.exists())
                    if phase == 'exit':
                        self.assertFalse(owner.thread.is_alive())
                    # A failed durable write cannot turn an old running status into success.
                    if path.exists():
                        self.assertNotEqual(journal.read_status(path)['state'], 'completed')
                with journal.RunStatus(path) as recovered:
                    recovered.update(state='completed', exit_code=0, finished_at=journal.utc_now())

    def test_partial_owner_record_write_does_not_leave_a_corrupt_live_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner = journal.RunStatus(Path(tmp)/'status.json')
            def partial_write(value, stream):
                stream.write('{"pid":')
                stream.flush()
                raise OSError(errno.ENOSPC, 'partial owner record')
            with patch.object(journal.json, 'dump', side_effect=partial_write), self.assertRaises(OSError):
                owner.__enter__()
            self.assertFalse(owner.lock_path.exists())
            with journal.RunStatus(owner.path) as recovered:
                recovered.update(state='completed', exit_code=0, finished_at=journal.utc_now())

    def test_file_backed_managed_logs_keep_exit_code_without_buffering(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'stdout'; err = Path(tmp)/'stderr'; started = []
            with out.open('wb') as stdout, err.open('wb') as stderr:
                rc, text, errors, timed = harness.run_bounded(
                    [sys.executable, '-c', 'import sys;print("out");print("err",file=sys.stderr);sys.exit(7)'],
                    timeout=10, stdout=stdout, stderr=stderr,
                    on_start=lambda child: started.append(child.pid))
            self.assertEqual((rc, text, errors, timed), (7, b'', b'', False))
            self.assertEqual(out.read_text().strip(), 'out')
            self.assertEqual(err.read_text().strip(), 'err')
            self.assertEqual(len(started), 1)
            self.assertFalse(journal.pid_alive(started[0]))

    @unittest.skipUnless(os.name == 'nt', 'Windows launch barrier')
    def test_persistent_receipt_failure_cannot_dispatch_workload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); marker = root/'workload-started'; written = []
            real_write = control.atomic_json
            def fail_after_initial(path, value):
                if written:
                    raise OSError(errno.ENOSPC, 'persistent injected disk failure')
                written.append(path)
                real_write(path, value)
            with patch.object(control, 'atomic_json', side_effect=fail_after_initial):
                with self.assertRaises(OSError):
                    control.launch([sys.executable, '-c', f'open({str(marker)!r},"w").write("ran")'],
                                   root, root, root/'control', {})
            self.assertFalse(marker.exists())
            receipt = control.read_json(root/'control/collection-exit.json')
            self.assertEqual(receipt['state'], 'starting')
            self.assertNotIn('resolved_exit_code', receipt)

    def test_keyboard_interrupt_persists_non_success_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(control, 'run_bounded', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                control.launch([sys.executable, '-c', 'pass'], root, root, root/'control', {})
            receipt = control.read_json(root/'control/collection-exit.json')
            self.assertEqual((receipt['state'], receipt['resolved_exit_code']), ('interrupted', 130))

    @unittest.skipUnless(os.name == 'nt', 'Windows controller Job lifecycle')
    def test_forced_controller_death_kills_collection_and_report_trees(self):
        for phase in ('collection', 'round', 'report'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); marker = root/'tree.json'; (root/'tools').mkdir()
                worker = root/'tools/refresh_live_artifacts.py'
                worker.write_text(
                    'import json,os,subprocess,sys,time\n'
                    'from pathlib import Path\n'
                    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],'
                    'creationflags=subprocess.CREATE_NO_WINDOW)\n'
                    f'Path({str(marker)!r}).write_text(json.dumps([os.getpid(),p.pid]))\n'
                    'time.sleep(60)\n', encoding='utf-8')
                script = root/'controller.py'
                script.write_text(
                    f'import sys;sys.path[:0]=[{str(ROOT/"tools")!r},{str(ROOT/"bench/aci/runners")!r}]\n'
                    'from pathlib import Path\n'
                    'import live_control as c\n'
                    f'r=Path({str(root)!r}); control=r/"control"\n'
                    'with c.RunStatus(r/"owner.status.json"):\n'
                    + (' c.launch([sys.executable,str(r/"tools/refresh_live_artifacts.py")],r,r,control,{})\n'
                       if phase == 'collection' else
                       ' import live_round as rround; rround.run("offline",[sys.executable,str(r/"tools/refresh_live_artifacts.py")])\n'
                       if phase == 'round' else
                       ' control.mkdir()\n'
                       ' t={"control_generation_id":"control","generation_id":"offline",'
                       '"pid":2147483647,"state":"completed","exit_code":0,"finished_at":"offline"}\n'
                       ' c.atomic_json(r/"round.status.json",t)\n'
                       ' c.atomic_json(r/"tasks.json",{})\n'
                       ' c.atomic_json(r/"latest_live.json",{})\n'
                       ' c.atomic_json(r/"collection.json",{"prompt_variants":["baseline","compact_all"],"task_set":str((r/"tasks.json").resolve())})\n'
                       ' receipt={"schema":"verseshell.live-control/v1","workspace":str(r.resolve()),'
                       '"collection":str(r.resolve()),"pid":t["pid"],"control_generation_id":"control",'
                       '"round_generation_id":"offline","process_exit_code":0}\n'
                       ' c.atomic_json(control/"collection-exit.json",receipt)\n'
                       ' c.finalize(control/"collection-exit.json",r,r,r/"tasks.json")\n'), encoding='utf-8')
                proc = subprocess.Popen([sys.executable, '-I', str(script)], creationflags=subprocess.CREATE_NO_WINDOW,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                pids = []
                try:
                    deadline = time.monotonic()+12
                    while not marker.exists() and proc.poll() is None and time.monotonic()<deadline:
                        time.sleep(.02)
                    if not marker.exists():
                        proc.kill(); _, errors = proc.communicate(timeout=5)
                        self.fail(f'workload did not start: {errors!r}')
                    pids = json.loads(marker.read_text())
                    self.assertTrue(all(journal.pid_alive(pid) for pid in pids))
                    proc.kill(); proc.communicate(timeout=5)
                    deadline = time.monotonic()+5
                    while any(journal.pid_alive(pid) for pid in pids) and time.monotonic()<deadline:
                        time.sleep(.02)
                    self.assertFalse(any(journal.pid_alive(pid) for pid in pids), 'controller left an orphan tree')
                    self.assertEqual(journal.read_status(root/'owner.status.json')['state'], 'interrupted')
                    if phase == 'collection':
                        receipt = control.read_json(root/'control/collection-exit.json')
                        self.assertEqual(receipt['state'], 'running')
                        self.assertNotIn('resolved_exit_code', receipt)
                    elif phase == 'report':
                        status = control.read_json(next((root/'control').glob('reports-*/reports-status.json')))
                        self.assertFalse(status['complete'])
                        self.assertEqual(status['reports']['compact_all']['state'], 'pending')
                finally:
                    if proc.poll() is None:
                        proc.kill(); proc.communicate(timeout=5)
                    # Bounded cleanup only for the exact child PIDs created by this test.
                    for pid in pids:
                        if journal.pid_alive(pid):
                            subprocess.run(['taskkill','/F','/T','/PID',str(pid)], capture_output=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                    if proc.stderr:
                        proc.stderr.close()


if __name__ == '__main__':
    unittest.main()
