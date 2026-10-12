#!/usr/bin/env python3
"""claim_gate: machine-checkable claim gate for VerseShell (task-forest TF-0008).

Computes the automated subset of the C1-C7 claim matrix and writes
eval/evidence.json. Exits non-zero when any gated claim is below its threshold.

Gated claims (thresholds mirror docs/claims-and-evidence.md exactly):
  C1  mock bench observation-token ratio D/A <= 0.50
  C2  mock bench tool-call ratio D/A       <= 0.70
  C3  diff-class expected/found completeness >= 0.90
  C4  one-step recovery structural fields   == 1.00
  C6  closed-loop trash/restore acceptance passes
  C7  full cargo test suite passes
  C8  process lifecycle contract tests pass (Windows-only test file)
  C9  compact encoding saves >= 0.40 on a small response envelope (lossless)
  C10 every documented README example runs and every README implementation number matches its source
  C11 cross-shell wall-clock: worst VerseShell/PowerShell median ratio <= 0.50 (stored measurement)
  C12 stored evidence freshness: each artifact's recorded fingerprint still matches the code
  C14 batch-read envelope: compact digest + batch budget hold on a frozen-trajectory replay
  C16 compact read projection: it actually shrinks the model-visible read observation
  C18 exec launches a name-dispatching shim (rustup's cargo/rustc) by its invoked name
  C22 exec resolves a bare npm-family name to a launchable PATHEXT candidate
  C23 the ts task scores behaviour (its own tsc) instead of the golden patch's text
  C24 every GOLDEN-bearing task is unsolved pristine and solved by GOLDEN
  C25 live numbers carry an interval, and the gate names what the sample supports
  C26 the reference client's projection carries the payload each tool promises
  C27 the len//4 observation-token proxy is calibrated against a real tokenizer
  C28 every affirmative claim meets its pre-registered sample-size / precision bar
  C29 no task enters the capability set without passing the admissibility gate
  C30 a default `file.view` hands the model the window, not just a hash
  C31 the raw-shell observation path decodes non-ASCII output losslessly
  C32 the raw-shell execution path bounds the wall clock AND the process tree
  C33 the headline row set follows the pre-registered row policy (§0.6)
C5 (learning cost) is measured with real model calls by tools/aci_learning_probe.py:
the model gets ONLY the quickstart doc (no tool schemas) and every op it emits is
executed through the real `ae --serve --agent`.
C13 (live A/D), C15 (where D's extra tokens come from), C17 (what the reads are for),
C19 (what the failed execs are), C20 (where D's extra steps come from) and C21 (the ts
fixture's toolchain-acquisition and success-predicate boundaries) are
registered in docs/claims-and-evidence.md without a pass threshold: they record
measurements, not goals. Their token/usage caliber is labelled in TOKEN_CALIBER
below (`gated: False`) and published as `token_caliber_registry` in the evidence.

Usage:
    python tools/claim_gate.py                 # regenerate metrics + run tests
    python tools/claim_gate.py --skip-tests    # skip cargo test (C6/C7 reported stale)
    python tools/claim_gate.py --metrics eval/metrics.json   # reuse a metrics dump
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from live_uncertainty import row_class  # noqa: E402
from claim_sources import selected_paths, file_hashes, source_snapshot, apply_stability_guard, build_inventory, markdown, require_current_evidence

THRESHOLDS = {
    "C1": {"desc": "mock bench observation_tokens ratio D/A", "op": "<=", "value": 0.50},
    "C2": {"desc": "mock bench tool_calls ratio D/A", "op": "<=", "value": 0.70},
    "C3": {"desc": "diff-class expected/found completeness", "op": ">=", "value": 0.90},
    "C4": {"desc": "one-step recovery structural checks", "op": ">=", "value": 1.00},
    "C5": {"desc": "quickstart-only learning: first-attempt op acceptance", "op": ">=", "value": 0.70},
    "C6": {"desc": "closed-loop trash/restore acceptance", "op": ">=", "value": 1.00},
    "C7": {"desc": "full cargo test suite green", "op": ">=", "value": 1.00},
    "C8": {"desc": "process lifecycle contract tests", "op": ">=", "value": 1.00},
    "C9": {"desc": "compact encoding savings on a small response envelope", "op": ">=", "value": 0.40},
    "C10": {"desc": "README examples run and README numbers match source", "op": ">=", "value": 1.00},
    "C11": {"desc": "cross-shell worst VerseShell/PowerShell median ratio", "op": "<=", "value": 0.50},
    "C12": {"desc": "stored evidence freshness (recorded fingerprint matches the code)", "op": ">=", "value": 1.00},
    "C14": {"desc": "batch-read envelope replay: compact digest saving + bounded batch budget", "op": ">=", "value": 0.15},
    "C16": {"desc": "compact read projection saving on a frozen trajectory", "op": ">=", "value": 0.10},
    "C18": {"desc": "exec launches a name-dispatching shim by its invoked name", "op": "==", "value": 1.0},
    "C22": {"desc": "exec resolves a bare npm-family name to a launchable PATHEXT candidate", "op": "==", "value": 1.0},
    "C23": {"desc": "the ts task scores behaviour (its own tsc) instead of the golden patch's text", "op": "==", "value": 1.0},
    "C24": {"desc": "every GOLDEN-bearing task is unsolved pristine and solved by GOLDEN", "op": "==", "value": 1.0},
    "C25": {"desc": "live numbers carry an interval and the gate names what the sample can support", "op": "==", "value": 1.0},
    "C26": {"desc": "the reference client's projection carries the payload each tool description promises", "op": "==", "value": 1.0},
    "C30": {"desc": "a default `file.view` hands the model the window, not just a hash", "op": "==", "value": 1.0},
    "C27": {"desc": "the len//4 observation-token proxy is calibrated against a real tokenizer", "op": "==", "value": 1.0},
    "C28": {"desc": "every affirmative claim meets its pre-registered sample-size / precision bar", "op": "==", "value": 1.0},
    "C29": {"desc": "no task enters the capability set without passing the admissibility gate", "op": "==", "value": 1.0},
    "C31": {"desc": "the raw-shell observation path decodes non-ASCII output losslessly", "op": "==", "value": 1.0},
    "C32": {"desc": "the raw-shell execution path bounds the wall clock AND the process tree", "op": "==", "value": 1.0},
    "C33": {"desc": "the headline row set follows the pre-registered row policy (§0.6)", "op": "==", "value": 1.0},
    "C34": {"desc": "the compact read projection removes the pre-registered share of the NAMED envelope overhead, on a task set newer than the one it was discovered on", "op": ">=", "value": 0.40},
    "C35": {"desc": "the paired control arm matches the with arm in composition (seeds, tasks, rows, revision, task set)", "op": "==", "value": 1.0},
    "C36": {"desc": "every verdict declares its hypothesis family and a confirmatory family carries a multiplicity correction", "op": "==", "value": 1.0},
    "C37": {"desc": "the headline statistics reproduce along an independent code path", "op": "==", "value": 1.0},
}

# ── per-claim token / usage / cost CALIBER (task-2, P2-5) ──────────────────────
# Every published token, usage or "cost" number must say WHAT was measured and
# what that measurement cannot substitute for. These labels are descriptive only:
# no threshold, no PASS/FAIL predicate and no gate membership depends on them.
#
# `caliber` is the machine-readable class, `measured_by` names where the number is
# produced, and `note` states the measurement object plus its non-substitutes.
#
# Caliber vocabulary used below:
#   synthetic_mock_constant               an a-priori constant in the mock runner, not a measurement
#   byte_or_ceil_div4_proxy               bytes, or ceil(bytes/4), not any live tokenizer
#   observation_proxy_estimate_tokens     max(1, len(text)//4) over delivered observation text
#   observation_proxy_plain_len_div_4     len(text)//4 with no max(1, .) floor
#   observation_proxy_inherited_from_live_rows
#                                         the live rows' recorded `observation_tokens` field
#   endpoint_usage                        endpoint-reported prompt/completion usage, summed
#   mixed_proxy_count_and_endpoint_usage  more than one of the above in a single claim
#   real_bpe_replay_vs_proxy_calibration  an independent cl100k_base replay of the same text
#   char_count_with_proxy_token_context   the gated number is characters; tokens are context only
#   no_token_field_published              the claim publishes no token/usage/cost number
#
# C13, C15, C17, C19, C20 and C21 are registered in docs/claims-and-evidence.md and
# have NO entry in THRESHOLDS (they record measurements, not goals). They are listed
# here with `gated: False` so their caliber is machine-readable too; this registry,
# and the copy published as `token_caliber_registry` in eval/evidence.json, is their
# label.
TOKEN_CALIBER: dict[str, dict] = {
    "C1": {
        "gated": True,
        "caliber": "synthetic_mock_constant",
        "measured_by": "bench/aci/runners/run_suite.py::simulate_trajectory -> "
                       "bench/aci/results/latest.json rows[].observation_tokens",
        "note": "the mock runner stamps each step with a fixed `observation_tokens` constant "
                "('realistic token asymmetry') and the gate compares mean D per-task tokens with "
                "mean A. These are seeded synthetic constants: NOT a text-derived len//4 proxy, "
                "NOT endpoint usage, NOT a wall-clock or money cost. The mock pipeline is a "
                "scoring self-check, not a capability measurement",
    },
    "C9": {
        "gated": True,
        "caliber": "byte_or_ceil_div4_proxy",
        "measured_by": "examples/compact_ratio.rs -> eval/compact_ratio.json "
                       "(gated value = min(byte_savings, token_savings))",
        "note": "the gated value is min(byte_savings, ceil(bytes/4) token_savings) on the "
                "synthetic `response_small_hash` envelope, plus lossless round-trips on observation "
                "payloads. The token half is a `ceil(len/4)` proxy over the ENCODED BYTE length: "
                "NOT the evaluated model's tokenizer, NOT cl100k_base, NOT whole-round usage and NOT "
                "a money cost. It says nothing about large or nested payloads",
    },
    "C13": {
        "gated": False,
        "source": ["bench/aci/results/latest_live.json","bench/aci/results/live_ab_without_read_files.json"],
        "caliber": "mixed_proxy_count_and_endpoint_usage",
        "measured_by": "bench/aci/runners/live_agent_loop.py -> "
                       "bench/aci/results/latest_live.json rows[]",
        "note": "live A/D comparison. `observation_tokens` is the live runner's "
                "max(1, len(text)//4) proxy accumulated over delivered observation text, so every "
                "observation-token headline (and the D/A token ratio) is proxy-caliber; "
                "`llm_prompt_tokens` / `llm_completion_tokens` are endpoint usage accumulated over "
                "every request. Neither is a money cost and neither is the size of one system "
                "prompt. Registered in docs/claims-and-evidence.md; no gate entry here",
    },
    "C14": {
        "gated": True,
        "caliber": "observation_proxy_estimate_tokens",
        "measured_by": "tools/tf45_envelope_replay.py (estimate_tokens imported from "
                       "bench/aci/runners/live_agent_loop.py)",
        "note": "max(1, len(text)//4) accumulated over the replayed model-visible read "
                "observations, legacy projection vs compact projection, and restricted to calls "
                "whose stored projection reproduces the recorded token count. The saving is a "
                "proxy-caliber ratio over that frozen call set: NOT endpoint usage, NOT the "
                "evaluated model's tokenizer, NOT currency and NOT model behaviour. The budget half "
                "(max_total_lines, pagination) is structural, not a token measurement",
    },
    "C15": {
        "gated": False,
        "source": ["eval/exec_token_breakdown.json"],
        "caliber": "observation_proxy_inherited_from_live_rows",
        "measured_by": "tools/exec_token_breakdown.py reading rows[].observation_tokens",
        "note": "per-op token figures are the live rows' recorded `observation_tokens` (the "
                "runner's max(1, len//4) proxy), not a fresh count: proxy-caliber, NOT endpoint "
                "usage and NOT currency. The A-side bucketing is a keyword heuristic, so this is a "
                "diagnostic, not an outbound claim. Registered in docs/claims-and-evidence.md; no "
                "gate entry here",
    },
    "C16": {
        "gated": True,
        "caliber": "observation_proxy_plain_len_div_4",
        "measured_by": "tools/read_path_breakdown.py (legacy_tokens / current_tokens = "
                       "len(text) // 4)",
        "note": "`len(text)//4` (no max(1, .) floor) over the reference client's projected read "
                "text under both projections; the gated saving is a proxy-caliber ratio over the "
                "frozen call set. NOT endpoint usage, NOT a real tokenizer, NOT currency and NOT "
                "model behaviour: a metadata-only envelope is byte-identical under both projections "
                "and contributes exactly zero by construction",
    },
    "C17": {
        "gated": False,
        "source": ["eval/read_usage_audit.json"],
        "caliber": "observation_proxy_inherited_from_live_rows",
        "measured_by": "tools/read_usage_audit.py reading rows[].observation_tokens",
        "note": "per-read token figures are the live rows' recorded `observation_tokens` (the "
                "runner's max(1, len//4) proxy), split evenly across the paths of a batched call. "
                "That even apportionment is an accounting convention, not a measurement; the "
                "numbers are proxy-caliber, NOT endpoint usage and NOT currency, and `unreferenced` "
                "does not mean wasted. Registered in docs/claims-and-evidence.md; no gate entry here",
    },
    "C19": {
        "gated": False,
        "source": ["eval/exec_failure_breakdown.json"],
        "caliber": "observation_proxy_inherited_from_live_rows",
        "measured_by": "tools/exec_failure_breakdown.py reading rows[].observation_tokens",
        "note": "failure token shares are the live rows' recorded `observation_tokens` "
                "(max(1, len//4) proxy) grouped by failure class: proxy-caliber, NOT endpoint usage "
                "and NOT currency. The failed observations are representative reproductions, not the "
                "original trajectory steps. Registered in docs/claims-and-evidence.md; no gate entry "
                "here",
    },
    "C20": {
        "gated": False,
        "source": ["eval/step_composition.json"],
        "caliber": "observation_proxy_inherited_from_live_rows",
        "measured_by": "tools/step_composition.py reading rows[].observation_tokens",
        "note": "step-composition token figures are the live rows' recorded `observation_tokens` "
                "(the runner's max(1, len//4) proxy): proxy-caliber, NOT endpoint usage and NOT "
                "currency. `duplicate` and `multi_in_one` counts are keyword heuristics, so this is "
                "a diagnostic, not a claim of measured waste. Registered in "
                "docs/claims-and-evidence.md; no gate entry here",
    },
    "C21": {
        "gated": False,
        "source": ["eval/ts_fixture_audit.json"],
        "caliber": "observation_proxy_inherited_from_live_rows",
        "measured_by": "tools/ts_fixture_audit.py reading rows[].observation_tokens and "
                       "steps[].observation_tokens",
        "note": "the ts-fixture token figures are the live rows' recorded `observation_tokens` "
                "(max(1, len//4) proxy), not a fresh count; the counterfactual band subtracts "
                "estimated toolchain-acquisition tokens. Proxy-caliber, NOT endpoint usage and NOT "
                "currency: the claim's real subject is the task's toolchain and success-predicate "
                "boundary. Registered in docs/claims-and-evidence.md; no gate entry here",
    },
    "C25": {
        "gated": True,
        "caliber": "mixed_proxy_count_and_endpoint_usage",
        "measured_by": "tools/live_uncertainty.py -> eval/live_uncertainty.json arms[].ratio_bootstrap",
        "note": "`observation_token_ratio` is the max(1, len//4) proxy over delivered observation "
                "text (bootstrap clustered by task); `tool_call_ratio` is a ratio of CALL COUNTS, "
                "not tokens; `usage_token_ratio` / `prompt_token_ratio` / `completion_token_ratio` "
                "are endpoint usage accumulated over every request. None measures the size of one "
                "system prompt or one tool-schema payload, and none is currency",
    },
    "C26": {
        "gated": True,
        "caliber": "no_token_field_published",
        "measured_by": "tools/projection_contract.py -> eval/projection_contract.json",
        "note": "this claim gates the PRESENCE of promised payload fields in the reference client's "
                "projection and publishes no token, usage or cost field. Observation-token "
                "magnitudes quoted alongside it (e.g. the repo.search fallback figures in the notes) "
                "are the max(1, len//4) proxy from the stored live run, not endpoint usage",
    },
    "C27": {
        "gated": True,
        "caliber": "real_bpe_replay_vs_proxy_calibration",
        "measured_by": "tools/token_proxy_calibration.py -> eval/token_proxy_calibration.json "
                       "(cl100k_base replay of the same sampled observation texts)",
        "note": "the calibration claim itself: it scores the max(1, len//4) proxy against an "
                "independent cl100k_base BPE replay of the SAME sampled observation texts. The "
                "published ratio is a real_tokens/proxy_tokens diagnostic: NOT a model-usage "
                "measurement, NOT the evaluated model's tokenizer, NOT any whole-round token total "
                "and NOT currency. The endpoint `usage.prompt_tokens` is unusable as ground truth "
                "(content-cached and inflated on many payloads), which is why the calibration "
                "neutralises it rather than trusting it",
    },
    "C28": {
        "gated": True,
        "caliber": "mixed_proxy_count_and_endpoint_usage",
        "measured_by": "tools/acceptance_power.py -> eval/acceptance_power.json live / live_coached",
        "note": "the ratio verdicts rest on observation-token proxies (max(1, len//4) from the live "
                "rows); `cost_per_success` divides those OBSERVATION-PROXY tokens by successes, so "
                "despite the word `cost` it is NOT currency; the `usage_*` / `prompt_*` / "
                "`completion_*` readings are endpoint usage. This claim gates whether the sample can "
                "carry a claim, not the caliber of the number it carries",
    },
    "C30": {
        "gated": True,
        "caliber": "no_token_field_published",
        "measured_by": "tools/projection_contract.py -> eval/projection_contract.json",
        "note": "this claim gates that a default `file.view` hands the model a rendered window; it "
                "publishes no token, usage or cost field. The 45.5k / 65.7k token magnitudes quoted "
                "in the notes are the max(1, len//4) proxy over the stored live run, not endpoint "
                "usage and not currency",
    },
    "C31": {
        "gated": True,
        "caliber": "no_token_field_published",
        "measured_by": "tools/harness_encoding_contract.py -> eval/harness_encoding_contract.json",
        "note": "this claim asserts byte-lossless decoding on the raw-shell observation path; it "
                "publishes no token, usage or cost field. Token costs quoted near it belong to "
                "C13/C19 and are max(1, len//4) proxy, not endpoint usage",
    },
    "C34": {
        "gated": True,
        "caliber": "char_count_with_proxy_token_context",
        "measured_by": "tools/read_path_breakdown.py totals.legacy_parts / current_parts "
                       "(line_wrapper + counts chars)",
        "note": "the gated value is a CHARACTER ratio: named overhead = `line_wrapper + counts` "
                "chars from read_path_breakdown.json's per-projection attribution, so it measures "
                "the reference client's rendering, not tokens. The `token_savings` reported in "
                "`context_not_gated` is the len//4 proxy. Neither is endpoint usage, currency or a "
                "total-token claim",
    },
}


def token_caliber_fields(cid: str) -> dict:
    """Machine-readable caliber label for a token-bearing claim (see TOKEN_CALIBER)."""
    entry = TOKEN_CALIBER[cid]
    return {
        "token_caliber": entry["caliber"],
        "token_caliber_note": entry["note"],
    }


# Acceptance items this repo actually asserts affirmatively. If any of these loses
# its `claimable` verdict in eval/acceptance_power.json, the gate must fail — that
# is the difference between "we measured it" and "the sample can carry the claim".
# Items that are currently NOT claimable (the token-saving ladder) are deliberately
# absent: the honest state is that they cannot be claimed yet, and C28 records it.
AFFIRMATIVE_ACCEPTANCE = [
    "cross_shell_all_ops_strictly_faster",
    "cross_shell_all_ops_2x",
]

# Stored measurements the gate relies on. Each must record the content fingerprint
# of the surface it measured, or the gate cannot tell whether the number still
# describes the current code.
#
# `bench/aci/results/latest_live.json` is gated again as of the successful
# re-measurement on `sn-glm-5-3-flash` (3 runs, seeds 42/43/44). Its A/B partner
# `live_ab_without_read_files.json` is deliberately NOT gated: it is a paired
# comparison arm (same code, one tool hidden) that exists to size the effect of
# `file.read_many`, and re-running it is only needed when the comparison itself
# is being redone — C13 records when it was taken.
#
# ⚠️ KNOWN GAP (tree-farm TF-0119): because it is ungated, SEVEN tools derive
# metrics from it while the gate reports them "fresh" — acceptance_power,
# exec_failure_breakdown, exec_token_breakdown, live_uncertainty, read_usage_audit,
# step_composition and three_arm_report. On 2026-09-27 that arm was still the
# round-12 file (75 rows, seed 42 only, produced by the runner that had the cp936
# crash) while the with-arm baseline was the round-13 3-seed file — i.e. the
# comparison arms were not composition-consistent. Closing this needs an explicit
# composition check, not a fingerprint: see TF-0119.
EVIDENCE_ARTIFACTS = [
    "bench/aci/results/latest.json",
    "bench/aci/results/latest_live.json",
    "eval/jev_obs_report.json",
    "eval/cross_shell.json",
    "eval/tf45_envelope_replay.json",
    "eval/exec_token_breakdown.json",
    "eval/read_path_breakdown.json",
    "eval/read_usage_audit.json",
    "eval/exec_failure_breakdown.json",
    "eval/step_composition.json",
    "eval/ts_fixture_audit.json",
    "eval/task_set_audit.json",
    "eval/aci_learning_probe.json",
    "eval/live_uncertainty.json",
    "eval/budget_sensitivity.json",
    "eval/task_design_audit.json",
    "eval/projection_contract.json",
    "eval/token_proxy_calibration.json",
    "eval/acceptance_power.json",
    "eval/task_admissibility.json",
    "eval/task_set_freeze.json",
    "eval/three_arm_report.json",
    "eval/harness_encoding_contract.json",
    "eval/harness_exec_contract.json",
    "eval/statistics_crosscheck.json",
]


def bench_ratios(bench_path: Path) -> tuple[float, float, int, dict]:
    """Return (token_ratio_D_over_A, tool_call_ratio_D_over_A, n_tasks, meta)."""
    data = json.loads(bench_path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    mode = data.get("mode", "?")
    if mode != "mock":
        raise SystemExit(f"claim_gate expects the mock bench results; got mode={mode!r} in {bench_path}")
    agg: dict[str, dict[str, float]] = {}
    for r in rows:
        cond = r.get("condition")
        if cond not in ("raw_shell", "verseshell_aci"):
            continue
        a = agg.setdefault(cond, {"tokens": 0.0, "calls": 0.0, "n": 0.0})
        a["tokens"] += float(r.get("observation_tokens", 0))
        a["calls"] += float(r.get("tool_calls", 0))
        a["n"] += 1
    if "raw_shell" not in agg or "verseshell_aci" not in agg or agg["raw_shell"]["n"] == 0:
        raise SystemExit(f"bench file lacks paired raw_shell/verseshell_aci rows: {bench_path}")
    tok_ratio = (agg["verseshell_aci"]["tokens"] / agg["verseshell_aci"]["n"]) / (
        agg["raw_shell"]["tokens"] / agg["raw_shell"]["n"]
    )
    call_ratio = (agg["verseshell_aci"]["calls"] / agg["verseshell_aci"]["n"]) / (
        agg["raw_shell"]["calls"] / agg["raw_shell"]["n"]
    )
    meta = {
        "bench_mode": mode,
        "task_set_version": data.get("task_set_version"),
        "seed": data.get("seed"),
        "generated_at": data.get("generated_at"),
        "n_rows_per_condition": int(agg["raw_shell"]["n"]),
    }
    return tok_ratio, call_ratio, int(agg["raw_shell"]["n"]), meta


def recovery_rate(metrics: dict) -> tuple[float, dict]:
    probes = metrics.get("recovery_probes", {})
    stale = probes.get("stale_hash", {})
    amb = probes.get("ambiguous", {})
    checks = {
        "stale_hash.data_actual_hash_present": bool(stale.get("data_actual_hash_present")),
        "stale_hash.data_expected_hash_present": bool(stale.get("data_expected_hash_present")),
        "stale_hash.one_step_retry_ok": bool(stale.get("one_step_retry_from_suggested_next_ok")),
        "ambiguous.matches_structured": bool(amb.get("matches_structured_line_offset_snippet")),
        "ambiguous.widen_retry_ok": bool(amb.get("widen_old_retry_ok")),
    }
    passed = sum(1 for v in checks.values() if v)
    return passed / len(checks), checks


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def evidence_fingerprint(globs: list[str]) -> str:
    """Content hash of a measured surface (same recipe the generators use)."""
    digest = hashlib.sha256()
    paths = sorted(
        p for pat in globs for p in ROOT.glob(pat)
        if p.is_file() and "__pycache__" not in p.parts
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_input_hashes(evidence: dict, *, required: bool = False, selected=None) -> list[str]:
    """Verify actual inputs, including files outside default globs."""
    inputs = evidence.get('input_sha256')
    if inputs is None:
        return ['actual input hashes missing'] if required else []
    if not isinstance(inputs, dict) or not inputs:
        return ['actual input hashes empty or malformed']
    failures = []
    for source, digest in inputs.items():
        if not isinstance(source, str) or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            failures.append(f'invalid input digest: {source}')
            continue
        try:
            recorded_path = (ROOT / source).resolve()
            if hashlib.sha256(recorded_path.read_bytes()).hexdigest() != digest:
                failures.append(f'changed input: {source}')
            if recorded_path.is_relative_to(ROOT.resolve()):
                logical = recorded_path.relative_to(ROOT.resolve()).as_posix()
                actual = (selected or {}).get(logical)
                if actual is not None and hashlib.sha256(Path(actual).read_bytes()).hexdigest() != digest:
                    failures.append(f'declared input differs from selected input: {logical}')
        except OSError:
            failures.append(f'missing or unreadable input: {source}')
    return failures


def freshness_entries(selected=None) -> list[dict]:
    """C12: compare each stored artifact's recorded fingerprint with the code now."""
    entries: list[dict] = []
    for rel in EVIDENCE_ARTIFACTS:
        path = (selected or {}).get(rel, ROOT / rel)
        entry: dict = {"artifact": rel, "selected_path": str(Path(path).resolve())}
        if not path.exists():
            entry.update({"status": "missing", "pass": False})
            entries.append(entry)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            entry.update({"status": f"unreadable: {error}", "pass": False})
            entries.append(entry)
            continue
        entry["generated_at"] = data.get("generated_at")
        evidence = data.get("evidence") or {}
        globs = evidence.get("globs")
        recorded = evidence.get("fingerprint")
        if not globs or not recorded:
            entry.update({
                "status": "no fingerprint recorded (regenerate the artifact)",
                "pass": False,
            })
        else:
            current = evidence_fingerprint(globs)
            entry.update({
                "status": "fresh" if current == recorded else "stale",
                "fingerprint_recorded": recorded[:16],
                "fingerprint_current": current[:16],
                "pass": current == recorded,
            })
        failures = verify_input_hashes(evidence, required=rel in {
            'eval/three_arm_report.json', 'eval/acceptance_power.json', 'eval/task_set_audit.json',
            'eval/task_design_audit.json'}, selected=selected)
        if failures:
            entry.update(status='stale actual inputs', **{'pass': False}, input_failures=failures)
        entries.append(entry)
    return entries


