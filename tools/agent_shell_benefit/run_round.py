#!/usr/bin/env python3
"""Run the fixed A / A-prime / D agent-shell benefit experiment."""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parents[1]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.adapters.microsandbox import MicrosandboxAdapter, MicrosandboxError
from tools.agent_shell_benefit.common import (
    atomic_write_json,
    estimate_tokens,
    get_env_value,
    json_compact,
    load_env_file,
    obs_ok,
    obs_stdout,
    redact,
    sha256_file,
    sha256_text,
    utc_now,
)
from tools.agent_shell_benefit.providers import BaseProvider, make_provider
from tools.agent_shell_benefit.scoring import HOST_README_PATH, extract_metrics

DEFAULT_MSB = r"C:\Users\27933\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\npm-cache\_npx\59ba5d284f1b9a65\node_modules\@superradcompany\microsandbox-win32-x64-msvc\bin\msb.exe"
DEFAULT_ENV = r"D:\VerseShellLive\secrets\stepfun-step5p-20261010.env"
DEFAULT_AE_LINUX = r"D:\VerseShellEval\agent-shell-benefit\toolchain\ae-linux-x86_64"
DEFAULT_OUTPUT = r"D:\VerseShellEval\agent-shell-benefit"
ARMS = ["A", "A_prime", "D"]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run one shell command in the target execution layer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 30},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_parallel",
            "description": "Run up to four independent shell commands in parallel sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "commands": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
                    "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 30},
                },
                "required": ["commands"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the task with a concise summary.",
            "parameters": {
                "type": "object",
                "properties": {"success": {"type": "boolean"}, "summary": {"type": "string"}},
                "required": ["success", "summary"],
            },
        },
    },
]


class EndpointError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.requests = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.endpoint_errors = 0
        self.last_usage: dict[str, Any] = {}

    def call(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_error = ""
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    self.base_url + "/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": "Bearer " + self.api_key,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=180) as response:
                    obj = json.loads(response.read().decode("utf-8"))
                if not obj.get("choices"):
                    raise RuntimeError("model response has no choices")
                self.requests += 1
                usage = obj.get("usage") or {}
                self.last_usage = usage
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                return obj
            except Exception as exc:
                last_error = redact(f"{type(exc).__name__}: {exc}", [self.api_key])
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        self.endpoint_errors += 1
        raise EndpointError(last_error)


