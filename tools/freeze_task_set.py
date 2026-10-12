#!/usr/bin/env python3
"""freeze_task_set: promote admitted candidates into the benchmark, then freeze.

Promotion is the step where a generated candidate becomes a task the live runner
sees. It must be:

  * **gated** — only candidates with `admissible: true` from
    `tools/task_admissibility.py` are promoted, and only `kind=capability` ones;
  * **traceable** — each promoted task keeps its provenance (generator, the models
    that wrote the independent variants, plan index, tier);
  * **frozen** — the resulting task set records a fingerprint over the tasks and
    fixtures, plus the exact candidate list. Claim C12 already fails closed on a
    changed fingerprint, so this is what makes "the task set was frozen before
    measurement" checkable rather than asserted;
  * **non-destructive by default** — `--dry-run` prints the plan and changes
    nothing.

The task set version is bumped, because a changed predicate or task set makes the
previous live numbers incomparable (C13 / C21 / C24 all record this).

Usage:
    python tools/freeze_task_set.py --dry-run
    python tools/freeze_task_set.py --version 2.0.0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench" / "aci"
CANDIDATES = BENCH / "candidates"
TASKS = BENCH / "tasks"
FIXTURES = BENCH / "fixtures"
MANIFEST = TASKS / "manifest.json"


def fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def fingerprint_globs(globs: list[str]) -> str:
    """Fingerprint exactly the way claim_gate's C12 freshness check recomputes it.

    The record's `evidence.fingerprint` must be produced from the SAME globs AND the
    same traversal order that C12 will use, otherwise the artifact reads as stale the
    moment it is written. claim_gate collects the paths from every glob and then sorts
    them TOGETHER; sorting each glob's matches separately produces a different digest
    for the same file set. Hashing a hand-built file list instead made the record
    permanently stale for the same reason.
    """
    digest = hashlib.sha256()
    paths = sorted(
        p for pat in globs for p in ROOT.glob(pat)
        if p.is_file() and "__pycache__" not in p.parts
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def load_admitted() -> dict[str, dict]:
    adm = json.loads((ROOT / "eval" / "task_admissibility.json").read_text(encoding="utf-8"))
    return {c["candidate"]: c for c in adm.get("candidates", []) if c.get("admissible")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=None, help="new task_set_version (required to apply)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--record-only", action="store_true",
                    help="skip promotion and just rewrite the freeze record for the current "
                         "task set (used to attach an evidence block to an existing freeze)")
    ap.add_argument("--keep-existing", action="store_true", default=True,
                    help="keep the existing hand-built tasks (default true)")
    args = ap.parse_args()

    admitted = load_admitted()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    existing = list(manifest.get("tasks", []))

    promote: list[tuple[str, Path, dict]] = []
    skipped: list[tuple[str, str]] = []
    ineligible: list[tuple[str, str]] = []
    for cdir in sorted(p for p in CANDIDATES.iterdir() if p.is_dir()):
        tp = cdir / "task.json"
        if not tp.exists():
            continue
        task = json.loads(tp.read_text(encoding="utf-8-sig"))
        name = cdir.name
        if name not in admitted:
            reason = "not admissible (gate rejected it or it has no verdict)"
            skipped.append((name, reason))
            continue
        if task.get("kind") != "capability":
            ineligible.append((name, f"kind={task.get('kind')!r} may not feed capability claims"))
            continue
        tid = task.get("id") or name
        if tid in existing:
            skipped.append((name, f"task id {tid!r} already in the task set"))
            continue
        promote.append((tid, cdir, task))

    print(f"admitted candidates      : {len(admitted)}")
    print(f"to promote (capability)  : {len(promote)}")
    print(f"existing task set size   : {len(existing)}")
    print(f"-> new task set size     : {len(existing) + len(promote)}")
    if ineligible:
        print("\nineligible (kept out of the capability set):")
        for name, why in ineligible:
            print(f"  {name}: {why}")
    if skipped:
        print("\nskipped:")
        for name, why in skipped:
            print(f"  {name}: {why}")

    if not promote and not args.record_only:
        print("\nnothing to promote; run tools/run_task_plan.py first", file=sys.stderr)
        return 2 if not args.dry_run else 0

    if promote:
        print("\nto promote:")
        for tid, cdir, task in promote:
            prov = task.get("provenance") or {}
            nvar = len(list((cdir / "variants").glob("*"))) if (cdir / "variants").is_dir() else 0
            print(f"  {tid:<40} tier={prov.get('tier')} plan#{prov.get('plan_index')} "
                  f"variants={nvar} lang={task.get('lang')}")
    else:
        print("\n[record-only] no promotion; rewriting the freeze record for the current task set")

    if args.dry_run:
        print("\n[dry-run] nothing written")
        return 0
    if not args.version:
        print("\n--version is required to apply (a changed task set invalidates the "
              "previous live numbers, so the version must be bumped deliberately)",
              file=sys.stderr)
        return 2

    # Apply: copy fixtures, write task JSONs, record provenance, update manifest.
    for tid, cdir, task in promote:
        if args.record_only:
            break
        dest_fixture = FIXTURES / tid
        if dest_fixture.exists():
            shutil.rmtree(dest_fixture)
        shutil.copytree(cdir / "fixture", dest_fixture,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        # The live runner materialises `task["workspace_fixture"]` from
        # bench/aci/fixtures/<name>, and task_set_audit (C24) applies
        # fixtures/<name>/GOLDEN as the reference patch — so both must exist here,
        # not just in the candidate directory.
        golden_src = None
        for name in ("GOLDEN", "golden"):
            if (cdir / name).is_dir():
                golden_src = cdir / name
                break
        if golden_src is not None:
            shutil.copytree(golden_src, dest_fixture / "GOLDEN",
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        promoted = dict(task)
        promoted["workspace_fixture"] = tid
        promoted["promoted_from"] = f"bench/aci/candidates/{cdir.name}"
        promoted["promoted_at"] = datetime.now(timezone.utc).isoformat()
        # `fixture` (the inline file map) is how the candidate was generated; the
        # shipped task uses the on-disk fixture directory instead.
        promoted.pop("fixture", None)
        (TASKS / f"{tid}.json").write_text(
            json.dumps(promoted, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")

    new_ids = [tid for tid, _, _ in promote]
    if new_ids:
        manifest["task_set_version"] = args.version
        manifest["tasks"] = existing + new_ids
        manifest["frozen_at"] = datetime.now(timezone.utc).isoformat()
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8", newline="\n")
    else:
        # record-only: do NOT rewrite the manifest. `bench/aci/tasks/*.json` is inside
        # the fingerprinted surface of the live artifacts, so bumping a bookkeeping
        # `frozen_at` here would mark `latest_live.json` stale without the task set
        # having changed at all. That is a self-inflicted false positive.
        print("record-only: manifest left untouched (rewriting it would invalidate "
              "fingerprints without any task-set change)")

    # The freeze record: what exactly was frozen, and its content fingerprint.
    #
    # The promoted/kept-existing split describes the FINAL task set, not just the tasks
    # this run happened to add. `new_ids` is only "what this invocation promoted": it is
    # empty on a `--record-only` rerun, and on a later batch it shrinks to that batch
    # while every earlier generated task silently falls into `kept_existing`. That made
    # the frozen record unable to answer "which 10 are hand-written and which are
    # generated" — the exact question it exists to answer (TF-0104). Classify instead by
    # each shipped task's own metadata, which cannot drift across runs: a generated task
    # is `kind=capability` and carries `provenance` / `promoted_from`; a hand-written one
    # carries none of them.
    def _is_generated(tid: str) -> bool:
        path = TASKS / f"{tid}.json"
        if not path.exists():
            return False
        t = json.loads(path.read_text(encoding="utf-8-sig"))
        return (t.get("kind") == "capability" or bool(t.get("provenance"))
                or bool(t.get("promoted_from")))

    promoted_ids = [t for t in manifest["tasks"] if _is_generated(t)]
    kept_existing_ids = [t for t in manifest["tasks"] if not _is_generated(t)]

    # ── the holdout, declared at freeze time (TF-0105 / TF-0114, pre-registered in
    # docs/task-generation-protocol.md §4.6) ──
    # The 25-task set that existed before this batch CANNOT be a holdout: C30 and the
    # D1-D7 defects were found and fixed on exactly those tasks, so a result on them is
    # a result on the tuning set. The tasks promoted in THIS batch are the only ones
    # generated after those fixes, so they are the holdout by construction. The rule is
    # recorded here (before any round-14 live result exists) rather than picked later.
    # A `--record-only` rerun promotes nothing, so it must PRESERVE the declaration
    # instead of resetting it to empty.
    _prev_holdout = None
    _freeze_out = ROOT / "eval" / "task_set_freeze.json"
    if _freeze_out.exists():
        try:
            _prev_holdout = (json.loads(_freeze_out.read_text(encoding="utf-8"))
                             or {}).get("holdout")
        except json.JSONDecodeError:
            _prev_holdout = None
    _holdout_rule = ("tasks promoted in this batch: generated after C30 and D1-D7 were fixed "
                     "on the previous 25-task set, so no live result on them has ever been "
                     "seen or used for tuning")
    holdout = (_prev_holdout if not new_ids and _prev_holdout
               else {"rule": _holdout_rule, "tasks": list(new_ids), "n": len(new_ids),
                     "declared_at": datetime.now(timezone.utc).isoformat(),
                     "preregistered_in": "docs/task-generation-protocol.md §4.6"})

    task_paths = [TASKS / f"{t}.json" for t in manifest["tasks"] if (TASKS / f"{t}.json").exists()]
    fixture_paths = [p for p in FIXTURES.rglob("*") if p.is_file()]
    globs = ["bench/aci/tasks/*.json", "bench/aci/fixtures/**/*", "tools/freeze_task_set.py"]
    freeze = {
        "schema": "verseshell.task_set_freeze/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "task_set_version": args.version,
        "tasks": manifest["tasks"],
        "n_tasks": len(manifest["tasks"]),
        "promoted": promoted_ids,
        "kept_existing": kept_existing_ids,
        "n_promoted": len(promoted_ids),
        "n_kept_existing": len(kept_existing_ids),
        "promoted_in_this_run": new_ids,
        "holdout": holdout,
        "fingerprint": fingerprint(task_paths + fixture_paths),
        "fingerprint_covers": [t.as_posix() for t in task_paths] + ["bench/aci/fixtures/**/*"],
        # Same shape as every other evidence artifact, so C12 can freshness-check the
        # freeze record too: if the frozen task set changes afterwards, the record goes
        # stale instead of silently describing a task set that no longer exists.
        "evidence": {"globs": globs, "fingerprint": fingerprint_globs(globs)},
        "per_tier": {},
    }
    # per_tier used to fold every task without a provenance `tier` into the bucket named
    # "existing", which merged 10 generated-but-untagged tasks with the 10 hand-written
    # ones and made the tier composition unreadable (the 10 untagged generated tasks were
    # exactly the ones the plan had assigned a tier to). Bucket honestly instead:
    # `handwritten` for the hand-built tasks, the declared tier for tagged generated
    # tasks, and `untiered_generated` for the generated tasks whose provenance is missing
    # the field — a visible metadata gap rather than a silent merge.
    for tid in manifest["tasks"]:
        p = TASKS / f"{tid}.json"
        if not p.exists():
            continue
        if not _is_generated(tid):
            tier = "handwritten"
        else:
            prov = (json.loads(p.read_text(encoding="utf-8-sig")).get("provenance") or {})
            tier = prov.get("tier") or "untiered_generated"
        freeze["per_tier"][tier] = freeze["per_tier"].get(tier, 0) + 1
    out = ROOT / "eval" / "task_set_freeze.json"
    out.write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")

    print(f"\npromoted {len(new_ids)} task(s) this run; task set is now {len(manifest['tasks'])} "
          f"tasks at version {args.version}")
    print(f"  generated (promoted) : {len(promoted_ids)}")
    print(f"  hand-written (kept)  : {len(kept_existing_ids)}")
    print(f"  holdout declared     : {holdout.get('n')} task(s)")
    print(f"  per tier: {freeze['per_tier']}")
    print(f"  freeze record: {out}")
    print(f"  fingerprint  : {freeze['fingerprint'][:16]}…")
    print("\nNEXT: the task set is frozen. Do not add or remove tasks after seeing "
          "live token results (docs/task-generation-protocol.md §5).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
