"""Fake-only Windows managed-barrier interpreter ownership contracts."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bench/aci/runners'))
import live_agent_loop as h

VENV = r'C:\offline\venv\Scripts\python.exe'
BASE = r'C:\offline\Python\python.exe'


class ManagedLaunchInterpreterTests(unittest.TestCase):
    def capture(self, base):
        events = []
        workload = [VENV, '-c', 'print("workload")']
        proc = SimpleNamespace(_handle=123, returncode=0)
        def communicate(*, input, timeout):
            events.append('permit')
            self.assertEqual(input, b'\x01original stdin')
            self.assertEqual(timeout, 5)
            return b'out', b'err'
        proc.communicate = Mock(side_effect=communicate)
        job = SimpleNamespace(
            AssignProcessToJobObject=Mock(side_effect=lambda *args: events.append('job') or 1),
            CloseHandle=Mock(side_effect=lambda *args: events.append('close')),
        )
        def on_start(child):
            self.assertIs(child, proc)
            events.append('on_start')
        with patch.object(h.sys, 'executable', VENV), \
             patch.object(h.sys, '_base_executable', None if base == 'missing' else base, create=True), \
             patch.object(h.shutil, 'which', return_value=VENV), \
             patch.object(h, '_create_kill_on_close_job', return_value=(job, 456)), \
             patch.object(h.subprocess, 'Popen', return_value=proc) as popen:
            if base == 'missing':
                del h.sys._base_executable
            result = h.run_bounded(workload, timeout=5, stdin_data=b'original stdin', on_start=on_start)
        self.assertEqual(result, (0, b'out', b'err', False))
        popen.assert_called_once()
        argv = popen.call_args.args[0]
        self.assertEqual(argv[1], '-I')
        self.assertEqual(Path(argv[2]).name, 'managed_launch.py')
        self.assertEqual(json.loads(argv[3]), [workload, False])
        self.assertEqual(json.loads(argv[3])[0][0], VENV)
        self.assertEqual(events, ['job', 'on_start', 'permit', 'close'])
        proc.communicate.assert_called_once_with(input=b'\x01original stdin', timeout=5)
        job.AssignProcessToJobObject.assert_called_once()
        job.CloseHandle.assert_called_once()
        return argv

    def test_base_interpreter_hosts_barrier_without_changing_venv_workload(self):
        self.assertEqual(self.capture(BASE)[0], BASE)

    def test_none_base_executable_falls_back_to_sys_executable(self):
        self.assertEqual(self.capture(None)[0], VENV)

    def test_missing_base_executable_falls_back_to_sys_executable(self):
        self.assertEqual(self.capture('missing')[0], VENV)


if __name__ == '__main__':
    unittest.main()
