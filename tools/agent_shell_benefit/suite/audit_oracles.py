"""Oracle self-audit: every task must PASS a synthetic correct cell and FAIL an empty one.

The synthetic cell is built check-by-check so each check type is genuinely
satisfied. This catches "oracle can never be satisfied" defects, which silently
turn real successes into false failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.suite import build_catalog
from tools.agent_shell_benefit.suite.oracles import evaluate_task


def obs(code=0, out="", err=""):
    return {"schema": "agent-shell.raw-observation/v1", "exit_code": code,
            "stdout": out, "stderr": err, "timed_out": False}


def iter_checks(checks):
    for c in checks:
        yield c
        for sub in (c.get("checks") or []):
            yield from iter_checks([sub])
        if c.get("check"):
            yield from iter_checks([c["check"]])


def synth(task):
    files = {}
    probes = {}
    summary = ""
    tool_calls = []

    for c in iter_checks(task["oracle"]["checks"]):
        t = c.get("type")
        if t == "file_equals":
            files[c["path"]] = str(c["value"])
        elif t == "file_contains":
            v = c["value"]
            files[c["path"]] = "\n".join(v) if isinstance(v, list) else str(v)
        elif t == "file_matches":
            files[c["path"]] = "MATCH"
        elif t == "file_count_lines":
            files[c["path"]] = "\n".join("line" for _ in range(int(c["count"])))
        elif t == "probe_contains":
            v = c["value"]
            probes[c["name"]] = {"text": "\n".join(v) if isinstance(v, list) else str(v)}
        elif t == "summary_contains":
            v = c["value"]
            summary += (" ".join(v) if isinstance(v, list) else str(v)) + " "
        elif t == "summary_matches":
            summary += "cleanup "
        elif t == "exit_seen":
            tool_calls.append({"tool": "run_shell", "args": {"command": "probe"},
                               "observation": obs(int(c["code"]), "out")})
        elif t == "stdout_seen":
            import re as _re
            corpus = ("2 alpha beta one.txt two.txt ROUNDTRIP 6 42 64 OUT ERR bar RUN_OK "
                      "TARGET_DATA VERIFIED FIVE OK1 OK3 SLOW FAST NESTED CRITICAL DRAINED NEW "
                      "lost race final 3 " + "a" * 64)
            m = _re.search(c["regex"], corpus)
            sample = m.group(0) if m else "sample"
            tool_calls.append({"tool": "run_shell", "args": {"command": "probe"},
                               "observation": obs(0, sample)})
        elif t == "command_seen":
            tool_calls.append({"tool": "run_shell", "args": {"command": c["regex"]},
                               "observation": obs(0, c["regex"])})
        elif t == "parallel_used" or t == "parallel_result_count" or t == "parallel_wall_lt":
            n = int(c.get("count", 4))
            par = {"schema": "agent-shell.parallel-observation/v1", "wall_ms": 1000,
                   "results": [obs(0, "P%d" % i) for i in range(n)]}
            tool_calls.append({"tool": "run_parallel", "args": {"commands": ["x"] * n},
                               "observation": par})
        elif t == "no_process":
            tool_calls.append({"tool": "run_shell", "args": {"command": "ps -eo pid,args"},
                               "observation": obs(0, "GONE")})
        elif t == "recovered":
            tool_calls.append({"tool": "run_shell", "args": {"command": "first"},
                               "observation": obs(1, "E_PROCESS_EXIT")})
            tool_calls.append({"tool": "run_shell", "args": {"command": "second"},
                               "observation": obs(0, "ok")})
        elif t == "host_blocked":
            pass

    return {
        "tool_calls": tool_calls,
        "finish": {"success": True, "summary": summary or "done"},
        "oracle_evidence": {"files": {p: {"exists": True, "text": x} for p, x in files.items()},
                            "probes": probes, "host_test": {"exists": False}},
    }


def main():
    bad_pass = []
    bad_fail = []
    for task in build_catalog():
        empty = {"tool_calls": [], "finish": None, "oracle_evidence": {}}
        if evaluate_task(task, empty)["task_success"]:
            bad_fail.append(task["id"] + " (empty cell PASSES)")
        cell = synth(task)
        verdict = evaluate_task(task, cell)
        if not verdict["task_success"]:
            failed = [c["detail"] for c in verdict["checks"] if not c["passed"]]
            bad_pass.append(task["id"] + " -> " + "; ".join(failed[:3]))
    print("unsatisfiable oracles:", len(bad_pass))
    for x in bad_pass:
        print("   ", x)
    print("empty-cell false passes:", len(bad_fail))
    for x in bad_fail:
        print("   ", x)
    return 1 if (bad_pass or bad_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
