"""Conservative paired delta intervals for crossed run/task samples.

Keep the original estimand. Allocate alpha/2 to each crossed margin and add
their Student-t radii (do not pretend seed rows are independent). These are
calibrated approximations, not distribution-free finite-sample guarantees.
"""
import math
import statistics
from functools import lru_cache


def _beta_fraction(a, b, x):
    # Continued fraction for the regularized incomplete beta, with a tiny
    # denominator guard. This avoids an optional scipy dependency in the CLI.
    qab=a+b; qap=a+1; qam=a-1; c=1.; d=1-qab*x/qap
    tiny=1e-300
    if abs(d)<tiny:d=tiny
    d=1/d; h=d
    for m in range(1,301):
        m2=2*m; aa=m*(b-m)*x/((qam+m2)*(a+m2))
        d=1+aa*d; c=1+aa/c
        if abs(d)<tiny:d=tiny
        if abs(c)<tiny:c=tiny
        d=1/d; h*=d*c
        aa=-(a+m)*(qab+m)*x/((a+m2)*(qap+m2))
        d=1+aa*d; c=1+aa/c
        if abs(d)<tiny:d=tiny
        if abs(c)<tiny:c=tiny
        d=1/d; change=d*c; h*=change
        if abs(change-1)<3e-14:return h
    raise ValueError('incomplete beta did not converge')


def _regularized_beta(x, a, b):
    if x<=0:return 0.
    if x>=1:return 1.
    factor=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    if x<(a+1)/(a+b+2):return factor*_beta_fraction(a,b,x)/a
    return 1-factor*_beta_fraction(b,a,1-x)/b


@lru_cache(maxsize=128)
def t_critical(df, two_sided_alpha):
    if df<1 or not 0<two_sided_alpha<1:raise ValueError('invalid t parameters')
    def tail(t):return _regularized_beta(df/(df+t*t),df/2,.5)
    low=0.; high=1.
    while tail(high)>two_sided_alpha:high*=2
    for _ in range(70):
        middle=(low+high)/2
        if tail(middle)>two_sided_alpha:low=middle
        else:high=middle
    return (low+high)/2


def effect_and_influence(matrix, kind):
    r=len(matrix); t=len(matrix[0]) if r else 0
    if r<3 or t<2 or any(len(row)!=t for row in matrix):raise ValueError('need 3 complete runs and 2 tasks')
    if any(len(c)!=4 or any(not isinstance(x,(int,float)) or not math.isfinite(x) or x<0 for x in c)
           for row in matrix for c in row):raise ValueError('invalid/nonfinite sufficient statistics')
    active=[j for j in range(t) if any(any(matrix[i][j]) for i in range(r))]
    if len(active)<2 or any(not any(any(c) for c in row) for row in matrix):
        raise ValueError('insufficient informative run/task clusters')
    matrix=[[row[j] for j in active] for row in matrix];t=len(active)
    a,wa,d,wd=[sum(c[k] for row in matrix for c in row)/(r*t) for k in range(4)]
    if not wa or not wd:raise ValueError('undefined success/observation denominator')
    if kind=='difference':
        point=d/wd-a/wa
        influence=[[(c[2]-d/wd*c[3])/wd-(c[0]-a/wa*c[1])/wa for c in row] for row in matrix]
    elif kind=='ratio':
        if not a or not d:raise ValueError('zero cost cannot support log-ratio inference')
        point=d*wa/(wd*a)
        influence=[[(c[2]/d-c[3]/wd)-(c[0]/a-c[1]/wa) for c in row] for row in matrix]
    else:raise ValueError('unknown effect kind')
    return point,influence


def from_influence(point, influence, *, log_scale=False, alpha=.05):
    r=len(influence);t=len(influence[0])
    run_means=[statistics.fmean(row) for row in influence]
    task_means=[statistics.fmean(influence[i][j] for i in range(r)) for j in range(t)]
    run_se=statistics.stdev(run_means)/math.sqrt(r)
    task_se=statistics.stdev(task_means)/math.sqrt(t)
    radius=t_critical(r-1,alpha/2)*run_se+t_critical(t-1,alpha/2)*task_se
    if log_scale:
        center=math.log(point)
        low=math.exp(center-radius) if center-radius>-745 else 0.
        high=math.exp(center+radius) if center+radius<709 else None
    else:low,high=point-radius,point+radius
    return {'available':high is not None,'point_estimate':point,'headline_ci95':[low,high],
            'confidence_level':1-alpha,
            'method':'crossed_axis_t_union/v1','alpha':alpha,'margin_alpha':alpha/2,
            'degrees_of_freedom':{'run':r-1,'task':t-1},'standard_errors':{'run':run_se,'task':task_se},
            'scale':'log ratio' if log_scale else 'difference','claimable':False,
            'assumptions':'exchangeable independent run/task margins; delta linearization; finite moments; calibrated, not exact'}


def summarize(matrix, kind, alpha=.05):
    try:
        point,influence=effect_and_influence(matrix,kind)
        return from_influence(point,influence,log_scale=kind=='ratio',alpha=alpha)
    except ValueError as error:return {'available':False,'reason':str(error),'claimable':False}


def interaction(first,second,kind,alpha=.05):
    try:
        if len(first)!=len(second) or any(len(x)!=len(y) for x,y in zip(first,second)):
            raise ValueError('interaction grids differ')
        if first and any(any(any(row[j]) for row in first)!=any(any(row[j]) for row in second) for j in range(len(first[0]))):
            raise ValueError('interaction informative task sets differ')
        a,ia=effect_and_influence(first,kind);b,ib=effect_and_influence(second,kind)
        if len(ia)!=len(ib) or any(len(x)!=len(y) for x,y in zip(ia,ib)):
            raise ValueError('interaction grids differ')
        # Ratio influences are on log scale; convert back before subtracting
        # effects. Both variants keep the same run/task identities.
        z=[[yb*(b if kind=='ratio' else 1)-ya*(a if kind=='ratio' else 1)
            for ya,yb in zip(x,y)] for x,y in zip(ia,ib)]
        return from_influence(b-a,z,alpha=alpha)
    except ValueError as error:return {'available':False,'reason':str(error),'claimable':False}
