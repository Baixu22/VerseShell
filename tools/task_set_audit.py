#!/usr/bin/env python3
"""C24: every GOLDEN-bearing task must be unsolved pristine and solved by GOLDEN.

A success predicate that matches the GOLDEN patch's text looks perfect when it is
checked against that patch, and rejects every other correct answer. That is exactly
how two tasks were scored wrong:

  * `ts_fix_type_error` — `file_contains "return a + b"` (rejected 6 of 6 stored
    runs that had really fixed the type error);
  * `python_noisy_install_summary` — `file_contains "packages"` (rejected 6 of 6
    runs whose one-line summary said "1 package").

So this audit pins the invariant that actually matters, using the *same* evaluator
the live runner uses (`live_agent_loop.check_success`), for every task that ships a
GOLDEN patch:

  * **pristine** fixture -> the declared predicate must FAIL (not pre-solved);
  * **GOLDEN** patch     -> it must PASS (solvable);
  * **registered equivalent variant** -> it must PASS (the predicate scores what the
    prompt asked for, not one fixed wording).

It also compares inferred single-file candidates under the legacy and declared
predicates. A candidate over a pristine fixture is not the original final workspace,
so this sensitivity analysis cannot independently re-certify a stored live score.

Usage:
    python tools/task_set_audit.py --out eval/task_set_audit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
TASKS = BENCH / "tasks"
FIXTURES = BENCH / "fixtures"
RESULTS = BENCH / "results"

sys.path.insert(0, str(BENCH / "runners"))
sys.path.insert(0, str(ROOT / "tools"))
from grading_contract import freeze_fixture_verifiers, guarded_success
from fixture_deps import materialize_deps  # noqa: E402
from live_agent_loop import check_success  # noqa: E402
from trajectory_replay import reconstruct  # noqa: E402
from task_sets import load_tasks as load_versioned_tasks  # noqa: E402

# A correct answer written differently from GOLDEN. If the declared predicate
# rejects one of these, it is scoring wording rather than behaviour.
EQUIVALENT_VARIANTS = {
    "windows_batch_capture_diag": {
        "path": "ERR.txt",
        "content": "src/main.rs:12  \r\n",
        "why": "cmd echo redirection adds trailing whitespace to the correct location",
    },
    "ts_fix_type_error": {
        "path": "src/index.ts",
        "content": ("export function add(a: number, b: number): number {\n"
                    "  const total: number = a + b;\n"
                    "  return total;\n}\n"),
        "why": "same behaviour as GOLDEN, renamed binding",
    },
    "python_noisy_install_summary": {
        "path": "SUMMARY.txt",
        "content": "Installed 1 dependency from requirements.txt: six==1.16.0 "
                   "(one line, no install log).\n",
        "why": "same one-line summary, different wording from GOLDEN",
    },
}

# Predicates these tasks shipped before they were fixed. Kept so the audit can
# re-score the stored runs under both and show what the change did.
LEGACY_PREDICATES = {
    "ts_fix_type_error": {
        "type": "all",
        "of": [
            {"type": "file_contains", "path": "src/index.ts", "contains": "return a + b"},
            {"type": "file_not_contains", "path": "src/index.ts",
             "contains": "const x: string"},
        ],
    },
    "python_noisy_install_summary": {
        "type": "file_contains", "path": "SUMMARY.txt", "contains": "packages",
    },
}

# Where the artifact each run produced lives inside the fixture.
REPLAY_TARGETS = {
    "ts_fix_type_error": "src/index.ts",
    "python_noisy_install_summary": "SUMMARY.txt",
}

EVIDENCE_GLOBS = [
    "bench/aci/tasks/*.json",
    "bench/aci/task_sets/*.json",
    "bench/aci/runners/task_sets.py",
    "bench/aci/fixtures/**/*",
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/runners/managed_launch.py",
    "bench/aci/runners/semantic_checks.py",
    "bench/aci/runners/grading_contract.py",
    "bench/aci/runners/fixture_deps.py",
    "bench/aci/results/latest_live.json",
    "tools/task_set_audit.py",
    "tools/trajectory_replay.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for pat in globs for p in ROOT.glob(pat)
                       if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def make_workspace(fixture: Path, workdir: Path, *, golden: bool = False,
                   files: dict[str, str] | None = None) -> Path:
    """Pristine fixture (+ optional GOLDEN patch / extra files) as a workspace."""
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    for item in fixture.iterdir():
        if item.name in ("GOLDEN", "deps"):
            continue
        dest = workdir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    materialize_deps(fixture, workdir)
    if golden:
        golden_dir = fixture / "GOLDEN"
        for item in golden_dir.rglob("*"):
            if item.is_dir():
                continue
            dest = workdir / item.relative_to(golden_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
    for rel, body in (files or {}).items():
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8", newline="\n")
    return workdir


def verdict(pred: dict, fixture: Path, workdir: Path, **kw) -> dict:
    """Evaluate a predicate exactly the way the live runner does."""
    frozen = freeze_fixture_verifiers(pred, fixture)
    workspace = make_workspace(fixture, workdir, **kw)
    ok, reason = guarded_success(pred, workspace, frozen, check_success)
    return {"pass": ok, "ran": ok is not None, "reason": reason}


def fixture_consistency(tasks: dict[str, dict], work: Path) -> dict:
    out: dict[str, dict] = {}
    for task_id, task in tasks.items():
        fixture = FIXTURES / task["workspace_fixture"]
        if not (fixture / "GOLDEN").is_dir():
            out[task_id] = {'task': task_id, 'predicate': task['success'],
                            'pristine': {'pass': None}, 'golden': {'pass': None},
                            'pass': False, 'reason': 'missing required GOLDEN fixture'}
            continue
        pred = task["success"]
        entry: dict = {
            "task": task_id,
            "task_version": task.get("version"),
            "predicate": pred,
            "protected_verifiers": freeze_fixture_verifiers(pred, fixture),
            "pristine": verdict(pred, fixture, work / f"{task_id}-pristine"),
            "golden": verdict(pred, fixture, work / f"{task_id}-golden", golden=True),
        }
        variant = EQUIVALENT_VARIANTS.get(task_id)
        if variant:
            entry["equivalent_variant"] = {
                "why": variant["why"],
                "path": variant["path"],
                "content": variant["content"],
                "verdict": verdict(pred, fixture, work / f"{task_id}-variant",
                                   files={variant["path"]: variant["content"]}),
            }
        entry["pass"] = (
            entry["pristine"]["pass"] is False
            and entry["golden"]["pass"] is True
            and (variant is None
                 or entry["equivalent_variant"]["verdict"]["pass"] is True)
        )
        out[task_id] = entry
    return out


def predicate_changes(tasks: dict[str, dict], rows: list[dict], work: Path) -> dict:
    out: dict[str, dict] = {}
    for task_id, legacy in LEGACY_PREDICATES.items():
        task = tasks.get(task_id)
        if task is None:
            continue
        fixture = FIXTURES / task["workspace_fixture"]
        target = REPLAY_TARGETS[task_id]
        pristine = fixture / target
        pristine_body = pristine.read_text(encoding="utf-8") if pristine.exists() else ""
        runs = []
        for row in rows:
            if row["task_id"] != task_id:
                continue
            body, how = reconstruct(row["condition"], pristine_body,
                                    row.get("trajectory", []), target)
            entry = {
                "condition": row["condition"],
                "seed": row.get("seed"),
                "recorded_success": row.get("success"),
                "reconstructed": body is not None,
                "reconstruction_scope": "single-file candidate, not complete final workspace",
                "independent_live_rescore": False,
                "how": how,
            }
            if body is not None:
                files = {target: body}
                entry["legacy"] = verdict(legacy, fixture,
                                          work / f"{task_id}-{row['condition']}-{row['seed']}-legacy",
                                          files=files)
                entry["declared"] = verdict(task["success"], fixture,
                                            work / f"{task_id}-{row['condition']}-{row['seed']}-declared",
                                            files=files)
            runs.append(entry)
        out[task_id] = {
            "legacy_predicate": legacy,
            "declared_predicate": task["success"],
            "runs_scored": len(runs),
            "runs_reconstructed": sum(1 for r in runs if r["reconstructed"]),
            "independent_live_rescore": False,
            "note": "predicate sensitivity on candidate text over a pristine fixture; not full live re-scoring; "
                    "legacy runs_scored counts stored rows inspected, runs_reconstructed counts inferred candidates",
            "legacy_pass": sum(1 for r in runs if r.get("legacy", {}).get("pass")),
            "declared_pass": sum(1 for r in runs if r.get("declared", {}).get("pass")),
            "runs": runs,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--task-set", type=Path, default=BENCH / "task_sets/3.1.0.json")
    ap.add_argument("--with-arm", type=Path, default=RESULTS / "latest_live.json")
    args = ap.parse_args(argv)

    manifest, tasks = load_versioned_tasks(TASKS, args.task_set)
    rows = json.loads(args.with_arm.read_text(encoding="utf-8-sig"))["rows"]
    work = Path(tempfile.mkdtemp(prefix="task-set-audit-"))
    try:
        consistency = fixture_consistency(tasks, work)
        changes = predicate_changes(tasks, rows, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    report = {
        "schema": "verseshell.task-set-audit/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_set_version": manifest.get("task_set_version"),
        "method": {
            "inputs": ["bench/aci/tasks/manifest.json", str(args.task_set), str(args.with_arm)],
            "evaluator": "live_agent_loop.check_success — the same function the live run uses",
            "fixture_consistency": "pristine must fail, GOLDEN must pass, a registered "
                                   "equivalent variant must pass",
            "predicate_changes": "score inferred single-file candidates over pristine fixtures; "
                                 "not independent full-workspace live re-scoring",
        },
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
                     "input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in (args.task_set, args.with_arm)}},
        "fixture_consistency": consistency,
        "predicate_changes": changes,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    print(f"task set {report['task_set_version']}: {len(consistency)} GOLDEN-bearing task(s)")
    for task_id, entry in consistency.items():
        variant = entry.get("equivalent_variant")
        variant_note = f"variant={variant['verdict']['pass']}" if variant else "variant=n/a"
        print(f"  [{'PASS' if entry['pass'] else 'FAIL'}] {task_id:<32} "
              f"pristine={entry['pristine']['pass']} golden={entry['golden']['pass']} {variant_note}")
    for task_id, entry in changes.items():
        print(f"  {task_id}: stored runs {entry['runs_scored']} "
              f"(reconstructed {entry['runs_reconstructed']}) | "
              f"legacy pass {entry['legacy_pass']} | declared pass {entry['declared_pass']}")
    return 0 if consistency and all(e["pass"] for e in consistency.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