def replay_source_binding(report, freeze, source_path):
    """A newer freeze label alone cannot promote a replay of older/different rows."""
    problems=[];identity=report.get('source_identity') or {};version=None
    try:
        raw=Path(source_path).read_bytes();data=json.loads(raw)
        version=data.get('task_set_version')
        valid_version=isinstance(version,str) and bool(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version))
        if not valid_version or tuple(map(int,version.split('.'))) <= (2,0,0):
            problems.append('measured task set is not newer than 2.0.0')
        if identity.get('sha256')!=hashlib.sha256(raw).hexdigest():problems.append('replay source hash differs from selected live input')
        if version!=identity.get('task_set_version') or version!=freeze.get('task_set_version'):
            problems.append('measured/replay/freeze task-set versions differ')
        tasks=freeze.get('tasks') or []
        if not tasks or len(set(tasks))!=len(tasks) or set(tasks)!={r.get('task_id') for r in data.get('rows',[])}:
            problems.append('frozen tasks differ from measured tasks')
    except (OSError,ValueError,TypeError,AttributeError) as error:
        problems.append('source binding unavailable: '+str(error))
    return {'pass':not problems,'problems':problems,'source_identity':identity,'measured_task_set_version':version}


def compact_ratio_claim(report: dict) -> dict:
    """C9 reads the measured compact-vs-JSON report.

    The gated number is deliberately narrow: the compact encoding must beat JSON
    on a *small response envelope* (where repeated key names dominate) and stay
    lossless on every observation payload. It makes no claim about large or
    nested payloads, where the measurement shows no saving.
    """
    families = {f.get("kind"): f for f in report.get("families", [])}
    response = families.get("response", {}).get("cases", [])
    observation = families.get("observation", {}).get("cases", [])
    small = next((c for c in response if c.get("name") == "response_small_hash"), None)
    if small is None:
        raise SystemExit("compact_ratio report lacks the response_small_hash case")
    roundtrips_ok = bool(observation) and all(c.get("roundtrip_ok") is True for c in observation)
    value = min(float(small.get("byte_savings", 0.0)), float(small.get("token_savings", 0.0)))
    return {
        "value": round(value, 4),
        "pass": value >= THRESHOLDS["C9"]["value"] and roundtrips_ok,
        "detail": {
            "small_response_byte_savings": small.get("byte_savings"),
            "small_response_token_savings": small.get("token_savings"),
            "observation_roundtrips_ok": roundtrips_ok,
            "observation_headline_savings": families.get("observation", {})
            .get("aggregate", {})
            .get("headline_savings"),
            "response_headline_savings": families.get("response", {})
            .get("aggregate", {})
            .get("headline_savings"),
        },
    }


def batch_envelope_claim(report: dict) -> dict:
    """C14 reads the frozen-trajectory replay of the batch-read envelope.

    Two things must hold: the compact digest must actually shrink the
    model-visible observation on calls the model really issued, and the new
    `max_total_lines` budget must bound a worst-case batch read while staying
    paginable. The gated number is the token saving; the budget, the
    no-truncation guard and a non-empty replay are pass conditions in `detail`.
    """
    totals = report.get("totals", {})
    budget = report.get("budget", {})
    savings = float(totals.get("token_savings", 0.0))
    coverage = float(totals.get("coverage", 0.0))
    exact = bool(totals.get("legacy_comparison_exact"))
    bounded = bool(budget.get("bounded"))
    paginable = bool(budget.get("pagination_roundtrip"))
    # The untruncated subset must ALSO clear the threshold. Once the batch budget
    # shipped, a truncated entry is part of the frozen trajectory rather than a
    # replay failure, so "no truncation" stopped being the right strictness — but
    # dropping the guard entirely would let a handful of huge truncated calls carry
    # the saving. Gating the clean subset keeps the check meaningful.
    untruncated_savings = float(totals.get("untruncated_token_savings", 0.0))
    untruncated_calls = int(totals.get("untruncated_calls") or 0)
    untruncated_ok = (untruncated_calls == 0
                      or untruncated_savings >= THRESHOLDS["C14"]["value"])
    return {
        "value": round(savings, 4),
        "pass": (savings >= THRESHOLDS["C14"]["value"] and exact and bounded
                 and paginable and coverage > 0 and untruncated_ok),
        "detail": {
            "calls_total": totals.get("calls"),
            "calls_replayed": totals.get("calls_replayed"),
            "calls_excluded": totals.get("calls_excluded"),
            "coverage": coverage,
            "legacy_tokens": totals.get("legacy_tokens"),
            "current_tokens": totals.get("current_tokens"),
            "legacy_comparison_exact": exact,
            "truncated_usable_calls": totals.get("truncated_usable_calls"),
            "untruncated_calls": untruncated_calls,
            "untruncated_token_savings": untruncated_savings,
            "untruncated_meets_threshold": untruncated_ok,
            "by_op": report.get("by_op"),
            "budget_default_lines": (budget.get("default") or {}).get("lines_returned"),
            "budget_default_cap": (budget.get("default") or {}).get("max_total_lines"),
            "budget_tight_lines": (budget.get("tight") or {}).get("lines_returned"),
            "budget_tight_cap": (budget.get("tight") or {}).get("max_total_lines"),
            "budget_bounded": bounded,
            "pagination": budget.get("pagination"),
            "pagination_roundtrip": paginable,
        },
    }


