#!/usr/bin/env python3
"""acceptance_power: refuse to let a claim be made on a sample too small to support it.

The claim matrix says WHAT is asserted; this tool says whether the stored sample
can carry the assertion at all. It exists because the failure mode that matters is
not a wrong number — it is a *vacuous* one: a point estimate quoted with no
interval, from a sample that could never have detected the effect being claimed.

Pre-registered design (do not tune after seeing the data; edit
`docs/acceptance-criteria.md` and this table together):

  success_paired        paired McNemar, MDE = 0.15 absolute, alpha=0.05 two-sided,
                        power=0.80. n is derived from the pilot discordance rate.
  token_ratio_level1    "D is cheaper"  -> require bootstrap CI95 UPPER < 1.00
  token_ratio_level2    "D saves >=15%" -> require point <= 0.85 AND CI95 upper <= 0.90
  token_ratio_frozen    "meets <=0.60"  -> require point <= 0.60 AND CI95 upper <= 0.70
  tool_ratio_level1     same ladder on the tool-call ratio
  cost_per_success      OBSERVATION-PROXY tokens per SUCCESSFUL task, D/A (the name
                        contains "cost" but the unit is tokens, not currency):
                        point <= 0.80 AND CI95 upper < 1.00,
                        AND success non-inferiority (lower bound of D-A >= -0.10)
  cross_shell_strict    every operation's ratio of medians: CI95 upper < 1.00
  cross_shell_2x        every operation's ratio of medians: CI95 upper < 0.50

For a ratio claim the required n is precision-based, not power-based: shrink the
interval until its upper bound clears the threshold.

A "product gap" — the case where no amount of extra data can rescue the claim — is
asserted ONLY when the whole CI95 sits on the wrong side of the cap the claim needs
(`point_cap` when the claim has one, otherwise `threshold`). A point estimate moves
with the sample, so `point > threshold` on its own is "no evidence", not a product
gap. `impossible_by_sample_size` is therefore derived from the interval, and
`gap_type` records which of the three states applies: `none` / `data_gap` /
`product_gap`. That distinction is the whole point of this tool.

Usage:
    python tools/acceptance_power.py --out eval/acceptance_power.json
"""
from __future__ import annotations
from live_uncertainty import reported_usage

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from live_uncertainty import ratio_bootstrap, row_policy, cost_per_success_interval  # noqa: E402
from report_inputs import select_prompt_variant

EVIDENCE_GLOBS = [
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "eval/cross_shell.json",
    "eval/live_uncertainty.json",
    "tools/acceptance_power.py",
    "tools/live_uncertainty.py",
    "tools/report_inputs.py",
]

Z_A = 1.959963984540054  # alpha = 0.05, two-sided
Z_B = 0.8416212335729143  # power = 0.80
BOOTSTRAP = 20000
BOOTSTRAP_SEED = 42
# Family-wise level for the confirmatory families (TF-0113, docs/acceptance-criteria.md
# §0.7). Per-item level, alpha=0.05 two-sided, was never a family-wise guarantee: 11
# uncorrected items put the family error rate at 43.1%.
MULTIPLICITY_ALPHA = 0.05

# Pre-registered minimum detectable effects / precision targets.
PREREG = {
    "success_mde_absolute": 0.15,
    "token_ratio_level1_upper": 1.00,
    "token_ratio_level2_point": 0.85,
    "token_ratio_level2_upper": 0.90,
    "token_ratio_frozen_point": 0.60,
    "token_ratio_frozen_upper": 0.70,
    "tool_ratio_level1_upper": 1.00,
    # caliber of the cost_per_success ladder: OBSERVATION-PROXY tokens per
    # successful task (max(1, len(text)//4) from the live rows' observation_tokens,
    # divided by the success count). The key names contain "cost" but the unit is
    # tokens, not currency, and this is not a billed endpoint-usage measurement.
    "cost_per_success_point": 0.80,
    "cost_per_success_upper": 1.00,
    "success_noninferiority_margin": 0.10,
    "cross_shell_strict_upper": 1.00,
    "cross_shell_2x_upper": 0.50,
}


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ── power / precision maths ────────────────────────────────────────────────────

def mcnemar_n(delta: float, psi: float, *, z_a: float = Z_A, z_b: float = Z_B) -> int | None:
    """Pairs needed for a paired binary outcome (McNemar, normal approximation).

    delta = |p_D - p_A|, psi = P(discordant). Returns None when the parameters are
    outside the formula's domain rather than inventing a number.
    """
    if delta <= 0 or psi <= 0 or psi < delta * delta:
        return None
    return int(math.ceil((z_a * math.sqrt(psi) + z_b * math.sqrt(psi - delta * delta)) ** 2
                          / (delta * delta)))


def mcnemar_observed_mde(n: int, psi: float, *, z_a: float = Z_A, z_b: float = Z_B) -> float | None:
    """Invert mcnemar_n: the smallest |delta| this n could detect at 80% power."""
    if n <= 0 or psi <= 0:
        return None
    return (z_a * math.sqrt(psi) + z_b * math.sqrt(psi)) / math.sqrt(n)


