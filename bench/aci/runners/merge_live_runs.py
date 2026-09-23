#!/usr/bin/env python3
"""Merge repeated live A/B runs into one results artifact.

The live protocol is N invocations of `live_agent_loop.py` (one per seed) whose
rows are concatenated. That merge used to be done by hand, which is exactly how a
run with an upstream 500 can slip into an average as a "0 tools / 0 tokens" data
point. This script refuses to do that: any row carrying `api_error` aborts the
merge with exit code 2, and the caller re-runs the failing (task, condition, seed)
cells before merging again.

Usage:
    python bench/aci/runners/merge_live_runs.py --out bench/aci/results/latest_live.json \
        bench/aci/results/tf45/with_seed42.json \
        bench/aci/results/tf45/with_seed43.json \
        bench/aci/results/tf45/with_seed44.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))
from live_agent_loop import (  # noqa: E402
    aggregate,
    compare_a_vs_d,
    current_git_rev,
    evidence_fingerprint,
    EVIDENCE_GLOBS,
    RESULTS,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-api-errors", action="store_true",
                    help="merge anyway (the result must then be labelled as partial)")
    args = ap.parse_args(argv)

    payloads = []
    for path in args.inputs:
        if not path.exists():
            print(f"ERROR: missing input {path}", file=sys.stderr)
            return 2
        payloads.append((path, json.loads(path.read_text(encoding="utf-8-sig"))))

    rows: list[dict] = []
    bad: list[str] = []
    seeds: list[int] = []
    for path, payload in payloads:
        cfg = payload.get("live_config", {})
        seed = cfg.get("seed")
        if seed is not None:
            seeds.append(seed)
        for row in payload.get("rows", []):
            row = dict(row)
            row["source_run"] = path.name
            row["seed"] = seed
            if row.get("api_error"):
                bad.append(f"{path.name}:{row.get('task_id')}:{row.get('condition')}:"
                           f"{row.get('run_index')}")
            rows.append(row)

    if bad and not args.allow_api_errors:
        print(f"ERROR: {len(bad)} row(s) carry api_error; refusing to merge.", file=sys.stderr)
        for item in bad[:40]:
            print(f"  {item}", file=sys.stderr)
        print("Re-run those (task, condition, seed) cells and merge again.", file=sys.stderr)
        return 2

    first = payloads[0][1]
    live_config = dict(first.get("live_config", {}))
    live_config["seeds"] = sorted(set(seeds))
    live_config["repeat"] = len(payloads)
    live_config["merged_from"] = [p.name for p, _ in payloads]
    if bad:
        live_config["api_error_rows"] = len(bad)

    payload = {
        "schema": first.get("schema", "verseshell.aci_bench.results/v1"),
        "task_set_version": first.get("task_set_version"),
        "seed": first.get("seed"),
        "mode": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": current_git_rev(),
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "live_config": live_config,
        "rows": rows,
        "aggregate": aggregate(rows),
        "comparison": compare_a_vs_d(rows),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"merged {len(payloads)} runs -> {len(rows)} rows -> {args.out}")
    print(f"  seeds={live_config['seeds']} api_error_rows={live_config.get('api_error_rows', 0)}")
    for row in payload["aggregate"]["aggregates"]:
        print(f"  {row['condition']:<16} n={row['tasks']:<3} success={row['success_rate']} "
              f"tools={row['avg_tool_calls']} obs_tok={row['avg_observation_tokens']}")
    for cmp_ in payload["comparison"]["comparisons"]:
        print(f"  D/A tools={cmp_['tool_call_ratio_D_over_A']} "
              f"tokens={cmp_['token_ratio_D_over_A']} accept={cmp_['meets_acceptance']}")

    if args.out.resolve() == (RESULTS / "latest_live.json").resolve():
        write_report(payload, RESULTS / "live_REPORT.md")
        print(f"  report -> {RESULTS / 'live_REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
