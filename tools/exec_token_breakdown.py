#!/usr/bin/env python3
"""TF-0058: decompose condition D's `exec.run` observation cost.

The live A/B says condition D spends ~1.69x the observation tokens of raw shell.
`exec.run` is the single biggest line item inside D, which invites the conclusion
that "the exec observation is the problem". This tool checks that with the stored
artifacts only (no API calls) and separates three explanations:

  1. **count effect**   — D issues more commands than the control arm
  2. **per-call effect** — each command returns more output than the control arm
  3. **failure mix**    — failing commands cost far more than succeeding ones

It also classifies raw-shell commands by intent, because A does its file reading
*through* `run_command` (`type file`), so comparing D's `exec.run` with A's
`run_command` compares unlike things unless that is made explicit.

Usage:
    python tools/exec_token_breakdown.py --out eval/exec_token_breakdown.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bench" / "aci" / "results"

ARMS = {
    "with_read_files": RESULTS / "latest_live.json",
    "without_read_files": RESULTS / "live_ab_without_read_files.json",
}

# The measured surface: the two stored live artifacts and this tool.
EVIDENCE_GLOBS = [
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "tools/exec_token_breakdown.py",
]

D_CONDITION = "verseshell_aci"
A_CONDITION = "raw_shell"
D_EXEC_OP = "exec.run"
A_EXEC_OP = "run_command"

# Raw-shell command classification. Heuristic and deliberately reported as such:
# a command can read *and* build, so the buckets are ordered by primary intent and
# the residual `other` bucket is reported rather than hidden.
BUILD_HINTS = ("cargo ", "cargo", "pytest", "npm ", "npx ", "tsc", "python -m pytest",
               "python -m py_compile", "python -m compileall")
READ_HINTS = ("type ", "cat ", "head ", "tail ", "more ", "findstr", "get-content",
              "select-string")
WRITE_HINTS = (">", "python -c", "new-item", "mkdir", "md ", "set-content", "out-file")


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    paths = sorted(
        p for pat in globs for p in ROOT.glob(pat)
        if p.is_file() and "__pycache__" not in p.parts
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))["rows"]


def run_count(rows: list[dict], condition: str) -> int:
    """One 'run' is a (task, seed) cell; the merge records `seed` on every row."""
    return len({(r["task_id"], r.get("seed")) for r in rows if r["condition"] == condition})


def op_table(rows: list[dict], condition: str) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for row in rows:
        if row["condition"] != condition:
            continue
        for step in row.get("trajectory", []):
            entry = table.setdefault(step["op"], {"calls": 0, "tokens": 0})
            entry["calls"] += 1
            entry["tokens"] += int(step.get("observation_tokens", 0))
    for entry in table.values():
        entry["tokens_per_call"] = round(entry["tokens"] / entry["calls"], 2) if entry["calls"] else 0.0
    return dict(sorted(table.items(), key=lambda kv: -kv[1]["tokens"]))


def decompose(calls_before: int, tokens_before: int,
              calls_after: int, tokens_after: int, runs: int) -> dict:
    """Split a per-run token change into count / per-call / interaction parts.

    total/run = calls/run * tokens/call, so the change is
        (dc) * p0      +  c1 * (dp)      +  dc * dp
        count effect      per-call effect   interaction
    """
    if not runs or not calls_before or not calls_after:
        return {}
    p0 = tokens_before / calls_before
    p1 = tokens_after / calls_after
    c0 = calls_before / runs
    c1 = calls_after / runs
    count_effect = (c1 - c0) * p0
    per_call_effect = c1 * (p1 - p0)
    interaction = (c1 - c0) * (p1 - p0)
    total = (tokens_after - tokens_before) / runs
    return {
        "runs": runs,
        "before": {"calls_per_run": round(c0, 3), "tokens_per_call": round(p0, 2),
                   "tokens_per_run": round(c0 * p0, 2)},
        "after": {"calls_per_run": round(c1, 3), "tokens_per_call": round(p1, 2),
                  "tokens_per_run": round(c1 * p1, 2)},
        "delta_tokens_per_run": round(total, 2),
        "count_effect": round(count_effect, 2),
        "per_call_effect": round(per_call_effect, 2),
        "interaction": round(interaction, 2),
        "count_share": round(count_effect / total, 4) if total else None,
        "per_call_share": round(per_call_effect / total, 4) if total else None,
    }


def exec_split(rows: list[dict], condition: str, op: str) -> dict:
    ok_calls = ok_tokens = fail_calls = fail_tokens = 0
    for row in rows:
        if row["condition"] != condition:
            continue
        for step in row.get("trajectory", []):
            if step["op"] != op:
                continue
            tokens = int(step.get("observation_tokens", 0))
            if step.get("aci_ok"):
                ok_calls += 1
                ok_tokens += tokens
            else:
                fail_calls += 1
                fail_tokens += tokens
    total_calls = ok_calls + fail_calls
    total_tokens = ok_tokens + fail_tokens
    return {
        "calls": total_calls,
        "tokens": total_tokens,
        "ok": {
            "calls": ok_calls, "tokens": ok_tokens,
            "tokens_per_call": round(ok_tokens / ok_calls, 2) if ok_calls else 0.0,
        },
        "failed": {
            "calls": fail_calls, "tokens": fail_tokens,
            "tokens_per_call": round(fail_tokens / fail_calls, 2) if fail_calls else 0.0,
        },
        "failed_share_of_calls": round(fail_calls / total_calls, 4) if total_calls else None,
        "failed_share_of_tokens": round(fail_tokens / total_tokens, 4) if total_tokens else None,
    }


def per_task(rows: list[dict], condition: str, op: str) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for row in rows:
        if row["condition"] != condition:
            continue
        for step in row.get("trajectory", []):
            if step["op"] != op:
                continue
            entry = table.setdefault(row["task_id"], {"calls": 0, "tokens": 0})
            entry["calls"] += 1
            entry["tokens"] += int(step.get("observation_tokens", 0))
    return dict(sorted(table.items(), key=lambda kv: -kv[1]["tokens"]))


def classify_command(command: str) -> str:
    text = (command or "").lower()
    for hints, label in ((BUILD_HINTS, "build_or_test"), (READ_HINTS, "read_file"),
                         (WRITE_HINTS, "write_or_mkdir")):
        if any(h in text for h in hints):
            return label
    return "other"


def read_command_shape(rows: list[dict]) -> dict:
    """How many files does one raw-shell read command pull?

    This is the check that decides whether A's read cost is low because `type` is
    a leaner envelope or because A simply reads fewer files per command.
    """
    calls = tokens = file_refs = 0
    for row in rows:
        if row["condition"] != A_CONDITION:
            continue
        for step in row.get("trajectory", []):
            if step["op"] != A_EXEC_OP:
                continue
            command = (step.get("args", {}).get("command") or "").lower()
            if classify_command(command) != "read_file":
                continue
            calls += 1
            tokens += int(step.get("observation_tokens", 0))
            file_refs += sum(command.count(h) for h in ("type ", "cat ", "get-content"))
    return {
        "calls": calls,
        "tokens": tokens,
        "tokens_per_call": round(tokens / calls, 2) if calls else 0.0,
        "file_refs": file_refs,
        "file_refs_per_call": round(file_refs / calls, 2) if calls else 0.0,
        "tokens_per_file_ref": round(tokens / file_refs, 2) if file_refs else 0.0,
    }


# Buckets used for the D-vs-A gap decomposition. D's read/edit work is explicit
# typed ops; A does both inside `run_command`, so A is bucketed by the heuristic
# command classification instead.
D_BUCKETS = {
    "read": ("file.view", "file.read_many", "file.read_range"),
    "exec": ("exec.run",),
    "edit": ("file.replace_exact", "file.write", "file.edit_range", "file.apply_patch"),
}


def d_bucket(rows: list[dict], condition: str) -> dict[str, int]:
    out = {"read": 0, "exec": 0, "edit": 0, "meta": 0}
    for row in rows:
        if row["condition"] != condition:
            continue
        for step in row.get("trajectory", []):
            tokens = int(step.get("observation_tokens", 0))
            for name, ops in D_BUCKETS.items():
                if step["op"] in ops:
                    out[name] += tokens
                    break
            else:
                out["meta"] += tokens
    return out


def a_bucket(rows: list[dict]) -> dict[str, int]:
    out = {"read": 0, "exec": 0, "edit": 0, "meta": 0}
    for row in rows:
        if row["condition"] != A_CONDITION:
            continue
        for step in row.get("trajectory", []):
            tokens = int(step.get("observation_tokens", 0))
            if step["op"] != A_EXEC_OP:
                out["meta"] += tokens
                continue
            label = classify_command(step.get("args", {}).get("command", ""))
            if label == "read_file":
                out["read"] += tokens
            elif label == "write_or_mkdir":
                out["edit"] += tokens
            else:
                out["exec"] += tokens
    return out


def d_read_shape(rows: list[dict]) -> dict:
    """D's read cost per file reference, counted from the actual call arguments.

    `file.read_many` carries a `paths` array, so the file-reference count on D's
    side is exact; A's side is the heuristic count of `type`/`cat` in the command
    string. Comparing the two is the point: it separates "D reads more files" from
    "D pays more per file".
    """
    calls = tokens = file_refs = 0
    for row in rows:
        if row["condition"] != D_CONDITION:
            continue
        for step in row.get("trajectory", []):
            if step["op"] not in D_BUCKETS["read"]:
                continue
            calls += 1
            tokens += int(step.get("observation_tokens", 0))
            if step["op"] == "file.read_many":
                file_refs += len(step.get("args", {}).get("paths") or [])
            else:
                file_refs += 1
    return {
        "calls": calls,
        "tokens": tokens,
        "tokens_per_call": round(tokens / calls, 2) if calls else 0.0,
        "file_refs": file_refs,
        "file_refs_per_call": round(file_refs / calls, 2) if calls else 0.0,
        "tokens_per_file_ref": round(tokens / file_refs, 2) if file_refs else 0.0,
    }


def command_intents(rows: list[dict]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for row in rows:
        if row["condition"] != A_CONDITION:
            continue
        for step in row.get("trajectory", []):
            if step["op"] != A_EXEC_OP:
                continue
            label = classify_command(step.get("args", {}).get("command", ""))
            entry = table.setdefault(label, {"calls": 0, "tokens": 0})
            entry["calls"] += 1
            entry["tokens"] += int(step.get("observation_tokens", 0))
    for entry in table.values():
        entry["tokens_per_call"] = round(entry["tokens"] / entry["calls"], 2) if entry["calls"] else 0.0
    return dict(sorted(table.items(), key=lambda kv: -kv[1]["tokens"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    for name, path in ARMS.items():
        if not path.exists():
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 1

    rows = {name: load_rows(path) for name, path in ARMS.items()}
    report: dict = {
        "schema": "verseshell.exec-token-breakdown/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "inputs": [str(p.relative_to(ROOT)) for p in ARMS.values()],
            "run": "one (task, seed) cell; each arm is 10 tasks x 3 seeds = 30 D runs",
            "tokens": "len(projected_text) // 4, the same estimate the live bench records",
            "decomposition": "total/run = calls/run * tokens/call, so the change splits into "
                             "count effect (dc * p0), per-call effect (c1 * dp) and interaction (dc * dp)",
            "command_intent": "heuristic keyword buckets ordered build_or_test > read_file > "
                              "write_or_mkdir > other; raw shell reads files through `type`, so its "
                              "run_command cost is not comparable to D's exec.run without this split",
        },
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "arms": {},
    }

    for name, arm_rows in rows.items():
        runs_d = run_count(arm_rows, D_CONDITION)
        d_ops = op_table(arm_rows, D_CONDITION)
        d_total = sum(v["tokens"] for v in d_ops.values())
        exec_entry = d_ops.get(D_EXEC_OP, {"calls": 0, "tokens": 0})
        report["arms"][name] = {
            "d_runs": runs_d,
            "d_total_tokens": d_total,
            "d_tokens_per_run": round(d_total / runs_d, 2) if runs_d else None,
            "d_ops": d_ops,
            "exec_run": {
                "calls": exec_entry["calls"],
                "tokens": exec_entry["tokens"],
                "share_of_d_tokens": round(exec_entry["tokens"] / d_total, 4) if d_total else None,
                "tokens_per_run": round(exec_entry["tokens"] / runs_d, 2) if runs_d else None,
                "tokens_per_call": exec_entry.get("tokens_per_call"),
                "per_task": per_task(arm_rows, D_CONDITION, D_EXEC_OP),
                "ok_vs_failed": exec_split(arm_rows, D_CONDITION, D_EXEC_OP),
            },
            "read_shape": d_read_shape(arm_rows),
            "raw_shell": {
                "runs": run_count(arm_rows, A_CONDITION),
                "command": op_table(arm_rows, A_CONDITION).get(A_EXEC_OP, {}),
                "command_intents": command_intents(arm_rows),
                "read_command_shape": read_command_shape(arm_rows),
            },
        }

    w, o = report["arms"]["with_read_files"], report["arms"]["without_read_files"]
    report["exec_run_delta_with_minus_without"] = decompose(
        calls_before=o["exec_run"]["calls"], tokens_before=o["exec_run"]["tokens"],
        calls_after=w["exec_run"]["calls"], tokens_after=w["exec_run"]["tokens"],
        runs=w["d_runs"],
    )
    # Where does D's extra cost over A come from? Compare per-run totals and note
    # that A's single tool also performs the reading D splits into typed ops.
    a_runs = w["raw_shell"]["runs"]
    a_total = w["raw_shell"]["command"].get("tokens", 0)
    report["d_vs_a"] = {
        "a_total_tokens": a_total,
        "a_tokens_per_run": round(a_total / a_runs, 2) if a_runs else None,
        "d_tokens_per_run": w["d_tokens_per_run"],
        "gap_tokens_per_run": round((w["d_total_tokens"] - a_total) / a_runs, 2) if a_runs else None,
        "d_exec_run_tokens_per_run": w["exec_run"]["tokens_per_run"],
        "a_run_command_tokens_per_run": round(a_total / a_runs, 2) if a_runs else None,
        "note": "A's run_command also performs file reading (`type file`), which D splits into "
                "file.view / file.read_many, so a smaller D exec.run does not by itself make D "
                "cheaper; the raw_shell command_intents table shows how much of A is reading",
    }

    # Which bucket actually explains D costing more than A? D's typed ops are
    # bucketed directly; A's single tool is bucketed by command intent, so this
    # is a heuristic split and is reported as such.
    d_buckets = d_bucket(rows["with_read_files"], D_CONDITION)
    a_buckets = a_bucket(rows["with_read_files"])
    a_runs_total = w["raw_shell"]["runs"]
    total_gap = round((w["d_total_tokens"] - a_total) / a_runs_total, 2) if a_runs_total else 0.0
    buckets = {}
    for key in ("read", "exec", "edit", "meta"):
        d_per_run = d_buckets[key] / w["d_runs"] if w["d_runs"] else 0.0
        a_per_run = a_buckets[key] / a_runs_total if a_runs_total else 0.0
        delta = d_per_run - a_per_run
        buckets[key] = {
            "d_tokens_per_run": round(d_per_run, 2),
            "a_tokens_per_run": round(a_per_run, 2),
            "delta_tokens_per_run": round(delta, 2),
            "share_of_gap": round(delta / total_gap, 4) if total_gap else None,
        }
    report["gap_decomposition"] = {
        "runs_d": w["d_runs"],
        "runs_a": a_runs_total,
        "total_gap_tokens_per_run": total_gap,
        "buckets": buckets,
        "note": "D buckets by typed op; A buckets by heuristic command intent. A's read bucket is "
                "`type`-style commands, which is how A reads files at all, so this is the closest "
                "available like-for-like split rather than an exact one",
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    for name in ARMS:
        arm = report["arms"][name]
        ex = arm["exec_run"]
        okf = ex["ok_vs_failed"]
        print(f"[{name}] D runs={arm['d_runs']} total={arm['d_total_tokens']} tok "
              f"({arm['d_tokens_per_run']}/run)")
        print(f"   exec.run {ex['calls']} calls, {ex['tokens']} tok "
              f"= {ex['share_of_d_tokens'] * 100:.1f}% of D, {ex['tokens_per_run']}/run, "
              f"{ex['tokens_per_call']}/call")
        print(f"   ok {okf['ok']['calls']} calls @{okf['ok']['tokens_per_call']} | "
              f"failed {okf['failed']['calls']} calls @{okf['failed']['tokens_per_call']} "
              f"= {okf['failed_share_of_tokens'] * 100:.1f}% of exec tokens "
              f"({okf['failed_share_of_calls'] * 100:.1f}% of calls)")
    dec = report["exec_run_delta_with_minus_without"]
    print(f"exec.run delta (with - without): {dec['delta_tokens_per_run']}/run = "
          f"count {dec['count_effect']} ({dec['count_share'] * 100:.0f}%) + "
          f"per-call {dec['per_call_effect']} ({dec['per_call_share'] * 100:.0f}%) + "
          f"interaction {dec['interaction']}")
    print("raw-shell command intents: " + ", ".join(
        f"{k}:{v['calls']}/{v['tokens']}" for k, v in w["raw_shell"]["command_intents"].items()))
    rcs = w["raw_shell"]["read_command_shape"]
    drs = w["read_shape"]
    print(f"D read ops:  {drs['calls']} calls, {drs['tokens']} tok, {drs['tokens_per_call']}/call, "
          f"{drs['file_refs_per_call']} file refs/call, {drs['tokens_per_file_ref']}/file ref")
    print(f"A read cmds: {rcs['calls']} calls, {rcs['tokens']} tok, {rcs['tokens_per_call']}/call, "
          f"{rcs['file_refs_per_call']} file refs/call, {rcs['tokens_per_file_ref']}/file ref")
    print(f"D {w['d_tokens_per_run']}/run vs A {report['d_vs_a']['a_tokens_per_run']}/run "
          f"(gap {report['d_vs_a']['gap_tokens_per_run']})")
    gap = report["gap_decomposition"]
    print(f"gap decomposition (total {gap['total_gap_tokens_per_run']}/run):")
    for key, entry in gap["buckets"].items():
        share = entry["share_of_gap"]
        share_text = f"{share * 100:5.1f}% of gap" if share is not None else "n/a"
        print(f"   {key:<6} D {entry['d_tokens_per_run']:>7} vs A {entry['a_tokens_per_run']:>7} "
              f"= {entry['delta_tokens_per_run']:>+7} ({share_text})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
