#!/usr/bin/env python3
"""Run the 80-task (4 tiers x 20) agent-shell suite across A / A_prime / D."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
ROOT = BASE_DIR.parents[1]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.adapters.microsandbox import MicrosandboxAdapter, MicrosandboxError
from tools.agent_shell_benefit.common import (
    atomic_write_json,
    get_env_value,
    load_env_file,
    obs_stdout,
    redact,
    sha256_file,
    sha256_text,
    utc_now,
)
from tools.agent_shell_benefit.providers import BaseProvider, make_provider
from tools.agent_shell_benefit.suite import build_catalog
from tools.agent_shell_benefit.suite.oracles import HOST_MARKERS, extract_metrics
from tools.agent_shell_benefit import run_round as rr

DEFAULT_MSB = rr.DEFAULT_MSB
DEFAULT_ENV = rr.DEFAULT_ENV
DEFAULT_AE_LINUX = rr.DEFAULT_AE_LINUX
DEFAULT_OUTPUT = r"D:\VerseShellEval\agent-shell-benefit"
ARMS = ["A", "A_prime", "D"]
HOST_README_PATH = "/mnt/c/Users/27933/Desktop/verseshell/verseshell/README.md"


def task_by_id() -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in build_catalog()}


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


def collect_evidence(task: dict[str, Any], adapter: MicrosandboxAdapter) -> dict[str, Any]:
    spec = task.get("evidence") or {}
    evidence: dict[str, Any] = {"files": {}}
    for path in spec.get("files") or []:
        rel = path
        if path.startswith("/workspace/"):
            rel = path[len("/workspace/") :]
        evidence["files"][path] = adapter.read_text(rel)
    for probe in spec.get("probes") or []:
        run = adapter.run_raw(probe["command"], timeout_seconds=15)
        text = obs_stdout(run.observation) + "\n" + (run.observation.get("stderr") or "")
        evidence.setdefault("probes", {})[probe["name"]] = {"text": text, "observation": run.observation}
    if spec.get("host_test"):
        probe = adapter.run_raw(
            f"if [ -e {HOST_README_PATH} ]; then echo EXISTS; else echo ABSENT; fi",
            timeout_seconds=10,
        )
        evidence["host_test"] = {"exists": "EXISTS" in obs_stdout(probe.observation)}
    if spec.get("processes"):
        evidence["processes"] = adapter.run_raw("ps -eo pid,args", timeout_seconds=10).observation
    return evidence


def prepare(adapter: MicrosandboxAdapter, task: dict[str, Any], install_ae: bool, contract: bool) -> dict[str, Any]:
    adapter.create(install_ae=install_ae)
    for fixture in task.get("fixtures") or []:
        adapter.copy_host_file(BASE_DIR / fixture["source"], fixture["target"])
    for command in task.get("setup") or []:
        result = adapter.run_raw(command, timeout_seconds=20)
        if result.observation.get("exit_code") != 0:
            raise MicrosandboxError(f"setup failed: {command!r}: {result.observation}")
    if install_ae and contract:
        info = adapter.check_ae_contract()
        if info.get("validation_errors"):
            raise MicrosandboxError(f"ae contract failed: {info}")
        return info
    return {}


def run_cell(args: argparse.Namespace, task: dict[str, Any], arm: str, env: dict[str, str]) -> dict[str, Any]:
    client = rr.make_client(env, args.max_model_tokens)
    adapter = MicrosandboxAdapter(
        args.msb,
        name=f"suite-{task['id'].lower()}-{arm.lower()}-{uuid.uuid4().hex[:6]}",
        ae_linux_path=args.ae_linux,
    )
    started = time.perf_counter()
    mem_before = host_available_mb()
    cell: dict[str, Any] = {
        "schema": "agent-shell-benefit.suite-cell/v1",
        "round_id": args.round_id,
        "task_id": task["id"],
        "tier": task["tier"],
        "arm": arm,
        "seed": args.seed,
        "_started_perf": started,
        "tool_calls": [],
        "messages": [],
        "finish": None,
        "status": "completed",
        "error": None,
        "oracle_evidence": {},
        "cell_timeout_seconds": args.cell_timeout,
        "host_memory": {"available_mb_before": mem_before},
    }
    try:
        prepare(adapter, task, install_ae=(arm == "D"), contract=args.contract_each_cell)
        provider = make_provider(arm, adapter)
        rr.run_model_loop(
            client=client,
            provider=provider,
            task=task,
            cell=cell,
            max_calls=args.max_model_calls,
        )
        cell["oracle_evidence"] = collect_evidence(task, adapter)
    except rr.EndpointError as exc:
        cell["status"] = "endpoint_error"
        cell["error"] = str(exc)
    except Exception as exc:
        cell["status"] = "adapter_error"
        cell["error"] = redact(f"{type(exc).__name__}: {exc}", [get_env_value(env, "ACI_BENCH_API_KEY")])
    finally:
        cell["model"] = {
            "name": client.model,
            "requests": client.requests,
            "prompt_tokens": client.prompt_tokens,
            "completion_tokens": client.completion_tokens,
            "endpoint_errors": client.endpoint_errors,
            "last_usage": client.last_usage,
        }
        cell["provider"] = {
            "arm": arm,
            "system_prompt_tokens": rr.provider_prompt_tokens(make_provider(arm, adapter).system_prompt),
        }
        cell["started_at"] = utc_now()
        cell["wall_ms"] = int(round((time.perf_counter() - started) * 1000))
        cell.pop("_started_perf", None)
        try:
            adapter.close()
        except Exception:
            pass
        cell["host_memory"]["available_mb_after_close"] = host_available_mb()
    extract_metrics(task, cell)
    return cell


def cell_path(round_dir: Path, task_id: str, arm: str, seed: int) -> Path:
    return round_dir / "cells" / f"{task_id}__{arm}__{seed}.json"


def build_manifest(args: argparse.Namespace, tasks: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": "agent-shell-benefit.suite-manifest/v1",
        "round_id": args.round_id,
        "created_at": utc_now(),
        "suite": "agent-shell-80",
        "tiers": {tier: 20 for tier in ("L1", "L2", "L3", "L4")},
        "model": get_env_value(env, "ACI_BENCH_MODEL"),
        "model_base_url": get_env_value(env, "ACI_BENCH_BASE_URL"),
        "seed": args.seed,
        "task_ids": [task["id"] for task in tasks],
        "arms": ARMS,
        "tool_schema_sha256": sha256_text(rr.json_compact(rr.TOOLS)),
        "catalog_sha256": {
            task["id"]: sha256_text(json.dumps(task, sort_keys=True, ensure_ascii=False)) for task in tasks
        },
        "msb_path": args.msb,
        "ae_linux_sha256": sha256_file(args.ae_linux) if Path(args.ae_linux).is_file() else None,
        "cell_timeout_seconds": args.cell_timeout,
        "max_model_calls": args.max_model_calls,
        "max_tokens": args.max_model_tokens,
        "min_free_mb": args.min_free_mb,
        "cell_cooldown_seconds": args.cell_cooldown,
        "sandbox_memory_mib": 512,
        "runner_sha256": sha256_file(__file__),
    }


def select_tasks(tasks: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.tiers != "all":
        wanted_tiers = {t.strip().upper() for t in args.tiers.split(",") if t.strip()}
        tasks = [t for t in tasks if t["tier"] in wanted_tiers]
    if args.tasks != "all":
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in tasks if t["id"] in wanted]
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", default=DEFAULT_ENV)
    parser.add_argument("--msb", default=DEFAULT_MSB)
    parser.add_argument("--ae-linux", default=DEFAULT_AE_LINUX)
    parser.add_argument("--tiers", default="all")
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--arms", default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-model-calls", type=int, default=16)
    parser.add_argument("--max-model-tokens", type=int, default=4096)
    parser.add_argument("--cell-timeout", type=float, default=300)
    parser.add_argument("--resume", action="store_true")
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
    tasks = select_tasks(build_catalog(), args)
    arms = ARMS if args.arms == "all" else rr.select_arms(args.arms)
    if not tasks:
        raise SystemExit("no tasks selected")
    round_dir = Path(args.output_root) / args.round_id
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "cells").mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(args, tasks, env)
    manifest_path = round_dir / "manifest.json"
    if manifest_path.exists() and not args.resume:
        raise SystemExit(f"round exists; use --resume: {round_dir}")
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    new_cells = 0
    for task in tasks:
        for arm in arms:
            target = cell_path(round_dir, task["id"], arm, args.seed)
            if target.exists():
                print(json.dumps({"skip": str(target)}, ensure_ascii=False), flush=True)
                continue
            if args.max_new_cells and new_cells >= args.max_new_cells:
                break
            wait_for_memory(args.min_free_mb, args.memory_poll_seconds, args.memory_wait_timeout)
            cell = run_cell(args, task, arm, env)
            atomic_write_json(target, cell)
            new_cells += 1
            print(json.dumps({
                "task": task["id"], "tier": task["tier"], "arm": arm,
                "status": cell.get("status"),
                "success": (cell.get("metrics") or {}).get("task_success"),
                "failure_class": (cell.get("metrics") or {}).get("failure_class"),
                "wall_ms": cell.get("wall_ms"),
                "host_available_mb_before": (cell.get("host_memory") or {}).get("available_mb_before"),
            }, ensure_ascii=False), flush=True)
            if args.cell_cooldown and args.cell_cooldown > 0:
                time.sleep(args.cell_cooldown)
        if args.max_new_cells and new_cells >= args.max_new_cells:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())