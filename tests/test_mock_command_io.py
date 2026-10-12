"""No live calls: real local child processes test predicate I/O and exit codes."""
import contextlib
import io
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bench/aci/runners'))
import run_suite


class MockCommandIOTests(unittest.TestCase):
    def test_non_ascii_output_cannot_crash_reader_or_change_exit_verdict(self):
        original = subprocess.Popen
        def launch(*args, **kwargs):
            if kwargs.get('text'):
                kwargs['encoding'] = 'gbk'
            return original(*args, **kwargs)
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp:
                errors = []
                script = ('import sys; b=bytes.fromhex("e28094ff"); '
                          'sys.stdout.buffer.write(b); sys.stderr.buffer.write(b); '
                          f'sys.exit({exit_code})')
                with patch.object(subprocess, 'Popen', side_effect=launch),                         patch.object(threading, 'excepthook', side_effect=errors.append):
                    ok, reason = run_suite.check_success(
                        {'type': 'command_exit_0', 'argv': [sys.executable, '-c', script]}, Path(tmp))
                self.assertEqual(ok, exit_code == 0)
                self.assertIn(str(exit_code), reason)
                self.assertEqual(errors, [], 'background output reader failed despite a returned verdict')

    def test_timeout_bounds_inherited_child_pipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = ('import subprocess,sys,time; '
                      'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                      'time.sleep(30)')
            start = time.monotonic()
            ok, reason = run_suite.check_success(
                {'type': 'command_exit_0', 'argv': [sys.executable, '-c', script], 'timeout_sec': 1}, Path(tmp))
            self.assertFalse(ok)
            self.assertIn('timeout', reason)
            self.assertLess(time.monotonic() - start, 8)

    def test_missing_command_remains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = run_suite.check_success(
                {'type': 'command_exit_0', 'argv': [str(Path(tmp) / 'nonexistent-executable')]}, Path(tmp))
            self.assertFalse(ok)
            self.assertIn('command not found', reason)


if __name__ == '__main__':
    unittest.main()
