#!/usr/bin/env python3
"""Derive budget-sensitive tasks from stored rows (acceptance criteria §0.5.2).

No endpoint calls, task edits, row exclusions or claim-eligibility changes.
The >=10% task diagnostic differs from the >10% arm exclusion rule in §0.6.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "with_read_files": "bench/aci/results/latest_live.json",
    "without_read_files": "bench/aci/results/live_ab_without_read_files.json",
}
EVIDENCE_GLOBS = [*SOURCES.values(), "tools/budget_sensitivity.py"]


def derive(payload: dict, arm: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"{arm}: artifact must be an object")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{arm}: no rows; budget sensitivity cannot be assessed")
    live_config = payload.get("live_config") or {}
    max_turns = live_config.get("max_turns")
    if type(max_turns) is not int or max_turns < 1:
        raise ValueError(f"{arm}: missing or invalid live_config.max_turns")
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{arm} row {index}: row must be an object")
        model = row.get("model") or live_config.get("model")
        task, condition = row.get("task_id"), row.get("condition")
        count, turns = row.get("completion_truncated_turns"), row.get("turns")
        if not all(isinstance(v, str) and v for v in (model, task, condition)):
            raise ValueError(f"{arm} row {index}: missing model/task/condition")
        if type(count) is not int or count < 0:
            raise ValueError(f"{arm} row {index}: missing or invalid completion_truncated_turns")
        if type(turns) is not int or turns < 0:
            raise ValueError(f"{arm} row {index}: missing or invalid turns")
        groups[(model, condition, task)].append({"completion": count > 0,
                                                  "turn": turns >= max_turns})
    result = []
    for (model, condition, task), flags in sorted(groups.items()):
        n = len(flags)
        truncated = sum(flag["completion"] for flag in flags)
        turn_capped = sum(flag["turn"] for flag in flags)
        completion_sensitive = truncated * 10 >= n
        turn_sensitive = turn_capped * 10 >= n
        result.append({"model": model, "condition": condition, "task_id": task,
                       "rows": n, "completion_truncated_rows": truncated,
                       "completion_truncated_rate": round(truncated / n, 6),
                       "turn_capped_rows": turn_capped,
                       "turn_capped_rate": round(turn_capped / n, 6),
                       "budget_sensitive_completion": completion_sensitive,
                       "budget_sensitive_turn": turn_sensitive,
                       "budget_sensitive_any": completion_sensitive or turn_sensitive,
                       # Backward-compatible field: it remains completion-only by design.
                       "budget_sensitive": completion_sensitive})
    return {"artifact": arm, "task_set_version": payload.get("task_set_version"),
            "live_config": {k: live_config.get(k)
                            for k in ("model", "max_tokens", "max_turns", "exclude_tools")},
            "rows": len(rows), "groups": result,
            "sensitive_task_ids": sorted({r["task_id"] for r in result if r["budget_sensitive"]}),
            "sensitive_task_ids_any": sorted({r["task_id"] for r in result if r["budget_sensitive_any"]})}


def fingerprint() -> str:
    digest = hashlib.sha256()
    for glob in EVIDENCE_GLOBS:
        for path in sorted(ROOT.glob(glob)):
            if path.is_file():
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "eval/budget_sensitivity.json")
    args = parser.parse_args(argv)
    try:
        arms = [derive(json.loads((ROOT / path).read_text(encoding="utf-8-sig")), name)
                for name, path in SOURCES.items()]
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    report = {"schema": "verseshell.budget-sensitivity/v1",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "generator": "tools/budget_sensitivity.py",
              "method": {"rule": "docs/acceptance-criteria.md §0.5.2",
                         "group_by": ["artifact", "model", "condition", "task_id"],
                         "numerator": {"completion": "rows where completion_truncated_turns > 0",
                                       "turn": "rows where turns >= live_config.max_turns"},
                         "denominator": "all observed rows in the group; no success or endpoint filtering",
                         "predicate": "each axis independently uses rows * 10 >= denominator; "
                                      "budget_sensitive_any is the union, while legacy budget_sensitive remains completion-only",
                         "threshold": 0.10, "operator": ">=",
                         "scope": "observed completion/turn budget sensitivity, not task difficulty or causation",
                         "not_used": ["success", "observation_tokens"],
                         "claim_eligibility": "unchanged; use the existing §0.6 row policy"},
              "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": fingerprint()},
              "arms": arms}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for arm in arms:
        print(f"{arm['artifact']}: {len(arm['sensitive_task_ids'])} sensitive tasks, "
              f"{sum(r['budget_sensitive'] for r in arm['groups'])}/{len(arm['groups'])} groups")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
