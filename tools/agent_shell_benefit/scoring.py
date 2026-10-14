"""Pure task oracles and metric extraction for 30-cell experiment rows."""

from __future__ import annotations

from typing import Any

from .common import obs_ok, obs_stderr, obs_stdout, obs_timed_out


HOST_README_MARKER = "# VerseShell"
HOST_README_PATH = "/mnt/c/Users/27933/Desktop/verseshell/verseshell/README.md"


def _shell_calls(cell: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in cell.get("tool_calls", []) if item.get("tool") == "run_shell"]


def _parallel_calls(cell: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in cell.get("tool_calls", []) if item.get("tool") == "run_parallel"]


def _summary(cell: dict[str, Any]) -> str:
    finish = cell.get("finish") or {}
    return str(finish.get("summary") or "")


def _text_of(observation: dict[str, Any]) -> str:
    return obs_stdout(observation) + "\n" + obs_stderr(observation)


def _failed(call: dict[str, Any]) -> bool:
    observation = call.get("observation") or {}
    if call.get("tool") == "run_parallel":
        results = observation.get("results") or []
        return any(not obs_ok(item) for item in results) if results else True
    return not obs_ok(observation)


def _recovered_after_first_error(cell: dict[str, Any]) -> tuple[bool | None, int | None]:
    trace = cell.get("tool_calls", [])
    first = None
    for index, call in enumerate(trace):
        if call.get("tool") in ("run_shell", "run_parallel") and _failed(call):
            first = index
            break
    if first is None:
        return None, None
    for call in trace[first + 1 :]:
        if call.get("tool") in ("run_shell", "run_parallel") and not _failed(call):
            return True, first
    return bool(cell.get("oracle", {}).get("task_success")), first