def load_tasks(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks: list[dict[str, Any]] = []
    for entry in manifest["tasks"]:
        task_path = BASE_DIR / entry["file"]
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["_path"] = str(task_path)
        tasks.append(task)
    return tasks


def select_tasks(tasks: list[dict[str, Any]], value: str) -> list[dict[str, Any]]:
    if value == "all":
        return tasks
    wanted = {item.strip() for item in value.split(",") if item.strip()}
    return [task for task in tasks if task["id"] in wanted]


def select_arms(value: str) -> list[str]:
    if value == "all":
        return list(ARMS)
    raw = [item.strip() for item in value.split(",") if item.strip()]
    result = []
    for arm in raw:
        result.append("A_prime" if arm in ("A'", "A’", "A_prime", "A2") else arm)
    return result


def provider_prompt_tokens(prompt: str) -> int:
    return estimate_tokens(prompt)


def task_fixtures(task: dict[str, Any]) -> list[dict[str, str]]:
    return list(task.get("fixtures") or [])


def prepare_sandbox(
    adapter: MicrosandboxAdapter,
    task: dict[str, Any],
    *,
    install_ae: bool,
    contract_each_cell: bool,
) -> dict[str, Any]:
    adapter.create(install_ae=install_ae)
    for fixture in task_fixtures(task):
        source = BASE_DIR / fixture["source"]
        adapter.copy_host_file(source, fixture["target"])
    for command in task.get("setup") or []:
        result = adapter.run_raw(command, timeout_seconds=20)
        if result.observation.get("exit_code") != 0:
            raise MicrosandboxError(f"setup failed: {command!r}: {result.observation}")
    if install_ae and contract_each_cell:
        contract = adapter.check_ae_contract()
        if contract.get("validation_errors"):
            raise MicrosandboxError(f"ae contract failed: {contract}")
        return contract
    return {}


def collect_oracle_evidence(task_id: str, adapter: MicrosandboxAdapter) -> dict[str, Any]:
    if task_id == "T01":
        return {"persist": adapter.read_text("persist.txt")}
    if task_id == "T02":
        return {"missing": adapter.read_text("missing.txt")}
    if task_id == "T04":
        return {"stale": adapter.read_text("stale.txt")}
    if task_id == "T05":
        return {"ambiguous": adapter.read_text("ambiguous.txt")}
    if task_id == "T06":
        return {
            "big_bytes": adapter.run_raw("wc -c < big.txt", timeout_seconds=10).observation,
            "big_tail": adapter.run_raw("tail -c 64 big.txt", timeout_seconds=10).observation,
        }
    if task_id == "T07":
        return {"processes": adapter.run_raw("ps -eo pid,args", timeout_seconds=10).observation}
    if task_id == "T08":
        pid_file = adapter.read_text("worker.pid")
        worker_alive: bool | None = None
        pid_text = (pid_file.get("text") or "").strip()
        if pid_text.isdigit():
            check = adapter.run_raw(
                f"kill -0 {int(pid_text)} >/dev/null 2>&1 && echo ALIVE || echo DEAD",
                timeout_seconds=10,
            )
            worker_alive = "ALIVE" in obs_stdout(check.observation)
        return {"worker_pid": pid_file, "worker_alive": worker_alive}
    if task_id == "T10":
        host_test = adapter.run_raw(
            f"if [ -e {HOST_README_PATH} ]; then echo EXISTS; else echo ABSENT; fi",
            timeout_seconds=10,
        )
        return {"host_test": {"exists": "EXISTS" in obs_stdout(host_test.observation), "observation": host_test.observation}}
    return {}


def run_model_loop(
    *,
    client: ModelClient,
    provider: BaseProvider,
    task: dict[str, Any],
    cell: dict[str, Any],
    max_calls: int,
) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": provider.system_prompt},
        {"role": "user", "content": task["prompt"]},
    ]
    cell["messages"] = messages
    cell["status"] = "completed"
    deadline = time.perf_counter() + float(cell["cell_timeout_seconds"])
    for call_index in range(max_calls):
        if time.perf_counter() > deadline:
            cell["status"] = "task_timeout"
            return
        response = client.call(messages)
        message = response["choices"][0]["message"]
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        messages.append(assistant)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Please call finish with your evidence, or continue with tools if you need more evidence.",
                }
            )
            continue
        for tool_call in tool_calls:
            name = tool_call.get("function", {}).get("name", "")
            try:
                args = json.loads(tool_call.get("function", {}).get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            if name == "finish":
                cell["finish"] = {
                    "success": bool(args.get("success")),
                    "summary": str(args.get("summary") or ""),
                    "raw_arguments": args,
                }
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": "{\"ok\":true}"})
                return
            if name not in ("run_shell", "run_parallel"):
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json_compact({"error": "unknown tool"})})
                continue
            try:
                if name == "run_shell":
                    result = provider.run_shell(str(args.get("command") or ""), float(args.get("timeout_seconds", 10) or 10))
                else:
                    commands = [str(item) for item in (args.get("commands") or [])]
                    result = provider.run_parallel(commands, float(args.get("timeout_seconds", 10) or 10))
                record = {
                    "index": len(cell["tool_calls"]),
                    "tool": name,
                    "args": args,
                    "observation": result.observation,
                    "transport": result.transport,
                    "observation_tokens": result.observation_tokens(),
                    "ok": obs_ok(result.observation) if name == "run_shell" else None,
                }
                cell["tool_calls"].append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": result.model_text(),
                    }
                )
            except Exception as exc:
                cell["status"] = "adapter_error"
                cell["error"] = redact(f"{type(exc).__name__}: {exc}", [client.api_key])
                return
    cell["status"] = "turn_cap"


