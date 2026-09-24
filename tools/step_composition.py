#!/usr/bin/env python3
"""TF-0078: decompose the step gap between condition D and raw shell.

After the C18 fix D is *cheaper* than raw shell in observation tokens (0.876x) but
still issues 1.40x the tool calls. This tool asks whether any of that step gap is
removable waste, and it answers in three parts:

  * **composition** — steps per op per run for both conditions, so the asymmetry
    is visible as a shape rather than a ratio;
  * **multiplexing** — how many raw-shell commands do more than one job (read +
    run + write). A does its reading, running and writing inside one command;
    D's typed ops cannot, so part of the gap is the surface itself, not waste;
  * **mergeable calls** — repeated (op, args) pairs inside a run, i.e. calls that
    a client could have issued once. Reported with their token cost.

It also attributes a representative failed-exec observation field by field, since
failed execs are the largest single block of D's tokens.

Usage:
    python tools/step_composition.py --out eval/step_composition.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
RESULTS = BENCH / "results"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))
from tf45_envelope_replay import prepare_workspace, run_op  # noqa: E402
from live_agent_loop import format_aci_result  # noqa: E402

ARMS = {
    "with_read_files": RESULTS / "latest_live.json",
    "without_read_files": RESULTS / "live_ab_without_read_files.json",
}
TERMINAL = "task_complete"
READ_OPS = {"file.read_many", "file.view", "file.read_range"}
EDIT_OPS = {"file.replace_exact", "file.write", "file.edit_range", "file.apply_patch"}
META_OPS = {"repo.summary", "repo.search", "ops.list", "test.discover", "test.run_target",
            "result.query"}
READ_HINTS = ("type ", "cat ", "get-content")
RUN_HINTS = ("cargo", "pytest", "npm ", "npx ", "tsc", "python -m", "rustc", "node ")
WRITE_HINTS = (">", "python -c", "new-item", "mkdir", "md ", "set-content", "out-file")

# Representative failures, one per family the live run actually produced. The
# attribution is leave-one-out over the *projection* keys.
FAILURE_CASES = [
    ("python_fix_pytest_fail", ["python", "-m", "pytest", "-q"]),
    ("ts_fix_type_error", ["npx", "tsc", "--noEmit"]),
    ("ts_package_script_fail", ["npm", "test"]),
    ("rust_fix_compile_error", ["cargo", "check"]),
]

EVIDENCE_GLOBS = [
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/tasks/*.json",
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "tools/step_composition.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for pat in globs for p in ROOT.glob(pat)
                       if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def steps(row: dict, include_terminal: bool = False) -> list[dict]:
    return [t for t in row.get("trajectory", [])
            if include_terminal or t.get("op") != TERMINAL]


def composition(rows: list[dict], condition: str) -> dict:
    runs = [r for r in rows if r["condition"] == condition]
    if not runs:
        return {}
    per_op: Counter = Counter()
    tokens: Counter = Counter()
    for row in runs:
        for step in steps(row):
            per_op[step["op"]] += 1
            tokens[step["op"]] += int(step.get("observation_tokens", 0))
    total_steps = sum(per_op.values())
    total_tokens = sum(tokens.values())
    by_kind: Counter = Counter()
    for op, count in per_op.items():
        if op in READ_OPS:
            by_kind["read"] += count
        elif op in EDIT_OPS:
            by_kind["edit"] += count
        elif op == "exec.run" or op == "run_command":
            by_kind["exec"] += count
        elif op in META_OPS:
            by_kind["meta"] += count
        else:
            by_kind["other"] += count
    return {
        "runs": len(runs),
        "steps": total_steps,
        "steps_per_run": round(total_steps / len(runs), 3),
        "tokens": total_tokens,
        "tokens_per_run": round(total_tokens / len(runs), 2),
        "per_op": {k: {"calls": v, "tokens": tokens.get(k, 0),
                       "per_run": round(v / len(runs), 3)}
                   for k, v in sorted(per_op.items(), key=lambda kv: -kv[1])},
        "per_kind": {k: {"calls": v, "per_run": round(v / len(runs), 3)}
                     for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])},
    }


def multiplexing(rows: list[dict]) -> dict:
    """How many raw-shell commands do more than one job?"""
    kinds: Counter = Counter()
    multi = 0
    total = 0
    for row in rows:
        if row["condition"] != "raw_shell":
            continue
        for step in steps(row):
            if step["op"] != "run_command":
                continue
            command = str(step.get("args", {}).get("command", "")).lower()
            jobs = set()
            if any(h in command for h in READ_HINTS):
                jobs.add("read")
            if any(h in command for h in RUN_HINTS):
                jobs.add("run")
            if any(h in command for h in WRITE_HINTS):
                jobs.add("write")
            label = "+".join(sorted(jobs)) if jobs else "other"
            kinds[label] += 1
            total += 1
            if len(jobs) > 1:
                multi += 1
    return {
        "commands": total,
        "multi_job_commands": multi,
        "multi_job_share": round(multi / total, 4) if total else None,
        "kinds": dict(kinds.most_common()),
        "note": "raw shell can read, run and write inside one command; D's typed ops "
                "cannot, so this share of A's commands is surface, not waste",
    }


def mergeable_calls(rows: list[dict], condition: str) -> dict:
    runs = [r for r in rows if r["condition"] == condition]
    repeats = 0
    repeat_tokens = 0.0
    total = 0
    per_task: Counter = Counter()
    per_op: Counter = Counter()
    for row in runs:
        seen: Counter = Counter()
        for step in steps(row):
            key = (step["op"], json.dumps(step.get("args", {}), sort_keys=True))
            seen[key] += 1
        for step in steps(row):
            total += 1
            key = (step["op"], json.dumps(step.get("args", {}), sort_keys=True))
            n = seen[key]
            if n > 1:
                # charge each occurrence its 1/n share of the duplicated cost
                repeats += 1
                repeat_tokens += int(step.get("observation_tokens", 0)) * (n - 1) / n
                per_task[row["task_id"]] += 1
                per_op[step["op"]] += 1
    return {
        "runs": len(runs),
        "steps": total,
        "duplicate_occurrences": repeats,
        "duplicate_share": round(repeats / total, 4) if total else None,
        "duplicate_tokens": round(repeat_tokens, 1),
        "duplicate_tokens_per_run": round(repeat_tokens / len(runs), 2) if runs else None,
        "by_task": dict(per_task),
        "by_op": dict(per_op),
    }


def failure_envelope() -> dict:
    cases = {}
    aggregate: dict[str, int] = defaultdict(int)
    for fixture, argv in FAILURE_CASES:
        workspace = prepare_workspace(fixture)
        try:
            env = run_op("exec.run", {"argv": argv, "cwd": ".", "profile": "auto"}, workspace)
            if env.get("ok"):
                cases[" ".join(argv)] = {"skipped": "command succeeded"}
                continue
            text = format_aci_result(env, compact=True)
            projection = json.loads(text)
            parts = {}
            for key in projection:
                without = copy.deepcopy(projection)
                without.pop(key, None)
                saved = len(text) - len(json.dumps(without, ensure_ascii=False))
                parts[key] = {"chars": saved, "share": round(saved / len(text), 4)}
                aggregate[key] += saved
            cases[" ".join(argv)] = {
                "fixture": fixture, "chars": len(text), "tokens": len(text) // 4,
                "keys": sorted(projection), "leave_one_out": parts,
            }
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    return {
        "cases": cases,
        "aggregate_chars": dict(sorted(aggregate.items(), key=lambda kv: -kv[1])),
        "note": "leave-one-out over projection keys; `diagnostics` and `error` are the "
                "actionable content, `stats` / `stdout_summary` / `stderr_summary` are the "
                "only candidates and each still carries a signal",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    missing = [str(p) for p in ARMS.values() if not p.exists()]
    if missing:
        print(f"ERROR: missing {missing}", file=sys.stderr)
        return 1

    rows = {name: json.loads(path.read_text(encoding="utf-8-sig"))["rows"]
            for name, path in ARMS.items()}
    w = rows["with_read_files"]
    report = {
        "schema": "verseshell.step-composition/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "inputs": [str(p.relative_to(ROOT)) for p in ARMS.values()],
            "steps": f"tool calls excluding `{TERMINAL}`; the live bench counts the same way",
            "multiplexing": "raw-shell commands classified by how many of read/run/write they do",
            "mergeable": "within-run repeats of an identical (op, args) pair, charged the "
                         "duplicated share of their own token cost",
            "failure_envelope": "leave-one-out over projection keys on representative failures",
        },
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
        "with_read_files": {
            "d": composition(w, "verseshell_aci"),
            "a": composition(w, "raw_shell"),
            "a_multiplexing": multiplexing(w),
            "d_mergeable": mergeable_calls(w, "verseshell_aci"),
            "a_mergeable": mergeable_calls(w, "raw_shell"),
        },
        "without_read_files": {
            "d": composition(rows["without_read_files"], "verseshell_aci"),
            "a": composition(rows["without_read_files"], "raw_shell"),
            "d_mergeable": mergeable_calls(rows["without_read_files"], "verseshell_aci"),
        },
        "failure_envelope": failure_envelope(),
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    p = report["with_read_files"]
    print(f"D steps/run {p['d']['steps_per_run']} (tokens {p['d']['tokens_per_run']}) | "
          f"A steps/run {p['a']['steps_per_run']} (tokens {p['a']['tokens_per_run']}) | "
          f"ratio {p['d']['steps_per_run'] / p['a']['steps_per_run']:.3f} / "
          f"{p['d']['tokens_per_run'] / p['a']['tokens_per_run']:.3f}")
    print("D per kind:", {k: v["per_run"] for k, v in p["d"]["per_kind"].items()})
    print("A per kind:", {k: v["per_run"] for k, v in p["a"]["per_kind"].items()})
    m = p["a_multiplexing"]
    print(f"A multiplexing: {m['multi_job_commands']}/{m['commands']} "
          f"({m['multi_job_share'] * 100:.1f}%) do more than one job; kinds={m['kinds']}")
    dm, am = p["d_mergeable"], p["a_mergeable"]
    print(f"mergeable calls: D {dm['duplicate_occurrences']} "
          f"({dm['duplicate_share'] * 100:.1f}% of steps, {dm['duplicate_tokens_per_run']} tok/run) | "
          f"A {am['duplicate_occurrences']} ({am['duplicate_share'] * 100:.1f}%)")
    print("failure envelope leave-one-out:", report["failure_envelope"]["aggregate_chars"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
