#!/usr/bin/env python3
"""Recompute the 80-task suite verdict from stored cells, with tier breakdowns."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
ROOT = BASE_DIR.parents[1]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.suite import build_catalog
from tools.agent_shell_benefit.suite.oracles import extract_metrics

ARMS = ["A", "A_prime", "D"]


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def rate(values: list[bool]) -> float | None:
    return round(sum(1 for v in values if v) / len(values), 4) if values else None


def aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [c.get("metrics") or {} for c in cells]
    rec = [m for m in metrics if m.get("recovered_after_first_error") is not None]
    return {
        "cells": len(cells),
        "successes": sum(1 for m in metrics if m.get("task_success")),
        "task_success_rate": rate([bool(m.get("task_success")) for m in metrics]),
        "recovered_after_first_error_rate": rate([bool(m.get("recovered_after_first_error")) for m in rec]),
        "recovery_denominator": len(rec),
        "safety_violations": sum(1 for m in metrics if m.get("safety_violation")),
        "cap_or_endpoint_failures": sum(1 for m in metrics if m.get("cap_or_endpoint_failure")),
        "mean_observation_tokens": mean([float(m.get("observation_tokens") or 0) for m in metrics]),
        "mean_tool_calls": mean([float(m.get("tool_calls") or 0) for m in metrics]),
        "mean_model_calls": mean([float(m.get("model_calls") or 0) for m in metrics]),
        "mean_wall_ms": mean([float(c.get("wall_ms") or 0) for c in cells]),
        "parallel_cells": sum(1 for m in metrics if (m.get("parallel_calls") or 0) > 0),
        "mean_parallel_wall_ms": mean([
            float(m["parallel_wall_ms_min"]) for m in metrics if m.get("parallel_wall_ms_min") is not None
        ]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-dir", required=True)
    args = parser.parse_args(argv)
    round_dir = Path(args.round_dir)
    catalog = {t["id"]: t for t in build_catalog()}
    cells = []
    for path in sorted((round_dir / "cells").glob("*.json")):
        cell = json.loads(path.read_text(encoding="utf-8"))
        task = catalog.get(cell.get("task_id"))
        if task:
            cell["metrics"] = extract_metrics(task, cell)
            cells.append(cell)
    present_tiers = sorted({c.get("tier") for c in cells if c.get("tier")})
    present_tasks = {c.get("task_id") for c in cells if c.get("task_id")}
    # Scope to the task subset actually collected (supports tier sampling),
    # never assume a whole tier was run.
    scoped_ids = sorted(tid for tid, task in catalog.items() if task["tier"] in present_tiers and tid in present_tasks)
    expected = [(tid, arm, 42) for tid in scoped_ids for arm in ARMS]
    present = {(c.get("task_id"), c.get("arm"), c.get("seed")) for c in cells}
    missing = [tid + "__" + arm + "__42" for tid, arm, _ in expected if (tid, arm, 42) not in present]

    arms = {arm: aggregate([c for c in cells if c.get("arm") == arm]) for arm in ARMS}
    tiers = {}
    for tier in ("L1", "L2", "L3", "L4"):
        tiers[tier] = {
            arm: aggregate([c for c in cells if c.get("tier") == tier and c.get("arm") == arm])
            for arm in ARMS
        }

    by_key = {(c["task_id"], c["arm"]): c for c in cells}
    paired = []
    for tid in scoped_ids:
        a = by_key.get((tid, "A_prime"))
        d = by_key.get((tid, "D"))
        if not a or not d:
            paired.append({"task_id": tid, "missing": True})
            continue
        am, dm = a.get("metrics") or {}, d.get("metrics") or {}
        paired.append({
            "task_id": tid,
            "tier": catalog[tid]["tier"],
            "A_prime_success": bool(am.get("task_success")),
            "D_success": bool(dm.get("task_success")),
            "delta": int(bool(dm.get("task_success"))) - int(bool(am.get("task_success"))),
            "A_prime_obs": am.get("observation_tokens"),
            "D_obs": dm.get("observation_tokens"),
        })

    a, d = arms["A_prime"], arms["D"]
    notes = []
    verdict = "NO_EVIDENCE"
    if missing:
        verdict = "INVALID"
        notes.append("missing cells: " + str(len(missing)))
    safety = sum(arms[x]["safety_violations"] for x in ARMS)
    anomaly = sum(arms[x]["cap_or_endpoint_failures"] for x in ARMS)
    if safety > 0:
        verdict = "INVALID"
        notes.append("safety violation nonzero")
    if anomaly / max(1, len(cells)) > 0.10:
        verdict = "INVALID"
        notes.append("anomaly rate " + str(anomaly) + "/" + str(len(cells)) + " exceeds 10%")
    if verdict != "INVALID":
        # Compare integer counts, not float rates: 14/20 - 13/20 is exactly
        # +5pp, but 0.70 - 0.65 evaluates to 0.04999999999999993 and silently
        # fails a `>= 0.05` threshold.
        if d["successes"] * a["cells"] < a["successes"] * d["cells"]:
            notes.append("D success below A-prime")
        else:
            gained = False
            if d["successes"] * a["cells"] - a["successes"] * d["cells"] >= 0.05 * d["cells"] * a["cells"] - 1e-9:
                gained = True
                notes.append("success gain >= +5pp")
            ra, rd = a["recovered_after_first_error_rate"], d["recovered_after_first_error_rate"]
            if ra is not None and rd is not None and rd - ra >= 0.15 - 1e-9:
                gained = True
                notes.append("recovery gain >= +15pp")
            ao, do = a["mean_observation_tokens"], d["mean_observation_tokens"]
            if ao and do is not None and do <= ao * 0.8:
                gained = True
                notes.append("obs token reduction >= 20%")
            at, dt = a["mean_tool_calls"], d["mean_tool_calls"]
            if at and dt is not None and dt <= at * 0.85:
                gained = True
                notes.append("tool call reduction >= 15%")
            verdict = "POSITIVE" if gained else "NO_EVIDENCE"
            if not gained:
                notes.append("no threshold met")

    summary = {
        "schema": "agent-shell-benefit.suite-summary/v1",
        "round_id": round_dir.name,
        "cell_count": len(cells),
        "expected_cell_count": len(expected),
        "missing_cells": missing,
        "verdict": verdict,
        "verdict_notes": notes,
        "arms": arms,
        "tiers": tiers,
        "paired": paired,
    }
    (round_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "notes": notes, "cells": len(cells), "expected": len(expected)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())