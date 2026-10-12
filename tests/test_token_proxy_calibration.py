"""Offline regression tests for tools/token_proxy_calibration.py.

These tests never touch the network and never call a model endpoint. The real
tokenizer is resolved with ``allow_download=False`` (tiktoken's local cache); when
no real tokenizer is reachable the tokenizer-dependent assertions are SKIPPED,
while the byte-invariant logic itself is tokenizer-independent and is always
asserted (here and in the negative controls).

Run with:
    python -m unittest discover -s tests -p "test_*.py"
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "token_proxy_calibration.py"
OFFLINE_ARTIFACT = (
    ROOT / "audit-r12-scratch" / "repair-p2-5-2026-09-29"
    / "token_proxy_calibration.offline.json"
)


def load_calibration_module():
    """Load the tool by file path. No network, no endpoint, no writes."""
    spec = importlib.util.spec_from_file_location(
        "token_proxy_calibration_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAL = load_calibration_module()

# A CJK observation: 40 characters, 120 UTF-8 bytes, and (with cl100k_base) more
# real tokens than characters. This is the D2 counterexample shape.
CJK_TEXT = "这是一个用于校准分词器代理的中文段落。观测文本往往包含中文注释、错误信息以及路径名称。"


def fake_counter(text: str) -> int:
    """A deterministic, tokenizer-independent byte-level BPE stand-in."""
    return max(1, len(text.encode("utf-8")) // 3)


def measured_panel_rows(counter) -> list[dict]:
    """The SHAPE_PANEL measured the way the tool measures it."""
    return [
        {
            "name": name,
            "chars": len(text),
            "utf8_bytes": len(text.encode("utf-8")),
            "real_tokens": counter(text),
            "proxy_tokens": CAL.proxy_estimate(text),
            "char_class": CAL.classify_text(text)["char_class"],
        }
        for name, text in CAL.SHAPE_PANEL
    ]


def observation(*, real_tokens, utf8_bytes, chars, name="synthetic") -> dict:
    """A minimal measured observation for the tokenizer-independent checks."""
    return {
        "name": name,
        "chars": chars,
        "utf8_bytes": utf8_bytes,
        "real_tokens": real_tokens,
        "proxy_tokens": max(1, chars // 4),
    }


class RealTokenizerMixin:
    def real_counter(self):
        counter, info = CAL.resolve_tokenizer(allow_download=False)
        if info.get("is_approximation"):
            self.skipTest(
                "no real tokenizer available offline (tier 4 approximation); "
                "tokenizer-dependent assertion skipped"
            )
        return counter, info


class UnicodeByteInvariantTests(RealTokenizerMixin, unittest.TestCase):
    def test_cjk_real_tokens_exceed_chars_but_never_exceed_utf8_bytes(self):
        counter, _info = self.real_counter()
        chars = len(CJK_TEXT)
        utf8_bytes = len(CJK_TEXT.encode("utf-8"))
        real = counter(CJK_TEXT)
        self.assertGreater(real, chars,
                           "cl100k_base must split some CJK characters into >1 token")
        self.assertLessEqual(real, utf8_bytes,
                             "a byte-level BPE can never emit more tokens than bytes")

    def test_byte_invariant_holds_and_chars_bound_is_not_an_invariant(self):
        counter, _info = self.real_counter()
        panel = measured_panel_rows(counter)
        inv = CAL.build_tokenizer_invariants([], panel)

        self.assertTrue(inv["real_tokens_never_exceed_utf8_bytes"])
        detail = inv["byte_invariant_detail"]
        self.assertEqual(detail["n_violations"], 0)
        self.assertEqual(detail["n_checked"], len(panel))
        self.assertIn("utf8_bytes", detail["claim"])

        # The chars comparison is kept, but explicitly NOT an invariant.
        self.assertTrue(inv["chars_bound_is_not_an_invariant"])
        chars_obs = inv["chars_bound_observed"]
        self.assertFalse(chars_obs["is_an_invariant"])
        self.assertTrue(chars_obs["chars_bound_is_not_an_invariant"])
        self.assertIn("RETRACTED", chars_obs["status"])
        self.assertFalse(chars_obs["observed_holds"])

        named = chars_obs["named_panel_counterexample"]
        self.assertIsNotNone(named, "the panel counterexample must be named")
        self.assertEqual(named["name"], "cjk_paragraph")
        self.assertGreater(named["real_tokens"], named["chars"])
        self.assertLessEqual(named["real_tokens"], named["utf8_bytes"])
        self.assertGreaterEqual(chars_obs["violations_by_source"]["shape_panel"], 1)

        # The old key is retained (type-stable) rather than silently dropped.
        self.assertIn("real_tokens_never_exceed_chars", inv)
        self.assertEqual(inv["real_tokens_never_exceed_chars"],
                         chars_obs["observed_holds"])

    def test_byte_invariant_is_tokenizer_independent(self):
        # Even with no real tokenizer, the invariant logic over injected
        # observations must hold: real <= utf8_bytes, and a char-bound failure is
        # only an observation.
        rows = [
            observation(real_tokens=284, utf8_bytes=804, chars=278, name="cjk_like"),
            observation(real_tokens=5, utf8_bytes=12, chars=12, name="tiny_json"),
        ]
        inv = CAL.build_tokenizer_invariants([], rows)
        self.assertTrue(inv["real_tokens_never_exceed_utf8_bytes"])
        self.assertFalse(inv["chars_bound_observed"]["observed_holds"])
        self.assertEqual(inv["chars_bound_observed"]["violations"], 1)


class FullTextMeasurementTests(RealTokenizerMixin, unittest.TestCase):
    LIMIT = 64

    def long_text(self) -> str:
        # Mixed scripts + ASCII so the full-text count and the truncated-copy
        # count are demonstrably different.
        return ("这是一个用于校准分词器代理的中文段落。" * 8) + ("abcdefghij" * 20)

    def test_all_metrics_come_from_the_full_text_not_the_stored_copy(self):
        text = self.long_text()
        self.assertGreater(len(text), self.LIMIT)
        sample = CAL.build_sample(
            text, condition="synthetic", op="op", task_id="t1", source_run="r1",
            cell_index=0, max_stored_text=self.LIMIT,
        )
        counter = fake_counter
        full_text = CAL.measure_sample(sample, counter, primary="fake")

        self.assertEqual(full_text, text)
        self.assertEqual(sample["chars"], len(text))
        self.assertEqual(sample["utf8_bytes"], len(text.encode("utf-8")))
        self.assertEqual(sample["proxy_tokens"], max(1, len(text) // 4))
        self.assertEqual(sample["real_tokens"], counter(text))

        # The stored text is ONLY the display copy.
        self.assertEqual(sample["text"], text[: self.LIMIT])
        self.assertEqual(sample["artifact_text_chars"], self.LIMIT)
        self.assertTrue(sample["text_truncated_in_artifact"])
        self.assertEqual(sample["text_truncated_in_artifact"],
                         sample["chars"] > self.LIMIT)
        # The truncated copy would have produced a different count: the old defect
        # is visible, not hidden.
        self.assertNotEqual(sample["real_tokens"], counter(sample["text"]))

        # measured_* mirrors describe the full text, and the consistency check agrees.
        self.assertEqual(sample["measured_chars"], len(text))
        self.assertEqual(sample["measured_utf8_bytes"], len(text.encode("utf-8")))
        self.assertEqual(sample["measured_text_sha256"],
                         hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(sample["measured_text_sha256"], sample["text_sha256"])
        self.assertTrue(sample["measured_text_is_full_text"])
        self.assertEqual(sample["measurement_skip_reason"], None)
        consistency = CAL.measurement_consistency(sample)
        self.assertTrue(consistency["checked"])
        self.assertTrue(consistency["ok"], consistency)

    def test_short_text_has_no_truncated_copy_and_still_measures_the_full_text(self):
        text = "short observation"
        sample = CAL.build_sample(
            text, condition="synthetic", op="op", task_id="t1", source_run="r1",
            cell_index=0, max_stored_text=self.LIMIT,
        )
        CAL.measure_sample(sample, fake_counter, primary="fake")
        self.assertFalse(sample["text_truncated_in_artifact"])
        self.assertEqual(sample["text"], text)
        self.assertEqual(sample["real_tokens"], fake_counter(text))
        self.assertTrue(CAL.measurement_consistency(sample)["ok"])

    def test_missing_stored_text_is_explicit_none_never_zero(self):
        sample = CAL.build_sample(
            None, condition="raw_shell", op="op", task_id="t1", source_run="r1",
            cell_index=3, max_stored_text=self.LIMIT,
        )
        self.assertEqual(sample["measurement_skip_reason"], "no_stored_text")
        for key in ("chars", "utf8_bytes", "real_tokens", "proxy_tokens"):
            self.assertIsNone(sample[key], f"{key} must be None, not 0")
        self.assertIsNone(sample["text"], "no stored text means no artifact copy")
        self.assertFalse(sample["text_truncated_in_artifact"])

        CAL.measure_sample(sample, fake_counter, primary="fake")
        self.assertIsNone(sample["real_tokens"], "an unmeasured sample must stay None")
        self.assertEqual(sample["measurement_skip_reason"], "no_stored_text")

        consistency = CAL.measurement_consistency(sample)
        self.assertFalse(consistency["checked"])
        self.assertIsNone(consistency["ok"])
        self.assertEqual(consistency["reason"], "no_stored_text")

        # An unmeasured sample is excluded from the aggregate, not scored as 0.
        agg = CAL.aggregate([sample])
        self.assertEqual(agg["overall"]["n_scored"], 0)
        self.assertEqual(agg["overall"]["n_samples"], 1)
        self.assertIsNone(agg["overall"]["chars_per_real_token"])
        self.assertNotEqual(agg["overall"]["chars_per_real_token"], 0)

    def test_missing_recorded_usage_is_explicit_not_coerced(self):
        text = "an observation with no recorded usage"
        sample = CAL.build_sample(
            text, condition="verseshell_aci", op="op", task_id="t1", source_run="r1",
            cell_index=0, max_stored_text=self.LIMIT, recorded_proxy_tokens=None,
        )
        self.assertEqual(sample["recorded_usage_skip_reason"], "no_recorded_usage")
        self.assertIsNone(sample["recorded_proxy_tokens"])
        self.assertIsNone(sample["proxy_matches_recorded"],
                          "no recorded usage must not be compared as 0")

        sample2 = CAL.build_sample(
            text, condition="verseshell_aci", op="op", task_id="t1", source_run="r1",
            cell_index=1, max_stored_text=self.LIMIT, recorded_proxy_tokens=99,
        )
        self.assertIsNone(sample2["recorded_usage_skip_reason"])
        self.assertFalse(sample2["proxy_matches_recorded"])


class RatioCheckBucketTests(unittest.TestCase):
    @staticmethod
    def cell(condition, task_id, source_run, real, proxy, chars=None):
        return {
            "condition": condition,
            "task_id": task_id,
            "source_run": source_run,
            "real_tokens": real,
            "proxy_tokens": proxy,
            "chars": chars if chars is not None else max(1, real * 4),
        }

    def samples(self) -> list[dict]:
        return [
            # bucket 1: agree (D/A > 1 on both calibers)
            self.cell("raw_shell", "T1", "r1", 10, 10),
            self.cell("verseshell_aci", "T1", "r1", 100, 100),
            # bucket 2: agree (D/A < 1 on both)
            self.cell("raw_shell", "T1", "r2", 100, 100),
            self.cell("verseshell_aci", "T1", "r2", 10, 10),
            # bucket 3: DISAGREE (real D/A < 1, proxy D/A > 1)
            self.cell("raw_shell", "T2", "r1", 100, 100),
            self.cell("verseshell_aci", "T2", "r1", 50, 200),
            # unpaired bucket: A only, must never be merged into another bucket
            self.cell("raw_shell", "T3", "r1", 7, 7),
        ]

    def test_pairs_only_within_task_and_source_run_buckets(self):
        rc = CAL.build_ratio_check(self.samples(), 0.8855)

        self.assertTrue(rc["supported"])
        buckets = {(u["task_id"], u["source_run"]) for u in rc["per_unit"]}
        self.assertEqual(buckets, {("T1", "r1"), ("T1", "r2"), ("T2", "r1")})
        self.assertNotIn(("T3", "r1"), buckets,
                         "a bucket missing one condition must not be paired")

        # Totals are the sum over paired buckets only; the unpaired A cell is not
        # silently added to any bucket.
        self.assertEqual(rc["totals"]["real_tokens_A"], 210)
        self.assertEqual(rc["totals"]["real_tokens_D"], 160)
        self.assertEqual(rc["totals"]["proxy_tokens_A"], 210)
        self.assertEqual(rc["totals"]["proxy_tokens_D"], 310)

        scope = rc["sample_scope"]
        self.assertEqual(scope["pairing_unit"], "(task_id, source_run)")
        self.assertTrue(scope["pairs_only_within_the_same_bucket"])
        self.assertEqual(scope["n_paired_units"], 3)
        self.assertEqual(scope["n_observations_paired"], 6)
        self.assertEqual(scope["cells_replayable_but_unpaired"], 1)
        self.assertFalse(scope["is_the_whole_benchmark_round"])

        # Deployment of the old keys is preserved for downstream consumers.
        for key in ("totals", "per_unit", "conclusion", "supported",
                    "direction_agreement", "materiality_threshold_relative",
                    "cells_used", "paired_units"):
            self.assertIn(key, rc)

    def test_reports_per_bucket_direction_disagreement(self):
        rc = CAL.build_ratio_check(self.samples(), 0.8855)
        direction = rc["direction_agreement"]
        self.assertEqual(direction["units"], 3)
        self.assertEqual(direction["units_where_sign_agrees"], 2)
        self.assertEqual(direction["units_where_direction_disagrees"], 1)
        self.assertTrue(direction["pairs_only_within_the_same_bucket"])

        disagreeing = direction["disagreeing_units"]
        self.assertEqual(len(disagreeing), 1)
        unit = disagreeing[0]
        self.assertEqual((unit["task_id"], unit["source_run"]), ("T2", "r1"))
        self.assertLess(unit["real_ratio_D_over_A"], 1)
        self.assertGreater(unit["proxy_ratio_D_over_A"], 1)
        # The report names the exact bucket, and no cell leaks across buckets.
        self.assertEqual(unit["real_tokens_D"], 50)
        self.assertEqual(unit["proxy_tokens_D"], 200)

    def test_published_ratio_is_labelled_historical_and_scope_is_a_subset(self):
        rc = CAL.build_ratio_check(self.samples(), 0.8855)
        self.assertEqual(rc["published_proxy_ratio_D_over_A"], 0.8855)
        prov = rc["published_proxy_ratio_provenance"]
        self.assertEqual(prov["value"], 0.8855)
        self.assertFalse(prov["is_the_current_whole_round_baseline"])
        self.assertFalse(prov["provenance_verified"])
        self.assertIn("historical", prov["caliber"])
        self.assertIn("must_not_be_combined_with", prov)
        self.assertIn("totals", prov["must_not_be_combined_with"])
        note = rc["sample_scope"]["note"]
        self.assertIn("subset", note)
        self.assertIn("(task_id, source_run)", note)


class NegativeControlTests(RealTokenizerMixin, unittest.TestCase):
    def test_forged_byte_invariant_violation_flips_the_check(self):
        clean = observation(real_tokens=284, utf8_bytes=804, chars=278, name="cjk_like")
        self.assertTrue(CAL.build_tokenizer_invariants([], [clean])[
            "real_tokens_never_exceed_utf8_bytes"])

        forged = observation(real_tokens=900, utf8_bytes=804, chars=278, name="forged")
        inv = CAL.build_tokenizer_invariants([], [clean, forged])
        self.assertFalse(inv["real_tokens_never_exceed_utf8_bytes"])
        detail = inv["byte_invariant_detail"]
        self.assertEqual(detail["n_violations"], 1)
        self.assertEqual(detail["violations"][0]["name"], "forged")

    def test_truncated_copy_measurement_inconsistency_is_caught(self):
        text = ("这是一个用于校准分词器代理的中文段落。" * 8) + ("abcdefghij" * 20)
        sample = CAL.build_sample(
            text, condition="synthetic", op="op", task_id="t1", source_run="r1",
            cell_index=0, max_stored_text=64,
        )
        CAL.measure_sample(sample, fake_counter, primary="fake")
        self.assertTrue(CAL.measurement_consistency(sample)["ok"])

        # Simulate the D1 defect: the metadata describes the full text but the
        # measured mirrors describe the truncated artifact copy.
        stored = sample["text"]
        sample["measured_chars"] = len(stored)
        sample["measured_utf8_bytes"] = len(stored.encode("utf-8"))
        sample["measured_text_sha256"] = hashlib.sha256(stored.encode("utf-8")).hexdigest()
        sample["real_tokens"] = fake_counter(stored)
        sample["measured_text_is_full_text"] = True  # a lying label

        consistency = CAL.measurement_consistency(sample)
        self.assertTrue(consistency["checked"])
        self.assertFalse(consistency["ok"],
                         "a measurement taken on the truncated copy must be caught")
        self.assertFalse(consistency["checks"]["metrics_measured_on_the_full_text"])

    def test_real_tokenizer_counts_agree_with_full_text_measurement(self):
        counter, info = self.real_counter()
        text = ("这是一个用于校准分词器代理的中文段落。" * 8) + ("abcdefghij" * 20)
        sample = CAL.build_sample(
            text, condition="synthetic", op="op", task_id="t1", source_run="r1",
            cell_index=0, max_stored_text=64,
        )
        CAL.measure_sample(sample, counter, primary=info["primary"])
        self.assertEqual(sample["real_tokens"], counter(text))
        self.assertGreater(sample["real_tokens"], counter(sample["text"]))
        self.assertTrue(sample["real_tokens"] <= sample["utf8_bytes"])
        self.assertTrue(CAL.measurement_consistency(sample)["ok"])

    def test_offline_resolution_never_attempts_a_download(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError(
                "resolve_tokenizer(allow_download=False) reached the downloader"
            )

        original = CAL.download_cl100k
        CAL.download_cl100k = forbidden
        try:
            _counter, info = CAL.resolve_tokenizer(allow_download=False)
        finally:
            CAL.download_cl100k = original
        self.assertIn(info["tier"], (1, 2, 4))
        self.assertTrue(info["primary"])
        # The downloader was never reached (``forbidden`` would have raised). When
        # no local tier resolved, the tier-3 attempt must be recorded as disabled.
        if info["tier"] == 4:
            tier3 = [a for a in info["attempts"] if a["tier"] == 3]
            self.assertTrue(tier3)
            self.assertFalse(tier3[0]["ok"])
            self.assertEqual(tier3[0]["error"], "disabled by --no-download")


class DownstreamContractTests(unittest.TestCase):
    def _agg_and_verdict(self):
        rows = measured_panel_rows(fake_counter)
        agg = CAL.aggregate([], panel=rows)
        anchor = {
            "chars": 400, "proxy_tokens": 100, "real_tokens": 100,
            "expected_real_range": [80, 120], "within_expected_range": True,
        }
        cross = {"draws_per_text": 0, "n_stable": 0, "n_texts": 1,
                 "conclusion": "endpoint cross-check disabled (--no-endpoint)"}
        tokenizer = {"primary": "fake", "is_approximation": False}
        return agg, CAL.build_verdict(agg, cross, tokenizer, anchor)

    def test_verdict_keeps_the_keys_claim_gate_c27_reads(self):
        agg, verdict = self._agg_and_verdict()
        for key in ("a_error_direction", "b_error_magnitude", "c_upper_bound",
                    "d_cache_hazard_and_neutralisation"):
            self.assertIsInstance(verdict[key], str)
            self.assertTrue(verdict[key])
        self.assertIsInstance(verdict["anchor_check"]["within_expected_range"], bool)
        self.assertIn("n_scored", agg["overall"])

    def test_verdict_states_the_proxy_is_not_a_bound_and_has_no_single_factor(self):
        agg, verdict = self._agg_and_verdict()
        for key in ("e_no_single_correction_factor", "f_tokenizer_byte_invariant",
                    "g_chars_bound_retracted", "h_caliber"):
            self.assertIsInstance(verdict[key], str)
            self.assertTrue(verdict[key])
        self.assertIn("not a bound", verdict["c_upper_bound"])
        self.assertIn("no single correction factor",
                      verdict["e_no_single_correction_factor"])
        self.assertIn("utf8_bytes", verdict["f_tokenizer_byte_invariant"])
        self.assertIn("NOT an invariant", verdict["g_chars_bound_retracted"])

    def test_caliber_labels_cover_every_published_metric(self):
        for metric in ("proxy_tokens", "real_tokens", "endpoint_tokens", "chars",
                       "utf8_bytes", "recorded_proxy_tokens", "ratio_check"):
            self.assertIn(metric, CAL.CALIBER_LABELS)
            self.assertIn("caliber", CAL.CALIBER_LABELS[metric])
        self.assertFalse(CAL.CALIBER_LABELS["proxy_tokens"]["is_a_real_token_count"])
        self.assertTrue(CAL.CALIBER_LABELS["real_tokens"]["is_a_real_token_count"])
        self.assertTrue(CAL.CALIBER_LABELS["chars"]["is_a_real_token_count"] is False)
        self.assertFalse(CAL.CALIBER_LABELS["endpoint_tokens"]["is_a_cost"])


@unittest.skipUnless(OFFLINE_ARTIFACT.exists(),
                     f"{OFFLINE_ARTIFACT} not generated in this checkout")
class GeneratedOfflineArtifactTests(unittest.TestCase):
    """Contract check against the regenerated offline calibration artifact."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(OFFLINE_ARTIFACT.read_text(encoding="utf-8"))

    def test_artifact_reports_the_byte_invariant_and_retracted_chars_bound(self):
        doc = self.doc
        inv = doc["aggregate"]["tokenizer_invariants"]
        self.assertTrue(inv["real_tokens_never_exceed_utf8_bytes"])
        self.assertEqual(inv["byte_invariant_detail"]["n_violations"], 0)
        self.assertTrue(inv["chars_bound_is_not_an_invariant"])
        self.assertFalse(inv["chars_bound_observed"]["is_an_invariant"])
        named = inv["chars_bound_observed"]["named_panel_counterexample"]
        self.assertEqual(named["name"], "cjk_paragraph")
        self.assertGreater(named["real_tokens"], named["chars"])
        self.assertTrue(inv["real_tokens_never_exceed_chars"] is False)

    def test_artifact_measured_every_sample_on_the_full_text(self):
        doc = self.doc
        integrity = doc["measurement_integrity"]
        self.assertTrue(integrity["all_measured_on_full_text"])
        self.assertEqual(integrity["measured_on_truncated_copy"], 0)
        self.assertEqual(integrity["n_measured"], integrity["n_samples"])
        for sample in doc["samples"]:
            self.assertNotIn("_measured_text", sample)
            if sample["text_truncated_in_artifact"]:
                self.assertEqual(sample["artifact_text_chars"],
                                 len(sample["text"]))
                self.assertGreater(sample["chars"], len(sample["text"]))
                self.assertEqual(sample["measured_chars"], sample["chars"])
                self.assertEqual(sample["measured_utf8_bytes"], sample["utf8_bytes"])

    def test_artifact_keeps_the_keys_downstream_consumers_read(self):
        doc = self.doc
        verdict = doc["verdict"]
        for key in ("a_error_direction", "b_error_magnitude", "c_upper_bound",
                    "d_cache_hazard_and_neutralisation"):
            self.assertTrue(verdict[key])
        self.assertIn("within_expected_range", verdict["anchor_check"])
        self.assertIn("n_scored", doc["aggregate"]["overall"])
        self.assertFalse(doc["tokenizer"]["is_approximation"])
        self.assertIn("published_proxy_ratio_D_over_A", doc["ratio_check"])
        self.assertIn("published_proxy_ratio_provenance", doc["ratio_check"])
        self.assertFalse(
            doc["ratio_check"]["published_proxy_ratio_provenance"]
            ["is_the_current_whole_round_baseline"])
        self.assertIn("caliber_labels", doc)

    def test_artifact_shape_panel_keeps_the_cjk_counterexample(self):
        panel = {item["name"]: item for item in self.doc["shape_panel"]}
        cjk = panel["cjk_paragraph"]
        self.assertEqual(cjk["chars"], 278)
        self.assertGreater(cjk["real_tokens"], cjk["chars"])
        self.assertLessEqual(cjk["real_tokens"], cjk["utf8_bytes"])
        self.assertEqual(panel["json_minified_tiny"]["text"], '{"ok": true}')


if __name__ == "__main__":
    unittest.main()