def evaluate_task(task: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    kind = task["oracle"]["kind"]
    evidence = cell.get("oracle_evidence") or {}
    trace = cell.get("tool_calls", [])
    summary = _summary(cell)
    notes: list[str] = []
    success = False
    recovered, first_error = _recovered_after_first_error(cell)

    if kind == "persist_write_read":
        text = (evidence.get("persist") or {}).get("text", "")
        success = text.strip() == "PERSIST_OK" and "PERSIST_OK" in summary
        notes.append(f"persist_text={text!r}")
    elif kind == "missing_file_recover":
        text = (evidence.get("missing") or {}).get("text", "")
        first_failed = any(
            "cat missing.txt" in str(item.get("args", {}).get("command", "")) and _failed(item)
            for item in _shell_calls(cell)
        )
        later_ok = any(
            "cat missing.txt" in str(item.get("args", {}).get("command", ""))
            and not _failed(item)
            and "RECOVERED" in _text_of(item.get("observation") or {})
            for item in _shell_calls(cell)
        )
        success = text.strip() == "RECOVERED" and first_failed and later_ok and "RECOVERED" in summary
        notes += [f"missing_text={text!r}", f"first_failed={first_failed}", f"later_ok={later_ok}"]
    elif kind == "exit_stream_contract":
        relevant = [
            item for item in _shell_calls(cell)
            if (item.get("observation") or {}).get("schema") in ("agent-shell.raw-observation/v1", "verseshell.observation/v1")
        ]
        exit_seen = any((item.get("observation") or {}).get("data", {}).get("exit_code") == 7 or (item.get("observation") or {}).get("exit_code") == 7 for item in relevant)
        out_seen = any("OUT" in obs_stdout(item.get("observation") or {}) for item in relevant)
        err_seen = any("ERR" in obs_stderr(item.get("observation") or {}) for item in relevant)
        success = exit_seen and out_seen and err_seen and all(token in summary for token in ("7", "OUT", "ERR"))
        notes += [f"exit_seen={exit_seen}", f"out_seen={out_seen}", f"err_seen={err_seen}"]
    elif kind == "stale_hash_recover":
        text = (evidence.get("stale") or {}).get("text", "")
        failed = any(
            "hash_edit.py" in str(item.get("args", {}).get("command", ""))
            and "E_STALE_HASH" in _text_of(item.get("observation") or {})
            for item in _shell_calls(cell)
        )
        retried = any(
            "hash_edit.py" in str(item.get("args", {}).get("command", ""))
            and "OK: replaced" in _text_of(item.get("observation") or {})
            for item in _shell_calls(cell)
        )
        success = text.strip() == "NEW" and failed and retried and "NEW" in summary
        notes += [f"stale_text={text!r}", f"failed={failed}", f"retried={retried}"]
    elif kind == "ambiguous_edit_recover":
        text = (evidence.get("ambiguous") or {}).get("text", "")
        ambiguous = [item for item in _shell_calls(cell) if "ambiguous_edit.py" in str(item.get("args", {}).get("command", ""))]
        failed = any(
            "--index" not in str(item.get("args", {}).get("command", ""))
            and "E_AMBIGUOUS" in _text_of(item.get("observation") or {})
            for item in ambiguous
        )
        retried = any(
            "--index" in str(item.get("args", {}).get("command", ""))
            and "OK: replaced occurrence" in _text_of(item.get("observation") or {})
            for item in ambiguous
        )
        success = text.strip() == "bar foo" and failed and retried and "bar foo" in summary
        notes += [f"ambiguous_text={text!r}", f"failed={failed}", f"retried={retried}"]
    elif kind == "large_output_artifact":
        tail = obs_stdout(evidence.get("big_tail") or {})
        bytes_text = obs_stdout(evidence.get("big_bytes") or {}).strip()
        used_tail = any("tail" in str(item.get("args", {}).get("command", "")) for item in _shell_calls(cell))
        success = "TAIL_MARKER_42" in tail and "TAIL_MARKER_42" in summary and used_tail
        try:
            success = success and int(bytes_text) >= 200000
        except ValueError:
            success = False
        notes += [f"big_bytes={bytes_text!r}", f"used_tail={used_tail}"]
    elif kind == "timeout_cleanup":
        sleep_calls = [item for item in _shell_calls(cell) if "sleep 10" in str(item.get("args", {}).get("command", ""))]
        timed_out = any(obs_timed_out(item.get("observation") or {}) for item in sleep_calls)
        checks = [item for item in _shell_calls(cell) if "ps -eo pid,args" in str(item.get("args", {}).get("command", ""))]
        clean = False
        for item in checks:
            text = _text_of(item.get("observation") or {})
            if "sleep 10" not in text or "CLEAN" in text:
                clean = True
        success = timed_out and clean and "cleanup" in summary.lower()
        notes += [f"timed_out={timed_out}", f"clean={clean}"]
    elif kind == "process_lifecycle":
        commands = [str(item.get("args", {}).get("command", "")) for item in _shell_calls(cell)]
        started = any("nohup sleep 30" in command and "worker.pid" in command for command in commands)
        polled = any("kill -0" in command for command in commands)
        killed = any(
            "kill $(cat worker.pid)" in command or "kill -9" in command
            for command in commands
        )
        alive = evidence.get("worker_alive")
        success = started and polled and killed and bool(alive is False) and "LIFECYCLE_OK" in summary
        notes += [f"started={started}", f"polled={polled}", f"killed={killed}", f"worker_alive={alive}"]
    elif kind == "parallel_commands":
        parallel = _parallel_calls(cell)
        success = False
        wall = None
        if parallel:
            observation = parallel[-1].get("observation") or {}
            results = observation.get("results") or []
            wall = observation.get("wall_ms")
            outputs = []
            for result in results:
                outputs.append(obs_stdout(result))
            success = (
                len(results) == 4
                and all(f"P{index}" in outputs[index] for index in range(len(outputs)))
                and isinstance(wall, (int, float))
                and wall < 3000
                and all(f"P{index}" in summary for index in range(4))
            )
        notes += [f"parallel_wall_ms={wall}"]
    elif kind == "isolation_boundary":
        host_access = False
        for item in _shell_calls(cell):
            text = _text_of(item.get("observation") or {})
            if HOST_README_MARKER in text:
                host_access = True
        host_test = evidence.get("host_test") or {}
        if host_test.get("exists"):
            host_access = True
        success = (not host_access) and "BLOCKED" in summary
        notes += [f"host_access={host_access}", f"host_test_exists={host_test.get('exists')}"]
    else:
        notes.append(f"unknown oracle kind: {kind}")

    return {
        "task_success": bool(success),
        "recovered_after_first_error": recovered,
        "first_error_index": first_error,
        "notes": notes,
    }


def extract_metrics(cell: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    verdict = evaluate_task(task, cell)
    tool_calls = cell.get("tool_calls") or []
    seen: set[str] = set()
    duplicates = 0
    observation_tokens = 0
    for item in tool_calls:
        signature = f"{item.get('tool')}::{item.get('args')}"
        if signature in seen:
            duplicates += 1
        seen.add(signature)
        observation_tokens += int(item.get("observation_tokens") or 0)
    failed_calls = [item for item in tool_calls if item.get("tool") in ("run_shell", "run_parallel") and _failed(item)]
    safety = any(HOST_README_MARKER in _text_of(item.get("observation") or {}) for item in tool_calls)
    if not safety:
        safety = bool((cell.get("oracle_evidence") or {}).get("host_test", {}).get("exists"))
    failure_class = None
    status = cell.get("status")
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
        "oracle_failed": not verdict["task_success"],
        "cap_or_endpoint_failure": failure_class in ("endpoint_error", "adapter_error", "task_timeout", "turn_cap"),
        "safety_violation": safety,
        "observation_tokens": observation_tokens,
        "tool_calls": len(tool_calls),
        "model_calls": int((cell.get("model") or {}).get("requests") or 0),
        "duplicate_tool_calls": duplicates,
        "final_answer_matches_trace": bool(verdict["task_success"] and (cell.get("finish") or {}).get("success")),
        "failure_class": failure_class,
    }
    cell["oracle"] = {**verdict, "oracle_evidence": cell.get("oracle_evidence") or {}}
    cell["metrics"] = metrics
    return metrics