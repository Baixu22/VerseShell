"""Regression for the raw-shell multi-line command truncation annotation.

Windows cmd /C executes only the FIRST line of a command that embeds a newline
and still returns that line's exit code. The 2026-10-10 partial run showed 9/10
raw-shell failures contained a multi-line command, so the harness must make the
truncation visible instead of reporting a clean success.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench/aci/runners"))
import live_agent_loop as h


class MultilineShellNoteTests(unittest.TestCase):
    def test_single_line_and_trailing_newline_are_not_flagged(self):
        for command in ("echo hi", "echo hi\n", "echo hi\r\n", "echo hi \n \n"):
            self.assertIsNone(h._multiline_shell_note(command), command)

    def test_embedded_newline_is_flagged_on_windows(self):
        with patch.object(h.os, "name", "nt"):
            for command in ("echo one\necho two",
                            'python -c "print(1)\nprint(2)"',
                            "echo one\r\necho two"):
                note = h._multiline_shell_note(command)
                self.assertIsNotNone(note, command)
                self.assertIn("FIRST line", note)
                self.assertIn("NOT executed", note)

    def test_non_windows_is_never_flagged(self):
        with patch.object(h.os, "name", "posix"):
            self.assertIsNone(h._multiline_shell_note("echo one\necho two"))

    def test_annotation_is_appended_without_changing_exit_code(self):
        with patch.object(h, "run_bounded", return_value=(0, b"one\r\n", b"", False)), \
                patch.object(h.os, "name", "nt"):
            text = h.execute_shell_cmd("echo one\necho two", ".")
        self.assertIn("[EXIT: 0]", text)
        self.assertIn("[MULTILINE:", text)
        self.assertIn("one", text)

    def test_single_line_command_has_no_annotation(self):
        with patch.object(h, "run_bounded", return_value=(0, b"hi\r\n", b"", False)), \
                patch.object(h.os, "name", "nt"):
            text = h.execute_shell_cmd("echo hi", ".")
        self.assertNotIn("[MULTILINE:", text)


if __name__ == "__main__":
    unittest.main()
