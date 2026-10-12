#!/usr/bin/env python3
"""Merge repeated live A/B runs into one results artifact.

The live protocol is N invocations of `live_agent_loop.py` (one per seed) whose
rows are concatenated. That merge used to be done by hand, which is exactly how a
run with an upstream 500 can slip into an average as a "0 tools / 0 tokens" data
point. This script refuses to do that: any row carrying `api_error` aborts the
merge with exit code 2, and the caller re-runs the failing (task, condition, seed)
cells before merging again. With --allow-api-errors, it instead writes an explicitly
partial diagnostic artifact: endpoint failures have success=None, retain raw_success,
and cannot yield an affirmative comparison or pass C35.

Usage:
    python bench/aci/runners/merge_live_runs.py --out bench/aci/results/latest_live.json \
        bench/aci/results/tf45/with_seed42.json \
        bench/aci/results/tf45/with_seed43.json \
        bench/aci/results/tf45/with_seed44.json
"""
from __future__ import annotations

import argparse
import hashlib
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
sys.path.insert(0, str(ROOT / "tools"))
from live_uncertainty import row_class  # noqa: E402
from live_identity import collection_signature, validate_run, validate_rows  # noqa: E402
from live_journal import atomic_json  # noqa: E402


def refresh_summaries(payload: dict) -> None:
    """Keep merger and per-cell checkpoints consistent about partial statistics."""
    rows = payload["rows"]
    payload["aggregate"] = aggregate(rows)
    payload["comparison"] = compare_a_vs_d(rows, context=payload)
    if payload.get("partial") or payload.get('synthetic_test_only'):
        payload["success_rate_scope"] = "verified rows, excluding endpoint failures; not a capability claim"
        payload["partial_reason"] = "partial merge: diagnostics only; C35 requires complete error-free arms"
    else:
        payload.pop("success_rate_scope", None)
        payload.pop("partial_reason", None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-api-errors", action="store_true",
                    help="merge anyway (the result must then be labelled as partial)")
    args = ap.parse_args(argv)

    payloads = []
    source_hashes = {}
    for path in args.inputs:
        if not path.exists():
            print(f"ERROR: missing input {path}", file=sys.stderr)
            return 2
        try:
            if args.out.resolve() == path.resolve() or (args.out.exists() and args.out.samefile(path)):
                raise ValueError("output aliases an input artifact")
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"))
            identity = validate_run(payload, complete=not (args.allow_api_errors or payload.get('partial')))
            if payloads and collection_signature(identity) != collection_signature(payloads[0][1]['run_identity']):
                raise ValueError('different frozen collection/configuration/source')
            payloads.append((path, payload))
            source_hashes[path] = hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'ERROR: {path.name}: {exc}; output preserved', file=sys.stderr)
            return 2

    rows: list[dict] = []
    bad: list[str] = []
    seeds: list[int] = []
    for path, payload in payloads:
        cfg = payload.get("live_config", {})
        seed = cfg.get("seed")
        for row in payload.get("rows", []):
            row = dict(row)
            row.setdefault("source_run", path.name)
            if row.get("seed") is None:
                row["seed"] = seed
            if row.get("seed") is not None:
                seeds.append(row["seed"])
            row["row_class"] = row_class(row, cfg.get("max_turns"))
            if row["row_class"] == "endpoint_failure":
                row.setdefault("raw_success", row.get("success"))
                row["success"] = None
                bad.append(f"{path.name}:{row.get('task_id')}:{row.get('condition')}:"
                           f"{row.get('run_index')}")
            rows.append(row)

    if bad and not args.allow_api_errors:
        print(f"ERROR: {len(bad)} row(s) are endpoint_failure (including api_error); refusing to merge.", file=sys.stderr)
        for item in bad[:40]:
            print(f"  {item}", file=sys.stderr)
        print("Re-run those (task, condition, seed) cells and merge again.", file=sys.stderr)
        return 2

    first = payloads[0][1]
    live_config = dict(first.get("live_config", {}))
    live_config["seeds"] = sorted(set(seeds))
    live_config["merged_from"] = [p.name for p, _ in payloads]
    live_config["api_error_rows"] = sum(bool(r.get("api_error")) for r in rows)
    live_config["endpoint_failure_rows"] = len(bad)
    partial = bool(args.allow_api_errors or bad or any(p.get("partial") for _, p in payloads))
    merged_identity = dict(first['run_identity'], seeds=sorted(set(seeds)))
    try:
        validate_rows(rows, merged_identity, complete=not partial)
    except ValueError as exc:
        print(f'ERROR: {exc}; output preserved', file=sys.stderr)
        return 2

    payload = {
        "synthetic_test_only": any(p.get('synthetic_test_only') for _,p in payloads),
        "schema": first.get("schema", "verseshell.aci_bench.results/v1"),
        "task_set_version": first.get("task_set_version"),
        "seed": first.get("seed"),
        "mode": "live",
        "partial": partial,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": first.get('git_rev'),
        "evidence": first['evidence'],
        "run_identity": merged_identity,
        "sources": [{'path': str(p), 'sha256': source_hashes[p]}
                    for p, _ in payloads],
        "live_config": live_config,
        "rows": rows,
    }

    try:
        refresh_summaries(payload)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest
               for path, digest in source_hashes.items()):
            raise ValueError("source changed during merge")
        atomic_json(args.out, payload)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}; previous output preserved", file=sys.stderr)
        return 2
    print(f"merged {len(payloads)} runs -> {len(rows)} rows -> {args.out}")
    print(f"  seeds={live_config['seeds']} api_error_rows={live_config.get('api_error_rows', 0)}")
    if partial:
        print("  PARTIAL: endpoint failures are unscored; comparisons are not claimable; C35 remains red")
        for item in bad:
            print(f"    endpoint_failure: {item}")
    for row in payload["aggregate"]["aggregates"]:
        print(f"  {row['condition']:<16} n={row['tasks']:<3} success={row['success_rate']} "
              f"tools={row['avg_tool_calls']} obs_tok={row['avg_observation_tokens']}")
    blocks = payload['comparison'].get('by_prompt_variant', {'selected': payload['comparison']})
    for variant, cmp_ in ((v, c) for v, block in blocks.items() for c in block['comparisons']):
        print(f"  {variant} {cmp_['baseline_condition']} D/A tools={cmp_['tool_call_ratio_D_over_A']} "
              f"tokens={cmp_['token_ratio_D_over_A']} accept=NOT_CLAIMABLE "
              f"reasons={cmp_['policy_blocked_reasons']}")

    if args.out.resolve() == (RESULTS / "latest_live.json").resolve():
        report_path = RESULTS / "live_REPORT.md"
        write_report(payload, report_path)
        if partial:
            report_path.write_text(
                "> **PARTIAL — diagnostic artifact, not claimable.** Endpoint failures are "
                "unscored; original values are preserved in raw_success. C35 remains red.\n\n"
                + report_path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print(f"  report -> {RESULTS / 'live_REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
