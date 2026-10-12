#!/usr/bin/env python3
"""Crossed run/task bootstrap for a pre-registered complete repeated-run study.

Reads stored artifacts only. It never collects data or changes existing claims.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import itertools
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from live_uncertainty import row_class, row_policy, valid_usage
from report_inputs import select_prompt_variant
from crossed_inference import summarize as axis_summary, interaction as axis_interaction

CONFIG_KEYS = ('model','api_base','caps','max_turns','max_tokens','temperature','exclude_tools')
METRICS = {
    'success_delta': ('difference', ()),
    'tool_call_ratio': ('ratio', ('tool_calls',)),
    'observation_token_ratio': ('ratio', ('observation_tokens',)),
    'usage_token_ratio': ('ratio', ('llm_prompt_tokens','llm_completion_tokens')),
    'prompt_token_ratio': ('ratio', ('llm_prompt_tokens',)),
    'completion_token_ratio': ('ratio', ('llm_completion_tokens',)),
    'usage_mean_of_ratios': ('difference', ('llm_prompt_tokens', 'llm_completion_tokens')),
    'observation_mean_of_ratios': ('difference', ('observation_tokens',)),
    'observation_cost_per_success': ('ratio', ('observation_tokens',)),
    'usage_cost_per_success': ('ratio', ('llm_prompt_tokens', 'llm_completion_tokens')),
}


def load_study(path: Path, *, prompt_variant=None) -> dict:
    manifest_bytes=path.read_bytes()
    spec=json.loads(manifest_bytes.decode('utf-8-sig'))
    task_path=(path.parent/spec['task_manifest']).resolve()
    task_set=json.loads(task_path.read_text(encoding='utf-8-sig'))
    tasks=task_set['tasks']; seeds=spec['seeds']; conditions=spec['conditions']
    indices=spec.get('run_indices',[0]); entries=spec['runs']
    for label, values in [('tasks',tasks),('seeds',seeds),('conditions',conditions),('run_indices',indices)]:
        if not values or len(values)!=len(set(values)):
            raise ValueError(f'{label} must be nonempty and unique')
    if len(tasks)<2 or len(entries)<3:
        raise ValueError('need at least three complete runs and two tasks')
    if not {'raw_shell','verseshell_aci'} <= set(conditions):
        raise ValueError('study must contain raw_shell and verseshell_aci')
    if not set(conditions)<= {'raw_shell','raw_shell_coached','verseshell_aci'}:
        raise ValueError('unsupported condition')
    expected=set(itertools.product(tasks,conditions,seeds,indices))
    runs=[]; sources=[]; ids=set(); paths=set(); hashes=set(); reference=None
    for entry in entries:
        run_id=entry['run_id']; artifact=(path.parent/entry['artifact']).resolve()
        raw=artifact.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
        if not isinstance(run_id,str) or not run_id or run_id in ids or artifact in paths or digest in hashes:
            raise ValueError('duplicate run identity, artifact path or identical artifact bytes')
        ids.add(run_id);paths.add(artifact);hashes.add(digest)
        original=json.loads(raw.decode('utf-8-sig'))
        declared_variants=original.get('live_config', {}).get('prompt_variants')
        if declared_variants:
            full_keys=[(row.get('task_id'), row.get('condition'), row.get('seed'), row.get('run_index'), row.get('prompt_variant'))
                       for row in original.get('rows', [])]
            full_expected={(*key,v) for key in expected for v in declared_variants}
            if len(full_keys)!=len(set(full_keys)) or set(full_keys)!=full_expected:
                raise ValueError(f'{run_id}: incomplete/different variant grid')
        payload=select_prompt_variant(original, prompt_variant or spec.get('prompt_variant'))
        cfg=payload.get('live_config') or {}
        if payload.get('mode')!='live' or payload.get('task_set_version')!=task_set.get('task_set_version'):
            raise ValueError(f'{run_id}: mode/task-set version mismatch')
        if any(key not in cfg or cfg[key] is None for key in CONFIG_KEYS):
            raise ValueError(f'{run_id}: incomplete replay configuration')
        repeat_limit = cfg.get('repeat_call_limit', 0)
        if type(repeat_limit) is not int or repeat_limit < 0 or repeat_limit == 1:
            raise ValueError(f'{run_id}: invalid repeat_call_limit')
        fingerprint=(payload.get('evidence') or {}).get('fingerprint')
        if not fingerprint or not payload.get('git_rev'):
            raise ValueError(f'{run_id}: missing source identity')
        signature=({key:cfg[key] for key in CONFIG_KEYS},payload['git_rev'],fingerprint,
                   cfg.get('prompt_variant', 'baseline'), cfg.get('protocol'), cfg.get('prompt_variants'), repeat_limit)
        if reference is None: reference=signature
        elif signature!=reference: raise ValueError(f'{run_id}: configuration/revision/fingerprint differs')
        rows={}
        for row in payload.get('rows',[]):
            seed = row.get('seed') if row.get('seed') is not None else cfg.get('seed')
            key=(row.get('task_id'),row.get('condition'),seed,row.get('run_index'))
            if key in rows: raise ValueError(f'{run_id}: duplicate cell {key}')
            if row.get('model')!=cfg['model']: raise ValueError(f'{run_id}: row model mismatch')
            if (type(row.get('repeat_call_limit', 0)) is not int or row.get('repeat_call_limit', 0) != repeat_limit
                    or (row.get('stop_reason') == 'repeat_call_limit' and not repeat_limit)):
                raise ValueError(f'{run_id}: row repeat_call_limit mismatch')
            rows[key]=row
        if set(rows)!=expected:
            raise ValueError(f'{run_id}: incomplete/different grid; missing={len(expected-set(rows))}, extra={len(set(rows)-expected)}')
        runs.append({'run_id':run_id,'rows':rows,'config':cfg,
                     'partial':bool(payload.get('partial')) or any(row_class(row,cfg['max_turns'])=='endpoint_failure' for row in rows.values()),
                     'synthetic_test_only':bool(payload.get('synthetic_test_only'))})
        sources.append({'run_id':run_id,'path':str(artifact),'sha256':digest})
    return {'tasks':tasks,'seeds':seeds,'indices':indices,'conditions':conditions,'runs':runs,'sources':sources,
            'task_manifest':str(task_path),'task_manifest_sha256':hashlib.sha256(task_path.read_bytes()).hexdigest(),
            'study_manifest':str(path),'study_manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest()}


def variance_components(matrix):
    r=len(matrix); t=len(matrix[0]); grand=sum(map(sum,matrix))/(r*t)
    rm=[sum(row)/t for row in matrix]; tm=[sum(row[j] for row in matrix)/r for j in range(t)]
    msr=t*sum((x-grand)**2 for x in rm)/(r-1)
    mst=r*sum((x-grand)**2 for x in tm)/(t-1)
    mse=sum((matrix[i][j]-rm[i]-tm[j]+grand)**2 for i in range(r) for j in range(t))/((r-1)*(t-1))
    raw_run=(msr-mse)/t; raw_task=(mst-mse)/r
    vr=max(0.0,raw_run); vt=max(0.0,raw_task)
    return {'run_variance':vr,'task_variance':vt,'interaction_residual_variance':mse,
            'unclipped_run_variance':raw_run,'unclipped_task_variance':raw_task,
            'variance_of_mean_parts':{'run':vr/r,'task':vt/t,'interaction_residual':mse/(r*t)},
            'run_degrees_of_freedom':r-1,'task_degrees_of_freedom':t-1,
            'method':'balanced two-way random-effects moments on linearized cell contributions; negative components clipped, raw values retained'}


def estimate(cells,kind):
    a,wa,d,wd=(sum(c[i] for c in cells) for i in range(4))
    if not wa or not wd: return None
    ma,md=a/wa,d/wd
    return md-ma if kind=='difference' else (md/ma if ma else None)


def interval(draws):
    if any(x is None for x in draws): return None
    values=sorted(draws)
    def quantile(p):
        index=(len(values)-1)*p; lower=int(index); upper=min(lower+1,len(values)-1)
        return values[lower]+(values[upper]-values[lower])*(index-lower)
    return [quantile(.025),quantile(.975)]


def metric_cells(study,baseline,view,metric):
    kind,fields=METRICS[metric]; matrix=[]
    for run in study['runs']:
        row=[]
        for task in study['tasks']:
            if metric.endswith('_mean_of_ratios'):
                ratios=[]
                for seed,index in itertools.product(study['seeds'],study['indices']):
                    a,d=(run['rows'][(task,c,seed,index)] for c in (baseline,'verseshell_aci'))
                    if view=='analysable' and any(row_class(c,run['config']['max_turns'])!='analysable' for c in (a,d)):
                        continue
                    if any(c.get('measurement_complete') is False for c in (a,d)):
                        raise ValueError('measurement includes an interrupted unknown attempt')
                    if fields[0].startswith('llm_') and not all(valid_usage(c) for c in (a,d)):
                        raise ValueError('incomplete endpoint usage')
                    values=[[c.get(f) for f in fields] for c in (a,d)]
                    if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for v in values for x in v):
                        raise ValueError('missing ratio inputs')
                    denom=sum(values[0])
                    if denom<=0: raise ValueError('undefined paired ratio: zero baseline')
                    ratios.append(sum(values[1])/denom)
                row.append((0,len(ratios),sum(ratios),len(ratios)))
                continue
            sums=[]
            for condition in (baseline,'verseshell_aci'):
                value=weight=0
                for seed,index in itertools.product(study['seeds'],study['indices']):
                    pair=[run['rows'][(task,c,seed,index)] for c in (baseline,'verseshell_aci')]
                    if view=='analysable' and (
                            any(row_class(c,run['config']['max_turns'])!='analysable' for c in pair)
                            or ((not fields or metric.endswith('_cost_per_success')) and any(c.get('success') is None for c in pair))):
                        continue
                    cell=run['rows'][(task,condition,seed,index)]
                    eligible=row_class(cell,run['config']['max_turns'])=='analysable'
                    if view=='analysable' and not eligible: continue
                    if not fields:
                        if view=='analysable' and cell.get('success') is None: continue
                        if eligible and cell.get('success') is None:
                            raise ValueError('unverified success; not a capability failure')
                        amount=float(eligible and cell.get('success') is True)
                    else:
                        if cell.get('measurement_complete') is False:
                            raise ValueError('measurement includes an interrupted unknown attempt')
                        if fields[0].startswith('llm_') and not valid_usage(cell):
                            raise ValueError('incomplete endpoint usage; no zero imputation')
                        values=[cell.get(field) for field in fields]
                        if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in values):
                            raise ValueError(f'missing/invalid {fields}; no zero imputation')
                        amount=sum(values)
                    value+=amount
                    if metric.endswith('_cost_per_success'):
                        if cell.get('success') is None and eligible:
                            raise ValueError('unverified success denominator')
                        weight+=int(eligible and cell.get('success') is True)
                    else:
                        weight+=1
                sums.extend((value,weight))
            row.append(tuple(sums))
        matrix.append(row)
    return matrix


def summarize(matrix,kind,draws,seed,alpha=.05):
    r,t=len(matrix),len(matrix[0]); flat=[c for row in matrix for c in row]
    point=estimate(flat,kind)
    if point is None: return {'available':False,'reason':'undefined denominator or no eligible rows'}
    rng=random.Random(seed); distributions={'crossed':[],'task_only':[],'run_only':[]}
    for _ in range(draws):
        rr=[rng.randrange(r) for _ in range(r)]; tt=[rng.randrange(t) for _ in range(t)]
        distributions['crossed'].append(estimate([matrix[i][j] for i in rr for j in tt],kind))
        distributions['task_only'].append(estimate([matrix[i][j] for i in range(r) for j in tt],kind))
        distributions['run_only'].append(estimate([matrix[i][j] for i in rr for j in range(t)],kind))
    a,wa,d,wd=(sum(c[i] for c in flat) for i in range(4));ma,md=a/wa,d/wd
    mwa,mwd=wa/(r*t),wd/(r*t)
    def influence(c):
        ia=(c[0]-ma*c[1])/mwa; id_=(c[2]-md*c[3])/mwd
        return id_-ia if kind=='difference' else id_/ma-md*ia/(ma*ma)
    components=variance_components([[influence(c) for c in row] for row in matrix])
    ci = interval(distributions['crossed'])
    studentized=axis_summary(matrix,kind,alpha)
    return {'available':ci is not None and studentized['available'],'point_estimate':point,
            'headline_ci95':studentized.get('headline_ci95') if ci is not None else None, 'inference':studentized,
            'legacy_percentile_ci95':ci,
            'bootstrap_unit':'crossed complete run and task; seeds/run_indices remain paired fixed strata',
            'diagnostic_task_only_ci95':interval(distributions['task_only']),
            'diagnostic_run_only_ci95':interval(distributions['run_only']),
            'undefined_draws':{k:sum(v is None for v in values) for k,values in distributions.items()},
            'variance_components':components,'variance_scale':'delta-method linearization' if kind=='ratio' else 'mean-difference linearization'}


def analyse(study,draws=4000,seed=42,alpha=.05):
    if type(draws) is not int or draws<1: raise ValueError('bootstrap draws must be positive')
    comparisons={}
    for baseline in ('raw_shell','raw_shell_coached'):
        if baseline not in study['conditions']: continue
        policies=[row_policy(list(run['rows'].values()),study['conditions'],run['config']['max_turns'],[(baseline,'verseshell_aci')]) for run in study['runs']]
        views={}
        for view in ('analysable','intention_to_treat'):
            metrics={}
            for index,(metric,(kind,_)) in enumerate(METRICS.items()):
                try: metrics[metric]=summarize(metric_cells(study,baseline,view,metric),kind,draws,seed+index,alpha)
                except ValueError as error: metrics[metric]={'available':False,'reason':str(error)}
            views[view]=metrics
        name='verseshell_aci_vs_'+baseline
        comparisons[name]={'views':views,'per_run_row_policy':policies,
            'row_policy_eligible':all(p['comparisons'][name]['claimable'] for p in policies) and not any(r['partial'] for r in study['runs']),
            'claimable':False,'claim_decision':'interval analysis only; does not replace preregistered power, multiplicity and independent acceptance checks'}
    return {'schema':'verseshell.repeated-run-uncertainty/v1','generated_at':datetime.now(timezone.utc).isoformat(),
            'sources':study['sources'],'task_manifest':study['task_manifest'],'task_manifest_sha256':study['task_manifest_sha256'],
            'complete_runs':len(study['runs']),'tasks':len(study['tasks']),'seeds':study['seeds'],
            'run_indices':study['indices'],'conditions':study['conditions'],
            'study_manifest':study['study_manifest'],'study_manifest_sha256':study['study_manifest_sha256'],
            'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'inference_sha256':hashlib.sha256(Path(__file__).with_name('crossed_inference.py').read_bytes()).hexdigest(),
            'row_policy_sha256':hashlib.sha256(Path(__file__).with_name('live_uncertainty.py').read_bytes()).hexdigest(),
            'method':{'draws':draws,'seed':seed,'sampling':'run and task indices sampled independently; same task sample used across all selected runs',
                      'assumptions':'exchangeable independent collections and tasks, balanced original grid; fixed seeds are not treated as independent collection replicates',
                      'limitations':'three collections give only two run degrees of freedom; neither bootstrap coverage nor variance magnitude is guaranteed; these are not lower bounds. File checks cannot prove independent endpoint collection.'},
            'comparisons':comparisons}


def interaction_interval(first, second, kind, draws=4000, seed=42, alpha=.05):
    """Difference of paired effects with the SAME run/task bootstrap draw."""
    r,t=len(first),len(first[0])
    if draws<1 or len(second)!=r or any(len(row)!=t for row in first+second):
        raise ValueError('invalid interaction matrices/draw count')
    def effect(rr,tt):
        a=estimate([first[i][j] for i in rr for j in tt],kind)
        b=estimate([second[i][j] for i in rr for j in tt],kind)
        return None if a is None or b is None else b-a
    point=effect(range(r),range(t));rng=random.Random(seed);values=[]
    for _ in range(draws):
        rr=[rng.randrange(r) for _ in range(r)];tt=[rng.randrange(t) for _ in range(t)]
        values.append(effect(rr,tt))
    ci=interval(values)
    studentized=axis_interaction(first,second,kind,alpha)
    return {'point_estimate':point,'headline_ci95':studentized.get('headline_ci95') if ci is not None else None,
            'inference':studentized,'legacy_percentile_ci95':ci,
            'available':point is not None and ci is not None and studentized['available'],
            'undefined_draws':sum(v is None for v in values),'bootstrap_unit':'synchronized run and task',
            'effect_scale':'second variant effect minus first variant effect',
            'claimable':False,'p_value':None,'inference_status':'diagnostic; calibration and prospective family required'}


def analyse_interaction(path,draws=4000,seed=42,alpha=.05):
    if type(draws) is not int or draws<1:raise ValueError('bootstrap draws must be positive')
    variants=('baseline','compact_all')
    studies=[load_study(path,prompt_variant=v) for v in variants]
    if studies[0]['sources']!=studies[1]['sources']:
        raise ValueError('variant sources changed while loading')
    for study in studies:
        if any(not set(variants)<=set(run['config'].get('prompt_variants',[]))
               or not run['config'].get('schedule_sha256') for run in study['runs']):
            raise ValueError('interaction requires a frozen joint variant schedule')
    comparisons={}
    for baseline in ('raw_shell','raw_shell_coached'):
        if baseline not in studies[0]['conditions']:continue
        views={}
        for view in ('analysable','intention_to_treat'):
            paired=copy.deepcopy(studies);excluded=0
            if view=='analysable':
                for run_index in range(len(paired[0]['runs'])):
                    for task,seed_value,index in itertools.product(paired[0]['tasks'],paired[0]['seeds'],paired[0]['indices']):
                        cells=[s['runs'][run_index]['rows'][(task,c,seed_value,index)]
                               for s in paired for c in (baseline,'verseshell_aci')]
                        cap=paired[0]['runs'][run_index]['config']['max_turns']
                        if any(row_class(c,cap)!='analysable' or c.get('success') is None for c in cells):
                            excluded+=1
                            for c in cells:c['harness_fault']='interaction_common_support_excluded'
            metrics={}
            for offset,(metric,(kind,_)) in enumerate(METRICS.items()):
                try:
                    matrices=[metric_cells(s,baseline,view,metric) for s in paired]
                    metrics[metric]=interaction_interval(*matrices,kind,draws,seed+offset,alpha)
                except ValueError as error:
                    metrics[metric]={'available':False,'reason':str(error),'claimable':False}
            views[view]={'metrics':metrics,'excluded_task_seed_pairs':excluded,
                         'support':'same four cells per task/seed/run for both variants and conditions'}
        comparisons[baseline]={'views':views,'claimable':False}
    study=studies[0]
    return {'schema':'verseshell.variant-interaction/v1','generated_at':datetime.now(timezone.utc).isoformat(),
            'variants':list(variants),'contrast':'(D versus baseline under compact_all) minus (D versus baseline under baseline)',
            'sources':study['sources'],'complete_runs':len(study['runs']),'tasks':len(study['tasks']),
            'partial':any(run['partial'] for run in study['runs']),
            'study_manifest':study['study_manifest'],'study_manifest_sha256':study['study_manifest_sha256'],
            'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'inference_sha256':hashlib.sha256(Path(__file__).with_name('crossed_inference.py').read_bytes()).hexdigest(),
            'comparisons':comparisons,'claimable':False,
            'interpretation':'description-treatment interaction on the declared effect scale, not a universal interface or pure-length effect'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--draws',type=int,default=4000);parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--interaction',action='store_true',help='synchronized baseline/compact_all interaction')
    args=parser.parse_args(argv)
    try:
        report=(analyse_interaction(args.manifest.resolve(),args.draws,args.seed) if args.interaction
                else analyse(load_study(args.manifest.resolve()),args.draws,args.seed))
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(f'ERROR: {error}',file=sys.stderr);return 2
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f"analysed {report['complete_runs']} complete runs x {report['tasks']} tasks; no claim approval")
    return 0


if __name__=='__main__': sys.exit(main())
