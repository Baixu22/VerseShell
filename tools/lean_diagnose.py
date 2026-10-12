#!/usr/bin/env python3
"""Lean live diagnosis: small fixed matrix, then compact failure locations.

This is deliberately NOT the formal repeated study.  It answers:
  * which task/condition/variant is failing;
  * whether the failure is endpoint/cap/repeat-call/turn-limit related;
  * whether result.query was used and with which handle form.

Use --from-jsonl to analyse an existing checkpoint with zero API calls.
Use the normal mode to run 3 known problem tasks x 3 conditions x 1 variant x 1 seed.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_ROUND = ROOT / "tools" / "live_round.py"
DEFAULT_ENV = Path(r"D:\VerseShellLive\secrets\stepfun-step5p-20261010.env")
DEFAULT_TASKS = ",".join([
    "node_envconfig_validate_dd681123",
    "js_leaderboard_rank_b1603acf",
    "python_csvlite_parse_80d158b2",
])
DEFAULT_CONDITIONS = "raw_shell,verseshell_aci"


PASS_MARKERS = (
    re.compile(r"#\s*pass\s+\d+"),
    re.compile(r"test result:\s*ok", re.IGNORECASE),
    re.compile(r"all tests? passed", re.IGNORECASE),
    re.compile(r"\b\d+ passed\b", re.IGNORECASE),
)
FAIL_MARKERS = (
    re.compile(r"#\s*fail\s+[1-9]"),
    re.compile(r"\b\d+ failed\b", re.IGNORECASE),
    re.compile(r"\bFAILED\b"),
)


def local_test_result(text: str) -> str:
    """Classify only obvious local test-result markers; unknown is not a success."""
    if not text:
        return "unknown"
    passed = any(pattern.search(text) for pattern in PASS_MARKERS)
    failed = any(pattern.search(text) for pattern in FAIL_MARKERS)
    if passed and not failed:
        return "passed"
    if failed:
        return "failed"
    return "unknown"


def repeated_call_summary(steps: list[dict]) -> tuple[int, dict | None]:
    counts = collections.Counter()
    previous = None
    best = streak = 0
    for step in steps:
        signature = json.dumps([step.get("op"), step.get("args")], sort_keys=True, ensure_ascii=False)
        counts[signature] += 1
        streak = streak + 1 if signature == previous else 1
        best = max(best, streak)
        previous = signature
    if not counts:
        return 0, None
    signature, count = counts.most_common(1)[0]
    op, args = json.loads(signature)
    return best, {"count": count, "op": op, "args": args}


def failure_class(cell: dict) -> str:
    """Classify a cell without claiming causality or formal eligibility."""
    if cell.get("endpoint_failure"):
        return "endpoint_failure"
    if cell.get("success") is True:
        return "ok"
    stop = cell.get("stop_reason")
    if cell.get("first_local_pass_turn") is not None and stop == "task_complete":
        return "scored_failure_after_local_pass"
    if cell.get("first_local_pass_turn") is not None and cell.get("calls_after_first_local_pass", 0) > 0:
        return "passed_then_continued"
    if stop == "repeat_call_limit":
        return "pre_success_repeat_loop"
    if stop == "turn_limit":
        return "pre_success_turn_thrash"
    if stop == "completion_limit":
        return "completion_before_pass"
    return "unknown"


def summarize_rows(rows: list[dict], max_turns: int, max_tokens: int, base_dir: Path | None = None) -> dict:
    success = collections.Counter()
    stops = collections.Counter()
    endpoint = 0
    completion_truncated = 0
    turn_capped = 0
    repeat_capped = 0
    query_calls = 0
    query_ok = 0
    query_handle_forms = collections.Counter()
    cells = []
    malformed = 0
    pass_marker_cells = 0
    continued_after_pass_cells = 0
    for row in rows:
        if not row.get("task_id") or not row.get("condition"):
            malformed += 1
            continue
        ok = row.get("success")
        success["true" if ok is True else "false" if ok is False else "unknown"] += 1
        stop = row.get("stop_reason") or "unknown"
        stops[stop] += 1
        row_endpoint = bool(row.get("api_error") or row.get("endpoint_status") or row.get("row_class") == "endpoint_failure")
        endpoint += int(row_endpoint)
        ct = int(row.get("completion_truncated_turns") or 0)
        completion_truncated += ct
        tc = int((row.get("turns") or 0) >= max_turns)
        turn_capped += tc
        repeat_capped += int(stop == "repeat_call_limit")
        trajectory = row.get("trajectory") or []
        for step in trajectory:
            if step.get("op") != "result.query":
                continue
            query_calls += 1
            args = step.get("args") or {}
            handle = str(args.get("handle", ""))
            if handle.startswith("result://sha256/"):
                query_handle_forms["canonical"] += 1
            elif handle.startswith("result://sha256:"):
                query_handle_forms["colon_alias"] += 1
            else:
                query_handle_forms["invalid_or_other"] += 1
            # The stored observation is best-effort: missing observation is unknown,
            # never silently counted as success.
            obs = step.get("observation") or {}
            path = obs.get("path")
            if path and base_dir is not None:
                try:
                    obs_path = Path(path)
                    if not obs_path.is_absolute():
                        obs_path = base_dir / obs_path
                    observed = json.loads(obs_path.read_text(encoding="utf-8-sig"))
                    query_ok += int(bool((observed.get("envelope") or {}).get("ok")))
                except Exception:
                    pass

        longest_repeat, top_repeat = repeated_call_summary(trajectory)
        first_pass_turn = None
        calls_after_first_pass = 0
        for turn, step in enumerate(trajectory, start=1):
            observation = step.get("observation")
            text = ""
            if base_dir is not None and isinstance(observation, dict) and isinstance(observation.get("path"), str):
                try:
                    text = json.loads((base_dir / observation["path"]).read_text(encoding="utf-8")).get("text", "")
                except Exception:
                    pass
            if first_pass_turn is None and local_test_result(text) == "passed":
                first_pass_turn = turn
            elif first_pass_turn is not None:
                calls_after_first_pass += 1
        pass_marker_cells += int(first_pass_turn is not None)
        continued_after_pass_cells += int(first_pass_turn is not None and calls_after_first_pass > 0)
        cells.append({
            "task_id": row.get("task_id"),
            "condition": row.get("condition"),
            "variant": row.get("prompt_variant"),
            "success": ok,
            "stop_reason": stop,
            "turns": row.get("turns"),
            "tool_calls": row.get("tool_calls"),
            "completion_truncated_turns": ct,
            "turn_capped": bool(tc),
            "endpoint_failure": row_endpoint,
            "max_identical_call_streak": longest_repeat,
            "top_repeated_call": top_repeat,
            "first_local_pass_turn": first_pass_turn,
            "calls_after_first_local_pass": calls_after_first_pass,
        })
        cells[-1]["failure_class"] = failure_class(cells[-1])
    classes = collections.Counter(cell["failure_class"] for cell in cells)
    return {
        "schema": "verseshell.lean-diagnosis/v1",
        "rows": len(rows),
        "malformed_rows": malformed,
        "valid_rows": len(cells),
        "max_turns": max_turns,
        "max_tokens": max_tokens,
        "success": dict(success),
        "stop_reasons": dict(stops),
        "endpoint_failures": endpoint,
        "completion_truncated_turns": completion_truncated,
        "turn_capped_rows": turn_capped,
        "repeat_capped_rows": repeat_capped,
        "result_query_calls": query_calls,
        "result_query_ok": query_ok,
        "result_query_handle_forms": dict(query_handle_forms),
        "local_pass_marker_cells": pass_marker_cells,
        "continued_after_local_pass_cells": continued_after_pass_cells,
        "failure_classes": dict(classes),
        "cells": cells,
    }


def summarize_jsonl(path: Path, max_turns: int, max_tokens: int) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return summarize_rows(rows, max_turns, max_tokens, path.parent)


def build_command(args) -> list[str]:
    cmd = [sys.executable, str(LIVE_ROUND), "--tag", args.tag,
           "--env-file", str(args.env_file), "--model", args.model,
           "--task-set", str(args.task_set), "--tasks", args.tasks,
           "--prompt-variant", args.prompt_variant, "--order-seed", str(args.order_seed),
           "--seeds", str(args.seed), "--arms", "with", "--conditions", args.conditions,
           "--repeat-call-limit", str(args.repeat_call_limit),
           "--max-turns", str(args.max_turns), "--max-tokens", str(args.max_tokens)]
    if args.analysis_plan:
        cmd += ["--analysis-plan", str(args.analysis_plan)]
    if args.preflight:
        cmd += ["--preflight", str(args.preflight)]
    if args.probe_report:
        cmd += ["--probe-report", str(args.probe_report)]
    if args.dry_run:
        cmd += ["--dry-run"]
    return cmd


def write_report(out_dir: Path, summary: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diagnosis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Lean live diagnosis", "",
             f"- rows: {summary['rows']}",
             f"- success: `{json.dumps(summary['success'], ensure_ascii=False)}`",
             f"- stop reasons: `{json.dumps(summary['stop_reasons'], ensure_ascii=False)}`",
             f"- endpoint failures: {summary['endpoint_failures']}",
             f"- completion truncated turns: {summary['completion_truncated_turns']}",
             f"- turn-capped rows: {summary['turn_capped_rows']}",
             f"- repeat-capped rows: {summary['repeat_capped_rows']}",
             f"- result.query calls: {summary['result_query_calls']}",
             f"- result.query handle forms: `{json.dumps(summary['result_query_handle_forms'], ensure_ascii=False)}`",
             "", "| task | condition | variant | success | stop | turns | tools | comp_trunc |",
             "|---|---|---|---:|---|---:|---:|---:|"]
    for cell in summary["cells"]:
        lines.append("| {task_id} | {condition} | {variant} | {success} | {stop_reason} | {turns} | {tool_calls} | {completion_truncated_turns} |".format(**cell))
    (out_dir / "diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--from-jsonl", type=Path,
                    help="analyse an existing rows.jsonl checkpoint; no model calls")
    ap.add_argument("--tag", help="collection tag for a live run")
    ap.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    ap.add_argument("--model", default="step-5-preview")
    ap.add_argument("--task-set", type=Path, default=ROOT / "bench/aci/task_sets/3.1.0.json")
    ap.add_argument("--tasks", default=DEFAULT_TASKS)
    ap.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    ap.add_argument("--prompt-variant", default="baseline", choices=["baseline", "compact", "compact_all", "shell_guided", "shell_safe"])
    ap.add_argument("--order-seed", type=int, default=42)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--repeat-call-limit", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=24)
    ap.add_argument("--max-tokens", type=int, default=16384)
    ap.add_argument("--analysis-plan", type=Path)
    ap.add_argument("--preflight", type=Path)
    ap.add_argument("--probe-report", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.from_jsonl:
        summary = summarize_jsonl(args.from_jsonl, args.max_turns, args.max_tokens)
        out_dir = args.out_dir or (args.from_jsonl.parent / f"{args.from_jsonl.stem}-lean")
        write_report(out_dir, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if not args.tag:
        args.tag = f"step5p-lean-{time.strftime('%Y%m%d-%H%M%S')}"
    if not args.env_file.exists():
        ap.error(f"env file does not exist: {args.env_file}")
    cmd = build_command(args)
    print("lean command:", " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 or args.dry_run:
        return rc
    latest = ROOT / "bench/aci/results" / args.tag / "latest_live.json"
    if not latest.exists():
        print(f"ERROR: missing {latest}", file=sys.stderr)
        return 2
    payload = json.loads(latest.read_text(encoding="utf-8-sig"))
    summary = summarize_rows(payload.get("rows") or [], args.max_turns, args.max_tokens, latest.parent)
    out_dir = args.out_dir or latest.parent / "lean-diagnosis"
    write_report(out_dir, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "cells"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