def ratio_verdict(point: float | None, lower: float | None, upper: float | None, n: int,
                  threshold: float, *, point_cap: float | None = None,
                  unit: str | None = None) -> dict:
    """Can this sample claim `ratio <= threshold`? Precision-based.

    `claimable` is decided by the interval, never by the point estimate alone.

    A product gap is asserted only when the WHOLE interval lies on the wrong side of
    the cap the claim needs: then no larger sample can bring the claim into reach. A
    point estimate past the cap whose interval still reaches below it is a data gap
    (`gap_type == "data_gap"`) — the estimate has to move, and more data can move it.
    """
    if point is None or lower is None or upper is None or n <= 0:
        return {"claimable": False, "reason": "no interval"}
    cap = point_cap if point_cap is not None else threshold
    out: dict = {
        "n_pairs": n,
        "point": round(point, 4),
        "ci95_lower": round(lower, 4),
        "ci95_upper": round(upper, 4),
        "threshold": threshold,
        # Which resampling unit the interval came from. C28 fails the gate when this is
        # not "task", because a row-level interval is systematically narrower and
        # changed an L2 verdict on the round-12 data.
        "unit": unit,
    }
    if point_cap is not None:
        out["point_cap"] = point_cap
        out["point_cap_met"] = point <= point_cap
    # The pre-registered claim needs BOTH the point cap and the interval bound, so
    # `claimable` must honour the cap too — an interval that clears the threshold is
    # not enough if the observed point sits above the cap the claim names.
    point_cap_ok = point_cap is None or point <= point_cap
    if upper < threshold and point_cap_ok:
        out.update({
            "claimable": True,
            "gap_type": "none",
            "impossible_by_sample_size": False,
            "reason": "interval upper bound clears the threshold",
        })
        return out
    if lower > cap:
        out.update({
            "claimable": False,
            "gap_type": "product_gap",
            "impossible_by_sample_size": True,
            "reason": (f"the whole CI95 [{lower:.4f}, {upper:.4f}] is above the cap {cap}: "
                       f"more samples cannot rescue this (product gap, not data gap)"),
        })
        return out
    # Not claimable, but the interval still reaches into the claimable region, so the
    # estimate can move: this is "no evidence", not a proven product gap.
    out.update({
        "claimable": False,
        "gap_type": "data_gap",
        "impossible_by_sample_size": False,
    })
    if not point_cap_ok:
        out.update({
            "n_required": None,
            "n_shortfall": None,
            "reason": (f"point estimate {point:.4f} is above the claim's point cap {point_cap}, "
                       f"but CI95 still reaches below it ({lower:.4f} < {point_cap}): the "
                       f"estimate has to move, so this is no evidence yet, not a product gap"),
        })
        return out
    margin_now = upper - point
    margin_need = threshold - point
    if margin_need <= 0:
        out.update({
            "n_required": None,
            "n_shortfall": None,
            "reason": (f"point estimate {point:.4f} is past the threshold {threshold}, but CI95 "
                       f"still reaches below it ({lower:.4f} < {threshold}): narrowing the "
                       f"interval alone cannot clear the threshold, so this is no evidence, "
                       f"not a product gap"),
        })
        return out
    n_required = int(math.ceil(n * (margin_now / margin_need) ** 2))
    out.update({
        "margin_at_current_n": round(margin_now, 4),
        "margin_needed": round(margin_need, 4),
        "n_required": n_required,
        "n_shortfall": max(0, n_required - n),
        "reason": (f"need ~{n_required} pairs (have {n}); "
                   f"CI95 upper {upper:.4f} > {threshold}"),
    })
    return out


def bootstrap_ratio(pairs: list[tuple[float, float]], *, iterations: int = BOOTSTRAP,
                    seed: int = BOOTSTRAP_SEED, keys: list | None = None) -> dict:
    """Percentile bootstrap CI for sum(D)/sum(A) over paired cells.

    Delegates to `tools/live_uncertainty.py::ratio_bootstrap` so the two artifacts
    cannot disagree about the same quantity, and publishes the **task-clustered**
    interval: the three seeds of one task are correlated (ICC 0.28–0.56), so the
    row-level resample used by earlier rounds understates the width. `keys` carries
    the task id per pair; without it the row interval is published and `unit` says so.
    """
    if not pairs:
        return {"point": None, "ci95": [None, None], "n_pairs": 0, "candidate_pairs": 0, "excluded_nonfinite_pairs": 0}
    out = ratio_bootstrap(pairs, kind="acceptance_ratio", iterations=iterations,
                          seed=seed, keys=keys)
    return {"point": out.get("point_estimate"),
            "estimator": "ratio_of_sums",
            "mean_of_ratios": out.get("mean_of_ratios"),
            "ci95": out.get("bootstrap_ci95", [None, None]),
            "ci95_row": out.get("bootstrap_ci95_row"),
            "unit": out.get("bootstrap_unit"),
            "n_pairs": out.get("n_pairs"),
            "candidate_pairs": out.get("candidate_pairs"),
            'excluded_nonfinite_pairs':out.get('excluded_nonfinite_pairs',0),
            "iterations": out.get("bootstrap_iterations"),
            # Caliber is deliberately NOT guessed here. This helper resamples
            # whatever paired values the caller passes, so it cannot know whether
            # they are observation-proxy tokens, endpoint usage, counts or currency,
            # and `kind="acceptance_ratio"` is a label for the resampling recipe, not
            # a caliber. Every caller must overwrite these two fields with the
            # caliber of the specific output field it publishes.
            "caliber": "unverified",
            "caliber_note": "caliber: unverified, must be labelled by the caller — "
                            "bootstrap_ratio does not know what its pairs count"}


def bootstrap_median_ratio(a: list[float], b: list[float], *, iterations: int = BOOTSTRAP,
                           seed: int = BOOTSTRAP_SEED) -> dict:
    """Percentile bootstrap CI for median(ae)/median(other), PAIRED BY ITERATION.

    The bench runs iteration *i* for every shell back-to-back, so sample *i* of one
    shell and sample *i* of the next were taken microseconds apart and share the
    machine state (a background process, a thermal step, a GC pause). Resampling the
    two shells independently — what earlier rounds did — throws that pairing away and
    widens the interval for no reason.
    """
    if not a or not b:
        return {"point": None, "ci95": [None, None], "n": 0}
    n = min(len(a), len(b))
    a, b = list(a[:n]), list(b[:n])
    rng = random.Random(seed)
    ratios: list[float] = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        sa = statistics.median([a[i] for i in idx])
        sb = statistics.median([b[i] for i in idx])
        if sb:
            ratios.append(sa / sb)
    ratios.sort()

    def pct(q):
        return ratios[min(len(ratios) - 1, max(0, int(round(q * (len(ratios) - 1)))))]

    return {"point": round(statistics.median(a) / statistics.median(b), 4),
            "ci95": [round(pct(0.025), 4), round(pct(0.975), 4)],
            "n": n, "iterations": len(ratios), "paired_by_iteration": True}


# ── data loading ───────────────────────────────────────────────────────────────

def paired_cells(payload: dict, baseline: str = "raw_shell") -> dict:
    by_cell: dict[tuple, dict] = {}
    for r in payload.get("rows", []):
        by_cell.setdefault((r.get("task_id"), r.get("seed"), r.get("run_index")), {})[r["condition"]] = r
    return {k: v for k, v in by_cell.items() if baseline in v and "verseshell_aci" in v}


