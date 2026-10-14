#!/usr/bin/env python3
"""Race counter: N writers increment a file without locking."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


def bump(path: Path) -> None:
    value = int(path.read_text().strip() or "0")
    time.sleep(0.005)  # widen the read-modify-write window
    path.write_text(str(value + 1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="counter.txt")
    parser.add_argument("--writers", type=int, default=8)
    parser.add_argument("--lock", action="store_true")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        path.write_text("0")
    if args.lock:
        import fcntl
        lock_path = path.with_suffix(path.suffix + ".lock")
        handle = open(lock_path, "w")
        fcntl.flock(handle, fcntl.LOCK_EX)
        bump(path)
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
    else:
        children = []
        for _ in range(args.writers):
            pid = os.fork()
            if pid == 0:
                bump(path)
                os._exit(0)
            children.append(pid)
        for pid in children:
            os.waitpid(pid, 0)
    final = int(path.read_text().strip() or "0")
    lost = args.writers - final if not args.lock else 0
    print(f"final={final} expected={args.writers} lost={lost} race={'yes' if lost else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())