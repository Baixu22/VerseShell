import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "bench" / "aci" / "runners")]
import replay_failure_commands as replay  # noqa: E402


class LoadRowsTests(unittest.TestCase):
    def test_reads_jsonl_and_json_rows(self):
        rows = [
            {"task_id": "a", "condition": "raw_shell", "prompt_variant": "baseline",
             "seed": 42, "stop_reason": "turn_limit", "success": False, "trajectory": []},
            {"task_id": "b", "condition": "raw_shell", "prompt_variant": "baseline",
             "seed": 42, "stop_reason": "task_complete", "success": True, "trajectory": []},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "rows.jsonl"
            jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            self.assertEqual(replay.load_rows(jsonl), rows)

            payload = Path(tmp) / "run.json"
            payload.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            self.assertEqual(replay.load_rows(payload), rows)


class SelectCellsTests(unittest.TestCase):
    def _args(self, **overrides):
        base = dict(task=None, condition=None, variant=None, seed=None, include_complete=False)
        base.update(overrides)
        return replay.argparse.Namespace(**base)

    def test_default_skips_complete_and_filters(self):
        rows = [
            {"task_id": "a", "condition": "raw_shell", "prompt_variant": "baseline",
             "seed": 42, "stop_reason": "turn_limit"},
            {"task_id": "a", "condition": "raw_shell", "prompt_variant": "baseline",
             "seed": 42, "stop_reason": "task_complete"},
            {"task_id": "b", "condition": "verseshell_aci", "prompt_variant": "compact_all",
             "seed": 7, "stop_reason": "repeat_call_limit"},
        ]
        self.assertEqual([r["task_id"] for r in replay.select_cells(rows, self._args())], ["a", "b"])
        self.assertEqual(
            [r["task_id"] for r in replay.select_cells(rows, self._args(include_complete=True))],
            ["a", "a", "b"])
        self.assertEqual(
            [r["task_id"] for r in replay.select_cells(rows, self._args(condition=["verseshell_aci"]))],
            ["b"])
        self.assertEqual(
            [r["task_id"] for r in replay.select_cells(rows, self._args(variant=["compact_all"]))],
            ["b"])
        self.assertEqual(
            [r["task_id"] for r in replay.select_cells(rows, self._args(seed=7))],
            ["b"])
        self.assertEqual(
            [r["task_id"] for r in replay.select_cells(rows, self._args(task=["a"]))],
            ["a"])

    def test_rows_without_task_id_are_ignored(self):
        rows = [{"condition": "raw_shell", "stop_reason": "turn_limit"},
                {"task_id": "a", "condition": "raw_shell", "prompt_variant": "baseline",
                 "seed": 1, "stop_reason": "turn_limit"}]
        self.assertEqual([r["task_id"] for r in replay.select_cells(rows, self._args())], ["a"])


class ReplayCommandTests(unittest.TestCase):
    def test_success_and_failure_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "ok.py").write_text("print('ok')\n", encoding="utf-8")
            (ws / "fail.py").write_text("import sys\nsys.exit(5)\n", encoding="utf-8")
            ok = replay.replay_command(f"{sys.executable} ok.py", ws, 30)
            fail = replay.replay_command(f"{sys.executable} fail.py", ws, 30)
        self.assertEqual(ok["exit_code"], 0)
        self.assertFalse(ok["syntax_error"])
        self.assertEqual(fail["exit_code"], 5)

    def test_syntax_error_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "bad.py").write_text("def (\n", encoding="utf-8")
            record = replay.replay_command(f"{sys.executable} bad.py", ws, 30)
        self.assertNotEqual(record["exit_code"], 0)
        self.assertTrue(record["syntax_error"])


class MainTests(unittest.TestCase):
    def test_dry_run_writes_report_without_executing(self):
        rows = [{"task_id": "js_leaderboard_rank_b1603acf", "condition": "raw_shell",
                 "prompt_variant": "baseline", "seed": 42, "stop_reason": "turn_limit",
                 "success": False,
                 "trajectory": [{"op": "run_command", "args": {"command": "dir"}}]}]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "rows.jsonl"
            src.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            out = Path(tmp) / "out"
            rc = replay.main(["--input", str(src), "--out-dir", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads((out / "replay.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["execute"])
            self.assertEqual(payload["cells"][0]["replay_success"], None)
            self.assertTrue((out / "replay.md").exists())

    def test_no_matching_cells_errors(self):
        rows = [{"task_id": "js_leaderboard_rank_b1603acf", "condition": "raw_shell",
                 "prompt_variant": "baseline", "seed": 42, "stop_reason": "task_complete",
                 "success": True, "trajectory": []}]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "rows.jsonl"
            src.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            out = Path(tmp) / "out"
            with self.assertRaises(SystemExit):
                replay.main(["--input", str(src), "--out-dir", str(out)])


if __name__ == "__main__":
    unittest.main()
