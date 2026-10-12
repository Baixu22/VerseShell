"""Prospective, frozen family evaluation; historical rows cannot be recertified."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from crossed_inference import summarize as axis_summary
from repeated_run_uncertainty import load_study, metric_cells, analyse_interaction, METRICS
from live_uncertainty import comparison_eligibility

ROOT=Path(__file__).resolve().parents[1]
ANALYSIS_SOURCES=('tools/crossed_inference.py','tools/repeated_run_uncertainty.py',
                  'tools/study_inference.py','tools/live_uncertainty.py','tools/report_inputs.py')


def read_plan(path):
    plan=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if plan.get('schema')!='verseshell.analysis-plan/v1' or plan.get('method')!='crossed_axis_t_union/v1':
        raise ValueError('unsupported prospective analysis plan')
    if not 0<plan.get('alpha',0)<=.05:raise ValueError('invalid family alpha')
    for name,minimum in [('minimum_tasks',30),('minimum_seeds',5),('minimum_complete_runs',3)]:
        if type(plan.get(name)) is not int or plan[name]<minimum:raise ValueError(f'{name} below preregistered floor')
    hypotheses=plan.get('hypotheses',[])
    ids=[h.get('id') for h in hypotheses]
    if not ids or not all(isinstance(i,str) and i for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('empty/duplicate hypothesis family')
    for h in hypotheses:
        if (h.get('baseline') not in ('raw_shell','raw_shell_coached') or h.get('metric') not in METRICS
                or h.get('kind') not in ('variant','interaction')
                or h.get('rule') not in ('upper_below','lower_above','excludes_zero')):
            raise ValueError('unsupported hypothesis')
        if h['kind']=='variant' and h.get('variant') not in ('baseline','compact_all'):
            raise ValueError('hypothesis lacks supported variant')
        if h['rule']!='excludes_zero' and (type(h.get('threshold')) not in (int,float) or not math.isfinite(h['threshold'])):
            raise ValueError('hypothesis threshold missing')
        if set(h.get('requires',[]))-set(ids) or h['id'] in h.get('requires',[]):
            raise ValueError('invalid hypothesis prerequisite')
    pending={h['id']:set(h.get('requires',[])) for h in hypotheses};resolved=set()
    while pending:
        ready={k for k,v in pending.items() if v<=resolved}
        if not ready:raise ValueError('cyclic hypothesis prerequisites')
        for key in ready:pending.pop(key)
        resolved|=ready
    recorded=plan.get('analysis_code_sha256') or {}
    if set(recorded)!=set(ANALYSIS_SOURCES):raise ValueError('analysis source manifest missing or incomplete')
    for name in ANALYSIS_SOURCES:
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=recorded[name]:
            raise ValueError(f'analysis implementation changed: {name}; freeze a new study plan')
    return plan


def evaluate(manifest,plan_path,calibration_paths,draws=4000):
    plan=read_plan(plan_path);plan_hash=hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()
    current_inference=hashlib.sha256(Path(__file__).with_name('crossed_inference.py').read_bytes()).hexdigest()
    calibrations=[]
    for path in calibration_paths:
        c=json.loads(Path(path).read_text(encoding='utf-8'))
        if (not c.get('calibration_approved') or c.get('configuration',{}).get('method')!='axis_t'
                or c.get('configuration',{}).get('repetitions',0)<1000
                or c.get('source_sha256',{}).get('crossed_inference.py')!=current_inference):
            raise ValueError('calibration is missing, stale, or failed')
        if (not c.get('scenarios') or not c.get('joint_controls')
                or any(r.get('unavailable')!=0 or r['rejection_fraction_ci95_mc'][1]>=.05 for r in c['scenarios'].values())
                or any(r.get('unavailable')!=0 or r['mc95'][1]>=.05 for r in c['joint_controls'].values())):
            raise ValueError('calibration evidence contradicts approval label')
        calibrations.append(c)
    if not calibrations:raise ValueError('calibration evidence required')
    alpha=plan['alpha']/len(plan['hypotheses']);studies={};interactions=None;verdicts={}
    variants={h['variant'] for h in plan['hypotheses'] if h['kind']=='variant'}|{'baseline','compact_all'}
    for variant in variants:
        studies[variant]=load_study(Path(manifest).resolve(),prompt_variant=variant)
        if (len(studies[variant]['tasks'])<plan['minimum_tasks'] or len(studies[variant]['seeds'])<plan['minimum_seeds']
                or len(studies[variant]['runs'])<plan['minimum_complete_runs']):
            raise ValueError('study grid does not meet frozen sample-size floors')
        if len(studies[variant]['runs']) not in {c['configuration']['runs'] for c in calibrations}:
            raise ValueError('run count has no supplied calibration')
        for run in studies[variant]['runs']:
            if run['config'].get('analysis_plan_sha256')!=plan_hash:
                raise ValueError('analysis plan was not frozen into acquisition; historical data are diagnostic only')
    for h in plan['hypotheses']:
        views={};eligible=True;row_eligible=True;reasons=[]
        if h['kind']=='interaction' and interactions is None:
            interactions=analyse_interaction(Path(manifest).resolve(),draws,42,alpha)
        relevant=(studies.values() if h['kind']=='interaction' else [studies[h['variant']]])
        for study in relevant:
            for run in study['runs']:
                policy=comparison_eligibility(list(run['rows'].values()), h['baseline'],
                    run['config']['max_turns'], partial=run['partial'],
                    synthetic=bool(run.get('synthetic_test_only')))
                eligible=eligible and policy['data_eligible']
                row_eligible=row_eligible and policy['row_policy_eligible']
                reasons.extend(policy['policy_blocked_reasons'])
        for view in ('analysable','intention_to_treat'):
            try:
                if h['kind']=='variant':
                    matrix=metric_cells(studies[h['variant']],h['baseline'],view,h['metric'])
                    result=axis_summary(matrix,METRICS[h['metric']][0],alpha)
                else:
                    result=interactions['comparisons'][h['baseline']]['views'][view]['metrics'][h['metric']]
                ci=result.get('headline_ci95');passed=False
                if result.get('available') and ci and all(x is not None for x in ci):
                    passed=(ci[1]<h['threshold'] if h['rule']=='upper_below' else
                            ci[0]>h['threshold'] if h['rule']=='lower_above' else ci[0]>0 or ci[1]<0)
                views[view]={'interval':ci,'point':result.get('point_estimate'),'available':result.get('available',False),'passes':bool(passed)}
            except ValueError as error:views[view]={'available':False,'passes':False,'reason':str(error)}
        verdicts[h['id']]={'claimable':bool(eligible and all(v['passes'] for v in views.values())),
                           'row_policy_eligible':bool(row_eligible), 'data_eligible':bool(eligible),
                           'views':views,'requires':h.get('requires',[]),
                           'policy_blocked_reasons':sorted(set(reasons + [
                               'family_interval_not_passed:' + view for view, result in views.items()
                               if not result['passes']]))}
    # Prerequisites only demote, and a cycle can never generate permission.
    for _ in verdicts:
        for value in verdicts.values():
            value['claimable']=value['claimable'] and all(verdicts[k]['claimable'] for k in value['requires'])
    for value in verdicts.values():
        value['policy_blocked_reasons'] += ['prerequisite_not_claimable:' + key
            for key in value['requires'] if not verdicts[key]['claimable']]
    return {'schema':'verseshell.prospective-inference/v1','analysis_plan_sha256':plan_hash,
            'family_size':len(verdicts),'family_alpha':plan['alpha'],'per_hypothesis_alpha':alpha,
            'method':plan['method'],'source_inference_sha256':current_inference,
            'sources':studies['baseline']['sources'],'calibration_scope':'specified simulation scenarios; approximations and assumptions remain',
            'verdicts':verdicts}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--calibration',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--draws',type=int,default=4000);args=p.parse_args(argv)
    try:report=evaluate(args.manifest,args.plan,args.calibration,args.draws)
    except (OSError,ValueError,KeyError) as error:print(f'ERROR: {error}');return 2
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())
