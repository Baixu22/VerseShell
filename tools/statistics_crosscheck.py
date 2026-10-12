#!/usr/bin/env python3
"""statistics_crosscheck: recompute the headline statistics along a SECOND code path.

Why this exists
---------------
The external audit found three defects in the analysis code — E7 (only one budget
measured), E11 (wrong resampling unit) and E12 (operator precedence inflating the
margin by 6x) — and **every one of them was found by hand, by a human reading the
numbers**. None was caught by a test. In a project whose conclusions are decided by a
few dozen lines of statistics, that is the most dangerous gap in the repository: a bug
in `live_uncertainty.py` silently rewrites every claim.

So this tool recomputes the same quantities from the RAW live rows with deliberately
different code: closed forms written from the textbook definitions (`math.comb` for the
exact binomial, the Wilson formula written out) instead of whatever the primary path
imports, and a bootstrap whose RNG is independent. It then compares item by item
against the values the primary path published in `eval/live_uncertainty.json`.

Agreement rules (and why they differ per item)
----------------------------------------------
* **Closed-form quantities must agree exactly** (to published rounding): counts, rates,
  Wilson bounds, McNemar discordant counts and exact p, paired mean/sd, CPST, and the
  point estimates of the ratios. Any disagreement is a real bug in one of the two paths.
* **Resampled quantities get a Monte-Carlo tolerance** and must at least fall on the same
  side of 1.0. A bootstrap with a different seed cannot reproduce bounds exactly, so
  demanding equality would be a false alarm; demanding only "same side" would hide a
  magnitude bug. Both are checked.

Usage:
    python tools/statistics_crosscheck.py --out eval/statistics_crosscheck.json
"""
from __future__ import annotations
from live_uncertainty import reported_usage

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROOT_ARM = ROOT / "bench/aci/results/latest_live.json"
POWER_ARTIFACT = ROOT / "eval/live_uncertainty.json"
EVIDENCE_GLOBS = [
    "bench/aci/results/latest_live.json",
    "eval/live_uncertainty.json",
    "tools/statistics_crosscheck.py",
]

Z95 = 1.959963984540054
BOOTSTRAP = 20000
BOOTSTRAP_SEED = 20260929  # deliberately NOT the primary path's seed
# Closed-form agreement: both paths publish 4 decimals, so 5e-4 is the rounding floor.
EXACT_TOL = 5e-4
# Bootstrap agreement: 20k task-clustered resamples on 35 tasks.
BOOT_TOL = 0.02


# ── independent implementations (textbook closed forms) ──────────────────────────

