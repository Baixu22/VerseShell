#!/usr/bin/env python3
"""claim_gate: machine-checkable claim gate for VerseShell (task-forest TF-0008).

Computes the automated subset of the C1-C7 claim matrix and writes
eval/evidence.json. Exits non-zero when any gated claim is below its threshold.

Gated claims (thresholds mirror docs/claims-and-evidence.md exactly):
  C1  mock bench observation-token ratio D/A <= 0.50
  C2  mock bench tool-call ratio D/A       <= 0.70
  C3  diff-class expected/found completeness >= 0.90
  C4  one-step recovery structural fields   == 1.00
  C6  closed-loop trash/restore acceptance passes
  C7  full cargo test suite passes
  C8  process lifecycle contract tests pass (Windows-only test file)
  C9  compact encoding saves >= 0.40 on a small response envelope (lossless)
  C10 every documented README example runs and every README implementation number matches its source
  C11 cross-shell wall-clock: worst VerseShell/PowerShell median ratio <= 0.50 (stored measurement)
  C12 stored evidence freshness: each artifact's recorded fingerprint still matches the code
  C14 batch-read envelope: compact digest + batch budget hold on a frozen-trajectory replay
C5 (learning cost) has no deterministic metric yet: status-only in evidence.json.
C13 (live A/D) and C15 (where D's extra tokens come from) are registered in
docs/claims-and-evidence.md without a pass threshold: they record measurements, not goals.

Usage:
    python tools/claim_gate.py                 # regenerate metrics + run tests
    python tools/claim_gate.py --skip-tests    # skip cargo test (C6/C7 reported stale)
    python tools/claim_gate.py --metrics eval/metrics.json   # reuse a metrics dump
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

THRESHOLDS = {
    "C1": {"desc": "mock bench observation_tokens ratio D/A", "op": "<=", "value": 0.50},
    "C2": {"desc": "mock bench tool_calls ratio D/A", "op": "<=", "value": 0.70},
    "C3": {"desc": "diff-class expected/found completeness", "op": ">=", "value": 0.90},
    "C4": {"desc": "one-step recovery structural checks", "op": ">=", "value": 1.00},
    "C6": {"desc": "closed-loop trash/restore acceptance", "op": ">=", "value": 1.00},
    "C7": {"desc": "full cargo test suite green", "op": ">=", "value": 1.00},
    "C8": {"desc": "process lifecycle contract tests", "op": ">=", "value": 1.00},
    "C9": {"desc": "compact encoding savings on a small response envelope", "op": ">=", "value": 0.40},
    "C10": {"desc": "README examples run and README numbers match source", "op": ">=", "value": 1.00},
    "C11": {"desc": "cross-shell worst VerseShell/PowerShell median ratio", "op": "<=", "value": 0.50},
    "C12": {"desc": "stored evidence freshness (recorded fingerprint matches the code)", "op": ">=", "value": 1.00},
    "C14": {"desc": "batch-read envelope replay: compact digest saving + bounded batch budget", "op": ">=", "value": 0.15},
}

# Stored measurements the gate relies on. Each must record the content fingerprint
# of the surface it measured, or the gate cannot tell whether the number still
# describes the current code.
#
# `bench/aci/results/latest_live.json` is gated again as of the successful
# re-measurement on `sn-glm-5-3-flash` (3 runs, seeds 42/43/44). Its A/B partner
# `live_ab_without_read_files.json` is deliberately NOT gated: it is a paired
# comparison arm (same code, one tool hidden) that exists to size the effect of
# `file.read_many`, and re-running it is only needed when the comparison itself
# is being redone — C13 records when it was taken.
EVIDENCE_ARTIFACTS = [
    "bench/aci/results/latest.json",
    "bench/aci/results/latest_live.json",
    "eval/jev_obs_report.json",
    "eval/cross_shell.json",
    "eval/tf45_envelope_replay.json",
    "eval/exec_token_breakdown.json",
]


def bench_ratios(bench_path: Path) -> tuple[float, float, int, dict]:
    """Return (token_ratio_D_over_A, tool_call_ratio_D_over_A, n_tasks, meta)."""
    data = json.loads(bench_path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    mode = data.get("mode", "?")
    if mode != "mock":
        raise SystemExit(f"claim_gate expects the mock bench results; got mode={mode!r} in {bench_path}")
    agg: dict[str, dict[str, float]] = {}
    for r in rows:
        cond = r.get("condition")
        if cond not in ("raw_shell", "verseshell_aci"):
            continue
        a = agg.setdefault(cond, {"tokens": 0.0, "calls": 0.0, "n": 0.0})
        a["tokens"] += float(r.get("observation_tokens", 0))
        a["calls"] += float(r.get("tool_calls", 0))
        a["n"] += 1
    if "raw_shell" not in agg or "verseshell_aci" not in agg or agg["raw_shell"]["n"] == 0:
        raise SystemExit(f"bench file lacks paired raw_shell/verseshell_aci rows: {bench_path}")
    tok_ratio = (agg["verseshell_aci"]["tokens"] / agg["verseshell_aci"]["n"]) / (
        agg["raw_shell"]["tokens"] / agg["raw_shell"]["n"]
    )
    call_ratio = (agg["verseshell_aci"]["calls"] / agg["verseshell_aci"]["n"]) / (
        agg["raw_shell"]["calls"] / agg["raw_shell"]["n"]
    )
    meta = {
        "bench_mode": mode,
        "task_set_version": data.get("task_set_version"),
        "seed": data.get("seed"),
        "generated_at": data.get("generated_at"),
        "n_rows_per_condition": int(agg["raw_shell"]["n"]),
    }
    return tok_ratio, call_ratio, int(agg["raw_shell"]["n"]), meta


def recovery_rate(metrics: dict) -> tuple[float, dict]:
    probes = metrics.get("recovery_probes", {})
    stale = probes.get("stale_hash", {})
    amb = probes.get("ambiguous", {})
    checks = {
        "stale_hash.data_actual_hash_present": bool(stale.get("data_actual_hash_present")),
        "stale_hash.data_expected_hash_present": bool(stale.get("data_expected_hash_present")),
        "stale_hash.one_step_retry_ok": bool(stale.get("one_step_retry_from_suggested_next_ok")),
        "ambiguous.matches_structured": bool(amb.get("matches_structured_line_offset_snippet")),
        "ambiguous.widen_retry_ok": bool(amb.get("widen_old_retry_ok")),
    }
    passed = sum(1 for v in checks.values() if v)
    return passed / len(checks), checks


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def evidence_fingerprint(globs: list[str]) -> str:
    """Content hash of a measured surface (same recipe the generators use)."""
    digest = hashlib.sha256()
    paths = sorted(
        p for pat in globs for p in ROOT.glob(pat)
        if p.is_file() and "__pycache__" not in p.parts
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def freshness_entries() -> list[dict]:
    """C12: compare each stored artifact's recorded fingerprint with the code now."""
    entries: list[dict] = []
    for rel in EVIDENCE_ARTIFACTS:
        path = ROOT / rel
        entry: dict = {"artifact": rel}
        if not path.exists():
            entry.update({"status": "missing", "pass": False})
            entries.append(entry)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            entry.update({"status": f"unreadable: {error}", "pass": False})
            entries.append(entry)
            continue
        entry["generated_at"] = data.get("generated_at")
        evidence = data.get("evidence") or {}
        globs = evidence.get("globs")
        recorded = evidence.get("fingerprint")
        if not globs or not recorded:
            entry.update({
                "status": "no fingerprint recorded (regenerate the artifact)",
                "pass": False,
            })
        else:
            current = evidence_fingerprint(globs)
            entry.update({
                "status": "fresh" if current == recorded else "stale",
                "fingerprint_recorded": recorded[:16],
                "fingerprint_current": current[:16],
                "pass": current == recorded,
            })
        entries.append(entry)
    return entries


