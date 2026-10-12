"""Offline dispatch regression tests for P1-2; never execute measurements."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import refresh_live_artifacts as refresh

REQUIRED = {
    "mock_bench": ["bench/aci/runners/run_suite.py", "--mode", "mock",
                   "--out", "bench/aci/results/latest.json"],
    "three_arm_report": ["tools/three_arm_report.py", "--out", "eval/three_arm_report.json"],
    "cross_shell": ["tools/cross_shell_bench.py", "--out", "eval/cross_shell.json"],
}


class RefreshChainTests(unittest.TestCase):
    def invoke(self, args=(), fail_script=None, have_without=True):
        calls = []
        stdout, stderr = io.StringIO(), io.StringIO()

        def run(argv, *, cwd):
            self.assertEqual(argv[0], sys.executable)
            self.assertEqual(cwd, refresh.ROOT)
            calls.append(argv[1:])
            return SimpleNamespace(returncode=1 if argv[1] == fail_script else 0)

        with tempfile.TemporaryDirectory() as tmp:
            arm = Path(tmp) / "with.json"
            arm.write_text("{}", encoding="utf-8")
            without = arm if have_without else Path(tmp) / "missing.json"
            with (
                patch.object(refresh, "WITH_ARM", arm),
                patch.object(refresh, "WITHOUT_ARM", without),
                patch.object(refresh.subprocess, "run", side_effect=run),
                patch.object(sys, "argv", [refresh.__file__, *args]),
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr),
            ):
                try:
                    code = refresh.main()
                except SystemExit as error:
                    code = error.code
        return code, calls, stdout.getvalue(), stderr.getvalue()

    def test_unknown_or_empty_selection_is_rejected_before_execution(self):
        for value in ("typo", "mock_bench,typo", "", ",,,"):
            with self.subTest(value=value):
                code, calls, _, _ = self.invoke(["--only", value])
                self.assertEqual(code, 2)
                self.assertEqual(calls, [])

    def test_missing_control_fails_before_partial_refresh(self):
        code, calls, _, _ = self.invoke(have_without=False)
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        code, calls, _, _ = self.invoke(["--only", "mock_bench"], have_without=False)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [REQUIRED["mock_bench"]])
        self.assertEqual(self.invoke(["--with-only"], have_without=False)[0], 0)

    def test_allow_missing_control_reaches_child_and_preserves_failure(self):
        script = "tools/read_usage_audit.py"
        code, calls, _, stderr = self.invoke(
            ["--allow-missing-without", "--only", "read_usage_audit"],
            fail_script=script, have_without=False)
        self.assertEqual(code, 1)
        self.assertEqual(calls[0][0], script)
        self.assertIn("read_usage_audit", stderr)

    def test_explicit_selection_cannot_be_silently_skipped_by_with_only(self):
        code, calls, _, _ = self.invoke(["--with-only", "--only", "read_usage_audit"])
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])

    def test_required_outputs_precede_calibration(self):
        code, calls, _, _ = self.invoke()
        self.assertEqual(code, 0)
        calibration = next(i for i, argv in enumerate(calls)
                           if argv[0] == "tools/token_proxy_calibration.py")
        positions = []
        for argv in REQUIRED.values():
            self.assertIn(argv, calls)
            self.assertEqual(calls.count(argv), 1)
            positions.append(calls.index(argv))
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(all(i < calibration for i in positions))
        self.assertEqual(len(calls), len(refresh.CHAIN))

    def test_each_new_stage_failure_is_reported(self):
        for label, argv in REQUIRED.items():
            with self.subTest(stage=label):
                code, calls, stdout, stderr = self.invoke(fail_script=argv[0])
                self.assertEqual(code, 1)
                self.assertIn(label, stderr)
                self.assertNotIn("selected refresh step(s)", stdout)
                self.assertEqual(calls[-1], argv)
                self.assertIn("remaining steps not run", stderr)

    def test_sync_follows_cross_shell_and_offline_flag_reaches_calibration(self):
        code, calls, _, _ = self.invoke(["--no-endpoint"])
        self.assertEqual(code, 0)
        cross_shell = calls.index(REQUIRED["cross_shell"])
        self.assertEqual(calls[cross_shell + 1], ["tools/sync_readme_cross_shell.py"])
        calibration = next(argv for argv in calls if argv[0] == "tools/token_proxy_calibration.py")
        self.assertIn("--no-endpoint", calibration)

    def test_with_only_retains_all_three_new_stages(self):
        code, calls, stdout, _ = self.invoke(["--with-only"])
        self.assertEqual(code, 0)
        for argv in REQUIRED.values():
            self.assertIn(argv, calls)
        expected = [argv + (["--task-set", str(refresh.ROOT / "bench/aci/task_sets/3.1.0.json")]
                            if label == "task_set_audit" else [])
                    for label, argv, needs_without in refresh.CHAIN if not needs_without]
        self.assertEqual(calls, expected)
        self.assertIn(f"completed {len(calls)} selected refresh step(s)", stdout)

    def test_selected_task_set_reaches_audit(self):
        code, calls, _, _ = self.invoke(["--only", "task_set_audit", "--task-set", "next.json"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][-2:], ["--task-set", "next.json"])


if __name__ == "__main__":
    unittest.main()
