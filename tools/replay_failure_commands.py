#!/usr/bin/env python3
"""Replay stored raw-shell failures in a fresh workspace, without model calls.

Safety: the default is a dry run.  --execute is required to run command strings,
and every command runs in a fresh temp workspace with a bounded timeout.
This is a diagnostic, not a re-scoring or formal-acceptance tool.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bench/aci/runners"), str(ROOT / "tools")]
import live_agent_loop as h  # noqa: E402
import lean_diagnose as lean  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    return payload.get("rows") or []


def select_cells(rows: list[dict], args) -> list[dict]:
    selected = []
    for row in rows:
        if not row.get("task_id"):
            continue
        if args.task and row.get("task_id") not in args.task:
            continue
        if args.condition and row.get("condition") not in args.condition:
            continue
        if args.variant and row.get("prompt_variant") not in args.variant:
            continue
        if args.seed is not None and row.get("seed") != args.seed:
            continue
        if not args.include_complete and row.get("stop_reason") == "task_complete":
            continue
        selected.append(row)
    return selected


def replay_command(command: str, workspace: Path, timeout: int) -> dict:
    try:
        rc, out, err, timed = h.run_bounded(command, timeout=timeout, cwd=str(workspace), shell=True,
                                            env=h.grading_environment(workspace))
        out_text, out_encoding, out_lossy = h.decode_shell_output(out)
        err_text, err_encoding, err_lossy = h.decode_shell_output(err)
    except Exception as exc:
        return {"exit_code": None, "timed_out": False, "error": f"{type(exc).__name__}: {exc}",
                "stdout": "", "stderr": "", "syntax_error": False}
    combined = out_text + "\n" + err_text
    syntax_error = bool(re.search(
        r"ParserError|SyntaxError|unterminated|TerminatorExpected|not recognized|"
        r"不是内部或外部命令|系统找不到指定的路径|No such file or directory",
        combined, re.IGNORECASE))
    return {"exit_code": rc, "timed_out": timed, "stdout": out_text, "stderr": err_text,
            "stdout_encoding": out_encoding, "stderr_encoding": err_encoding,
            "stdout_lossy": out_lossy, "stderr_lossy": err_lossy,
            "syntax_error": syntax_error, "local_test_result": lean.local_test_result(combined)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--task", action="append")
    ap.add_argument("--condition", action="append", choices=["raw_shell", "raw_shell_coached", "verseshell_aci"])
    ap.add_argument("--variant", action="append", choices=["baseline", "compact", "compact_all", "shell_guided"])
    ap.add_argument("--seed", type=int)
    ap.add_argument("--include-complete", action="store_true")
    ap.add_argument("--execute", action="store_true", help="actually replay commands in temp workspaces")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args(argv)

    rows = select_cells(load_rows(args.input), args)
    if not rows:
        ap.error("no matching failed cells")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for index, row in enumerate(rows):
        task_id = row["task_id"]
        task_path = ROOT / "bench/aci/tasks" / f"{task_id}.json"
        task = json.loads(task_path.read_text(encoding="utf-8-sig"))
        workspace = h.prepare_workspace(task["workspace_fixture"])
        steps = []
        try:
            for turn, step in enumerate(row.get("trajectory") or [], start=1):
                if step.get("op") != "run_command":
                    steps.append({"turn": turn, "op": step.get("op"), "skipped": "not raw shell"})
                    continue
                command = (step.get("args") or {}).get("command", "")
                record = {"turn": turn, "op": "run_command", "command": command, "identical_call_run": step.get("identical_call_run")}
                if args.execute:
                    record.update(replay_command(command, workspace, args.timeout))
                steps.append(record)
            verdict, reason = h.check_success(task.get("success") or {}, workspace) if args.execute else (None, "dry run")
            reports.append({"task_id": task_id, "condition": row.get("condition"), "variant": row.get("prompt_variant"),
                            "seed": row.get("seed"), "recorded_stop": row.get("stop_reason"),
                            "recorded_success": row.get("success"), "replay_success": verdict, "replay_reason": reason,
                            "steps": steps})
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    out = args.out_dir / "replay.json"
    out.write_text(json.dumps({"schema": "verseshell.failure-replay/v1", "execute": args.execute,
                               "cells": reports}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Stored failure replay", "", f"- execute: {args.execute}", f"- cells: {len(reports)}", ""]
    for report in reports:
        lines += [f"## {report['task_id']} / {report['condition']} / {report['variant']}",
                  f"- recorded stop={report['recorded_stop']} success={report['recorded_success']}",
                  f"- replay success={report['replay_success']} reason={report['replay_reason']}", ""]
        for step in report["steps"]:
            if step.get("skipped"):
                lines.append(f"- turn {step['turn']}: skipped {step['op']}")
                continue
            lines.append(f"- turn {step['turn']}: `{step['command'][:300]}`")
            if args.execute:
                lines.append(f"  exit={step.get('exit_code')} timeout={step.get('timed_out')} syntax={step.get('syntax_error')} local={step.get('local_test_result')}")
                if step.get("stderr"):
                    lines.append(f"  stderr: {step['stderr'][:300]}")
        lines.append("")
    (args.out_dir / "replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"cells": len(reports), "execute": args.execute, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
