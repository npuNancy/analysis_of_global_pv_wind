"""Reduce accepted preparation shards and export model-resolved shared tables."""
import itertools
import json
import numpy as np
import pandas as pd
from paper_figures.common.cli import parser
from paper_figures.common.io import write_csv,complete,require_complete
from paper_figures.common.metrics import derive,climate_deployment,three_factor,safe_ratio,ensemble

IDENTITY=['model','climate_ssp','station_ssp','tech','snapshot','country','event','support']
SUMS=['net_mwh','positive_mwh','normal_event_mwh','normal_annual_mwh','actual_event_mwh','capacity_event_hours','capacity_mw','available_capacity_mw','n_stations']

def summarize_loss(a):
    out=a.output_root/'loss_summary';out.mkdir(parents=True,exist_ok=True);parts=[];supports=[]
    for s,t,p in itertools.product(a.station_ssps,a.techs,a.patches):
        folder=a.output_root/'loss_shards'/s/t/p;require_complete(folder)
        f=pd.read_csv(folder/'annual.csv.gz')
        if len(f):parts.append(f)
        f=pd.read_csv(folder/'station_support.csv.gz',dtype={'station_id':str});f['station_ssp']=s;f['tech']=t;f['patch']=p;supports.append(f)
    membership=pd.concat(supports,ignore_index=True)
    if membership.duplicated(['station_ssp','tech','snapshot','station_id']).any():raise ValueError('Station counted in multiple source patches')
    write_csv(out/'station_support.csv.gz',membership)
    if not parts:raise ValueError('No loss data in campaign')
    table=pd.concat(parts,ignore_index=True)
    annual=table.groupby(IDENTITY+['year'],as_index=False)[SUMS].sum();annual=derive(annual)
    # Regional sums must reproduce GLOBAL, including unassigned and ambiguous rows.
    regional=annual[annual.country.ne('GLOBAL')].groupby([k for k in IDENTITY if k!='country']+['year'])[SUMS].sum()
    global_=annual[annual.country.eq('GLOBAL')].set_index([k for k in IDENTITY if k!='country']+['year'])[SUMS]
    if not np.allclose(regional.sort_index(),global_.sort_index(),rtol=1e-9,atol=1e-5):raise ValueError('Country/global total conservation failed')
    capcheck=annual[annual.support.eq('common')].groupby(IDENTITY).capacity_mw.agg(['min','max'])
    if not np.allclose(capcheck['min'],capcheck['max']):raise ValueError('Common capacity changed across years')
    years=annual.groupby(IDENTITY).year.nunique()
    if not (years==10).all():raise ValueError('Incomplete loss window')
    window=derive(annual.groupby(IDENTITY,as_index=False)[SUMS].mean())
    # Original support can vary by year; report mean annual R as its period estimator.
    means=annual.groupby(IDENTITY,as_index=False)[['R','R_positive']].mean()
    for metric in ['R','R_positive']:
        original=window.support.eq('original')
        window.loc[original,metric]=means.loc[original,metric]
    write_csv(out/'annual.csv.gz',annual);write_csv(out/'window.csv.gz',window)
    differences=[];factors=[]
    keys=['model','tech','snapshot','country','event','support']
    for identity,g in window.groupby(keys,sort=True):
        meta=dict(zip(keys,identity));r=g.set_index(['climate_ssp','station_ssp'])
        required=[('ssp126','ssp126'),('ssp585','ssp126'),('ssp126','ssp585'),('ssp585','ssp585')]
        for metric in ['R','R_positive','annual_loss_pct']:
            v={k:float(r.loc[k,metric]) if k in r.index else np.nan for k in required}
            d=climate_deployment(v)
            if np.isfinite(d['closure']) and abs(d['closure'])>1e-8+1e-10*abs(d['D']):raise ValueError('Climate/deployment closure failed')
            row={**meta,'metric':metric,**d}
            row['D245']=float(r.loc[('ssp245','ssp245'),metric]-r.loc[('ssp126','ssp126'),metric]) if ('ssp245','ssp245') in r.index and ('ssp126','ssp126') in r.index else np.nan
            row['R126']=v[('ssp126','ssp126')];row['R585']=v[('ssp585','ssp585')];differences.append(row)
        if meta['support']=='common':
            for s in ('ssp126','ssp585'):
                if ('ssp126',s) not in r.index or ('ssp585',s) not in r.index:continue
                base=r.loc[('ssp126',s)];target=r.loc[('ssp585',s)]
                phi=three_factor(base[['E_loss','cf_event','r_event']],target[['E_loss','cf_event','r_event']]);gap=target.R-base.R
                residual=phi.sum()-gap
                if np.isfinite(residual) and abs(residual)>1e-7+1e-9*abs(gap):raise ValueError('Three-factor closure failed')
                factors.append({**meta,'station_ssp':s,'psi_E':phi[0],'psi_CF':phi[1],'psi_r':phi[2],'delta_C':gap,'closure':residual,'delta_E':target.E_loss-base.E_loss})
    write_csv(out/'contrasts.csv.gz',pd.DataFrame(differences));write_csv(out/'three_factor.csv.gz',pd.DataFrame(factors))
    coverage=annual[annual.event.eq('all')][[k for k in IDENTITY if k!='event']+['year','capacity_mw','available_capacity_mw','n_stations']]
    catalogs=pd.read_csv(a.output_root/'catalogues/capacity_by_country.csv')
    catalogs=catalogs.rename(columns={'capacity_mw':'catalogue_capacity_mw'})
    globals_=catalogs.groupby(['station_ssp','tech','snapshot'],as_index=False).catalogue_capacity_mw.sum();globals_['country']='GLOBAL';catalogs=pd.concat([catalogs,globals_])
    coverage=coverage.merge(catalogs,on=['station_ssp','tech','snapshot','country'],how='left',validate='many_to_one')
    coverage['coverage_pct']=100*safe_ratio(coverage.capacity_mw,coverage.catalogue_capacity_mw)
    write_csv(out/'capacity_coverage.csv.gz',coverage)
    complete(out,models=a.models,station_ssps=a.station_ssps,climate_ssps=a.climate_ssps,snapshots=a.snapshots,patches=a.patches,
             scope='GLOBAL means selected patches; publish only when all formal patches are included',units={'R':'MWh MW-1 yr-1','E_loss':'h yr-1','capacity_mw':'MW'})

