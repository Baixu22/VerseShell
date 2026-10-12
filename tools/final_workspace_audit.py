"""Verify saved grading inputs and optionally re-score explicitly selected cells offline.

Missing historical files remain unknown, never inferred from a write command.
External protected-verifier references require an explicit --verifier-source;
only exact hash-matching verifier bytes may come from it, never student files.
--rescore executes the current trusted task predicate, so select cells explicitly.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'bench/aci/runners'))
from final_workspace import load_manifest, restore, grader_hashes
from grading_contract import guarded_success
from live_agent_loop import check_success
from task_sets import load_tasks


def review_row(row, root, *, task=None, rescore=False, work_dir=None, verifier_source=None):
    result = {k: row.get(k) for k in ('cell_id', 'task_id', 'condition', 'prompt_variant', 'seed', 'run_index')}
    result.update(recorded_success=row.get('success'), snapshot_verified=False,
                  independent_success=None, matches_recorded=None, rescore_attempted=False)
    reference = row.get('final_workspace')
    if not isinstance(reference, dict) or reference.get('state') not in ('available', 'requires_verifier_source'):
        result.update(status='unavailable', reason=(reference or {}).get('reason', 'historical_final_workspace_not_recorded')
                      if isinstance(reference, (dict, type(None))) else 'invalid_snapshot_reference')
        return result
    if reference['state'] == 'requires_verifier_source' and verifier_source is None:
        result.update(status='unavailable', reason='explicit_frozen_verifier_source_required')
        return result
    try:
        manifest, _ = load_manifest(root, reference, verifier_source=verifier_source)
        if (not row.get('cell_id') or manifest.get('cell_id') != row['cell_id']
                or manifest.get('task_id') != row.get('task_id')
                or manifest.get('protected_verifiers') != row.get('protected_verifiers')):
            raise ValueError('snapshot does not match row identity/verifier contract')
        result.update(status='snapshot_verified', snapshot_verified=True,
                      files=len(manifest['files']), bytes=manifest['total_bytes'],
                      grader_matches_current=manifest.get('grader_sha256') == grader_hashes(),
                      scope=manifest['scope'], protected_reference_count=reference.get('protected_reference_count', 0))
        if reference['state'] == 'requires_verifier_source':
            result['verifier_source'] = str(Path(verifier_source).resolve())
        if not rescore:
            return result
        if task is None or task.get('success') != manifest.get('predicate'):
            result.update(status='not_comparable', reason='current_task_predicate_missing_or_changed')
            return result
        if not result['grader_matches_current']:
            result.update(status='not_comparable', reason='grader_source_changed')
            return result
        if work_dir is not None:Path(work_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='aci-final-review-', dir=work_dir) as temporary:
            workspace = Path(temporary)/'work'
            restore(root, reference, workspace, verifier_source=verifier_source)
            result['rescore_attempted'] = True
            success, reason = guarded_success(task['success'], workspace, manifest['protected_verifiers'], check_success)
        result.update(status='rescored' if success is not None else 'unverified',
                      independent_success=success, independent_reason=reason,
                      matches_recorded=(success == row.get('success')) if type(success) is bool and type(row.get('success')) is bool else None,
                      comparability='current-machine replay; external runtime/toolchain state is not frozen')
    except (OSError, ValueError, KeyError, TypeError) as error:
        if not result['rescore_attempted']:result['snapshot_verified'] = False
        result.update(status='rescore_error' if result['rescore_attempted'] else 'invalid_snapshot', reason=str(error))
    return result


def audit(payload, root, *, tasks=None, rescore_ids=(), work_dir=None, verifier_sources=None):
    rows = payload.get('rows', [])
    selected = set(rescore_ids)
    if selected - {r.get('cell_id') for r in rows}:
        raise ValueError('selected cell is missing from input')
    if any(sum(r.get('cell_id') == cell for r in rows) != 1 for cell in selected):
        raise ValueError('selected cell identity is duplicated')
    records = [review_row(row, root, task=(tasks or {}).get(row.get('task_id')),
                          rescore=row.get('cell_id') in selected, work_dir=work_dir,
                          verifier_source=(verifier_sources or {}).get(row.get('task_id'))) for row in rows]
    reasons = Counter(r.get('reason', r['status']) for r in records if not r['snapshot_verified'])
    return {'schema': 'verseshell.final-workspace-audit/v1',
            'scope': 'saved grading-input coverage and selected current-machine re-scores; not full historical recertification',
            'summary': {'rows': len(records), 'snapshots_verified': sum(r['snapshot_verified'] for r in records),
                        'snapshots_unavailable_or_invalid': sum(not r['snapshot_verified'] for r in records),
                        'rescore_selected': len(selected), 'rescore_attempted': sum(r['rescore_attempted'] for r in records),
                        'independently_scored': sum(type(r['independent_success']) is bool for r in records),
                        'matches_recorded': sum(r['matches_recorded'] is True for r in records),
                        'disagrees_with_recorded': sum(r['matches_recorded'] is False for r in records),
                        'unavailable_reasons': dict(reasons)}, 'rows': records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rescore', action='store_true')
    parser.add_argument('--cell-id', action='append', default=[])
    parser.add_argument('--verifier-source', action='append', default=[], metavar='TASK_ID=DIRECTORY',
                        help='explicit frozen verifier source for a task; never fills missing student files')
    parser.add_argument('--task-set', type=Path, default=ROOT/'bench/aci/task_sets/3.1.0.json')
    args = parser.parse_args(argv)
    if args.out.exists() or args.out.resolve().is_relative_to(args.input.parent.resolve()):
        parser.error('output must be a new file outside the historical input directory')
    if bool(args.cell_id) != args.rescore or len(args.cell_id) > 20 or len(set(args.cell_id)) != len(args.cell_id):
        parser.error('--rescore requires 1..20 distinct --cell-id values; default audit never executes predicates')
    sources = {}
    for binding in args.verifier_source:
        task_id, separator, directory = binding.partition('=')
        if not separator or not task_id or not directory or task_id in sources:
            parser.error('--verifier-source requires distinct TASK_ID=DIRECTORY bindings')
        sources[task_id] = Path(directory)
    raw = args.input.read_bytes()
    tasks = load_tasks(ROOT/'bench/aci/tasks', args.task_set)[1] if args.rescore else None
    report = audit(json.loads(raw.decode('utf-8-sig')), args.input.parent, tasks=tasks,
                   rescore_ids=args.cell_id, work_dir=args.out.parent/'workspaces', verifier_sources=sources)
    report['source'] = {'path': str(args.input.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    report['analyzer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.input.read_bytes() != raw:raise ValueError('historical input changed during audit')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