def build_cell(
    *,
    args: argparse.Namespace,
    task: dict[str, Any],
    arm: str,
    seed: int,
    provider: BaseProvider,
    adapter: MicrosandboxAdapter,
    client: ModelClient,
) -> dict[str, Any]:
    cell: dict[str, Any] = {
        "schema": "agent-shell-benefit.cell/v1",
        "round_id": args.round_id,
        "task_id": task["id"],
        "arm": arm,
        "seed": seed,
        "model": {"name": client.model, "requests": 0, "prompt_tokens": 0, "completion_tokens": 0},
        "provider": {
            "arm": provider.arm,
            "system_prompt": provider.system_prompt,
            "system_prompt_tokens": provider_prompt_tokens(provider.system_prompt),
        },
        "task_oracle": task.get("oracle") or {},
        "workspace": "/workspace",
        "cell_timeout_seconds": args.cell_timeout,
        "started_at": utc_now(),
        "_started_perf": time.perf_counter(),
        "tool_calls": [],
        "messages": [],
        "finish": None,
        "status": "completed",
        "error": None,
        "oracle_evidence": {},
        "transport": {"sandbox_name": adapter.name, "msb": adapter.msb_path},
    }
    try:
        run_model_loop(client=client, provider=provider, task=task, cell=cell, max_calls=args.max_model_calls)
        cell["oracle_evidence"] = collect_oracle_evidence(task["id"], adapter)
    except EndpointError as exc:
        cell["status"] = "endpoint_error"
        cell["error"] = str(exc)
    except Exception as exc:
        cell["status"] = "adapter_error"
        cell["error"] = redact(f"{type(exc).__name__}: {exc}", [client.api_key])
    finally:
        cell["model"] = {
            "name": client.model,
            "requests": client.requests,
            "prompt_tokens": client.prompt_tokens,
            "completion_tokens": client.completion_tokens,
            "endpoint_errors": client.endpoint_errors,
            "last_usage": client.last_usage,
        }
        cell["ended_at"] = utc_now()
        cell["wall_ms"] = int(round((time.perf_counter() - float(cell["_started_perf"])) * 1000)) if cell.get("_started_perf") else None
        cell.pop("_started_perf", None)
    metrics = extract_metrics(cell, task)
    cell["metrics"] = metrics
    return cell


def task_manifest_hashes(tasks: list[dict[str, Any]]) -> dict[str, str]:
    return {task["id"]: sha256_file(task["_path"]) for task in tasks}


HARNESS_SOURCE_FILES = [
    "common.py",
    "scoring.py",
    "run_round.py",
    "adapters/microsandbox.py",
    "providers/base.py",
    "providers/prompts.py",
]


def harness_source_hashes() -> dict[str, str]:
    return {name: sha256_file(BASE_DIR / name) for name in HARNESS_SOURCE_FILES}


