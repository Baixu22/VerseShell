#!/usr/bin/env python3
"""three_arm_report: the pre-registered three-arm report (acceptance criteria §0.5).

Condition D is fine-grained: typed ops are separate calls, while one shell command
can read, edit and build at once. So a turn budget can truncate D far more than A
and turn a measurement of the interface into a measurement of the budget. That
already happened once (`max_turns=8`: D was capped in 64% of runs, A in 0%), so
§0.5 requires:

  * measuring each arm's cap-binding rate BEFORE trusting the comparison;
  * reporting those three rates next to the headline numbers, always;
  * treating >10% on any arm as "the cap is binding";
  * being able to recompute with capped rows excluded.

This tool does exactly that, for both contrasts the design defines:

  D_over_A         D vs the neutral shell baseline (status quo)
  D_over_A_coached D vs the prompt-matched shell baseline (claim C1)

and reports the ratios with bootstrap intervals, plus cap-excluded recomputation.

Usage:
    python tools/three_arm_report.py --out eval/three_arm_report.json
"""
from __future__ import annotations
from live_uncertainty import reported_usage
from report_inputs import select_prompt_variant

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
from live_uncertainty import is_harness_crash, ratio_bootstrap, row_policy, wilson, single_collection_verdict  # noqa: E402

EVIDENCE_GLOBS = [
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "bench/aci/runners/live_agent_loop.py",
    "tools/three_arm_report.py",
    "tools/live_uncertainty.py",
    "tools/report_inputs.py",
]
CAP_BINDING_LIMIT = 0.10


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def arm_stats(rows: list[dict], cond: str, cap: int | None) -> dict:
    sub = [r for r in rows if r.get("condition") == cond]
    if not sub:
        return {"condition": cond, "n": 0}
    scored = [r for r in sub if r.get("success") is not None]
    succ = sum(1 for r in scored if r.get("success"))
    at_cap = [r for r in sub if cap is not None and r.get("turns", 0) >= cap]
    # §3.3 names BOTH budgets: `max_turns` **and** `max_tokens`. Measuring only the turn
    # cap is how the round-12 "cap_ok = true — first time the budget is not binding"
    # claim got published while the completion budget was truncating 8/75 raw_shell rows
    # (11%) and 11/75 raw_shell_coached rows (15%). A turn cut off by `finish_reason ==
    # "length"` emits no tool call and is scored as a plain failure, so the truncation
    # biases against whichever arm hits it — in round 12 that was the raw-shell arms.
    at_token_cap = [r for r in sub if r.get("completion_truncated_turns")]
    turn_rate = len(at_cap) / len(sub)
    token_rate = len(at_token_cap) / len(sub)
    crashes = [r for r in sub if is_harness_crash(r)]
    clean = [r for r in scored if not is_harness_crash(r)]
    clean_succ = sum(1 for r in clean if r.get("success"))
    lo, hi = wilson(succ, len(scored))
    lo_c, hi_c = wilson(clean_succ, len(clean))
    return {
        "condition": cond,
        "n": len(sub),
        "n_scored": len(scored),
        "successes": succ,
        "success_rate": round(succ / len(scored), 4) if scored else None,
        "wilson_ci95": [round(lo, 4), round(hi, 4)],
        "at_cap": len(at_cap),
        "at_cap_rate": round(turn_rate, 4),
        "turn_cap_binding": turn_rate > CAP_BINDING_LIMIT,
        "at_token_cap": len(at_token_cap),
        "at_token_cap_rate": round(token_rate, 4),
        "token_cap_binding": token_rate > CAP_BINDING_LIMIT,
        "cap_binding": (turn_rate > CAP_BINDING_LIMIT) or (token_rate > CAP_BINDING_LIMIT),
        # Harness faults are reported separately from the cap: they are not the
        # model's doing, and leaving them inside the success rate biases whichever
        # arm hits them (in practice the raw-shell arms, because only they decode
        # shell output).
        "harness_crash": len(crashes),
        "harness_crash_rate": round(len(crashes) / len(sub), 4),
        "n_scored_excluding_harness_crash": len(clean),
        "successes_excluding_harness_crash": clean_succ,
        "success_rate_excluding_harness_crash": round(clean_succ / len(clean), 4) if clean else None,
        "wilson_ci95_excluding_harness_crash": [round(lo_c, 4), round(hi_c, 4)],
        "harness_crash_tasks": sorted({r.get("task_id") for r in crashes}),
        "avg_tool_calls": round(statistics.fmean([r["tool_calls"] for r in sub]), 4),
        "avg_observation_tokens": round(statistics.fmean([r["observation_tokens"] for r in sub]), 4),
        "median_observation_tokens": round(statistics.median([r["observation_tokens"] for r in sub]), 4),
    }


