#!/usr/bin/env python3
"""P0-1: per-turn diagnostics over a STORED live run artifact (read-only).

The rows in `bench/aci/results/latest_live.json` predate per-turn recording, so the
artifact can only say *how many* turns a cell truncated, not *which* turn, and never
whether the endpoint was reasoning when the completion budget ran out. This tool
classifies each cell from the per-turn records the runner now writes
(`row["turn_diagnostics"]`) and refuses to fill a gap it cannot see:

  * `reasoning_burn` — the first turn hit `finish_reason="length"`, emitted no tool
    call, and the endpoint returned reasoning text for it.
  * `budget_burn_without_reasoning_evidence` — same truncation shape, but no
    reasoning field came back (or it came back empty). This is *not* evidence that
    the budget was spent on something else; it is a missing field.
  * `truncated_other_turn` — some turn truncated, but not the turn-1 / zero-tool-call
    shape (e.g. a later turn, or a truncated turn that still emitted tool calls).
  * `no_truncation` — every recorded turn is complete and none truncated.
  * `unknown_field_missing` — the row has no usable `turn_diagnostics` at all
    (the old-schema artifact), or the list is empty/malformed. Reported as unknown,
    never as healthy.
  * `unknown_incomplete_turn` — some recorded turn is unusable (a request error, a
    recording error, or a missing finish_reason), or the per-turn records and the
    row's own cell-level `completion_truncated_turns` total disagree, so the cell
    cannot be decided.

Usage:
    python tools/live_turn_diagnostics.py --input bench/aci/results/latest_live.json \
        --out audit-r12-scratch/.../turn-diagnostics-old-run.json

The input artifact is opened read-only and is never rewritten; `--out` is refused
when it resolves to the input path. Reasoning length is reported only when the
endpoint provided a reasoning field — it is never derived from completion tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "bench" / "aci" / "results" / "latest_live.json"

SCHEMA = "verseshell.live-turn-diagnostics/v1"

CLASS_REASONING_BURN = "reasoning_burn"
CLASS_BUDGET_BURN = "budget_burn_without_reasoning_evidence"
CLASS_TRUNCATED_OTHER = "truncated_other_turn"
CLASS_NO_TRUNCATION = "no_truncation"
CLASS_UNKNOWN_FIELD_MISSING = "unknown_field_missing"
CLASS_UNKNOWN_INCOMPLETE = "unknown_incomplete_turn"

CLASSIFICATIONS = (
    CLASS_REASONING_BURN,
    CLASS_BUDGET_BURN,
    CLASS_TRUNCATED_OTHER,
    CLASS_NO_TRUNCATION,
    CLASS_UNKNOWN_FIELD_MISSING,
    CLASS_UNKNOWN_INCOMPLETE,
)

CLASSIFICATION_LEGEND = {
    CLASS_REASONING_BURN:
        "first recorded turn: finish_reason=length, tool_call_count=0, and the "
        "endpoint returned non-empty reasoning text for that turn",
    CLASS_BUDGET_BURN:
        "first recorded turn: finish_reason=length and tool_call_count=0, but no "
        "reasoning field was returned (or it was empty) — the budget was spent, the "
        "reason is NOT established",
    CLASS_TRUNCATED_OTHER:
        "at least one turn truncated, but not the turn-1 / zero-tool-call shape "
        "(a later turn, or a truncated turn that still emitted tool calls)",
    CLASS_NO_TRUNCATION:
        "every recorded turn is complete and none truncated",
    CLASS_UNKNOWN_FIELD_MISSING:
        "the row carries no usable per-turn record (old-schema row, empty or "
        "malformed list); classified unknown, never healthy",
    CLASS_UNKNOWN_INCOMPLETE:
        "a recorded turn is unusable (request error, recording error, or missing "
        "finish_reason), or the row's own `completion_truncated_turns` total is "
        "missing or disagrees with the per-turn records, so this cell is left "
        "undecided",
}

LIMITATIONS = [
    "This is a diagnostic over ONE stored run, not a causal experiment: it cannot "
    "separate prompt/tool-schema volume from interface framing, and it cannot say "
    "why a completion budget was spent.",
    "reasoning length is reported only when the endpoint returned a reasoning field; "
    "an absent field is recorded as absent and is never inferred from completion "
    "tokens (the endpoint bills reasoning as completion tokens but does not promise "
    "that the budget was spent on reasoning).",
    "A cell recorded before the per-turn change is reported unknown_field_missing, "
    "not as no_truncation; the old row's completion_truncated_turns total cannot "
    "establish which turn truncated.",
    "`no_truncation` requires the row's own cell-level `completion_truncated_turns` "
    "total to be recorded and to agree with the per-turn records; a disagreement is "
    "reported as unknown_incomplete_turn, never as a healthy cell.",
    "The input artifact is read-only input; this tool writes only its --out path.",
]

_ABSENT = object()


def load_artifact(path: Path) -> tuple[dict, list[dict], int | None]:
    """(payload, rows, cap_tokens). A bare list is accepted as a rows list."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return {"rows": payload}, payload, None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: no `rows` list")
    cap = (payload.get("live_config") or {}).get("max_tokens")
    return payload, rows, cap if isinstance(cap, int) else None


