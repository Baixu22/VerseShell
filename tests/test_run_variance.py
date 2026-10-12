"""Exact collection matching: mtime, seed labels and matching averages are insufficient."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import live_uncertainty as uncertainty
import run_variance as variance


class RunVarianceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runs = self.root / "bench/aci/results"
        self.current = self.runs / "current"
        self.published = self.root / "custom-published.json"
        self.out = self.root / "out.json"
        self.rows = []
        for seed in (42, 43, 44):
            rows = [dict(task_id="task", condition=cond, model="test", run_index=0,
                         observation_tokens=tokens, tool_calls=2, success=True)
                    for cond, tokens in (("raw_shell", 20), ("verseshell_aci", 10))]
            self.write(self.current / f"with_seed{seed}.json",
                       {"live_config": {"seed": seed}, "rows": rows})
            self.rows.extend(dict(r, seed=seed, source_run=f"with_seed{seed}.json") for r in rows)
        self.arm = {
            "artifact": "with_read_files", "seeds": [42, 43, 44], "n_rows": len(self.rows),
            "source_rows_fingerprint": uncertainty.rows_fingerprint(self.rows),
            "ratio_bootstrap": {"observation_token_ratio": {"bootstrap_ci95": [0.4, 0.6]}},
        }
        self.publish()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def publish(self):
        self.write(self.published, {"arms": [self.arm]})

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(variance, "ROOT", self.root), contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            rc = variance.main(["--published", str(self.published), "--out", str(self.out), *args])
        return rc, stderr.getvalue()

    def test_discovers_matching_collection_even_when_wrong_round_is_newer(self):
        for source in self.current.glob("*.json"):
            data = json.loads(source.read_text())
            # Same statistics and seeds, different actual measured content.
            data["rows"][0]["elapsed_ms"] = 999
            wrong = self.runs / "newer" / source.name
            self.write(wrong, data)
            os.utime(wrong, (2000000000, 2000000000))
        self.assertEqual(self.invoke()[0], 0)
        out = json.loads(self.out.read_text())
        self.assertEqual(out["run_dir"], "bench/aci/results/current")
        self.assertTrue(out["round_pinning"]["verified"])
        self.assertIn("custom-published.json", out["evidence"]["globs"])
        self.assertEqual(out["findings"]["observation_token_ratio"]["per_seed"], [0.5] * 3)
        rc, message = self.invoke("--run-dir", str(self.runs / "newer"))
        self.assertEqual(rc, 2)
        self.assertIn("do not match", message)

    def test_missing_changed_and_duplicate_rows_fail_without_overwriting_output(self):
        path = self.current / "with_seed43.json"
        original = json.loads(path.read_text())
        for kind in ("missing", "changed", "duplicate", "bad_seed"):
            with self.subTest(kind=kind):
                self.write(path, original)
                self.out.write_text("previous report")
                if kind == "missing":
                    path.unlink()
                else:
                    data = copy.deepcopy(original)
                    if kind == "changed":
                        data["rows"][0]["success"] = False
                    elif kind == "duplicate":
                        data["rows"].append(data["rows"][0])
                    else:
                        data["live_config"]["seed"] = 44
                    self.write(path, data)
                self.assertEqual(self.invoke("--run-dir", str(self.current))[0], 2)
                self.assertEqual(self.out.read_text(), "previous report")

    def test_legacy_published_or_subset_seeds_fail_closed(self):
        for args in (("--seeds", "42,43"), ("--seeds", "42,42,43"), ("--seeds", "bad")):
            self.assertEqual(self.invoke(*args)[0], 2)
        self.arm.pop("source_rows_fingerprint")
        self.publish()
        rc, message = self.invoke()
        self.assertEqual(rc, 2)
        self.assertIn("regenerate", message)
        self.assertFalse(self.out.exists())

    def test_fingerprint_ignores_order_and_derived_class_but_preserves_provenance(self):
        rows = [dict(r, row_class="verified") for r in reversed(self.rows)]
        self.assertEqual(uncertainty.rows_fingerprint(rows), self.arm["source_rows_fingerprint"])
        rows[0]["source_run"] = "another-run.json"
        self.assertNotEqual(uncertainty.rows_fingerprint(rows), self.arm["source_rows_fingerprint"])

    def test_output_must_not_overwrite_input(self):
        before = self.published.read_bytes()
        self.assertEqual(self.invoke("--out", str(self.published))[0], 2)
        self.assertEqual(self.published.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
