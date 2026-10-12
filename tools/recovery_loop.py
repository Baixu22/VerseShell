#!/usr/bin/env python3
"""Measure the failure-recovery loop from stored rows: after the FIRST failed
tool call, how many further tool calls until the same operation succeeds (or the
task completes)?  Read-only, no model calls.

Failure signals, per arm:
  - verseshell_aci: trajectory step has aci_ok === False (or an error_code)
  - raw_shell:      the stored observation text carries "[EXIT: <n>]" with n != 0
A 'recovery' is the next call of the same op that succeeds, or a successful
task_complete. 'attempts_to_recover' counts calls between the failure and that
recovery (inclusive of the recovering call).
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

EXIT_RE = re.compile(r"\[EXIT:\s*(-?\d+)\]")

def load_rows(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    # Accept either a JSONL checkpoint or a single merged JSON object.
    if path.suffix == ".jsonl":
        return [r for r in (json.loads(l) for l in text.splitlines() if l.strip())
                if r.get("task_id")]
    payload = json.loads(text)
    return [r for r in (payload.get("rows") or []) if r.get("task_id")]

def step_ok(step, row, base_dir: Path):
    """Return True/False/None for a tool step (None = no signal)."""
    if step.get("op") == "task_complete":
        return None
    if row.get("condition") == "verseshell_aci":
        if step.get("aci_ok") is False or step.get("error_code"):
            return False
        if step.get("aci_ok") is True:
            return True
        return None
    # raw_shell: read the stored observation text
    obs = step.get("observation") or {}
    p = obs.get("path")
    if not p:
        return None
    try:
        text = (base_dir / p).read_text(encoding="utf-8")
    except OSError:
        return None
    m = EXIT_RE.search(text)
    if not m:
        return None
    return m.group(1) == "0"

def analyse(rows, base_dir: Path):
    out = []
    for r in rows:
        traj = r.get("trajectory") or []
        first_fail = None
        for i, s in enumerate(traj):
            if step_ok(s, r, base_dir) is False:
                first_fail = i
                break
        rec = {"task_id": r["task_id"], "condition": r["condition"],
               "success": r.get("success"), "stop_reason": r.get("stop_reason"),
               "calls": len(traj), "first_fail_index": first_fail,
               "attempts_to_recover": None, "recovered": False}
        if first_fail is not None:
            fail_op = traj[first_fail].get("op")
            for j in range(first_fail + 1, len(traj)):
                s = traj[j]
                if s.get("op") == "task_complete" and r.get("success") is True:
                    rec["recovered"] = True
                    rec["attempts_to_recover"] = j - first_fail
                    break
                if s.get("op") == fail_op and step_ok(s, r, base_dir) is True:
                    rec["recovered"] = True
                    rec["attempts_to_recover"] = j - first_fail
                    break
        out.append(rec)
    return out

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    rows = load_rows(a.input)
    cells = analyse(rows, a.input.parent)
    # aggregate per condition
    agg = {}
    for c in sorted({x["condition"] for x in cells}):
        sub = [x for x in cells if x["condition"] == c]
        withfail = [x for x in sub if x["first_fail_index"] is not None]
        rec = [x for x in withfail if x["recovered"]]
        att = [x["attempts_to_recover"] for x in rec]
        agg[c] = {
            "runs": len(sub), "runs_with_failure": len(withfail),
            "runs_recovered": len(rec),
            "mean_attempts_to_recover": round(sum(att)/len(att), 2) if att else None,
            "median_attempts_to_recover": sorted(att)[len(att)//2] if att else None,
        }
    report = {"schema": "verseshell.recovery-loop/v1",
              "source": str(a.input), "aggregate": agg, "cells": cells}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=1))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
