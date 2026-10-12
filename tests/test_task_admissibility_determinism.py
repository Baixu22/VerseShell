"""Determinism tests for tools/task_admissibility.py.

`eval/task_admissibility.json` is evidence: two audit runs over the same tree must
produce the same `admissible` verdict and the same `pristine_observation_tokens`.
Two mechanisms broke that (reproduced 2026-09-29):

  * A3 measured each variant ONCE, so a variant whose predicate is itself flaky
    flipped the whole admission decision between runs and no check caught it.
  * `pristine_observation_tokens` counted the RAW dump, which contains temp paths,
    elapsed times, OS thread ids and object addresses -- all volatile.

These tests cover both fixes offline (no network, no model endpoint): the normaliser
is exercised as a pure function, and the stability check is exercised on synthetic
candidates whose predicates are contrived to be flaky / stable by construction.

    python -B -m unittest tests.test_task_admissibility_determinism -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import task_admissibility as admission  # noqa: E402

NORMALISE = admission.normalise_observation

# One sample string per measured volatile class, in the exact shape each produced in
# the 2026-09-29 diff (audit-r12-scratch/repair-c14-c16-2026-09-29/volatile-diff.txt).
VOLATILE_SAMPLES = [
    # the audit's own materialise() workspace, plain / escaped / file:// URL
    r"file:///C:/Users/27933/AppData/Local/Temp/adm-mjs_async_order_525bd589-t8kujyzz/check.mjs:17:10",
    r"C:\Users\27933\AppData\Local\Temp\adm-rust_agegate_626af881-14l1ln1b",
    r"C:\\Users\\27933\\AppData\\Local\\Temp\\adm-rust_dedup_first_unique_f6b48e73-tz02j9ee",
    # pytest / tempfile temp roots
    r"tmp_path = WindowsPath('C:/Users/27933/AppData/Local/Temp/pytest-of-27933/pytest-490/test_blank_lines_are_skipped0')",
    r"rootdir: C:\\Users\\27933\\AppData\\Local\\Temp\\tmpu7g_534a",
    # elapsed times
    "========================= 9 failed, 2 passed in 0.14s =========================",
    "  ✔ orders distinct players by descending points (1.6539ms)",
    "ℹ duration_ms 12.3835",
    # OS thread id in a libtest panic line
    r"thread 'tests::passes_at_exactly_sixty' (38576) panicked at src\lib.rs:17:9:",
    # CPython object address
    "self = <test_turnstile.TestTransitionTable object at 0x00000191F81404F0>",
]

# Dump content that is NOT volatile and must come through byte for byte. These are
# the payloads A8 is actually about: assertion diffs, test names, failure counts.
REAL_CONTENT = """running 9 tests
test tests::single_row ... FAILED
failures:

---- tests::single_row stdout ----

thread 'tests::single_row' panicked at src\\lib.rs:111:9:
assertion `left == right` failed
  left: [1, 2, 3]
 right: [1, 2, 3, 4]
4 failed, 6 passed
ℹ pass 4
ℹ fail 5
Error [ERR_MODULE_NOT_FOUND]: Cannot find module './csvproc'
  left: [6, 2]
 right: [6, 2, 2]
