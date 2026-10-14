#!/usr/bin/env python3
"""Append-only journal with optional fault/crash injection for recovery tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    if not path.exists():
        return {"done": [], "committed": 0}
    return json.loads(path.read_text())


def save(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", default="journal.json")
    parser.add_argument("--items", type=int, default=5)
    parser.add_argument("--inject-fault-after", type=int, default=-1)
    parser.add_argument("--crash-after", type=int, default=-1)
    args = parser.parse_args()
    path = Path(args.journal)
    state = load(path)
    done = set(state.get("done", []))
    for index in range(1, args.items + 1):
        if index in done:
            continue
        if args.crash_after >= 0 and index > args.crash_after:
            save(path, {"done": sorted(done), "committed": len(done)})
            print("CRASH after " + str(len(done)) + " items")
            return 2
        if args.inject_fault_after >= 0 and index == args.inject_fault_after + 1:
            print("FAULT injected at item " + str(index))
            return 3
        done.add(index)
        save(path, {"done": sorted(done), "committed": len(done)})
    print("DONE committed=" + str(len(done)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())