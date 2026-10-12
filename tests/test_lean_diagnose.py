import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import lean_diagnose as lean


class LeanDiagnoseTests(unittest.TestCase):
    def test_default_command_is_small_and_not_formal(self):
        args = lean.argparse.Namespace(
            tag="lean", env_file=Path("env"), model="m", task_set=Path("tasks.json"),
            tasks=lean.DEFAULT_TASKS, prompt_variant="baseline", order_seed=42, seed=42,
            arms="with", conditions=lean.DEFAULT_CONDITIONS, repeat_call_limit=3,
            max_turns=24, max_tokens=16384, analysis_plan=None, preflight=None,
            probe_report=None, dry_run=False)
        cmd = lean.build_command(args)
        joined = " ".join(cmd)
        self.assertNotIn("--analysis-plan", joined)
        self.assertNotIn("--publish", joined)
        self.assertEqual(cmd[cmd.index("--tasks") + 1], lean.DEFAULT_TASKS)
        self.assertEqual(cmd[cmd.index("--seeds") + 1], "42")

    def test_summary_counts_failure_locations_and_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs = root / "obs" / "q.json"
            obs.parent.mkdir()
            obs.write_text(json.dumps({"envelope": {"ok": True}}), encoding="utf-8")
            rows = [{
                "task_id": "t", "condition": "raw_shell", "prompt_variant": "baseline",
                "success": False, "stop_reason": "repeat_call_limit", "turns": 24,
                "tool_calls": 10, "completion_truncated_turns": 1, "api_error": False,
                "trajectory": [{"op": "result.query", "args": {"handle": "result://sha256/" + "a" * 64},
                               "observation": {"path": "obs/q.json"}}],
            }]
            summary = lean.summarize_rows(rows, 24, 16384, root)
        self.assertEqual(summary["success"], {"false": 1})
        self.assertEqual(summary["stop_reasons"], {"repeat_call_limit": 1})
        self.assertEqual(summary["completion_truncated_turns"], 1)
        self.assertEqual(summary["turn_capped_rows"], 1)
        self.assertEqual(summary["result_query_ok"], 1)
        self.assertEqual(summary["result_query_handle_forms"], {"canonical": 1})
        self.assertEqual(summary["cells"][0]["failure_class"], "pre_success_repeat_loop")


if __name__ == "__main__":
    unittest.main()