def analyse_live(with_payload: dict, without_payload: dict,
                 baseline: str = "raw_shell") -> dict:
    """Paired analysis of D against `baseline`.

    `baseline="raw_shell"` is the status-quo contrast; `"raw_shell_coached"` is the
    prompt-matched contrast that claim C1 needs, because both arms were then
    briefed with equal detail and the residual difference can be attributed to the
    interface rather than to prompt quality.
    """
    cells = paired_cells(with_payload, baseline)
    items = sorted(cells.items())
    keys = [k[0] for k, _ in items]

    def usage(row: dict) -> float:
        return reported_usage(row)

    tok = [(float(c[baseline]["observation_tokens"]),
            float(c["verseshell_aci"]["observation_tokens"])) for _, c in items]
    tools = [(float(c[baseline]["tool_calls"]),
              float(c["verseshell_aci"]["tool_calls"])) for _, c in items]
    # The pre-registered "real tokenizer" reading: the endpoint's own `usage`,
    # accumulated over observed requests in usage-eligible pairs. Broader than observation_tokens on purpose — it
    # includes the system prompt, the tool schemas, every re-sent observation and the
    # reasoning output per turn — but it is NOT the size of one system prompt or one
    # tool-schema payload and NOT a money cost. When the two disagree in direction,
    # this one governs (docs/acceptance-criteria.md §4.2).
    usage_tok = [(usage(c[baseline]), usage(c["verseshell_aci"])) for _, c in items]
    prompt_tok = [(reported_usage(c[baseline], "llm_prompt_tokens"),
                   reported_usage(c["verseshell_aci"], "llm_prompt_tokens"))
                  for _, c in items]
    completion_tok = [(reported_usage(c[baseline], "llm_completion_tokens"),
                       reported_usage(c["verseshell_aci"], "llm_completion_tokens"))
                      for _, c in items]

    # Success: paired binary -> discordant counts feed the McNemar power lookup.
    only_a = only_d = both = neither = 0
    for c in cells.values():
        a_ok = bool(c[baseline].get("success"))
        d_ok = bool(c["verseshell_aci"].get("success"))
        if a_ok and d_ok:
            both += 1
        elif a_ok and not d_ok:
            only_a += 1
        elif d_ok and not a_ok:
            only_d += 1
        else:
            neither += 1
    n_pairs = len(cells)
    psi = (only_a + only_d) / n_pairs if n_pairs else 0.0
    observed_delta = abs(only_d - only_a) / n_pairs if n_pairs else 0.0

    mde = PREREG["success_mde_absolute"]
    success = {
        "n_pairs": n_pairs,
        "discordant": only_a + only_d,
        "only_A": only_a,
        "only_D": only_d,
        "both_pass": both,
        "neither": neither,
        "discordance_rate_psi": round(psi, 4),
        "observed_abs_delta": round(observed_delta, 4),
        "prereg_mde": mde,
        "n_required_at_mde": mcnemar_n(mde, psi) if psi else None,
        "observed_mde_at_current_n": (round(mcnemar_observed_mde(n_pairs, psi), 4)
                                      if psi else None),
        "powered_for_prereg_mde": bool(psi and mcnemar_n(mde, psi) and n_pairs >= mcnemar_n(mde, psi)),
        "observed_positive_headroom": round(1 - (both + only_a) / n_pairs, 4) if n_pairs else None,
        "positive_mde_feasible_at_observed_baseline": bool(n_pairs and 1 - (both + only_a) / n_pairs >= mde),
        "headroom_note": "sample-size power for an absolute difference does not establish room for a positive improvement",
    }

    # Caliber of each published ratio is resolved by THIS caller (bootstrap_ratio's
    # own default is the explicit "unverified" placeholder, never a guess).
    tok_ratio = bootstrap_ratio(tok, keys=keys)
    tok_ratio["caliber"] = "observation_proxy_estimate_tokens"
    tok_ratio["caliber_note"] = (
        "ratio of the live rows' recorded `observation_tokens`, i.e. the live runner's "
        "`estimate_tokens(text) = max(1, len(text)//4)` accumulated over delivered "
        "observation text: a PROXY, NOT endpoint usage, NOT the evaluated model's own "
        "tokenizer and NOT currency")
    tool_ratio = bootstrap_ratio(tools, keys=keys)
    tool_ratio["caliber"] = "count_ratio"
    tool_ratio["caliber_note"] = (
        "ratio of tool-CALL COUNTS: not tokens, not usage, not currency")
    usage_ratio = bootstrap_ratio(usage_tok, keys=keys)
    usage_ratio["caliber"] = "endpoint_usage_total"
    usage_ratio["caliber_note"] = (
        "ratio of endpoint-reported `usage` summed over observed requests in usage-eligible pairs "
        "(llm_prompt_tokens + llm_completion_tokens): system prompt + tool schemas + "
        "re-sent history + reasoning per turn. It is NOT the length of one system prompt "
        "or one tool-schema payload, and without price/cache rules it is NOT a money cost")
    prompt_ratio = bootstrap_ratio(prompt_tok, keys=keys)
    prompt_ratio["caliber"] = "endpoint_usage_prompt"
    prompt_ratio["caliber_note"] = (
        "ratio of endpoint-reported `llm_prompt_tokens` (input usage accumulated over "
        "observed requests in usage-eligible pairs), NOT one request's system-prompt/schema size and NOT currency")
    completion_ratio = bootstrap_ratio(completion_tok, keys=keys)
    completion_ratio["caliber"] = "endpoint_usage_completion"
    completion_ratio["caliber_note"] = (
        "ratio of endpoint-reported `llm_completion_tokens` (output usage). The reasoning "
        "billing boundary is unconfirmed, so it is NOT the visible answer's character "
        "count and NOT currency")

    # Cost per successful task: tokens spent / successes, per arm.
    def cpst(payload):
        rows = payload.get("rows", [])
        total = sum(float(r["observation_tokens"]) for r in rows)
        wins = sum(1 for r in rows if r.get("success"))
        return total / wins if wins else None, total, wins

    cpst_a, tok_a, win_a = cpst(with_payload)
    # Paired CPST proxy: per (task,seed) cell, D tokens/D success vs baseline.
    per_cell = []
    for c in cells.values():
        ta = float(c[baseline]["observation_tokens"])
        td = float(c["verseshell_aci"]["observation_tokens"])
        sa = 1.0 if c[baseline].get("success") else 0.0
        sd = 1.0 if c["verseshell_aci"].get("success") else 0.0
        per_cell.append((ta, td, sa, sd))
    sum_a_tok = sum(p[0] for p in per_cell)
    sum_d_tok = sum(p[1] for p in per_cell)
    sum_a_win = sum(p[2] for p in per_cell)
    sum_d_win = sum(p[3] for p in per_cell)
    cpst_ratio = ((sum_d_tok / sum_d_win) / (sum_a_tok / sum_a_win)
                  if sum_d_win and sum_a_win and sum_a_tok else None)

    # Success non-inferiority: paired difference CI lower bound.
    #
    # The parentheses matter. `1.0 if D else 0.0 - (1.0 if A else 0.0)` parses as
    # `1.0 if D else (0.0 - A)`, which scores 1.0 whenever D succeeded even if A did
    # too — that produced a mean of 0.7333 and a lower bound of +0.5864 for a sample
    # whose real paired difference is +0.12 (see docs/audit-r12-verification.md §3.4).
    diffs = [
        (1.0 if c["verseshell_aci"].get("success") else 0.0)
        - (1.0 if c[baseline].get("success") else 0.0)
        for c in cells.values()
    ]
    mean_diff = statistics.fmean(diffs) if diffs else 0.0
    sd_diff = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
    se = sd_diff / math.sqrt(len(diffs)) if diffs else 0.0
    # Normal quantile, matching the paired interval reported by tools/live_uncertainty.py,
    # so the two artifacts cannot disagree about the same quantity.
    noninf_lower = mean_diff - Z_A * se

    without_cells = paired_cells(without_payload, baseline)
    without_psi = 0.0
    without_obs = 0.0
    if without_cells:
        oa = sum(1 for c in without_cells.values()
                 if c[baseline].get("success") and not c["verseshell_aci"].get("success"))
        od = sum(1 for c in without_cells.values()
                 if c["verseshell_aci"].get("success") and not c[baseline].get("success"))
        without_psi = (oa + od) / len(without_cells)
        without_obs = abs(od - oa) / len(without_cells)

    return {
        "baseline_condition": baseline,
        "n_rows": len(with_payload.get("rows", [])),
        "n_pairs": n_pairs,
        "success": success,
        "token_ratio": tok_ratio,
        "tool_ratio": tool_ratio,
        # Endpoint usage in eligible paired rows only; unknown retries are excluded.
        # Received token counts are not a reconciled provider bill.
        # This is NOT the length of one system prompt or one tool-schema payload, and it
        # is never converted to money. It is not gated by its own threshold — the
        # pre-registered ladder is defined on observation tokens — but it must be
        # published next to it, because docs/acceptance-criteria.md §4.2 says the
        # endpoint-usage reading governs when the two disagree in direction. Each ratio is
        # self-labelled through its `caliber` / `caliber_note` fields.
        "usage_token_ratio": usage_ratio,
        "prompt_token_ratio": prompt_ratio,
        "completion_token_ratio": completion_ratio,
        "usage_note": "Unknown usage is excluded, never zero-imputed; candidate_pairs, n_pairs and "
                      "excluded_nonfinite_pairs describe the cost denominator, not the score denominator. "
                      "No provider invoice is reconciled. Caliber: endpoint usage, not system-prompt length. `usage_*` blocks are "
                      "the endpoint's reported `usage` accumulated over observed requests in usage-eligible pairs (system "
                      "prompt + tool schemas + re-sent history + reasoning). They are broader "
                      "than observation_tokens, are NOT the size of one system prompt or one "
                      "tool-schema payload, and are NOT a money cost. `token_ratio` is "
                      "observation-proxy caliber (max(1, len(text)//4) over the delivered "
                      "observation text) and `tool_ratio` is a ratio of CALL COUNTS. "
                      "Observation tokens being cheaper while usage tokens are dearer is a "
                      "real, reportable combination, not a contradiction",
        "cost_per_success": {
            "paired_task_intervals": {view: cost_per_success_interval(
                with_payload.get('rows', []), baseline, (with_payload.get('live_config') or {}).get('max_turns'), view=view)
                for view in ('analysable', 'intention_to_treat')},
            "point_D_over_A": round(cpst_ratio, 4) if cpst_ratio is not None else None,
            "tokens_A": round(sum_a_tok, 2),
            "tokens_D": round(sum_d_tok, 2),
            "successes_A": int(sum_a_win),
            "successes_D": int(sum_d_win),
            "cpst_A_tokens_per_success": round(sum_a_tok / sum_a_win, 3) if sum_a_win else None,
            "cpst_D_tokens_per_success": round(sum_d_tok / sum_d_win, 3) if sum_d_win else None,
            "success_noninferiority_lower_bound": round(noninf_lower, 4),
            "success_mean_diff_D_minus_A": round(mean_diff, 4),
            "caliber": "observation_proxy_tokens_per_success",
            "caliber_note": "`cost_per_success` / `cpst_*` divide OBSERVATION-PROXY tokens (the "
                            "live rows' recorded `observation_tokens`, i.e. max(1, len(text)//4) "
                            "over delivered observation text) by the count of SUCCESSFUL tasks. "
                            "Despite the word `cost` this is NOT currency and NOT a billed "
                            "endpoint-usage measurement; `tokens_A` / `tokens_D` are that same "
                            "proxy",
        },
        "without_arm": {
            "n_pairs": len(without_cells),
            "discordance_rate_psi": round(without_psi, 4),
            "observed_abs_delta": round(without_obs, 4),
        },
        "raw_shell_successes": win_a,
        "cpst_A_absolute": cpst_a,
    }


