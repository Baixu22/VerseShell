"""Offline P1-1 controls; temporary run artifacts only, no endpoint calls."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "bench/aci/runners"))
import merge_live_runs as merger
import claim_gate as gate
from live_uncertainty import row_class


class PartialMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        row = {"task_id": "offline-task", "model": "offline", "seed": 42, "run_index": 0,
               "success": True, "tool_calls": 2, "observation_tokens": 20, "elapsed_ms": 10,
               "turns": 2, "completion_truncated_turns": 0, "trajectory": [], "last_error": None}
        self.payload = {"schema": "verseshell.aci_bench.results/v1", "task_set_version": "test",
                        "git_rev": "offline", "live_config": {"seed": 42, "max_turns": 20},
                        "rows": [{**row, "condition": c} for c in
                                 ["raw_shell", "raw_shell_coached", "verseshell_aci"]]}
        cfg = self.payload['live_config']
        cfg.update(model='offline', api_base='invalid://offline', protocol='chat_completions',
                   caps='file.read', max_tokens=100, temperature=0, exclude_tools=[],
                   tasks=['offline-task'], conditions=['raw_shell','raw_shell_coached','verseshell_aci'],
                   repeat=1, collection_id='offline-collection')
        self.payload['evidence'] = {'globs':['offline'], 'fingerprint':'acquisition-fingerprint'}
        self.payload['run_identity'] = {k:v for k,v in cfg.items() if k != 'seed'}
        self.payload['run_identity'].update(seeds=[42], task_set_version='test',
                                           evidence=self.payload['evidence'], binary_sha256='offline-binary')
        self.source = self.directory / "source.json"
        self.out = self.directory / "merged.json"

    def merge(self, allow=False):
        self.source.write_text(json.dumps(self.payload), encoding="utf-8")
        args = [str(self.source), "--out", str(self.out)]
        if allow:
            args.append("--allow-api-errors")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(merger, "current_git_rev", return_value="offline"),                 patch.object(merger, "evidence_fingerprint", return_value="offline"),                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = merger.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def fail_raw(self):
        self.payload["rows"][0].update(api_error=True, success=False, tool_calls=0,
                                       last_error="HTTP 502 offline probe")

    def test_partial_labels_rows_and_does_not_score_endpoint_as_failure(self):
        self.fail_raw()
        self.assertEqual(self.merge(allow=True)[0], 0)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertIs(result.get("partial"), True)
        for row in result["rows"]:
            self.assertEqual(row["row_class"], row_class(row, 20))
        failed = result["rows"][0]
        self.assertIsNone(failed["success"])
        self.assertIs(failed["raw_success"], False)
        raw = next(a for a in result["aggregate"]["aggregates"] if a["condition"] == "raw_shell")
        self.assertEqual(raw["scored_rows"], 0)
        self.assertIsNone(raw["success_rate"])
        for comparison in result["comparison"]["comparisons"]:
            self.assertFalse(comparison["meets_acceptance"])
            self.assertFalse(comparison["claimable"])

    def test_endpoint_does_not_reduce_verified_success_rate(self):
        self.fail_raw()
        good = {**self.payload["rows"][0], "task_id": "verified-task", "success": True,
                "api_error": False, "last_error": None}
        self.payload["rows"].append(good)
        self.payload['live_config']['tasks'].append('verified-task')
        self.assertEqual(self.merge(allow=True)[0], 0)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        raw = next(a for a in result["aggregate"]["aggregates"] if a["condition"] == "raw_shell")
        self.assertEqual((raw["tasks"], raw["scored_rows"], raw["success_rate"]), (2, 1, 1.0))

    def test_strict_merge_rejects_errors_and_writes_nothing(self):
        self.fail_raw()
        code, _, stderr = self.merge()
        self.assertEqual(code, 2)
        self.assertIn("offline-task", stderr)
        self.assertFalse(self.out.exists())

    def test_clean_default_merge_still_works_and_recomputes_count(self):
        self.payload["live_config"]["api_error_rows"] = 99
        self.assertEqual(self.merge()[0], 0)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertIs(result["partial"], False)
        self.assertEqual(result["live_config"]["api_error_rows"], 0)
        self.assertTrue(all(r["row_class"] == "analysable" for r in result["rows"]))
        self.assertEqual(result["aggregate"], merger.aggregate(self.payload["rows"]))

    def test_remerge_preserves_partial_seed_and_original_success(self):
        self.fail_raw()
        self.merge(allow=True)
        self.payload = json.loads(self.out.read_text(encoding="utf-8"))
        self.payload["live_config"].pop("seed", None)
        self.merge(allow=True)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(result["live_config"]["seeds"], [42])
        self.assertIs(result["rows"][0]["raw_success"], False)
        self.assertEqual(result["rows"][0]["source_run"], "source.json")
        clean = copy.deepcopy(self.payload)
        clean["rows"] = clean["rows"][1:]
        self.payload = clean
        self.merge()
        self.assertIs(json.loads(self.out.read_text(encoding="utf-8"))["partial"], True)

    def test_gate_detects_legacy_error_without_trusting_partial_label(self):
        self.fail_raw()
        self.source.write_text(json.dumps(self.payload), encoding="utf-8")
        details = gate.live_run_composition(self.source)
        self.assertTrue(details["partial"])
        self.assertEqual(details["endpoint_failure_rows"], 1)
        self.assertEqual(details["affected_rows"][0]["task_id"], "offline-task")
        self.assertIn("verseshell_aci_vs_raw_shell", details["affected_comparisons"])
        self.assertIn("with_vs_without/raw_shell", details["affected_comparisons"])

    def test_gate_rejects_incorrect_labels_and_empty_partial_flag(self):
        self.fail_raw()
        self.payload["rows"][0]["row_class"] = "analysable"
        self.source.write_text(json.dumps(self.payload), encoding="utf-8")
        self.assertTrue(gate.live_run_composition(self.source)["row_class_mismatches"])
        self.payload["rows"] = self.payload["rows"][1:]
        self.payload["partial"] = True
        self.source.write_text(json.dumps(self.payload), encoding="utf-8")
        self.assertTrue(gate.live_run_composition(self.source)["partial"])


if __name__ == "__main__":
    unittest.main()
