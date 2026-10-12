#!/usr/bin/env python3
"""live_uncertainty: put uncertainty on every live number (TF-0088).

The live artifacts record point estimates and nothing else — no interval, no
spread, no paired delta. That is exactly the gap between "we have data" and
"every claim has complete data feedback": a reader cannot tell whether
`success_rate_D - success_rate_A = +0.1667` is a result or noise.

This tool reads a stored live artifact (it makes no API calls) and reports, per
condition pair and per metric:

  - Wilson score interval for each success rate (correct for small n and for
    proportions near 0/1, unlike the normal approximation), on the paired and
    unpaired view;
  - two-proportion z-test (pooled) with a two-sided p-value, so a difference can
    be called significant or not;
  - a paired analysis over (task, seed) cells: mean per-condition delta, the SD
    of the paired differences, a paired t interval, and the n needed for 80%
    power at the observed effect size;
  - mean +- SD for tool calls and observation tokens, with the same paired view.

It also recomputes the artifact's own aggregates from `rows[]` and fails if they
disagree, so a stored aggregate can never drift away from the raw rows.

The point is not to make the numbers look better. It is to state, with the data
already in the repository, which claims the sample can actually support.

Usage:
    python tools/live_uncertainty.py --out eval/live_uncertainty.json
    python tools/live_uncertainty.py --arm bench/aci/results/live_ab_without_read_files.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EVIDENCE_GLOBS = [
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "bench/aci/runners/live_agent_loop.py",
    "tools/live_uncertainty.py",
]

Z_95 = 1.959963984540054


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def rows_fingerprint(rows: list[dict]) -> str:
    """Fingerprint the exact row set used for an uncertainty artifact.

    ``run_variance`` consumes per-seed shards while this report consumes a merged
    artifact. A timestamp or a shared code fingerprint cannot prove that they are
    the same collection. This content fingerprint does: it is order-independent,
    ignores only the derived ``row_class`` field, and includes every measured row
    value and provenance field otherwise.
    """
    canonical: list[str] = []
    for row in rows:
        value = dict(row)
        value.pop("row_class", None)
        canonical.append(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")))
    digest = hashlib.sha256()
    for value in sorted(canonical):
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


# ── statistics ────────────────────────────────────────────────────────────────

def wilson(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval — the honest small-n interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> dict:
    """Pooled two-proportion z-test. Returns z, two-sided p, and phi (effect)."""
    if n1 == 0 or n2 == 0:
        return {"z": None, "p_value": None, "phi": None}
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return {"z": None, "p_value": None, "phi": None}
    z = (p2 - p1) / se
    p_value = 2 * (1 - _normal_cdf(abs(z)))
    phi = 2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1))
    return {"z": round(z, 4), "p_value": round(p_value, 6), "phi": round(phi, 4)}


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def t_crit_975(df: int) -> float:
    """Two-sided 95% t critical value, small table + normal fallback."""
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
             7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
             13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
             19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000}
    if df <= 0:
        return float("nan")
    if df in table:
        return table[df]
    for k in sorted(table):
        if df < k:
            return table[k]
    return 1.96


def n_for_power(effect: float, sd: float, power: float = 0.80) -> int | None:
    """Pairs needed for a paired t-test at the observed effect (alpha=.05)."""
    if sd == 0 or effect == 0 or math.isnan(sd) or math.isnan(effect):
        return None
    z_a, z_b = 1.959963984540054, 0.8416212335729143  # 0.05 two-sided, 80% power
    n = ((z_a + z_b) * sd / abs(effect)) ** 2
    return int(math.ceil(n))


def mean_sd(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "se": None}
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    se = sd / math.sqrt(len(values)) if values else None
    return {"n": len(values), "mean": round(mean, 4), "sd": round(sd, 4),
            "se": None if se is None else round(se, 4)}


def paired_metric(pairs: list[tuple[float, float]], label: str) -> dict:
    """pairs = [(A value, D value)] matched on (task, seed)."""
    if not pairs:
        return {"metric": label, "n_pairs": 0}
    deltas = [d - a for a, d in pairs]
    md = statistics.fmean(deltas)
    sd = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
    se = sd / math.sqrt(len(deltas)) if deltas else None
    crit = t_crit_975(len(deltas) - 1)
    half = crit * se if se is not None else None
    out = {
        "metric": label,
        "n_pairs": len(deltas),
        "mean_delta_D_minus_A": round(md, 4),
        "sd_of_deltas": round(sd, 4),
        "paired_ci95": None if half is None or math.isnan(half)
        else [round(md - half, 4), round(md + half, 4)],
        "n_for_80pct_power": n_for_power(md, sd),
    }
    if sd and not math.isnan(sd) and se:
        t = md / se
        out["paired_t"] = round(t, 4)
        out["paired_p_value"] = round(2 * (1 - _normal_cdf(abs(t))), 6)
    return out


def _percentile(sorted_values: list[float], q: float) -> float:
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def _ratio_of_sums(sample: list[tuple[float, float]]) -> float | None:
    sum_a = sum(p[0] for p in sample)
    if sum_a == 0:
        return None
    return sum(p[1] for p in sample) / sum_a


def cost_per_success_interval(rows, baseline, cap, *, view='analysable', field='observation_tokens', iterations=4000, seed=42):
    """Paired task bootstrap of cost/success; diagnostic until study calibration.

    Invalid inputs or any zero-success resample keep the interval unavailable.
    No p-value is inferred from the bootstrap tail probability.
    """
    if view not in ('analysable', 'intention_to_treat') or iterations < 1:
        raise ValueError('invalid CPST view/iterations')
    cells = {}
    for row in rows:
        if row.get('condition') not in (baseline, 'verseshell_aci'): continue
        key = (row.get('task_id'), row.get('seed'), row.get('run_index'))
        cell = cells.setdefault(key, {})
        if row['condition'] in cell: raise ValueError('duplicate paired cell')
        cell[row['condition']] = row
    clusters = {}; excluded = 0
    for key, cell in cells.items():
        if len(cell) != 2: excluded += 1; continue
        a,d = cell[baseline],cell['verseshell_aci']
        eligible = [row_class(r,cap)=='analysable' for r in (a,d)]
        if view=='analysable' and not all(eligible): excluded += 1; continue
        if any(r.get('measurement_complete') is False for r in (a,d)):
            return {'available':False,'reason':'interrupted attempt measurement unknown'}
        if any(r.get('success') is None and ok for r,ok in zip((a,d),eligible)):
            return {'available':False,'reason':'unverified success denominator'}
        costs = [reported_usage(r) if field=='usage' else r.get(field) for r in (a,d)]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in costs):
            return {'available':False,'reason':'missing/invalid cost; no zero imputation'}
        contribution = [costs[0],int(eligible[0] and a['success'] is True),
                        costs[1],int(eligible[1] and d['success'] is True),1]
        prior=clusters.setdefault(str(key[0]),[0]*5)
        for i,v in enumerate(contribution): prior[i]+=v
    groups=list(clusters.values())
    def estimate(sample):
        ca,sa,cd,sd,n=(sum(c[i] for c in sample) for i in range(5))
        return ((cd/sd)/(ca/sa) if sa and sd and ca>0 else None,
                (sd-sa)/n if n else None)
    if not groups: return {'available':False,'reason':'no eligible pairs','excluded_pairs':excluded}
    point,delta=estimate(groups); rng=random.Random(seed); ratios=[]; differences=[]
    for _ in range(iterations):
        ratio,diff=estimate([groups[rng.randrange(len(groups))] for _ in groups])
        ratios.append(ratio); differences.append(diff)
    undefined=sum(x is None for x in ratios)
    def ci(values):
        if any(x is None for x in values): return None
        values=sorted(values)
        return [_percentile(values,.025),_percentile(values,.975)]
    return {'available':point is not None and not undefined, 'point_estimate':point,
            'ci95':ci(ratios),'success_delta':delta,'success_delta_ci95':ci(differences),
            'undefined_draws':undefined,'bootstrap_unit':'task','tasks':len(groups),
            'n_pairs':sum(g[4] for g in groups),'excluded_pairs':excluded,'view':view,
            'caliber':field,'claimable':False,
            'inference_status':'diagnostic interval; requires prospective calibration and multiplicity'}


def token_count(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def attempt_usage(turn, index):
    """Old records attach usage to the returned turn, never to an earlier retry."""
    attempts = turn.get('transport_attempts') or []
    attempt = attempts[index]
    if 'usage' in attempt:
        return attempt['usage'] if isinstance(attempt['usage'], dict) else {}
    if (index == len(attempts)-1 and not attempt.get('error') and not turn.get('request_error')
            and type(attempt.get('status')) is int and 200 <= attempt['status'] < 300):
        return {k: turn.get(k) for k in ('prompt_tokens', 'completion_tokens')}
    return {}


def usage_exclusion_reasons(row):
    """One conservative cost-row rule shared by single and repeated-run consumers."""
    reasons = []
    for key in ('api_error', 'harness_fault', 'recovery_uncertain'):
        if row.get(key):
            reasons.append(key)
    for key in ('usage_complete', 'measurement_complete'):
        if row.get(key) is False:
            reasons.append(key + '=false')
    for key in ('llm_prompt_tokens', 'llm_completion_tokens'):
        if not token_count(row.get(key)):
            reasons.append('missing_or_invalid_' + key)
    turns = row.get('turn_diagnostics')
    if turns is not None and not isinstance(turns, list):
        reasons.append('invalid_turn_diagnostics')
    elif turns:
        if type(row.get('turns')) is int and len(turns) != row['turns']:
            reasons.append('missing_turn_diagnostics')
        totals = {'prompt_tokens': 0, 'completion_tokens': 0}
        for turn in turns:
            if not isinstance(turn, dict):
                reasons.append('invalid_turn_diagnostics')
                continue
            if turn.get('request_error') or turn.get('record_error'):
                reasons.append('unobserved_turn_usage')
            for key in totals:
                if token_count(turn.get(key)):
                    totals[key] += turn[key]
                else:
                    reasons.append('unobserved_turn_usage')
            attempts = turn.get('transport_attempts') or []
            if not isinstance(attempts, list) or any(not isinstance(a, dict) for a in attempts):
                reasons.append('invalid_attempt_ledger')
                continue
            for index, attempt in enumerate(attempts):
                usage = attempt_usage(turn, index)
                if attempt.get('usage_complete') is False or any(not token_count(usage.get(k)) for k in totals):
                    reasons.append('unobserved_attempt_usage')
                if index < len(attempts)-1:
                    for key in totals:
                        if token_count(usage.get(key)):
                            totals[key] += usage[key]
                elif any(token_count(usage.get(k)) and token_count(turn.get(k)) and usage[k] != turn[k] for k in totals):
                    reasons.append('response_usage_mismatch')
        for key, total in totals.items():
            if token_count(row.get('llm_' + key)) and row['llm_' + key] != total:
                reasons.append('turn_usage_total_mismatch')
    return sorted(set(reasons))


def valid_usage(row):
    return not usage_exclusion_reasons(row)


def reported_usage(row,field=None):
    if not valid_usage(row):return float('nan')
    return float(row[field]) if field else float(row['llm_prompt_tokens']+row['llm_completion_tokens'])


def finite_pairs(pairs, keys=None):
    selected=[i for i,p in enumerate(pairs) if all(type(v) in (int,float) and math.isfinite(v) for v in p)]
    return [pairs[i] for i in selected],([keys[i] for i in selected] if keys is not None else None),len(pairs)-len(selected)


def ratio_bootstrap(pairs: list[tuple[float, float]], *, kind: str,
                    iterations: int = 20000, seed: int = 42,
                    keys: list | None = None) -> dict:
    """Bootstrap CI for the headline ratio D/A.

    The published number is `sum(D)/sum(A)`, a ratio of two dependent sums, and a
    ratio's sampling distribution is skewed, so a normal interval is wrong.

    Two resampling units are computed, and **which one is published matters**:

      * `task` — resample whole tasks, keeping each task's seeds together. This is
        the design unit: the three seeds of one task are correlated (measured ICC
        0.28–0.56, i.e. an effective n of ~35–42 rather than 75), so a row-level
        resample understates the interval. **This is `bootstrap_ci95`, the published
        interval.**
      * `row` — resample individual `(task_id, seed, run_index)` cells. Kept as
        `bootstrap_ci95_row` for continuity with earlier rounds and as a diagnostic.
        It is systematically narrower: on the round-12 data the observation-token
        upper bound was 0.857 by row vs 0.898 by task, against an L2 threshold of
        0.90 — i.e. the row interval was the difference between "claimable" and
        "sitting on the threshold".

    `keys` is a per-pair cluster id (the task id). When it is missing, or when there
    is only one cluster, the row interval is published instead and `clustering_note`
    says so — a caller must never get an unclustered interval silently labelled as
    clustered.
    """
    candidate_pairs = len(pairs)
    pairs,keys,excluded=finite_pairs(pairs,keys)
    if not pairs:
        return {"kind": kind, "n_pairs": 0,'candidate_pairs':candidate_pairs,'excluded_nonfinite_pairs':excluded}
    n = len(pairs)
    point = _ratio_of_sums(pairs)
    if point is None:
        return {'kind':kind,'n_pairs':n,'candidate_pairs':candidate_pairs,'excluded_nonfinite_pairs':excluded,'undefined_reason':'zero denominator'}

    by_cluster: dict[str, list[tuple[float, float]]] = {}
    if keys is not None:
        for key, pair in zip(keys, pairs):
            by_cluster.setdefault(str(key), []).append(pair)
    clusters = sorted(by_cluster)

    def draws(draw):
        rng = random.Random(seed)
        values: list[float] = []
        means: list[float] = []
        for _ in range(iterations):
            sample = draw(rng)
            value = _ratio_of_sums(sample)
            if value is not None:
                values.append(value)
            ratios = [d / a for a, d in sample if a > 0]
            if ratios:
                means.append(statistics.fmean(ratios))
        values.sort()
        means.sort()
        return values, means

    def row_draw(rng):
        return [pairs[rng.randrange(n)] for _ in range(n)]

    def task_draw(rng):
        out: list[tuple[float, float]] = []
        for _ in range(len(clusters)):
            out.extend(by_cluster[clusters[rng.randrange(len(clusters))]])
        return out

    row_values, row_means = draws(row_draw)
    task_values, task_means = draws(task_draw) if len(clusters) > 1 else ([], [])
    published, unit = (task_values, "task") if task_values else (row_values, "row")
    published_means = task_means if unit == "task" else row_means
    ratios = [d / a for a, d in pairs if a > 0]

    out: dict = {
        "kind": kind,
        'candidate_pairs':candidate_pairs,
        'excluded_nonfinite_pairs':excluded,
        "n_pairs": n,
        "point_estimate": round(point, 4),
        "estimator": "ratio_of_sums",
        "mean_of_ratios": {
            "point_estimate": round(statistics.fmean(ratios), 4) if ratios else None,
            "bootstrap_ci95": ([round(_percentile(published_means, 0.025), 4),
                                round(_percentile(published_means, 0.975), 4)]
                               if published_means else None),
            "bootstrap_unit": unit,
            "n_pairs": len(ratios),
            "excluded_nonpositive_baseline": n - len(ratios),
            "weighting": "equal weight per paired cell; seeds retained in task clusters",
        },
        "bootstrap_unit": unit,
        "bootstrap_ci95": [round(_percentile(published, 0.025), 4),
                           round(_percentile(published, 0.975), 4)],
        "bootstrap_ci95_row": ([round(_percentile(row_values, 0.025), 4),
                                round(_percentile(row_values, 0.975), 4)]
                               if row_values else None),
        "bootstrap_iterations": len(published),
        "prob_ratio_below_frozen_target": None,
    }
    if task_values:
        out["n_tasks"] = len(clusters)
        out["bootstrap_ci95_task"] = out["bootstrap_ci95"]
    else:
        out["clustering_note"] = ("no task keys (or a single task): the published "
                                  "interval is the row-level one, which understates "
                                  "the true width")
    target = 0.70 if kind == "tool_call_ratio" else (
        0.60 if kind == "observation_token_ratio" else None)
    if target is not None:
        out["frozen_target"] = target
        out["prob_ratio_below_frozen_target"] = round(
            sum(1 for r in published if r < target) / len(published), 4)
    return out


# ── artifact analysis ─────────────────────────────────────────────────────────

def is_harness_crash(row: dict) -> bool:
    """True when the harness died before recording a single tool result.

    Rows recorded from TF-0100 on carry `harness_crash` explicitly. Rows recorded
    before it do not, so they are recognised by the shape the crash left behind: a
    `last_error` with an empty trajectory (the cp936 decoding crash aborted the loop
    before any observation was appended — see docs/audit-r12-verification.md §5.2).
    Without this, those rows stay folded into the arms' ordinary failures and the
    raw-shell arms look worse than they are.
    """
    if row.get("harness_crash"):
        return True
    return bool(row.get("last_error")) and not row.get("trajectory")


# ── §0.6 row policy (pre-registered, tree-farm TF-0118) ─────────────────────────
#
# §0.5 says "if either side hits the cap >10%, raise the cap and re-run". That remedy
# turned out to be UNAVAILABLE on this endpoint: re-probing the 11 cap-truncated cells
# at max_tokens=32768 produced 0 length-truncations and 9 HTTP 502s (the proxy's 300s
# non-streaming response limit), and merge_live_runs.py refuses an artifact that
# contains api_error rows. With no way to raise the budget, the row set has to be
# decided by a rule written down BEFORE the data (docs/acceptance-criteria.md §0.6),
# not chosen after seeing which choice looks better.
#
# This is the single implementation of that rule: three_arm_report.py and
# acceptance_power.py both call it, so they cannot disagree about which rows count.
POLICY_EXCLUSION_LIMIT = 0.10

# §0.6.8 (pre-registered, tree-farm TF-0121) splits the single `cap_truncated` class
# into the budget AXES that produced it, so every report can say WHICH budget ran out.
# The split is diagnostic: `row_class` and the §0.6.3 gate still use the UNION, because
# a per-axis gate would let the union reach 20% (each axis <= 10%) and so loosen it.
BUDGET_AXIS_COMPLETION = "completion_cap"
BUDGET_AXIS_TURN = "turn_cap"
BUDGET_AXIS_REPEAT_CALL = "repeat_call_cap"
BUDGET_AXES = (BUDGET_AXIS_COMPLETION, BUDGET_AXIS_TURN, BUDGET_AXIS_REPEAT_CALL)


def row_budget_axis(row: dict, cap_turns: int | None = None) -> tuple:
    """Which §0.6.8 budget axes bound this row. Field-driven, never result-driven.

    A row may hit several axes at once (a turn can hit the completion cap AND be the
    last allowed turn); callers count each axis separately and the union only once.
    `stop_reason` is optional: merged artifacts may omit it, and the turn axis is then
    still recoverable from `turns >= max_turns`.
    """
    axes = []
    if row.get("completion_truncated_turns"):
        axes.append(BUDGET_AXIS_COMPLETION)
    if row.get("stop_reason") == "repeat_call_limit":
        axes.append(BUDGET_AXIS_REPEAT_CALL)
    if cap_turns is not None and row.get("turns", 0) >= cap_turns:
        axes.append(BUDGET_AXIS_TURN)
    return tuple(axes)


def row_class(row: dict, cap_turns: int | None = None) -> str:
    """`endpoint_failure` | `cap_truncated` | `analysable` — see docs §0.6.1.

    Field-driven only; no knowledge of which result would be convenient.
    """
    if row.get("api_error") or row.get("harness_fault") or row.get('recovery_uncertain') or is_harness_crash(row):
        return "endpoint_failure"
    if row_budget_axis(row, cap_turns):
        return "cap_truncated"
    return "analysable"


def _budget_axis_counts(rows: list[dict], cap_turns: int | None = None) -> dict:
    """Per-axis hit counts, multi-axis overlap and the de-duplicated union."""
    hits = {axis: 0 for axis in BUDGET_AXES}
    overlap = 0
    for row in rows:
        axes = row_budget_axis(row, cap_turns)
        for axis in axes:
            hits[axis] += 1
        if len(axes) > 1:
            overlap += 1
    n = len(rows)
    return {
        **hits,
        "overlap": overlap,
        "union": sum(1 for row in rows if row_budget_axis(row, cap_turns)),
        "completion_cap_rate": round(hits[BUDGET_AXIS_COMPLETION] / n, 4) if n else None,
        "turn_cap_rate": round(hits[BUDGET_AXIS_TURN] / n, 4) if n else None,
        "repeat_call_cap_rate": round(hits[BUDGET_AXIS_REPEAT_CALL] / n, 4) if n else None,
    }


def _mean(rows: list[dict], field: str) -> float | None:
    vals = [r.get(field) for r in rows if isinstance(r.get(field), (int, float))]
    return round(statistics.fmean(vals), 4) if vals else None


def row_policy(rows: list[dict], conditions, cap_turns: int | None = None,
               comparisons=None) -> dict:
    """Per-arm row classes, both 口径, and which comparisons §0.6.3 permits.

    `comparisons` is an iterable of (baseline_condition, treatment_condition) pairs.
    A comparison is claimable only when BOTH arms keep endpoint_failure <= 10% AND
    cap_truncated <= 10%, and the `analysable` and `intention_to_treat` views do not
    point in opposite directions.
    """
    per_arm: dict[str, dict] = {}
    exact_rates = {}
    for cond in conditions:
        sub = [r for r in rows if r.get("condition") == cond]
        n = len(sub)
        classes = [row_class(r, cap_turns) for r in sub]
        an = [r for r, c in zip(sub, classes) if c == "analysable"]
        ep = sum(1 for c in classes if c == "endpoint_failure")
        cp = sum(1 for c in classes if c == "cap_truncated")
        axes = _budget_axis_counts(sub, cap_turns)
        if axes["union"] != cp:
            raise ValueError("row_budget_axis and row_class disagree on the cap union")
        api_err = sum(1 for r in sub if r.get("api_error"))
        successes = sum(1 for r in an if r.get("success"))
        exact_rates[cond] = (Fraction(successes, len(an)) if an else Fraction(0),
                             Fraction(successes, n) if n else Fraction(0))
        per_arm[cond] = {
            "n": n,
            "endpoint_failure": ep,
            "cap_truncated": cp,
            "analysable": len(an),
            "api_error": api_err,
            "endpoint_rate": round(ep / n, 4) if n else None,
            "cap_truncated_rate": round(cp / n, 4) if n else None,
            # §0.6.8 dual-budget decomposition; `union` must equal `cap_truncated`
            "budget_axes": axes,
            "analysable_rate": round(len(an) / n, 4) if n else None,
            # the two 口径 that §0.6.2 requires side by side, never one alone
            "success_analysable": (round(sum(1 for r in an if r.get("success")) / len(an), 4)
                                   if an else None),
            "success_intention_to_treat": (round(sum(1 for r, kind in zip(sub, classes)
                                                        if kind == "analysable" and r.get("success")) / n, 4)
                                           if n else None),
            "mean_tool_calls_analysable": _mean(an, "tool_calls"),
            "mean_tool_calls_intention_to_treat": _mean(sub, "tool_calls"),
            "mean_observation_tokens_analysable": _mean(an, "observation_tokens"),
            "mean_observation_tokens_intention_to_treat": _mean(sub, "observation_tokens"),
        }

    out_comparisons: dict[str, dict] = {}
    for base, treat in (comparisons or []):
        b, t = per_arm.get(base), per_arm.get(treat)
        if not b or not t:
            continue
        limit = Fraction(str(POLICY_EXCLUSION_LIMIT))
        rates_ok = all(
            arm["n"] > 0
            and arm["endpoint_failure"] * limit.denominator <= arm["n"] * limit.numerator
            and arm["cap_truncated"] * limit.denominator <= arm["n"] * limit.numerator
            for arm in (b, t)
        )
        d_an = exact_rates[treat][0] - exact_rates[base][0]
        d_itt = exact_rates[treat][1] - exact_rates[base][1]
        # Disagreement means STRICTLY opposite directions; a zero delta is not a
        # disagreement (it cannot favour either row set).
        sign_disagrees = (d_an > 0 > d_itt) or (d_an < 0 < d_itt)
        reasons = []
        repeat_limits = [r.get('repeat_call_limit', 0) for r in rows if r.get('condition') in (base, treat)]
        if (any(type(n) is not int or n < 0 or n == 1 for n in repeat_limits)
                or len(set(repeat_limits)) > 1
                or any(r.get('stop_reason') == 'repeat_call_limit' and not r.get('repeat_call_limit', 0)
                       for r in rows if r.get('condition') in (base, treat))):
            reasons.append('repeat_call_policy_mismatch')
        if not rates_ok:
            reasons.append("exclusion_rate_above_10pct")
        if sign_disagrees:
            reasons.append("analysable_and_itt_disagree_in_sign")
        if b["api_error"] or t["api_error"]:
            reasons.append("api_error_rows_present")
        if any(r.get('recovery_uncertain') for r in rows if r.get('condition') in (base,treat)):
            reasons.append('interrupted_attempt_outcome_unknown')
        out_comparisons[f"{treat}_vs_{base}"] = {
            "baseline": base, "treatment": treat,
            "rates_ok": rates_ok,
            # §0.6.8: each comparison carries both arms' axis split next to its ruling
            "cap_truncated_axes": {base: b["budget_axes"], treat: t["budget_axes"]},
            "success_delta_analysable": round(float(d_an), 4),
            "success_delta_intention_to_treat": round(float(d_itt), 4),
            "sign_agreement": not sign_disagrees,
            "claimable": not reasons,
            "policy_blocked_reasons": reasons,
        }

    return {
        "rule": "docs/acceptance-criteria.md §0.6 (pre-registered)",
        "exclusion_limit": POLICY_EXCLUSION_LIMIT,
        "primary": "analysable",
        "must_also_report": "intention_to_treat",
        "per_arm": per_arm,
        "comparisons": out_comparisons,
    }


def recompute_aggregate(rows: list[dict]) -> dict[str, dict]:
    """Recompute every condition present, so a new arm cannot slip in unchecked."""
    out: dict[str, dict] = {}
    for cond in sorted({r.get("condition") for r in rows if r.get("condition")}):
        sub = [r for r in rows if r.get("condition") == cond]
        scored = [r for r in sub if r.get("success") is not None]
        crashes = [r for r in sub if is_harness_crash(r)]
        clean = [r for r in scored if not is_harness_crash(r)]
        out[cond] = {
            "n_rows": len(sub),
            "n_scored": len(scored),
            "n_unverified": len(sub) - len(scored),
            "successes": sum(1 for r in scored if r.get("success")),
            "mean_tool_calls": round(statistics.fmean([r["tool_calls"] for r in sub]), 4) if sub else None,
            "mean_observation_tokens": round(statistics.fmean(
                [r["observation_tokens"] for r in sub]), 4) if sub else None,
            # Harness faults are not the model's doing; they are reported separately so
            # a crash can never be averaged in as an ordinary failure.
            "harness_crash": len(crashes),
            "successes_excluding_harness_crash": sum(1 for r in clean if r.get("success")),
            "n_scored_excluding_harness_crash": len(clean),
        }
    return out


def analyse(payload: dict, label: str) -> dict:
    rows = payload.get("rows", [])
    live_config = payload.get("live_config", {})
    recomputed = recompute_aggregate(rows)

    # Cross-check the stored aggregate against rows[]: a stale or hand-edited
    # aggregate must not survive as evidence.
    stored_mismatch: list[str] = []
    for agg in payload.get("aggregate", {}).get("aggregates", []):
        cond = agg.get("condition")
        rec = recomputed.get(cond)
        if not rec:
            continue
        checks = {
            "tasks": rec["n_rows"],
            "success_rate": round(rec["successes"] / rec["n_scored"], 4) if rec["n_scored"] else None,
            "avg_tool_calls": rec["mean_tool_calls"],
            "avg_observation_tokens": rec["mean_observation_tokens"],
        }
        for key, value in checks.items():
            if value is None:
                continue
            stored = agg.get(key)
            if stored is None:
                continue
            if isinstance(value, float):
                # The artifact rounds its aggregates for display (e.g. 4.07), so
                # compare at the precision the stored value was written with
                # instead of flagging a 0.003 rounding difference as drift.
                decimals = len(str(stored).split(".")[1]) if "." in str(stored) else 0
                if round(value, decimals) != round(float(stored), decimals):
                    stored_mismatch.append(f"{cond}.{key}: stored={stored} recomputed={value}")
            elif stored != value:
                stored_mismatch.append(f"{cond}.{key}: stored={stored} recomputed={value}")

    a = recomputed["raw_shell"]
    d = recomputed["verseshell_aci"]

    rates = {}
    for name, rec in (("raw_shell", a), ("verseshell_aci", d)):
        n = rec["n_scored"]
        low, high = wilson(rec["successes"], n)
        rates[name] = {
            "successes": rec["successes"],
            "n_scored": n,
            "n_unverified": rec["n_unverified"],
            "success_rate": round(rec["successes"] / n, 4) if n else None,
            "wilson_ci95": [round(low, 4), round(high, 4)],
        }

    z_test = two_proportion_z(a["successes"], a["n_scored"], d["successes"], d["n_scored"])

    # Paired view: match on (task_id, seed) — the protocol's own unit.
    def key(r: dict) -> tuple:
        return (r.get("task_id"), r.get("seed"), r.get("run_index"))

    by_cell: dict[tuple, dict] = {}
    for r in rows:
        by_cell.setdefault(key(r), {})[r.get("condition")] = r
    paired_items = sorted((k, c) for k, c in by_cell.items()
                          if "raw_shell" in c and "verseshell_aci" in c)
    # Cluster id for the task-level bootstrap. The three seeds of one task are
    # correlated (ICC 0.28-0.56), so resampling rows understates the interval; the
    # published interval resamples whole tasks.
    cluster_keys = [k[0] for k, _ in paired_items]
    paired_cells = [c for _, c in paired_items]

    def usage(row: dict) -> float:
        return reported_usage(row)

    succ_pairs = [(1.0 if c["raw_shell"].get("success") else 0.0,
                   1.0 if c["verseshell_aci"].get("success") else 0.0) for c in paired_cells]
    tool_pairs = [(float(c["raw_shell"]["tool_calls"]), float(c["verseshell_aci"]["tool_calls"]))
                  for c in paired_cells]
    tok_pairs = [(float(c["raw_shell"]["observation_tokens"]),
                  float(c["verseshell_aci"]["observation_tokens"])) for c in paired_cells]
    usage_pairs = [(usage(c["raw_shell"]), usage(c["verseshell_aci"])) for c in paired_cells]
    prompt_pairs = [(reported_usage(c["raw_shell"], "llm_prompt_tokens"),
                     reported_usage(c["verseshell_aci"], "llm_prompt_tokens"))
                    for c in paired_cells]
    completion_pairs = [(reported_usage(c["raw_shell"], "llm_completion_tokens"),
                         reported_usage(c["verseshell_aci"], "llm_completion_tokens"))
                        for c in paired_cells]

    paired = {
        "success_rate": paired_metric(succ_pairs, "success_rate"),
        "tool_calls": paired_metric(tool_pairs, "tool_calls"),
        "observation_tokens": paired_metric(tok_pairs, "observation_tokens"),
    }
    # McNemar on the discordant success pairs — the right test for a paired
    # binary outcome, and far more powerful than the unpaired z-test here.
    both_ok = sum(1 for x, y in succ_pairs if x and y)
    only_a = sum(1 for x, y in succ_pairs if x and not y)
    only_d = sum(1 for x, y in succ_pairs if y and not x)
    neither = sum(1 for x, y in succ_pairs if not x and not y)
    mcnemar = {"both_pass": both_ok, "only_A": only_a, "only_D": only_d, "neither": neither}
    n_disc = only_a + only_d
    if n_disc:
        # exact binomial two-sided p under p=0.5
        k = min(only_a, only_d)
        p_exact = min(1.0, 2 * sum(math.comb(n_disc, i) for i in range(k + 1)) / (2 ** n_disc))
        mcnemar["p_value_exact"] = round(p_exact, 6)
    else:
        mcnemar["p_value_exact"] = None

    free_text = []
    if z_test["p_value"] is not None and z_test["p_value"] > 0.05:
        free_text.append(
            f"unpaired success-rate difference is NOT significant at alpha=0.05 "
            f"(z={z_test['z']}, p={z_test['p_value']})")
    if mcnemar.get("p_value_exact") is not None and mcnemar["p_value_exact"] > 0.05:
        free_text.append(
            f"paired (McNemar) success difference is NOT significant "
            f"(discordant {only_a} A-only vs {only_d} D-only, p={mcnemar['p_value_exact']})")

    return {
        "artifact": label,
        "mode": payload.get("mode"),
        "task_set_version": payload.get("task_set_version"),
        "generated_at": payload.get("generated_at"),
        "source_rows_fingerprint": rows_fingerprint(rows),
        "source_provenance": {
            "generated_at": payload.get("generated_at"),
            "git_rev": payload.get("git_rev"),
            "task_set_version": payload.get("task_set_version"),
            "evidence_fingerprint": (payload.get("evidence") or {}).get("fingerprint"),
            "merged_from": live_config.get("merged_from", []),
        },
        "model": live_config.get("model"),
        "seeds": live_config.get("seeds") or ([live_config.get("seed")] if live_config.get("seed") is not None else []),
        "repeat": live_config.get("repeat"),
        "n_rows": len(rows),
        "recomputed_aggregate": recomputed,
        "stored_aggregate_mismatches": stored_mismatch,
        "success_rate": rates,
        "unpaired_z_test_success": z_test,
        "paired_success_mcnemar": mcnemar,
        "paired": paired,
        "ratio_bootstrap": {
            "tool_call_ratio": ratio_bootstrap(tool_pairs, kind="tool_call_ratio",
                                               keys=cluster_keys),
            "observation_token_ratio": ratio_bootstrap(tok_pairs, kind="observation_token_ratio",
                                                       keys=cluster_keys),
            "usage_token_ratio": ratio_bootstrap(usage_pairs, kind="usage_token_ratio",
                                                 keys=cluster_keys),
            "prompt_token_ratio": ratio_bootstrap(prompt_pairs, kind="prompt_token_ratio",
                                                  keys=cluster_keys),
            "completion_token_ratio": ratio_bootstrap(completion_pairs,
                                                      kind="completion_token_ratio",
                                                      keys=cluster_keys),
        },
        # Per-ratio caliber: what each published ratio's two sums actually count.
        # The bootstrap itself is caliber-agnostic; these labels are what the
        # artifacts must be read with (`bootstrap_unit: task` = task-clustered).
        "ratio_caliber": {
            "tool_call_ratio": {
                "caliber": "count_ratio",
                "note": "ratio of tool-CALL COUNTS (raw_shell vs verseshell_aci): not tokens, "
                        "not usage, not currency",
            },
            "observation_token_ratio": {
                "caliber": "observation_proxy_estimate_tokens",
                "note": "ratio of `estimate_tokens(text) = max(1, len(text)//4)` accumulated over "
                        "the delivered observation text. This is a PROXY: NOT endpoint usage, NOT "
                        "the evaluated model's own tokenizer and NOT a money cost",
            },
            "usage_token_ratio": {
                "caliber": "endpoint_usage_total",
                "note": "ratio of endpoint-reported `usage` summed over observed requests in usage-eligible pairs "
                        "(llm_prompt_tokens + llm_completion_tokens): system prompt + tool schemas "
                        "+ re-sent history + reasoning per turn. It is NOT the size of one system "
                        "prompt or one tool-schema payload, and without price/cache rules it is NOT "
                        "a money cost",
            },
            "prompt_token_ratio": {
                "caliber": "endpoint_usage_prompt",
                "note": "ratio of endpoint-reported `llm_prompt_tokens` (input usage accumulated "
                        "over observed requests in usage-eligible pairs): NOT the system-prompt/schema size of one request and "
                        "NOT currency",
            },
            "completion_token_ratio": {
                "caliber": "endpoint_usage_completion",
                "note": "ratio of endpoint-reported `llm_completion_tokens` (output usage). The "
                        "reasoning billing boundary is unconfirmed, so it is NOT the visible "
                        "answer's character count and NOT currency",
            },
        },
        "real_tokenizer_note": "Unknown usage is excluded, never zero-imputed; candidate_pairs, n_pairs and "
                               "excluded_nonfinite_pairs describe the cost denominator, not the score denominator. "
                               "No provider invoice is reconciled. Caliber: see `ratio_caliber`. `observation_token_ratio` is "
                               "PROXY-caliber — max(1, len(text)//4) over the delivered "
                               "observation text. `usage_token_ratio` / `prompt_token_ratio` / "
                               "`completion_token_ratio` are ENDPOINT-USAGE caliber: the endpoint's "
                               "reported `usage` accumulated over observed requests in usage-eligible pairs (system prompt + "
                               "tool schemas + re-sent history + reasoning). They are therefore "
                               "broader than observation_tokens, are NOT the size of one system "
                               "prompt or one tool-schema payload, and are NOT a money cost; the "
                               "usage reading governs when the two disagree in direction "
                               "(docs/acceptance-criteria.md §4.2)",
        "tool_calls": {"raw_shell": mean_sd([float(r["tool_calls"]) for r in rows if r["condition"] == "raw_shell"]),
                       "verseshell_aci": mean_sd([float(r["tool_calls"]) for r in rows if r["condition"] == "verseshell_aci"])},
        "observation_tokens": {"raw_shell": mean_sd([float(r["observation_tokens"]) for r in rows if r["condition"] == "raw_shell"]),
                               "verseshell_aci": mean_sd([float(r["observation_tokens"]) for r in rows if r["condition"] == "verseshell_aci"])},
        "significance_notes": free_text,
        "uncertainty_scope": {
            "independent_complete_run_variance_included": False,
            "ratio_interval": "task-clustered only",
            "other_intervals": "Wilson/paired-row t assumptions; not independent collection replicates",
            "all_row_success_is_not_policy_itt": True,
            "repeated_run_analysis": "tools/repeated_run_uncertainty.py requires a separately collected complete-run manifest",
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "live_uncertainty.json")
    ap.add_argument("--with-arm", type=Path,
                    default=ROOT / "bench/aci/results/latest_live.json")
    ap.add_argument("--without-arm", type=Path,
                    default=ROOT / "bench/aci/results/live_ab_without_read_files.json")
    args = ap.parse_args(argv)

    arms = []
    for path, label in ((args.with_arm, "with_read_files"), (args.without_arm, "without_read_files")):
        if not path.exists():
            print(f"WARNING: missing {path}", file=sys.stderr)
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        arms.append(analyse(payload, label))

    if not arms:
        print("ERROR: no live artifact found", file=sys.stderr)
        return 2

    payload = {
        "schema": "verseshell.aci_live_uncertainty/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "independent_complete_run_variance_included": False,
            "success_interval": "Wilson score interval (95%); no independent-run component",
            "unpaired_test": "two-proportion pooled z-test, two-sided",
            "paired_test": "McNemar exact binomial on discordant success pairs; "
                           "paired t interval for continuous metrics",
            "paired_unit": "(task_id, seed, run_index)",
            "ratio_bootstrap_unit": "task — whole tasks are resampled, because the three "
                                    "seeds of one task are correlated (ICC 0.28-0.56) and a "
                                    "row-level resample is systematically narrower. The row "
                                    "interval is still reported as `bootstrap_ci95_row`",
            "real_tokenizer": "endpoint `usage` accumulated over every turn, published as "
                              "usage_token_ratio / prompt_token_ratio / completion_token_ratio",
            "power_target": "0.80 at alpha=0.05 two-sided",
        },
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
        "arms": arms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    for arm in arms:
        sr = arm["success_rate"]
        print(f"\n[{arm['artifact']}] n_rows={arm['n_rows']} model={arm['model']} seeds={arm['seeds']}")
        for cond in ("raw_shell", "verseshell_aci"):
            r = sr[cond]
            print(f"  {cond:<15} success={r['success_rate']} ({r['successes']}/{r['n_scored']}) "
                  f"Wilson95={r['wilson_ci95']} unverified={r['n_unverified']}")
        z = arm["unpaired_z_test_success"]
        print(f"  unpaired z={z['z']} p={z['p_value']}")
        mc = arm["paired_success_mcnemar"]
        print(f"  McNemar only_A={mc['only_A']} only_D={mc['only_D']} p={mc['p_value_exact']}")
        for metric in ("success_rate", "tool_calls", "observation_tokens"):
            p = arm["paired"][metric]
            print(f"  paired {metric:<20} delta={p.get('mean_delta_D_minus_A')} "
                  f"sd={p.get('sd_of_deltas')} ci95={p.get('paired_ci95')} "
                  f"n_for_80%={p.get('n_for_80pct_power')}")
        for name, b in arm["ratio_bootstrap"].items():
            extra = ""
            if b.get("frozen_target") is not None:
                extra = f" P(<{b['frozen_target']})={b.get('prob_ratio_below_frozen_target')}"
            print(f"  bootstrap {name:<24} point={b.get('point_estimate')} "
                  f"ci95={b.get('bootstrap_ci95')} [{b.get('bootstrap_unit')}]{extra} "
                  f"row_ci95={b.get('bootstrap_ci95_row')}")
        if arm["stored_aggregate_mismatches"]:
            print(f"  !! stored aggregate disagrees with rows: {arm['stored_aggregate_mismatches']}")
    return 0


def comparison_eligibility(rows, baseline, cap_turns=None, *, partial=False, synthetic=False):
    """Shared data prerequisites, NOT a significance or product-acceptance verdict."""
    conditions = (baseline, 'verseshell_aci')
    rows = [r for r in rows if r.get('condition') in conditions]
    policy = row_policy(rows, conditions, cap_turns, [(baseline, 'verseshell_aci')])
    comparison = policy['comparisons']['verseshell_aci_vs_' + baseline]
    reasons = list(comparison['policy_blocked_reasons'])
    if partial:
        reasons.append('partial_artifact')
    if synthetic:
        reasons.append('synthetic_test_only')
    unknown = sum(type(r.get('success')) is not bool for r in rows)
    incomplete = sum(bool(usage_exclusion_reasons(r)) for r in rows)
    if unknown:
        reasons.append('unknown_scoring_rows')
    if incomplete:
        reasons.append('incomplete_usage_rows')
    keys = [[(r.get('task_id'), r.get('seed'), r.get('run_index'),
              r.get('prompt_variant', 'baseline'), r.get('model', 'live'))
             for r in rows if r.get('condition') == condition] for condition in conditions]
    if (not all(keys) or set(keys[0]) != set(keys[1])
            or any(len(k) != len(set(k)) for k in keys)):
        reasons.append('incomplete_or_duplicate_pairs')
    return {'row_policy_eligible': comparison['claimable'],
            'data_eligible': not reasons, 'policy_blocked_reasons': reasons,
            'unknown_scoring_rows': unknown, 'incomplete_usage_rows': incomplete,
            'row_policy': policy}


def single_collection_verdict(rows, baseline, cap_turns=None, *, partial=False, synthetic=False):
    """A collection can never substitute for the frozen repeated-study evaluator.

    Even a complete, eligible row set has no evaluated family or independent-run
    evidence here. Keep the old boolean fail-closed; retain the old OR separately.
    """
    result = comparison_eligibility(rows, baseline, cap_turns, partial=partial, synthetic=synthetic)
    return {**result, 'acceptance_scope': 'single_collection_diagnostic',
            'claimable': False, 'meets_acceptance': False,
            'policy_blocked_reasons': result['policy_blocked_reasons'] + [
                'complete_repeated_study_not_evaluated', 'frozen_family_inference_not_evaluated']}


if __name__ == "__main__":
    sys.exit(main())
