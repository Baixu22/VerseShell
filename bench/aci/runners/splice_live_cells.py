#!/usr/bin/env python3
"""Re-run the live cells that carry `api_error` and patch them into their run file.

The endpoint returns an intermittent 500 (`parse response failed`), which marks
the affected row `api_error`. `merge_live_runs.py` refuses to merge such rows, so
they must be re-run. Doing that by hand is how a half-spliced artifact gets
committed; this script does it in one place and recomputes the file's aggregate
and comparison afterwards.

Usage:
    python bench/aci/runners/splice_live_cells.py bench/aci/results/tf62/without_seed42.json
    python bench/aci/runners/splice_live_cells.py --api-key <key> <run files...>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))
from live_agent_loop import (  # noqa: E402
    TASKS_DIR,
    aggregate,
    compare_a_vs_d,
    run_agent_loop,
    success_verdict,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY", ""))
    args = ap.parse_args(argv)

    if not args.api_key:
        print("ERROR: no API key (set DEEPSEEK_API_KEY or pass --api-key)", file=sys.stderr)
        return 1

    patched_total = 0
    for path in args.runs:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        cfg = payload.get("live_config", {})
        bad = [i for i, row in enumerate(payload["rows"]) if row.get("api_error")]
        if not bad:
            print(f"{path.name}: no api_error rows")
            continue
        print(f"{path.name}: re-running {len(bad)} cell(s)")
        for index in bad:
            row = payload["rows"][index]
            task = json.loads((TASKS_DIR / f"{row['task_id']}.json").read_text(encoding="utf-8-sig"))
            print(f"  {row['task_id']} [{row['condition']}] seed={cfg.get('seed')}")
            fresh = run_agent_loop(
                task, row["condition"],
                model=cfg.get("model"), api_key=args.api_key, base_url=cfg.get("api_base"),
                max_turns=cfg.get("max_turns", 15), caps=cfg.get("caps"),
                temperature=cfg.get("temperature", 0.0), seed=cfg.get("seed"),
                run_index=row.get("run_index", 0),
                exclude_tools=tuple(cfg.get("exclude_tools") or ()),
            )
            if fresh.get("api_error"):
                print(f"    STILL FAILING: {fresh.get('last_error')}", file=sys.stderr)
                return 2
            fresh["source_run"] = row.get("source_run", path.name)
            fresh["seed"] = row.get("seed", cfg.get("seed"))
            payload["rows"][index] = fresh
            patched_total += 1
            print(f"    -> {success_verdict(fresh['success'])}: "
                  f"{fresh['tool_calls']} tools, {fresh['observation_tokens']} obs_tok")
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        payload["aggregate"] = aggregate(payload["rows"])
        payload["comparison"] = compare_a_vs_d(payload["rows"])
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
        print(f"  patched {path}")

    print(f"re-ran {patched_total} cell(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