def cell_identity(row: dict) -> dict:
    """Row identity, including the seed.

    `run_index` is constant across a merged multi-seed arm (the round is expressed in
    `live_config.repeat` / the per-seed shards), so `(task_id, condition, run_index)`
    collides once per seed and cannot tell two same-task cells apart. `seed` (and
    `source_run` when present) is what makes the identity unique; the r15 verification
    found this as finding F9.
    """
    return {
        "task_id": row.get("task_id"),
        "condition": row.get("condition"),
        "seed": row.get("seed"),
        "run_index": row.get("run_index"),
        "source_run": row.get("source_run"),
    }


def _truncation_flag(record: dict) -> bool | None:
    """True / False when the record says so, None when the record cannot say.

    A `completion_truncated: false` is only trusted when the record also carries a
    `finish_reason` string; a false flag with no finish_reason is a missing field,
    not a clean turn.
    """
    flag = record.get("completion_truncated")
    finish_reason = record.get("finish_reason")
    if flag is True:
        return True
    if isinstance(flag, bool):
        return (finish_reason == "length") if isinstance(finish_reason, str) else None
    if isinstance(finish_reason, str):
        return finish_reason == "length"
    return None


def _turn_number(record: dict) -> int | None:
    turn = record.get("turn")
    return turn if isinstance(turn, int) and not isinstance(turn, bool) else None