def compact_ratio_claim(report: dict) -> dict:
    """C9 reads the measured compact-vs-JSON report.

    The gated number is deliberately narrow: the compact encoding must beat JSON
    on a *small response envelope* (where repeated key names dominate) and stay
    lossless on every observation payload. It makes no claim about large or
    nested payloads, where the measurement shows no saving.
    """
    families = {f.get("kind"): f for f in report.get("families", [])}
    response = families.get("response", {}).get("cases", [])
    observation = families.get("observation", {}).get("cases", [])
    small = next((c for c in response if c.get("name") == "response_small_hash"), None)
    if small is None:
        raise SystemExit("compact_ratio report lacks the response_small_hash case")
    roundtrips_ok = bool(observation) and all(c.get("roundtrip_ok") is True for c in observation)
    value = min(float(small.get("byte_savings", 0.0)), float(small.get("token_savings", 0.0)))
    return {
        "value": round(value, 4),
        "pass": value >= THRESHOLDS["C9"]["value"] and roundtrips_ok,
        "detail": {
            "small_response_byte_savings": small.get("byte_savings"),
            "small_response_token_savings": small.get("token_savings"),
            "observation_roundtrips_ok": roundtrips_ok,
            "observation_headline_savings": families.get("observation", {})
            .get("aggregate", {})
            .get("headline_savings"),
            "response_headline_savings": families.get("response", {})
            .get("aggregate", {})
            .get("headline_savings"),
        },
    }


