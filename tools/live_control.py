"""Launch a frozen round and finalize isolated offline reports, without PowerShell exit-code ambiguity.

Launch: python tools/live_control.py --workspace D:/VerseShellLive/workspace --tag NEW -- [live_round options]
Report-only recovery: same command with --finalize RECEIPT.json (never relaunches collection).
New launches need the configured endpoint; report-only recovery is offline.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'bench/aci/runners'))
from live_journal import RunStatus, atomic_json, pid_alive, utc_now
from live_storage import storage_check, storage_policy
from live_agent_loop import run_bounded
from refresh_live_artifacts import COLLECTION_REPORT_FILES


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def resolve_exit(process_code, terminal, receipt):
    """A durable zero is trusted only for this launched PID and generation."""
    if process_code is not None and type(process_code) is not int:
        return 2, 'unknown_or_conflicting_exit'
    matched = (terminal.get('control_generation_id') == receipt['control_generation_id']
               and type(terminal.get('pid')) is int and terminal['pid'] > 0
               and terminal['pid'] == receipt.get('round_pid', receipt['pid']) and bool(terminal.get('generation_id'))
               and terminal.get('finished_at')
               and (not receipt.get('round_generation_id')
                    or terminal['generation_id'] == receipt['round_generation_id']))
    durable = terminal.get('exit_code')
    valid = (matched and type(durable) is int and
             ((durable == 0 and terminal.get('state') == 'completed') or
              (durable == 75 and terminal.get('state') == 'paused') or
              (durable != 0 and terminal.get('state') in ('failed', 'interrupted'))))
    if type(process_code) is int and process_code != 0:
        return process_code, 'process_handle'
    if valid and (process_code is None or process_code == durable):
        return durable, 'matching_terminal' if process_code is None else 'process_and_terminal'
    return 2, 'unknown_or_conflicting_exit'


def launch(command, workspace, collection, control, policy):
    control.mkdir(parents=True, exist_ok=False)
    receipt_path = control/'collection-exit.json'
    receipt = {'schema': 'verseshell.live-control/v1', 'workspace': str(workspace.resolve()),
               'collection': str(collection.resolve()), 'control_generation_id': control.name,
               'started_at': utc_now(), 'state': 'starting', 'pid': None,
               'storage_reserves': policy, 'controller_sha256': sha(__file__)}
    atomic_json(receipt_path, receipt)
    env = dict(os.environ, ACI_CONTROL_GENERATION_ID=control.name,
               ACI_STORAGE_RESERVES=json.dumps(policy))
    try:
        with (control/'collection.stdout.log').open('xb') as stdout, (control/'collection.stderr.log').open('xb') as stderr:
            def started(child):
                receipt.update(pid=child.pid, state='running')
                atomic_json(receipt_path, receipt)
            code, _, _, _ = run_bounded(command, timeout=None, cwd=workspace, env=env,
                                        stdout=stdout, stderr=stderr, on_start=started)
        receipt['process_exit_code'] = code
        try:
            terminal = read_json(collection/'round.status.json')
        except (OSError, ValueError):
            terminal = {}
        # Windows venv python.exe can delegate to a different interpreter PID.
        # Bind that PID only after our retained handle exits, using the unique nonce.
        if terminal.get('control_generation_id') == receipt['control_generation_id']:
            receipt['round_pid'] = terminal.get('pid')
        code, basis = resolve_exit(code, terminal, receipt)
        receipt.update(round_generation_id=terminal.get('generation_id'), terminal=terminal,
                       resolved_exit_code=code, exit_basis=basis,
                       state='completed' if code == 0 else 'paused' if code == 75 else 'failed',
                       finished_at=utc_now())
    except KeyboardInterrupt:
        # The managed process tree has already been terminated before this receipt.
        receipt.update(state='interrupted', resolved_exit_code=130, exit_basis='controller_interrupt',
                       finished_at=utc_now())
        atomic_json(receipt_path, receipt)
        raise
    except OSError as error:
        receipt.update(state='failed', resolved_exit_code=2, error=str(error), finished_at=utc_now())
    atomic_json(receipt_path, receipt)
    return receipt_path


def finalize(receipt_path, workspace, collection, task_set):
    receipt = read_json(receipt_path)
    if (receipt.get('schema') != 'verseshell.live-control/v1'
            or receipt.get('workspace') != str(workspace.resolve())
            or receipt.get('collection') != str(collection.resolve())):
        raise ValueError('receipt does not identify this workspace/collection')
    if pid_alive(receipt.get('pid')) or pid_alive(receipt.get('round_pid')):
        raise ValueError('collection owner is still alive; refusing report recovery')
    terminal = read_json(collection/'round.status.json')
    code, basis = resolve_exit(receipt.get('process_exit_code'), terminal, receipt)
    # Refuse a newer generation even if an old receipt has process_exit_code=0.
    if code:
        return code
    plan = read_json(collection/'collection.json')
    variants = plan.get('prompt_variants', [plan.get('prompt_variant', 'baseline')])
    if not variants or len(set(variants)) != len(variants) or set(variants) - {'baseline', 'compact', 'compact_all', 'shell_guided'}:
        raise ValueError('invalid frozen report variants')
    if plan.get('task_set') != str(task_set.resolve()):
        raise ValueError('report task set differs from collection')
    source = collection/'latest_live.json'
    sources = {str(p.resolve()): sha(p) for p in (source, collection/'collection.json', task_set)}
    attempt = Path(receipt_path).parent/('reports-'+uuid.uuid4().hex)
    attempt.mkdir()
    summary = {'schema': 'verseshell.live-reports/v1', 'state': 'running', 'complete': False,
               'control_generation_id': receipt['control_generation_id'],
               'round_generation_id': terminal['generation_id'], 'exit_basis': basis,
               'source_sha256': sources, 'started_at': utc_now(),
               'reports': {v: {'state': 'pending', 'exit_code': None} for v in variants},
               'scope': 'offline report generation; not product or statistical acceptance'}
    status = attempt/'reports-status.json'
    atomic_json(status, summary)
    for variant in variants:
        item = summary['reports'][variant]
        output = attempt/variant
        item.update(state='running', output=str(output))
        atomic_json(status, summary)
        try:
            check = storage_check(receipt.get('storage_reserves', {}))
            if not check['ok']:
                atomic_json(collection/'STOP', {'reason': 'storage_reserve', **check})
                item.update(state='paused', reason='storage_reserve', storage=check, finished_at=utc_now())
                atomic_json(status, summary)
                continue
            if any(sha(p) != digest for p, digest in sources.items()):
                raise ValueError('source changed before report generation')
            command = [sys.executable, str(workspace/'tools/refresh_live_artifacts.py'),
                       '--collection', str(collection), '--out-dir', str(output),
                       '--task-set', str(task_set), '--prompt-variant', variant]
            with (attempt/(variant+'.stdout.log')).open('xb') as stdout, (attempt/(variant+'.stderr.log')).open('xb') as stderr:
                item['exit_code'], _, _, _ = run_bounded(command, timeout=None, cwd=workspace,
                                                        stdout=stdout, stderr=stderr)
            if item['exit_code'] != 0:
                raise ValueError('report tool failed; see preserved logs')
            manifest = read_json(output/'refresh-status.json')
            if (not manifest.get('complete') or manifest.get('source_sha256') != sources[str(source.resolve())]
                    or manifest.get('prompt_variant') != variant):
                raise ValueError('missing or mismatched completed report manifest')
            if set(manifest.get('reports', {})) != set(COLLECTION_REPORT_FILES):
                raise ValueError('incomplete report inventory')
            if any(sha(output/name) != digest for name, digest in manifest['reports'].items()):
                raise ValueError('report digest mismatch')
            if any(sha(p) != digest for p, digest in sources.items()):
                raise ValueError('source changed during report generation')
            item.update(state='completed', manifest_sha256=sha(output/'refresh-status.json'))
        except KeyboardInterrupt:
            item.update(state='interrupted', finished_at=utc_now())
            summary.update(state='interrupted', finished_at=utc_now())
            atomic_json(status, summary)
            raise
        except (OSError, ValueError) as error:
            item.update(state='failed', error=str(error))
        item['finished_at'] = utc_now()
        atomic_json(status, summary)
    summary['complete'] = all(v['state'] == 'completed' for v in summary['reports'].values())
    state = ('completed' if summary['complete'] else
             'failed' if any(v['state'] == 'failed' for v in summary['reports'].values()) else 'paused')
    summary.update(state=state, finished_at=utc_now())
    atomic_json(status, summary)
    print(status, flush=True)
    return 0 if summary['complete'] else 75 if state == 'paused' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--task-set', type=Path)
    parser.add_argument('--finalize', type=Path, help='offline report-only retry from launch receipt')
    parser.add_argument('round_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    collection = workspace/'bench/aci/results'/args.tag
    if collection.resolve().parent != (workspace/'bench/aci/results').resolve():
        parser.error('--tag must be a single directory name')
    task_set = (args.task_set or workspace/'bench/aci/task_sets/3.1.0.json').resolve()
    extra = args.round_args[1:] if args.round_args[:1] == ['--'] else args.round_args
    if args.finalize and extra:
        parser.error('--finalize cannot dispatch collection options')
    if any(x.split('=')[0] in {'--tag', '--task-set', '--publish', '--force', '--dry-run'} for x in extra):
        parser.error('tag/task-set are controlled here; publish/force/dry-run are not supported')
    collection.mkdir(parents=True, exist_ok=True)
    try:
        with RunStatus(collection/'control.status.json') as owner:
            receipt_path = args.finalize
            if receipt_path is None:
                policy = storage_policy() if 'ACI_STORAGE_RESERVES' in os.environ else (
                    {'D:/': 15*1024**3, 'C:/': 2*1024**3} if os.name == 'nt' else {})
                check = storage_check(policy)
                if not check['ok']:
                    atomic_json(collection/'STOP', {'reason': 'storage_reserve', **check})
                    owner.update(state='paused', exit_code=75, finished_at=utc_now())
                    return 75
                command = [sys.executable, str(workspace/'tools/live_round.py'), '--tag', args.tag,
                           '--task-set', str(task_set), *extra]
                receipt_path = launch(command, workspace, collection,
                                      collection/'control'/owner.value['generation_id'], policy)
                print(receipt_path, flush=True)
                receipt = read_json(receipt_path)
                if receipt['resolved_exit_code'] != 0:
                    code = receipt['resolved_exit_code']
                    owner.update(state=receipt['state'], exit_code=code, finished_at=utc_now())
                    return code
            code = finalize(receipt_path, workspace, collection, task_set)
            owner.update(state='completed' if code == 0 else 'paused' if code == 75 else 'failed',
                         exit_code=code, finished_at=utc_now())
            return code
    except (OSError, ValueError, RuntimeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
