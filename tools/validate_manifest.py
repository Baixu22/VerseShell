#!/usr/bin/env python3
"""Validate eval/manifest.json provenance: every source path must exist.

Usage:
    python tools/validate_manifest.py
    python tools/validate_manifest.py --root <repo_root>

Exit 0 when all sources resolve to real files; exit 1 with a missing-path report.
No human annotation required — only path existence and required keys.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_KEYS = ("id", "kind", "source", "expect")


def validate(manifest_path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"manifest is not valid JSON: {e}"]

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["manifest.entries must be a non-empty list"]

    seen_ids: set[str] = set()
    for i, entry in enumerate(entries):
        loc = f"entries[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{loc}: not an object")
            continue

        for key in REQUIRED_KEYS:
            if key not in entry:
                errors.append(f"{loc}: missing required key '{key}'")

        eid = entry.get("id")
        if not eid:
            errors.append(f"{loc}: empty id")
        elif eid in seen_ids:
            errors.append(f"{loc}: duplicate id '{eid}'")
        else:
            seen_ids.add(str(eid))

        source = entry.get("source")
        if not source or not isinstance(source, str):
            errors.append(f"{loc} ({eid}): source must be a non-empty string")
        else:
            if source.startswith(("http://", "https://")):
                pass  # external URL is allowed as explicit provenance
            else:
                p = root / source
                if not p.exists():
                    errors.append(f"{loc} ({eid}): source path missing: {source}")

        for optional in ("fixture", "golden"):
            val = entry.get(optional)
            if val is None:
                continue
            if not isinstance(val, str) or not val:
                errors.append(f"{loc} ({eid}): {optional} must be a non-empty string when set")
            elif not val.startswith(("http://", "https://")):
                p = root / val
                if not p.exists():
                    errors.append(f"{loc} ({eid}): {optional} path missing: {val}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: parent of tools/)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="manifest path (default: <root>/eval/manifest.json)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest or (root / "eval" / "manifest.json")
    manifest = manifest.resolve()

    if not manifest.is_file():
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        return 1

    errors = validate(manifest, root)
    if errors:
        print(f"FAIL: {len(errors)} problem(s) in {manifest.relative_to(root)}")
        for e in errors:
            print(f"  - {e}")
        return 1

    data = json.loads(manifest.read_text(encoding="utf-8"))
    kinds: dict[str, int] = {}
    for e in data["entries"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"OK: {len(data['entries'])} entries, all sources exist under {root.name}/")
    for k in sorted(kinds):
        print(f"  {k}: {kinds[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
