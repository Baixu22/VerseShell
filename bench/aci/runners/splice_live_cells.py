#!/usr/bin/env python3
"""Re-run endpoint-failed cells in original run files, checkpointing each completed call.

Only the measurement owner runs this tool: it makes real model calls. Tests mock
run_agent_loop. Use original run files, not merged artifacts whose first config
cannot describe every source run. A model task failure is a completed rerun;
only endpoint/harness failures remain pending.

Credentials: --api-key > ACI_BENCH_API_KEY in the environment > .env.local >
legacy DEEPSEEK_API_KEY. Credentials are never printed.

Usage:
    python bench/aci/runners/splice_live_cells.py <original run files...>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))
from live_agent_loop import TASKS_DIR, run_agent_loop, success_verdict  # noqa: E402
from merge_live_runs import refresh_summaries, row_class  # noqa: E402


def resolve_api_key(explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    if os.environ.get("ACI_BENCH_API_KEY"):
        return os.environ["ACI_BENCH_API_KEY"]
    path = ROOT / ".env.local"
    file_key = ""
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == "ACI_BENCH_API_KEY":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                file_key = value
    return file_key or os.environ.get("DEEPSEEK_API_KEY", "")


def checkpoint(path: Path, payload: dict) -> None:
    """Replace a complete JSON snapshot atomically after every completed rerun."""
    cfg = payload["live_config"]
    rows = payload["rows"]
    for row in rows:
        row["row_class"] = row_class(row, cfg["max_turns"])
        if row["row_class"] == "endpoint_failure":
            row.setdefault("raw_success", row.get("success"))
            row["success"] = None
    cfg["api_error_rows"] = sum(bool(row.get("api_error")) for row in rows)
    cfg["endpoint_failure_rows"] = sum(row["row_class"] == "endpoint_failure" for row in rows)
    payload["partial"] = bool(cfg["endpoint_failure_rows"])
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    refresh_summaries(payload)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=path.name + ".", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args(argv)

    patched_total = 0
    failures = []
    api_key = None
    for path in args.runs:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get('run_identity'):
            print(f'ERROR: {path.name}: frozen collections are immutable to this legacy splicer; use a separately registered recovery collection',file=sys.stderr)
            failures.append(str(path));continue
        cfg = payload.get("live_config", {})
        bad = [i for i, row in enumerate(payload["rows"])
               if row_class(row, cfg.get("max_turns")) == "endpoint_failure"]
        if not bad:
            print(f"{path.name}: no endpoint_failure rows")
            continue
        missing = [key for key in ("model", "api_base", "max_turns", "max_tokens", "caps", "temperature")
                   if key not in cfg or cfg[key] is None]
        if cfg.get("merged_from") or missing:
            reason = "use original run files, not a merged artifact" if cfg.get("merged_from") else (
                "missing recorded replay settings: " + ", ".join(missing))
            print(f"ERROR: {path.name}: {reason}", file=sys.stderr)
            failures.append(str(path))
            continue
        if api_key is None:
            api_key = resolve_api_key(args.api_key)
        if not api_key:
            print("ERROR: no API key (set ACI_BENCH_API_KEY in the environment or .env.local, "
                  "or pass --api-key)", file=sys.stderr)
            return 1
        print(f"{path.name}: re-running {len(bad)} cell(s)")
        for index in bad:
            row = payload["rows"][index]
            seed = row.get("seed") if row.get("seed") is not None else cfg.get("seed")
            identity = f"{path.name}:{row['task_id']} [{row['condition']}] seed={seed}"
            print(f"  {identity}")
            try:
                task = json.loads((TASKS_DIR / f"{row['task_id']}.json").read_text(encoding="utf-8-sig"))
                fresh = run_agent_loop(
                    task, row["condition"], model=cfg["model"], api_key=api_key, base_url=cfg["api_base"],
                    max_turns=cfg["max_turns"], max_tokens=cfg["max_tokens"], caps=cfg["caps"],
                    temperature=cfg["temperature"], seed=seed, run_index=row.get("run_index", 0),
                    exclude_tools=tuple(cfg.get("exclude_tools") or ()),
                )
            except Exception as exc:
                print(f"    STILL FAILING: {type(exc).__name__}: {str(exc).replace(api_key, '[REDACTED]')}",
                      file=sys.stderr)
                failures.append(identity)
                continue
            if row_class(fresh, cfg["max_turns"]) == "endpoint_failure":
                message = str(fresh.get("last_error") or fresh.get("harness_fault") or "harness failure")
                print(f"    STILL FAILING: {message.replace(api_key, '[REDACTED]')}", file=sys.stderr)
                failures.append(identity)
                continue
            fresh["source_run"] = row.get("source_run", path.name)
            fresh["seed"] = seed
            payload["rows"][index] = fresh
            try:
                checkpoint(path, payload)
            except Exception as exc:
                print(f"ERROR: could not save {identity}: {type(exc).__name__}; stopping", file=sys.stderr)
                return 1
            patched_total += 1
            print(f"    saved -> {success_verdict(fresh['success'])}: "
                  f"{fresh['tool_calls']} tools, {fresh['observation_tokens']} obs_tok")

    print(f"re-ran and saved {patched_total} cell(s); {len(failures)} unresolved")
    if failures:
        for identity in failures:
            print(f"  unresolved: {identity}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
