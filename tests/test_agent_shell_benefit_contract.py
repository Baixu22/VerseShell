from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tools" / "agent_shell_benefit" / "contract_check.py"
MANIFEST = ROOT / "tools" / "agent_shell_benefit" / "task_manifest.json"


class AgentShellBenefitContractTest(unittest.TestCase):
    def test_manifest_is_frozen_at_ten_by_three(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in manifest["tasks"]], [f"T{i:02d}" for i in range(1, 11)])
        self.assertEqual(manifest["expected_cells"], 30)
        self.assertEqual(manifest["arms"], ["A", "A_prime", "D"])

    def test_actual_ae_output_matches_provider_contract(self) -> None:
        ae = ROOT / "target" / "release" / "ae.exe"
        if not ae.is_file():
            self.skipTest("build target/release/ae.exe first")
        proc = subprocess.run(
            [sys.executable, str(CONTRACT), "--ae", str(ae)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["schema"], "verseshell.observation/v1")
        self.assertEqual(result["validation_errors"], [])


class AgentShellSuiteTest(unittest.TestCase):
    def test_catalog_is_80_tasks_across_four_tiers(self) -> None:
        from tools.agent_shell_benefit.suite import build_catalog

        catalog = build_catalog()
        self.assertEqual(len(catalog), 80)
        for tier in ("L1", "L2", "L3", "L4"):
            self.assertEqual(len([t for t in catalog if t["tier"] == tier]), 20)

    def test_every_task_has_a_verifiable_artifact_or_trace_check(self) -> None:
        from tools.agent_shell_benefit.suite import build_catalog

        strong = {
            "file_equals", "file_contains", "file_absent", "file_matches", "file_count_lines",
            "exit_seen", "stdout_seen", "command_seen", "parallel_used", "parallel_result_count",
            "parallel_wall_lt", "no_process", "host_blocked", "recovered",
            "no_duplicate_commands", "tool_count_min", "tool_count_max",
        }
        for task in build_catalog():
            kinds = {c.get("type") for c in task["oracle"]["checks"]}
            self.assertTrue(kinds & strong, f"{task['id']} is summary-only: {kinds}")

    def test_oracle_selftest_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "agent_shell_benefit" / "suite" / "selftest_oracles.py")],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ALL_PASS", proc.stdout)


class AgentShellSuiteAuditTest(unittest.TestCase):
    """Guard the suite against the defect classes found during development."""

    def _run(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "agent_shell_benefit" / "suite" / script)],
            capture_output=True, text=True, timeout=120,
        )

    def test_static_task_audit_is_clean(self) -> None:
        proc = self._run("audit_suite.py")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("AUDIT CLEAN", proc.stdout)

    def test_every_oracle_is_satisfiable_and_not_trivially_passable(self) -> None:
        proc = self._run("audit_oracles.py")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("unsatisfiable oracles: 0", proc.stdout)
        self.assertIn("empty-cell false passes: 0", proc.stdout)


if __name__ == "__main__":
    unittest.main()