def analyse_cross_shell(payload: dict) -> dict:
    ops = []
    for op in payload.get("operations", []):
        shells = op.get("shells", {})
        ae = shells.get("ae", {}).get("samples_ms") or []
        equiv = op.get("equivalence") or {}
        row = {
            "operation": op.get("name"),
            "n": len(ae),
            "outputs_equivalent": bool(equiv.get("equivalent")),
            "equivalence_keys": equiv.get("distinct_keys"),
            "unresolved_shells": equiv.get("unresolved_shells"),
            "cold_vs_warm": {
                s: {"cold_ms": shells.get(s, {}).get("cold_ms"),
                    "warm_median_ms": shells.get(s, {}).get("warm_median_ms")}
                for s in ("ae", "pwsh", "cmd", "bash") if shells.get(s)
            },
        }
        for other in ("pwsh", "cmd", "bash"):
            samples = shells.get(other, {}).get("samples_ms") or []
            row[f"vs_{other}"] = bootstrap_median_ratio(ae, samples) if samples else None
        ops.append(row)

    def worst(key: str) -> float | None:
        vals = [o[key]["point"] for o in ops if o.get(key)]
        return max(vals) if vals else None

    return {
        "operations": ops,
        "worst_point_ratio_vs_pwsh": worst("vs_pwsh"),
        "worst_point_ratio_vs_cmd": worst("vs_cmd"),
        "all_outputs_equivalent": all(o["outputs_equivalent"] for o in ops),
        "interleaved": bool(payload.get("method", {}).get("interleaved")),
        "n_iterations": payload.get("method", {}).get("iterations"),
        "comparator_note": "cmd.exe is the shell the raw-shell baseline arm actually runs "
                           "through (`shell=True` in the live runner); PowerShell is the one "
                           "the README advertises. Only the PowerShell comparison is "
                           "pre-registered (C11); the cmd.exe numbers are recorded as "
                           "context and are NOT a claim",
        "wall_clock_context": payload.get("wall_clock_context") or {},
    }


