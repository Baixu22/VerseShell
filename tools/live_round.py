"""One round of the live ACI-Bench baseline, with real model calls.

Protocol: all manifest tasks x requested conditions x seed-labelled shards,
with and without read_files. Outputs stay under the tag unless --publish is set.
  without arm = the same model/seeds with only `read_files` hidden (paired control)

Every cell is a real function-calling run through live_agent_loop.py. The script
is resumable only under the same frozen collection. Existing outputs must pass
identity and grid checks; endpoint failures are retained as diagnostic partials.

Usage:
    python tools/live_round.py --tag tf88                 # full round
    python tools/live_round.py --tag tf88 --arms with     # one arm only
    python tools/live_round.py --tag tf88 --force         # ignore existing files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import shutil
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_LOCAL = ROOT / ".env.local"
RUNNER = ROOT / "bench" / "aci" / "runners" / "live_agent_loop.py"
MERGER = ROOT / "bench" / "aci" / "runners" / "merge_live_runs.py"
RESULTS = ROOT / "bench" / "aci" / "results"
sys.path.insert(0, str(RUNNER.parent))
import live_agent_loop as harness
from live_identity import validate_run
from merge_live_runs import row_class
from live_journal import RunStatus,utc_now
from task_sets import load_tasks
from live_schedule import make_schedule, digest as schedule_digest
from live_journal import atomic_json
from live_storage import storage_policy, storage_check

SEEDS = (42, 43, 44)


def load_env(path=ENV_LOCAL) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def run(label: str, cmd: list[str]) -> int:
    print(f"\n{'=' * 72}\n[{time.strftime('%H:%M:%S')}] {label}\n{'=' * 72}", flush=True)
    rc, _, _, _ = harness.run_bounded(cmd, timeout=None, cwd=ROOT, stdout=None, stderr=None)
    print(f"[{time.strftime('%H:%M:%S')}] {label} -> exit {rc}", flush=True)
    return rc


def has_api_error(path: Path) -> int:
    if not path.exists():
        return -1
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return sum(row_class(r, data.get('live_config', {}).get('max_turns')) == 'endpoint_failure'
               for r in data.get("rows", []))


def verify_readiness(readiness_path,probe_path,model,base,max_tokens,analysis_plan):
    from prelive_check import source_hashes
    readiness=json.loads(Path(readiness_path).read_text(encoding='utf-8'))
    probe=json.loads(Path(probe_path).read_text(encoding='utf-8'))
    if readiness.get('schema')!='verseshell.prelive-readiness/v1' or not readiness.get('ready_for_live') or not readiness.get('source_sha256'):
        raise ValueError('offline readiness is missing or failed')
    if readiness['source_sha256'] != source_hashes(ROOT):
        raise ValueError('readiness source changed or source inventory is incomplete')
    if not {'python','node','cargo','rustc','npm'}<=set(readiness.get('toolchain',{})):
        raise ValueError('readiness lacks toolchain identities')
    for name,item in readiness.get('toolchain',{}).items():
        executable=sys.executable if name=='python' else shutil.which(name)
        if not executable or str(Path(executable).resolve())!=item['path'] or hashlib.sha256(Path(executable).read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError(f'toolchain changed since readiness: {name}')
    if hashlib.sha256(harness.AE.read_bytes()).hexdigest()!=readiness.get('binary_sha256'):
        raise ValueError('ae binary changed since readiness')
    if hashlib.sha256(Path(analysis_plan).read_bytes()).hexdigest()!=readiness.get('analysis_plan_sha256'):
        raise ValueError('analysis plan differs from readiness')
    fingerprint=harness.evidence_fingerprint(harness.EVIDENCE_GLOBS)
    if (probe.get('schema')!='verseshell.endpoint-readiness/v1' or not probe.get('pass') or probe.get('requested_model')!=model or probe.get('api_base')!=base
            or probe.get('max_tokens')!=max_tokens or probe.get('source_fingerprint')!=fingerprint
            or not probe.get('probe_source_sha256')
            or probe['probe_source_sha256']!=readiness['source_sha256'].get('tools/prelive_probe.py')):
        raise ValueError('endpoint probe does not match model/URL/budget/current runner/probe source')


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--tag", required=True, help="subdirectory under bench/aci/results")
    ap.add_argument("--env-file", type=Path, default=ENV_LOCAL)
    ap.add_argument("--model", help="override ACI_BENCH_MODEL for this frozen collection")
    ap.add_argument('--task-set',type=Path,default=ROOT/'bench/aci/task_sets/3.1.0.json')
    ap.add_argument('--tasks', help='comma-separated development task IDs; omitted means the full manifest')
    ap.add_argument('--prompt-variant',choices=['baseline','compact','compact_all','shell_guided','shell_safe'],default='baseline')
    ap.add_argument('--prompt-variants', help='comma-separated variants, balanced within each task/seed block')
    ap.add_argument('--order-seed', type=int, default=42)
    ap.add_argument('--analysis-plan',type=Path,help='prospective hypothesis family frozen before collection')
    ap.add_argument('--preflight',type=Path)
    ap.add_argument('--probe-report',type=Path)
    ap.add_argument('--resume-paused',action='store_true')
    ap.add_argument("--dry-run", action="store_true", help="freeze configuration without model calls")
    ap.add_argument("--publish", action="store_true", help="explicitly replace canonical merged baselines")
    ap.add_argument("--arms", default="with")
    ap.add_argument("--conditions", default="raw_shell,raw_shell_coached,verseshell_aci",
                    help="conditions to run; the default is the three-arm design "
                         "(neutral shell baseline, prompt-matched shell control, ACI)")
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    ap.add_argument("--force", action="store_true")
    ap.add_argument('--repeat-call-limit', type=int, default=0,
                    help='same optional repeat budget for every condition/variant; 0 disables, N >= 2')
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=16384,
                    help="completion budget per turn; the endpoint serves a reasoning "
                         "model, so a small cap truncates before any tool call is emitted")
    args = ap.parse_args()
    try:harness.validate_repeat_call_limit(args.repeat_call_limit)
    except ValueError as error:ap.error(str(error))

    env = load_env(args.env_file)
    model = args.model or env['ACI_BENCH_MODEL']
    if args.analysis_plan and not args.dry_run:
        if not args.model or not args.preflight or not args.probe_report:
            ap.error('prospective collection requires explicit --model, --preflight and --probe-report')
        try:verify_readiness(args.preflight,args.probe_report,model,env['ACI_BENCH_BASE_URL'],args.max_tokens,args.analysis_plan)
        except (ValueError,OSError) as error:ap.error(str(error))
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    outdir = RESULTS / args.tag
    if outdir.resolve().parent != RESULTS.resolve():
        ap.error('--tag must be a single directory name under results')
    if args.force:
        ap.error('use a new tag instead of replacing a frozen collection')
    if not arms or set(arms) - {'with', 'without'} or len(arms) != len(set(arms)):
        ap.error('invalid/duplicate arms')
    if not seeds or len(seeds) != len(set(seeds)):
        ap.error('invalid/duplicate seeds')
    conditions = args.conditions.split(',')
    if len(conditions) != len(set(conditions)) or set(conditions) - {'raw_shell','raw_shell_coached','verseshell_aci'}:
        ap.error('invalid/duplicate conditions')
    outdir.mkdir(parents=True, exist_ok=True)
    manifest,_=load_tasks(harness.TASKS_DIR,args.task_set)
    task_ids = list(manifest['tasks']) if args.tasks is None else [t.strip() for t in args.tasks.split(',')]
    if not task_ids or len(task_ids) != len(set(task_ids)) or set(task_ids) - set(manifest['tasks']):
        ap.error('invalid, empty, duplicate or unknown task selection')
    schedule = None
    if args.prompt_variants:
        try:
            schedule = make_schedule(task_ids, conditions, seeds,
                                     args.prompt_variants.split(','), order_seed=args.order_seed)
        except ValueError as error:
            ap.error(str(error))
    plan = {'collection_id': args.tag, 'model': model,
            'api_base': env['ACI_BENCH_BASE_URL'], 'arms': arms, 'seeds': seeds,
            'conditions': conditions, 'max_turns': args.max_turns,
            'max_tokens': args.max_tokens, 'temperature': 0, 'repeat_call_limit': args.repeat_call_limit,
            'tasks': task_ids,'task_set_version':manifest['task_set_version'],
            'task_set':str(args.task_set.resolve()),'prompt_variant':args.prompt_variant,
            'candidate_fingerprint': harness.evidence_fingerprint(harness.EVIDENCE_GLOBS),
            'binary_sha256': hashlib.sha256(harness.AE.read_bytes()).hexdigest(),
            'orchestrator_sha256': hashlib.sha256(Path(__file__).read_bytes()+MERGER.read_bytes()+(ROOT/'tools/live_control.py').read_bytes()).hexdigest(),
            'storage_reserves': storage_policy(),
            'cell_retries': 0, 'interrupted_cell_attempts': 3,
            'http_retries': '429/5xx/network, max 3 attempts within 900s; 401/402/403 pause; every attempt recorded',
            'classification': 'one complete engineering validation collection, not 3 independent repeats'}
    if schedule:
        plan.update(prompt_variants=schedule['variants'], schedule_sha256=schedule_digest(schedule))
    if args.analysis_plan:
        from study_inference import read_plan
        analysis=read_plan(args.analysis_plan)
        if len(seeds)<analysis['minimum_seeds'] or len(task_ids)<analysis['minimum_tasks']:
            ap.error('collection grid below analysis-plan floors; specify at least five seeds')
        plan['analysis_plan_sha256']=hashlib.sha256(args.analysis_plan.read_bytes()).hexdigest()
    freeze = outdir/'collection.json'
    if freeze.exists() and json.loads(freeze.read_text(encoding='utf-8')) != plan:
        ap.error('frozen collection differs from current configuration/source; use a new tag')
    if schedule:
        schedule_path = outdir/'schedule.json'
        if schedule_path.exists() and json.loads(schedule_path.read_text(encoding='utf-8')) != schedule:
            ap.error('frozen schedule changed; use a new tag')
        atomic_json(schedule_path, schedule)
    if not freeze.exists():
        atomic_json(freeze, plan)
    if args.dry_run:
        print(f"frozen {len(plan['tasks'])*len(plan['conditions'])*len(seeds)*len(arms)*len(plan.get('prompt_variants', [args.prompt_variant]))} cells: {freeze}")
        return 0
    storage = storage_check(plan['storage_reserves'])
    if not storage['ok']:
        atomic_json(outdir/'STOP', {'reason': 'storage_reserve', **storage})
        print('PAUSED: storage reserve unavailable', file=sys.stderr)
        return 75
    if args.resume_paused and (outdir/'STOP').exists():
        (outdir/'STOP').replace(outdir/('STOP.acknowledged-'+str(time.time_ns())))

    def pause_at_boundary():
        storage = storage_check(plan['storage_reserves'])
        if not storage['ok']:
            atomic_json(outdir/'STOP', {'reason': 'storage_reserve', **storage})
            print('PAUSED: storage reserve unavailable', file=sys.stderr)
            return True
        if (outdir/'STOP').exists():
            print('PAUSED: operator stop marker', file=sys.stderr)
            return True
        return False

    for arm in arms:
        exclude = "--exclude-tools read_files" if arm == "without" else None
        written: list[Path] = []
        for seed in seeds:
            if pause_at_boundary():
                return 75
            out = outdir / f"{arm}_seed{seed}.json"
            written.append(out)
            if out.exists():
                try:
                    payload = json.loads(out.read_text(encoding='utf-8'))
                    identity = validate_run(payload)
                    if (identity['collection_id'] != args.tag or identity['seeds'] != [seed]
                            or identity['evidence']['fingerprint'] != plan['candidate_fingerprint']
                            or identity['binary_sha256'] != plan['binary_sha256']
                            or identity.get('storage_reserves') != plan['storage_reserves']
                            or any(identity[k] != plan[k] for k in ('model','api_base','tasks','conditions','max_turns','max_tokens','temperature'))
                            or identity.get('repeat_call_limit', 0) != plan['repeat_call_limit']
                            or identity['caps'] != harness.ACI_CAPABILITIES or identity['repeat'] != 1
                            or identity.get('task_set')!=plan['task_set'] or identity.get('prompt_variant')!=args.prompt_variant
                            or identity.get('schedule_sha256') != plan.get('schedule_sha256')
                            or identity.get('analysis_plan_sha256') != plan.get('analysis_plan_sha256')
                            or identity['exclude_tools'] != (['read_files'] if arm == 'without' else [])):
                        raise ValueError('output does not belong to this collection')
                except ValueError as exc:
                    print(f'ERROR: cannot reuse {out.name}: {exc}', file=sys.stderr)
                    return 2
                print(f"reuse validated {out}; retain all outcomes", flush=True)
                continue
            cmd = [
                sys.executable, str(RUNNER),
                "--tasks", ",".join(task_ids),
                "--conditions", args.conditions,
                "--model", model,
                "--base-url", env["ACI_BENCH_BASE_URL"],
                "--api-key", env["ACI_BENCH_API_KEY"],
                "--max-turns", str(args.max_turns),
                "--max-tokens", str(args.max_tokens),
                "--repeat-call-limit", str(args.repeat_call_limit),
                "--temperature", "0",
                "--seed", str(seed),
                "--collection-id", args.tag,
                '--task-set',str(args.task_set),'--prompt-variant',args.prompt_variant,
                "--out", str(out),
            ]
            if exclude:
                cmd += exclude.split()
            if schedule:
                cmd += ['--schedule', str(outdir/'schedule.json')]
            if args.analysis_plan:
                cmd += ['--analysis-plan',str(args.analysis_plan)]
            if args.resume_paused:cmd.append('--resume-paused')
            rc = run(f"{arm} seed={seed}", cmd)
            if rc != 0:
                print(f"ERROR: shard {arm}/{seed} exited {rc}; checkpoint preserved", flush=True)
                return rc

        if pause_at_boundary():
            return 75
        merged = (RESULTS if args.publish else outdir) / ("latest_live.json" if arm == "with"
                            else "live_ab_without_read_files.json")
        rc = run(f"merge {arm} -> {merged.name}",
                 [sys.executable, str(MERGER), "--out", str(merged),
                  *(['--allow-api-errors'] if any(has_api_error(p) for p in written) else []), *map(str, written)])
        if rc != 0:
            print(f"MERGE FAILED for arm {arm} (exit {rc}); fix the api_error cells and re-run.",
                  flush=True)
            return rc

    if pause_at_boundary():
        return 75
    print(f"\n[{time.strftime('%H:%M:%S')}] round {args.tag} complete", flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(add_help=False, allow_abbrev=False);parser.add_argument('--tag')
    args,_=parser.parse_known_args()
    if not args.tag or '-h' in sys.argv or '--help' in sys.argv:return _main()
    outdir=RESULTS/args.tag
    if outdir.resolve().parent!=RESULTS.resolve():return _main()
    try:
        with RunStatus(outdir/'round.status.json') as observer:
            observer.update(control_generation_id=os.environ.get('ACI_CONTROL_GENERATION_ID'))
            code=_main()
            observer.update(state=('planned' if '--dry-run' in sys.argv else 'completed') if code==0 else ('paused' if code==75 else 'failed'),exit_code=code,finished_at=utc_now())
            return code
    except RuntimeError as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 2


if __name__ == "__main__":
    sys.exit(main())
