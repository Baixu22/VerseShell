#!/usr/bin/env python3
"""Print descriptive results; only the frozen study evaluator grants live claims."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path, nargs="?", default=Path("bench/aci/results/latest.json"))
    ap.add_argument("--require-accept", action="store_true")
    args = ap.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8-sig"))
    is_mock = data.get('mode') == 'mock'
    if not is_mock:
        # Recompute even historical/stale comparison labels. A successful analysis
        # command (exit 0 without --require-accept) is not acceptance of its data.
        root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(root / 'bench/aci/runners'))
        from merge_live_runs import refresh_summaries
        data.setdefault("rows", [])
        refresh_summaries(data)
    cmp_ = data.get("comparison") or {}
    print(json.dumps(cmp_, indent=2))
    print(json.dumps(data.get("aggregate"), indent=2))
    if args.require_accept:
        if not is_mock:
            print("NOT CLAIMABLE: collection diagnostics are not a frozen repeated-study verdict; "
                  "use tools/study_inference.py", file=sys.stderr)
            return 1
        comps = cmp_.get("comparisons") or []
        if not comps:
            print("FAIL: no mock comparisons", file=sys.stderr)
            return 2
        if not all(c.get("meets_acceptance") is True for c in comps):
            print("FAIL: mock regression not met", file=sys.stderr)
            return 1
        print("PASS: mock regression only; not product or live acceptance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
