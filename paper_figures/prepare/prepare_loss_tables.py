"""Loss shards with shared station support across models, climates and years."""
import itertools
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json
import numpy as np
import pandas as pd
from utils.data_access import read_loss_stations as reader
from paper_figures.config import EVENTS,LOSS_VARIABLES
from paper_figures.common.cli import parser
from paper_figures.common.io import write_csv,write_json,complete,require_complete

def read_year(records,events,catalog,identity):
    ids=[];caps=[];arrays=[]
    names=[f'{prefix}_{event}' for event in events for prefix in LOSS_VARIABLES.values()]
    for r in sorted(records,key=lambda r:r['station_batch']):
        with reader.open_record(r,variables=['station_id','capacity_mw','lon','lat',*names]) as ds:
            for key,value in identity.items():
                if ds.attrs.get(key)!=value:raise ValueError(f'Loss identity mismatch {key}: {r["path"]}')
            if set(json.loads(ds.attrs['supported_events']))!=set(events[1:]):raise ValueError('Event set mismatch')
            si=ds.station_id.values.astype(str);ca=ds.capacity_mw.values.astype(float)
            if not np.isfinite(ca).all() or (ca<=0).any():raise ValueError('Invalid positive snapshot capacities')
            expected=catalog.reindex(si)
            if expected.capacity_mw.isna().any():raise ValueError('Loss station missing from snapshot catalogue')
            if not np.allclose(ca,expected.capacity_mw,rtol=1e-6,atol=1e-5):raise ValueError('Loss/catalogue capacity mismatch')
            if not np.allclose(ds.lat.values,expected.lat,atol=1e-6) or not np.allclose((ds.lon.values-expected.lon+180)%360-180,0,atol=1e-6):raise ValueError('Station coordinates mismatch')
            ids.extend(si);caps.extend(ca)
            arrays.append(np.column_stack([ds[n].values for n in names]).reshape(len(si),len(events),len(LOSS_VARIABLES)))
    ids=np.asarray(ids);caps=np.asarray(caps);v=np.concatenate(arrays)
    order=np.argsort(ids);ids=ids[order];caps=caps[order];v=v[order]
    if len(np.unique(ids))!=len(ids):raise ValueError('Duplicate station IDs across batches')
    return ids,caps,v

_WORKER_CATALOG = None
_WORKER_EVENTS = None

def initialize_worker(catalog, events):
    global _WORKER_CATALOG, _WORKER_EVENTS
    _WORKER_CATALOG, _WORKER_EVENTS = catalog, events

def read_year_worker(task):
    key, records, identity = task
    return key, read_year(records, _WORKER_EVENTS, _WORKER_CATALOG, identity)


