#!/usr/bin/env python3
"""Score + print A/D acceptance from latest results."""
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
    cmp_ = data.get("comparison") or {}
    print(json.dumps(cmp_, indent=2))
    print(json.dumps(data.get("aggregate"), indent=2))
    if args.require_accept:
        comps = cmp_.get("comparisons") or []
        if not comps:
            print("FAIL: no comparisons", file=sys.stderr)
            return 2
        if not all(c.get("meets_acceptance") for c in comps):
            print("FAIL: acceptance not met", file=sys.stderr)
            return 1
        print("PASS: acceptance met for all models in report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
