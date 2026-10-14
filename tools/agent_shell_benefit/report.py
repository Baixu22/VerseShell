#!/usr/bin/env python3
"""Render the fixed P1 summary to Markdown without changing its verdict."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-dir", required=True)
    args = parser.parse_args(argv)
    round_dir = Path(args.round_dir)
    summary = json.loads((round_dir / "summary.json").read_text(encoding="utf-8"))
    lines = [
        f"# Agent-shell benefit report: {summary['round_id']}",
        "",
        f"**Verdict: `{summary['verdict']}`**",
        "",
        f"- cells: {summary['cell_count']} / {summary['expected_cell_count']}",
        f"- missing: {', '.join(summary['missing_cells']) if summary['missing_cells'] else 'none'}",
        f"- verdict notes: {'; '.join(summary.get('verdict_notes') or [])}",
        "",
        "## Arm aggregates",
        "",
        "| arm | success rate | recovery rate | obs tokens mean | tool calls mean | model calls mean | anomalies | safety |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("A", "A_prime", "D"):
        row = summary["arms"].get(arm) or {}
        lines.append(
            f"| {arm} | {row.get('task_success_rate')} | {row.get('recovered_after_first_error_rate')} | "
            f"{row.get('mean_observation_tokens')} | {row.get('mean_tool_calls')} | "
            f"{row.get('mean_model_calls')} | {row.get('cap_or_endpoint_failures')} | {row.get('safety_violations')} |"
        )
    lines += [
        "",
        "## D vs A-prime paired tasks",
        "",
        "| task | A-prime success | D success | delta | A-prime obs | D obs | A-prime tools | D tools |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.get("paired") or []:
        if row.get("missing"):
            lines.append(f"| {row['task_id']} | MISSING | MISSING |  |  |  |  |  |")
            continue
        lines.append(
            f"| {row['task_id']} | {row['A_prime_success']} | {row['D_success']} | "
            f"{row['success_delta_D_minus_A_prime']} | {row['A_prime_observation_tokens']} | "
            f"{row['D_observation_tokens']} | {row['A_prime_tool_calls']} | {row['D_tool_calls']} |"
        )
    lines += [
        "",
        "## Provenance",
        "",
        "- raw cells: `cells/<task>__<arm>__<seed>.json`",
        "- derived rows: `rows.jsonl`",
        "- machine summary: `summary.json`",
        "- preregistration: `preregistration.md`",
        f"- verdict computation: {summary.get('verdict_source')}",
        "",
        "This report does not upgrade an endpoint, adapter, timeout, or safety anomaly into a pass.",
    ]
    (round_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(round_dir / "report.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())