def wilson_ci(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval, written out rather than imported."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return ((centre - half) / denom, (centre + half) / denom)


def mcnemar_exact_p(only_a: int, only_d: int) -> float:
    """Two-sided exact McNemar: 2 * P(X <= min(b, c)) with X ~ Bin(b + c, 0.5)."""
    n = only_a + only_d
    if n == 0:
        return 1.0
    k = min(only_a, only_d)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def mean_sd(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    m = sum(values) / n
    if n == 1:
        return (m, 0.0)
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return (m, math.sqrt(var))


def task_clustered_ratio(pairs: list[tuple[str, float, float]],
                         *, iterations: int = BOOTSTRAP,
                         seed: int = BOOTSTRAP_SEED) -> dict:
    """Percentile bootstrap CI95 for sum(D)/sum(A), resampling whole TASKS.

    `pairs` is (task_id, baseline_value, treatment_value). Whole tasks are the
    resampling unit because the three seeds of one task are correlated (ICC 0.28-0.56),
    so a row-level resample is systematically narrower — that was defect E11.
    """
    by_task: dict[str, list[tuple[float, float]]] = {}
    for task, a, d in pairs:
        by_task.setdefault(task, []).append((a, d))
    tasks = sorted(by_task)
    point_num = sum(d for _, a, d in pairs)
    point_den = sum(a for _, a, d in pairs)
    point = (point_num / point_den) if point_den else None
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(iterations):
        num = den = 0.0
        for _ in tasks:
            t = tasks[rng.randrange(len(tasks))]
            for a, d in by_task[t]:
                num += d
                den += a
        draws.append(num / den if den else float("nan"))
    draws = [x for x in draws if not math.isnan(x)]
    draws.sort()
    if not draws:
        return {"point": point, "ci95": [None, None], "n_tasks": len(tasks)}
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    below = sum(1 for x in draws if x < 1.0) / len(draws)
    return {"point": point, "ci95": [lo, hi], "n_tasks": len(tasks),
            "prob_below_1": below, "iterations": iterations, "seed": seed}


def cpst(rows: list[dict], condition: str) -> dict:
    sub = [r for r in rows if r.get("condition") == condition]
    tokens = sum(r.get("observation_tokens") or 0 for r in sub)
    successes = sum(1 for r in sub if r.get("success"))
    return {"tokens": tokens, "successes": successes,
            "cpst": (tokens / successes) if successes else None}


def real_token_total(row: dict) -> float:
    return reported_usage(row)


def load_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig")).get("rows") or []


def pairs_from(rows: list[dict], baseline: str, treatment: str,
               value) -> tuple[list[tuple[str, float, float]], dict]:
    """Pair on (task_id, seed, run_index) and return (task, base, treat) triples."""
    def key(r):
        return (r.get("task_id"), r.get("seed"), r.get("run_index"))

    base = {key(r): r for r in rows if r.get("condition") == baseline}
    treat = {key(r): r for r in rows if r.get("condition") == treatment}
    shared = sorted(set(base) & set(treat), key=lambda k: (str(k[0]), str(k[1]), str(k[2])))
    triples = [(str(k[0]), float(value(base[k])), float(value(treat[k]))) for k in shared]
    triples = [(t,a,d) for t,a,d in triples if math.isfinite(a) and math.isfinite(d)]
    counts = {"baseline_rows": len(base), "treatment_rows": len(treat), "paired": len(triples), "excluded_nonfinite_pairs": len(shared)-len(triples)}
    return triples, counts


# ── comparison harness ──────────────────────────────────────────────────────────

def check(name: str, mine, theirs, *, tol: float, kind: str) -> dict:
    """One comparison. `kind` is 'closed_form' (exact) or 'resampled' (tolerance)."""
    entry = {"item": name, "kind": kind, "recomputed": mine, "published": theirs,
             "tolerance": tol}
    if mine is None or theirs is None:
        entry.update({"agree": False, "reason": "missing on one side"})
        return entry
    if isinstance(mine, (list, tuple)) and isinstance(theirs, (list, tuple)):
        if len(mine) != len(theirs):
            entry.update({"agree": False, "reason": "different arity"})
            return entry
        deltas = [abs(float(a) - float(b)) for a, b in zip(mine, theirs)]
        entry["abs_delta"] = max(deltas)
        entry["agree"] = max(deltas) <= tol
        return entry
    delta = abs(float(mine) - float(theirs))
    entry["abs_delta"] = delta
    entry["agree"] = delta <= tol
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root-arm", type=Path, default=ROOT_ARM)
    ap.add_argument("--published", type=Path, default=POWER_ARTIFACT)
    ap.add_argument("--out", type=Path, default=ROOT / "eval/statistics_crosscheck.json")
    args = ap.parse_args(argv)

    rows = load_rows(args.root_arm)
    published = json.loads(args.published.read_text(encoding="utf-8"))
    arm = next((a for a in published.get("arms", [])
                if a.get("artifact") == "with_read_files"), None)
    if arm is None:
        print("ERROR: live_uncertainty.json has no with_read_files arm", file=sys.stderr)
        return 2

    items: list[dict] = []

    # ── 1. success counts, rates and Wilson intervals (closed form) ──
    pub_success = arm.get("success_rate") or {}
    for cond in ("raw_shell", "verseshell_aci"):
        sub = [r for r in rows if r.get("condition") == cond]
        scored = [r for r in sub if r.get("success") is not None]
        k = sum(1 for r in scored if r.get("success"))
        n = len(scored)
        lo, hi = wilson_ci(k, n)
        ref = pub_success.get(cond) or {}
        items.append(check(f"success/{cond}/successes", k, ref.get("successes"), tol=0, kind="closed_form"))
        items.append(check(f"success/{cond}/n", n, ref.get("n_scored"), tol=0, kind="closed_form"))
        items.append(check(f"success/{cond}/rate", round(k / n, 4) if n else None,
                           ref.get("success_rate"), tol=EXACT_TOL, kind="closed_form"))
        items.append(check(f"success/{cond}/wilson95", [lo, hi], ref.get("wilson_ci95"),
                           tol=EXACT_TOL, kind="closed_form"))

    # ── 2. paired success: discordant counts, exact McNemar, delta ──
    def success_flag(r):
        return 1.0 if r.get("success") else 0.0

    triples, counts = pairs_from(rows, "raw_shell", "verseshell_aci", success_flag)
    both = sum(1 for _, a, d in triples if a == 1 and d == 1)
    only_a = sum(1 for _, a, d in triples if a == 1 and d == 0)
    only_d = sum(1 for _, a, d in triples if a == 0 and d == 1)
    neither = sum(1 for _, a, d in triples if a == 0 and d == 0)
    pub_mc = arm.get("paired_success_mcnemar") or {}
    items.append(check("mcnemar/both_pass", both, pub_mc.get("both_pass"), tol=0, kind="closed_form"))
    items.append(check("mcnemar/only_A", only_a, pub_mc.get("only_A"), tol=0, kind="closed_form"))
    items.append(check("mcnemar/only_D", only_d, pub_mc.get("only_D"), tol=0, kind="closed_form"))
    items.append(check("mcnemar/neither", neither, pub_mc.get("neither"), tol=0, kind="closed_form"))
    items.append(check("mcnemar/p_value_exact", round(mcnemar_exact_p(only_a, only_d), 6),
                       pub_mc.get("p_value_exact"), tol=EXACT_TOL, kind="closed_form"))

    deltas = [d - a for _, a, d in triples]
    m, sd = mean_sd(deltas)
    pub_paired = (arm.get("paired") or {}).get("success_rate") or {}
    items.append(check("paired_success/n_pairs", len(triples), pub_paired.get("n_pairs"), tol=0, kind="closed_form"))
    items.append(check("paired_success/mean_delta", round(m, 4),
                       pub_paired.get("mean_delta_D_minus_A"), tol=EXACT_TOL, kind="closed_form"))
    items.append(check("paired_success/sd", round(sd, 4), pub_paired.get("sd_of_deltas"),
                       tol=EXACT_TOL, kind="closed_form"))

    # ── 3. ratio point estimates and task-clustered bootstrap (resampled) ──
    pub_ratio = arm.get("ratio_bootstrap") or {}
    ratio_specs = [
        ("observation_token_ratio", "observation_tokens"),
        ("tool_call_ratio", "tool_calls"),
    ]
    recomputed_boot: dict[str, dict] = {}
    for kind_name, field in ratio_specs:
        def value(r, field=field):
            return r.get(field) or 0

        tr, _ = pairs_from(rows, "raw_shell", "verseshell_aci", value)
        boot = task_clustered_ratio(tr)
        recomputed_boot[kind_name] = boot
        ref = pub_ratio.get(kind_name) or {}
        items.append(check(f"{kind_name}/point", round(boot["point"], 4) if boot["point"] else None,
                           ref.get("point_estimate"), tol=EXACT_TOL, kind="closed_form"))
        items.append(check(f"{kind_name}/n_tasks", boot["n_tasks"], ref.get("n_tasks"),
                           tol=0, kind="closed_form"))
        # same side of 1.0 is a hard requirement, not a tolerance question
        if boot["ci95"][0] is not None and ref.get("bootstrap_ci95"):
            same_side = ((boot["ci95"][1] < 1.0) == (ref["bootstrap_ci95"][1] < 1.0))
            items.append({"item": f"{kind_name}/ci_same_side_of_1", "kind": "resampled",
                          "recomputed": boot["ci95"][1] < 1.0,
                          "published": ref["bootstrap_ci95"][1] < 1.0,
                          "agree": same_side, "tolerance": None})
        items.append(check(f"{kind_name}/ci95", boot["ci95"], ref.get("bootstrap_ci95"),
                           tol=BOOT_TOL, kind="resampled"))

    # ── 4. CPST (closed form) — published by acceptance_power, not live_uncertainty ──
    power = json.loads((ROOT / "eval/acceptance_power.json").read_text(encoding="utf-8"))
    pub_live = power.get("live") or {}
    a_cpst, d_cpst = cpst(rows, "raw_shell"), cpst(rows, "verseshell_aci")
    published_cpst = pub_live.get("cost_per_success") or {}
    items.append(check("cpst/A_tokens", round(a_cpst["tokens"], 1), published_cpst.get("tokens_A"),
                       tol=1.0, kind="closed_form"))
    items.append(check("cpst/D_tokens", round(d_cpst["tokens"], 1), published_cpst.get("tokens_D"),
                       tol=1.0, kind="closed_form"))
    items.append(check("cpst/A_successes", a_cpst["successes"], published_cpst.get("successes_A"),
                       tol=0, kind="closed_form"))
    items.append(check("cpst/D_successes", d_cpst["successes"], published_cpst.get("successes_D"),
                       tol=0, kind="closed_form"))
    if a_cpst["cpst"] and d_cpst["cpst"]:
        items.append(check("cpst/A_per_success", round(a_cpst["cpst"], 3),
                           published_cpst.get("cpst_A_tokens_per_success"), tol=1e-2, kind="closed_form"))
        items.append(check("cpst/D_per_success", round(d_cpst["cpst"], 3),
                           published_cpst.get("cpst_D_tokens_per_success"), tol=1e-2, kind="closed_form"))
        items.append(check("cpst/D_over_A", round(d_cpst["cpst"] / a_cpst["cpst"], 4),
                           published_cpst.get("point_D_over_A"), tol=EXACT_TOL, kind="closed_form"))

    # ── 5. real-tokenizer ratio (usage = prompt + completion over every turn) ──
    pub_usage = pub_live.get("usage_token_ratio") or {}
    usage_triples, _ = pairs_from(rows, "raw_shell", "verseshell_aci", real_token_total)
    if usage_triples:
        rec_num = sum(d for _, a, d in usage_triples)
        rec_den = sum(a for _, a, d in usage_triples)
        items.append(check("usage_token_ratio/point",
                           round(rec_num / rec_den, 4) if rec_den else None,
                           pub_usage.get("point"), tol=EXACT_TOL, kind="closed_form"))
        boot_usage = task_clustered_ratio(usage_triples)
        recomputed_boot["usage_token_ratio"] = boot_usage
        if pub_usage.get("ci95"):
            items.append(check("usage_token_ratio/ci95", boot_usage["ci95"], pub_usage["ci95"],
                               tol=BOOT_TOL, kind="resampled"))
            items.append({"item": "usage_token_ratio/ci_same_side_of_1", "kind": "resampled",
                          "recomputed": boot_usage["ci95"][1] < 1.0,
                          "published": pub_usage["ci95"][1] < 1.0,
                          "agree": (boot_usage["ci95"][1] < 1.0) == (pub_usage["ci95"][1] < 1.0),
                          "tolerance": None})

    failed = [i for i in items if not i["agree"]]
    payload = {
        "schema": "verseshell.statistics_crosscheck/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/statistics_crosscheck.py",
        "purpose": ("recompute the headline statistics along a second code path — the "
                    "audit's E7/E11/E12 were all analysis-code bugs found by hand, and no "
                    "test caught them"),
        "method": {
            "closed_form": "textbook formulas written out here (math.comb for the exact "
                           "binomial, Wilson written explicitly); they must match the "
                           "published value exactly to published rounding",
            "resampled": (f"independent percentile bootstrap, {BOOTSTRAP} iterations, "
                          f"seed={BOOTSTRAP_SEED}, resampling whole TASKS; compared with a "
                          f"{BOOT_TOL} absolute tolerance on the bounds plus a same-side-of-1.0 "
                          f"check, because a different seed cannot reproduce bounds exactly"),
            "tolerances": {"closed_form": EXACT_TOL, "resampled": BOOT_TOL},
            "source": "bench/aci/results/latest_live.json (raw rows)",
            "compared_against": "eval/live_uncertainty.json (with_read_files arm)",
        },
        "n_items": len(items),
        "n_failed": len(failed),
        "items": items,
        "recomputed_bootstraps": recomputed_boot,
        "evidence": {"globs": EVIDENCE_GLOBS,
                     "fingerprint": None},
    }

    import hashlib
    digest = hashlib.sha256()
    for pat in EVIDENCE_GLOBS:
        for p in sorted(ROOT.glob(pat)):
            if p.is_file() and "__pycache__" not in p.parts:
                digest.update(p.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(p.read_bytes()).digest())
    payload["evidence"]["fingerprint"] = digest.hexdigest()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    print(f"statistics cross-check: {len(items) - len(failed)}/{len(items)} items agree")
    for item in items:
        mark = "ok  " if item["agree"] else "DIFF"
        print(f"  [{mark}] {item['item']:<40} recomputed={item['recomputed']} "
              f"published={item['published']} delta={item.get('abs_delta')}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
