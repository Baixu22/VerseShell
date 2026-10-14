#!/usr/bin/env python3
"""Small deterministic stale-hash fixture used by T04."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--expected-hash", required=True)
    args = parser.parse_args()
    path = Path(args.path)
    data = path.read_bytes()
    actual_hash = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8")
    if args.expected_hash != actual_hash:
        print(f"E_STALE_HASH: expected_hash={args.expected_hash}", file=sys.stderr)
        print(f"E_STALE_HASH: actual_hash={actual_hash}", file=sys.stderr)
        print(f"next_actions: rerun with actual_hash={actual_hash}", file=sys.stderr)
        return 2
    if args.old not in text:
        print(f"E_NOT_FOUND: old text not present: {args.old!r}", file=sys.stderr)
        return 3
    path.write_text(text.replace(args.old, args.new, 1), encoding="utf-8")
    print(f"OK: replaced {args.old!r} with {args.new!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())