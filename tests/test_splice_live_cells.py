"""P1-3 regression tests: local temporary runs and mocked model calls only."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench/aci/runners"))
import splice_live_cells as splice


class SpliceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tasks = self.root / "tasks"
        self.tasks.mkdir()
        self.path = self.root / "run.json"
        self.payload = {"schema": "test", "live_config": {
            "model": "offline", "api_base": "invalid://offline", "max_turns": 20,
            "max_tokens": 8192, "temperature": 0.25, "seed": 42,
            "caps": "file.read", "exclude_tools": ["read_files"]},
            "rows": [self.row("first", True), self.row("second", True)]}
        for row in self.payload["rows"]:
            (self.tasks / (row["task_id"] + ".json")).write_text(json.dumps({"id": row["task_id"]}), encoding="utf-8")
        self.save()

    def row(self, task, error, success=True):
        return {"task_id": task, "condition": "raw_shell", "model": "offline", "api_error": error,
                "success": False if error else success, "tool_calls": 1, "observation_tokens": 10,
                "elapsed_ms": 5, "run_index": 0, "seed": 43, "source_run": "original.json",
                "turns": 1, "trajectory": [], "last_error": "offline 502" if error else None}

    def save(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")

    def invoke(self, responses, args=(), env=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(splice, "ROOT", self.root), patch.object(splice, "TASKS_DIR", self.tasks),                 patch.dict(os.environ, env or {}, clear=True),                 patch.object(splice, "run_agent_loop", side_effect=responses) as model,                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = splice.main([str(self.path), *args])
        return code, model, stdout.getvalue() + stderr.getvalue()

    def test_success_survives_later_endpoint_failure(self):
        code, model, output = self.invoke([self.row("first", False), self.row("second", True)],
                                          ["--api-key", "offline-cli-key"])
        self.assertEqual(code, 2)
        result = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertFalse(result["rows"][0]["api_error"])
        self.assertTrue(result["rows"][1]["api_error"])
        self.assertEqual(result["live_config"]["api_error_rows"], 1)
        self.assertTrue(result["partial"])
        self.assertIn("second", output)
        self.assertNotIn("offline-cli-key", output)
        self.assertEqual(model.call_args_list[0].kwargs["max_tokens"], 8192)
        self.assertEqual(model.call_args_list[0].kwargs["seed"], 43)
        self.assertEqual(model.call_args_list[0].kwargs["exclude_tools"], ("read_files",))
        code, model, _ = self.invoke([self.row("second", False)], ["--api-key", "offline-cli-key"])
        self.assertEqual(code, 0)
        self.assertEqual(model.call_count, 1)
        result = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertFalse(result["partial"])
        self.assertEqual(result["live_config"]["api_error_rows"], 0)
        self.assertTrue(all(r["row_class"] == "analysable" for r in result["rows"]))

    def test_aci_env_file_and_explicit_precedence(self):
        (self.root / ".env.local").write_text('# local\nACI_BENCH_API_KEY="offline-file-key"\n', encoding="utf-8")
        for args, env, expected in [([], {}, "offline-file-key"),
                                   ([], {"ACI_BENCH_API_KEY": "offline-env-key"}, "offline-env-key"),
                                   (["--api-key", "offline-cli-key"], {"ACI_BENCH_API_KEY": "offline-env-key"}, "offline-cli-key")]:
            with self.subTest(expected=expected):
                self.save()
                code, model, output = self.invoke([self.row("first", False), self.row("second", False)], args, env)
                self.assertEqual(code, 0)
                self.assertEqual(model.call_args_list[0].kwargs["api_key"], expected)
                self.assertNotIn(expected, output)

    def test_explicit_empty_key_does_not_fall_back(self):
        code, model, _ = self.invoke([], ["--api-key", ""], {"ACI_BENCH_API_KEY": "offline-env-key"})
        self.assertEqual(code, 1)
        model.assert_not_called()

    def test_failure_messages_redact_selected_key(self):
        key = "offline-secret-key"
        error = self.row("first", True)
        error["last_error"] = "rejected token " + key
        code, _, output = self.invoke([error, RuntimeError("token " + key)], ["--api-key", key])
        self.assertEqual(code, 2)
        self.assertNotIn(key, output)
        self.assertIn("[REDACTED]", output)

    def test_later_cells_run_after_failure_and_model_failure_is_saved(self):
        code, model, _ = self.invoke([RuntimeError("offline failure"), self.row("second", False, success=False)],
                                     ["--api-key", "offline-key"])
        self.assertEqual(code, 2)
        self.assertEqual(model.call_count, 2)
        result = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertFalse(result["rows"][1]["api_error"])
        self.assertIs(result["rows"][1]["success"], False)

    def test_checkpoint_exists_before_next_model_call(self):
        def response(task, *args, **kwargs):
            if task["id"] == "second":
                self.assertFalse(json.loads(self.path.read_text(encoding="utf-8"))["rows"][0]["api_error"])
            return self.row(task["id"], False)
        self.assertEqual(self.invoke(response, ["--api-key", "offline-key"])[0], 0)

    def test_missing_budget_or_merged_input_never_calls_model(self):
        for change in ("max_tokens", "merged"):
            with self.subTest(change=change):
                original = copy.deepcopy(self.payload)
                if change == "max_tokens":
                    del self.payload["live_config"]["max_tokens"]
                else:
                    self.payload["live_config"]["merged_from"] = ["a.json", "b.json"]
                self.save()
                before = self.path.read_bytes()
                code, model, _ = self.invoke([], ["--api-key", "offline-key"])
                self.assertNotEqual(code, 0)
                model.assert_not_called()
                self.assertEqual(self.path.read_bytes(), before)
                self.payload = original

    def test_failed_replace_preserves_original_file(self):
        before = self.path.read_bytes()
        with patch.object(splice.os, "replace", side_effect=OSError("offline disk failure")):
            code, _, _ = self.invoke([self.row("first", False)], ["--api-key", "offline-key"])
        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