def contrast(rows: list[dict], baseline: str, cap: int | None) -> dict:
    """D vs `baseline`, paired on (task, seed, run_index), with and without capped rows."""
    def cells(subset_rows: list[dict]) -> dict:
        by = {}
        for r in subset_rows:
            by.setdefault((r.get("task_id"), r.get("seed"), r.get("run_index")), {})[r["condition"]] = r
        return {k: v for k, v in by.items() if baseline in v and "verseshell_aci" in v}

    def compute(subset_rows: list[dict], label: str) -> dict:
        items = sorted(cells(subset_rows).items())
        if not items:
            return {"subset": label, "n_pairs": 0}
        keys = [k[0] for k, _ in items]
        cs = [c for _, c in items]

        def usage(row: dict) -> float:
            return reported_usage(row)

        tok = [(float(c[baseline]["observation_tokens"]),
                float(c["verseshell_aci"]["observation_tokens"])) for c in cs]
        tools = [(float(c[baseline]["tool_calls"]),
                  float(c["verseshell_aci"]["tool_calls"])) for c in cs]
        # Cost pairs require observed usage in both arms. Received token counters
        # are not an invoice; unknown retries are excluded, never zero-imputed.
        usage_tok = [(usage(c[baseline]), usage(c["verseshell_aci"])) for c in cs]
        prompt_tok = [(reported_usage(c[baseline], "llm_prompt_tokens"),
                       reported_usage(c["verseshell_aci"], "llm_prompt_tokens")) for c in cs]
        completion_tok = [(reported_usage(c[baseline], "llm_completion_tokens"),
                           reported_usage(c["verseshell_aci"], "llm_completion_tokens")) for c in cs]
        only_a = sum(1 for c in cs if c[baseline].get("success") and not c["verseshell_aci"].get("success"))
        only_d = sum(1 for c in cs if c["verseshell_aci"].get("success") and not c[baseline].get("success"))
        sa = sum(1 for c in cs if c[baseline].get("success")) / len(cs)
        sd = sum(1 for c in cs if c["verseshell_aci"].get("success")) / len(cs)
        return {
            "subset": label,
            "n_pairs": len(cs),
            "success_rate_baseline": round(sa, 4),
            "success_rate_D": round(sd, 4),
            "success_delta_D_minus_baseline": round(sd - sa, 4),
            "only_baseline_wins": only_a,
            "only_D_wins": only_d,
            # All intervals below are task-clustered (`bootstrap_unit == "task"`); the
            # row-level interval is kept inside each block as a diagnostic.
            "tool_call_ratio_D_over_baseline": ratio_bootstrap(
                tools, kind="tool_call_ratio", keys=keys),
            "observation_token_ratio_D_over_baseline": ratio_bootstrap(
                tok, kind="observation_token_ratio", keys=keys),
            "usage_token_ratio_D_over_baseline": ratio_bootstrap(
                usage_tok, kind="usage_token_ratio", keys=keys),
            "prompt_token_ratio_D_over_baseline": ratio_bootstrap(
                prompt_tok, kind="prompt_token_ratio", keys=keys),
            "completion_token_ratio_D_over_baseline": ratio_bootstrap(
                completion_tok, kind="completion_token_ratio", keys=keys),
            "ratio_caliber": {
                "tool_call_ratio_D_over_baseline": {
                    "caliber": "count_ratio",
                    "note": "ratio of tool-CALL COUNTS: not tokens, not usage, not currency",
                },
                "observation_token_ratio_D_over_baseline": {
                    "caliber": "observation_proxy_estimate_tokens",
                    "note": "ratio of `estimate_tokens(text) = max(1, len(text)//4)` accumulated "
                            "over the delivered observation text. PROXY-caliber: NOT endpoint "
                            "usage, NOT the evaluated model's own tokenizer and NOT a money cost",
                },
                "usage_token_ratio_D_over_baseline": {
                    "caliber": "endpoint_usage_total",
                    "note": "ratio of endpoint-reported `usage` summed over observed requests in usage-eligible pairs "
                            "(llm_prompt_tokens + llm_completion_tokens). It is NOT the length of "
                            "one system prompt or one tool-schema payload, and without price/cache "
                            "rules it is NOT a money cost",
                },
                "prompt_token_ratio_D_over_baseline": {
                    "caliber": "endpoint_usage_prompt",
                    "note": "ratio of endpoint-reported `llm_prompt_tokens`, the input usage "
                            "accumulated over observed requests in usage-eligible pairs: NOT one request's system-prompt/schema "
                            "size and NOT currency",
                },
                "completion_token_ratio_D_over_baseline": {
                    "caliber": "endpoint_usage_completion",
                    "note": "ratio of endpoint-reported `llm_completion_tokens`. The reasoning "
                            "billing boundary is unconfirmed, so it is NOT the visible answer's "
                            "character count and NOT currency",
                },
            },
            "usage_note": "Unknown usage is excluded, never zero-imputed; candidate_pairs, n_pairs and "
                          "excluded_nonfinite_pairs describe the cost denominator, not the score denominator. "
                          "caliber: see `ratio_caliber`. `usage_*` ratios use the endpoint's "
                          "`usage` field accumulated over observed requests in usage-eligible pairs (system prompt + tool "
                          "schemas + re-sent history + reasoning) — i.e. endpoint-usage caliber, "
                          "NOT the length of one system prompt or one tool-schema payload, and not "
                          "a money cost or a reconciled bill. It is the broader endpoint-usage reading the "
                          "pre-registration requires, so when it disagrees in direction with the "
                          "observation-token proxy it governs (docs/acceptance-criteria.md §4.2), "
                          "while `observation_token_ratio_D_over_baseline` stays proxy-caliber and "
                          "must be quoted as such",
        }

    kept = [r for r in rows if (cap is None or r.get("turns", 0) < cap)
            and not r.get("completion_truncated_turns")]
    no_crash = [r for r in rows if not is_harness_crash(r)]
    return {
        "baseline_condition": baseline,
        "all_rows": compute(rows, "all_rows"),
        "cap_excluded": compute(kept, "no_turn_or_completion_cap"),
        "cap_excluded_dropped": len(cells(rows)) - len(cells(kept)),
        "excluded_count_unit": "paired_cells",
        "harness_crash_excluded": compute(no_crash, "no_harness_crash"),
        "harness_crash_excluded_dropped": len(cells(rows)) - len(cells(no_crash)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-arm", type=Path, default=ROOT / "bench/aci/results/latest_live.json")
    ap.add_argument("--without-arm", type=Path,
                    default=ROOT / "bench/aci/results/live_ab_without_read_files.json")
    ap.add_argument("--out", type=Path, default=ROOT / "eval/three_arm_report.json")
    ap.add_argument('--prompt-variant')
    args = ap.parse_args()

    payload = select_prompt_variant(json.loads(args.with_arm.read_text(encoding="utf-8-sig")), args.prompt_variant)
    rows = payload.get("rows", [])
    cap = (payload.get("live_config") or {}).get("max_turns")

    conditions = sorted({r.get("condition") for r in rows if r.get("condition")})
    arms = {c: arm_stats(rows, c, cap) for c in conditions}
    baselines = [c for c in ("raw_shell", "raw_shell_coached") if c in arms and arms[c]["n"]]
    contrasts = [contrast(rows, b, cap) for b in baselines]

    # §0.6 pre-registered row policy: per-arm row classes, BOTH 口径, and which
    # comparisons the exclusion rule permits. See tools/live_uncertainty.py.
    policy = row_policy(rows, conditions, cap,
                        comparisons=[(b, "verseshell_aci") for b in baselines
                                     if "verseshell_aci" in arms])

    acceptance = {f'verseshell_aci_vs_{base}': single_collection_verdict(
        rows, base, cap, partial=bool(payload.get('partial')),
        synthetic=bool(payload.get('synthetic_test_only'))) for base in baselines}
    binding = [c for c, a in arms.items() if a.get("cap_binding")]
    turn_binding = [c for c, a in arms.items() if a.get("turn_cap_binding")]
    token_binding = [c for c, a in arms.items() if a.get("token_cap_binding")]
    crash_arms = {c: a["harness_crash"] for c, a in arms.items() if a.get("harness_crash")}
    report = {
        "schema": "verseshell.three_arm_report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/three_arm_report.py",
        "source": str(args.with_arm.resolve()),
        "source_arm": args.with_arm.name,
        "max_turns": cap,
        "cap_binding_limit": CAP_BINDING_LIMIT,
        "model": (payload.get("live_config") or {}).get("model"),
        "prompt_variant": (payload.get("live_config") or {}).get("prompt_variant"),
        "interpretation": "Row-policy eligibility is not statistical significance or interface-only "
                          "causality. Historical compact changes D descriptions only. Compare "
                          "baseline and compact_all in separately frozen, matched collections.",
        "task_set_version": payload.get("task_set_version"),
        "arms": arms,
        "contrasts": contrasts,
        "cap_binding_arms": binding,
        "cap_binding_arms_by_turn": turn_binding,
        "cap_binding_arms_by_completion_tokens": token_binding,
        "cap_ok": not binding,
        "harness_crash_arms": crash_arms,
        "harness_crash_total": sum(crash_arms.values()),
        # §0.6: the row set is decided by a pre-registered rule, and BOTH 口径 must be
        # reported. `claimable` here is per-comparison, because truncation is one-sided.
        "row_policy": policy,
        "claimable": False,
        "acceptance_scope": "single_collection_diagnostic",
        "acceptance": acceptance,
        "row_policy_eligible_comparisons": sorted(
            k for k, v in policy["comparisons"].items() if v["claimable"]),
        # Legacy consumer key is fail-closed, not an alias for row eligibility.
        "row_policy_claimable_comparisons": [],
        "row_policy_blocked_comparisons": sorted(
            k for k, v in policy["comparisons"].items() if not v["claimable"]),
        "verdict": (
            f"cap is binding on {', '.join(binding)} "
            f"(max_turns: {', '.join(turn_binding) or 'none'}; "
            f"max_tokens: {', '.join(token_binding) or 'none'}) — the comparison is "
            f"confounded by the budget; raise the binding cap and re-run "
            f"(acceptance criteria §0.5 / brief §3.3, which names BOTH budgets)"
            if binding else
            "no arm exceeds the cap-binding limit on either budget (max_turns or "
            "max_tokens); the comparison is not confounded by the budget"
        ),
        "harness_note": (
            "Harness faults (rows where the runner died before recording any tool result) "
            "are reported per arm and excluded in `harness_crash_excluded`. They are not the "
            "model's doing and they fall only on the arms that decode shell output, so leaving "
            "them inside the success rate biases the comparison."
            if crash_arms else
            "no harness faults detected in this artifact"
        ),
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
                     "input_sha256": {str(args.with_arm): hashlib.sha256(args.with_arm.read_bytes()).hexdigest()}},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    print(f"max_turns = {cap}   (cap-binding limit {CAP_BINDING_LIMIT:.0%})")
    print(f"\n{'arm':<20}{'n':>4}{'turncap':>9}{'tokcap':>8}{'crash':>7}{'succ':>8}{'succ*':>8}"
          f"{'tools':>8}{'obs_tok':>10}")
    for c, a in arms.items():
        print(f"{c:<20}{a['n']:>4}{a['at_cap_rate']:>8.0%}{a['at_token_cap_rate']:>8.0%}"
              f"{a['harness_crash']:>7}"
              f"{a['success_rate']:>8}{a['success_rate_excluding_harness_crash']:>8}"
              f"{a['avg_tool_calls']:>8.2f}{a['avg_observation_tokens']:>10.1f}")
    print("  (turncap = turns >= max_turns; tokcap = finish_reason=='length'; "
          "succ* = success rate with harness-fault rows excluded)")
    print(f"\nverdict: {report['verdict']}")
    # §0.6: both 口径 side by side, plus the per-comparison ruling
    print(f"\n{'arm':<20}{'excl':>8}{'endpoint':>10}{'cap':>7}{'succ_an':>9}{'succ_itt':>10}")
    for c, a in policy["per_arm"].items():
        print(f"{c:<20}{(1 - (a['analysable_rate'] or 0)):>8.1%}"
              f"{a['endpoint_rate']:>10.1%}{a['cap_truncated_rate']:>7.1%}"
              f"{a['success_analysable']:>9}{a['success_intention_to_treat']:>10}")
    print("  (analysable = primary口径; intention_to_treat counts every excluded row as a failure)")
    for name, cmp_ in policy["comparisons"].items():
        print(f"  {name:<34} row_policy_eligible={str(cmp_['claimable']):<5} "
              f"succ_an={cmp_['success_delta_analysable']:+.4f} "
              f"succ_itt={cmp_['success_delta_intention_to_treat']:+.4f} "
              f"sign_ok={cmp_['sign_agreement']} {cmp_['policy_blocked_reasons']}")
    for name, decision in acceptance.items():
        print(f"  {name}: NOT CLAIMABLE {decision['policy_blocked_reasons']}")
    if crash_arms:
        print(f"harness faults: {crash_arms}  → {report['harness_note']}")
    for con in contrasts:
        allr, kept = con["all_rows"], con["cap_excluded"]
        if not allr.get("n_pairs"):
            continue
        tr = allr["observation_token_ratio_D_over_baseline"]
        kr = kept.get("observation_token_ratio_D_over_baseline", {})
        print(f"\nD vs {con['baseline_condition']}:")
        print(f"  success D-A = {allr['success_delta_D_minus_baseline']} "
              f"(only_D_wins={allr['only_D_wins']} vs only_baseline={allr['only_baseline_wins']})")
        print(f"  observations ratio = {tr.get('point_estimate')} "
              f"CI95={tr.get('bootstrap_ci95')} unit={tr.get('bootstrap_unit')} "
              f"(row CI95={tr.get('bootstrap_ci95_row')})")
        ur = allr.get("usage_token_ratio_D_over_baseline", {})
        pr = allr.get("prompt_token_ratio_D_over_baseline", {})
        cr = allr.get("completion_token_ratio_D_over_baseline", {})
        print(f"  real tokens (endpoint usage): total={ur.get('point_estimate')} "
              f"CI95={ur.get('bootstrap_ci95')} | prompt={pr.get('point_estimate')} "
              f"CI95={pr.get('bootstrap_ci95')} | completion={cr.get('point_estimate')} "
              f"CI95={cr.get('bootstrap_ci95')}")
        print(f"  cap-excluded ratio = {kr.get('point_estimate')} CI95={kr.get('bootstrap_ci95')} "
              f"(dropped {con['cap_excluded_dropped']} pairs)")
        ncr = con.get("harness_crash_excluded", {})
        if con.get("harness_crash_excluded_dropped"):
            print(f"  crash-excluded: success D-A = {ncr.get('success_delta_D_minus_baseline')} "
                  f"(only_D_wins={ncr.get('only_D_wins')} vs "
                  f"only_baseline={ncr.get('only_baseline_wins')}), "
                  f"ratio = {ncr.get('observation_token_ratio_D_over_baseline', {}).get('point_estimate')} "
                  f"(dropped {con['harness_crash_excluded_dropped']} pairs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
