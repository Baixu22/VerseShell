#!/usr/bin/env python3
"""refresh_live_artifacts: regenerate every artifact derived from the live baseline.

The claims that read the stored live run (C13-C17, C19-C21, C25, C27) each record
the sha256 fingerprint of the surface they measured. Change the runner, the task
set or the live baseline and every one of them goes stale at once (claim C12
fails closed). Doing that refresh by hand is how a half-updated evidence set gets
committed, so this runs the whole chain in dependency order and reports which
step failed. Unknown/empty selections and missing required inputs fail before any
step runs. Explicit subsets do not claim that every artifact was refreshed.
The first failed step stops the chain; downstream reports must not consume a
mixture of old and newly generated inputs.

Order matters:
  1. `latest_live.json` must already be merged (the with arm).
  2. `live_ab_without_read_files.json` must already be merged (the paired control).
  3. Regenerate the mock bundle, three-arm report and cross-shell report, then
     the remaining with-arm and two-arm tools. All result-bundle writers must
     precede tokenizer calibration (it hashes bench/aci/results/*.json).
  4. Uncertainty, power and cross-check reports consume the refreshed inputs.

The full chain includes cross-shell timing and endpoint calls in tokenizer
calibration. It belongs to the measurement owner; repair-only sessions can run
tests/test_refresh_live_artifacts.py without executing those measurements.

Usage:
    python tools/refresh_live_artifacts.py                 # full chain
    python tools/refresh_live_artifacts.py --with-only      # skip two-arm tools
    python tools/refresh_live_artifacts.py --no-endpoint    # repair/offline refresh; no endpoint probes
    python tools/refresh_live_artifacts.py --only tf45_envelope_replay
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"bench/aci/runners"))
from live_journal import atomic_json

# (label, argv, needs_without_arm)
CHAIN: list[tuple[str, list[str], bool]] = [
    # Calibration fingerprints results/*.json; regenerate the mock bundle first.
    ("mock_bench", ["bench/aci/runners/run_suite.py", "--mode", "mock",
                    "--out", "bench/aci/results/latest.json"], False),
    # The heuristic observation judge summarises the mock bench and eval/metrics.json,
    # and both are now inside its recorded fingerprint (it used to declare them as
    # inputs while fingerprinting neither, so C12 could report it fresh over changed
    # inputs). It therefore has to be refreshed right after the mock bench.
    ("jev_obs_report", ["tools/jev_obs_judge.py", "--mode", "heuristic",
                        "--report", "eval/jev_obs_report.json",
                        "--markdown", "eval/jev_obs_report.md"], False),
    ("three_arm_report", ["tools/three_arm_report.py",
                          "--out", "eval/three_arm_report.json"], False),
    ("cross_shell", ["tools/cross_shell_bench.py",
                     "--out", "eval/cross_shell.json"], False),
    # C10 checks the README table against the measured artifact. Keep
    # the derived documentation update in this chain so a fresh timing run cannot
    # leave the evidence set stale until a human performs a second command.
    ("sync_readme_cross_shell", ["tools/sync_readme_cross_shell.py"], False),
    ("tf45_envelope_replay", ["tools/tf45_envelope_replay.py",
                              "--out", "eval/tf45_envelope_replay.json"], False),
    ("read_path_breakdown", ["tools/read_path_breakdown.py",
                             "--out", "eval/read_path_breakdown.json"], False),
    ("ts_fixture_audit", ["tools/ts_fixture_audit.py",
                          "--out", "eval/ts_fixture_audit.json"], False),
    ("task_set_audit", ["tools/task_set_audit.py",
                        "--out", "eval/task_set_audit.json"], False),
    ("read_usage_audit", ["tools/read_usage_audit.py",
                          "--out", "eval/read_usage_audit.json"], True),
    ("exec_token_breakdown", ["tools/exec_token_breakdown.py",
                              "--out", "eval/exec_token_breakdown.json"], True),
    ("exec_failure_breakdown", ["tools/exec_failure_breakdown.py",
                                "--out", "eval/exec_failure_breakdown.json"], True),
    ("step_composition", ["tools/step_composition.py",
                          "--out", "eval/step_composition.json"], True),
    ("token_proxy_calibration", ["tools/token_proxy_calibration.py",
                                 "--out", "eval/token_proxy_calibration.json"], False),
    ("live_uncertainty", ["tools/live_uncertainty.py",
                          "--out", "eval/live_uncertainty.json"], True),
    # Last: it reads the artifacts above (acceptance_power's fingerprint covers
    # eval/live_uncertainty.json and eval/cross_shell.json).
    ("acceptance_power", ["tools/acceptance_power.py",
                          "--out", "eval/acceptance_power.json"], True),
    # Very last: it reads the published values from BOTH artifacts above and re-derives
    # the same numbers along an independent code path (TF-0111), so it must see the
    # final numbers rather than an intermediate state.
    ("statistics_crosscheck", ["tools/statistics_crosscheck.py",
                               "--out", "eval/statistics_crosscheck.json"], False),
    # Field-only task diagnostic, independent of success and claim eligibility.
    ("task_design_audit", ["tools/task_design_audit.py",
                           "--out", "eval/task_design_audit.json"], False),
    ("budget_sensitivity", ["tools/budget_sensitivity.py",
                            "--out", "eval/budget_sensitivity.json"], True),
    # Reads the per-seed raw runs plus live_uncertainty.json, so it also comes after.
    ("run_variance", ["tools/run_variance.py",
                      "--out", "eval/run_variance.json"], True),
]

WITH_ARM = ROOT / "bench/aci/results/latest_live.json"
WITHOUT_ARM = ROOT / "bench/aci/results/live_ab_without_read_files.json"

# One inventory for generation and recovery; Markdown is also published evidence.
COLLECTION_REPORT_FILES = (
    "task_set_audit.json", "three_arm_report.json",
    "cost_attribution.json", "cost_attribution.md",
    "anomaly_audit.json", "anomaly_audit.md", "acceptance_power.json",
)


def refresh_collection(collection, output, task_set, variant=None, runner=None):
    """Offline, isolated report bundle. Completion manifest is written last."""
    runner = runner or subprocess.run
    source = Path(collection)/'latest_live.json'
    output = Path(output)
    if not source.is_file():
        raise ValueError('collection has no latest_live.json')
    if output.exists() and any(output.iterdir()):
        raise ValueError('report directory is not empty; choose a new output')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    status = output/'refresh-status.json'
    receipt = {'complete': False, 'state': 'running', 'source': str(source.resolve()),
               'source_sha256': before, 'prompt_variant': variant, 'steps': []}
    atomic_json(status, receipt)
    plans = [
        ['tools/task_set_audit.py', '--with-arm', str(source), '--task-set', str(task_set), '--out', str(output/'task_set_audit.json')],
        ['tools/three_arm_report.py', '--with-arm', str(source), '--out', str(output/'three_arm_report.json')],
        ['tools/cost_attribution.py', '--with-arm', str(source), '--out', str(output/'cost_attribution.json')],
        ['tools/anomaly_audit.py', '--with-arm', str(source), '--task-set', str(task_set), '--out', str(output/'anomaly_audit.json')],
        ['tools/acceptance_power.py', '--with-arm', str(source), '--with-only', '--skip-cross-shell', '--out', str(output/'acceptance_power.json')],
    ]
    try:
        for index, command in enumerate(plans):
            if variant and index:
                command += ['--prompt-variant', variant]
            step = {'tool': command[0], 'state': 'running', 'exit_code': None}
            receipt['steps'].append(step)
            atomic_json(status, receipt)
            rc = runner([sys.executable, *command], cwd=ROOT).returncode
            step.update(exit_code=rc, state='completed' if type(rc) is int and rc == 0 else 'failed')
            if type(rc) is not int or rc != 0:
                receipt.update(state='failed', error='nonzero or unknown tool exit code')
                atomic_json(status, receipt)
                return rc if type(rc) is int and rc != 0 else 2
            atomic_json(status, receipt)
        if hashlib.sha256(source.read_bytes()).hexdigest() != before:
            raise ValueError('source changed during refresh; bundle remains incomplete')
        if any(not (output/name).is_file() for name in COLLECTION_REPORT_FILES):
            raise ValueError('generator exited without required report; bundle remains incomplete')
        receipt.update(complete=True, state='completed', scope='with-only offline reports; not live acceptance',
                       reports={name: hashlib.sha256((output/name).read_bytes()).hexdigest()
                                for name in COLLECTION_REPORT_FILES})
        atomic_json(status, receipt)
    except (ValueError, OSError) as error:
        receipt.update(complete=False, state='failed', error=str(error))
        if receipt['steps'] and receipt['steps'][-1]['state'] == 'running':
            receipt['steps'][-1]['state'] = 'failed'
        atomic_json(status, receipt)
        raise
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-only", action="store_true",
                    help="skip the steps that also read the without arm")
    ap.add_argument("--task-set", type=Path, default=ROOT / "bench/aci/task_sets/3.1.0.json",
                    help="effective task predicates for the C24 audit")
    ap.add_argument("--only", default=None, help="comma-separated known step labels; empty selections are rejected")
    ap.add_argument("--allow-missing-without", action="store_true",
                    help="run two-arm steps even if the control arm is missing")
    ap.add_argument("--no-endpoint", action="store_true",
                    help="pass --no-endpoint to tokenizer calibration; intended for offline repair refreshes")
    ap.add_argument('--collection', type=Path, help='isolated with-only offline report bundle')
    ap.add_argument('--out-dir', type=Path)
    ap.add_argument('--prompt-variant', choices=['baseline','compact','compact_all'])
    args = ap.parse_args()
    if args.collection:
        if not args.out_dir or args.only or args.allow_missing_without:
            ap.error('--collection requires --out-dir and cannot mix legacy selection flags')
        try:
            return refresh_collection(args.collection, args.out_dir, args.task_set, args.prompt_variant)
        except (ValueError, OSError) as error:
            print(f'ERROR: {error}', file=sys.stderr)
            return 2
    if args.out_dir or args.prompt_variant:
        ap.error('--out-dir/--prompt-variant require --collection')

    only = {s.strip() for s in (args.only or "").split(",") if s.strip()}
    known = {label for label, _, _ in CHAIN}
    if args.only is not None and not only:
        ap.error("--only must select at least one step")
    if only - known:
        ap.error("unknown --only step(s): " + ", ".join(sorted(only - known)))
    selected = [entry for entry in CHAIN if not only or entry[0] in only]
    if args.with_only and only and any(needs_without for _, _, needs_without in selected):
        ap.error("--with-only conflicts with explicitly selected two-arm steps")
    planned = [entry for entry in selected if not (args.with_only and entry[2])]
    if not planned:
        ap.error("no refresh steps selected")
    have_without = WITHOUT_ARM.exists()
    if not WITH_ARM.exists():
        print(f"ERROR: missing {WITH_ARM}; merge the with arm first", file=sys.stderr)
        return 2
    if not have_without and any(needs_without for _, _, needs_without in planned):
        if not args.allow_missing_without:
            print(f"ERROR: missing {WITHOUT_ARM}; use --with-only for an explicit subset, "
                  "or --allow-missing-without to let the selected tools diagnose it", file=sys.stderr)
            return 2
        print(f"NOTE: {WITHOUT_ARM.name} is missing; selected two-arm tools will still run")

    skipped: list[str] = []
    for label, argv, needs_without in CHAIN:
        if only and label not in only:
            continue
        if args.with_only and needs_without:
            skipped.append(label)
            continue
        print(f"\n{'=' * 72}\n[{time.strftime('%H:%M:%S')}] {label}\n{'=' * 72}", flush=True)
        child_argv = list(argv)
        if label == "task_set_audit":
            child_argv.extend(["--task-set", str(args.task_set)])
        if args.no_endpoint and label == "token_proxy_calibration":
            child_argv.append("--no-endpoint")
        try:
            rc = subprocess.run([sys.executable, *child_argv], cwd=ROOT).returncode
        except OSError as exc:
            print(f"FAILED: {label}: {exc}; remaining steps not run", file=sys.stderr)
            return 1
        print(f"[{time.strftime('%H:%M:%S')}] {label} -> exit {rc}", flush=True)
        if rc != 0:
            print(f"FAILED: {label} (exit {rc}); remaining steps not run", file=sys.stderr)
            return 1

    print("\n" + "=" * 72)
    if skipped:
        print("skipped: " + ", ".join(skipped))
    print(f"completed {len(planned)} selected refresh step(s); "
          "run claim_gate.py to check evidence freshness")
    return 0


if __name__ == "__main__":
    sys.exit(main())
