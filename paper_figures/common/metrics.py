"""Ratios of totals, paired comparisons, and exact symmetric decompositions."""
import itertools
import numpy as np
import pandas as pd

def safe_ratio(a,b):
    a,b=np.broadcast_arrays(np.asarray(a,dtype=float),np.asarray(b,dtype=float))
    return np.divide(a,b,out=np.full(a.shape,np.nan),where=np.isfinite(b)&(b>0))

def derive(t):
    t=t.copy()
    for src,out in [('net_mwh','R'),('positive_mwh','R_positive'),('capacity_event_hours','E_loss')]:
        t[out]=safe_ratio(t[src],t.capacity_mw)
    t['cf_event']=safe_ratio(t.normal_event_mwh,t.capacity_event_hours)
    t['r_event']=safe_ratio(t.net_mwh,t.normal_event_mwh)
    t['annual_loss_pct']=100*safe_ratio(t.net_mwh,t.normal_annual_mwh)
    return t

def climate_deployment(r):
    a,b,c,d=[r[k] for k in [('ssp126','ssp126'),('ssp585','ssp126'),('ssp126','ssp585'),('ssp585','ssp585')]]
    dc0=b-a;dc1=d-c;ds0=c-a;ds1=d-b
    return dict(D=d-a,delta_C_126=dc0,delta_C_585=dc1,delta_S_126=ds0,delta_S_585=ds1,
                Phi_C=(dc0+dc1)/2,Phi_S=(ds0+ds1)/2,J=dc1-dc0,
                closure=(dc0+dc1+ds0+ds1)/2-(d-a))

def three_factor(base,target):
    base=np.asarray(base,float);target=np.asarray(target,float)
    if not np.isfinite([base,target]).all(): return np.full(3,np.nan)
    out=np.zeros(3)
    for order in itertools.permutations(range(3)):
        state=base.copy()
        for k in order:
            before=state.prod();state[k]=target[k];out[k]+=(state.prod()-before)/6
    return out

def ensemble(t,keys,value,expected_models=4):
    def calc(g):
        v=g[value].to_numpy(float);v=v[np.isfinite(v)]
        n=len(v);mean=v.mean() if n==expected_models else np.nan
        agreement=int(np.sum((np.sign(v)==np.sign(mean))&(v!=0))) if np.isfinite(mean) and mean!=0 else 0
        category='unavailable' if n!=expected_models else ('higher_585' if mean>0 and agreement>=3 else 'higher_126' if mean<0 and agreement>=3 else 'unclear')
        return pd.Series(dict(mean=mean,minimum=v.min() if n else np.nan,maximum=v.max() if n else np.nan,
                              n_models=n,agreement=agreement,category=category))
    if t.duplicated(keys+['model']).any():raise ValueError('Duplicate model statistics')
    return t.groupby(keys,dropna=False,sort=True).apply(calc,include_groups=False).reset_index()