def summarize_events(a):
    out=a.output_root/'event_summary';out.mkdir(parents=True,exist_ok=True);parts=[];freq=[]
    for s,t,p in itertools.product(a.station_ssps,a.techs,a.patches):
        folder=a.output_root/'station_events'/s/t/p;require_complete(folder)
        f=pd.read_csv(folder/'monthly.csv.gz')
        if len(f):parts.append(f)
        fp=folder/'frequency_duration.csv.gz'
        if fp.exists():
            try:f=pd.read_csv(fp)
            except pd.errors.EmptyDataError:continue
            if len(f):freq.append(f)
    keys=['model','climate_ssp','station_ssp','tech','snapshot','year','month','country','event']
    monthly=pd.concat(parts,ignore_index=True).groupby(keys,as_index=False)[['capacity_mw','capacity_event_hours','capacity_valid_hours']].sum()
    monthly['E']=safe_ratio(monthly.capacity_event_hours,monthly.capacity_mw)
    write_csv(out/'monthly.csv.gz',monthly)
    annual=monthly.groupby([k for k in keys if k!='month'],as_index=False).agg(capacity_mw=('capacity_mw','first'),capacity_event_hours=('capacity_event_hours','sum'),capacity_valid_hours=('capacity_valid_hours','sum'))
    annual['E']=safe_ratio(annual.capacity_event_hours,annual.capacity_mw);write_csv(out/'annual.csv.gz',annual)
    window=annual.groupby([k for k in keys if k not in ('year','month')],as_index=False)[['capacity_mw','capacity_event_hours','capacity_valid_hours','E']].mean();write_csv(out/'window.csv.gz',window)
    monthly['season']=monthly.month.map({1:'DJF',2:'DJF',12:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'})
    sk=[k for k in keys if k!='month']+['season'];season=monthly.groupby(sk,as_index=False).E.sum()
    season=season.groupby([k for k in sk if k!='year'],as_index=False).E.mean();write_csv(out/'seasonal.csv.gz',season)
    if freq:
        f=pd.concat(freq,ignore_index=True);ids=[k for k in keys if k not in ('year','month')]
        cols=['capacity_mw','capacity_starts','capacity_complete_events','capacity_duration_hours','capacity_censored_events']
        f=f.groupby(ids,as_index=False)[cols].sum();f['frequency_per_year']=safe_ratio(f.capacity_starts,10*f.capacity_mw);f['duration_hours']=safe_ratio(f.capacity_duration_hours,f.capacity_complete_events)
        write_csv(out/'frequency_duration.csv.gz',f)
    complete(out,models=a.models,snapshots=a.snapshots,patches=a.patches)

def main():
    p=parser(__doc__);p.add_argument('--stage',choices=['loss','events'],default='loss');a=p.parse_args()
    if not a.patches:raise ValueError('Explicit expected patches required for reduction')
    (summarize_loss if a.stage=='loss' else summarize_events)(a)
if __name__=='__main__':main()