def batch_envelope_claim(report: dict) -> dict:
    """C14 reads the frozen-trajectory replay of the batch-read envelope.

    Two things must hold: the compact digest must actually shrink the
    model-visible observation on calls the model really issued, and the new
    `max_total_lines` budget must bound a worst-case batch read while staying
    paginable. The gated number is the token saving; the budget, the
    no-truncation guard and a non-empty replay are pass conditions in `detail`.
    """
    totals = report.get("totals", {})
    budget = report.get("budget", {})
    savings = float(totals.get("token_savings", 0.0))
    coverage = float(totals.get("coverage", 0.0))
    exact = bool(totals.get("legacy_comparison_exact"))
    bounded = bool(budget.get("bounded"))
    paginable = bool(budget.get("pagination_roundtrip"))
    return {
        "value": round(savings, 4),
        "pass": (savings >= THRESHOLDS["C14"]["value"] and exact and bounded
                 and paginable and coverage > 0),
        "detail": {
            "calls_total": totals.get("calls"),
            "calls_replayed": totals.get("calls_replayed"),
            "calls_excluded": totals.get("calls_excluded"),
            "coverage": coverage,
            "legacy_tokens": totals.get("legacy_tokens"),
            "current_tokens": totals.get("current_tokens"),
            "legacy_comparison_exact": exact,
            "by_op": report.get("by_op"),
            "budget_default_lines": (budget.get("default") or {}).get("lines_returned"),
            "budget_default_cap": (budget.get("default") or {}).get("max_total_lines"),
            "budget_tight_lines": (budget.get("tight") or {}).get("lines_returned"),
            "budget_tight_cap": (budget.get("tight") or {}).get("max_total_lines"),
            "budget_bounded": bounded,
            "pagination": budget.get("pagination"),
            "pagination_roundtrip": paginable,
        },
    }