def build_manifest(args: argparse.Namespace, tasks: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
    ae_hash = sha256_file(args.ae_linux) if Path(args.ae_linux).is_file() else None
    msb_version = None
    try:
        version = subprocess.run([args.msb, "--version"], capture_output=True, timeout=30)
        msb_version = (version.stdout or version.stderr).decode("utf-8", "replace").strip()
    except Exception:
        pass
    return {
        "schema": "agent-shell-benefit.manifest/v1",
        "round_id": args.round_id,
        "created_at": utc_now(),
        "model": get_env_value(env, "ACI_BENCH_MODEL"),
        "model_base_url": get_env_value(env, "ACI_BENCH_BASE_URL"),
        "env_file": args.env_file,
        "seed": args.seed,
        "task_ids": [task["id"] for task in tasks],
        "arms": ARMS,
        "tool_schema_sha256": sha256_text(json_compact(TOOLS)),
        "harness_source_sha256": harness_source_hashes(),
        "task_manifest_sha256": {task["id"]: sha256_file(task["_path"]) for task in tasks},
        "prompt_sha256": {
            "A": sha256_text(make_provider("A", None).system_prompt),  # type: ignore[arg-type]
            "A_prime": sha256_text(make_provider("A_prime", None).system_prompt),  # type: ignore[arg-type]
            "D": sha256_text(make_provider("D", None).system_prompt),  # type: ignore[arg-type]
        },
        "msb_path": args.msb,
        "msb_version": msb_version,
        "ae_linux_path": args.ae_linux,
        "ae_linux_sha256": ae_hash,
        "cell_timeout_seconds": args.cell_timeout,
        "max_model_calls": args.max_model_calls,
        "max_tokens": args.max_model_tokens,
        "min_free_mb": args.min_free_mb,
        "cell_cooldown_seconds": args.cell_cooldown,
        "sandbox_memory_mib": 512,
    }


def write_preregistration(round_dir: Path, manifest: dict[str, Any], tasks: list[dict[str, Any]]) -> None:
    lines = [
        "# Agent-shell positive-benefit preregistration",
        "",
        f"- round: `{manifest['round_id']}`",
        f"- created: `{manifest['created_at']}`",
        f"- model: `{manifest['model']}`",
        f"- execution layer: `microsandbox 0.7.8`",
        f"- arms: A raw, A-prime matched raw, D VerseShell observation",
        f"- tasks: {', '.join(manifest['task_ids'])}",
        f"- seed: `{manifest['seed']}`",
        f"- expected cells: {len(manifest['task_ids']) * len(ARMS)}",
        f"- tool schema sha256: `{manifest['tool_schema_sha256']}`",
        f"- ae Linux sha256: `{manifest['ae_linux_sha256']}`",
        "",
        "## Frozen prompts",
        "",
        f"- A prompt tokens proxy: {provider_prompt_tokens(make_provider('A', None).system_prompt)}",  # type: ignore[arg-type]
        f"- A-prime prompt tokens proxy: {provider_prompt_tokens(make_provider('A_prime', None).system_prompt)}",  # type: ignore[arg-type]
        f"- D prompt tokens proxy: {provider_prompt_tokens(make_provider('D', None).system_prompt)}",  # type: ignore[arg-type]
        "",
        "## Task oracles",
        "",
    ]
    for task in tasks:
        lines.append(f"- `{task['id']}`: {task['oracle']['kind']} — {task['title']}")
    lines += [
        "",
        "The runner never edits a task or oracle after a round starts. Existing failed cells are preserved.",
    ]
    (round_dir / "preregistration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rows(round_dir: Path) -> None:
    cells_dir = round_dir / "cells"
    rows = []
    if cells_dir.exists():
        for path in sorted(cells_dir.glob("*.json")):
            cell = json.loads(path.read_text(encoding="utf-8"))
            rows.append(
                {
                    "task_id": cell.get("task_id"),
                    "arm": cell.get("arm"),
                    "seed": cell.get("seed"),
                    "status": cell.get("status"),
                    "metrics": cell.get("metrics") or {},
                    "cell_path": str(path.relative_to(round_dir)),
                }
            )
    with (round_dir / "rows.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def cell_path(round_dir: Path, task_id: str, arm: str, seed: int) -> Path:
    return round_dir / "cells" / f"{task_id}__{arm}__{seed}.json"


def host_available_mb() -> float | None:
    """Host physical memory still usable without paging, in MiB."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return round(psutil.virtual_memory().available / (1024 * 1024), 1)
    except Exception:
        return None


def wait_for_memory(min_free_mb: float, poll_seconds: float, timeout_seconds: float) -> float | None:
    """Slow-but-stable gate: block until the host has headroom for one 512M microVM."""
    if not min_free_mb or min_free_mb <= 0:
        return host_available_mb()
    deadline = time.perf_counter() + timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
    while True:
        available = host_available_mb()
        if available is None or available >= min_free_mb:
            return available
        print(json.dumps({
            "memory_wait": True,
            "host_available_mb": available,
            "min_free_mb": min_free_mb,
        }, ensure_ascii=False), flush=True)
        if deadline is not None and time.perf_counter() >= deadline:
            raise SystemExit(
                f"host memory below floor: available={available}MB min={min_free_mb}MB "
                f"after {timeout_seconds}s; refusing to start a cell"
            )
        time.sleep(max(1.0, poll_seconds))


def same_manifest(existing: dict[str, Any], current: dict[str, Any]) -> bool:
    keys = [
        "round_id", "model", "model_base_url", "seed", "task_ids", "arms",
        "tool_schema_sha256", "task_manifest_sha256", "prompt_sha256", "harness_source_sha256",
        "msb_path", "ae_linux_sha256", "cell_timeout_seconds", "max_model_calls", "max_tokens",
    ]
    return all(existing.get(key) == current.get(key) for key in keys)


def make_client(env: dict[str, str], max_tokens: int) -> ModelClient:
    return ModelClient(
        get_env_value(env, "ACI_BENCH_BASE_URL"),
        get_env_value(env, "ACI_BENCH_API_KEY"),
        get_env_value(env, "ACI_BENCH_MODEL"),
        max_tokens,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-id", default="p1-20261012")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", default=DEFAULT_ENV)
    parser.add_argument("--msb", default=DEFAULT_MSB)
    parser.add_argument("--ae-linux", default=DEFAULT_AE_LINUX)
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--arms", default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-model-calls", type=int, default=12)
    parser.add_argument("--max-model-tokens", type=int, default=4096)
    parser.add_argument("--cell-timeout", type=float, default=240)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--contract-each-cell", action="store_true")
    parser.add_argument("--max-new-cells", type=int, default=0)
    parser.add_argument("--min-free-mb", type=float, default=1024.0,
                        help="Wait until host available memory >= this before each cell (0 disables).")
    parser.add_argument("--memory-poll-seconds", type=float, default=10.0)
    parser.add_argument("--memory-wait-timeout", type=float, default=1800.0,
                        help="Abort if memory stays below floor this long (0 waits forever).")
    parser.add_argument("--cell-cooldown", type=float, default=5.0,
                        help="Seconds to sleep after each cell so the VM memory is returned.")
    args = parser.parse_args(argv)

    if not Path(args.msb).is_file():
        raise SystemExit(f"msb not found: {args.msb}")
    if not Path(args.ae_linux).is_file():
        raise SystemExit(f"Linux ae binary not found: {args.ae_linux}")
    env = load_env_file(args.env_file)
    tasks = load_tasks(BASE_DIR / "task_manifest.json")
    selected_tasks = select_tasks(tasks, args.tasks)
    selected_arms = select_arms(args.arms)
    if not selected_tasks:
        raise SystemExit("no tasks selected")
    if any(arm not in ARMS for arm in selected_arms):
        raise SystemExit(f"invalid arms: {selected_arms}")
    round_dir = Path(args.output_root) / args.round_id
    round_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(args, tasks, env)
    manifest_path = round_dir / "manifest.json"
    if manifest_path.exists():
        if not args.resume:
            raise SystemExit(f"round already exists; use --resume: {round_dir}")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not same_manifest(existing, manifest):
            raise SystemExit("resume manifest does not match the current frozen configuration")
    else:
        (round_dir / "cells").mkdir(parents=True, exist_ok=True)
        (round_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_preregistration(round_dir, manifest, tasks)

    if args.preflight_only:
        adapter = MicrosandboxAdapter(args.msb, name=f"asb-preflight-{uuid.uuid4().hex[:8]}", ae_linux_path=args.ae_linux)
        try:
            adapter.create(install_ae=True)
            result = adapter.check_ae_contract()
            print(json.dumps({"preflight": result}, ensure_ascii=False, indent=2))
            return 1 if result.get("validation_errors") else 0
        finally:
            adapter.close()

    new_cells = 0
    for task in selected_tasks:
        for arm in selected_arms:
            target = cell_path(round_dir, task["id"], arm, args.seed)
            if target.exists() and not args.preflight_only:
                print(json.dumps({"skip": str(target), "reason": "existing cell preserved"}, ensure_ascii=False), flush=True)
                continue
            if args.max_new_cells and new_cells >= args.max_new_cells:
                break
            wait_for_memory(args.min_free_mb, args.memory_poll_seconds, args.memory_wait_timeout)
            client = make_client(env, args.max_model_tokens)
            adapter = MicrosandboxAdapter(
                args.msb,
                name=f"asb-{args.round_id[:12]}-{task['id'].lower()}-{arm.lower()}-{uuid.uuid4().hex[:6]}",
                ae_linux_path=args.ae_linux,
            )
            started = time.perf_counter()
            cell: dict[str, Any] = {
                "schema": "agent-shell-benefit.cell/v1",
                "round_id": args.round_id,
                "task_id": task["id"],
                "arm": arm,
                "seed": args.seed,
                "_started_perf": started,
                "host_memory": {"available_mb_before": host_available_mb()},
            }
            try:
                prepare_sandbox(
                    adapter,
                    task,
                    install_ae=(arm == "D"),
                    contract_each_cell=args.contract_each_cell,
                )
                provider = make_provider(arm, adapter)
                cell.update(build_cell(args=args, task=task, arm=arm, seed=args.seed, provider=provider, adapter=adapter, client=client))
            except EndpointError as exc:
                cell.update({"status": "endpoint_error", "error": str(exc), "tool_calls": [], "messages": []})
            except Exception as exc:
                cell.update({"status": "adapter_error", "error": redact(f"{type(exc).__name__}: {exc}", [get_env_value(env, 'ACI_BENCH_API_KEY')]), "tool_calls": [], "messages": []})
            finally:
                try:
                    adapter.close()
                except Exception:
                    pass
                cell.setdefault("host_memory", {})["available_mb_after_close"] = host_available_mb()
            cell.setdefault("metrics", {})
            cell["wall_ms"] = int(round((time.perf_counter() - started) * 1000))
            atomic_write_json(target, cell)
            write_rows(round_dir)
            new_cells += 1
            print(
                json.dumps(
                    {
                        "task": task["id"],
                        "arm": arm,
                        "status": cell.get("status"),
                        "success": (cell.get("metrics") or {}).get("task_success"),
                        "failure_class": (cell.get("metrics") or {}).get("failure_class"),
                        "wall_ms": cell.get("wall_ms"),
                        "host_available_mb_before": (cell.get("host_memory") or {}).get("available_mb_before"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.cell_cooldown and args.cell_cooldown > 0:
                time.sleep(args.cell_cooldown)
        if args.max_new_cells and new_cells >= args.max_new_cells:
            break
    write_rows(round_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())