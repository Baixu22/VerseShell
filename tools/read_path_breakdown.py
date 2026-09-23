#!/usr/bin/env python3
"""TF-0062: measure and attribute condition D's read-path observation.

C15 showed reading is 58.9% of the D-vs-A token gap and that D pays 48.0 tokens
per file reference against raw shell's 26.0. This tool answers the next question —
*which part of the read observation* is that — using the same frozen-trajectory
method as `tools/tf45_envelope_replay.py`: replay the read calls the model
actually issued and measure the projection directly.

Two things are reported:

  * **attribution** of the projected characters, so the structure is visible
    rather than guessed: content, the newline wrapper, the digest, the paths, the
    derivable counts, and a residual bucket (key names, braces, commas).
  * the **compact-projection A/B**: the same envelope projected with
    `format_aci_result(compact=False)` (the pre-change rendering) and
    `(compact=True)` (current). Both come from the real projector, so the delta is
    the actual client-side effect and not a re-implementation.

Usage:
    python tools/read_path_breakdown.py --out eval/read_path_breakdown.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
sys.path.insert(0, str(ROOT / "tools"))
from tf45_envelope_replay import (  # noqa: E402
    frozen_calls,
    prepare_workspace,
    run_op,
)

sys.path.insert(0, str(BENCH / "runners"))
from live_agent_loop import format_aci_result  # noqa: E402

EVIDENCE_GLOBS = [
    "src/**/*.rs",
    "bench/aci/fixtures/**/*",
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/results/latest_live.json",
    "tools/tf45_envelope_replay.py",
    "tools/read_path_breakdown.py",
]


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


def project(envelope: dict, *, compact: bool) -> str:
    return format_aci_result(envelope, compact=compact)


# Attribution uses two exact techniques rather than one clever-but-fragile one:
#   * `content` and `lines_wrapper` are computed directly (a JSON array of N
#     strings costs the text plus exactly 4N: two quotes per string, two
#     separator characters per gap, two brackets).
#   * `digest`, `path` and `counts` are measured by *deleting* those fields and
#     re-projecting, which only ever removes content so the difference cannot go
#     negative. Deleting is not safe for `ok` (it selects the projection branch)
#     or for `hash` alone (the projection falls back to the 71-char
#     `content_hash`), so the digest variant removes both digest fields.
# `residual` is what no single value owns: the remaining key names, braces,
# commas and the `files` array container.
def variant_no_digest(envelope: dict) -> dict:
    clone = copy.deepcopy(envelope)
    data = clone.get("data")
    if isinstance(data, dict):
        data.pop("content_hash", None)
        for entry in data.get("files") or []:
            if isinstance(entry, dict):
                entry.pop("hash", None)
                entry.pop("content_hash", None)
    return clone


def variant_no_paths(envelope: dict) -> dict:
    clone = copy.deepcopy(envelope)
    data = clone.get("data")
    if isinstance(data, dict):
        for entry in data.get("files") or []:
            if isinstance(entry, dict):
                entry.pop("path", None)
    return clone


def variant_no_counts(envelope: dict) -> dict:
    clone = copy.deepcopy(envelope)
    data = clone.get("data")
    if isinstance(data, dict):
        data.pop("total_lines", None)
        data.pop("start_line", None)
        for entry in data.get("files") or []:
            if isinstance(entry, dict):
                entry.pop("total_lines", None)
                entry.pop("start_line", None)
    return clone


def item_line_stats(item: object) -> tuple[int, int]:
    """(text characters, line count) for one `lines` array."""
    if not isinstance(item, dict):
        return 0, 0
    chars = 0
    count = 0
    for line in item.get("lines") or []:
        count += 1
        if isinstance(line, dict):
            chars += len(line.get("text", ""))
        else:
            chars += len(str(line))
    return chars, count


def line_stats(envelope: dict) -> tuple[int, int]:
    """(text characters, line count) across the top level and every entry."""
    data = envelope.get("data") or {}
    chars, count = item_line_stats(data)
    for entry in data.get("files") or []:
        entry_chars, entry_count = item_line_stats(entry)
        chars += entry_chars
        count += entry_count
    return chars, count


def attribute(envelope: dict, *, compact: bool) -> dict:
    """Attribute the projected text to content, per-value costs and residual."""
    base = project(envelope, compact=compact)
    total = len(base)
    content, lines = line_stats(envelope)
    parts = {
        "content": content,
        # A JSON array of N strings costs the text plus exactly 4N (two quotes and
        # two separator characters per line, two brackets); the compact rendering
        # joins them into one string, which costs 2N (two quotes plus two escaped
        # newlines per gap).
        "line_wrapper": (2 * lines) if compact else (4 * lines),
        "digest": total - len(project(variant_no_digest(envelope), compact=compact)),
        "path": total - len(project(variant_no_paths(envelope), compact=compact)),
        "counts": total - len(project(variant_no_counts(envelope), compact=compact)),
    }
    parts["residual"] = total - sum(parts.values())
    return {"total_chars": total, "parts": parts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    calls = frozen_calls()
    per_call: list[dict] = []
    by_op: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "legacy_chars": 0, "current_chars": 0,
        "legacy_tokens": 0, "current_tokens": 0,
        "legacy_parts": defaultdict(int), "current_parts": defaultdict(int),
    })
    excluded = 0
    matched = {"legacy": 0, "current": 0}

    for call in calls:
        workspace = prepare_workspace(call["fixture"])
        try:
            envelope = run_op(call["op"], call["args"], workspace)
            legacy_text = project(envelope, compact=False)
            current_text = project(envelope, compact=True)
            legacy_tokens = len(legacy_text) // 4
            current_tokens = len(current_text) // 4
            # Count only calls the stored live run can vouch for, under whichever
            # projection that run used. A client change without a live re-run then
            # fails loudly instead of comparing across projections.
            if legacy_tokens == call["stored_tokens"]:
                which = "legacy"
            elif current_tokens == call["stored_tokens"]:
                which = "current"
            else:
                excluded += 1
                continue
            matched[which] += 1
            legacy_att = attribute(envelope, compact=False)
            current_att = attribute(envelope, compact=True)
            per_call.append({
                "task_id": call["task_id"], "op": call["op"], "args": call["args"],
                "matched_projection": which,
                "legacy_chars": legacy_att["total_chars"],
                "current_chars": current_att["total_chars"],
                "legacy_tokens": legacy_tokens,
                "current_tokens": current_tokens,
                "legacy_parts": legacy_att["parts"],
                "current_parts": current_att["parts"],
            })
            bucket = by_op[call["op"]]
            bucket["calls"] += 1
            bucket["legacy_chars"] += legacy_att["total_chars"]
            bucket["current_chars"] += current_att["total_chars"]
            bucket["legacy_tokens"] += legacy_tokens
            bucket["current_tokens"] += current_tokens
            for key, value in legacy_att["parts"].items():
                bucket["legacy_parts"][key] += value
            for key, value in current_att["parts"].items():
                bucket["current_parts"][key] += value
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def shares(parts: dict[str, int], total: int) -> dict[str, float]:
        if not total:
            return {}
        return {k: round(v / total, 4) for k, v in sorted(parts.items(), key=lambda kv: -kv[1])}

    def aggregate(items: list[dict], key: str) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for item in items:
            for name, value in item[key].items():
                out[name] += value
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    legacy_chars = sum(r["legacy_chars"] for r in per_call)
    current_chars = sum(r["current_chars"] for r in per_call)
    legacy_tokens = sum(r["legacy_tokens"] for r in per_call)
    current_tokens = sum(r["current_tokens"] for r in per_call)
    legacy_parts = aggregate(per_call, "legacy_parts")
    current_parts = aggregate(per_call, "current_parts")

    def op_view(bucket: dict) -> dict:
        return {
            "calls": bucket["calls"],
            "legacy_chars": bucket["legacy_chars"],
            "current_chars": bucket["current_chars"],
            "char_savings": round(1.0 - bucket["current_chars"] / bucket["legacy_chars"], 4)
            if bucket["legacy_chars"] else None,
            "legacy_tokens": bucket["legacy_tokens"],
            "current_tokens": bucket["current_tokens"],
            "token_savings": round(1.0 - bucket["current_tokens"] / bucket["legacy_tokens"], 4)
            if bucket["legacy_tokens"] else None,
            "legacy_parts": dict(bucket["legacy_parts"]),
            "legacy_part_shares": shares(bucket["legacy_parts"], bucket["legacy_chars"]),
            "current_parts": dict(bucket["current_parts"]),
            "current_part_shares": shares(bucket["current_parts"], bucket["current_chars"]),
        }

    report = {
        "schema": "verseshell.read-path-breakdown/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "frozen_call_source": "bench/aci/results/latest_live.json (condition D read ops)",
            "ab": "the same envelope is projected twice with the real projector: "
                  "format_aci_result(compact=False) is the pre-change rendering, "
                  "format_aci_result(compact=True) is current",
            "attribution": "content and line_wrapper are computed exactly (a JSON array of N strings costs "
                           "the text plus 4N); digest, path and counts are measured by deleting those fields "
                           "and re-projecting, which only removes content so no part can go negative; "
                           "`residual` is the key names, braces, commas and array containers no single value owns",
            "reproducible_call": "a call counts only when one of the two projections reproduces the token "
                                 "count the stored live run recorded, so a client change without a live "
                                 "re-run fails instead of comparing across projections",
        },
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "totals": {
            "calls": len(per_call),
            "excluded_calls": excluded,
            "matched_projection": matched,
            "legacy_chars": legacy_chars,
            "current_chars": current_chars,
            "char_savings": round(1.0 - current_chars / legacy_chars, 4) if legacy_chars else None,
            "legacy_tokens": legacy_tokens,
            "current_tokens": current_tokens,
            "token_savings": round(1.0 - current_tokens / legacy_tokens, 4) if legacy_tokens else None,
            "legacy_parts": legacy_parts,
            "legacy_part_shares": shares(legacy_parts, legacy_chars),
            "current_parts": current_parts,
            "current_part_shares": shares(current_parts, current_chars),
        },
        "by_op": {op: op_view(bucket) for op, bucket in by_op.items()},
        "rows": per_call,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    t = report["totals"]
    print(f"read bucket: {t['calls']} calls ({t['excluded_calls']} excluded), "
          f"matched={t['matched_projection']}")
    print(f"  compact projection: {t['legacy_chars']} -> {t['current_chars']} chars "
          f"({t['char_savings'] * 100:.1f}%), {t['legacy_tokens']} -> {t['current_tokens']} tok "
          f"({t['token_savings'] * 100:.1f}%)")
    print("  pre-change attribution (share of chars):")
    for key, value in t["legacy_parts"].items():
        print(f"    {key:<16}{value:>7}  {t['legacy_part_shares'][key] * 100:5.1f}%")
    print("  after-change attribution (share of chars):")
    for key, value in t["current_parts"].items():
        print(f"    {key:<16}{value:>7}  {t['current_part_shares'][key] * 100:5.1f}%")
    for op, view in report["by_op"].items():
        print(f"  {op:<16} calls={view['calls']:<3} "
              f"{view['legacy_tokens']:>5} -> {view['current_tokens']:>5} tok "
              f"({view['token_savings'] * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
