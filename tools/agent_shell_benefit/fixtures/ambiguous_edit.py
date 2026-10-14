#!/usr/bin/env python3
"""Small deterministic ambiguous-edit fixture used by T05."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    path = Path(args.path)
    text = path.read_text(encoding="utf-8")
    positions = [index for index in range(len(text)) if text.startswith(args.old, index)]
    if args.index is None:
        print(f"E_AMBIGUOUS: {len(positions)} matches for {args.old!r}", file=sys.stderr)
        for number, position in enumerate(positions):
            line = text.count("\\n", 0, position) + 1
            column = position - text.rfind("\\n", 0, position)
            print(f"matches[{number}]: line={line} column={column} offset={position}", file=sys.stderr)
        print("next_actions: rerun with --index 0 or --index 1", file=sys.stderr)
        return 3
    if args.index < 0 or args.index >= len(positions):
        print(f"E_INDEX: index {args.index} is invalid; matches={len(positions)}", file=sys.stderr)
        return 4
    position = positions[args.index]
    updated = text[:position] + args.new + text[position + len(args.old) :]
    path.write_text(updated, encoding="utf-8")
    print(f"OK: replaced occurrence {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())