def compact_read_claim(report: dict) -> dict:
    """C16 reads the read-path breakdown: the compact projection must actually
    shrink the model-visible read observation on calls the model really issued.

    Both projections come from the real projector (`compact=False` vs `True`), so
    the delta is measured rather than re-implemented, and the claim also requires
    that at least one call was matched against the stored live run.

    The gated number is the PRE-REGISTERED one: the saving over all replayed calls.
    The rendered/metadata-only split is reported in `detail` but deliberately does
    NOT carry the gate, because moving a registered metric after seeing the number
    is the exact failure mode this repo is built to avoid.

    The split is still informative: an envelope with no rendered window (a bare
    `{ok, content_hash, total_lines}`) is byte-identical under both projections, so
    it contributes a saving of exactly zero by construction, and a baseline whose
    read mix is dominated by such calls measures the call mix rather than the
    projection. That is a real caveat to state alongside the number, not a reason to
    redefine it.
    """
    totals = report.get("totals", {})
    calls = int(totals.get("calls") or 0)
    matched = totals.get("matched_projection") or {}
    rendered_calls = int(totals.get("calls_rendering_content") or 0)
    rendered_savings = totals.get("rendered_token_savings")
    all_savings = float(totals.get("token_savings") or 0.0)
    return {
        "value": round(all_savings, 4),
        "pass": (all_savings >= THRESHOLDS["C16"]["value"] and calls > 0 and bool(matched)),
        "detail": {
            "calls": calls,
            "calls_rendering_content": rendered_calls,
            "calls_metadata_only": totals.get("calls_metadata_only"),
            "rendered_token_savings": rendered_savings,
            "rendered_legacy_tokens": totals.get("rendered_legacy_tokens"),
            "rendered_current_tokens": totals.get("rendered_current_tokens"),
            "all_calls_token_savings": all_savings,
            "excluded_calls": totals.get("excluded_calls"),
            "matched_projection": matched,
            "legacy_tokens": totals.get("legacy_tokens"),
            "current_tokens": totals.get("current_tokens"),
            "char_savings": totals.get("char_savings"),
            "legacy_parts": totals.get("legacy_parts"),
            "current_parts": totals.get("current_parts"),
            "by_op": report.get("by_op"),
        },
    }


def shim_launch_claim(report: dict) -> dict:
    """C18 reads the shim probe: exec must launch a name-dispatching shim by name.

    The probe re-runs `cargo --version` / `cargo check` / `rustc --version` through
    the real exec path. A launcher that canonicalises the shim away makes rustup
    answer for all three, which is exactly the defect this claim fences. The gate
    is fail-closed: it also requires that the machine actually has such a shim, so
    a machine without one reports not-exercised rather than a vacuous pass.
    """
    probe = report.get("shim_probe") or {}
    facts = report.get("shim_facts") or []
    shim_present = any(f.get("canonical_loses_name") for f in facts if isinstance(f, dict))
    passed = bool(probe.get("pass")) and shim_present
    return {
        "value": 1.0 if passed else 0.0,
        "pass": passed,
        "detail": {
            "shim_present": shim_present,
            "cargo_dispatches_correctly": probe.get("cargo_dispatches_correctly"),
            "cargo_check_succeeds_on_fixed_fixture": probe.get("cargo_check_succeeds_on_fixed_fixture"),
            "commands": probe.get("commands"),
            "shims": [f for f in facts if isinstance(f, dict) and f.get("is_symlink")],
        },
    }


def bare_name_claim(report: dict) -> dict:
    """C22 reads the bare-name probe: a bare npm-family name must actually start.

    npm-for-Windows ships an extensionless `npm` (a `#!/bin/sh` script) beside
    `npm.cmd`, and `resolve_candidate` returned the bare file first — so
    `exec.run(["npm", ...])` failed with `E_EXEC_SPAWN` while raw shell (which
    spawns through `cmd`) worked, costing condition D a wasted call on every npm
    task. Fail-closed: the gate also requires that this machine actually shadows
    such a name, so a machine without one reports not-exercised rather than a
    vacuous pass.
    """
    probe = report.get("bare_name_probe") or {}
    facts = report.get("bare_name_facts") or {}
    shadowed = list(facts.get("shadowed") or [])
    passed = bool(probe.get("pass")) and bool(shadowed) and bool(probe.get("triggered"))
    return {
        "value": 1.0 if passed else 0.0,
        "pass": passed,
        "detail": {
            "shadowed": shadowed,
            "triggered": probe.get("triggered"),
            "commands": probe.get("commands"),
            "skipped": probe.get("skipped"),
        },
    }


def ts_fixture_contract_claim(report: dict) -> dict:
    """C23: the ts task must score the behaviour it asks for, not the patch's text.

    Four things must hold together: the declared predicate is a command (not a
    `file_contains` on the golden patch), the pristine fixture fails it (the task is
    not pre-solved), the GOLDEN patch passes it (the task is solvable), and both of
    those verdicts came from a real run of the fixture's pinned TypeScript. A literal
    predicate is exactly what made five of six stored runs look like failures when
    they had in fact fixed the type error.
    """
    section = report.get("success_predicate") or {}
    pred = section.get("declared_success") or {}
    argv = [str(a) for a in (pred.get("argv") or [])]
    baseline = section.get("baseline") or {}
    pristine = (baseline.get("pristine") or {}).get("tsc") or {}
    golden = (baseline.get("golden") or {}).get("tsc") or {}
    equivalent = (baseline.get("equivalent_rename") or {}).get("tsc") or {}
    checks = {
        "predicate_is_behavioural": pred.get("type") == "command_exit_0"
                                    and any("typescript" in a for a in argv),
        "pristine_fails": pristine.get("ran") is True and pristine.get("pass") is False,
        "golden_passes": golden.get("ran") is True and golden.get("pass") is True,
        # The bug this gate fences: a different-but-equivalent fix must not be
        # rejected. `equivalent_rename` keeps the behaviour and renames the binding.
        "equivalent_fix_passes": equivalent.get("ran") is True
                                 and equivalent.get("pass") is True,
    }
    passed = all(checks.values())
    return {
        "value": 1.0 if passed else 0.0,
        "pass": passed,
        "detail": {
            "checks": checks,
            "argv": argv,
            "legacy_pass_by_condition": section.get("legacy_predicate_pass_by_condition"),
            "tsc_pass_by_condition": section.get("tsc_pass_by_condition"),
            "runs_where_legacy_rejected_a_passing_fix":
                section.get("runs_where_legacy_rejected_a_passing_fix"),
        },
    }


def task_set_consistency_claim(report: dict, task_set: Path | None = None) -> dict:
    """C24: every task that ships a GOLDEN patch must be unsolved pristine and solved
    by that patch (and by an equivalent variant where one is registered).

    This is the invariant a literal-text predicate breaks while still looking
    correct against the patch it was written from: `file_contains "packages"` and
    `file_contains "return a + b"` both passed their own GOLDEN and rejected every
    other correct answer.
    """
    consistency = report.get("fixture_consistency") or {}
    failures = sorted(t for t, e in consistency.items()
                      if not e.get('pass') or e.get('pristine', {}).get('pass') is not False
                      or e.get('golden', {}).get('pass') is not True
                      or ('equivalent_variant' in e and e['equivalent_variant'].get('verdict', {}).get('pass') is not True))
    sys.path.insert(0, str(ROOT / "bench/aci/runners"))
    from task_sets import load_tasks
    from grading_contract import freeze_fixture_verifiers
    manifest, tasks = load_tasks(ROOT / "bench/aci/tasks",
                                task_set or ROOT / "bench/aci/task_sets/3.1.0.json")
    expected = tasks
    missing = sorted(set(expected) - set(consistency))
    mismatched = sorted(t for t in expected.keys() & consistency.keys()
                        if consistency[t].get("predicate") != expected[t]["success"])
    version_matches = report.get("task_set_version") == manifest["task_set_version"]
    contract_mismatches = sorted(t for t in expected.keys() & consistency.keys()
                                if consistency[t].get('protected_verifiers') != freeze_fixture_verifiers(
                                    expected[t]['success'], ROOT/'bench/aci/fixtures'/expected[t]['workspace_fixture']))
    passed = bool(consistency) and not (failures or missing or mismatched or contract_mismatches) and version_matches
    return {
        "value": 1.0 if passed else 0.0,
        "pass": passed,
        "detail": {
            "tasks_covered": sorted(consistency),
            "failures": failures,
            "missing_tasks": missing,
            "predicate_mismatches": mismatched,
            "verifier_contract_mismatches": contract_mismatches,
            "task_set_version_matches": version_matches,
            "verdicts": {
                t: {
                    "pristine": (e.get("pristine") or {}).get("pass"),
                    "golden": (e.get("golden") or {}).get("pass"),
                    "variant": ((e.get("equivalent_variant") or {}).get("verdict") or {}).get("pass"),
                }
                for t, e in consistency.items()
            },
            "predicate_changes": {
                t: {"stored_runs": e.get("runs_scored"),
                    "reconstructed": e.get("runs_reconstructed"),
                    "legacy_pass": e.get("legacy_pass"),
                    "declared_pass": e.get("declared_pass")}
                for t, e in (report.get("predicate_changes") or {}).items()
            },
        },
    }


def summarize_test_output(stdout: str) -> dict:
    """Aggregate every `test result:` line so the evidence carries real counts
    instead of whichever suite happened to print last."""
    totals = {"suites": 0, "passed": 0, "failed": 0, "ignored": 0}
    for m in re.finditer(
        r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", stdout
    ):
        totals["suites"] += 1
        totals["passed"] += int(m.group(1))
        totals["failed"] += int(m.group(2))
        totals["ignored"] += int(m.group(3))
    return totals


def _impossible_flag_consistent(verdicts: dict) -> bool:
    """A product gap must be proven by the interval, not by the point estimate.

    `impossible_by_sample_size` separates a data gap from a product gap. It may be
    set only when the WHOLE CI95 lies on the wrong side of the cap the claim needs.
    A point estimate past the cap whose interval still reaches below it is a data
    gap, because the estimate itself can move with more data — labelling that
    "unsalvageable" tells a reader to stop collecting when they should not.
    """
    for item in verdicts.values():
        if not isinstance(item, dict):
            continue
        lower = item.get("ci95_lower")
        if lower is None:
            continue
        cap = item.get("point_cap")
        if cap is None:
            cap = item.get("threshold")
        if cap is None:
            continue
        expected_product_gap = lower > cap
        if bool(item.get("impossible_by_sample_size")) != expected_product_gap:
            return False
        # `policy_blocked` is a legitimate non-claimable state that does NOT come from the
        # interval: §0.6 blocks a comparison because one of its arms excluded >10% of rows,
        # which is true whatever the CI says. Requiring it to be labelled `data_gap` would
        # be wrong (that label means "the estimate can still move with more data", while a
        # policy block means "this row set is not eligible at all"), so the interval-derived
        # label is only enforced for verdicts the policy did not block.
        if item.get("gap_type") == "policy_blocked":
            continue
        expected_type = ("product_gap" if expected_product_gap
                         else ("none" if item.get("claimable") else "data_gap"))
        if item.get("gap_type") != expected_type:
            return False
    return True


