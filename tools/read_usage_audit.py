#!/usr/bin/env python3
"""TF-0067: classify what condition D's reads are actually *for*.

C15/C16 left the read path as the biggest remaining share of the D-vs-A gap
(52.6%) with its structural overhead spent. The open question is behavioural:
does D read files it has no use for? This tool answers it from stored artifacts
only, with a classification that is defined in code rather than by eye:

  referenced_in_run  the path is edited, or named in an exec command, in the
                     same run — the read has a visible downstream use
  task_subject       the path is named in the task prompt or in a success
                     predicate — the read is about the thing being fixed
  task_file          the fixture's own `TASK.md`, whose text the system prompt
                     already carries as the task hint
  unreferenced       none of the above

Classification is per read *path*; a batched call's tokens are apportioned
evenly across the paths it asked for, which is an apportionment and is labelled
as one. Raw shell is classified the same way from its `type`/`cat` file refs so
the two conditions can be compared.

Usage:
    python tools/read_usage_audit.py --out eval/read_usage_audit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
TASKS_DIR = BENCH / "tasks"
RESULTS = BENCH / "results"
sys.path.insert(0, str(ROOT / "tools"))
from exec_token_breakdown import classify_command  # noqa: E402

ARMS = {
    "with_read_files": RESULTS / "latest_live.json",
    "without_read_files": RESULTS / "live_ab_without_read_files.json",
}

D_READ_OPS = {"file.read_many", "file.view", "file.read_range"}
EDIT_OPS = {"file.replace_exact", "file.write", "file.edit_range", "file.apply_patch"}
A_OP = "run_command"
TASK_FILE = "TASK.md"

EVIDENCE_GLOBS = [
    "bench/aci/tasks/*.json",
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "tools/read_usage_audit.py",
]

PATH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9]{1,8}")
FILE_REF_RE = re.compile(r"(?:type|cat|get-content)\s+([^\s&|]+)", re.IGNORECASE)

CLASSES = ("referenced_in_run", "task_subject", "task_file", "unreferenced")


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


def load_tasks() -> dict[str, dict]:
    tasks = {}
    for path in TASKS_DIR.glob("*.json"):
        if path.name == "manifest.json":
            continue
        task = json.loads(path.read_text(encoding="utf-8-sig"))
        tasks[task["id"]] = task
    return tasks


def task_subject_paths(task: dict) -> set[str]:
    """Paths the task itself names: the prompt plus every success predicate path."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            value = node.get("path")
            if isinstance(value, str):
                found.add(value)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(task.get("success"))
    for match in PATH_RE.findall(task.get("prompt", "")):
        found.add(match)
    return found


