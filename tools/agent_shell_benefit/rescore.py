#!/usr/bin/env python3
"""Recompute the fixed P1 verdict from stored cell evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parents[1]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.scoring import HOST_README_MARKER, extract_metrics


def load_task_map() -> dict[str, dict[str, Any]]:
    manifest = json.loads((BASE_DIR / "task_manifest.json").read_text(encoding="utf-8"))
    result = {}
    for entry in manifest["tasks"]:
        task = json.loads((BASE_DIR / entry["file"]).read_text(encoding="utf-8"))
        result[task["id"]] = task
    return result


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def rate(values: list[bool]) -> float | None:
    return round(sum(1 for value in values if value) / len(values), 4) if values else None


def load_cells(round_dir: Path, task_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cells = []
    for path in sorted((round_dir / "cells").glob("*.json")):
        cell = json.loads(path.read_text(encoding="utf-8"))
        task = task_map.get(cell.get("task_id"))
        if task:
            cell["metrics"] = extract_metrics(cell, task)
            cell["_path"] = str(path)
            cells.append(cell)
    return cells


def aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [cell.get("metrics") or {} for cell in cells]
    recoverable = [m for m in metrics if m.get("recovered_after_first_error") is not None]
    return {
        "cells": len(cells),
        "task_success_rate": rate([bool(m.get("task_success")) for m in metrics]),
        "recovered_after_first_error_rate": rate([bool(m.get("recovered_after_first_error")) for m in recoverable]),
        "recovery_denominator": len(recoverable),
        "safety_violations": sum(1 for m in metrics if m.get("safety_violation")),
        "cap_or_endpoint_failures": sum(1 for m in metrics if m.get("cap_or_endpoint_failure")),
        "endpoint_errors": sum(1 for cell in cells if cell.get("status") == "endpoint_error"),
        "adapter_errors": sum(1 for cell in cells if cell.get("status") == "adapter_error"),
        "task_timeouts": sum(1 for cell in cells if cell.get("status") == "task_timeout"),
        "turn_caps": sum(1 for cell in cells if cell.get("status") == "turn_cap"),
        "mean_observation_tokens": mean([float(m.get("observation_tokens") or 0) for m in metrics]),
        "mean_tool_calls": mean([float(m.get("tool_calls") or 0) for m in metrics]),
        "mean_model_calls": mean([float(m.get("model_calls") or 0) for m in metrics]),
        "mean_input_tokens": mean([float((cell.get("model") or {}).get("prompt_tokens") or 0) for cell in cells]),
        "mean_output_tokens": mean([float((cell.get("model") or {}).get("completion_tokens") or 0) for cell in cells]),
        "mean_wall_ms": mean([float(cell.get("wall_ms") or 0) for cell in cells]),
        "duplicate_tool_calls": sum(int(m.get("duplicate_tool_calls") or 0) for m in metrics),
    }


def paired_results(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(cell["task_id"], cell["arm"]): cell for cell in cells}
    task_ids = sorted({cell["task_id"] for cell in cells})
    rows = []
    for task_id in task_ids:
        a = by_key.get((task_id, "A_prime"))
        d = by_key.get((task_id, "D"))
        if not a or not d:
            rows.append({"task_id": task_id, "missing": True})
            continue
        am = a.get("metrics") or {}
        dm = d.get("metrics") or {}
        rows.append(
            {
                "task_id": task_id,
                "A_prime_success": bool(am.get("task_success")),
                "D_success": bool(dm.get("task_success")),
                "success_delta_D_minus_A_prime": int(bool(dm.get("task_success"))) - int(bool(am.get("task_success"))),
                "A_prime_observation_tokens": am.get("observation_tokens"),
                "D_observation_tokens": dm.get("observation_tokens"),
                "A_prime_tool_calls": am.get("tool_calls"),
                "D_tool_calls": dm.get("tool_calls"),
                "A_prime_model_calls": am.get("model_calls"),
                "D_model_calls": dm.get("model_calls"),
                "A_prime_recovered": am.get("recovered_after_first_error"),
                "D_recovered": dm.get("recovered_after_first_error"),
            }
        )
    return rows


def decide(summary: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    arms = summary["arms"]
    a = arms.get("A_prime") or {}
    d = arms.get("D") or {}
    if summary["missing_cells"]:
        return "INVALID", [f"missing cells: {summary['missing_cells']}"]
    total_cells = max(1, summary["cell_count"])
    safety = sum((summary["arms"].get(arm) or {}).get("safety_violations") or 0 for arm in ("A", "A_prime", "D"))
    if safety > 0:
        return "INVALID", ["safety violation is nonzero"]
    anomaly = sum((summary["arms"].get(arm) or {}).get("cap_or_endpoint_failures") or 0 for arm in ("A", "A_prime", "D"))
    if anomaly / total_cells > 0.10:
        notes.append(f"anomaly rate {anomaly}/{total_cells} exceeds 10%")
        return "INVALID", notes
    prompt_delta = summary.get("prompt_token_delta_fraction")
    if prompt_delta is not None and prompt_delta > 0.20:
        notes.append(f"A-prime/D prompt token proxy differs by {prompt_delta:.3f}")
        return "INVALID", notes
    a_success = a.get("task_success_rate")
    d_success = d.get("task_success_rate")
    if a_success is None or d_success is None:
        return "INVALID", ["missing A-prime or D aggregate"]
    if d_success < a_success:
        notes.append("D oracle success rate is below A-prime")
        return "NO_EVIDENCE", notes
    positive = False
    if d_success - a_success >= 0.099999:
        positive = True
        notes.append("success rate gain >= +1/10")
    recovery_a = a.get("recovered_after_first_error_rate")
    recovery_d = d.get("recovered_after_first_error_rate")
    if recovery_a is not None and recovery_d is not None and recovery_d - recovery_a >= 0.15:
        positive = True
        notes.append("first-error recovery gain >= +15pp")
    if d_success >= a_success:
        a_obs = a.get("mean_observation_tokens")
        d_obs = d.get("mean_observation_tokens")
        if a_obs and d_obs is not None and d_obs <= a_obs * 0.8:
            positive = True
            notes.append("observation token reduction >= 20% with success not lower")
        a_tools = a.get("mean_tool_calls")
        d_tools = d.get("mean_tool_calls")
        a_models = a.get("mean_model_calls")
        d_models = d.get("mean_model_calls")
        if (
            (a_tools and d_tools is not None and d_tools <= a_tools * 0.85)
            or (a_models and d_models is not None and d_models <= a_models * 0.85)
        ):
            positive = True
            notes.append("tool/model call reduction >= 15% with success not lower")
    if positive:
        return "POSITIVE", notes
    notes.append("no positive-benefit threshold was met")
    return "NO_EVIDENCE", notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-dir", required=True)
    args = parser.parse_args(argv)
    round_dir = Path(args.round_dir)
    task_map = load_task_map()
    cells = load_cells(round_dir, task_map)
    expected = [(task_id, arm, 42) for task_id in sorted(task_map) for arm in ("A", "A_prime", "D")]
    present = {(cell.get("task_id"), cell.get("arm"), cell.get("seed")) for cell in cells}
    missing = [f"{task_id}__{arm}__42" for task_id, arm, _ in expected if (task_id, arm, 42) not in present]
    arms = {arm: aggregate([cell for cell in cells if cell.get("arm") == arm]) for arm in ("A", "A_prime", "D")}
    prompt_a = 0
    prompt_d = 0
    for cell in cells:
        if cell.get("arm") == "A_prime":
            prompt_a = (cell.get("provider") or {}).get("system_prompt_tokens") or 0
        if cell.get("arm") == "D":
            prompt_d = (cell.get("provider") or {}).get("system_prompt_tokens") or 0
    denom = max(prompt_a, prompt_d, 1)
    summary = {
        "schema": "agent-shell-benefit.summary/v1",
        "round_id": round_dir.name,
        "cell_count": len(cells),
        "expected_cell_count": len(expected),
        "missing_cells": missing,
        "arms": arms,
        "paired": paired_results(cells),
        "prompt_tokens_A_prime": prompt_a,
        "prompt_tokens_D": prompt_d,
        "prompt_token_delta_fraction": abs(prompt_d - prompt_a) / denom,
    }
    verdict, notes = decide(summary)
    summary["verdict"] = verdict
    summary["verdict_notes"] = notes
    summary["verdict_source"] = "rescore.py pure recomputation from stored oracle evidence"
    (round_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "notes": notes, "summary": str(round_dir / "summary.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())