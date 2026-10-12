"""Boundary and negative controls for the pre-registered budget diagnostic."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import budget_sensitivity as budget
import claim_gate as gate


def payload(n, k, turn_k=0, max_turns=100):
    return {"live_config": {"model": "m", "max_turns": max_turns},
            "rows": [{"model": "m", "task_id": "t", "condition": "raw_shell",
                      "completion_truncated_turns": 3 if i < k else 0,
                      "success": False, "turns": max_turns if i < turn_k else 0,
                      "observation_tokens": 9999}
                     for i in range(n)]}


class BudgetSensitivityTests(unittest.TestCase):
    def test_exact_threshold_and_no_rounding_promotion(self):
        for n, k, expected in [(10, 1, True), (11, 1, False), (9, 1, True), (10001, 1000, False), (3, 0, False)]:
            with self.subTest(n=n, k=k):
                row = budget.derive(payload(n, k), "with")["groups"][0]
                self.assertIs(row["budget_sensitive"], expected)
                self.assertEqual(row["completion_truncated_rows"], k)

    def test_success_size_and_api_flags_do_not_select_tasks(self):
        original = payload(10, 1)
        changed = copy.deepcopy(original)
        for row in changed["rows"]:
            row.update(success=True, observation_tokens=0, api_error=True)
        self.assertEqual(budget.derive(original, "with"), budget.derive(changed, "with"))

    def test_turn_axis_is_reported_without_changing_legacy_completion_label(self):
        row = budget.derive(payload(10, 0, turn_k=1), "with")["groups"][0]
        self.assertFalse(row["budget_sensitive_completion"])
        self.assertTrue(row["budget_sensitive_turn"])
        self.assertTrue(row["budget_sensitive_any"])
        self.assertFalse(row["budget_sensitive"])
        self.assertEqual(row["turn_capped_rows"], 1)
        self.assertEqual(row["turn_capped_rate"], 0.1)

    def test_turn_axis_exact_threshold_has_no_rounding_promotion(self):
        for n, k, expected in [(10, 1, True), (11, 1, False), (9, 1, True)]:
            with self.subTest(n=n, k=k):
                row = budget.derive(payload(n, 0, turn_k=k), "with")["groups"][0]
                self.assertIs(row["budget_sensitive_turn"], expected)

    def test_condition_and_model_groups_cannot_dilute_each_other(self):
        data = payload(3, 1)
        other = payload(100, 0)
        for row in other["rows"]:
            row["condition"] = "verseshell_aci"
        data["rows"] += other["rows"]
        other = payload(100, 0)
        for row in other["rows"]:
            row["model"] = "another"
        data["rows"] += other["rows"]
        groups = budget.derive(data, "with")["groups"]
        self.assertEqual(sum(r["budget_sensitive"] for r in groups), 1)
        self.assertEqual(len(groups), 3)

    def test_unknown_data_is_not_reported_as_insensitive(self):
        for data in ({"rows": []}, {"rows": [{}]}, {"rows": [None]}, payload(1, 0)):
            if data.get("rows") and isinstance(data["rows"][0], dict) and data["rows"][0].get("model"):
                data["rows"][0].pop("completion_truncated_turns")
            with self.assertRaises(ValueError):
                budget.derive(data, "missing")

    def test_freshness_gate_rejects_modified_source(self):
        self.assertIn("eval/budget_sensitivity.json", gate.EVIDENCE_ARTIFACTS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval").mkdir()
            source = root / "rows.json"
            source.write_text('{"rows": []}', encoding="utf-8")
            with patch.object(gate, "ROOT", root), patch.object(gate, "EVIDENCE_ARTIFACTS", ["eval/budget_sensitivity.json"]):
                evidence = {"globs": ["rows.json"], "fingerprint": gate.evidence_fingerprint(["rows.json"])}
                (root / "eval/budget_sensitivity.json").write_text(json.dumps({"evidence": evidence}), encoding="utf-8")
                self.assertTrue(gate.freshness_entries()[0]["pass"])
                source.write_text('{"rows": [1]}', encoding="utf-8")
                self.assertFalse(gate.freshness_entries()[0]["pass"])


if __name__ == "__main__":
    unittest.main()