def summarize_test_output(stdout: str) -> dict:
    """Aggregate every `test result:` line so the evidence carries real counts
    instead of whichever suite happened to print last."""
    totals = {"suites": 0, "passed": 0, "failed": 0, "ignored": 0}
    for m in re.finditer(
        r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", stdout
    ):
        totals["suites"] += 1
        totals["passed"] += int(m.group(1))
        totals["failed"] += int(m.group(2))
        totals["ignored"] += int(m.group(3))
    return totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", type=Path, default=None,
                    help="reuse an existing eval/metrics.json instead of regenerating")
    ap.add_argument("--bench", type=Path, default=ROOT / "bench/aci/results/latest.json")
    ap.add_argument("--compact-ratio", type=Path, default=None,
                    help="reuse an existing eval/compact_ratio.json instead of regenerating")
    ap.add_argument("--cross-shell", type=Path, default=None,
                    help="path to a stored eval/cross_shell.json (regenerate with tools/cross_shell_bench.py)")
    ap.add_argument("--envelope-replay", type=Path, default=None,
                    help="path to a stored eval/tf45_envelope_replay.json "
                         "(regenerate with tools/tf45_envelope_replay.py)")
    ap.add_argument("--evidence", type=Path, default=ROOT / "eval/evidence.json")
    ap.add_argument("--skip-tests", action="store_true",
                    help="skip cargo test; C6/C7 become stale and fail the gate")
    args = ap.parse_args(argv)

    # ── regenerate or load the Rust-side metrics ──
    if args.metrics is not None:
        metrics_path = args.metrics.resolve()
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics_source = str(metrics_path.relative_to(ROOT))
        metrics_regenerated = False
    else:
        proc = run(["cargo", "run", "--example", "eval_metrics", "--quiet",
                    "--", "--out", "eval/metrics.json"])
        if proc.returncode != 0:
            print("FAIL: could not regenerate eval/metrics.json", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
            return 1
        metrics_path = ROOT / "eval/metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics_source = "eval/metrics.json (regenerated by examples/eval_metrics.rs)"
        metrics_regenerated = True

    now = datetime.now(timezone.utc).isoformat()
    claims: list[dict] = []

    # ── C1 / C2: mock bench ratios ──
    tok_ratio, call_ratio, n_tasks, bench_meta = bench_ratios(args.bench.resolve())
    claims.append({
        "id": "C1", "claim": THRESHOLDS["C1"]["desc"],
        "threshold": "<= 0.50", "value": round(tok_ratio, 4),
        "pass": tok_ratio <= THRESHOLDS["C1"]["value"],
        "mode": "mock", "sample_size": n_tasks, "measured_at": bench_meta["generated_at"],
        "command": "python tools/claim_gate.py",
        "source": ["bench/aci/results/latest.json", "bench/aci/runners/run_suite.py"],
        "notes": "seeded mock trajectories (no live model); ratio = mean D per-task observation tokens / mean A",
    })
    claims.append({
        "id": "C2", "claim": THRESHOLDS["C2"]["desc"],
        "threshold": "<= 0.70", "value": round(call_ratio, 4),
        "pass": call_ratio <= THRESHOLDS["C2"]["value"],
        "mode": "mock", "sample_size": n_tasks, "measured_at": bench_meta["generated_at"],
        "command": "python tools/claim_gate.py",
        "source": ["bench/aci/results/latest.json", "bench/aci/runners/run_suite.py"],
        "notes": "seeded mock trajectories; ratio = mean D tool_calls / mean A tool_calls",
    })

    # ── C3: diff-class expected/found completeness ──
    c3 = metrics["reducer_diagnostic_completeness"]["diff_class"]
    claims.append({
        "id": "C3", "claim": THRESHOLDS["C3"]["desc"],
        "threshold": ">= 0.90", "value": round(c3["rate"], 4),
        "pass": c3["rate"] >= THRESHOLDS["C3"]["value"],
        "mode": "deterministic", "sample_size": c3["total"],
        "measured_at": now,
        "command": "cargo run --example eval_metrics -- --out eval/metrics.json",
        "source": ["eval/manifest.json", "examples/eval_metrics.rs",
                   "src/reducers/pytest.rs", "src/reducers/cargo.rs"],
        "detail": {"complete": c3["complete"], "total": c3["total"]},
        "notes": "scope: expect.diff_class=true entries (pytest assert `==`, cargo E0308); git/npm/panic failures carry no expected/found pair by nature",
    })

    # ── C4: one-step recovery structural checks ──
    c4_rate, c4_checks = recovery_rate(metrics)
    claims.append({
        "id": "C4", "claim": THRESHOLDS["C4"]["desc"],
        "threshold": "== 1.00", "value": round(c4_rate, 4),
        "pass": c4_rate >= THRESHOLDS["C4"]["value"],
        "mode": "deterministic", "sample_size": len(c4_checks),
        "measured_at": now,
        "command": "cargo run --example eval_metrics -- --out eval/metrics.json",
        "source": ["src/ops/file.rs", "examples/eval_metrics.rs",
                   "tests/aci_1_0_ops_tests.rs"],
        "detail": c4_checks,
        "notes": "E_STALE_HASH data.actual_hash/expected_hash + retry; E_AMBIGUOUS matches[] line/offset/snippet + widen retry",
    })

    # ── C5: no deterministic metric yet — status only, never gated ──
    claims.append({
        "id": "C5", "claim": "learning cost absorbable by a coding agent",
        "threshold": None, "value": None, "pass": None,
        "mode": None, "sample_size": None, "measured_at": None,
        "command": None,
        "source": ["docs/quickstart", "README.md"],
        "notes": "status=未证实: no deterministic metric; must not appear as an affirmative README claim",
    })

    # ── C9: compact vs JSON, measured by examples/compact_ratio.rs ──
    if args.compact_ratio is not None:
        compact_path = args.compact_ratio.resolve()
        compact_source = str(compact_path.relative_to(ROOT))
        compact_regenerated = False
    else:
        proc = run(["cargo", "run", "--example", "compact_ratio", "--quiet", "--",
                    "--out", "eval/compact_ratio.json"])
        if proc.returncode != 0:
            print("FAIL: could not regenerate eval/compact_ratio.json", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
            return 1
        compact_path = ROOT / "eval/compact_ratio.json"
        compact_source = "eval/compact_ratio.json (regenerated by examples/compact_ratio.rs)"
        compact_regenerated = True
    compact_report = json.loads(compact_path.read_text(encoding="utf-8"))
    c9 = compact_ratio_claim(compact_report)
    claims.append({
        "id": "C9", "claim": THRESHOLDS["C9"]["desc"],
        "threshold": ">= 0.40", "value": c9["value"],
        "pass": c9["pass"],
        "mode": "deterministic", "sample_size": compact_report.get("overall", {}).get("case_count"),
        "measured_at": now,
        "command": "cargo run --example compact_ratio -- --out eval/compact_ratio.json",
        "source": ["examples/compact_ratio.rs", "src/compact.rs", "src/server.rs", compact_source],
        "detail": c9["detail"],
        "notes": "scope is the compact ENCODING layer only: small response envelope must save >=0.40; "
                 "observation payloads must stay lossless but are NOT promised to shrink "
                 "(measured headline is negative); Observation Budget is a separate layer",
    })

    # ── C6 / C7 / C8: cargo test gates ──
    def test_claim(cid: str, test_args: list[str], source: list[str], notes: str) -> None:
        if args.skip_tests:
            claims.append({"id": cid, "claim": THRESHOLDS[cid]["desc"],
                           "threshold": THRESHOLDS[cid]["value"], "value": None,
                           "pass": False, "stale": True, "mode": "cargo_test",
                           "measured_at": now, "platform": sys.platform,
                           "command": "cargo test " + " ".join(test_args),
                           "source": source, "notes": notes + " (skipped by --skip-tests)"})
            return
        proc = run(["cargo", "test", "--quiet", *test_args])
        ok = proc.returncode == 0
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        claims.append({"id": cid, "claim": THRESHOLDS[cid]["desc"],
                       "threshold": "all pass", "value": 1.0 if ok else 0.0,
                       "pass": ok, "mode": "cargo_test", "measured_at": now,
                       "platform": sys.platform,
                       "command": "cargo test " + " ".join(test_args),
                       "source": source,
                       "result_tail": tail,
                       "test_totals": summarize_test_output(proc.stdout),
                       "notes": notes})

    test_claim("C6", ["--test", "aci_1_0_closed_loop_acceptance"],
               ["tests/aci_1_0_closed_loop_acceptance.rs", "src/ops/trash.rs", "src/ops/tx_ops.rs"],
               "step 6 covers file.remove (trash) -> tx.restore incl. across restarts")
    test_claim("C7", [], ["Cargo.toml", "tests/"], "full workspace test suite")
    test_claim("C8", ["--test", "process_lifecycle_tests"],
               ["tests/process_lifecycle_tests.rs", "src/process_lifecycle.rs",
                "src/process_lifecycle_windows.rs", "src/ops/process_ops.rs"],
               "process lifecycle contract: ownership echo, monotonic cursor, idempotent kill, "
               "tree termination, ConPTY + restart reconciliation; test file is #![cfg(windows)], "
               "so a pass only proves the contract on Windows")

    # ── C10: README promises (runs after the test targets so the ae binary exists) ──
    readme_path = ROOT / "eval/readme_claims.json"
    proc = run([sys.executable, "tools/readme_claims_check.py", "--json", "eval/readme_claims.json"])
    readme_ok = proc.returncode == 0
    readme_checks: list[dict] = []
    if readme_path.exists():
        try:
            readme_checks = json.loads(readme_path.read_text(encoding="utf-8")).get("checks", [])
        except json.JSONDecodeError:
            readme_checks = []
    claims.append({
        "id": "C10", "claim": THRESHOLDS["C10"]["desc"],
        "threshold": "all pass", "value": 1.0 if readme_ok else 0.0, "pass": readme_ok,
        "mode": "deterministic", "sample_size": len(readme_checks), "measured_at": now,
        "platform": sys.platform,
        "command": "python tools/readme_claims_check.py",
        "source": ["README.md", "tools/readme_claims_check.py", "tests/integration_tests.rs"],
        "detail": {
            "checks": len(readme_checks),
            "failed": [c.get("name") for c in readme_checks if not c.get("pass")],
        },
        "notes": "documented REPL examples must run and match their documented output, and README "
                 "implementation numbers must equal their source of truth; coverage is the explicit "
                 "registry in tools/readme_claims_check.py, not free-form prose",
    })

    # ── C11: cross-shell ratios from a stored measurement ──
    cross_path = args.cross_shell.resolve() if args.cross_shell else ROOT / "eval/cross_shell.json"
    cross = json.loads(cross_path.read_text(encoding="utf-8"))
    cross_agg = cross.get("aggregate", {})
    worst_ratio = cross_agg.get("worst_ratio_ae_over_pwsh")
    cross_ok = (
        bool(cross_agg.get("all_commands_ok"))
        and worst_ratio is not None
        and worst_ratio <= THRESHOLDS["C11"]["value"]
    )
    claims.append({
        "id": "C11", "claim": THRESHOLDS["C11"]["desc"],
        "threshold": "<= 0.50", "value": worst_ratio, "pass": cross_ok,
        "mode": "wall_clock", "sample_size": cross_agg.get("gated_operations"),
        "measured_at": cross.get("generated_at"),
        "platform": sys.platform,
        "command": "python tools/cross_shell_bench.py",
        "source": ["tools/cross_shell_bench.py", "eval/cross_shell.json", "README.md"],
        "detail": {
            "per_operation_ratio": {
                row.get("name"): row.get("ratio_ae_over_pwsh") for row in cross.get("operations", [])
            },
            "all_commands_ok": cross_agg.get("all_commands_ok"),
            "failed_commands": cross_agg.get("failed_commands"),
            "machine": cross.get("machine", {}).get("processor"),
            "iterations": cross.get("method", {}).get("iterations"),
        },
        "notes": "stored wall-clock measurement (20 runs + 3 warm-up, process startup included, "
                 "single machine); the gate re-checks the stored artifact, so re-run "
                 "tools/cross_shell_bench.py after changing the hot path",
    })

    # ── C14: batch-read envelope on a frozen trajectory ──
    replay_path = (args.envelope_replay.resolve() if args.envelope_replay
                   else ROOT / "eval/tf45_envelope_replay.json")
    if replay_path.exists():
        replay_report = json.loads(replay_path.read_text(encoding="utf-8"))
        c14 = batch_envelope_claim(replay_report)
        claims.append({
            "id": "C14", "claim": THRESHOLDS["C14"]["desc"],
            "threshold": ">= 0.15", "value": c14["value"], "pass": c14["pass"],
            "mode": "deterministic", "sample_size": c14["detail"]["calls_replayed"],
            "measured_at": replay_report.get("generated_at"),
            "command": "python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json",
            "source": ["tools/tf45_envelope_replay.py", "bench/aci/runners/live_agent_loop.py",
                       "src/ops/file.rs", "src/ops/common.rs", "eval/tf45_envelope_replay.json"],
            "detail": c14["detail"],
            "notes": "frozen-trajectory replay: the read ops the model actually issued in the stored "
                     "live run are re-run against the current binary and projected twice (legacy full "
                     "`sha256:<64 hex>` vs the compact 16-hex digest). It measures the observation "
                     "surface, NOT model behaviour; a call only counts when the projection the stored "
                     "run actually used reproduces its recorded token count, and the rest are listed "
                     "with both numbers (so a client change without a live re-run fails instead of "
                     "comparing across projections). The budget half of the claim is structural: a worst-case "
                     "8x300-line batch must not exceed `max_total_lines`, and paginating a 250-line "
                     "file by `next_start_line` must recover it line for line",
        })
    else:
        claims.append({
            "id": "C14", "claim": THRESHOLDS["C14"]["desc"],
            "threshold": ">= 0.15", "value": None, "pass": False,
            "mode": "deterministic", "measured_at": now,
            "command": "python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json",
            "source": ["tools/tf45_envelope_replay.py"],
            "notes": f"missing evidence artifact: {replay_path}",
        })

    # ── C12: stored evidence must still describe the current code ──
    freshness = freshness_entries()
    stale = [f["artifact"] for f in freshness if not f["pass"]]
    claims.append({
        "id": "C12", "claim": THRESHOLDS["C12"]["desc"],
        "threshold": "all artifacts fresh", "value": 1.0 if not stale else 0.0,
        "pass": not stale, "mode": "content_fingerprint",
        "sample_size": len(freshness), "measured_at": now,
        "command": "python tools/claim_gate.py",
        "source": EVIDENCE_ARTIFACTS + ["tools/claim_gate.py"],
        "detail": {"artifacts": freshness, "stale": stale},
        "notes": "each stored measurement records the sha256 fingerprint of the surface it measured; "
                 "if the code changed since, the evidence is stale and must be regenerated "
                 "(run_suite / jev_obs_judge / cross_shell_bench)",
    })

    gated = [c for c in claims if c["pass"] is not None]
    all_pass = all(c["pass"] for c in gated)

    # ── evidence.json: every external number = one claim entry here ──
    evidence = {
        "schema": "verseshell.claim-evidence/v1",
        "generated_at": now,
        "generator": "tools/claim_gate.py",
        "metrics_source": metrics_source,
        "metrics_regenerated": metrics_regenerated,
        "bench_meta": bench_meta,
        "threshold_source": "docs/claims-and-evidence.md",
        "all_pass": all_pass,
        "claims": claims,
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")

    print(f"claim_gate: {sum(1 for c in gated if c['pass'])}/{len(gated)} gated claims pass")
    for c in claims:
        if c["pass"] is None:
            status = "N/A"
        elif c.get("stale"):
            status = "STALE"
        elif c["pass"]:
            status = "PASS"
        else:
            status = "FAIL"
        val = c["value"] if c["value"] is not None else "-"
        print(f"  [{status}] {c['id']} {c['claim']}: value={val} threshold={c['threshold']}")
    print(f"evidence written: {args.evidence}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
