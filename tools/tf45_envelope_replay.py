#!/usr/bin/env python3
"""TF-0045: measure the batch-read envelope change on a frozen trajectory.

The live A/B answers "how does ACI compare to raw shell", but it cannot isolate a
single envelope change — the model's own calls move too. This tool holds the
calls fixed: it replays the read ops the model actually issued in the stored live
run against the current binary, and projects every observation twice:

  * legacy  = the pre-TF-0045 client projection (full `sha256:<64 hex>` per file)
  * current = the TF-0045 projection (16-hex compact digest, prefix-matchable)

Both projections run on the *same* envelope produced by the *same* binary, so the
delta is exactly the client-side effect of the envelope change, with no sampling
noise and no API calls. It also checks the new batch budget: a worst-case read of
8 large files must not return more lines than `max_total_lines`.

The tool is deliberately not a benchmark of the model. It measures the observation
surface, which is what claim C14 gates.

Usage:
    python tools/tf45_envelope_replay.py                 # JSON on stdout
    python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
FIXTURES = BENCH / "fixtures"
AE = ROOT / "target" / "debug" / "ae.exe"
STORED_LIVE = BENCH / "results" / "latest_live.json"

sys.path.insert(0, str(BENCH / "runners"))
from fixture_deps import materialize_deps  # noqa: E402
from live_agent_loop import (  # noqa: E402
    ACI_CAPABILITIES,
    estimate_tokens,
    format_aci_result,
)

# The measured surface: the product code that shapes the envelope, the client
# that projects it, and the frozen call set the replay is pinned to.
EVIDENCE_GLOBS = [
    "src/**/*.rs",
    "Cargo.toml",
    "bench/aci/fixtures/**/*",
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/results/latest_live.json",
    "tools/tf45_envelope_replay.py",
]

READ_OPS = ("file.read_many", "file.view", "file.read_range")

# Worst-case batch budget probe: 8 files, each far longer than one window.
BUDGET_FILES = 8
BUDGET_LINES_PER_FILE = 300


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


def run_op(op: str, args: dict, workspace: Path, timeout: int = 120) -> dict:
    """Run one ACI op through `ae --serve --agent`, same way the bench does."""
    env = dict(os.environ)
    env["AETHER_APPROVE_ALL"] = "1"
    env["AETHER_MODE"] = "agent"
    env["AETHER_WORKSPACE"] = str(workspace)
    proc = subprocess.Popen(
        [str(AE), "--serve", "--agent", "--cap", ACI_CAPABILITIES],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    payload = {
        "id": uuid.uuid4().hex[:12],
        "agent": "tf45_replay",
        "op": op,
        "args": args,
        "timeout_ms": 60000,
        "budget": {"max_tokens": 4000},
    }
    out, err = proc.communicate(json.dumps(payload).encode() + b"\n", timeout=timeout)
    lines = [ln for ln in out.decode("utf-8", "replace").split("\n") if ln.strip()]
    if not lines:
        raise RuntimeError(f"{op}: no output ({err.decode('utf-8', 'replace')[:300]})")
    return json.loads(lines[0])


def prepare_workspace(fixture: str) -> Path:
    src = FIXTURES / fixture
    td = Path(tempfile.mkdtemp(prefix=f"tf45-replay-{fixture}-"))
    for item in src.iterdir():
        if item.name in ("GOLDEN", "deps"):
            continue
        dest = td / item.name
        if item.is_dir():
            shutil.copytree(
                item, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
            )
        else:
            shutil.copy2(item, dest)
    materialize_deps(src, td)
    return td


def strip_compact_digest(envelope: dict) -> dict:
    """The envelope as the pre-TF-0045 client saw it.

    Removing the compact `hash` field is exactly the legacy view: the current
    projection falls back to the full `content_hash` when `hash` is absent.
    """
    legacy = copy.deepcopy(envelope)
    data = legacy.get("data")
    if isinstance(data, dict):
        data.pop("hash", None)
        for entry in data.get("files") or []:
            if isinstance(entry, dict):
                entry.pop("hash", None)
    return legacy


def frozen_calls() -> list[dict]:
    """Read ops the model issued in the stored live run (condition D)."""
    payload = json.loads(STORED_LIVE.read_text(encoding="utf-8-sig"))
    calls: list[dict] = []
    for row in payload.get("rows", []):
        if row.get("condition") != "verseshell_aci":
            continue
        for step in row.get("trajectory", []):
            if step.get("op") in READ_OPS:
                calls.append({
                    "task_id": row["task_id"],
                    "fixture": None,
                    "op": step["op"],
                    "args": step.get("args", {}),
                    "stored_tokens": int(step.get("observation_tokens", 0)),
                })
    # The stored rows carry no fixture name; join it from the task definition.
    tasks_dir = BENCH / "tasks"
    fixtures = {}
    for path in tasks_dir.glob("*.json"):
        if path.name == "manifest.json":
            continue
        try:
            task = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        fixtures[task.get("id")] = task.get("workspace_fixture")
    for call in calls:
        call["fixture"] = fixtures.get(call["task_id"])
    return calls


def replay(calls: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for call in calls:
        workspace = prepare_workspace(call["fixture"])
        try:
            envelope = run_op(call["op"], call["args"], workspace)
            legacy_text = format_aci_result(strip_compact_digest(envelope))
            current_text = format_aci_result(envelope)
            data = envelope.get("data") or {}
            files = data.get("files") if isinstance(data.get("files"), list) else []
            legacy_tokens = estimate_tokens(legacy_text)
            current_tokens = estimate_tokens(current_text)
            # A call counts as faithfully reproduced only when replaying it
            # through the current binary reproduces the exact token count the
            # stored live run recorded, under the projection that run actually
            # used: `current` once the compact-digest client shipped, `legacy`
            # before it. That is the precondition for treating the delta as a
            # counterfactual, and it is what makes the tool refuse to compare
            # across a client change that was never re-measured.
            # It fails for files the live run itself produced or mutated —
            # `.ae/audit.log`, `ERR.txt`, `out/result.txt` — whose content
            # depends on run history the pristine fixture cannot rebuild.
            code = (envelope.get("error") or {}).get("code")
            matched = None
            if current_tokens == call["stored_tokens"]:
                matched = "current"
            elif legacy_tokens == call["stored_tokens"]:
                matched = "legacy"
            if code == "E_NOT_FOUND":
                reproducible = False
                reason = "file did not exist in the pristine fixture (created by the live run)"
            elif matched is None:
                reproducible = False
                reason = (
                    "content depends on live-run history: current projection "
                    f"{current_tokens} tok / legacy projection {legacy_tokens} tok vs "
                    f"{call['stored_tokens']} tok recorded live"
                )
            else:
                reproducible = True
                reason = None
            rows.append({
                "task_id": call["task_id"],
                "op": call["op"],
                "args": call["args"],
                "ok": envelope.get("ok"),
                "reproducible": reproducible,
                "unreproducible_reason": reason,
                "matched_projection": matched,
                "stored_tokens": call["stored_tokens"],
                "legacy_chars": len(legacy_text),
                "current_chars": len(current_text),
                "legacy_tokens": legacy_tokens,
                "current_tokens": current_tokens,
                # A truncated entry would mean the frozen call already used the
                # new budget semantics, and the legacy comparison would no
                # longer be exact. The stored fixtures are small, so this is a
                # guard, not an expectation.
                "truncated_entries": sum(
                    1 for e in files
                    if isinstance(e, dict) and (e.get("truncated") or e.get("deferred"))
                ),
            })
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    return rows


def budget_probe() -> dict:
    """A worst-case batch read must respect `max_total_lines` and stay paginable."""
    workspace = Path(tempfile.mkdtemp(prefix="tf45-budget-"))
    try:
        names = []
        body = "".join(f"line {i}\n" for i in range(1, BUDGET_LINES_PER_FILE + 1))
        for i in range(BUDGET_FILES):
            name = f"big{i}.txt"
            (workspace / name).write_text(body, encoding="utf-8")
            names.append(name)

        default = run_op("file.read_many", {"paths": names}, workspace)
        tight = run_op(
            "file.read_many",
            {"paths": names, "window": 100, "max_total_lines": 40},
            workspace,
        )

        def summarize(envelope: dict) -> dict:
            data = envelope.get("data") or {}
            files = data.get("files") or []
            lines = sum(len(e.get("lines") or []) for e in files if isinstance(e, dict))
            return {
                "lines_returned": lines,
                "reported_lines_returned": data.get("lines_returned"),
                "max_total_lines": data.get("max_total_lines"),
                "deferred": data.get("deferred"),
                "paginable": all(
                    isinstance(e.get("next_start_line"), int)
                    for e in files
                    if isinstance(e, dict) and (e.get("truncated") or e.get("deferred"))
                ),
                "all_within_budget": lines <= int(data.get("max_total_lines") or 0),
            }

        default_summary = summarize(default)
        tight_summary = summarize(tight)

        # Pagination round-trip: walk a file page by page using the
        # `next_start_line` the op hands back and require the concatenation to
        # equal the file itself. This is what makes a bounded window usable
        # rather than lossy.
        page_file = workspace / "paged.txt"
        page_lines = [f"paged line {i}" for i in range(1, 251)]
        page_file.write_text("".join(f"{ln}\n" for ln in page_lines), encoding="utf-8")
        collected: list[str] = []
        start_line = 1
        pages = 0
        while start_line is not None and pages < 10:
            pages += 1
            page = run_op(
                "file.read_many",
                {"paths": ["paged.txt"], "windows": [{"start_line": start_line, "window": 100}]},
                workspace,
            )
            entry = (page.get("data") or {}).get("files", [{}])[0]
            collected.extend(
                ln.get("text", "") for ln in entry.get("lines") or [] if isinstance(ln, dict)
            )
            start_line = entry.get("next_start_line") if entry.get("truncated") else None
        pagination_roundtrip = collected == page_lines

        return {
            "files": BUDGET_FILES,
            "lines_per_file": BUDGET_LINES_PER_FILE,
            "default": default_summary,
            "tight": tight_summary,
            "pagination": {
                "file_lines": len(page_lines),
                "window": 100,
                "pages": pages,
                "lines_recovered": len(collected),
                "roundtrip_exact": pagination_roundtrip,
            },
            "bounded": bool(
                default_summary["all_within_budget"] and tight_summary["all_within_budget"]
            ),
            "pagination_roundtrip": pagination_roundtrip,
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if not AE.exists():
        print(f"ERROR: ae not found at {AE} (run cargo build)", file=sys.stderr)
        return 1

    calls = frozen_calls()
    rows = replay(calls)
    budget = budget_probe()

    usable = [r for r in rows if r["reproducible"]]
    excluded = [r for r in rows if not r["reproducible"]]

    legacy_tokens = sum(r["legacy_tokens"] for r in usable)
    current_tokens = sum(r["current_tokens"] for r in usable)
    savings = 1.0 - (current_tokens / legacy_tokens) if legacy_tokens else 0.0

    by_op: dict[str, dict] = {}
    for row in usable:
        acc = by_op.setdefault(
            row["op"], {"calls": 0, "legacy_tokens": 0, "current_tokens": 0}
        )
        acc["calls"] += 1
        acc["legacy_tokens"] += row["legacy_tokens"]
        acc["current_tokens"] += row["current_tokens"]
    for acc in by_op.values():
        acc["savings"] = (
            round(1.0 - acc["current_tokens"] / acc["legacy_tokens"], 4)
            if acc["legacy_tokens"] else 0.0
        )

    stored_by_op: dict[str, int] = {}
    for row in rows:
        stored_by_op[row["op"]] = stored_by_op.get(row["op"], 0) + 1

    exact = all(r["truncated_entries"] == 0 for r in usable)
    coverage = len(usable) / len(rows) if rows else 0.0
    matched_counts: dict[str, int] = {}
    for r in usable:
        key = r["matched_projection"] or "unknown"
        matched_counts[key] = matched_counts.get(key, 0) + 1
    report = {
        "schema": "verseshell.tf45-envelope-replay/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "frozen_call_source": "bench/aci/results/latest_live.json (condition D read ops)",
            "legacy_projection": "format_aci_result on the envelope with the compact `hash` removed "
                                 "(== the pre-TF-0045 client projection)",
            "current_projection": "format_aci_result on the envelope as returned by the current binary",
            "tokens": "len(projected_text) // 4 (same estimate the live bench records)",
            "reproducible_call": "a frozen call is counted only when replaying it through the current "
                                 "binary reproduces the exact token count the stored live run recorded, "
                                 "under the projection that run actually used (`current` once the "
                                 "compact-digest client shipped, `legacy` before it); calls that read "
                                 "run-produced state (audit log, ERR.txt, out/...) fail that test and "
                                 "are listed with both numbers",
            "caveat": "client-side envelope effect on a frozen call set; it is NOT a model-behaviour "
                      "measurement and says nothing about whether the model would choose different calls",
        },
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "totals": {
            "calls": len(rows),
            "calls_replayed": len(usable),
            "calls_excluded": len(excluded),
            "coverage": round(coverage, 4),
            "stored_projection_matched": matched_counts,
            "excluded": [
                {"task_id": r["task_id"], "op": r["op"], "args": r["args"],
                 "stored_tokens": r["stored_tokens"], "legacy_tokens": r["legacy_tokens"],
                 "reason": r["unreproducible_reason"]}
                for r in excluded
            ],
            "legacy_tokens": legacy_tokens,
            "current_tokens": current_tokens,
            "token_savings": round(savings, 4),
            "legacy_chars": sum(r["legacy_chars"] for r in usable),
            "current_chars": sum(r["current_chars"] for r in usable),
            "legacy_comparison_exact": exact,
        },
        "by_op": by_op,
        "stored_calls_by_op": stored_by_op,
        "budget": budget,
        "rows": rows,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    print(
        f"replay: {len(usable)}/{len(rows)} frozen read calls reproduced exactly "
        f"(matched={matched_counts}; {len(excluded)} excluded: run-produced state) | "
        f"legacy={legacy_tokens} tok -> current={current_tokens} tok "
        f"({savings * 100:.1f}% saved) | no truncation={exact}"
    )
    for op, acc in sorted(by_op.items()):
        print(f"  {op:<16} calls={acc['calls']}/{stored_by_op.get(op, 0):<3} "
              f"{acc['legacy_tokens']:>5} -> {acc['current_tokens']:>5} tok "
              f"({acc['savings'] * 100:.1f}%)")
    print(
        f"budget: {budget['files']}x{budget['lines_per_file']} lines | "
        f"default={budget['default']['lines_returned']} lines "
        f"(<= {budget['default']['max_total_lines']}) | "
        f"tight={budget['tight']['lines_returned']} lines "
        f"(<= {budget['tight']['max_total_lines']}) | bounded={budget['bounded']} | "
        f"pagination_roundtrip={budget['pagination_roundtrip']} "
        f"({budget['pagination']['pages']} pages, "
        f"{budget['pagination']['lines_recovered']}/{budget['pagination']['file_lines']} lines)"
    )
    return 0 if (exact and coverage > 0 and budget["bounded"]
                 and budget["pagination_roundtrip"]) else 1


if __name__ == "__main__":
    sys.exit(main())