def classify_cell(row: dict, cap_tokens: int | None = None) -> dict:
    """Classify one cell from its per-turn records, with the evidence inline."""
    out = {
        **cell_identity(row),
        "classification": None,
        "reason": "",
        "recorded": False,
        "evidence": {
            "cap_tokens": cap_tokens,
            "row_turns": row.get("turns"),
            "row_completion_truncated_turns": row.get("completion_truncated_turns"),
            "row_llm_completion_tokens": row.get("llm_completion_tokens"),
            "first_turn": None,
            "truncated_turn_numbers": [],
            "unusable_turn_numbers": [],
            "fields_missing": [],
        },
    }
    raw = row.get("turn_diagnostics", _ABSENT)
    ev = out["evidence"]
    if raw is _ABSENT:
        out["classification"] = CLASS_UNKNOWN_FIELD_MISSING
        out["reason"] = ("the row has no `turn_diagnostics` key: it predates per-turn "
                         "recording, so which turn truncated is not recorded")
        return out
    if not isinstance(raw, list) or not raw:
        out["classification"] = CLASS_UNKNOWN_FIELD_MISSING
        out["reason"] = ("`turn_diagnostics` is present but is not a non-empty list: "
                         "recording was not available for this row, so the cell is "
                         "unknown rather than healthy")
        return out

    records = [r for r in raw if isinstance(r, dict)]
    malformed = len(raw) - len(records)
    usable: list[dict] = []
    unusable: list[int | None] = []
    for record in records:
        turn_no = _turn_number(record)
        if record.get("record_error") or record.get("request_error") or turn_no is None:
            unusable.append(turn_no)
            continue
        flag = _truncation_flag(record)
        if flag is None:
            unusable.append(turn_no)
            continue
        usable.append(record)
    ev["unusable_turn_numbers"] = unusable
    if malformed:
        ev["unusable_turn_numbers"].append(None)
        ev["malformed_records"] = malformed

    if not usable:
        out["classification"] = CLASS_UNKNOWN_INCOMPLETE
        out["reason"] = ("every recorded turn is unusable (request/recording error or "
                         "missing finish_reason): the cell cannot be decided")
        return out

    out["recorded"] = True
    turns = sorted(_turn_number(r) for r in usable)
    if turns[0] != 1:
        out["classification"] = CLASS_UNKNOWN_INCOMPLETE
        out["reason"] = (f"the first recorded turn is {turns[0]}, not 1: turn-1 "
                         "behaviour is not recorded, so it cannot be attributed")
        return out

    first = next(r for r in usable if _turn_number(r) == 1)
    ev["first_turn"] = first
    ev["fields_missing"] = list(first.get("fields_missing") or [])
    truncated_turns = sorted(_turn_number(r) for r in usable if _truncation_flag(r))
    ev["truncated_turn_numbers"] = truncated_turns

    first_flag = _truncation_flag(first)
    tool_calls = first.get("tool_call_count")
    reasoning_returned = first.get("reasoning_returned")
    reasoning_chars = first.get("reasoning_chars")
    has_reasoning = bool(reasoning_returned) and isinstance(reasoning_chars, int) and reasoning_chars > 0

    if first_flag and not isinstance(tool_calls, int):
        out["classification"] = CLASS_UNKNOWN_INCOMPLETE
        out["reason"] = ("turn 1 truncated, but tool_call_count is not recorded: the "
                         "zero-tool-call shape cannot be established")
        return out

    if first_flag and tool_calls == 0:
        if has_reasoning:
            out["classification"] = CLASS_REASONING_BURN
            out["reason"] = (f"turn 1 finish_reason={first.get('finish_reason')!r} with "
                             f"tool_call_count=0 and {reasoning_chars} chars of reasoning "
                             "returned by the endpoint")
        else:
            out["classification"] = CLASS_BUDGET_BURN
            out["reason"] = (f"turn 1 finish_reason={first.get('finish_reason')!r} with "
                             "tool_call_count=0, but no reasoning evidence was returned "
                             "(reasoning_returned="
                             f"{reasoning_returned!r}, reasoning_chars={reasoning_chars!r})")
        first_tokens = first.get("completion_tokens")
        if isinstance(first_tokens, int) and cap_tokens:
            ev["cap_reached"] = first_tokens >= cap_tokens
        return out

    if first_flag:
        out["classification"] = CLASS_TRUNCATED_OTHER
        out["reason"] = (f"turn 1 truncated but tool_call_count={tool_calls!r}, so this "
                         "is not the zero-tool-call burn shape")
        return out

    if truncated_turns:
        out["classification"] = CLASS_TRUNCATED_OTHER
        out["reason"] = f"turn(s) {truncated_turns} truncated, not turn 1"
        return out

    row_turns = row.get("turns")
    complete = (isinstance(row_turns, int) and not isinstance(row_turns, bool)
                and row_turns > 0 and len(turns) == row_turns
                and turns == list(range(1, row_turns + 1)))
    if unusable or malformed or not complete:
        out["classification"] = CLASS_UNKNOWN_INCOMPLETE
        out["reason"] = ("no truncation was observed, but the turn records are malformed, "
                         "unusable, duplicated or do not cover exactly turns 1..row.turns: "
                         "the cell is left undecided rather than called no_truncation")
        return out

    # The row carries its own cell-level truncation total written by the runner. It is
    # independent evidence, and a `no_truncation` verdict is only sound when the two
    # agree: a row that records truncation the per-turn list cannot account for is a
    # gap, not a clean cell. Observed truncation is still positive evidence (the
    # branches above return first), so this only ever closes the healthy verdict.
    row_truncated_total = row.get("completion_truncated_turns")
    if not isinstance(row_truncated_total, int) or isinstance(row_truncated_total, bool):
        out["classification"] = CLASS_UNKNOWN_INCOMPLETE
        out["reason"] = ("no truncation was observed in the turn records, but the row does "
                         "not record a cell-level `completion_truncated_turns` total: the "
                         "cell is left undecided rather than called no_truncation")
        return out
    if row_truncated_total:
        out["classification"] = CLASS_UNKNOWN_INCOMPLETE
        out["reason"] = (f"no truncation was observed in the turn records, but the row "
                         f"records completion_truncated_turns={row_truncated_total}: the "
                         "per-turn record cannot account for the row's own truncation "
                         "total, so the cell is left undecided rather than called "
                         "no_truncation")
        return out

    out["classification"] = CLASS_NO_TRUNCATION
    out["reason"] = "every recorded turn is complete and none truncated"
    return out


