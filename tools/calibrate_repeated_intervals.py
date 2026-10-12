"""Reproducible synthetic coverage screen; never evidence of a model effect."""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from live_uncertainty import wilson
from repeated_run_uncertainty import summarize, interaction_interval
from crossed_inference import summarize as axis_summary, interaction as axis_interaction


def simulate(rng, runs, tasks, run_sd, task_sd, noise_sd, base_sd):
    bases=[math.exp(rng.gauss(4,base_sd)) for _ in range(tasks)]
    task_effects=[rng.gauss(0,task_sd) for _ in range(tasks)]
    result=[]
    correction=(run_sd**2+task_sd**2+noise_sd**2)/2
    for _ in range(runs):
        run_effect=rng.gauss(0,run_sd)
        result.append([(a,1,a*math.exp(run_effect+task_effects[j]+rng.gauss(0,noise_sd)-correction),1)
                       for j,a in enumerate(bases)])
    return result


def joint_controls(repetitions, tasks, runs, seed):
    rng=random.Random(seed);counts={k:[0,0] for k in ('cpst','success_delta','interaction')}
    for _ in range(repetitions):
        task_noise=[rng.uniform(-.15,.15) for _ in range(tasks)]
        bases=[math.exp(rng.gauss(4,1)) for _ in range(tasks)]
        matrix=[];success=[];second=[]
        for i in range(runs):
            run_noise=rng.uniform(-.2,.2);cost_noise=rng.gauss(0,.5);variant_noise=rng.uniform(-.2,.2)
            row=[];success_row=[];second_row=[]
            for j in range(tasks):
                ca=cd=sa=sd=0
                for _ in range(5):
                    u=rng.random();sa+=u<.5;sd+=u<.5+run_noise+task_noise[j]
                    cost=bases[j]*math.exp(rng.gauss(0,.3)-.3**2/2)
                    ca+=cost;cd+=cost*math.exp(cost_noise-.5**2/2)
                row.append((ca,sa,cd,sd));success_row.append((sa,5,sd,5))
                second_row.append((ca,sa,cd*(1+variant_noise+rng.uniform(-.1,.1)),sd))
            matrix.append(row);success.append(success_row);second.append(second_row)
        for key,result,target in [('cpst',axis_summary(matrix,'ratio'),1),
                                  ('success_delta',axis_summary(success,'difference'),0),
                                  ('interaction',axis_interaction(matrix,second,'ratio'),0)]:
            if not result['available']:counts[key][1]+=1
            else:
                lo,hi=result['headline_ci95'];counts[key][0]+=not lo<=target<=hi
    return {k:{'null_rejections':n,'unavailable':u,'replications':repetitions,
               'mc95':list(wilson(n,repetitions))} for k,(n,u) in counts.items()}


def calibrate(repetitions=200, draws=400, tasks=24, runs=3, seed=42, method='bootstrap'):
    if repetitions<1 or draws<1 or tasks<2 or runs<3:
        raise ValueError('positive repetitions/draws, at least 2 tasks and 3 runs required')
    rng=random.Random(seed);results={}
    if method not in ('bootstrap','axis_t'):raise ValueError('unknown calibration method')
    scenarios={
        'independent_skew': (0,.0,.4,1),
        'strong_run_correlation': (.5,.15,.1,1),
        'heavy_tailed_tasks': (.1,.2,1.1,2),
    }
    for name,parameters in scenarios.items():
        rejected=unavailable=0
        for index in range(repetitions):
            matrix=simulate(rng,runs,tasks,*parameters)
            result=axis_summary(matrix,'ratio') if method=='axis_t' else summarize(matrix,'ratio',draws,seed+index)
            if method=='bootstrap':
                result={**result,'headline_ci95':result.get('legacy_percentile_ci95',result.get('headline_ci95'))}
            ci=result.get('headline_ci95')
            if not result['available']: unavailable+=1
            elif not ci[0]<=1<=ci[1]: rejected+=1
        results[name]={'population_ratio':1,'repetitions':repetitions,'unavailable':unavailable,
                       'zero_effect_rejected':rejected,'rejection_fraction_all':rejected/repetitions,
                       'rejection_fraction_ci95_mc':list(wilson(rejected,repetitions)),
                       'conditional_rejection_fraction':rejected/(repetitions-unavailable) if repetitions>unavailable else None}
    # A common random effect must cancel exactly under synchronized resampling.
    matrix=simulate(rng,runs,tasks,.5,.2,.1,1)
    paired=interaction_interval(matrix,matrix,'ratio',draws,seed)
    empty=summarize([[(10,1,5,0) for _ in range(tasks)] for _ in range(runs)],'ratio',draws,seed)
    return {'schema':'verseshell.interval-calibration-screen/v1','synthetic_only':True,
            'configuration':{'runs':runs,'tasks':tasks,'draws':draws,'repetitions':repetitions,'seed':seed,'method':method},
            'scenarios':results,'controls':{'identical_variant_interaction':paired,'zero_success_denominator':empty},
            'claimable':False,'calibration_approved':False,
            'interpretation':'Monte Carlo screening of declared lognormal null populations. Does not validate coverage for arbitrary live data or approve a confirmatory family.',
            'limitations':['Three complete runs leave only two run degrees of freedom.',
                           'Monte Carlo uncertainty is reported; no favorable scenarios or seeds are selected.',
                           'Missing-data mechanisms and adversarial grading require separate controls.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=200);parser.add_argument('--draws',type=int,default=400)
    parser.add_argument('--tasks',type=int,default=24);parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--method',choices=['bootstrap','axis_t'],default='bootstrap')
    parser.add_argument('--extended',action='store_true',help='paired CPST, success and interaction null controls')
    args=parser.parse_args(argv)
    report=calibrate(args.repetitions,args.draws,args.tasks,args.runs,args.seed,args.method)
    if args.extended:
        if args.method!='axis_t':parser.error('--extended requires --method axis_t')
        report['joint_controls']=joint_controls(args.repetitions,args.tasks,args.runs,args.seed+1)
        report['calibration_approved']=(all(r['unavailable']==0 and r['rejection_fraction_ci95_mc'][1]<.05
                                           for r in report['scenarios'].values())
                                        and all(r['unavailable']==0 and r['mc95'][1]<.05
                                                for r in report['joint_controls'].values()))
        report['approval_scope']='specified synthetic nulls only; not universal coverage or model acceptance'
    report['source_sha256']={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                            for name in ('calibrate_repeated_intervals.py','repeated_run_uncertainty.py','live_uncertainty.py','crossed_inference.py')}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    for name,r in report['scenarios'].items():
        print(f"{name}: null rejected {r['zero_effect_rejected']}/{r['repetitions']}; unavailable={r['unavailable']}; MC95={r['rejection_fraction_ci95_mc']}")
    print('Synthetic diagnostic only; confirmatory claims remain blocked')
    return 0


if __name__=='__main__':raise SystemExit(main())