def live_run_composition(path: Path) -> dict:
    """C35 derives partial status from raw flags, never from a trusted label alone."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("rows") or []
    cap = (payload.get("live_config") or {}).get("max_turns")
    affected, mismatches = [], []
    declared_partial = bool(payload.get("partial"))
    for row in rows:
        kind = row_class(row, cap)
        identity = {key: row.get(key) for key in
                    ("task_id", "condition", "seed", "source_run", "run_index")}
        if kind == "endpoint_failure":
            affected.append({**identity, "row_class": kind})
        if ("row_class" in row or declared_partial) and row.get("row_class") != kind:
            mismatches.append({**identity, "recorded": row.get("row_class"), "expected": kind})
    conditions = {r.get("condition") for r in rows}
    affected_conditions = {r["condition"] for r in affected}
    comparisons = {f"with_vs_without/{c}" for c in affected_conditions}
    for base in ("raw_shell", "raw_shell_coached"):
        if base in conditions and "verseshell_aci" in conditions and (
            base in affected_conditions or "verseshell_aci" in affected_conditions
        ):
            comparisons.add(f"verseshell_aci_vs_{base}")
    # A live collection has no independently evaluated repeat/family evidence.
    # Inspect legacy top-level and variant comparison labels without mistaking the
    # nested row_policy eligibility boolean for formal acceptance.
    affirmative = []
    def inspect_comparisons(block, location='comparison'):
        if block.get('claimable') is True or block.get('meets_acceptance') is True:
            affirmative.append(location)
        for i, comparison in enumerate(block.get('comparisons') or []):
            if comparison.get('meets_acceptance') is True or comparison.get('claimable') is True:
                affirmative.append(f'{location}.comparisons[{i}]')
        for variant, child in (block.get('by_prompt_variant') or {}).items():
            inspect_comparisons(child, location + '.by_prompt_variant.' + variant)
    inspect_comparisons(payload.get('comparison') or {})
    return {
        "affirmative_collection_verdicts": affirmative,
        "rows": len(rows),
        "seeds": sorted({r.get("seed") for r in rows if r.get("seed") is not None}),
        "tasks": sorted({r.get("task_id") for r in rows if r.get("task_id")}),
        "git_rev": payload.get("git_rev"), "task_set_version": payload.get("task_set_version"),
        "schema": payload.get("schema"), "generated_at": payload.get("generated_at"),
        "api_error_rows": sum(bool(r.get("api_error")) for r in rows),
        "partial": declared_partial or bool(affected),
        "partial_declared": declared_partial,
        "endpoint_failure_rows": len(affected), "affected_rows": affected,
        "affected_comparisons": sorted(comparisons), "row_class_mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", type=Path, default=None,
                    help="reuse an existing eval/metrics.json instead of regenerating")
    ap.add_argument("--bench", type=Path, default=None)
    ap.add_argument("--artifact-map", type=Path, help="versioned logical-to-physical evidence paths; never copies over canonical artifacts")
    ap.add_argument("--task-set", type=Path, default=ROOT / "bench/aci/task_sets/3.1.0.json")
    ap.add_argument('--task-set-audit',type=Path,help='effective grading audit for the requested task set')
    ap.add_argument("--compact-ratio", type=Path, default=None,
                    help="reuse an existing eval/compact_ratio.json instead of regenerating")
    ap.add_argument("--cross-shell", type=Path, default=None,
                    help="path to a stored eval/cross_shell.json (regenerate with tools/cross_shell_bench.py)")
    ap.add_argument("--envelope-replay", type=Path, default=None,
                    help="path to a stored eval/tf45_envelope_replay.json "
                         "(regenerate with tools/tf45_envelope_replay.py)")
    ap.add_argument("--read-path-breakdown", type=Path, default=None,
                    help="path to a stored eval/read_path_breakdown.json "
                         "(regenerate with tools/read_path_breakdown.py)")
    ap.add_argument("--exec-failure-breakdown", type=Path, default=None,
                    help="path to a stored eval/exec_failure_breakdown.json "
                         "(regenerate with tools/exec_failure_breakdown.py)")
    ap.add_argument("--learning-probe", type=Path, default=None,
                    help="path to a stored eval/aci_learning_probe.json "
                         "(regenerate with tools/aci_learning_probe.py)")
    ap.add_argument("--live-uncertainty", type=Path, default=None,
                    help="path to a stored eval/live_uncertainty.json "
                         "(regenerate with tools/live_uncertainty.py)")
    ap.add_argument("--projection-contract", type=Path, default=None,
                    help="path to a stored eval/projection_contract.json "
                         "(regenerate with tools/projection_contract.py)")
    ap.add_argument("--token-proxy-calibration", type=Path, default=None,
                    help="path to a stored eval/token_proxy_calibration.json "
                         "(regenerate with tools/token_proxy_calibration.py)")
    ap.add_argument("--acceptance-power", type=Path, default=None,
                    help="path to a stored eval/acceptance_power.json "
                         "(regenerate with tools/acceptance_power.py)")
    ap.add_argument("--task-admissibility", type=Path, default=None,
                    help="path to a stored eval/task_admissibility.json "
                         "(regenerate with tools/task_admissibility.py)")
    ap.add_argument("--without-arm", type=Path, default=None,
                    help="path to the paired control arm's results "
                         "(default bench/aci/results/live_ab_without_read_files.json); "
                         "C35 compares it against the with arm, and this override exists so "
                         "the negative control can point the gate at a deliberately "
                         "mismatched control")
    ap.add_argument("--statistics-crosscheck", type=Path, default=None,
                    help="path to a stored eval/statistics_crosscheck.json; the override "
                         "exists so C37's negative control can point the gate at a "
                         "cross-check computed against deliberately perturbed published "
                         "values (C33 once hard-coded its path and the negative control "
                         "passed for the wrong reason)")
    ap.add_argument("--evidence", type=Path, default=ROOT / "eval/evidence.json")
    ap.add_argument("--skip-tests", action="store_true",
                    help="skip cargo test; C6/C7 become stale and fail the gate")
    args = ap.parse_args(argv)
    try:
        selected, explicit_inputs = selected_paths(ROOT, args, EVIDENCE_ARTIFACTS)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    selected['@task_set'] = args.task_set.resolve()
    source_before = source_snapshot(ROOT)
    input_before = file_hashes(selected)
    generated = {}
    def artifact_path(name):
        return selected[name]

    # ── regenerate or load the Rust-side metrics ──
    if "eval/metrics.json" in explicit_inputs:
        metrics_path = artifact_path("eval/metrics.json")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics_source = str(metrics_path)
        metrics_regenerated = False
    else:
        metrics_path = args.evidence.resolve().with_name(args.evidence.stem + ".metrics.json")
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        command = ["cargo", "run", "--example", "eval_metrics", "--quiet", "--", "--out", str(metrics_path)]
        proc = run(command)
        if proc.returncode != 0:
            print("FAIL: could not regenerate eval/metrics.json", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
            return 1
        selected["eval/metrics.json"] = metrics_path
        generated["eval/metrics.json"] = {"argv": command, "exit_code": proc.returncode,
                                          "sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest()}
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics_source = str(metrics_path)
        metrics_regenerated = True

    now = datetime.now(timezone.utc).isoformat()
    claims: list[dict] = []

    # ── C1 / C2: mock bench ratios ──
    tok_ratio, call_ratio, n_tasks, bench_meta = bench_ratios(artifact_path("bench/aci/results/latest.json"))
    claims.append({
        "id": "C1", "claim": THRESHOLDS["C1"]["desc"],
        **token_caliber_fields("C1"),
        "threshold": "<= 0.50", "value": round(tok_ratio, 4),
        "pass": tok_ratio <= THRESHOLDS["C1"]["value"],
        "mode": "mock", "sample_size": n_tasks, "measured_at": bench_meta["generated_at"],
        "command": "python tools/claim_gate.py",
        "source": ["bench/aci/results/latest.json", "bench/aci/runners/run_suite.py"],
        "notes": "seeded mock trajectories (no live model); ratio = mean D per-task observation tokens / mean A",
    })
    claims.append({
        "id": "C2", "claim": THRESHOLDS["C2"]["desc"],
        "threshold": "<= 0.70", "value": round(call_ratio, 4),
        "pass": call_ratio <= THRESHOLDS["C2"]["value"],
        "mode": "mock", "sample_size": n_tasks, "measured_at": bench_meta["generated_at"],
        "command": "python tools/claim_gate.py",
        "source": ["bench/aci/results/latest.json", "bench/aci/runners/run_suite.py"],
        "notes": "seeded mock trajectories; ratio = mean D tool_calls / mean A tool_calls",
    })

    # ── C3: diff-class expected/found completeness ──
    c3 = metrics["reducer_diagnostic_completeness"]["diff_class"]
    claims.append({
        "id": "C3", "claim": THRESHOLDS["C3"]["desc"],
        "threshold": ">= 0.90", "value": round(c3["rate"], 4),
        "pass": c3["rate"] >= THRESHOLDS["C3"]["value"],
        "mode": "deterministic", "sample_size": c3["total"],
        "measured_at": now,
        "command": "cargo run --example eval_metrics -- --out eval/metrics.json",
        "source": [metrics_source, "eval/manifest.json", "examples/eval_metrics.rs",
                   "src/reducers/pytest.rs", "src/reducers/cargo.rs"],
        "detail": {"complete": c3["complete"], "total": c3["total"]},
        "notes": "scope: expect.diff_class=true entries (pytest assert `==`, cargo E0308); git/npm/panic failures carry no expected/found pair by nature",
    })

    # ── C4: one-step recovery structural checks ──
    c4_rate, c4_checks = recovery_rate(metrics)
    claims.append({
        "id": "C4", "claim": THRESHOLDS["C4"]["desc"],
        "threshold": "== 1.00", "value": round(c4_rate, 4),
        "pass": c4_rate >= THRESHOLDS["C4"]["value"],
        "mode": "deterministic", "sample_size": len(c4_checks),
        "measured_at": now,
        "command": "cargo run --example eval_metrics -- --out eval/metrics.json",
        "source": [metrics_source, "src/ops/file.rs", "examples/eval_metrics.rs",
                   "tests/aci_1_0_ops_tests.rs"],
        "detail": c4_checks,
        "notes": "E_STALE_HASH data.actual_hash/expected_hash + retry; E_AMBIGUOUS matches[] line/offset/snippet + widen retry",
    })

    # ── C5: quickstart-only learning cost, measured with real model calls ──
    # The probe gives the model ONLY docs/quickstart/aci-mcp.md (no tool schemas)
    # and executes every op it emits through the real ae --serve --agent path.
    # The gated number is op acceptance conditional on the agent emitting the
    # documented shape: if the quickstart teaches the call shape correctly, the
    # server should accept what a doc-only reader produces.
    learning_path = artifact_path('eval/aci_learning_probe.json')
    if learning_path.exists():
        learning = json.loads(learning_path.read_text(encoding="utf-8"))
        summary = learning.get("summary", {})
        value = summary.get("op_acceptance_given_ops_emitted")
        scored = summary.get("scored_rows") or 0
        api_errors = summary.get("api_error_rows") or 0
        # Fail-closed: a probe that measured nothing (all rows errored) must not
        # pass by having a null value, and must not pass on a tiny sample either.
        measured = value is not None and scored > 0 and api_errors == 0
        claims.append({
            "id": "C5", "claim": THRESHOLDS["C5"]["desc"],
            "threshold": ">= 0.70 (conditional on the agent emitting ops)",
            "value": value, "pass": bool(measured and value >= THRESHOLDS["C5"]["value"]),
            "mode": "live_model_probe", "sample_size": scored,
            "measured_at": learning.get("generated_at"),
            "command": "python tools/aci_learning_probe.py --repeat 3 --out eval/aci_learning_probe.json",
            "source": ["tools/aci_learning_probe.py", "docs/quickstart/aci-mcp.md",
                       "eval/aci_learning_probe.json"],
            "detail": {
                "first_attempt_op_acceptance": summary.get("first_attempt_op_acceptance"),
                "op_acceptance_given_ops_emitted": value,
                "task_success": summary.get("task_success"),
                "hash_handoff_rate": summary.get("hash_handoff_rate"),
                "rows_with_no_ops_emitted": summary.get("rows_with_no_ops_emitted"),
                "scored_rows": scored,
                "api_error_rows": api_errors,
                "model": learning.get("model"),
                "doc_under_test": learning.get("doc_under_test"),
            },
            "notes": "real model calls, quickstart doc only as the system prompt, no tool schemas; "
                     "every emitted op is executed through the real `ae --serve --agent`. Acceptance "
                     "is conditional on the agent emitting a documented shape, so a model that "
                     "answers in prose is reported separately (rows_with_no_ops_emitted) instead of "
                     "being scored as a rejected contract. This is the metric C5 previously lacked; "
                     "the raw task-success half is reported but not gated (it also depends on model "
                     "capability, not only on the doc)",
        })
    else:
        claims.append({
            "id": "C5", "claim": THRESHOLDS["C5"]["desc"],
            "threshold": ">= 0.70", "value": None, "pass": False,
            "mode": "live_model_probe", "measured_at": now,
            "command": "python tools/aci_learning_probe.py --out eval/aci_learning_probe.json",
            "source": ["tools/aci_learning_probe.py", "docs/quickstart/aci-mcp.md"],
            "notes": f"missing evidence artifact: {learning_path}",
        })

    # ── C9: compact vs JSON, measured by examples/compact_ratio.rs ──
    if "eval/compact_ratio.json" in explicit_inputs:
        compact_path = artifact_path("eval/compact_ratio.json")
        compact_source = str(compact_path)
        compact_regenerated = False
    else:
        compact_path = args.evidence.resolve().with_name(args.evidence.stem + ".compact-ratio.json")
        compact_path.parent.mkdir(parents=True, exist_ok=True)
        command = ["cargo", "run", "--example", "compact_ratio", "--quiet", "--", "--out", str(compact_path)]
        proc = run(command)
        if proc.returncode != 0:
            print("FAIL: could not regenerate eval/compact_ratio.json", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
            return 1
        selected["eval/compact_ratio.json"] = compact_path
        generated["eval/compact_ratio.json"] = {"argv": command, "exit_code": proc.returncode,
                                                "sha256": hashlib.sha256(compact_path.read_bytes()).hexdigest()}
        compact_source = str(compact_path)
        compact_regenerated = True
    compact_report = json.loads(compact_path.read_text(encoding="utf-8"))
    c9 = compact_ratio_claim(compact_report)
    claims.append({
        "id": "C9", "claim": THRESHOLDS["C9"]["desc"],
        **token_caliber_fields("C9"),
        "threshold": ">= 0.40", "value": c9["value"],
        "pass": c9["pass"],
        "mode": "deterministic", "sample_size": compact_report.get("overall", {}).get("case_count"),
        "measured_at": now,
        "command": "cargo run --example compact_ratio -- --out eval/compact_ratio.json",
        "source": ["examples/compact_ratio.rs", "src/compact.rs", "src/server.rs", compact_source],
        "detail": c9["detail"],
        "notes": "scope is the compact ENCODING layer only: small response envelope must save >=0.40; "
                 "observation payloads must stay lossless but are NOT promised to shrink "
                 "(measured headline is negative); Observation Budget is a separate layer",
    })

    # ── C6 / C7 / C8: cargo test gates ──
    def test_claim(cid: str, test_args: list[str], source: list[str], notes: str) -> None:
        if args.skip_tests:
            claims.append({"id": cid, "claim": THRESHOLDS[cid]["desc"],
                           "threshold": THRESHOLDS[cid]["value"], "value": None,
                           "pass": False, "stale": True, "mode": "cargo_test",
                           "measured_at": now, "platform": sys.platform,
                           "command": "cargo test " + " ".join(test_args),
                           "source": source, "notes": notes + " (skipped by --skip-tests)"})
            return
        proc = run(["cargo", "test", "--quiet", *test_args])
        totals = summarize_test_output(proc.stdout)
        ok = proc.returncode == 0 and totals["passed"] > 0 and totals["failed"] == 0
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        claims.append({"id": cid, "claim": THRESHOLDS[cid]["desc"],
                       "threshold": "all pass", "value": 1.0 if ok else 0.0,
                       "pass": ok, "mode": "cargo_test", "measured_at": now,
                       "platform": sys.platform,
                       "command": "cargo test " + " ".join(test_args),
                       "source": source,
                       "result_tail": tail,
                       "exit_code": proc.returncode,
                       "stdout_tail": (proc.stdout or "")[-4000:],
                       "stderr_tail": (proc.stderr or "")[-4000:],
                       "test_totals": totals,
                       "notes": notes})

    test_claim("C6", ["--test", "aci_1_0_closed_loop_acceptance"],
               ["tests/aci_1_0_closed_loop_acceptance.rs", "src/ops/trash.rs", "src/ops/tx_ops.rs"],
               "step 6 covers file.remove (trash) -> tx.restore incl. across restarts")
    test_claim("C7", [], ["Cargo.toml", "tests/"], "full workspace test suite")
    test_claim("C8", ["--test", "process_lifecycle_tests"],
               ["tests/process_lifecycle_tests.rs", "src/process_lifecycle.rs",
                "src/process_lifecycle_windows.rs", "src/ops/process_ops.rs"],
               "process lifecycle contract: ownership echo, monotonic cursor, idempotent kill, "
               "tree termination, ConPTY + restart reconciliation; test file is #![cfg(windows)], "
               "so a pass only proves the contract on Windows")

    # ── C10: README promises (runs after the test targets so the ae binary exists) ──
    readme_path = args.evidence.resolve().parent / "readme_claims.json"
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_command = [sys.executable, "tools/readme_claims_check.py", "--json", str(readme_path),
                      "--cross-shell", str(artifact_path("eval/cross_shell.json")),
                      "--compact-ratio", str(compact_path)]
    proc = run(readme_command)
    selected["@readme_check"] = readme_path
    generated["@readme_check"] = {"argv": readme_command, "exit_code": proc.returncode,
                                  "sha256": hashlib.sha256(readme_path.read_bytes()).hexdigest() if readme_path.is_file() else None}
    readme_ok = proc.returncode == 0
    readme_checks: list[dict] = []
    if readme_path.exists():
        try:
            readme_checks = json.loads(readme_path.read_text(encoding="utf-8")).get("checks", [])
        except json.JSONDecodeError:
            readme_checks = []
    claims.append({
        "id": "C10", "claim": THRESHOLDS["C10"]["desc"],
        "threshold": "all pass", "value": 1.0 if readme_ok else 0.0, "pass": readme_ok,
        "mode": "deterministic", "sample_size": len(readme_checks), "measured_at": now,
        "platform": sys.platform,
        "command": "python tools/readme_claims_check.py",
        "source": ["README.md", "tools/readme_claims_check.py", "tests/integration_tests.rs",
                   str(readme_path), "eval/cross_shell.json", "eval/compact_ratio.json"],
        "execution": {"exit_code": proc.returncode, "argv": readme_command},
        "detail": {
            "checks": len(readme_checks),
            "failed": [c.get("name") for c in readme_checks if not c.get("pass")],
            "exit_code": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-2000:],
        },
        "notes": "documented REPL examples must run and match their documented output, and README "
                 "implementation numbers must equal their source of truth; coverage is the explicit "
                 "registry in tools/readme_claims_check.py, not free-form prose",
    })

    # ── C11: cross-shell ratios from a stored measurement ──
    # `docs/acceptance-criteria.md` §2 makes output equivalence a PREREQUISITE of the
    # timing comparison, so a measurement whose equivalence was not proven cannot pass
    # even if the ratios look good.
    cross_path = artifact_path('eval/cross_shell.json')
    cross = json.loads(cross_path.read_text(encoding="utf-8"))
    cross_agg = cross.get("aggregate", {})
    cross_method = cross.get("method", {})
    worst_ratio = cross_agg.get("worst_ratio_ae_over_pwsh")
    outputs_equivalent = bool(cross_agg.get("all_outputs_equivalent"))
    not_equivalent = cross_agg.get("operations_without_proven_equivalence") or []
    cross_ok = (
        bool(cross_agg.get("all_commands_ok"))
        and outputs_equivalent
        and bool(cross_method.get("interleaved"))
        and worst_ratio is not None
        and worst_ratio <= THRESHOLDS["C11"]["value"]
    )
    claims.append({
        "id": "C11", "claim": THRESHOLDS["C11"]["desc"],
        "threshold": "<= 0.50", "value": worst_ratio, "pass": cross_ok,
        "mode": "wall_clock",
        "sample_size": cross_agg.get("gated_operations_vs_pwsh", cross_agg.get("gated_operations")),
        "measured_at": cross.get("generated_at"),
        "platform": sys.platform,
        "command": "python tools/cross_shell_bench.py",
        "source": ["tools/cross_shell_bench.py", "eval/cross_shell.json", "README.md"],
        "detail": {
            "per_operation_ratio_vs_pwsh": {
                row.get("name"): row.get("ratio_ae_over_pwsh") for row in cross.get("operations", [])
            },
            "per_operation_ratio_vs_cmd": {
                row.get("name"): row.get("ratio_ae_over_cmd") for row in cross.get("operations", [])
            },
            "worst_ratio_ae_over_cmd": cross_agg.get("worst_ratio_ae_over_cmd"),
            "all_commands_ok": cross_agg.get("all_commands_ok"),
            "failed_commands": cross_agg.get("failed_commands"),
            "all_outputs_equivalent": outputs_equivalent,
            "operations_without_proven_equivalence": not_equivalent,
            "interleaved": bool(cross_method.get("interleaved")),
            "cold_start_reported": bool(cross_method.get("cold_start")),
            "machine": cross.get("machine", {}).get("processor"),
            "iterations": cross_method.get("iterations"),
            "wall_clock_context": cross.get("wall_clock_context", {}).get("arms"),
        },
        "notes": "stored wall-clock measurement (20 interleaved iterations + warm-up, process "
                 "startup included, single machine). §2 of the acceptance criteria requires "
                 "output equivalence to be proven BEFORE the times are compared, so "
                 "`all_outputs_equivalent` is part of the pass condition. The pre-registered "
                 "comparator is PowerShell; `per_operation_ratio_vs_cmd` is context only, and "
                 "it is the shell the raw-shell baseline arm actually runs through — the two "
                 "must not be conflated when the headline is quoted",
    })

    # ── C14: batch-read envelope on a frozen trajectory ──
    replay_path = artifact_path('eval/tf45_envelope_replay.json')
    if replay_path.exists():
        replay_report = json.loads(replay_path.read_text(encoding="utf-8"))
        c14 = batch_envelope_claim(replay_report)
        claims.append({
            "id": "C14", "claim": THRESHOLDS["C14"]["desc"],
            **token_caliber_fields("C14"),
            "threshold": ">= 0.15", "value": c14["value"], "pass": c14["pass"],
            "mode": "deterministic", "sample_size": c14["detail"]["calls_replayed"],
            "measured_at": replay_report.get("generated_at"),
            "command": "python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json",
            "source": ["tools/tf45_envelope_replay.py", "bench/aci/runners/live_agent_loop.py",
                       "src/ops/file.rs", "src/ops/common.rs", "eval/tf45_envelope_replay.json"],
            "detail": c14["detail"],
            "notes": "frozen-trajectory replay: the read ops the model actually issued in the stored "
                     "live run are re-run against the current binary and projected twice (legacy full "
                     "`sha256:<64 hex>` vs the compact 16-hex digest). It measures the observation "
                     "surface, NOT model behaviour; a call only counts when the projection the stored "
                     "run actually used reproduces its recorded token count, and the rest are listed "
                     "with both numbers (so a client change without a live re-run fails instead of "
                     "comparing across projections). The budget half of the claim is structural: a worst-case "
                     "8x300-line batch must not exceed `max_total_lines`, and paginating a 250-line "
                     "file by `next_start_line` must recover it line for line",
        })
    else:
        claims.append({
            "id": "C14", "claim": THRESHOLDS["C14"]["desc"],
            **token_caliber_fields("C14"),
            "threshold": ">= 0.15", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json",
            "source": ["tools/tf45_envelope_replay.py"],
            "notes": f"missing evidence artifact: {replay_path}",
        })

    # ── C16: compact read projection on a frozen trajectory ──
    read_path = artifact_path('eval/read_path_breakdown.json')
    if read_path.exists():
        read_report = json.loads(read_path.read_text(encoding="utf-8"))
        c16 = compact_read_claim(read_report)
        claims.append({
            "id": "C16", "claim": THRESHOLDS["C16"]["desc"],
            **token_caliber_fields("C16"),
            "threshold": ">= 0.10", "value": c16["value"], "pass": c16["pass"],
            "mode": "deterministic", "sample_size": c16["detail"]["calls"],
            "measured_at": read_report.get("generated_at"),
            "command": "python tools/read_path_breakdown.py --out eval/read_path_breakdown.json",
            "source": ["tools/read_path_breakdown.py", "bench/aci/runners/live_agent_loop.py",
                       "tools/tf45_envelope_replay.py", "eval/read_path_breakdown.json"],
            "detail": c16["detail"],
            "notes": "the same envelope is projected twice with the real projector "
                     "(format_aci_result(compact=False) is the pre-change rendering, compact=True is "
                     "current), so the delta is measured rather than re-implemented. Scope is the "
                     "reference client's rendering of the read ops, NOT the product envelope: dropping "
                     "`total_lines` is only sound when the client shows the text, which is why the "
                     "product contract is untouched. It says nothing about model behaviour",
        })
    else:
        claims.append({
            "id": "C16", "claim": THRESHOLDS["C16"]["desc"],
            **token_caliber_fields("C16"),
            "threshold": ">= 0.10", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/read_path_breakdown.py --out eval/read_path_breakdown.json",
            "source": ["tools/read_path_breakdown.py"],
            "notes": f"missing evidence artifact: {read_path}",
        })

    # ── C18: exec must launch a name-dispatching shim by its invoked name ──
    shim_path = artifact_path('eval/exec_failure_breakdown.json')
    if shim_path.exists():
        shim_report = json.loads(shim_path.read_text(encoding="utf-8"))
        c18 = shim_launch_claim(shim_report)
        claims.append({
            "id": "C18", "claim": THRESHOLDS["C18"]["desc"],
            "threshold": "== 1.00", "value": c18["value"], "pass": c18["pass"],
            "mode": "deterministic", "sample_size": len(c18["detail"]["commands"] or {}),
            "measured_at": shim_report.get("generated_at"),
            "command": "python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json",
            "source": ["tools/exec_failure_breakdown.py", "src/process_command.rs",
                       "src/process_runner.rs", "eval/exec_failure_breakdown.json"],
            "detail": c18["detail"],
            "notes": "on a rustup install `cargo.exe`/`rustc.exe` are symlinks to `rustup.exe` and "
                     "rustup picks the tool from the name it was invoked as, so a launcher must not "
                     "canonicalise the final symlink away. The defect made `cargo check` return exit 100 "
                     "with '0 error(s)', `cargo build` read as the `+build` toolchain, and "
                     "`cargo --version` print the rustup version — silently breaking every Rust task in "
                     "condition D while raw shell (which spawns through cmd) was unaffected. Fail-closed: "
                     "the gate also requires that this machine actually has such a shim",
        })
    else:
        claims.append({
            "id": "C18", "claim": THRESHOLDS["C18"]["desc"],
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json",
            "source": ["tools/exec_failure_breakdown.py"],
            "notes": f"missing evidence artifact: {shim_path}",
        })

    # ── C22: a bare npm-family name must resolve to a launchable image ──
    if shim_path.exists():
        bare_report = json.loads(shim_path.read_text(encoding="utf-8"))
        c22 = bare_name_claim(bare_report)
        claims.append({
            "id": "C22", "claim": THRESHOLDS["C22"]["desc"],
            "threshold": "== 1.00", "value": c22["value"], "pass": c22["pass"],
            "mode": "deterministic", "sample_size": len(c22["detail"]["commands"] or {}),
            "measured_at": bare_report.get("generated_at"),
            "command": "python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json",
            "source": ["tools/exec_failure_breakdown.py", "src/process_command.rs",
                       "eval/exec_failure_breakdown.json"],
            "detail": c22["detail"],
            "notes": "an extensionless sibling on PATH is normally a POSIX shell script that Win32 "
                     "cannot launch (`npm` sits next to `npm.cmd`), and `cmd.exe` resolves a bare "
                     "name through PATHEXT. Resolving the bare file first made every "
                     "`exec.run([\"npm\", ...])` / `[\"npx\", ...]` fail with `E_EXEC_SPAWN` while raw "
                     "shell was unaffected — it cost condition D a wasted call plus ~48 observation "
                     "tokens on each npm task. Fail-closed: the gate also requires that this machine "
                     "actually shadows such a name",
        })
    else:
        claims.append({
            "id": "C22", "claim": THRESHOLDS["C22"]["desc"],
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json",
            "source": ["tools/exec_failure_breakdown.py"],
            "notes": f"missing evidence artifact: {shim_path}",
        })

    # ── C23: the ts task must score behaviour, not the golden patch's text ──
    ts_fixture_path = artifact_path('eval/ts_fixture_audit.json')
    if ts_fixture_path.exists():
        ts_report = json.loads(ts_fixture_path.read_text(encoding="utf-8"))
        c23 = ts_fixture_contract_claim(ts_report)
        claims.append({
            "id": "C23", "claim": THRESHOLDS["C23"]["desc"],
            "threshold": "== 1.00", "value": c23["value"], "pass": c23["pass"],
            "mode": "deterministic",
            "sample_size": 3,
            "measured_at": (ts_report.get("generated_at")),
            "command": "python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json",
            "source": ["tools/ts_fixture_audit.py", "bench/aci/tasks/ts_fix_type_error.json",
                       "bench/aci/fixtures/ts_fix_type_error/**", "eval/ts_fixture_audit.json"],
            "detail": c23["detail"],
            "notes": "the v1.1.0 predicate matched the golden patch as a literal string "
                     "(`file_contains \"return a + b\"`), so a run that fixed the type error by "
                     "keeping the intermediate binding was scored as a failure — five of six "
                     "stored runs. The v1.2.0 predicate runs `tsc --noEmit` through the "
                     "fixture's pinned TypeScript, and this gate also checks that the pristine "
                     "fixture still fails it and the GOLDEN patch still passes it, so the task "
                     "cannot silently become pre-solved or unsolvable",
        })
    else:
        claims.append({
            "id": "C23", "claim": THRESHOLDS["C23"]["desc"],
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json",
            "source": ["tools/ts_fixture_audit.py"],
            "notes": f"missing evidence artifact: {ts_fixture_path}",
        })

    # ── C24: every GOLDEN-bearing task is unsolved pristine and solved by GOLDEN ──
    task_set_path = artifact_path('eval/task_set_audit.json')
    if task_set_path.exists():
        task_set_report = json.loads(task_set_path.read_text(encoding="utf-8"))
        c24 = task_set_consistency_claim(task_set_report, args.task_set)
        claims.append({
            "id": "C24", "claim": THRESHOLDS["C24"]["desc"],
            "threshold": "== 1.00", "value": c24["value"], "pass": c24["pass"],
            "mode": "deterministic",
            "sample_size": len(c24["detail"]["tasks_covered"]),
            "measured_at": task_set_report.get("generated_at"),
            "command": "python tools/task_set_audit.py --out eval/task_set_audit.json",
            "source": ["tools/task_set_audit.py", "tools/trajectory_replay.py",
                       "bench/aci/tasks/manifest.json", "bench/aci/tasks/*.json",
                       "bench/aci/fixtures/**", "eval/task_set_audit.json", str(args.task_set.resolve())],
            "detail": c24["detail"],
            "notes": "evaluated with the live runner's check_success; coverage, task-set version "
                     "and effective predicates must match the requested versioned task set. "
                     "Pristine must fail, GOLDEN and registered equivalents must pass. "
                     "Historical replay counts are reported separately and are not live acceptance.",
        })
    else:
        claims.append({
            "id": "C24", "claim": THRESHOLDS["C24"]["desc"],
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/task_set_audit.py --out eval/task_set_audit.json",
            "source": ["tools/task_set_audit.py"],
            "notes": f"missing evidence artifact: {task_set_path}",
        })

    # ── C25: the live numbers must carry uncertainty, and the gate must say
    # what the sample can actually support ──
    unc_path = artifact_path('eval/live_uncertainty.json')
    if unc_path.exists():
        unc = json.loads(unc_path.read_text(encoding="utf-8"))
        arms = unc.get("arms", [])
        checks: dict[str, bool] = {}
        detail_arms = []
        for arm in arms:
            name = arm.get("artifact")
            sr = arm.get("success_rate", {})
            # Every arm must have an interval on both conditions, a paired view,
            # a ratio bootstrap, and rows whose aggregates were recomputed from
            # the raw rows (so a stored aggregate cannot drift from its rows).
            has_intervals = all(
                sr.get(c, {}).get("wilson_ci95") for c in ("raw_shell", "verseshell_aci")
            )
            paired = arm.get("paired", {})
            has_paired = all(paired.get(m, {}).get("n_pairs", 0) > 0
                             for m in ("success_rate", "tool_calls", "observation_tokens"))
            boot = arm.get("ratio_bootstrap", {})
            proxy_kinds = ("tool_call_ratio", "observation_token_ratio")
            has_boot = all(
                boot.get(k, {}).get("bootstrap_ci95") for k in proxy_kinds
            )
            # Degeneration 1: the published interval must be the task-clustered one.
            # Resampling rows is a real regression — it made the L2 "saves >=15%"
            # verdict claimable at an upper bound of 0.8551 when the clustered upper
            # bound is 0.9061, i.e. past the 0.90 threshold.
            clustered = all(boot.get(k, {}).get("bootstrap_unit") == "task"
                            for k in proxy_kinds)
            # Degeneration 2: the real-tokenizer reading must be published next to the
            # proxy. docs/acceptance-criteria.md §4.2 makes it a hard requirement, and
            # on the round-12 data the two point in OPPOSITE directions, so a product
            # that silently drops it can only ever show the flattering half.
            real_tokenizer = all(
                boot.get(k, {}).get("bootstrap_ci95")
                for k in ("usage_token_ratio", "prompt_token_ratio",
                          "completion_token_ratio"))
            no_drift = not arm.get("stored_aggregate_mismatches")
            checks[f"{name}.intervals"] = bool(has_intervals)
            checks[f"{name}.paired"] = bool(has_paired)
            checks[f"{name}.ratio_bootstrap"] = bool(has_boot)
            checks[f"{name}.ratio_bootstrap_is_task_clustered"] = bool(clustered)
            checks[f"{name}.real_tokenizer_published"] = bool(real_tokenizer)
            checks[f"{name}.aggregate_matches_rows"] = bool(no_drift)
            detail_arms.append({
                "artifact": name,
                "n_rows": arm.get("n_rows"),
                "success_rate_A": sr.get("raw_shell", {}).get("success_rate"),
                "success_rate_D": sr.get("verseshell_aci", {}).get("success_rate"),
                "success_ci_A": sr.get("raw_shell", {}).get("wilson_ci95"),
                "success_ci_D": sr.get("verseshell_aci", {}).get("wilson_ci95"),
                "unpaired_p": arm.get("unpaired_z_test_success", {}).get("p_value"),
                "mcnemar_p": arm.get("paired_success_mcnemar", {}).get("p_value_exact"),
                "tool_ratio_point": boot.get("tool_call_ratio", {}).get("point_estimate"),
                "tool_ratio_ci": boot.get("tool_call_ratio", {}).get("bootstrap_ci95"),
                "token_ratio_point": boot.get("observation_token_ratio", {}).get("point_estimate"),
                "token_ratio_ci": boot.get("observation_token_ratio", {}).get("bootstrap_ci95"),
                "token_ratio_ci_row": boot.get("observation_token_ratio", {}).get("bootstrap_ci95_row"),
                "token_ratio_unit": boot.get("observation_token_ratio", {}).get("bootstrap_unit"),
                "usage_token_ratio_point": boot.get("usage_token_ratio", {}).get("point_estimate"),
                "usage_token_ratio_ci": boot.get("usage_token_ratio", {}).get("bootstrap_ci95"),
                "prompt_token_ratio_point": boot.get("prompt_token_ratio", {}).get("point_estimate"),
                "prompt_token_ratio_ci": boot.get("prompt_token_ratio", {}).get("bootstrap_ci95"),
                "completion_token_ratio_point":
                    boot.get("completion_token_ratio", {}).get("point_estimate"),
                "completion_token_ratio_ci":
                    boot.get("completion_token_ratio", {}).get("bootstrap_ci95"),
                "p_token_ratio_below_frozen_target":
                    boot.get("observation_token_ratio", {}).get("prob_ratio_below_frozen_target"),
                "n_for_80pct_power_success":
                    paired.get("success_rate", {}).get("n_for_80pct_power"),
                "significance_notes": arm.get("significance_notes", []),
            })
        value = 1.0 if (checks and all(checks.values())) else 0.0
        claims.append({
            "id": "C25", "claim": THRESHOLDS["C25"]["desc"],
            **token_caliber_fields("C25"),
            "threshold": "== 1.00", "value": value, "pass": value == 1.0,
            "mode": "statistical_audit", "sample_size": sum(a.get("n_rows") or 0 for a in arms),
            "measured_at": unc.get("generated_at"),
            "command": "python tools/live_uncertainty.py --out eval/live_uncertainty.json",
            "source": ["tools/live_uncertainty.py", "bench/aci/results/latest_live.json",
                       "bench/aci/results/live_ab_without_read_files.json",
                       "eval/live_uncertainty.json"],
            "detail": {"checks": checks, "arms": detail_arms,
                       "method": unc.get("method")},
            "notes": "Wilson interval per success rate, pooled z-test and McNemar on the paired "
                     "(task, seed) cells, a paired t interval and a bootstrap interval for the "
                     "headline D/A ratios, plus a recomputation of every stored aggregate from "
                     "rows[] so an aggregate cannot drift away from its raw rows. It gates the "
                     "PRESENCE of uncertainty, not its favourability: a wide interval that makes a "
                     "difference non-significant is a correct result, and the gate still passes "
                     "because the number is honestly reported",
        })
    else:
        claims.append({
            "id": "C25", "claim": THRESHOLDS["C25"]["desc"],
            **token_caliber_fields("C25"),
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "statistical_audit", "measured_at": now,
            "command": "python tools/live_uncertainty.py --out eval/live_uncertainty.json",
            "source": ["tools/live_uncertainty.py"],
            "notes": f"missing evidence artifact: {unc_path}",
        })

    # ── C26: the reference client must project what each tool promises ──
    proj_path = artifact_path('eval/projection_contract.json')
    if proj_path.exists():
        proj = json.loads(proj_path.read_text(encoding="utf-8"))
        summary = proj.get("summary", {})
        checks = proj.get("checks", [])
        passed = summary.get("passed", 0)
        total = summary.get("checks", 0)
        # Fail-closed: an artifact with zero checks must not pass vacuously.
        ok = bool(total) and passed == total
        claims.append({
            "id": "C26", "claim": THRESHOLDS["C26"]["desc"],
            **token_caliber_fields("C26"),
            "threshold": "== 1.00", "value": (passed / total) if total else None,
            "pass": ok, "mode": "real_op_projection_audit",
            "sample_size": total,
            "measured_at": proj.get("generated_at"),
            "command": "python tools/projection_contract.py --out eval/projection_contract.json",
            "source": ["tools/projection_contract.py", "bench/aci/runners/live_agent_loop.py",
                       "eval/projection_contract.json"],
            "detail": {
                "checks": total,
                "passed": passed,
                "failed": [c.get("check") for c in checks if not c.get("pass")],
                "per_check": [{"check": c.get("check"), "pass": c.get("pass"),
                               "detail": c.get("detail")} for c in checks],
            },
            "notes": "each check runs a real op through `ae --serve --agent` and inspects what "
                     "format_aci_result hands the model. It exists because three fields the server "
                     "sent (and the tool descriptions promised) were silently dropped: "
                     "`repo.search` matches projected to only `{\"ok\": true}` so search was "
                     "useless and agents fell back to raw `grep`; `repo.summary` lost `top_level`; "
                     "and `E_AMBIGUOUS` lost its candidate sites, which is the payload claim C4's "
                     "one-step recovery depends on. It also asserts the projection does NOT leak "
                     "the host workspace path",
        })

        # ── C30: a default `file.view` must carry the window ──
        # Named separately from C26 because C26's original fixture was a 3-line file,
        # which fell inside the old ten-line cutoff: the defect was invisible to a
        # check that only ever looked at a file small enough to be exempt from it.
        by_name = {c.get("check"): c for c in checks}
        c30_names = ["default window view returns content", "read_many returns content"]
        c30_checks = {n: bool((by_name.get(n) or {}).get("pass")) for n in c30_names}
        c30_ok = all(c30_checks.values())
        claims.append({
            "id": "C30", "claim": THRESHOLDS["C30"]["desc"],
            **token_caliber_fields("C30"),
            "threshold": "== 1.00",
            "value": (sum(c30_checks.values()) / len(c30_checks)) if c30_checks else None,
            "pass": c30_ok, "mode": "real_op_projection_audit",
            "sample_size": len(c30_checks),
            "measured_at": proj.get("generated_at"),
            "command": "python tools/projection_contract.py --out eval/projection_contract.json",
            "source": ["tools/projection_contract.py", "bench/aci/runners/live_agent_loop.py",
                       "eval/projection_contract.json"],
            "detail": {
                "checks": c30_checks,
                "per_check": [by_name.get(n) for n in c30_names],
            },
            "notes": "the reference client gated its read projection on `len(lines) <= 10`, so a "
                     "default `file.view` (window=80) of any file longer than ten lines returned "
                     "only `{ok, content_hash, total_lines}` — the tool description promises a "
                     "window of lines and the client withheld it. Measured on the v2.0.0 live run: "
                     "180/204 `file.view` calls returned metadata only, 45% re-viewed an "
                     "already-viewed path, and D fell back to repo.search (301 calls / 65.7k "
                     "tokens) and shell reads to see content. C26 could not see it because its "
                     "fixture was a 3-line file. The gate is on the two checks that use a 60-line "
                     "file with default arguments, so the cutoff cannot come back unnoticed",
        })
    else:
        claims.append({
            "id": "C26", "claim": THRESHOLDS["C26"]["desc"],
            **token_caliber_fields("C26"),
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "real_op_projection_audit", "measured_at": now,
            "command": "python tools/projection_contract.py --out eval/projection_contract.json",
            "source": ["tools/projection_contract.py"],
            "notes": f"missing evidence artifact: {proj_path}",
        })

    # ── C32: the raw-shell execution path must bound the wall clock AND the tree ──
    # C31 fixed one way the raw-shell path could silently ruin a run (a decode crash
    # scored as a task failure). C32 covers the other, worse one: the path could not
    # bound a command whose child holds the stdout pipe, so a D-arm
    # `open('CON','r').read()` hung a whole round for 11.5 hours and destroyed the 61
    # rows already completed. `subprocess.run(timeout=)` cannot fix that — its timeout
    # fires but kills only the direct child, and `communicate()` then blocks forever
    # on the pipe the grandchild still holds. The check therefore also asserts the
    # pre-fix shape still fails, so it cannot pass by measuring nothing.
    exec_path = artifact_path('eval/harness_exec_contract.json')
    if exec_path.exists():
        ec = json.loads(exec_path.read_text(encoding="utf-8"))
        ec_checks = {c.get("id"): bool(c.get("pass")) for c in (ec.get("checks") or [])}
        ec_ok = bool(ec_checks) and all(ec_checks.values())
        detail_by_id = {c.get("id"): c.get("detail") for c in (ec.get("checks") or [])}
        claims.append({
            "id": "C32", "claim": THRESHOLDS["C32"]["desc"],
            "threshold": "== 1.00",
            "value": (sum(ec_checks.values()) / len(ec_checks)) if ec_checks else None,
            "pass": ec_ok, "mode": "harness_exec_contract",
            "sample_size": len(ec_checks),
            "measured_at": ec.get("generated_at"),
            "command": "python tools/harness_exec_contract.py "
                       "--out eval/harness_exec_contract.json",
            "source": ["tools/harness_exec_contract.py",
                       "bench/aci/runners/live_agent_loop.py",
                       "eval/harness_exec_contract.json"],
            "detail": {
                "checks": ec_checks,
                "mechanism": ec.get("mechanism"),
                "negative_control": detail_by_id.get(
                    "negative_control_pre_fix_shape_still_hangs"),
            },
            "notes": "`execute_shell_cmd` used `subprocess.run(..., timeout=120)`. On "
                     "2026-09-27 a D-arm command "
                     "`python -c \"open('src/lib.rs','w').write(open('CON','r').read())\"` "
                     "blocked forever reading the Windows console device; the timeout "
                     "fired but killed only the direct child, so `communicate()` blocked "
                     "on the pipe the grandchild held and "
                     "`except subprocess.TimeoutExpired` never ran. The round hung for "
                     "11.5 hours and 61 finished rows were lost because results were "
                     "written only at the end. Fixed by `run_bounded()`: Popen + Job "
                     "Object (KILL_ON_JOB_CLOSE) + TerminateJobObject, with "
                     "`taskkill /T /F` as a second belt, plus per-row checkpoint "
                     "sidecars so a crash can no longer discard completed work. Measured "
                     "alternatives (audit-r12-scratch/probe_shell_timeout.py): run()/ "
                     "stdin=DEVNULL / CREATE_NO_WINDOW all still hang; job object 6.01s "
                     "and taskkill 6.21s both bound it.",
        })
    else:
        claims.append({
            "id": "C32", "claim": THRESHOLDS["C32"]["desc"],
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "harness_exec_contract", "measured_at": now,
            "command": "python tools/harness_exec_contract.py "
                       "--out eval/harness_exec_contract.json",
            "source": ["tools/harness_exec_contract.py"],
            "notes": f"missing evidence artifact: {exec_path}",
        })

    # ── C33: the headline row set must follow the pre-registered §0.6 policy ──
    # C32 fixed how a row is EXECUTED; C33 fixes WHICH rows count. §0.5 said "if either
    # side hits the cap >10%, raise the cap and re-run", but the 2026-09-27 probe showed
    # that is not possible here: the 11 cap-truncated cells re-run at max_tokens=32768
    # gave 0 length-truncations and 9 HTTP 502s (proxy 300s non-streaming limit), and
    # merge_live_runs.py refuses an artifact containing api_error rows. With no way to
    # remove the truncation, the row set must be fixed by a rule written BEFORE the
    # data — so what the gate enforces is CONSISTENCY: no comparison may carry a
    # claimable verdict while the policy blocks it, and both 口径 must be published.
    ap_path = artifact_path('eval/acceptance_power.json')
    tar_path = artifact_path('eval/three_arm_report.json')
    problems33: list[str] = []
    detail33: dict = {}
    if not ap_path.exists():
        problems33.append(f"missing {ap_path}")
    else:
        apd = json.loads(ap_path.read_text(encoding="utf-8"))
        pol = apd.get("row_policy") or {}
        per_arm = pol.get("per_arm") or {}
        comps = pol.get("comparisons") or {}
        detail33["exclusion_limit"] = pol.get("exclusion_limit")
        detail33["primary"] = pol.get("primary")
        detail33["must_also_report"] = pol.get("must_also_report")
        if not per_arm or not comps:
            problems33.append("acceptance_power.json has no row_policy block")
        for cond, a in per_arm.items():
            if a.get("success_analysable") is None or a.get("success_intention_to_treat") is None:
                problems33.append(f"{cond}: both 口径 must be published (analysable + ITT)")
        blocked = {k for k, c in comps.items() if not c.get("claimable")}
        offenders = sorted(
            k for k, v in (apd.get("verdicts") or {}).items()
            if isinstance(v, dict) and v.get("claimable")
            and v.get("row_policy_comparison") in blocked)
        if offenders:
            problems33.append("claimable verdicts on a policy-blocked comparison: "
                              + ", ".join(offenders))
        detail33["blocked_comparisons"] = sorted(blocked)
        detail33["claimable_comparisons"] = sorted(
            k for k, c in comps.items() if c.get("claimable"))
        detail33["per_arm_exclusion"] = {
            c: {"endpoint_rate": a.get("endpoint_rate"),
                "cap_truncated_rate": a.get("cap_truncated_rate")}
            for c, a in per_arm.items()}
        # one implementation, two artifacts: the rates must agree
        if tar_path.exists():
            tpol = (json.loads(tar_path.read_text(encoding="utf-8"))
                    .get("row_policy") or {}).get("per_arm") or {}
            for cond, a in per_arm.items():
                t = tpol.get(cond)
                if not t:
                    problems33.append(f"three_arm_report.json lacks row_policy for {cond}")
                elif (t.get("cap_truncated_rate") != a.get("cap_truncated_rate")
                      or t.get("endpoint_rate") != a.get("endpoint_rate")):
                    problems33.append(f"{cond}: row_policy disagrees between the two artifacts")
        else:
            problems33.append(f"missing {tar_path}")
    claims.append({
        "id": "C33", "claim": THRESHOLDS["C33"]["desc"],
        "threshold": "== 1.00",
        "value": 0.0 if problems33 else 1.0,
        "pass": not problems33, "mode": "row_policy_consistency",
        "measured_at": now,
        "command": "python tools/acceptance_power.py --out eval/acceptance_power.json",
        "source": ["tools/live_uncertainty.py", "tools/acceptance_power.py",
                   "tools/three_arm_report.py", "eval/acceptance_power.json",
                   "eval/three_arm_report.json"],
        "detail": detail33,
        "notes": ("§0.6 fixes which rows count, per comparison, BEFORE the data. The gate "
                  "checks consistency: a blocked comparison must not carry a claimable "
                  "verdict, and both 口径 must be published. "
                  + (" | ".join(problems33) if problems33 else "consistent")),
    })

    # ── C34: the compact read projection must remove the pre-registered share of the
    # NAMED envelope overhead, and it must be re-verified on a task set NEWER than the
    # one the number was discovered on (TF-0117, decided by TF-0116) ──
    # C14/C16 gate the saving as a share of the WHOLE read bucket, and that share moves
    # with the read mix: after C30 the mix became content-dominated, so the same
    # projection that removes ~half of the named overhead shows only ~8% of the total.
    # Neither number is wrong; the bucket-share one is simply not a property of the
    # projection. TF-0116 therefore refused to move the C14/C16 thresholds after seeing
    # the data and registered a SEPARATE, mixture-invariant claim instead.
    # `line_wrapper` plus the derivable `counts` are exactly the parts the compact
    # projection touches, and read_path_breakdown.json attributes them per projection, so
    # the metric is recomputed from the artifact rather than re-implemented here.
    # The "new data" requirement is part of the claim, not decoration: the 45.5% was
    # measured on task set 2.0.0, so a pass on 2.0.0 would be the same batch proving
    # itself. Until a later task set (or the holdout) is measured, this reads FAIL.
    DISCOVERY_VERSION = "2.0.0"
    freeze34_path = artifact_path('eval/task_set_freeze.json')
    freeze34 = {}
    if freeze34_path.exists():
        freeze34 = json.loads(freeze34_path.read_text(encoding="utf-8"))
    version34 = freeze34.get("task_set_version")
    if read_path.exists():
        rt34 = read_report.get("totals") or {}
        lp34 = rt34.get("legacy_parts") or {}
        cp34 = rt34.get("current_parts") or {}
        legacy_oh = float(lp34.get("line_wrapper", 0)) + float(lp34.get("counts", 0))
        current_oh = float(cp34.get("line_wrapper", 0)) + float(cp34.get("counts", 0))
        saving34 = ((legacy_oh - current_oh) / legacy_oh) if legacy_oh else 0.0
        binding34 = replay_source_binding(read_report, freeze34, artifact_path("bench/aci/results/latest_live.json"))
        on_new_data = binding34["pass"]
        # Bind the replay to the selected bytes, actual newer version and frozen task IDs.
        # A fresh code fingerprint alone cannot associate a replay with a changed freeze.
        ev34 = read_report.get("evidence") or {}
        globs34, recorded34 = ev34.get("globs"), ev34.get("fingerprint")
        artifact_fresh = bool(globs34 and recorded34
                              and evidence_fingerprint(globs34) == recorded34)
        claims.append({
            "id": "C34", "claim": THRESHOLDS["C34"]["desc"],
            **token_caliber_fields("C34"),
            "threshold": ">= 0.40 and measured on a fresh artifact from a task set newer than 2.0.0",
            "value": round(saving34, 4),
            "pass": saving34 >= THRESHOLDS["C34"]["value"] and on_new_data and artifact_fresh,
            "mode": "deterministic", "sample_size": rt34.get("calls"),
            "measured_at": read_report.get("generated_at"),
            "command": "python tools/read_path_breakdown.py --out eval/read_path_breakdown.json",
            "source": ["tools/read_path_breakdown.py", "eval/read_path_breakdown.json",
                       "bench/aci/results/latest_live.json", "eval/task_set_freeze.json", "docs/claims-and-evidence.md",
                       "docs/acceptance-criteria.md"],
            "detail": {
                "legacy_named_overhead_chars": legacy_oh,
                "current_named_overhead_chars": current_oh,
                "named_overhead_parts": ["line_wrapper", "counts"],
                "task_set_version_measured_on": binding34["measured_task_set_version"],
                "discovery_task_set_version": DISCOVERY_VERSION,
                "validated_on_new_data": on_new_data,
                "artifact_fresh": artifact_fresh,
                "source_binding": binding34,
                "context_not_gated": {
                    "bucket_share_saving_C16": rt34.get("token_savings"),
                    "content_chars": (cp34.get("content")),
                },
            },
            "notes": "mixture-invariant restatement of the read-projection saving. C14/C16 keep "
                     "their original thresholds and are evaluated separately; this is an ADDITIONAL, separately "
                     "pre-registered claim, registered before round 14's data existed. These "
                     "conditions must hold: measured bytes and task IDs must match the selected freeze, "
                     "the actual version must be newer than 2.0.0, AND the artifact must be "
                     "fresh against its own globs (otherwise bumping the task set would validate "
                     "the claim over the old numbers). Scope is the reference client's rendering "
                     "of the read ops on a frozen call set, NOT model behaviour, and it says "
                     "nothing about total-token cost",
        })
    else:
        claims.append({
            "id": "C34", "claim": THRESHOLDS["C34"]["desc"],
            **token_caliber_fields("C34"),
            "threshold": ">= 0.40 and measured on a task set newer than 2.0.0",
            "value": None, "pass": False, "mode": "deterministic", "measured_at": now,
            "command": "python tools/read_path_breakdown.py --out eval/read_path_breakdown.json",
            "source": ["tools/read_path_breakdown.py"],
            "notes": f"missing evidence artifact: {read_path}",
        })

    # The raw-shell arm had no gated contract check at all (every other gated check
    # looks at the ACI side), which is how a decode crash survived three rounds of
    # headline rewrites while silently scoring 5 runs as task failures.
    # ── C31: the raw-shell observation path must not lose non-ASCII bytes ──
    # The raw-shell arm had no gated contract check at all (every other gated check
    # looks at the ACI side), which is how a decode crash survived three rounds of
    # headline rewrites while silently scoring 5 runs as task failures.
    enc_path = artifact_path('eval/harness_encoding_contract.json')
    if enc_path.exists():
        enc = json.loads(enc_path.read_text(encoding="utf-8"))
        enc_checks = {c.get("name"): bool(c.get("pass")) for c in (enc.get("checks") or [])}
        enc_ok = bool(enc_checks) and all(enc_checks.values())
        enc_detail = enc.get("detail") or {}
        claims.append({
            "id": "C31", "claim": THRESHOLDS["C31"]["desc"],
            **token_caliber_fields("C31"),
            "threshold": "== 1.00",
            "value": (sum(enc_checks.values()) / len(enc_checks)) if enc_checks else None,
            "pass": enc_ok, "mode": "harness_encoding_contract",
            "sample_size": len(enc_checks),
            "measured_at": enc.get("generated_at"),
            "command": "python tools/harness_encoding_contract.py "
                       "--out eval/harness_encoding_contract.json",
            "source": ["tools/harness_encoding_contract.py",
                       "bench/aci/runners/live_agent_loop.py",
                       "eval/harness_encoding_contract.json"],
            "detail": {
                "checks": enc_checks,
                "locale_codec": enc_detail.get("locale_preferred_encoding"),
                "locale_would_have_failed": (enc_detail.get("locale_control") or {}).get(
                    "would_have_failed"),
                "prefix_call_shape": enc_detail.get("prefix_call_shape"),
            },
            "notes": "`execute_shell_cmd` called `subprocess.run(..., text=True)` with no "
                     "`encoding`, so CPython decoded shell output with the locale codec "
                     "(cp936 here). A byte that is invalid in that codec makes the reader "
                     "thread raise, `stdout` comes back `None`, and the old `out += ...` "
                     "raised TypeError — aborting the loop, discarding the trajectory and "
                     "scoring the run as an ordinary task failure. On the frozen round-12 "
                     "live artifact that hit 3/75 `raw_shell` and 2/75 `raw_shell_coached` "
                     "rows and 0/75 `verseshell_aci` rows; excluding them moves D−A from "
                     "0.120 to 0.083. `mechanism_control` is host-independent (it proves the "
                     "fixture bytes are undecodable in cp936); `utf8_observation_roundtrip` "
                     "drives the real function with a real `type` of a real UTF-8 file",
        })
    else:
        claims.append({
            "id": "C31", "claim": THRESHOLDS["C31"]["desc"],
            **token_caliber_fields("C31"),
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "harness_encoding_contract", "measured_at": now,
            "command": "python tools/harness_encoding_contract.py "
                       "--out eval/harness_encoding_contract.json",
            "source": ["tools/harness_encoding_contract.py"],
            "notes": f"missing evidence artifact: {enc_path}",
        })

    # ── C27: the observation-token proxy must be calibrated, not assumed ──
    cal_path = artifact_path('eval/token_proxy_calibration.json')
    if cal_path.exists():
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        verdict = cal.get("verdict", {})
        tok = cal.get("tokenizer", {})
        overall = (cal.get("aggregate") or {}).get("overall") or {}
        checks = {
            # A real tokenizer, not the byte-class approximation.
            "tokenizer_is_real": not tok.get("is_approximation", True),
            "tokenizer_resolved": bool(tok.get("primary")),
            # The sanity anchor must be inside its expected range.
            "anchor_within_expected_range":
                bool((verdict.get("anchor_check") or {}).get("within_expected_range")),
            # All four questions must be answered explicitly.
            "states_error_direction": bool(verdict.get("a_error_direction")),
            "states_error_magnitude": bool(verdict.get("b_error_magnitude")),
            "states_upper_bound_verdict": bool(verdict.get("c_upper_bound")),
            "documents_cache_hazard": bool(verdict.get("d_cache_hazard_and_neutralisation")),
            "has_samples": bool(overall.get("n_scored")),
        }
        value = 1.0 if all(checks.values()) else 0.0
        claims.append({
            "id": "C27", "claim": THRESHOLDS["C27"]["desc"],
            **token_caliber_fields("C27"),
            "threshold": "== 1.00", "value": value, "pass": value == 1.0,
            "mode": "tokenizer_calibration", "sample_size": overall.get("n_scored"),
            "measured_at": cal.get("generated_at"),
            "command": "python tools/token_proxy_calibration.py --out eval/token_proxy_calibration.json",
            "source": ["tools/token_proxy_calibration.py",
                       "bench/aci/runners/live_agent_loop.py",
                       "bench/aci/results/latest_live.json",
                       "eval/token_proxy_calibration.json"],
            "detail": {
                "checks": checks,
                "tokenizer": tok.get("primary"),
                "tokenizer_tier": tok.get("tier"),
                "is_approximation": tok.get("is_approximation"),
                "mean_real_over_proxy": (overall.get("real_over_proxy_ratio") or {}).get("mean"),
                "median_real_over_proxy": (overall.get("real_over_proxy_ratio") or {}).get("median"),
                "mean_relative_error_proxy_vs_real":
                    (overall.get("relative_error_proxy_vs_real") or {}).get("mean"),
                "chars_per_real_token": overall.get("chars_per_real_token"),
                "proxy_undercounts_samples": overall.get("proxy_undercounts_samples"),
                "error_direction": verdict.get("a_error_direction"),
                "upper_bound_verdict": verdict.get("c_upper_bound"),
                "anchor": verdict.get("anchor_check"),
            },
            "notes": "every published observation-token number (C13-C17, C19, C20) is computed with "
                     "`estimate_tokens(text) = max(1, len(text)//4)`, which was never validated. This "
                     "calibrates it against a real BPE tokenizer (cl100k_base) on the observation texts "
                     "replayed from the stored live run, and gates that the calibration EXISTS and is "
                     "honest (real tokenizer, anchor in range, all four questions answered, cache hazard "
                     "documented), not that the proxy is accurate. The stable conclusions are qualitative: "
                     "the proxy is NEITHER an upper bound NOR a lower bound (it under-counts most of these "
                     "shapes and over-counts a minority), the direction is shape-dependent, there is NO "
                     "single correction factor that turns proxy tokens into real tokens, and the headline "
                     "magnitude is NOT reproducible across rounds — or even across replays of the same "
                     "sample. For the current numbers read THIS artifact's own `detail.checks`, "
                     "`detail.mean_real_over_proxy` / `detail.median_real_over_proxy`, "
                     "`detail.proxy_undercounts_samples` and its `aggregate` block; do not lift a figure "
                     "out of this note as if it were the claim's constant. Two number sets exist and "
                     "neither is a constant: (a) the in-place eval/token_proxy_calibration.json was "
                     "generated BEFORE the P2-5 full-text measurement fix (its sample aggregate mixed a "
                     "truncated text copy with full-text chars/char_class/sha256 for 6 of 60 samples), so "
                     "its headline is superseded; (b) an offline re-derivation after the fix reads mean "
                     "real/proxy ~1.263 and median ~1.229 with 53/60 under-count, 6/60 over-count and 1 "
                     "equal at n=60, and a second replay of the same sample gave ~1.262 — the replay is "
                     "not bit-deterministic, so the figure moves run to run. The endpoint "
                     "`usage.prompt_tokens` cross-check section of the artifact is a PREVIOUS round's "
                     "measurement and must be re-run by the test owner at L7; it is unusable as ground "
                     "truth until then because it is content-cached and inflated (~+170 on many payloads), "
                     "which the tool neutralises with unique nonces and a min-over-draws estimator. Quote "
                     "every observation-token number as proxy-caliber (C13-C17, C19, C20) and never as "
                     "'the proxy under-counts by N%' without the n, the interval and the artifact "
                     "revision it came from",
        })
    else:
        claims.append({
            "id": "C27", "claim": THRESHOLDS["C27"]["desc"],
            **token_caliber_fields("C27"),
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "tokenizer_calibration", "measured_at": now,
            "command": "python tools/token_proxy_calibration.py --out eval/token_proxy_calibration.json",
            "source": ["tools/token_proxy_calibration.py"],
            "notes": f"missing evidence artifact: {cal_path}",
        })

    # ── C28: no affirmative claim may rest on a sample too small to carry it ──
    acc_path = artifact_path('eval/acceptance_power.json')
    if acc_path.exists():
        acc = json.loads(acc_path.read_text(encoding="utf-8"))
        prereg = acc.get("preregistered_parameters") or {}
        verdicts = acc.get("verdicts") or {}
        required_items = [
            "success_paired_can_claim_MDE_0.15",
            "success_paired_coached_can_claim_MDE_0.15",
            "token_ratio_level1_D_cheaper",
            "token_ratio_level2_saves_15pct",
            "token_ratio_frozen_0.60",
            "tool_ratio_level1_D_fewer_calls",
            "token_ratio_coached_level1_D_cheaper",
            "cost_per_success_D_cheaper",
            "cost_per_success_coached_D_cheaper",
            "cross_shell_all_ops_strictly_faster",
            "cross_shell_all_ops_2x",
        ]
        ratio_items = (
            "token_ratio_level1_D_cheaper",
            "token_ratio_level2_saves_15pct",
            "token_ratio_frozen_0.60",
            "tool_ratio_level1_D_fewer_calls",
            "token_ratio_coached_level1_D_cheaper",
        )
        live_blocks = [b for b in (acc.get("live"), acc.get("live_coached")) if b]
        checks: dict[str, bool] = {
            "preregistration_recorded": bool(prereg),
            "all_items_present": all(k in verdicts for k in required_items),
            # Every item must carry an explicit boolean, so "unknown" can never be
            # read as "fine".
            "every_item_has_explicit_claimable": all(
                isinstance(verdicts.get(k, {}).get("claimable"), bool) for k in required_items),
            # Self-consistency: a product gap may be asserted only when the WHOLE
            # interval is past the cap; `gap_type` must agree with that and with
            # `claimable`.
            "impossible_flag_consistent": _impossible_flag_consistent(verdicts),
            # Every ratio verdict must be decided by the TASK-clustered interval.
            "ratio_verdicts_are_task_clustered": all(
                (verdicts.get(k) or {}).get("unit") == "task" for k in ratio_items),
            # And the real-tokenizer reading must be published next to the proxy.
            "real_tokenizer_published": bool(live_blocks) and all(
                (block.get(k) or {}).get("ci95")
                for block in live_blocks
                for k in ("usage_token_ratio", "prompt_token_ratio", "completion_token_ratio")),
        }
        unclaimable_affirmative = [
            k for k in AFFIRMATIVE_ACCEPTANCE
            if not (verdicts.get(k, {}).get("claimable") is True)
        ]
        checks["affirmative_items_are_claimable"] = not unclaimable_affirmative
        value = 1.0 if all(checks.values()) else 0.0
        live = acc.get("live") or {}
        claims.append({
            "id": "C28", "claim": THRESHOLDS["C28"]["desc"],
            **token_caliber_fields("C28"),
            "threshold": "== 1.00", "value": value, "pass": value == 1.0,
            "mode": "power_and_precision_audit",
            "sample_size": live.get("n_pairs"),
            "measured_at": acc.get("generated_at"),
            "command": "python tools/acceptance_power.py --out eval/acceptance_power.json",
            "source": ["tools/acceptance_power.py", "docs/acceptance-criteria.md",
                       "bench/aci/results/latest_live.json",
                       "eval/cross_shell.json", "eval/acceptance_power.json"],
            "detail": {
                "checks": checks,
                "preregistered_parameters": prereg,
                "affirmative_items": AFFIRMATIVE_ACCEPTANCE,
                "unclaimable_affirmative": unclaimable_affirmative,
                "verdicts": {
                    k: {"claimable": (verdicts.get(k) or {}).get("claimable"),
                        "gap_type": (verdicts.get(k) or {}).get("gap_type"),
                        "unit": (verdicts.get(k) or {}).get("unit"),
                        "point": (verdicts.get(k) or {}).get("point"),
                        "ci95": [(verdicts.get(k) or {}).get("ci95_lower"),
                                 (verdicts.get(k) or {}).get("ci95_upper")],
                        "reason": (verdicts.get(k) or {}).get("reason")}
                    for k in required_items
                },
                "ratio_verdicts_task_clustered":
                    checks.get("ratio_verdicts_are_task_clustered"),
                "real_tokenizer_published": checks.get("real_tokenizer_published"),
                "real_tokenizer": {
                    block.get("baseline_condition", f"live_{i}"): {
                        k: {"point": (block.get(k) or {}).get("point"),
                            "ci95": (block.get(k) or {}).get("ci95"),
                            "ci95_row": (block.get(k) or {}).get("ci95_row"),
                            "unit": (block.get(k) or {}).get("unit")}
                        for k in ("usage_token_ratio", "prompt_token_ratio",
                                  "completion_token_ratio")
                    }
                    for i, block in enumerate(live_blocks)
                },
                "n_pairs": live.get("n_pairs"),
                "success_detectable_mde_at_current_n":
                    (live.get("success") or {}).get("observed_mde_at_current_n"),
                "token_ratio": live.get("token_ratio"),
                "tool_ratio": live.get("tool_ratio"),
                "cost_per_success": live.get("cost_per_success"),
            },
            "notes": "This gates the PRE-REGISTRATION contract in docs/acceptance-criteria.md: every "
                     "affirmative claim must have an interval that clears its threshold, and a "
                     "product gap may be asserted only when the WHOLE CI95 lies on the wrong side "
                     "of the cap the claim needs. It deliberately does NOT fail because the "
                     "token-saving ladder is unclaimable today — the honest state is that those claims "
                     "cannot be made yet, and the gate records exactly how many pairs each needs. It "
                     "FAILS only when an item this repo does assert (the cross-shell claims) loses its "
                     "claimable verdict, when a verdict has no explicit boolean, or when the "
                     "impossible-by-sample-size flag / gap_type disagrees with the interval",
        })
    else:
        claims.append({
            "id": "C28", "claim": THRESHOLDS["C28"]["desc"],
            **token_caliber_fields("C28"),
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "power_and_precision_audit", "measured_at": now,
            "command": "python tools/acceptance_power.py --out eval/acceptance_power.json",
            "source": ["tools/acceptance_power.py", "docs/acceptance-criteria.md"],
            "notes": f"missing evidence artifact: {acc_path}",
        })

    # ── C29: nothing enters the capability set without passing the gate ──
    adm_path = artifact_path('eval/task_admissibility.json')
    if adm_path.exists():
        adm = json.loads(adm_path.read_text(encoding="utf-8"))
        summary = adm.get("summary") or {}
        candidates = adm.get("candidates") or []
        admissible_ids = {c.get("task_id") or c.get("candidate")
                          for c in candidates if c.get("admissible")}
        rejected_ids = {c.get("task_id") or c.get("candidate")
                        for c in candidates if not c.get("admissible")}
        # What is actually shipped as a task, and which of those claim to be
        # capability tasks (only those may feed the capability/token claims).
        shipped_capability: list[str] = []
        for task_file in sorted((ROOT / "bench/aci/tasks").glob("*.json")):
            try:
                t = json.loads(task_file.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                continue
            if t.get("kind") == "capability":
                shipped_capability.append(t.get("id") or task_file.stem)
        checks = {
            "artifact_has_protocol": bool(adm.get("protocol")),
            "counts_consistent": (
                summary.get("candidates") == len(candidates)
                and (summary.get("admissible", 0) + summary.get("rejected", 0))
                == summary.get("candidates", -1)
            ),
            # The promotion guard: a rejected candidate must never appear in the
            # shipped task set.
            "no_rejected_candidate_promoted": not (rejected_ids & set(shipped_capability)),
            # Every shipped capability task must have passed the gate.
            "shipped_capability_tasks_admissible": set(shipped_capability) <= admissible_ids,
            # An admissible capability task must carry anti-gaming evidence.
            "admissible_capability_has_antigaming": all(
                (c.get("verifier_artifacts") and c.get("checks", {})
                 .get("A4a_verifier_tamper_rejected"))
                or c.get("llm_shortcuts_rejected", 0) >= 1
                for c in candidates
                if c.get("admissible") and c.get("kind") == "capability"
            ),
        }
        value = 1.0 if all(checks.values()) else 0.0
        claims.append({
            "id": "C29", "claim": THRESHOLDS["C29"]["desc"],
            "threshold": "== 1.00", "value": value, "pass": value == 1.0,
            "mode": "task_admissibility_gate",
            "sample_size": summary.get("candidates"),
            "measured_at": adm.get("generated_at"),
            "command": "python tools/task_admissibility.py --out eval/task_admissibility.json",
            "source": ["tools/task_admissibility.py", "tools/task_generate.py",
                       "tools/run_task_plan.py",
                       "docs/task-generation-protocol.md", "bench/aci/candidates/**/*",
                       "bench/aci/runners/live_agent_loop.py", "eval/task_admissibility.json"],
            "detail": {
                "checks": checks,
                "summary": summary,
                "shipped_capability_tasks": shipped_capability,
                "admissible_ids": sorted(i for i in admissible_ids if i),
                "rejected_ids": sorted(i for i in rejected_ids if i),
            },
            "notes": "guards the PROMOTION path, not the current count: it fails when a rejected "
                     "candidate appears in bench/aci/tasks/, when a shipped task declaring "
                     "kind=capability was never admitted, when the summary disagrees with the rows, "
                     "or when an admitted capability task carries no anti-gaming evidence. It does "
                     "NOT fail because the admissible-capability count is still small — that is the "
                     "honest current state and the acceptance criteria say so. The gate's sharpest "
                     "check is A4a: replace every test/verifier artifact in the fixture with a "
                     "trivially-passing stub and require the predicate to still FAIL. The LLM-produced "
                     "'shortcuts' are deliberately informational, because a passing one is ambiguous "
                     "(gameable predicate vs a model that declined to game and solved it properly). "
                     "A8 makes `tier=large` real: it runs the predicate's own command on the pristine "
                     "state, unreduced, and requires >=1000 observation tokens — one generated large "
                     "candidate measured 231 tokens because it added a file argument to pytest, so "
                     "'large' has to be a gate rather than a request",
        })
    else:
        claims.append({
            "id": "C29", "claim": THRESHOLDS["C29"]["desc"],
            "threshold": "== 1.00", "value": None, "pass": False,
            "mode": "task_admissibility_gate", "measured_at": now,
            "command": "python tools/task_admissibility.py --out eval/task_admissibility.json",
            "source": ["tools/task_admissibility.py", "docs/task-generation-protocol.md"],
            "notes": f"missing evidence artifact: {adm_path}",
        })

    # ── C35: the paired control arm must MATCH the with arm in composition ──
    # C12 fingerprints each artifact against the CODE, so an artifact built on a stale
    # INPUT still reads as fresh. That is exactly how `live_ab_without_read_files.json`
    # sat at 75 rows / seed 42 / a pre-cp936-crash harness while the with arm was 225
    # rows / 3 seeds, with SEVEN derived tools reading it and reporting themselves fresh
    # (TF-0119). C12 cannot catch that, because the without arm is deliberately not in
    # its fingerprinted artifact list. This check compares the control against the arm it
    # is paired with, which is the property every two-arm claim actually needs.
    with_arm_path = artifact_path('bench/aci/results/latest_live.json')
    without_arm_path = artifact_path('bench/aci/results/live_ab_without_read_files.json')
    problems35: list[str] = []
    detail35: dict = {}

    if not with_arm_path.exists() or not without_arm_path.exists():
        missing = [p.name for p in (with_arm_path, without_arm_path) if not p.exists()]
        problems35.append("missing arm artifact(s): " + ", ".join(missing))
    else:
        w35 = live_run_composition(with_arm_path)
        wo35 = live_run_composition(without_arm_path)
        detail35 = {"with_arm": w35, "without_arm": wo35}
        if w35["seeds"] != wo35["seeds"]:
            problems35.append(f"seed sets differ: with={w35['seeds']} without={wo35['seeds']}")
        if w35["tasks"] != wo35["tasks"]:
            only_w = sorted(set(w35["tasks"]) - set(wo35["tasks"]))
            only_wo = sorted(set(wo35["tasks"]) - set(w35["tasks"]))
            problems35.append(f"task sets differ (with-only={only_w[:5]}, without-only={only_wo[:5]})")
        if w35["rows"] != wo35["rows"]:
            problems35.append(f"row counts differ: with={w35['rows']} without={wo35['rows']}")
        if w35["git_rev"] != wo35["git_rev"]:
            problems35.append(f"revisions differ: with={w35['git_rev']} without={wo35['git_rev']}")
        if w35["task_set_version"] != wo35["task_set_version"]:
            problems35.append("task-set versions differ: "
                              f"with={w35['task_set_version']} without={wo35['task_set_version']}")
        if w35["api_error_rows"] or wo35["api_error_rows"]:
            problems35.append("api_error rows present: "
                              f"with={w35['api_error_rows']} without={wo35['api_error_rows']}")
        for arm, composition in detail35.items():
            if composition["partial"]:
                problems35.append(f"{arm} is partial ({composition['endpoint_failure_rows']} endpoint failures)")
            if composition["row_class_mismatches"]:
                problems35.append(f"{arm} has incorrect or missing row_class labels")
            if composition['affirmative_collection_verdicts']:
                problems35.append(f"{arm} publishes formal acceptance from collection-only "
                                  f"diagnostics: {composition['affirmative_collection_verdicts']}")
    claims.append({
        "id": "C35", "claim": THRESHOLDS["C35"]["desc"],
        "threshold": "== 1.00",
        "value": 0.0 if problems35 else 1.0,
        "pass": not problems35, "mode": "paired_arm_composition",
        "measured_at": (detail35.get("with_arm") or {}).get("generated_at") or now,
        "command": "python tools/live_round.py --tag <tag> --arms with,without",
        "source": ["bench/aci/results/latest_live.json",
                   "bench/aci/results/live_ab_without_read_files.json",
                   "tools/live_round.py", "bench/aci/runners/merge_live_runs.py",
                   "tools/refresh_live_artifacts.py"],
        "detail": detail35,
        "notes": ("the C2 ablation is a PAIRED control: every two-arm number (read_usage_audit, "
                  "exec_token_breakdown, step_composition, live_uncertainty, acceptance_power, ...) "
                  "silently assumes the two arms cover the same (task, seed) grid on the same "
                  "revision. C12 cannot see this because the control arm is intentionally outside "
                  "its fingerprinted artifact list, so the check lives here. "
                  + (" | ".join(problems35) if problems35 else "compositions match")),
    })

    # ── C36: hypothesis families + multiplicity correction (tree-farm TF-0113) ──
    # Eleven verdicts used to be published at alpha=0.05 EACH with no correction, which
    # puts the family-wise error rate at 1 - 0.95**11 = 43.1% — a claimable item sitting
    # on the boundary cannot survive that. The grouping is pre-registered in
    # docs/acceptance-criteria.md §0.7 and implemented in `VERDICT_FAMILIES` in
    # tools/acceptance_power.py. The gate's job is narrow and checkable: refuse a verdict
    # published without its family, refuse a claimable verdict inside an UNCORRECTED
    # family, and refuse a verdict that is claimable while failing its own Holm level.
    problems36: list[str] = []
    detail36: dict = {}
    if not ap_path.exists():
        problems36.append(f"missing {ap_path}")
    else:
        apd36 = json.loads(ap_path.read_text(encoding="utf-8"))
        mult = apd36.get("multiplicity") or {}
        verdicts36 = apd36.get("verdicts") or {}
        detail36["method"] = mult.get("method")
        detail36["alpha"] = mult.get("alpha")
        detail36["preregistered_in"] = mult.get("preregistered_in")
        if not mult:
            problems36.append("acceptance_power.json has no multiplicity block")
        else:
            if not mult.get("preregistered_in"):
                problems36.append("multiplicity block does not name where the families "
                                  "are pre-registered")
            fams36 = mult.get("families") or {}
            if not fams36:
                problems36.append("multiplicity block declares no families")
            for fam, info in fams36.items():
                if fam != "exploratory" and info.get("corrected") and not info.get("holm_alpha"):
                    problems36.append(f"family {fam!r} is marked corrected but carries no "
                                      f"adjusted level")
        for key, v36 in verdicts36.items():
            if not isinstance(v36, dict):
                continue
            fam36 = v36.get("family")
            if not fam36:
                problems36.append(f"{key}: no hypothesis family declared")
                continue
            if fam36 == "exploratory" and v36.get("claimable"):
                problems36.append(f"{key}: an EXPLORATORY verdict is published as claimable")
            if v36.get("claimable") and v36.get("passes_holm") is False:
                problems36.append(f"{key}: claimable while failing its own Holm level")
            if (v36.get("claimable") and not key.startswith("success_paired")
                    and v36.get("passes_holm") is not True):
                problems36.append(f"{key}: effect claim lacks a passing multiplicity correction")
        demoted36 = set(mult.get("demoted_by_multiplicity") or [])
        still36 = sorted(k for k in demoted36 if (verdicts36.get(k) or {}).get("claimable"))
        if still36:
            problems36.append("demoted by multiplicity yet still claimable: " + ", ".join(still36))
        detail36["families"] = {
            f: {"m": i.get("m"), "m_scored": i.get("m_scored"),
                "corrected": i.get("corrected")}
            for f, i in (mult.get("families") or {}).items()}
        detail36["demoted_by_multiplicity"] = sorted(demoted36)
        detail36["claimable_verdicts"] = sorted(
            k for k, v36 in verdicts36.items()
            if isinstance(v36, dict) and v36.get("claimable"))
    claims.append({
        "id": "C36", "claim": THRESHOLDS["C36"]["desc"],
        "threshold": "== 1.00",
        "value": 0.0 if problems36 else 1.0,
        "pass": not problems36, "mode": "hypothesis_family_multiplicity",
        "measured_at": now,
        "command": "python tools/acceptance_power.py --out eval/acceptance_power.json",
        "source": ["tools/acceptance_power.py", "eval/acceptance_power.json",
                   "docs/acceptance-criteria.md"],
        "detail": detail36,
        "notes": ("families are split by DATA SOURCE, not by convenience: the live-model "
                  "ladder and the local cross-shell benchmark do not share a correction. "
                  "Only interval-based verdicts can be Holm-corrected, because only they "
                  "carry a (point, CI) triple to recover an approximate p-value from; the "
                  "success verdicts are design/power verdicts and keep `passes_holm: null`, "
                  "which is reported rather than hidden. "
                  + (" | ".join(problems36) if problems36 else "all families declared and corrected")),
    })

    # ── C37: the headline statistics must reproduce along a second code path ──
    # The external audit's E7 (only one budget measured), E11 (wrong resampling unit) and
    # E12 (operator precedence inflating a margin 6x) were ALL bugs in the analysis code,
    # and every one was found by a human reading numbers — no test caught them. In a
    # project whose conclusions are decided by a few dozen lines of statistics, "the code
    # that computes the answer agrees with an independent implementation" has to be a
    # checked property, not a hope. `tools/statistics_crosscheck.py` recomputes the
    # published quantities from the raw rows with textbook closed forms written out
    # locally and an independently seeded bootstrap, then compares item by item:
    # closed-form items must agree exactly to published rounding, resampled items within
    # a Monte-Carlo tolerance AND on the same side of 1.0.
    xcheck_path = artifact_path('eval/statistics_crosscheck.json')
    problems37: list[str] = []
    detail37: dict = {}
    if not xcheck_path.exists():
        problems37.append(f"missing {xcheck_path}")
    else:
        xc = json.loads(xcheck_path.read_text(encoding="utf-8"))
        items37 = xc.get("items") or []
        detail37["n_items"] = xc.get("n_items")
        detail37["n_failed"] = xc.get("n_failed")
        if not items37:
            problems37.append("statistics_crosscheck.json carries no comparison items")
        if xc.get("n_failed"):
            problems37.append(f"{xc['n_failed']} item(s) disagree with the published values")
        if (xc.get("n_items") or 0) < 20:
            # A cross-check that compares almost nothing would pass vacuously.
            problems37.append(f"only {xc.get('n_items')} items compared; expected the full set")
        kinds = {i.get("kind") for i in items37}
        for required in ("closed_form", "resampled"):
            if required not in kinds:
                problems37.append(f"no {required} item was compared")
        bad = [i.get("item") for i in items37 if not i.get("agree")]
        detail37["disagreeing_items"] = bad
        detail37["closed_form_tolerance"] = (xc.get("method") or {}).get("tolerances", {}).get("closed_form")
        detail37["resampled_tolerance"] = (xc.get("method") or {}).get("tolerances", {}).get("resampled")
    claims.append({
        "id": "C37", "claim": THRESHOLDS["C37"]["desc"],
        "threshold": "== 1.00",
        "value": 0.0 if problems37 else 1.0,
        "pass": not problems37, "mode": "independent_reimplementation",
        "measured_at": now,
        "command": "python tools/statistics_crosscheck.py --out eval/statistics_crosscheck.json",
        "source": ["tools/statistics_crosscheck.py", "eval/statistics_crosscheck.json",
                   "bench/aci/results/latest_live.json", "eval/live_uncertainty.json",
                   "eval/acceptance_power.json"],
        "detail": detail37,
        "notes": ("a second implementation is not proof of correctness, but it does catch the "
                  "class of bug the audit actually found (wrong resampling unit, wrong "
                  "operator precedence, a forgotten budget) because those are coding errors, "
                  "not statistical subtleties. Closed-form quantities are compared exactly; "
                  "bootstrapped ones within a Monte-Carlo tolerance and on the same side of "
                  "1.0, since a different seed cannot reproduce bounds exactly and 'same "
                  "side' alone would hide a magnitude bug. "
                  + (" | ".join(problems37) if problems37 else "all compared items agree")),
    })

    # ── C12: stored evidence must still describe the current code ──
    freshness = freshness_entries(selected)
    stale = [f["artifact"] for f in freshness if not f["pass"]]
    claims.append({
        "id": "C12", "claim": THRESHOLDS["C12"]["desc"],
        "threshold": "all artifacts fresh", "value": 1.0 if not stale else 0.0,
        "pass": not stale, "mode": "content_fingerprint",
        "sample_size": len(freshness), "measured_at": now,
        "command": "python tools/claim_gate.py",
        "source": EVIDENCE_ARTIFACTS + ["tools/claim_gate.py"],
        "detail": {"artifacts": freshness, "stale": stale},
        "notes": "each stored measurement records the sha256 fingerprint of the surface it measured; "
                 "if the code changed since, the evidence is stale and must be regenerated "
                 "(run_suite / jev_obs_judge / cross_shell_bench)",
    })

    stability = apply_stability_guard(claims, source_before, source_snapshot(ROOT),
                                      input_before, file_hashes(selected), generated)
    inventory = build_inventory(claims, TOKEN_CALIBER, selected, freshness, stability, generated, ROOT)
    require_current_evidence(claims, inventory)
    gated = [c for c in claims if c["pass"] is not None]
    all_pass = all(c["pass"] for c in gated)

    # ── evidence.json: every external number = one claim entry here ──
    evidence = {
        "schema": "verseshell.claim-evidence/v1",
        "generated_at": now,
        "generator": "tools/claim_gate.py",
        "metrics_source": metrics_source,
        "metrics_regenerated": metrics_regenerated,
        "bench_meta": bench_meta,
        "threshold_source": "docs/claims-and-evidence.md",
        # Per-claim token/usage/cost caliber. Gated claims also carry
        # `token_caliber` / `token_caliber_note` inline; this registry is the
        # machine-readable label for the non-gated claims (C13/C15/C17/C19/C20/C21),
        # which have no entry in THRESHOLDS.
        "token_caliber_registry": TOKEN_CALIBER,
        "all_pass": all_pass,
        "claims": claims,
        "claim_inventory": inventory,
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")

    args.evidence.with_suffix(".claims.md").write_text(markdown(inventory), encoding="utf-8", newline="\n")
    print(f"claim_gate: {sum(1 for c in gated if c['pass'])}/{len(gated)} gated claims pass")
    for c in claims:
        if c["pass"] is None:
            status = "N/A"
        elif c.get("stale"):
            status = "STALE"
        elif c["pass"]:
            status = "PASS"
        else:
            status = "FAIL"
        val = c["value"] if c["value"] is not None else "-"
        print(f"  [{status}] {c['id']} {c['claim']}: value={val} threshold={c['threshold']}")
        if c["id"] == "C35" and not c["pass"]:
            for arm, detail in c.get("detail", {}).items():
                if detail.get("partial") or detail.get("row_class_mismatches"):
                    print(f"    {arm}: partial={detail['partial']} "
                          f"endpoint_failure_rows={detail['endpoint_failure_rows']}")
                    for row in detail["affected_rows"]:
                        print("      endpoint_failure " + json.dumps(row, ensure_ascii=False))
                    for mismatch in detail["row_class_mismatches"]:
                        print("      row_class mismatch " + json.dumps(mismatch, ensure_ascii=False))
                    print("      affected comparisons: " + ", ".join(detail["affected_comparisons"]))
    print(f"evidence written: {args.evidence}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
