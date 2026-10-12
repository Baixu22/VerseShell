"""§0.6.8 controls: the dual-budget split is additive and the gate is unchanged.

These are synthetic rows. The failure this file must catch is the tempting one:
reading "only the completion axis tripped" as permission to claim a comparison whose
union cap_truncated rate is still above 10%, or letting a row that hits two axes be
counted twice in the union. Neither may happen.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from live_uncertainty import BUDGET_AXES, row_budget_axis, row_class, row_policy  # noqa: E402


def row(condition, *, completion=0, turns=1, stop_reason=None, success=False,
        api_error=False, **extra):
    payload = {
        "condition": condition,
        "task_id": f"task-{condition}",
        "model": "synthetic-model",
        "success": success,
        "turns": turns,
        "completion_truncated_turns": completion,
        "tool_calls": 0,
        "observation_tokens": 0,
        "api_error": api_error,
    }
    if stop_reason is not None:
        payload["stop_reason"] = stop_reason
    payload.update(extra)
    return payload


def arm(condition, spec):
    """spec: iterable of dicts passed as kwargs to `row`, one row each."""
    return [row(condition, **kwargs) for kwargs in spec]


CAP = 20


class BudgetAxisTests(unittest.TestCase):
    def test_single_ticks_are_axis_specific(self):
        self.assertEqual(row_budget_axis(row("x", completion=1), CAP), ("completion_cap",))
        self.assertEqual(row_budget_axis(row("x", turns=CAP), CAP), ("turn_cap",))
        self.assertEqual(row_budget_axis(row("x", stop_reason="repeat_call_limit"), CAP),
                         ("repeat_call_cap",))
        self.assertEqual(row_budget_axis(row("x"), CAP), ())

    def test_row_class_is_the_union_of_the_axes(self):
        for kwargs in ({"completion": 1}, {"turns": CAP}, {"stop_reason": "repeat_call_limit"}):
            with self.subTest(**kwargs):
                probe = row("x", **kwargs)
                self.assertTrue(row_budget_axis(probe, CAP))
                self.assertEqual(row_class(probe, CAP), "cap_truncated")
        self.assertEqual(row_class(row("x"), CAP), "analysable")

    def test_endpoint_failure_keeps_priority_over_any_budget_axis(self):
        probe = row("x", completion=1, api_error=True)
        self.assertEqual(row_budget_axis(probe, CAP), ("completion_cap",))
        self.assertEqual(row_class(probe, CAP), "endpoint_failure")

    def test_missing_stop_reason_still_exposes_the_turn_axis(self):
        probe = row("x", turns=CAP)  # merged artifacts can omit stop_reason entirely
        self.assertNotIn("stop_reason", probe)
        self.assertEqual(row_budget_axis(probe, CAP), ("turn_cap",))

    def test_overlap_counts_each_axis_but_the_union_only_once(self):
        rows = arm("verseshell_aci", [
            {"completion": 1, "turns": CAP},
            {"completion": 1, "turns": CAP},
            *[{} for _ in range(8)],
        ])
        policy = row_policy(rows, ["verseshell_aci"], CAP)
        axes = policy["per_arm"]["verseshell_aci"]["budget_axes"]
        self.assertEqual(axes["completion_cap"], 2)
        self.assertEqual(axes["turn_cap"], 2)
        self.assertEqual(axes["overlap"], 2)
        self.assertEqual(axes["union"], 2)
        self.assertEqual(policy["per_arm"]["verseshell_aci"]["cap_truncated"], 2)


class GateIsNotLoosenedTests(unittest.TestCase):
    def compare(self, a_rows, d_rows):
        rows = a_rows + d_rows
        conditions = ["raw_shell", "verseshell_aci"]
        return row_policy(rows, conditions, CAP, [("raw_shell", "verseshell_aci")])

    def test_a_single_dirty_axis_blocks_the_comparison(self):
        a_rows = arm("raw_shell", [{} for _ in range(10)])
        d_rows = arm("verseshell_aci", [
            {"completion": 1}, {"completion": 1}, *[{} for _ in range(8)],
        ])
        policy = self.compare(a_rows, d_rows)
        d_axes = policy["per_arm"]["verseshell_aci"]["budget_axes"]
        self.assertEqual(d_axes["completion_cap"], 2)
        self.assertEqual(d_axes["turn_cap"], 0)
        self.assertEqual(d_axes["union"], 2)          # 20% > 10%
        comparison = policy["comparisons"]["verseshell_aci_vs_raw_shell"]
        self.assertFalse(comparison["claimable"])
        self.assertIn("exclusion_rate_above_10pct", comparison["policy_blocked_reasons"])
        self.assertIn("verseshell_aci", comparison["cap_truncated_axes"])

    def test_a_clean_axis_does_not_rescue_a_dirty_other_axis(self):
        a_rows = arm("raw_shell", [
            {"turns": CAP}, {"turns": CAP}, *[{} for _ in range(8)],
        ])
        d_rows = arm("verseshell_aci", [{} for _ in range(10)])
        policy = self.compare(a_rows, d_rows)
        a_axes = policy["per_arm"]["raw_shell"]["budget_axes"]
        self.assertEqual(a_axes["turn_cap"], 2)
        self.assertEqual(a_axes["completion_cap"], 0)
        self.assertEqual(a_axes["union"], 2)
        self.assertFalse(policy["comparisons"]["verseshell_aci_vs_raw_shell"]["claimable"])

    def test_split_never_replaces_the_union_denominator(self):
        # 3 rows trip both axes: per-axis rates are 30% each, union is 30% (not 60%).
        a_rows = arm("raw_shell", [{} for _ in range(10)])
        d_rows = arm("verseshell_aci", [
            {"completion": 1, "turns": CAP} for _ in range(3)
        ] + [{} for _ in range(7)])
        policy = self.compare(a_rows, d_rows)
        axes = policy["per_arm"]["verseshell_aci"]["budget_axes"]
        self.assertEqual(axes["union"], 3)
        self.assertEqual(policy["per_arm"]["verseshell_aci"]["cap_truncated_rate"], 0.3)
        self.assertFalse(policy["comparisons"]["verseshell_aci_vs_raw_shell"]["claimable"])

    def test_both_arms_clean_is_not_blocked_by_the_budget_rule(self):
        a_rows = arm("raw_shell", [{"success": True} for _ in range(10)])
        d_rows = arm("verseshell_aci", [{"success": True} for _ in range(10)])
        policy = self.compare(a_rows, d_rows)
        comparison = policy["comparisons"]["verseshell_aci_vs_raw_shell"]
        self.assertNotIn("exclusion_rate_above_10pct", comparison["policy_blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
