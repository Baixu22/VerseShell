#!/usr/bin/env python3
"""Offline design audit: distinguish size labels, measured coverage and difficulty.

This does not select tasks, change a plan, generate candidates or run a model.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from task_admissibility import LARGE_OBS_MIN_TOKENS
SOURCES = ['eval/task_set_freeze.json', 'eval/task_admissibility.json',
           'bench/aci/results/latest_live.json', 'eval/acceptance_power.json']
EVIDENCE_GLOBS = [*SOURCES, 'tools/task_design_audit.py', 'tools/task_admissibility.py', 'docs/task-generation-protocol.md']


def additional_large_required(total: int, large: int) -> int:
    """Minimum all-large additions for (large+x)/(total+x) >= 1/3."""
    if type(total) is not int or type(large) is not int or not 0 <= large <= total:
        raise ValueError('invalid task counts')
    return max(0, (total - 3 * large + 1) // 2)


def audit(freeze: dict, admission: dict, live: dict, power: dict) -> dict:
    tasks = freeze.get('tasks') or []
    if not tasks or len(tasks) != len(set(tasks)) or freeze.get('n_tasks') != len(tasks):
        raise ValueError('frozen task list/count is missing or inconsistent')
    if not freeze.get('task_set_version') or freeze['task_set_version'] != live.get('task_set_version'):
        raise ValueError('freeze and live task-set versions must match')
    observations = {}
    for candidate in admission.get('candidates', []):
        task = candidate.get('task_id')
        tokens = candidate.get('pristine_observation_tokens')
        if task not in tasks or type(tokens) is not int or tokens < 0:
            continue
        if not candidate.get('checks', {}).get('A1_pristine_fails'):
            continue
        if task in observations and observations[task] != tokens:
            raise ValueError(f'conflicting pristine observations for {task}')
        observations[task] = tokens
    large = sorted(task for task, tokens in observations.items() if tokens >= LARGE_OBS_MIN_TOKENS)
    unknown = sorted(set(tasks) - observations.keys())
    baseline = [r for r in live.get('rows', []) if r.get('condition') == 'raw_shell']
    if not baseline or len({r.get('model') for r in baseline}) != 1:
        raise ValueError('baseline needs rows from exactly one model')
    if {r.get('task_id') for r in baseline} != set(tasks):
        raise ValueError('baseline task coverage differs from the frozen set')
    mde = power['preregistered_parameters']['success_mde_absolute']
    n = len(baseline)
    successes = sum(r.get('success') is True for r in baseline)
    rate = successes / n
    count = len(tasks)
    return {
        'task_set_version': freeze.get('task_set_version'),
        'composition': {
            'total_tasks': count, 'measured_tasks': len(observations),
            'confirmed_large_tasks': large, 'unmeasured_tasks': unknown,
            'labelled_large_count': (freeze.get('per_tier') or {}).get('large'),
            'confirmed_large_fraction': len(large) / count,
            'coverage_range_not_confidence_interval': [len(large)/count, (len(large)+len(unknown))/count],
            'quota_guaranteed_by_existing_evidence': 3 * len(large) >= count,
            'all_large_additions_to_guarantee_quota_without_reclassifying_existing': additional_large_required(count, len(large)),
            'additional_range_if_unknown_tasks_are_measured': [
                additional_large_required(count, len(large)+len(unknown)),
                additional_large_required(count, len(large))],
        },
        'difficulty': {
            'scope': 'observed all-row baseline, not a population estimate or task-selection score',
            'successes': successes, 'rows': n, 'observed_success_rate': rate,
            'preregistered_target': [0.40, 0.70], 'inside_target': 0.40 <= rate <= 0.70,
            'preregistered_mde': mde, 'observed_positive_headroom': 1-rate,
            'headroom_supports_positive_mde': 1-rate >= mde,
            'does_not_rule_out': 'smaller positive effects, negative effects or another baseline in future runs',
        },
        'boundaries': [
            'Large means measured pristine output >=1000 proxy tokens, not a tier label.',
            'Missing observations are unknown, never silently counted as measured-small.',
            'The quota formula assumes each added task actually passes A8; planned labels are not evidence.',
            'Do not feed task-level live results into new difficulty design; a blind author and new frozen evaluation remain required.',
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'eval/task_design_audit.json')
    parser.add_argument('--freeze', type=Path, default=ROOT/SOURCES[0])
    parser.add_argument('--admission', type=Path, default=ROOT/SOURCES[1])
    parser.add_argument('--with-arm', type=Path, default=ROOT/SOURCES[2])
    parser.add_argument('--power', type=Path, default=ROOT/SOURCES[3])
    args = parser.parse_args(argv)
    try:
        paths = [args.freeze, args.admission, args.with_arm, args.power]
        inputs = [json.loads(p.read_text(encoding='utf-8-sig')) for p in paths]
        if inputs[3].get('task_set_version') not in (None, inputs[2].get('task_set_version')):
            raise ValueError('power and live task-set versions must match')
        if inputs[3].get('source') and Path(inputs[3]['source']).resolve() != args.with_arm.resolve():
            raise ValueError('power report was computed from a different live input')
        report = audit(*inputs)
    except (OSError, ValueError, KeyError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2
    digest = hashlib.sha256()
    for path in sorted(p for glob in EVIDENCE_GLOBS for p in ROOT.glob(glob) if p.is_file()):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    report.update(schema='verseshell.task-design-audit/v1', generator='tools/task_design_audit.py',
                  generated_at=datetime.now(timezone.utc).isoformat(),
                  evidence={'globs': EVIDENCE_GLOBS, 'fingerprint': digest.hexdigest(),
                            'input_sha256': {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    c=report['composition']; d=report['difficulty']
    print(f"coverage={c['measured_tasks']}/{c['total_tasks']}; confirmed large={len(c['confirmed_large_tasks'])}; unknown={len(c['unmeasured_tasks'])}")
    print(f"baseline={d['successes']}/{d['rows']}; positive headroom={d['observed_positive_headroom']:.6f}; MDE={d['preregistered_mde']}")
    print(f"all-large additions to guarantee quota={c['all_large_additions_to_guarantee_quota_without_reclassifying_existing']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