def analyze(payload: dict, rows: list[dict], cap_tokens: int | None, source: Path) -> dict:
    cells = [classify_cell(row, cap_tokens) for row in rows]
    per_condition: dict[str, dict] = {}
    for cell in cells:
        condition = str(cell.get("condition"))
        bucket = per_condition.setdefault(condition, {
            "cells": 0,
            "recorded_cells": 0,
            "classification_counts": Counter(),
            "truncated_cells": 0,
            "turn1_zero_tool_truncated_cells": 0,
        })
        bucket["cells"] += 1
        if cell["recorded"]:
            bucket["recorded_cells"] += 1
        bucket["classification_counts"][cell["classification"]] += 1
        if cell["classification"] in (CLASS_REASONING_BURN, CLASS_BUDGET_BURN):
            bucket["truncated_cells"] += 1
            bucket["turn1_zero_tool_truncated_cells"] += 1
        elif cell["classification"] == CLASS_TRUNCATED_OTHER:
            bucket["truncated_cells"] += 1

    for bucket in per_condition.values():
        bucket["classification_counts"] = {
            name: bucket["classification_counts"].get(name, 0) for name in CLASSIFICATIONS
        }
        bucket["unknown_cells"] = (bucket["classification_counts"][CLASS_UNKNOWN_FIELD_MISSING]
                                   + bucket["classification_counts"][CLASS_UNKNOWN_INCOMPLETE])

    truncated = [
        {
            **cell_identity(cell),
            "classification": cell["classification"],
            "reason": cell["reason"],
            "finish_reason": (cell["evidence"]["first_turn"] or {}).get("finish_reason")
                             if cell["evidence"]["first_turn"] else None,
            "completion_tokens": (cell["evidence"]["first_turn"] or {}).get("completion_tokens")
                                 if cell["evidence"]["first_turn"] else None,
            "cap_tokens": cell["evidence"]["cap_tokens"],
            "cap_reached": cell["evidence"].get("cap_reached"),
            "reasoning_returned": (cell["evidence"]["first_turn"] or {}).get("reasoning_returned")
                                  if cell["evidence"]["first_turn"] else None,
            "reasoning_chars": (cell["evidence"]["first_turn"] or {}).get("reasoning_chars")
                               if cell["evidence"]["first_turn"] else None,
            "tool_call_count": (cell["evidence"]["first_turn"] or {}).get("tool_call_count")
                               if cell["evidence"]["first_turn"] else None,
            "request_ms": (cell["evidence"]["first_turn"] or {}).get("request_ms")
                          if cell["evidence"]["first_turn"] else None,
            "truncated_turn_numbers": cell["evidence"]["truncated_turn_numbers"],
            "row_completion_truncated_turns": cell["evidence"]["row_completion_truncated_turns"],
        }
        for cell in cells
        if cell["classification"] in (CLASS_REASONING_BURN, CLASS_BUDGET_BURN, CLASS_TRUNCATED_OTHER)
    ]

    recorded = sum(1 for c in cells if c["recorded"])
    warnings = []
    if rows and recorded == 0:
        warnings.append(
            "no row in this artifact carries usable per-turn diagnostics: every cell "
            "is unknown_field_missing. This is the expected result for an artifact "
            "written before the per-turn change; it is NOT evidence of no truncation."
        )
    elif recorded < len(rows):
        warnings.append(f"{len(rows) - recorded}/{len(rows)} rows have no usable "
                        "per-turn diagnostics; their truncation cause is unknown.")

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "bytes": source.stat().st_size,
            "artifact_schema": payload.get("schema"),
            "artifact_mode": payload.get("mode"),
            "artifact_generated_at": payload.get("generated_at"),
            "rows": len(rows),
            "rows_with_turn_diagnostics": recorded,
            "cap_tokens": cap_tokens,
        },
        "method": {
            "unit": "one row = one cell (task_id, condition, seed, run_index, source_run)",
            "primary_evidence": "row['turn_diagnostics'] written by "
                                "bench/aci/runners/live_agent_loop.py",
            "reasoning": "reported only when the endpoint returned a reasoning field; "
                         "never derived from completion tokens",
            "classifications": CLASSIFICATION_LEGEND,
        },
        "limitations": LIMITATIONS,
        "warnings": warnings,
        "per_condition": per_condition,
        "truncated_cells": truncated,
        "cells": cells,
    }