# ── TF-0113: hypothesis families and family-wise error control ──────────────────
#
# Eleven verdicts used to be published side by side, each at alpha=0.05, with no
# multiplicity correction — so at 11 independent items the family-wise error rate is
# 1 - 0.95**11 = 43.1%. A claimable item sitting on the boundary (the D/A' observation
# token upper bound of 0.9788, with 0.0212 of margin) cannot survive that.
#
# The split below is PRE-REGISTERED in docs/acceptance-criteria.md §0.7 and is by DATA
# SOURCE and QUESTION, not by convenience: the two cross-shell verdicts come from a local
# process benchmark with its own pre-registration and its own data, so they form a
# separate family and must not dilute (or be diluted by) the live-model ladder.
# Anything absent from this table is EXPLORATORY: post-hoc, with no pre-registered
# threshold, and it may never be cited as a confirmatory result.
VERDICT_FAMILIES: dict[str, str] = {
    "success_paired_can_claim_MDE_0.15": "live_model",
    "token_ratio_level1_D_cheaper": "live_model",
    "token_ratio_level2_saves_15pct": "live_model",
    "token_ratio_frozen_0.60": "live_model",
    "tool_ratio_level1_D_fewer_calls": "live_model",
    "token_ratio_coached_level1_D_cheaper": "live_model",
    "cost_per_success_D_cheaper": "live_model",
    "success_paired_coached_can_claim_MDE_0.15": "live_model",
    "cost_per_success_coached_D_cheaper": "live_model",
    "cross_shell_all_ops_strictly_faster": "cross_shell",
    "cross_shell_all_ops_2x": "cross_shell",
}


def _approx_p_from_ci(point, lower, upper, null_value) -> float | None:
    """Approximate two-sided p-value from a percentile CI95.

    The verdicts are interval-based rather than p-value based, so Holm needs a p-value
    from somewhere. This recovers one through the interval's own width
    (`SE ~ (upper - lower) / (2 * Z_A)`, `z = (null_value - point) / SE`) and is labelled
    `p_value_kind = "approx_from_ci95"` everywhere it appears. It exists so that a
    family-wise correction can be applied at all; it does NOT replace the interval rule —
    `claimable` still requires the interval itself to clear the threshold.
    """
    if point is None or lower is None or upper is None or null_value is None:
        return None
    half = (upper - lower) / 2.0
    if half <= 0:
        return None
    se = half / Z_A
    z = (null_value - point) / se
    return max(0.0, min(1.0, math.erfc(abs(z) / math.sqrt(2.0))))


