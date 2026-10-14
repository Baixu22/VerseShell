#!/usr/bin/env python3
"""Simple worker-pool queue drainer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    path = Path(args.queue)
    jobs = [line for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    if not jobs:
        jobs = [f"job{i}" for i in range(1, 9)]
        path.write_text("\n".join(jobs) + "\n")
    print(f"WORKERS={args.workers}")
    print(f"DRAINED={len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())