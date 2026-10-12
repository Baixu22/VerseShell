#!/usr/bin/env python3
"""run_task_plan: converge a pre-registered task plan through generation AND admission.

Generating is not the goal; having an *admissible* task for every pre-registered
plan slot is. A single pass does not get there:

  * the endpoint intermittently 502s and the served reasoning models sometimes
    emit unparseable JSON, so some slots fail to generate;
  * some generated candidates are rejected by `tools/task_admissibility.py`
    (A2 GOLDEN does not pass, A3 fewer than two independent correct answers,
    A4a the verifier can be neutered, A8 a `tier=large` task did not actually
    produce a large observation), so their slot must be regenerated.

So this drives the loop: generate -> gate -> regenerate whatever is still missing,
up to a round cap. `task_generate.py` treats a gate-rejected candidate as NOT done,
which is what makes the loop able to replace it.

Usage:
    python tools/run_task_plan.py --plan <pre-registered-plan.json> --model <author-model> --rounds 12
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from task_generate_v2 import generation_policy  # noqa: E402


def admitted_indices(plan: dict, candidates_dir: Path, adm_path: Path,
                     policy: dict | None = None) -> tuple[set[int], dict]:
    """Plan indices that have an ADMITTED candidate, plus a status breakdown.

    Only slots that belong to THIS plan count. The first version collected the
    `plan_index` of every candidate under `bench/aci/candidates/` and never intersected
    it with the plan, so a plan that covers a subset of the slots was scored against
    unrelated candidates: running the 15-slot remainder plan printed
    `admitted 6/15 ... {'admissible': 6, ..., 'absent': -9}` because the five
    FULL_PLAN slots (1, 12, 13, 14, 24) were counted too, and `absent` went negative.
    With a small filtered plan the same arithmetic can reach `admitted >= target` and
    make the driver stop while slots are still empty — a silent false "converged".
    """
    plan_indices = {int(e["index"]) for e in plan["plan"] if e.get("index") is not None}
    if not adm_path.exists():
        return set(), {"admissible": 0, "rejected": 0, "absent": len(plan_indices)}
    adm = json.loads(adm_path.read_text(encoding="utf-8"))
    index_of: dict[str, int] = {}
    for d in sorted(p for p in candidates_dir.iterdir() if p.is_dir()):
        tp = d / "task.json"
        if not tp.exists():
            continue
        try:
            prov = json.loads(tp.read_text(encoding="utf-8-sig")).get("provenance") or {}
        except json.JSONDecodeError:
            continue
        if policy is not None and prov.get("generation_policy") != policy:
            continue
        if prov.get("plan_index") is not None:
            index_of[d.name] = int(prov["plan_index"])

    # A slot is COVERED if ANY of its candidates was admitted. A slot can hold both an
    # admitted candidate and older rejected ones (a rejected candidate does not free its
    # plan index — it is replaced by regenerating the same index), so the two sets must be
    # derived per slot rather than by adding up candidate rows.
    per_slot: dict[int, bool] = {}
    for c in adm.get("candidates", []):
        idx = index_of.get(c.get("candidate"))
        if idx is None or idx not in plan_indices:
            continue
        per_slot[idx] = per_slot.get(idx, False) or bool(c.get("admissible"))
    admitted = {i for i, ok in per_slot.items() if ok}
    rejected = {i for i, ok in per_slot.items() if not ok}
    counts = {"admissible": len(admitted), "rejected": len(rejected),
              "absent": len(plan_indices - admitted - rejected)}
    return admitted, counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "bench" / "aci" / "candidates")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--generator", default="tools/task_generate_v2.py",
                    help="generator to run; v2 decomposes the job into low-reasoning "
                         "steps because the one-shot v1 emitted 0 characters at a full "
                         "16384-token reasoning budget on this endpoint")
    ap.add_argument("--model", required=True, help="explicit pre-registered task author")
    ap.add_argument("--variant-models", required=True)
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    model = args.model
    variants = [m.strip() for m in args.variant_models.split(",") if m.strip()]
    try:
        policy = generation_policy(plan, model, variants)
    except ValueError as exc:
        ap.error(str(exc))
    target = len(plan["plan"])
    indices=[item.get('index') for item in plan['plan']]
    if not target or any(type(i) is not int for i in indices) or len(set(indices))!=target or args.rounds<1:
        ap.error('nonempty unique integer plan indices and positive rounds required')
    audit_dir=args.out.parent/(args.out.name+'-admission-runs')/uuid.uuid4().hex
    audit_dir.mkdir(parents=True,exist_ok=True)

    for rnd in range(1, args.rounds + 1):
        print(f"\n{'#' * 72}\n# ROUND {rnd}/{args.rounds}\n{'#' * 72}", flush=True)

        rc = subprocess.run([sys.executable, args.generator,
                             "--plan", str(args.plan), "--out", str(args.out),
                             "--model", model,
                             "--variant-models", args.variant_models], cwd=ROOT).returncode
        print(f"[{time.strftime('%H:%M:%S')}] generate -> exit {rc}", flush=True)
        if rc != 0:
            return rc

        adm_path=audit_dir/f'round-{rnd}.json'
        rc=subprocess.run([sys.executable, "tools/task_admissibility.py", "--candidates", str(args.out),
                           "--out", str(adm_path)], cwd=ROOT).returncode
        if rc not in (0,1) or not adm_path.is_file():
            print('admission failed without a current report; refusing stale coverage',file=sys.stderr)
            return 2
        admitted, counts = admitted_indices(plan, args.out, adm_path, policy)
        print(f"[{time.strftime('%H:%M:%S')}] admitted {len(admitted)}/{target} "
              f"plan slots  {counts}", flush=True)
        if len(admitted) >= target:
            print(f"\nall {target} plan slots have an admitted candidate after {rnd} round(s)")
            return 0

    admitted, counts = admitted_indices(plan, args.out, adm_path, policy)
    print(f"\nstopped after {args.rounds} rounds with {len(admitted)}/{target} admitted "
          f"plan slots ({counts})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