def summarize(report: dict) -> str:
    lines = []
    info = report["input"]
    lines.append(f"input: {info['path']} (sha256 {info['sha256'][:16]}..., {info['bytes']} bytes)")
    lines.append(f"artifact: schema={info['artifact_schema']} mode={info['artifact_mode']} "
                 f"generated_at={info['artifact_generated_at']}")
    lines.append(f"rows: {info['rows']} | rows with usable per-turn diagnostics: "
                 f"{info['rows_with_turn_diagnostics']} | cap_tokens={info['cap_tokens']}")
    lines.append("")
    lines.append("== per condition ==")
    for condition, bucket in sorted(report["per_condition"].items()):
        lines.append(f"{condition}: cells={bucket['cells']} recorded={bucket['recorded_cells']} "
                     f"unknown={bucket['unknown_cells']} truncated={bucket['truncated_cells']}")
        for name, count in bucket["classification_counts"].items():
            lines.append(f"    {name:<42} {count}")
    lines.append("")
    lines.append(f"== truncated cells ({len(report['truncated_cells'])}) ==")
    if not report["truncated_cells"]:
        lines.append("    none (or none classifiable from this artifact)")
    for cell in report["truncated_cells"]:
        lines.append(
            f"    {cell['task_id']} [{cell['condition']}] run={cell['run_index']} "
            f"seed={cell['seed']} source_run={cell['source_run']} "
            f"{cell['classification']} finish_reason={cell['finish_reason']} "
            f"completion_tokens={cell['completion_tokens']} "
            f"reasoning_returned={cell['reasoning_returned']} "
            f"reasoning_chars={cell['reasoning_chars']} "
            f"tool_calls={cell['tool_call_count']} "
            f"truncated_turns={cell['truncated_turn_numbers']} "
            f"row_truncated_turns={cell['row_completion_truncated_turns']}"
        )
    for warning in report["warnings"]:
        lines.append("")
        lines.append(f"WARNING: {warning}")
    lines.append("")
    lines.append("== limitations ==")
    for item in report["limitations"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                    help="stored live run artifact to diagnose (read-only)")
    ap.add_argument("--out", type=Path, default=None,
                    help="where to write the machine-readable report; stdout still "
                         "gets the summary")
    args = ap.parse_args(argv)

    source: Path = args.input
    if not source.is_file():
        print(f"ERROR: input artifact not found: {source}", file=sys.stderr)
        return 1
    if args.out is not None and args.out.resolve() == source.resolve():
        print("ERROR: --out must not be the input artifact; this tool never rewrites "
              "its input.", file=sys.stderr)
        return 2
    try:
        payload, rows, cap_tokens = load_artifact(source)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {source}: {exc}", file=sys.stderr)
        return 2

    report = analyze(payload, rows, cap_tokens, source)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    print(summarize(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
