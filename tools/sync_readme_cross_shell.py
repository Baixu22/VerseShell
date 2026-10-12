#!/usr/bin/env python3
"""Sync README's cross-shell table to ``eval/cross_shell.json``.

The README table is a checked, derived view of the benchmark artifact. Keep the
update in the refresh chain so a new timing run cannot leave C10 stale until a
human notices it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "eval/cross_shell.json"
README = ROOT / "README.md"


def expected_rows() -> list[tuple[str, str]]:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    rows: list[tuple[str, str]] = []
    for row in data.get("operations", []):
        shells = row["shells"]
        ae = round(shells["ae"]["median_ms"], 1)
        pwsh = round(shells["pwsh"]["median_ms"], 1)
        bash_ms = shells["bash"].get("median_ms")
        bash = "N/A" if bash_ms is None else f"{round(bash_ms, 1)}ms"
        speedup = round(shells["pwsh"]["median_ms"] / shells["ae"]["median_ms"], 1)
        rows.append((
            row["name"],
            f"| {row['name']} | **{ae}ms** | {pwsh}ms | {bash} | **{speedup}x faster** |",
        ))
    return rows


def sync() -> list[tuple[int, str, str]]:
    rows = expected_rows()
    if not rows:
        raise ValueError("eval/cross_shell.json contains no operations")

    lines = README.read_text(encoding="utf-8").splitlines(keepends=True)
    changed: list[tuple[int, str, str]] = []
    seen: dict[str, int] = {name: 0 for name, _ in rows}
    for index, line in enumerate(lines):
        for name, expected in rows:
            if line.lstrip().startswith(f"| {name} |"):
                seen[name] += 1
                if line.rstrip("\r\n") != expected:
                    changed.append((index + 1, line.rstrip("\r\n"), expected))
                    lines[index] = expected + ("\r\n" if line.endswith("\r\n") else "\n")
                break

    missing = [name for name, count in seen.items() if count == 0]
    duplicate = [name for name, count in seen.items() if count > 1]
    if missing or duplicate:
        details = []
        if missing:
            details.append("missing README rows: " + ", ".join(missing))
        if duplicate:
            details.append("duplicate README rows: " + ", ".join(duplicate))
        raise ValueError("; ".join(details))

    if changed:
        README.write_text("".join(lines), encoding="utf-8", newline="")
    return changed


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - cosmetic
        pass
    try:
        changed = sync()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot sync README cross-shell table: {exc}", file=sys.stderr)
        return 2

    if not changed:
        print("README cross-shell table already matches eval/cross_shell.json")
        return 0
    print(f"updated {len(changed)} README row(s):")
    for line_no, before, after in changed:
        print(f"  L{line_no}\n    - {before}\n    + {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())