def apply_multiplicity(verdicts: dict, alpha: float = 0.05) -> tuple[dict, dict]:
    """Label every verdict's family and Holm-correct the confirmatory ones.

    Only interval-based verdicts can be corrected this way, because only they carry a
    (point, CI) triple to convert into a p-value. The success verdicts are *design/power*
    verdicts — they ask "is n large enough to detect the pre-registered MDE", not "is the
    observed difference significant" — so `passes_holm` stays `None` for them and they are
    left as they were. That limitation is reported, not hidden.
    """
    families: dict[str, list[str]] = {}
    for key in verdicts:
        fam = VERDICT_FAMILIES.get(key, "exploratory")
        verdicts[key]["family"] = fam
        families.setdefault(fam, []).append(key)

    summary: dict = {
        "alpha": alpha,
        "method": "Holm-Bonferroni, within family",
        "families_table": dict(VERDICT_FAMILIES),
        "preregistered_in": "docs/acceptance-criteria.md §0.7",
        "families": {},
        "demoted_by_multiplicity": [],
        "note": ("Exploratory verdicts have no pre-registered threshold and are never "
                 "claimable as confirmatory results. Families are split by data source: "
                 "the live-model ladder and the local cross-shell benchmark do not share "
                 "a correction."),
    }

    demoted: list[str] = []
    for fam, keys in families.items():
        if fam == "exploratory":
            summary["families"][fam] = {
                "m": len(keys), "corrected": False,
                "reason": "post-hoc, no pre-registered threshold",
                "members": sorted(keys),
            }
            for k in keys:
                verdicts[k]["multiplicity_corrected"] = False
                verdicts[k]["claimable_before_multiplicity"] = bool(verdicts[k].get("claimable"))
                verdicts[k]["claimable_after_multiplicity"] = False
                verdicts[k]["claimable"] = False
            continue

        scored = []
        for k in keys:
            v = verdicts[k]
            p = _approx_p_from_ci(v.get("point"), v.get("ci95_lower"), v.get("ci95_upper"),
                                  v.get("threshold"))
            scored.append((k, p))
        ordered = sorted([s for s in scored if s[1] is not None], key=lambda s: s[1])
        # Power checks are design diagnostics, not effect hypotheses. Missing
        # intervals for effect claims must not shrink the correction family.
        design_checks = {k for k in keys if k.startswith("success_paired")}
        m = len(keys) - len(design_checks)
        holm: dict[str, tuple[float, float, bool]] = {}
        still_passing = True
        for i, (k, p) in enumerate(ordered):
            a_i = alpha / (m - i)
            ok = still_passing and p <= a_i
            if not ok:
                still_passing = False
            holm[k] = (p, a_i, ok)

        for k in keys:
            v = verdicts[k]
            before = bool(v.get("claimable"))
            v["multiplicity_corrected"] = k in holm
            v["claimable_before_multiplicity"] = before
            if k in holm:
                p, a_i, ok = holm[k]
                v["p_value_approx"] = round(p, 6)
                v["p_value_kind"] = "approx_from_ci95"
                v["holm_alpha"] = round(a_i, 6)
                v["passes_holm"] = ok
                v["claimable_after_multiplicity"] = before and ok
                v["claimable"] = before and ok
                if before and not ok:
                    v["demoted_by_multiplicity"] = True
                    demoted.append(k)
            else:
                v["passes_holm"] = None
                v["claimable_after_multiplicity"] = before if k in design_checks else False
                v["claimable"] = v["claimable_after_multiplicity"]
                v["multiplicity_note"] = ("sample-size diagnostic, not an effect claim"
                                          if k in design_checks else
                                          "missing effect interval/p-value; confirmatory claim blocked")
                if before and k not in design_checks:
                    v["demoted_by_multiplicity"] = True
                    demoted.append(k)

        summary["families"][fam] = {
            "m": len(keys),
            "m_scored": len(ordered),
            "hypothesis_count": m,
            "corrected": bool(holm),
            "members": sorted(keys),
            "holm_alpha": {k: round(a, 6) for k, (_, a, _) in holm.items()},
            "uncorrected_members": sorted(k for k in keys if k not in holm),
        }

    summary["demoted_by_multiplicity"] = sorted(demoted)
    return verdicts, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "acceptance_power.json")
    ap.add_argument('--prompt-variant')
    ap.add_argument("--with-arm", type=Path, default=ROOT / "bench/aci/results/latest_live.json")
    ap.add_argument("--without-arm", type=Path, default=ROOT / "bench/aci/results/live_ab_without_read_files.json")
    ap.add_argument("--cross-shell", type=Path, default=ROOT / "eval/cross_shell.json")
    ap.add_argument("--with-only", action="store_true",
                    help="no read_files ablation was collected; do not borrow a historical control")
    ap.add_argument("--skip-cross-shell", action="store_true",
                    help="exclude unrelated cross-shell timings from this collection report")
    args = ap.parse_args(argv)

    with_payload = select_prompt_variant(json.loads(args.with_arm.read_text(encoding="utf-8-sig")), args.prompt_variant)
    without_payload = {} if args.with_only else select_prompt_variant(json.loads(args.without_arm.read_text(encoding="utf-8-sig")), args.prompt_variant)
    live = analyse_live(with_payload, without_payload, "raw_shell")
    # Claim C1's contrast: D against the prompt-matched shell arm. Only this one can
    # attribute a difference to the INTERFACE, because both arms were briefed with
    # equal detail.
    live_coached = analyse_live(with_payload, without_payload, "raw_shell_coached")
    has_coached = bool(paired_cells(with_payload, "raw_shell_coached"))
    cross = (json.loads(args.cross_shell.read_text(encoding="utf-8"))
             if not args.skip_cross_shell and args.cross_shell.exists() else {})

    n_pairs = live["n_pairs"]
    tok = live["token_ratio"]
    tool = live["tool_ratio"]
    cpst = live["cost_per_success"]

    verdicts = {
        "success_paired_can_claim_MDE_0.15": {
            "claim": "D 与 A 的成功率差达到预注册 MDE 0.15 时可判定",
            "claimable": bool(live["success"]["powered_for_prereg_mde"]),
            "n_actual": n_pairs,
            "n_required": live["success"]["n_required_at_mde"],
            "powered": live["success"]["powered_for_prereg_mde"],
            "observed_mde_at_current_n": live["success"]["observed_mde_at_current_n"],
            "reason": (f"need ~{live['success']['n_required_at_mde']} pairs for MDE "
                       f"{PREREG['success_mde_absolute']}; at n={n_pairs} only "
                       f"|delta|>={live['success']['observed_mde_at_current_n']} is detectable"
                       if live["success"]["n_required_at_mde"] else "no discordant pairs -> undefined"),
        },
        "token_ratio_level1_D_cheaper": ratio_verdict(
            tok["point"], tok["ci95"][0], tok["ci95"][1], n_pairs,
            PREREG["token_ratio_level1_upper"], unit=tok.get("unit")),
        "token_ratio_level2_saves_15pct": ratio_verdict(
            tok["point"], tok["ci95"][0], tok["ci95"][1], n_pairs,
            PREREG["token_ratio_level2_upper"], unit=tok.get("unit"),
            point_cap=PREREG["token_ratio_level2_point"]),
        "token_ratio_frozen_0.60": ratio_verdict(
            tok["point"], tok["ci95"][0], tok["ci95"][1], n_pairs,
            PREREG["token_ratio_frozen_upper"], unit=tok.get("unit"),
            point_cap=PREREG["token_ratio_frozen_point"]),
        "tool_ratio_level1_D_fewer_calls": ratio_verdict(
            tool["point"], tool["ci95"][0], tool["ci95"][1], n_pairs,
            PREREG["tool_ratio_level1_upper"], unit=tool.get("unit")),
        # Claim C1: the prompt-matched contrast. This is the only contrast that can
        # be attributed to the interface, because both arms were briefed equally.
        "token_ratio_coached_level1_D_cheaper": (
            ratio_verdict(live_coached["token_ratio"]["point"],
                          live_coached["token_ratio"]["ci95"][0],
                          live_coached["token_ratio"]["ci95"][1],
                          live_coached["n_pairs"], PREREG["token_ratio_level1_upper"],
                          unit=live_coached["token_ratio"].get("unit"))
            if has_coached else
            {"claimable": False,
             "reason": "the prompt-matched arm (raw_shell_coached) was not run, so the "
                       "interface effect cannot be separated from the prompt effect"}
        ),
        "cost_per_success_D_cheaper": {
            "claim": "每成功一次任务的花费（观察 token/成功数）D <= 0.80 A，且成功率非劣",
            "point_D_over_A": cpst["point_D_over_A"],
            "cpst_A_tokens_per_success": cpst["cpst_A_tokens_per_success"],
            "cpst_D_tokens_per_success": cpst["cpst_D_tokens_per_success"],
            "success_noninferiority_lower_bound": cpst["success_noninferiority_lower_bound"],
            "noninferiority_margin": PREREG["success_noninferiority_margin"],
            "success_noninferiority_ok":
                cpst["success_noninferiority_lower_bound"] >= -PREREG["success_noninferiority_margin"],
            "point_ok": (cpst["point_D_over_A"] is not None
                         and cpst["point_D_over_A"] <= PREREG["cost_per_success_point"]),
            "claimable": bool(cpst["point_D_over_A"] is not None
                              and cpst["point_D_over_A"] <= PREREG["cost_per_success_point"]
                              and cpst["success_noninferiority_lower_bound"]
                              >= -PREREG["success_noninferiority_margin"]),
            "reason": "cost ratio must clear the cap AND success must be non-inferior; "
                      "cheaper-by-failing is not a saving",
        },
    }

    # D vs A′ — the prompt-matched contrast, and the only one that can be attributed
    # to the interface rather than to prompt quality. It needs its own success and
    # CPST verdicts instead of being folded into the D-vs-A rows: earlier rounds
    # reported the coached success difference nowhere, so a nominally significant
    # result on the only attributable contrast was invisible to the gate.
    if has_coached:
        cs = live_coached["success"]
        verdicts["success_paired_coached_can_claim_MDE_0.15"] = {
            "claim": "D 与 A′（提示词等量对照）的成功率差达到预注册 MDE 0.15 时可判定",
            "claimable": bool(cs["powered_for_prereg_mde"]),
            "n_actual": cs["n_pairs"],
            "n_required": cs["n_required_at_mde"],
            "powered": cs["powered_for_prereg_mde"],
            "observed_mde_at_current_n": cs["observed_mde_at_current_n"],
            "only_A": cs["only_A"],
            "only_D": cs["only_D"],
            "observed_abs_delta": cs["observed_abs_delta"],
            "reason": (f"need ~{cs['n_required_at_mde']} pairs for MDE "
                       f"{PREREG['success_mde_absolute']}; at n={cs['n_pairs']} only "
                       f"|delta|>={cs['observed_mde_at_current_n']} is detectable"
                       if cs["n_required_at_mde"] else
                       "no discordant pairs -> undefined"),
        }
        cc = live_coached["cost_per_success"]
        cc_noninferior = (cc["success_noninferiority_lower_bound"]
                          >= -PREREG["success_noninferiority_margin"])
        verdicts["cost_per_success_coached_D_cheaper"] = {
            "claim": "每成功一次任务的花费（观察 token/成功数）D <= 0.80 A′，且成功率非劣",
            "point_D_over_A": cc["point_D_over_A"],
            "cpst_A_tokens_per_success": cc["cpst_A_tokens_per_success"],
            "cpst_D_tokens_per_success": cc["cpst_D_tokens_per_success"],
            "success_noninferiority_lower_bound": cc["success_noninferiority_lower_bound"],
            "noninferiority_margin": PREREG["success_noninferiority_margin"],
            "success_noninferiority_ok": bool(cc_noninferior),
            "point_ok": (cc["point_D_over_A"] is not None
                         and cc["point_D_over_A"] <= PREREG["cost_per_success_point"]),
            "claimable": bool(cc["point_D_over_A"] is not None
                              and cc["point_D_over_A"] <= PREREG["cost_per_success_point"]
                              and cc_noninferior),
            "reason": "same rule as the D-vs-A row, applied to the prompt-matched arm: "
                      "the cost ratio must clear the cap AND success must be non-inferior",
        }

    # Cross-shell per-operation verdicts. `docs/acceptance-criteria.md` §2 requires the
    # equivalence of the command outputs to be PROVEN BEFORE the times are compared, so
    # `all_outputs_equivalent` is part of `claimable` — a speedup over a shell that was
    # asked to do different work is not a speedup.
    cs_analysis = analyse_cross_shell(cross) if cross else {}
    cs_ops = []
    for row in cs_analysis.get("operations", []):
        r = row.get("vs_pwsh")
        if not r:
            continue
        cs_ops.append({
            "operation": row["operation"],
            "n": r["n"],
            "point": r["point"],
            "ci95": r["ci95"],
            "paired_by_iteration": r.get("paired_by_iteration"),
            "outputs_equivalent": row.get("outputs_equivalent"),
            "strictly_faster": r["ci95"][1] < PREREG["cross_shell_strict_upper"],
            "at_least_2x_faster": r["ci95"][1] < PREREG["cross_shell_2x_upper"],
            "vs_cmd_point": (row.get("vs_cmd") or {}).get("point"),
        })
    outputs_equivalent = bool(cs_analysis.get("all_outputs_equivalent"))
    # The "every operation" verdicts hinge on the operation with the WIDEST interval —
    # that is the one that can fail the claim. Publishing its (point, CI) as the
    # verdict's own scoring triple is what lets the TF-0113 multiplicity pass compute a
    # p-value for this family at all; without it the cross-shell family would be labelled
    # "corrected" while nothing was actually corrected.
    worst_op = max(cs_ops, key=lambda o: o["ci95"][1]) if cs_ops else None
    worst_scoring = ({
        "scoring_operation": worst_op["operation"],
        "point": worst_op["point"],
        "ci95_lower": worst_op["ci95"][0],
        "ci95_upper": worst_op["ci95"][1],
    } if worst_op else {})
    verdicts["cross_shell_all_ops_strictly_faster"] = {
        "claim": "每一个操作的墙钟中位数比都严格快于 PowerShell（CI95 上界 < 1.00），"
                 "且该操作的输出等价已先被证明",
        "operations": cs_ops,
        "worst_point": max((o["point"] for o in cs_ops), default=None),
        "worst_point_vs_cmd": cs_analysis.get("worst_point_ratio_vs_cmd"),
        "all_outputs_equivalent": outputs_equivalent,
        "interleaved": bool(cs_analysis.get("interleaved")),
        "threshold": PREREG["cross_shell_strict_upper"],
        **worst_scoring,
        "claimable": (bool(cs_ops) and outputs_equivalent
                      and all(o["strictly_faster"] for o in cs_ops)),
        "reason": "headline must be the WORST operation, never the best; and §2 requires "
                  "output equivalence before timing. `worst_point_vs_cmd` is context only: "
                  "cmd.exe is the shell the baseline arm actually uses, but the "
                  "pre-registered claim is against PowerShell",
    }
    verdicts["cross_shell_all_ops_2x"] = {
        "claim": "每一个操作都快于 PowerShell 2 倍（CI95 上界 < 0.50），且输出等价已先被证明",
        "threshold": PREREG["cross_shell_2x_upper"],
        **worst_scoring,
        "claimable": (bool(cs_ops) and outputs_equivalent
                      and all(o["at_least_2x_faster"] for o in cs_ops)),
        "failing_operations": [o["operation"] for o in cs_ops if not o["at_least_2x_faster"]],
        "all_outputs_equivalent": outputs_equivalent,
    }
    # These two verdicts now carry a scoring triple (`point`/`ci95_*`/`threshold`) so the
    # TF-0113 multiplicity pass can correct them — the worst operation's interval is the
    # one that can fail an "every operation" claim. Publishing an interval means C28's
    # interval-vs-label consistency check now inspects them, so they must publish the
    # interval-derived labels as well. With the worst operation's lower bound around 0.25
    # against caps of 1.00 / 0.50, the whole interval is on the claimed side: the label is
    # `none` when claimable, `data_gap` otherwise, and `impossible_by_sample_size` is
    # False because more data is not what constrains these claims.
    for _k in ("cross_shell_all_ops_strictly_faster", "cross_shell_all_ops_2x"):
        _v = verdicts[_k]
        if "ci95_lower" in _v:
            _v.setdefault("gap_type", "none" if _v.get("claimable") else "data_gap")
            _v.setdefault("impossible_by_sample_size", False)

    # ── §0.6 pre-registered row policy (tree-farm TF-0118) ───────────────────────
    # Which rows count is decided by a rule written BEFORE the data. A comparison is
    # claimable only when BOTH its arms keep endpoint_failure <= 10% AND
    # cap_truncated <= 10%, and the `analysable` and `intention_to_treat` views do not
    # point in opposite directions. Judged PER COMPARISON, not for the whole round:
    # truncation is one-sided in practice — on the 2026-09-27 re-run only A' was
    # truncated (13.3%), which must block the coached contrast without silently
    # invalidating D-vs-A. §0.5's remedy (raise the cap and re-run) is NOT available on
    # this endpoint: re-probing those cells at max_tokens=32768 gave 0 length
    # truncations and 9 HTTP 502s, and merge_live_runs.py refuses api_error rows.
    policy = row_policy(
        with_payload["rows"],
        ["raw_shell", "raw_shell_coached", "verseshell_aci"],
        (with_payload.get("live_config") or {}).get("max_turns"),
        comparisons=[("raw_shell", "verseshell_aci"),
                     ("raw_shell_coached", "verseshell_aci")],
    )
    VERDICT_COMPARISON = {
        "success_paired_can_claim_MDE_0.15": "verseshell_aci_vs_raw_shell",
        "token_ratio_level1_D_cheaper": "verseshell_aci_vs_raw_shell",
        "token_ratio_level2_saves_15pct": "verseshell_aci_vs_raw_shell",
        "token_ratio_frozen_0.60": "verseshell_aci_vs_raw_shell",
        "tool_ratio_level1_D_fewer_calls": "verseshell_aci_vs_raw_shell",
        "cost_per_success_D_cheaper": "verseshell_aci_vs_raw_shell",
        "token_ratio_coached_level1_D_cheaper": "verseshell_aci_vs_raw_shell_coached",
        "success_paired_coached_can_claim_MDE_0.15": "verseshell_aci_vs_raw_shell_coached",
        "cost_per_success_coached_D_cheaper": "verseshell_aci_vs_raw_shell_coached",
    }
    for _vkey, _ckey in VERDICT_COMPARISON.items():
        _v = verdicts.get(_vkey)
        _cmp = policy["comparisons"].get(_ckey)
        if not isinstance(_v, dict) or not _cmp:
            continue
        _v["row_policy_comparison"] = _ckey
        _v["row_policy_claimable"] = _cmp["claimable"]
        _v["row_policy_blocked_reasons"] = _cmp["policy_blocked_reasons"]
        _v["success_delta_analysable"] = _cmp["success_delta_analysable"]
        _v["success_delta_intention_to_treat"] = _cmp["success_delta_intention_to_treat"]
        if not _cmp["claimable"] and _v.get("claimable"):
            _v["claimable_before_row_policy"] = True
            _v["claimable"] = False
            _v["gap_type"] = "policy_blocked"
            _v["reason"] = ("§0.6 row policy: "
                            + ", ".join(_cmp["policy_blocked_reasons"])
                            + " — the row set may not be chosen after seeing the result")

    # ── TF-0113: family labels + family-wise error control (docs §0.7) ──
    # Applied AFTER the row-policy pass so that a verdict blocked by §0.6 stays blocked,
    # and a verdict that survives the row policy still has to survive multiplicity.
    verdicts, multiplicity = apply_multiplicity(verdicts, MULTIPLICITY_ALPHA)

    payload = {
        "schema": "verseshell.acceptance_power/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/acceptance_power.py",
        "source": str(args.with_arm),
        "model": with_payload.get("live_config", {}).get("model"),
        "task_set_version": with_payload.get("task_set_version"),
        "without_arm_available": not args.with_only,
        "prompt_variant": with_payload.get("live_config", {}).get("prompt_variant"),
        "interpretation": "Statistical eligibility for the recorded pipeline, not proof of an "
                          "interface-only effect. Historical compact changes D descriptions only. "
                          "Report both ratio estimators; endpoint usage governs over observation proxy.",
        "preregistration_source": "docs/acceptance-criteria.md",
        "preregistered_parameters": PREREG,
        "method": {
            "success": "paired McNemar normal approximation, alpha=0.05 two-sided, power=0.80",
            "ratios": "percentile bootstrap CI95 resampling whole TASKS (the design unit: "
                      "the three seeds of one task are correlated, measured ICC 0.28-0.56). "
                      "The row-level interval is kept as `ci95_row` for continuity with "
                      "earlier rounds; it is systematically narrower",
            "real_tokenizer": "endpoint `usage` accumulated over every turn (system prompt + "
                              "tool schemas + re-sent history + reasoning), published as "
                              "`usage_token_ratio` / `prompt_token_ratio` / "
                              "`completion_token_ratio`; governs when it disagrees in "
                              "direction with the observation-token proxy",
            "cross_shell": "percentile bootstrap CI95 on median(ae)/median(other), PAIRED BY "
                           "ITERATION (the bench runs iteration i for every shell "
                           "back-to-back, so pairing is the honest unit); output equivalence "
                           "must be proven before the times are compared",
            "rule": "a claim is only allowed when its interval clears the threshold; a product "
                    "gap (no amount of data can rescue the claim) is asserted only when the "
                    "WHOLE CI95 lies on the wrong side of the cap the claim needs. A point "
                    "estimate past the threshold whose interval still reaches below it is "
                    "'no evidence' (`gap_type=data_gap`), because the estimate can move",
        },
        "live": live,
        "live_coached": live_coached,
        "has_prompt_matched_arm": has_coached,
        "row_policy": policy,
        "multiplicity": multiplicity,
        "cross_shell": cs_analysis,
        "verdicts": verdicts,
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
                     "input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in [args.with_arm,
                                                *([] if args.with_only else [args.without_arm]),
                                                *([] if args.skip_cross_shell or not args.cross_shell.exists()
                                                  else [args.cross_shell])]}},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    print(f"\n样本: pairs={n_pairs} (rows={live['n_rows']})")
    s = live["success"]
    print(f"\n成功率（配对 McNemar，预注册 MDE={PREREG['success_mde_absolute']}）")
    print(f"  不一致 {s['discordant']}（A 独赢 {s['only_A']} / D 独赢 {s['only_D']}），psi={s['discordance_rate_psi']}")
    print(f"  需要 {s['n_required_at_mde']} 对；当前 {n_pairs} 对 → "
          f"{'达标' if s['powered_for_prereg_mde'] else '**样本不足**'}")
    print(f"  当前 n 只能检出 |delta| >= {s['observed_mde_at_current_n']}")
    print("\n比值类判定（bootstrap CI95）")
    for key in ("token_ratio_level1_D_cheaper", "token_ratio_level2_saves_15pct",
                "token_ratio_frozen_0.60", "tool_ratio_level1_D_fewer_calls"):
        v = verdicts[key]
        print(f"  [{'可主张' if v.get('claimable') else '不可主张'}] {key}: point={v.get('point')} "
              f"ci95=[{v.get('ci95_lower')}, {v.get('ci95_upper')}] threshold={v.get('threshold')} "
              f"gap={v.get('gap_type')}")
        if v.get("n_required"):
            print(f"        → 需要约 {v['n_required']} 对（缺 {v['n_shortfall']}）")
        if v.get("impossible_by_sample_size"):
            print("        → **产品缺口**：整个 CI95 都在门槛错误一侧，加样本也救不回来")
        elif v.get("gap_type") == "data_gap":
            print("        → **无证据**：区间仍跨到门槛可达成的一侧，估计值可能移动")
    c = verdicts["cost_per_success_D_cheaper"]
    print(f"\n每成功一次的花费 D/A = {c['point_D_over_A']}（A {c['cpst_A_tokens_per_success']} / "
          f"D {c['cpst_D_tokens_per_success']} tok/成功）")
    print(f"  成功率非劣下界 = {c['success_noninferiority_lower_bound']} "
          f"(margin -{PREREG['success_noninferiority_margin']}) → "
          f"{'OK' if c['success_noninferiority_ok'] else '**劣于对照**'}")
    print("\n跨 shell（headline 取最差操作）")
    for o in cs_ops:
        print(f"  {o['operation']:<14} point={o['point']} ci95={o['ci95']} "
              f"strict={o['strictly_faster']} 2x={o['at_least_2x_faster']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
