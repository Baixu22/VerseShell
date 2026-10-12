"""Regression for the recovery-loop metric (tools/recovery_loop.py)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import recovery_loop as rl


class RecoveryLoopTests(unittest.TestCase):
    def test_aci_failure_then_same_op_success(self):
        rows = [{
            "task_id": "t", "condition": "verseshell_aci", "success": True,
            "stop_reason": "task_complete",
            "trajectory": [
                {"op": "exec.run", "aci_ok": False, "error_code": "E_PROCESS_EXIT"},
                {"op": "result.query", "aci_ok": True},
                {"op": "file.replace_exact", "aci_ok": True},
                {"op": "exec.run", "aci_ok": True},
                {"op": "task_complete"},
            ],
        }]
        cells = rl.analyse(rows, Path("."))
        self.assertEqual(cells[0]["first_fail_index"], 0)
        self.assertTrue(cells[0]["recovered"])
        self.assertEqual(cells[0]["attempts_to_recover"], 3)

    def test_raw_shell_reads_exit_code_from_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "obs").mkdir()
            (root / "obs" / "a.json").write_text("[EXIT: 1]", encoding="utf-8")
            (root / "obs" / "b.json").write_text("[EXIT: 0]", encoding="utf-8")
            rows = [{
                "task_id": "t", "condition": "raw_shell", "success": True,
                "stop_reason": "task_complete",
                "trajectory": [
                    {"op": "run_command", "observation": {"path": "obs/a.json"}},
                    {"op": "run_command", "observation": {"path": "obs/b.json"}},
                    {"op": "task_complete"},
                ],
            }]
            cells = rl.analyse(rows, root)
        self.assertEqual(cells[0]["first_fail_index"], 0)
        self.assertTrue(cells[0]["recovered"])
        self.assertEqual(cells[0]["attempts_to_recover"], 1)

    def test_no_failure_has_no_recovery(self):
        rows = [{
            "task_id": "t", "condition": "verseshell_aci", "success": True,
            "stop_reason": "task_complete",
            "trajectory": [{"op": "file.read_many", "aci_ok": True}, {"op": "task_complete"}],
        }]
        cells = rl.analyse(rows, Path("."))
        self.assertIsNone(cells[0]["first_fail_index"])
        self.assertFalse(cells[0]["recovered"])


if __name__ == "__main__":
    unittest.main()
