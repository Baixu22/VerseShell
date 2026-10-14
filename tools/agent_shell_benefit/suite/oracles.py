"""Declarative assertion engine for the 80-task agent-shell suite.

Each task declares an oracle as a tree of checks. The engine evaluates the
checks against (a) the final sandbox state (evidence) and (b) the tool trace.
This keeps 80 tasks declarative instead of 80 bespoke Python functions.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..common import obs_ok, obs_stderr, obs_stdout, obs_timed_out

HOST_MARKERS = ("# VerseShell",)


def shell_calls(cell: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in cell.get("tool_calls", []) if item.get("tool") == "run_shell"]


def parallel_calls(cell: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in cell.get("tool_calls", []) if item.get("tool") == "run_parallel"]


def all_calls(cell: dict[str, Any]) -> list[dict[str, Any]]:
    return list(cell.get("tool_calls", []))


def call_text(call: dict[str, Any]) -> str:
    observation = call.get("observation") or {}
    if call.get("tool") == "run_parallel":
        parts = []
        for item in observation.get("results") or []:
            parts.append(obs_stdout(item) + "\n" + obs_stderr(item))
        return "\n".join(parts)
    return obs_stdout(observation) + "\n" + obs_stderr(observation)


def call_command(call: dict[str, Any]) -> str:
    return str((call.get("args") or {}).get("command") or "")


def trace_text(cell: dict[str, Any]) -> str:
    return "\n".join(call_text(call) for call in all_calls(cell))


def trace_commands(cell: dict[str, Any]) -> str:
    return "\n".join(call_command(call) for call in all_calls(cell))


def summary_of(cell: dict[str, Any]) -> str:
    return str((cell.get("finish") or {}).get("summary") or "")


ERROR_MARKERS = (
    "E_STALE_HASH",
    "E_AMBIGUOUS",
    "E_PROCESS_EXIT",
    "E_TIMEOUT",
    "No such file or directory",
    "Traceback (most recent call last)",
    "FAULT injected",
    "CRASH after",
)


def _text_has_error_marker(call: dict[str, Any]) -> bool:
    text = call_text(call)
    return any(marker in text for marker in ERROR_MARKERS)


def call_failed(call: dict[str, Any]) -> bool:
    observation = call.get("observation") or {}
    if call.get("tool") == "run_parallel":
        results = observation.get("results") or []
        failed = any(not obs_ok(item) for item in results) if results else True
    else:
        failed = not obs_ok(observation)
    return failed or _text_has_error_marker(call)


def first_error_index(cell: dict[str, Any]) -> int | None:
    for index, call in enumerate(cell.get("tool_calls", [])):
        if call.get("tool") in ("run_shell", "run_parallel") and call_failed(call):
            return index
    return None


def _file_text(evidence: dict[str, Any], path: str) -> str | None:
    entry = (evidence.get("files") or {}).get(path)
    if not entry:
        return None
    return entry.get("text")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _norm(text: str | None) -> str:
    return (text or "").replace("\r\n", "\n")


def eval_check(check: dict[str, Any], cell: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    kind = check.get("type")
    summary = summary_of(cell)
    text = trace_text(cell)
    commands = trace_commands(cell)

    if kind == "all_of":
        details = []
        ok = True
        for sub in check.get("checks") or []:
            sub_ok, sub_detail = eval_check(sub, cell, evidence)
            details.append(sub_detail)
            ok = ok and sub_ok
        return ok, "all_of[" + "; ".join(details) + "]"
    if kind == "any_of":
        details = []
        for sub in check.get("checks") or []:
            sub_ok, sub_detail = eval_check(sub, cell, evidence)
            if sub_ok:
                return True, "any_of(" + sub_detail + ")"
            details.append(sub_detail)
        return False, "any_of_none[" + "; ".join(details) + "]"
    if kind == "not":
        sub_ok, sub_detail = eval_check(check.get("check") or {}, cell, evidence)
        return (not sub_ok), "not(" + sub_detail + ")"

    if kind == "file_equals":
        got = _file_text(evidence, check["path"])
        want = check["value"]
        ok = got is not None and _norm(got).strip() == _norm(want).strip()
        return ok, "file_equals(" + check["path"] + ")=" + str(ok)
    if kind == "file_contains":
        got = _file_text(evidence, check["path"]) or ""
        ok = all(str(v) in got for v in _as_list(check.get("value")))
        return ok, "file_contains(" + check["path"] + ")=" + str(ok)
    if kind == "file_absent":
        got = _file_text(evidence, check["path"])
        ok = got is None
        return ok, "file_absent(" + check["path"] + ")=" + str(ok)
    if kind == "file_matches":
        got = _file_text(evidence, check["path"]) or ""
        ok = re.search(check["regex"], got, re.MULTILINE) is not None
        return ok, "file_matches(" + check["path"] + ")=" + str(ok)
    if kind == "file_count_lines":
        got = _file_text(evidence, check["path"]) or ""
        n = len([ln for ln in got.split("\n") if ln.strip() != ""])
        ok = n == int(check["count"])
        return ok, "file_lines(" + check["path"] + ")=" + str(n)

    if kind == "summary_contains":
        wanted = [str(v) for v in _as_list(check.get("value"))]
        ok = all(v in summary for v in wanted)
        return ok, "summary_contains=" + str(ok)
    if kind == "summary_matches":
        ok = re.search(check["regex"], summary, re.MULTILINE) is not None
        return ok, "summary_matches=" + str(ok)

    if kind == "stdout_seen":
        ok = re.search(check["regex"], text, re.MULTILINE) is not None
        return ok, "stdout_seen=" + str(ok)
    if kind == "exit_seen":
        want = int(check["code"])
        seen = False
        for call in all_calls(cell):
            observation = call.get("observation") or {}
            if observation.get("schema") == "verseshell.observation/v1":
                code = (observation.get("data") or {}).get("exit_code")
            elif call.get("tool") == "run_parallel":
                codes = []
                for r in (observation.get("results") or []):
                    if r.get("schema") == "verseshell.observation/v1":
                        codes.append((r.get("data") or {}).get("exit_code"))
                    else:
                        codes.append(r.get("exit_code"))
                code = want if want in codes else None
            else:
                code = observation.get("exit_code")
            if code == want:
                seen = True
                break
        if not seen:
            seen = re.search(r"\bEXIT_CODE=" + str(want) + r"\b", text) is not None
        return seen, "exit_seen(" + str(want) + ")=" + str(seen)

    if kind == "command_seen":
        ok = re.search(check["regex"], commands, re.MULTILINE) is not None
        return ok, "command_seen=" + str(ok)

    if kind == "tool_count_min":
        tool = check["tool"]
        count = len([c for c in all_calls(cell) if c.get("tool") == tool])
        ok = count >= int(check["count"])
        return ok, "tool_count_min(" + tool + "," + str(check["count"]) + ")=" + str(count)
    if kind == "tool_count_max":
        tool = check["tool"]
        count = len([c for c in all_calls(cell) if c.get("tool") == tool])
        ok = count <= int(check["count"])
        return ok, "tool_count_max(" + tool + "," + str(check["count"]) + ")=" + str(count)

    if kind == "parallel_used":
        ok = len(parallel_calls(cell)) >= int(check.get("count", 1))
        return ok, "parallel_used=" + str(ok)
    if kind == "parallel_wall_lt":
        limit = float(check["ms"])
        observed = []
        for call in parallel_calls(cell):
            wall = (call.get("observation") or {}).get("wall_ms")
            if isinstance(wall, (int, float)):
                observed.append(wall)
        ok = bool(observed) and min(observed) < limit
        return ok, "parallel_wall_lt(" + str(limit) + ")=" + str(min(observed) if observed else None)
    if kind == "parallel_result_count":
        want = int(check["count"])
        observed = [len((call.get("observation") or {}).get("results") or []) for call in parallel_calls(cell)]
        ok = bool(observed) and max(observed) >= want
        return ok, "parallel_result_count(" + str(want) + ")=" + str(observed)

    if kind == "no_process":
        pattern = check["pattern"]
        # Only the LAST process-listing call proves the end state. Scanning the
        # whole trace would match the legitimate still-alive observation that
        # precedes the kill.
        probes = [c for c in shell_calls(cell)
                  if re.search(r"\bps\b|pgrep|kill -0", call_command(c))]
        scanned = call_text(probes[-1]) if probes else ""
        ok = bool(probes) and re.search(pattern, scanned) is None
        return ok, "no_process(" + pattern + ")=" + str(ok)

    if kind == "probe_contains":
        entry = (evidence.get("probes") or {}).get(check["name"]) or {}
        got = entry.get("text") or ""
        ok = all(str(v) in got for v in _as_list(check.get("value")))
        return ok, "probe_contains(" + check["name"] + ")=" + str(ok)

    if kind == "host_blocked":
        ok = not any(marker in text for marker in HOST_MARKERS)
        if (evidence.get("host_test") or {}).get("exists"):
            ok = False
        return ok, "host_blocked=" + str(ok)

    if kind == "recovered":
        idx = first_error_index(cell)
        if idx is None:
            return False, "recovered(no_error)"
        for call in cell.get("tool_calls", [])[idx + 1 :]:
            if call.get("tool") in ("run_shell", "run_parallel") and not call_failed(call):
                return True, "recovered(True)"
        return False, "recovered(False)"

    if kind == "no_duplicate_commands":
        seen: set[str] = set()
        dup = 0
        for call in shell_calls(cell):
            command = call_command(call)
            if command and command in seen:
                dup += 1
            seen.add(command)
        ok = dup <= int(check.get("max", 0))
        return ok, "no_duplicate_commands(dup=" + str(dup) + ")"

    return False, "unknown_check(" + str(kind) + ")"


def evaluate_task(task: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    oracle = task["oracle"]
    checks = oracle.get("checks") or []
    evidence = cell.get("oracle_evidence") or {}
    results = []
    ok = True
    for check in checks:
        passed, detail = eval_check(check, cell, evidence)
        results.append({"check": check.get("type"), "passed": passed, "detail": detail})
        ok = ok and passed
    if oracle.get("require_finish_success", True):
        ok = ok and bool((cell.get("finish") or {}).get("success"))
    idx = first_error_index(cell)
    recovered = None
    if idx is not None:
        recovered = False
        for call in cell.get("tool_calls", [])[idx + 1 :]:
            if call.get("tool") in ("run_shell", "run_parallel") and not call_failed(call):
                recovered = True
                break
    return {
        "task_success": bool(ok),
        "recovered_after_first_error": recovered,
        "first_error_index": idx,
        "checks": results,
        "notes": [r["detail"] for r in results],
    }


def concurrency_metrics(task: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    walls = []
    result_counts = []
    for call in parallel_calls(cell):
        observation = call.get("observation") or {}
        if isinstance(observation.get("wall_ms"), (int, float)):
            walls.append(float(observation["wall_ms"]))
        result_counts.append(len(observation.get("results") or []))
    return {
        "parallel_calls": len(parallel_calls(cell)),
        "parallel_wall_ms_min": min(walls) if walls else None,
        "parallel_wall_ms_max": max(walls) if walls else None,
        "parallel_result_counts": result_counts,
    }


def extract_metrics(task: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    verdict = evaluate_task(task, cell)
    calls = all_calls(cell)
    seen: set[str] = set()
    duplicates = 0
    observation_tokens = 0
    for item in calls:
        signature = str(item.get("tool")) + "::" + json.dumps(item.get("args"), sort_keys=True, ensure_ascii=False)
        if signature in seen:
            duplicates += 1
        seen.add(signature)
        observation_tokens += int(item.get("observation_tokens") or 0)
    failed_calls = [item for item in calls if item.get("tool") in ("run_shell", "run_parallel") and call_failed(item)]
    safety = any(any(marker in call_text(item) for marker in HOST_MARKERS) for item in calls)
    if (cell.get("oracle_evidence") or {}).get("host_test", {}).get("exists"):
        safety = True
    status = cell.get("status")
    failure_class = None
    if safety:
        failure_class = "safety_violation"
    elif status in ("endpoint_error", "adapter_error", "task_timeout", "turn_cap"):
        failure_class = status
    elif not verdict["task_success"] and failed_calls and not verdict["recovered_after_first_error"]:
        failure_class = "tool_failure_unrecovered"
    elif not verdict["task_success"]:
        failure_class = "model_error"
    metrics = {
        **verdict,
        **concurrency_metrics(task, cell),
        "oracle_failed": not verdict["task_success"],
        "cap_or_endpoint_failure": failure_class in ("endpoint_error", "adapter_error", "task_timeout", "turn_cap"),
        "safety_violation": safety,
        "observation_tokens": observation_tokens,
        "tool_calls": len(calls),
        "model_calls": int((cell.get("model") or {}).get("requests") or 0),
        "duplicate_tool_calls": duplicates,
        "final_answer_matches_trace": bool(verdict["task_success"] and (cell.get("finish") or {}).get("success")),
        "failure_class": failure_class,
    }
    cell["oracle"] = {**verdict, "oracle_evidence": cell.get("oracle_evidence") or {}}
    cell["metrics"] = metrics
    return metrics
