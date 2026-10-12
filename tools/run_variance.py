#!/usr/bin/env python3
"""run_variance: descriptive between-seed spread, not an independent-run variance estimate.

Why this exists
---------------
The published confidence intervals resample TASKS. That captures "which tasks did we
happen to draw" and nothing else. But this endpoint accepts a `seed` without reproducing
it (`docs/claims-and-evidence.md` C13 boundary 3), and the audit measured a run-to-run
drift in the D/A' observation-token ratio of 0.2577 between rounds 12 and 13 — 10.4x the
0.0212 margin the claim rested on. A task-only interval does not quantify independent-collection uncertainty;
its coverage cannot be diagnosed from those observations alone.

Round 14 has one collection at each of three DIFFERENT seeds. Their spread mixes
seed effects and collection noise; it does not identify the independent run-to-run
component at fixed seeds. These statistics are descriptive diagnostics only.

A sample SD with two degrees of freedom is noisy, not a mathematical lower bound.
The SE/CI-half-width ratio does not prove undercoverage or quantify a missing
variance component. Use repeated_run_uncertainty.py for a separately collected,
complete repeated-run study; do not relabel the three seed files as repetitions.

Usage:
    python tools/run_variance.py --out eval/run_variance.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from live_uncertainty import rows_fingerprint

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SEEDS = (42, 43, 44)
PUBLISHED = ROOT / "eval/live_uncertainty.json"
# A live round writes its per-seed shards under its own tag
# (`bench/aci/results/<tag>/`). This tool used to hardcode round 14's tag
# (`bench/aci/results/tf0114`), so after a new round it silently compared the NEW
# published interval against the OLD round's per-seed spread. Directory timestamps
# cannot establish collection identity. Match the exact source rows fingerprint
# published by live_uncertainty, including seed and source_run provenance.


def evidence_globs(run_dir: Path, published: Path) -> list[str]:
    """Fingerprint inputs for the chosen shard directory."""
    return [
        f"{run_dir.relative_to(ROOT).as_posix()}/with_seed*.json",
        published.relative_to(ROOT).as_posix(),
        "tools/live_uncertainty.py",
        "tools/run_variance.py",
    ]


def discover_run_dir(seeds: list[int], arm: dict) -> tuple[Path | None, str]:
    """Select only a complete grid whose rows match the published collection."""
    for candidate in sorted((ROOT / "bench/aci/results").glob("*")):
        if not candidate.is_dir():
            continue
        files = [candidate / f"with_seed{s}.json" for s in seeds]
        if not all(f.exists() for f in files):
            continue
        try:
            matched_rows(candidate, seeds, arm)
        except (OSError, ValueError, TypeError, KeyError):
            continue
        return candidate, "exact source rows fingerprint match to published interval"
    return None, "no complete seed grid matches the published source rows fingerprint"



def matched_rows(run_dir: Path, seeds: list[int], arm: dict) -> dict[int, list[dict]]:
    """Apply merger provenance defaults, then check identity before any statistics."""
    by_seed: dict[int, list[dict]] = {}
    keys: set[tuple] = set()
    for seed in seeds:
        path = run_dir / f"with_seed{seed}.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        cfg = payload.get("live_config") or {}
        rows = payload.get("rows")
        if cfg.get("seed") != seed or not isinstance(rows, list) or not rows:
            raise ValueError(f"{path.name}: missing rows or mismatched seed")
        by_seed[seed] = []
        for value in rows:
            row = dict(value)
            row.setdefault("source_run", path.name)
            if row.get("seed") is None:
                row["seed"] = cfg["seed"]
            if row["seed"] != seed:
                raise ValueError(f"{path.name}: row seed mismatch")
            key = tuple(row.get(k) for k in ("model", "task_id", "condition", "seed", "run_index"))
            if key in keys:
                raise ValueError(f"{path.name}: duplicate cell {key}")
            keys.add(key)
            by_seed[seed].append(row)
    rows = [r for group in by_seed.values() for r in group]
    if len(rows) != arm.get("n_rows") or rows_fingerprint(rows) != arm["source_rows_fingerprint"]:
        raise ValueError("per-seed rows do not match the published interval's source collection")
    return by_seed


def paired(rows: list[dict], baseline: str, treatment: str, value):
    def key(r):
        return (r.get("task_id"), r.get("run_index"))
    base = {key(r): r for r in rows if r.get("condition") == baseline}
    treat = {key(r): r for r in rows if r.get("condition") == treatment}
    shared = sorted(set(base) & set(treat), key=lambda k: (str(k[0]), str(k[1])))
    return [(str(k[0]), float(value(base[k])), float(value(treat[k]))) for k in shared]


def ratio(triples) -> float | None:
    den = sum(a for _, a, _ in triples)
    num = sum(d for _, _, d in triples)
    return (num / den) if den else None


def success_delta(rows: list[dict]) -> float | None:
    triples = paired(rows, "raw_shell", "verseshell_aci",
                     lambda r: 1.0 if r.get("success") else 0.0)
    if not triples:
        return None
    return sum(d - a for _, a, d in triples) / len(triples)


def sd(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, default=None,
                    help="directory holding with_seed<N>.json shards; defaults to the "
                         "complete grid matching the published source rows fingerprint")
    ap.add_argument("--seeds", default=",".join(str(s) for s in DEFAULT_SEEDS))
    ap.add_argument("--published", type=Path, default=PUBLISHED)
    ap.add_argument("--out", type=Path, default=ROOT / "eval/run_variance.json")
    args = ap.parse_args(argv)

    try:
        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
        if len(seeds) < 2 or len(set(seeds)) != len(seeds):
            raise ValueError("need at least two distinct seeds, with no duplicates")
        published_path = args.published.resolve()
        published = json.loads(published_path.read_text(encoding="utf-8-sig"))
        arms = [a for a in published.get("arms", []) if a.get("artifact") == "with_read_files"]
        if len(arms) != 1 or not arms[0].get("source_rows_fingerprint"):
            raise ValueError("published report lacks a unique with-arm source rows fingerprint; "
                             "regenerate it with tools/live_uncertainty.py")
        arm = arms[0]
        if sorted(seeds) != sorted(arm.get("seeds") or []):
            raise ValueError("requested seeds must exactly match the published interval")
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.run_dir is not None:
        run_dir, selection = args.run_dir, "explicit --run-dir"
    else:
        discovered, why = discover_run_dir(seeds, arm)
        if discovered is None:
            # An explicit path must pass the same check; it cannot bypass identity.
            print(f"ERROR: {why}; supply matching --run-dir and --published inputs",
                  file=sys.stderr)
            return 2
        run_dir, selection = discovered, why
    run_dir = (run_dir if run_dir.is_absolute() else ROOT / run_dir).resolve()
    try:
        globs = evidence_globs(run_dir, published_path)
        by_seed = matched_rows(run_dir, seeds, arm)
        inputs = [published_path, *(run_dir / f"with_seed{s}.json" for s in seeds)]
        if args.out.resolve() in inputs:
            raise ValueError("--out must not overwrite an input")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"run dir: {run_dir.relative_to(ROOT).as_posix()}  ({selection})")
    per_seed: dict[str, list[float]] = {"observation_token_ratio": [],
                                        "tool_call_ratio": [],
                                        "success_delta": []}
    used: list[int] = []
    for seed in seeds:
        path = run_dir / f"with_seed{seed}.json"
        rows = by_seed[seed]
        obs = paired(rows, "raw_shell", "verseshell_aci", lambda r: r.get("observation_tokens") or 0)
        tools = paired(rows, "raw_shell", "verseshell_aci", lambda r: r.get("tool_calls") or 0)
        r_obs, r_tool, delta = ratio(obs), ratio(tools), success_delta(rows)
        if r_obs is None or r_tool is None or delta is None:
            print(f"ERROR: {path.name} produced no usable pairs", file=sys.stderr)
            return 2
        per_seed["observation_token_ratio"].append(r_obs)
        per_seed["tool_call_ratio"].append(r_tool)
        per_seed["success_delta"].append(delta)
        used.append(seed)

    if len(used) < 2:
        print("ERROR: need at least 2 usable seeds for a descriptive between-seed comparison",
              file=sys.stderr)
        return 2

    pub_ratio = (arm.get("ratio_bootstrap") or {}).get("observation_token_ratio") or {}
    pub_delta = ((arm.get("paired") or {}).get("success_rate") or {}).get("paired_ci95")

    findings: dict = {}
    for metric, values in per_seed.items():
        m = sum(values) / len(values)
        s = sd(values)
        se = s / math.sqrt(len(values))
        entry = {
            "per_seed": [round(v, 4) for v in values],
            "seeds": used,
            "mean": round(m, 4),
            "between_seed_sd": round(s, 4),
            "between_seed_se_of_mean": round(se, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "spread": round(max(values) - min(values), 4),
        }
        if metric == "observation_token_ratio" and pub_ratio.get("bootstrap_ci95"):
            lo, hi = pub_ratio["bootstrap_ci95"]
            half = (hi - lo) / 2.0
            entry["published_task_clustered_ci95"] = [lo, hi]
            entry["published_half_width"] = round(half, 4)
            entry["run_to_run_se_over_published_half_width"] = round(se / half, 4) if half else None
            # Does the between-seed spread alone straddle 1.0?
            entry["per_seed_straddles_1_0"] = bool(min(values) < 1.0 < max(values))
        if metric == "success_delta" and pub_delta:
            lo, hi = pub_delta
            half = (hi - lo) / 2.0
            entry["published_task_clustered_ci95"] = [lo, hi]
            entry["published_half_width"] = round(half, 4)
            entry["run_to_run_se_over_published_half_width"] = round(se / half, 4) if half else None
            entry["per_seed_straddles_0_0"] = bool(min(values) < 0.0 < max(values))
        findings[metric] = entry

    worst = max((e.get("run_to_run_se_over_published_half_width") or 0.0)
                for e in findings.values())
    payload = {
        "schema": "verseshell.run_variance/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/run_variance.py",
        "question": "what descriptive spread is present between different seeds?",
        "method": {
            "design": f"one collection per distinct seed: {used}",
            "estimator": "sample between-seed SD and SD/sqrt(n), descriptive only",
            "comparison": "descriptive SE divided by a task-clustered interval half-width; not a variance decomposition",
            "limitation": f"{len(used)-1} degrees of freedom; seed and collection effects are confounded. Not a lower bound or evidence of CI undercoverage.",
            "includes_independent_run_variance": False,
            "legacy_field_names": "run_to_run_se_over_published_half_width is retained for compatibility; interpret as a descriptive between-seed ratio only",
        },
        "runs_used": used,
        "run_dir": run_dir.relative_to(ROOT).as_posix(),
        "run_dir_selection": selection,
        "round_pinning": {
            "verified": True,
            "method": "exact merged source rows fingerprint, ignoring only derived row_class",
            "source_rows_fingerprint": arm["source_rows_fingerprint"],
            "published": published_path.relative_to(ROOT).as_posix(),
            "n_rows": arm["n_rows"],
        },
        "findings": findings,
        "max_run_to_run_se_over_published_half_width": round(worst, 4),
        "verdict": "between-seed variation observed; independent repeated-run variance and CI coverage remain unidentified",
        "evidence": {"globs": globs, "fingerprint": None},
    }

    digest = hashlib.sha256()
    for pat in globs:
        for p in sorted(ROOT.glob(pat)):
            if p.is_file() and "__pycache__" not in p.parts:
                digest.update(p.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(p.read_bytes()).digest())
    payload["evidence"]["fingerprint"] = digest.hexdigest()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    for metric, e in findings.items():
        print(f"  {metric}: per-seed={e['per_seed']} mean={e['mean']} "
              f"between-seed sd={e['between_seed_sd']} se={e['between_seed_se_of_mean']}")
        if e.get("published_half_width") is not None:
            print(f"    published half-width={e['published_half_width']} "
                  f"-> descriptive between-seed SE is {e['run_to_run_se_over_published_half_width']}x of it")
    print(f"  VERDICT: {payload['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
