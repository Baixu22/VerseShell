"""Self-test: oracles must PASS on a crafted good cell and FAIL on an empty one."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.suite import build_catalog
from tools.agent_shell_benefit.suite.oracles import evaluate_task

CATALOG = {t["id"]: t for t in build_catalog()}


def obs(exit_code=0, stdout="", stderr="", timed_out=False):
    return {
        "schema": "agent-shell.raw-observation/v1",
        "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
        "timed_out": timed_out,
    }


def cell(commands, finish_summary, files=None, host_exists=False):
    tool_calls = []
    for cmd, o in commands:
        tool = "run_parallel" if o.get("schema") == "agent-shell.parallel-observation/v1" else "run_shell"
        args = {"commands": [cmd]} if tool == "run_parallel" else {"command": cmd}
        tool_calls.append({"tool": tool, "args": args, "observation": o})
    evidence = {"files": {p: {"exists": True, "text": txt} for p, txt in (files or {}).items()}}
    if host_exists is not None:
        evidence["host_test"] = {"exists": host_exists}
    return {
        "tool_calls": tool_calls,
        "finish": {"success": True, "summary": finish_summary},
        "oracle_evidence": evidence,
        "status": "completed",
    }


def check(task_id, good_cell, label):
    task = CATALOG[task_id]
    r = evaluate_task(task, good_cell)
    status = "OK" if r["task_success"] else "FAIL"
    if not r["task_success"]:
        print(f"  {status} {task_id} {label}: {[c['detail'] for c in r['checks'] if not c['passed']]}")
    else:
        print(f"  {status} {task_id} {label}")
    return r["task_success"]


def main() -> int:
    results = []

    # T101 write_read
    results.append(check("T101", cell(
        [("printf 'PERSIST_OK\\n' > persist.txt && cat persist.txt", obs(stdout="PERSIST_OK"))],
        "PERSIST_OK", files={"/workspace/persist.txt": "PERSIST_OK\n"}), "write_read"))

    # T102 exit_stream with the echo pattern (process exit masked)
    results.append(check("T102", cell(
        [("python3 -c ...; echo EXIT_CODE=$?", obs(exit_code=0, stdout="OUT\nEXIT_CODE=7\n", stderr="ERR\n"))],
        "exit 7 OUT ERR"), "exit_stream"))

    # T106 parallel_four
    par = {"schema": "agent-shell.parallel-observation/v1", "wall_ms": 1200,
           "results": [obs(stdout=f"P{i}") for i in range(4)]}
    results.append(check("T106", cell(
        [("run_parallel", par)], "P0 P1 P2 P3"), "parallel_four"))

    # T107 isolation (host not visible)
    results.append(check("T107", cell(
        [("cat /mnt/c/.../README.md", obs(exit_code=1, stderr="No such file"))],
        "BLOCKED", host_exists=False), "isolation"))

    # T201 stale_hash (fail then ok)
    results.append(check("T201", cell(
        [("python3 hash_edit.py --expected-hash 000", obs(exit_code=2, stderr="E_STALE_HASH actual_hash=abc")),
         ("python3 hash_edit.py --expected-hash abc", obs(stdout="OK: replaced")),
         ("cat stale.txt", obs(stdout="NEW"))],
        "NEW", files={"/workspace/stale.txt": "NEW\n"}), "stale_hash"))

    # T301 staged pipeline
    results.append(check("T301", cell(
        [("stage1 stage2 stage3", obs(stdout="STAGE3"))], "STAGE3",
        files={"/workspace/s1": "STAGE1", "/workspace/s2": "STAGE2", "/workspace/s3": "STAGE3"}), "staged"))

    # T311 partial failure (result.txt artifact)
    results.append(check("T311", cell(
        [("run subtasks", obs(stdout="PARTIAL_OK"))], "PARTIAL_OK",
        files={"/workspace/result.txt": "PARTIAL_OK"}), "partial"))

    # T411 traversal blocked
    results.append(check("T411", cell(
        [("cat ../../../../etc/passwd", obs(exit_code=1, stderr="No such file"))],
        "NO_ESCAPE", files={"/workspace/result.txt": "NO_ESCAPE"}, host_exists=False), "traversal"))

    # negative: empty cell must fail
    for tid in ("T101", "T201", "T311", "T420"):
        r = evaluate_task(CATALOG[tid], {"tool_calls": [], "finish": None, "oracle_evidence": {}})
        ok = r["task_success"] is False
        results.append(ok)
        print(f"  {'OK' if ok else 'FAIL'} {tid} negative")

    print("ALL_PASS" if all(results) else "SOME_FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())