"""

# The two cargo --quiet progress meters are dropped, not substituted: their number of
# LINES varies with test interleaving, so a placeholder per line would not stabilise
# the count.
PROGRESS = "... 3/9\nfirst_hot_window --- FAILED\n. 8/9\n.\n"


class NormaliseObservationTests(unittest.TestCase):
    def test_every_volatile_class_is_stripped(self):
        for sample in VOLATILE_SAMPLES:
            with self.subTest(sample=sample):
                clean = NORMALISE(sample)
                self.assertEqual(
                    NORMALISE(clean), clean,
                    "normalisation must be idempotent")
                self.assertNotEqual(
                    clean, sample,
                    "a measured-volatile sample must be rewritten")
                self.assertIn(
                    "<", clean,
                    "volatile text is replaced by a placeholder, not deleted silently")

    def test_placeholders_are_the_documented_ones(self):
        cases = {
            VOLATILE_SAMPLES[0]: "adm-mjs_async_order_525bd589-<rnd>",
            VOLATILE_SAMPLES[3]: "pytest-of-<user>/pytest-<N>",
            VOLATILE_SAMPLES[4]: "\\tmp<rnd>",
            VOLATILE_SAMPLES[5]: "in <t>s",
            VOLATILE_SAMPLES[6]: "(<t>ms)",
            VOLATILE_SAMPLES[7]: "duration_ms <t>",
            VOLATILE_SAMPLES[8]: "(<tid>)",
            VOLATILE_SAMPLES[9]: "at 0x<addr>",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertIn(expected, NORMALISE(raw))

    def test_two_runs_of_the_same_dump_normalise_to_the_same_length(self):
        # The actual bug: two runs of the SAME candidate differed by a random temp
        # suffix and a timing digit, which moved the 4-char token proxy by 1.
        run_a = (
            "rootdir: C:\\Users\\27933\\AppData\\Local\\Temp\\adm-js_leaderboard_rank_b1603acf-aaaaaaaa\n"
            "✔ orders players (1.6539ms)\n"
            "✖ breaks ties (0.9461ms)\n"
            "2 failed, 1 passed in 0.14s\n"
            "thread 'x' (38056) panicked at src\\lib.rs:1:1:\n"
            "self = <X object at 0x00000191F81404F0>\n")
        run_b = (
            "rootdir: C:\\Users\\27933\\AppData\\Local\\Temp\\adm-js_leaderboard_rank_b1603acf-bbbbbbbb\n"
            "✔ orders players (1.7ms)\n"
            "✖ breaks ties (0.9ms)\n"
            "2 failed, 1 passed in 0.09s\n"
            "thread 'x' (4996) panicked at src\\lib.rs:1:1:\n"
            "self = <X object at 0x000001AA1EB30130>\n")
        self.assertNotEqual(run_a, run_b)
        self.assertEqual(NORMALISE(run_a), NORMALISE(run_b))
        self.assertEqual(len(NORMALISE(run_a)) // 4, len(NORMALISE(run_b)) // 4)

    def test_real_content_is_left_byte_for_byte(self):
        self.assertEqual(NORMALISE(REAL_CONTENT), REAL_CONTENT)

    def test_progress_lines_are_dropped_regardless_of_count(self):
        # Run A printed 2 progress lines, run B printed 3; the failure payload is the
        # same and must normalise to the same text.
        run_a = "... 3/9\nfirst_hot_window --- FAILED\n. 8/9\n"
        run_b = ".. 2/9\nfirst_hot_window --- FAILED\n. 7/9\n.\n"
        self.assertEqual(NORMALISE(run_a), NORMALISE(run_b))
        self.assertEqual(NORMALISE(run_a), "first_hot_window --- FAILED\n")
        self.assertEqual(NORMALISE(PROGRESS), "first_hot_window --- FAILED\n")

    def test_clean_input_is_untouched(self):
        for text in ("", "\n", "all 16 tests passed\n", REAL_CONTENT):
            with self.subTest(text=text):
                self.assertEqual(NORMALISE(text), text)


def _write_candidate(root: Path, counter: Path, *, flake_every: int | None) -> Path:
    """Build a synthetic candidate whose variant predicate can be made flaky.

    `check.py` exits 1 while main.py is unfixed, and 0 once it contains FIXED. When
    main.py also carries the FLAKY_VARIANT marker, `check.py` increments a counter
    file OUTSIDE the workspace (the workspace is re-materialised per run, so a
    counter inside it could not flake across repeats) and fails every `flake_every`
    invocations. `flake_every=2` is caught by the A3 window; `flake_every=6` slips
    through it and must be caught by the admission confirmation window.
    """
    cand = root / "candidate"
    (cand / "fixture").mkdir(parents=True)
    (cand / "GOLDEN").mkdir()
    v2_name = "v2_flaky" if flake_every else "v2_stable"
    for name in ("v1_stable", v2_name):
        (cand / "variants" / name).mkdir(parents=True)

    flake = ("n % 2 == 1" if flake_every == 2
             else f"n % {flake_every or 2} == {(flake_every or 2) - 1}")
    checker = f'''\
import pathlib
import sys

COUNTER = pathlib.Path({str(counter)!r})
src = pathlib.Path("main.py").read_text(encoding="utf-8")
if "FIXED" not in src:
    sys.exit(1)
if "FLAKY_VARIANT" in src:
    n = int(COUNTER.read_text()) if COUNTER.exists() else 0
    COUNTER.write_text(str(n + 1))
    sys.exit(1 if {flake} else 0)
sys.exit(0)
'''
    (cand / "fixture" / "main.py").write_text("BUG = 1\n", encoding="utf-8")
    (cand / "fixture" / "check.py").write_text(checker, encoding="utf-8")
    (cand / "GOLDEN" / "main.py").write_text("FIXED = 1\n", encoding="utf-8")
    (cand / "variants" / "v1_stable" / "main.py").write_text("FIXED = 1\n", encoding="utf-8")
    v2_body = "FIXED = 1\nFLAKY_VARIANT = 1\n" if flake_every else "FIXED = 1\n"
    (cand / "variants" / v2_name / "main.py").write_text(v2_body, encoding="utf-8")

    task = {
        "id": "synthetic_determinism",
        "kind": "capability",
        "prompt": "Make the checker accept the module.",
        "success": {
            "type": "all",
            "of": [
                # check.py is the executed verifier artifact, so A4a tampers with it;
                # the file_contains conjunct keeps the tampered workspace failing.
                {"type": "command_exit_0", "argv": [sys.executable, "check.py"]},
                {"type": "file_contains", "path": "main.py", "contains": "FIXED"},
            ],
        },
        "provenance": {"generator": "test", "independent_of": "synthetic"},
    }
    (cand / "task.json").write_text(json.dumps(task, indent=2), encoding="utf-8")
    return cand


def _audit(cand: Path) -> dict:
    return admission.audit_candidate(
        cand, json.loads((cand / "task.json").read_text(encoding="utf-8")))


class BudgetLabelTests(unittest.TestCase):
    def test_both_axes_are_projected_without_changing_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.json"
            path.write_text(json.dumps({"arms": [{"groups": [
                {"task_id": "completion", "budget_sensitive_completion": True,
                 "budget_sensitive_turn": False},
                {"task_id": "turn", "budget_sensitive_completion": False,
                 "budget_sensitive_turn": True},
                {"task_id": "clean", "budget_sensitive_completion": False,
                 "budget_sensitive_turn": False},
            ]}]}), encoding="utf-8")
            labels = admission.budget_sensitivity_labels(path)
        self.assertEqual(labels["completion"]["axes"], ["completion"])
        self.assertEqual(labels["turn"]["axes"], ["turn"])
        self.assertFalse(labels["clean"]["sensitive"])
        self.assertEqual(labels["clean"]["status"], "measured")
        self.assertNotIn("admissible", labels["completion"])

    def test_missing_manifest_is_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(admission.budget_sensitivity_labels(Path(tmp) / "missing.json"), {})


class VariantStabilityTests(unittest.TestCase):
    def test_flaky_variant_predicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _audit(_write_candidate(root, root / "counter", flake_every=2))

        self.assertFalse(result["admissible"])
        self.assertIn("A3_variants_pass", result["failed_checks"])
        self.assertFalse(result["checks"]["A3_variants_pass"])
        flaky = [v for v in result["variants"] if not v["stable"]]
        self.assertEqual([v["name"] for v in flaky], ["v2_flaky"])
        # The A3 window is what caught it; the reason is auditable.
        self.assertEqual(len(flaky[0]["verdicts"]), admission.REPEATS)
        self.assertEqual(sorted(flaky[0]["verdicts"]), [False, True])
        self.assertFalse(flaky[0]["pass"])
        # A predicate that cannot answer the same question twice has no reproducible
        # pristine observation either, so A8 records it as not measurable instead of
        # publishing a number that changes every run.
        self.assertFalse(result["verifier_deterministic"])
        self.assertFalse(result["pristine_observation_measurable"])
        self.assertIsNone(result["pristine_observation_tokens"])
        self.assertIsNotNone(result["pristine_observation_raw_chars"])
        # The stable parts of the candidate are unaffected: this is A3 failing, not a
        # broken harness.
        self.assertTrue(result["checks"]["A1_pristine_fails"])
        self.assertTrue(result["checks"]["A2_golden_passes"])
        self.assertTrue(result["checks"]["A5_determinism"])
        self.assertTrue(result["checks"]["A4a_verifier_tamper_rejected"])

    def test_rare_flake_is_caught_by_the_admission_confirmation_window(self):
        # Fails only every 6th execution: the A3 window (REPEATS=2 samples) sees two
        # passes and would admit it, so the confirmation window is the check that has
        # to catch it -- which is exactly why admission is not decided on 2 samples.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _audit(_write_candidate(root, root / "counter", flake_every=6))

        self.assertFalse(result["admissible"])
        self.assertFalse(result["checks"]["A3_variants_pass"])
        row = [v for v in result["variants"] if v["name"] == "v2_flaky"][0]
        self.assertEqual(row["verdicts"][:admission.REPEATS], [True] * admission.REPEATS)
        self.assertEqual(len(row["verdicts"]),
                         admission.REPEATS + admission.ADMIT_CONFIRM_REPEATS)
        self.assertFalse(row["stable"])
        self.assertFalse(row["pass"])
        self.assertFalse(result["verifier_deterministic"])
        self.assertIsNone(result["pristine_observation_tokens"])
        # Every confirmation sample is recorded, so the rejection is auditable.
        self.assertEqual(
            result["admission_confirmation_samples"]["variants"]["v2_flaky"],
            row["verdicts"][admission.REPEATS:])
        self.assertIn(False, row["verdicts"][admission.REPEATS:])

    def test_stable_variant_predicate_is_still_admitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _audit(_write_candidate(root, root / "counter", flake_every=None))

        self.assertTrue(result["admissible"], result["failed_checks"])
        self.assertEqual(result["failed_checks"], [])
        self.assertTrue(result["verifier_deterministic"])
        self.assertTrue(result["pristine_observation_measurable"])
        self.assertIsInstance(result["pristine_observation_tokens"], int)
        self.assertEqual(len(result["variants"]), 2)
        expected = [True] * (admission.REPEATS + admission.ADMIT_CONFIRM_REPEATS)
        for row in result["variants"]:
            self.assertTrue(row["pass"])
            self.assertTrue(row["stable"])
            self.assertEqual(row["verdicts"], expected)
        self.assertEqual(result["golden_verdicts"], expected)

    def test_flaky_and_stable_runs_agree_on_the_stable_candidate(self):
        # The property the artifact needs: two audits of the same tree agree.
        verdicts, tokens = [], []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = _audit(_write_candidate(root, root / "counter", flake_every=None))
            verdicts.append(result["admissible"])
            tokens.append(result["pristine_observation_tokens"])
        self.assertEqual(verdicts, [True, True])
        self.assertEqual(tokens[0], tokens[1])


if __name__ == "__main__":
    unittest.main()
