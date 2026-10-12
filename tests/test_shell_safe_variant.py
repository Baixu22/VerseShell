"""Regression for the opt-in shell_safe raw-shell description arm.

cmd /C runs only the FIRST line of a multi-line command and silently returns
that line's exit code. The frozen baseline description told models to edit
files with python -c, which drove the 2026-10-10 raw-shell failures. The
shell_safe arm removes that inducement WITHOUT touching the frozen baseline, so
C1/C2 and the A/A' control stay comparable.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench/aci/runners"))
import live_agent_loop as h
import live_schedule as sched


def run_desc(condition, variant):
    _, _, tools = h.prompt_and_tools(condition, variant)
    return {t["function"]["name"]: t["function"] for t in tools}["run_command"]["description"]


class ShellSafeVariantTests(unittest.TestCase):
    def test_baseline_description_is_unchanged(self):
        self.assertIn("python -c to write files", run_desc("raw_shell", "baseline"))

    def test_shell_safe_removes_inducement_and_warns_about_multiline(self):
        desc = run_desc("raw_shell", "shell_safe")
        self.assertNotIn("use python -c to write files", desc)
        self.assertIn("FIRST line", desc)
        self.assertIn("cmd /C", desc)
        self.assertIn("PowerShell", desc)

    def test_shell_safe_is_description_only(self):
        _, base_prompt, base_tools = h.prompt_and_tools("raw_shell", "baseline")
        _, safe_prompt, safe_tools = h.prompt_and_tools("raw_shell", "shell_safe")
        self.assertEqual(base_prompt, safe_prompt)
        self.assertEqual({t["function"]["name"] for t in base_tools},
                         {t["function"]["name"] for t in safe_tools})
        b = {t["function"]["name"]: t["function"] for t in base_tools}
        s = {t["function"]["name"]: t["function"] for t in safe_tools}
        for name in b:
            if name == "run_command":
                self.assertNotEqual(b[name]["description"], s[name]["description"])
            else:
                self.assertEqual(b[name], s[name])

    def test_aci_arm_untouched_by_shell_safe(self):
        self.assertEqual(h.prompt_and_tools("verseshell_aci", "baseline"),
                         h.prompt_and_tools("verseshell_aci", "shell_safe"))

    def test_both_shell_conditions_get_the_safe_description(self):
        for condition in ("raw_shell", "raw_shell_coached"):
            self.assertIn("FIRST line", run_desc(condition, "shell_safe"))

    def test_unknown_variant_still_rejected(self):
        with self.assertRaises(ValueError):
            h.prompt_and_tools("raw_shell", "not_a_variant")

    def test_schedule_accepts_shell_safe_and_rejects_unknown(self):
        self.assertIn("shell_safe", sched.VARIANTS)
        schedule = sched.make_schedule(["t1"], ["raw_shell"], [42], ["baseline", "shell_safe"])
        sched.validate_schedule(schedule)
        with self.assertRaises(ValueError):
            sched.make_schedule(["t1"], ["raw_shell"], [42], ["bogus"])


if __name__ == "__main__":
    unittest.main()