def normalise(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def classify(path: str, referenced: set[str], subjects: set[str]) -> str:
    key = normalise(path)
    if key in referenced or path in referenced:
        return "referenced_in_run"
    if key in subjects or path in subjects:
        return "task_subject"
    if key.upper() == TASK_FILE.upper():
        return "task_file"
    return "unreferenced"


def referenced_set(steps: list[dict]) -> set[str]:
    """Everything the run touched outside reading, normalised."""
    out: set[str] = set()
    for step in steps:
        args = step.get("args", {})
        if step["op"] in EDIT_OPS and args.get("path"):
            out.add(normalise(args["path"]))
        if step["op"] in (A_OP, "exec.run"):
            blob = args.get("command") or " ".join(args.get("argv") or [])
            for token in str(blob).replace("\\", "/").split():
                out.add(normalise(token.strip('"\'')))
    return out


def referenced_set_raw_shell(steps: list[dict]) -> set[str]:
    """Downstream use for raw shell, excluding the read command itself.

    A reads files *inside* `run_command`, so the naive rule would classify every
    `type file` as "referenced" by its own command. Only edits and commands whose
    primary intent is not reading count here, which is what makes the two
    conditions comparable.
    """
    out: set[str] = set()
    for step in steps:
        args = step.get("args", {})
        if step["op"] in EDIT_OPS and args.get("path"):
            out.add(normalise(args["path"]))
        if step["op"] != A_OP:
            continue
        command = str(args.get("command", ""))
        if classify_command(command) == "read_file":
            continue
        for token in command.replace("\\", "/").split():
            out.add(normalise(token.strip('"\'')))
    return out


def audit_condition(rows: list[dict], condition: str, tasks: dict[str, dict],
                    read_ops: set[str]) -> dict:
    per_class_calls: Counter = Counter()
    per_class_paths: Counter = Counter()
    per_class_tokens: defaultdict = defaultdict(float)
    per_task: defaultdict = defaultdict(Counter)
    path_counts: Counter = Counter()
    detail: list[dict] = []

    for row in rows:
        if row["condition"] != condition:
            continue
        task = tasks.get(row["task_id"])
        if task is None:
            continue
        subjects = task_subject_paths(task)
        steps = row.get("trajectory", [])
        referenced = referenced_set(steps)
        for step in steps:
            if step["op"] not in read_ops:
                continue
            args = step.get("args", {})
            if step["op"] == "file.read_many":
                paths = [p for p in (args.get("paths") or []) if isinstance(p, str)]
            else:
                # file.view / file.read_range take a single `path`
                paths = [args["path"]] if args.get("path") else []
            if not paths:
                continue
            tokens = int(step.get("observation_tokens", 0))
            share = tokens / len(paths)
            classes = [classify(p, referenced, subjects) for p in paths]
            for path, klass in zip(paths, classes):
                per_class_paths[klass] += 1
                per_class_tokens[klass] += share
                per_task[row["task_id"]][klass] += 1
                path_counts[f"{klass}:{normalise(path)}"] += 1
            # call-level label: uniform calls take their class, mixed calls are
            # labelled by the majority class so the call counts stay meaningful
            label = classes[0] if len(set(classes)) == 1 else "mixed:" + "+".join(sorted(set(classes)))
            per_class_calls[label] += 1
            detail.append({
                "task_id": row["task_id"], "op": step["op"], "paths": paths,
                "classes": classes, "tokens": tokens, "share_per_path": round(share, 2),
            })

    total_tokens = sum(per_class_tokens.values())
    return {
        "calls": sum(per_class_calls.values()),
        "paths": sum(per_class_paths.values()),
        "tokens": round(total_tokens, 2),
        "per_class_calls": dict(per_class_calls),
        "per_class_paths": dict(per_class_paths),
        "per_class_tokens": {k: round(v, 2) for k, v in per_class_tokens.items()},
        "per_class_token_share": {
            k: round(v / total_tokens, 4) for k, v in sorted(per_class_tokens.items(), key=lambda kv: -kv[1])
        } if total_tokens else {},
        "per_task_class_counts": {k: dict(v) for k, v in sorted(per_task.items())},
        "top_paths": path_counts.most_common(15),
        "rows": detail,
    }


def audit_raw_shell(rows: list[dict], tasks: dict[str, dict]) -> dict:
    per_class_paths: Counter = Counter()
    per_class_tokens: defaultdict = defaultdict(float)
    path_counts: Counter = Counter()
    for row in rows:
        if row["condition"] != "raw_shell":
            continue
        task = tasks.get(row["task_id"])
        if task is None:
            continue
        subjects = task_subject_paths(task)
        steps = row.get("trajectory", [])
        referenced = referenced_set_raw_shell(steps)
        for step in steps:
            if step["op"] != A_OP:
                continue
            command = str(step.get("args", {}).get("command", ""))
            refs = FILE_REF_RE.findall(command)
            if not refs:
                continue
            tokens = int(step.get("observation_tokens", 0))
            share = tokens / len(refs)
            for ref in refs:
                klass = classify(ref, referenced, subjects)
                per_class_paths[klass] += 1
                per_class_tokens[klass] += share
                path_counts[normalise(ref)] += 1
    total = sum(per_class_tokens.values())
    return {
        "file_refs": sum(per_class_paths.values()),
        "tokens": round(total, 2),
        "per_class_file_refs": dict(per_class_paths),
        "per_class_tokens": {k: round(v, 2) for k, v in per_class_tokens.items()},
        "per_class_token_share": {
            k: round(v / total, 4) for k, v in sorted(per_class_tokens.items(), key=lambda kv: -kv[1])
        } if total else {},
        "top_paths": path_counts.most_common(10),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    for name, path in ARMS.items():
        if not path.exists():
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 1

    tasks = load_tasks()
    rows = {name: json.loads(path.read_text(encoding="utf-8-sig"))["rows"]
            for name, path in ARMS.items()}

    report = {
        "schema": "verseshell.read-usage-audit/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "inputs": [str(p.relative_to(ROOT)) for p in ARMS.values()],
            "classes": {
                "referenced_in_run": "path edited, or named in an exec command, in the same run",
                "task_subject": "path named in the task prompt or in a success predicate",
                "task_file": f"the fixture's own {TASK_FILE}, whose text the system prompt already "
                             "carries as the task hint",
                "unreferenced": "none of the above",
            },
            "apportionment": "a batched call's tokens are split evenly across the paths it asked for; "
                             "that is an apportionment, not a per-file measurement",
            "raw_shell": "classified the same way from the file references in `type`/`cat` commands",
        },
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "with_read_files": {
            "d_reads": audit_condition(rows["with_read_files"], "verseshell_aci", tasks, D_READ_OPS),
            "a_reads": audit_raw_shell(rows["with_read_files"], tasks),
        },
        "without_read_files": {
            "d_reads": audit_condition(rows["without_read_files"], "verseshell_aci", tasks, D_READ_OPS),
            "a_reads": audit_raw_shell(rows["without_read_files"], tasks),
        },
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    for arm, payload in (("with_read_files", report["with_read_files"]),
                         ("without_read_files", report["without_read_files"])):
        d = payload["d_reads"]
        print(f"[{arm}] D reads: {d['calls']} calls, {d['paths']} paths, {d['tokens']} tok")
        for klass in CLASSES:
            share = d["per_class_token_share"].get(klass, 0.0)
            print(f"    {klass:<18} paths={d['per_class_paths'].get(klass, 0):<4} "
                  f"tok={d['per_class_tokens'].get(klass, 0):>8}  {share * 100:5.1f}%")
        a = payload["a_reads"]
        print("    top D paths: " + ", ".join(f"{k}×{v}" for k, v in d["top_paths"][:8]))
        print(f"    A file refs: {a['file_refs']} refs, {a['tokens']} tok")
        for klass, share in a["per_class_token_share"].items():
            print(f"      {klass:<18} refs={a['per_class_file_refs'].get(klass, 0):<4} "
                  f"tok={a['per_class_tokens'].get(klass, 0):>8}  {share * 100:5.1f}%")
        print("    top A paths: " + ", ".join(f"{k}×{v}" for k, v in a["top_paths"][:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
