#!/usr/bin/env python3
"""Exclusive lock helper: only one holder runs the critical section."""

from __future__ import annotations

import argparse
import fcntl
import os
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--wait", type=float, default=0.0)
    args = parser.parse_args()
    lock_path = Path(args.path)
    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"LOCK_BUSY pid={os.getpid()}")
        return 1
    try:
        handle.write(str(os.getpid()))
        handle.flush()
        if args.wait:
            time.sleep(args.wait)
        os.system(args.run)
        print(f"LOCK_HELD pid={os.getpid()}")
        return 0
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


if __name__ == "__main__":
    raise SystemExit(main())