def run(a,s,t,p):
    out=a.output_root/'loss_shards'/s/t/p;out.mkdir(parents=True,exist_ok=True)
    if (out/'complete.json').exists():require_complete(out);return
    require_complete(a.output_root/'catalogues')
    cats=pd.read_csv(a.output_root/'catalogues'/f'capacity_{s}_{t}.csv.gz',dtype={'station_id':str})
    records=reader.find_records(model=a.models,climate_scenario=a.climate_ssps,station_scenario=s,tech=t,patch=p)
    events=['all',*EVENTS[t]];rows=[];coverage=[];station_support=[]
    sources=[dict(path=r['path'],snapshot=r['snapshot_year'],year=r['start_year'],model=r['model'],climate_ssp=r['climate_scenario']) for r in records]
    write_json(out/'sources.json',sources)
    for snap in a.snapshots:
        catalog=cats[cats.snapshot.eq(snap)].set_index('station_id');payload={};common=None;refids=None;refcaps=None
        selected=[r for r in records if r['snapshot_year']==snap]
        if not selected:
            coverage.append(dict(snapshot=snap,status='EMPTY_SNAPSHOT',stations=0));continue
        tasks=[]
        for m,c,y in itertools.product(a.models,a.climate_ssps,range(snap,snap+10)):
            rec=[r for r in selected if r['model']==m and r['climate_scenario']==c and r['start_year']==y]
            if not rec:raise ValueError(f'Missing loss comparison: {s,t,p,snap,m,c,y}')
            tasks.append(((m,c,y),rec,dict(model=m,climate_scenario=c,station_scenario=s,tech=t,source_patch=p,snapshot_year=snap,analysis_year=y)))
        # Spawn gives each process its own NetCDF handles and native library state.
        with ProcessPoolExecutor(max_workers=a.workers,mp_context=multiprocessing.get_context('spawn'),
                                 initializer=initialize_worker,initargs=(catalog,events)) as pool:
            for (m,c,y),(ids,cap,v) in pool.map(read_year_worker,tasks,chunksize=1):
                if refids is None:refids=ids;refcaps=cap;common=np.ones(len(ids),bool)
                if not np.array_equal(ids,refids):raise ValueError('Source-patch membership differs; global station alignment is required')
                if not np.allclose(cap,refcaps,rtol=1e-7,atol=1e-6):raise ValueError('Capacity changed under fixed deployment')
                valid=np.isfinite(v).all(axis=(1,2))&(v[:,0,3]>0)
                common &= valid
                payload[m,c,y]=(v,valid)
        countries=catalog.loc[refids,'country'].to_numpy()
        support=pd.DataFrame(dict(station_id=refids,capacity_mw=refcaps,country=countries,common=common,snapshot=snap))
        station_support.append(support)
        for (m,c,y),(v,own) in payload.items():
            for policy,valid in [('common',common),('original',own)]:
                for country in ['GLOBAL',*sorted(set(countries))]:
                    selected_country=np.ones(len(countries),bool) if country=='GLOBAL' else countries==country
                    keep=valid&selected_country;den=refcaps[keep].sum()
                    for ei,e in enumerate(events):
                        totals=v[keep,ei,:].sum(axis=0) if keep.any() else np.zeros(len(LOSS_VARIABLES))
                        row=dict(model=m,climate_ssp=c,station_ssp=s,tech=t,patch=p,snapshot=snap,year=y,country=country,event=e,support=policy,
                                 capacity_mw=den,available_capacity_mw=refcaps[selected_country].sum(),n_stations=int(keep.sum()))
                        row.update(dict(zip(LOSS_VARIABLES,totals)))
                        row['capacity_event_hours']=float(np.dot(refcaps[keep],v[keep,ei,5]))
                        del row['event_hours']
                        rows.append(row)
            coverage.append(dict(model=m,climate_ssp=c,snapshot=snap,year=y,status='ANNUAL_VALUES_CHECKED',stations=len(refids),
                                 original_stations=int(own.sum()),common_stations=int(common.sum()),capacity_mw=float(refcaps.sum()),
                                 original_capacity_mw=float(refcaps[own].sum()),common_capacity_mw=float(refcaps[common].sum()),
                                 time_coverage='not_reported_by_annual_product'))
        print('completed snapshot',s,t,p,snap,len(refids),int(common.sum()),flush=True)
        del payload
    write_csv(out/'annual.csv.gz',pd.DataFrame(rows,columns=None if rows else ['model','climate_ssp','station_ssp','tech','patch','snapshot','year','country','event','support','capacity_mw']))
    write_csv(out/'coverage.csv.gz',pd.DataFrame(coverage))
    write_csv(out/'station_support.csv.gz',pd.concat(station_support,ignore_index=True) if station_support else pd.DataFrame(columns=['station_id','capacity_mw','country','common','snapshot']))
    complete(out,station_ssp=s,tech=t,patch=p,models=a.models,climate_ssps=a.climate_ssps,snapshots=a.snapshots,
             support='common finite annual fields across selected climates, models and ten years; fixed snapshot capacity',
             time_coverage='Annual files do not establish identical valid timestamps')

def main():
    p=parser(__doc__);p.add_argument('--workers',type=int,default=min(4,int(os.environ.get('SLURM_CPUS_PER_TASK','4'))));a=p.parse_args()
    if not 1<=a.workers<=int(os.environ.get('SLURM_CPUS_PER_TASK',str(a.workers))):raise ValueError('Workers exceed allocated CPUs')
    if not a.patches:
        a.patches=sorted(pd.read_csv(a.output_root/'catalogues/event_task_states.csv.gz').patch.unique())
    for s,t,p in itertools.product(a.station_ssps,a.techs,a.patches):run(a,s,t,p)
if __name__=='__main__':main()
