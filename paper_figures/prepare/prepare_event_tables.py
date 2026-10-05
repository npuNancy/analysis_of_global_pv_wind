"""Observed monthly exposure on the Loss common cohort; optional run statistics."""
import itertools
import os
import copy
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
import json
from datetime import timedelta
import numpy as np
import pandas as pd
import xarray as xr
import cftime
from utils.data_access import read_extreme_stations as reader
from paper_figures.config import EVENTS,MIN_TIME_COVERAGE
from paper_figures.common.cli import parser
from paper_figures.common.io import write_csv,complete,require_complete

def run_serial(a,s,t,p,worker_key):
    out=a.output_root/'station_events'/s/t/p/'parts'/worker_key;out.mkdir(parents=True,exist_ok=True)
    if (out/'complete.json').exists():require_complete(out);return
    loss=a.output_root/'loss_shards'/s/t/p;require_complete(loss)
    support=pd.read_csv(loss/'station_support.csv.gz',dtype={'station_id':str})
    selected=support[support.common.eq(True)]
    rows=[];audit=[];frequency=[];events=['all',*EVENTS[t]]
    records=reader.find_records(model=a.models,climate_scenario=a.climate_ssps,station_scenario=s,tech=t,patch=p,years=(min(a.snapshots),max(a.snapshots)+9))
    for snap in a.snapshots:
        st=selected[selected.snapshot.eq(snap)].sort_values('station_id');ids=st.station_id.to_numpy();cap=st.capacity_mw.to_numpy();countries=st.country.to_numpy()
        if not len(ids):continue
        for m,c in itertools.product(a.models,a.climate_ssps):
            files=sorted([r for r in records if r['model']==m and r['climate_scenario']==c and r['start_year']<=snap+9 and r['end_year']>=snap],key=lambda r:r['start_year'])
            if not files:raise ValueError('No station event files')
            counts=np.zeros((10,12,len(events),len(ids)),dtype=np.uint16);valid_counts=np.zeros((10,12,len(ids)),dtype=np.uint16)
            previous=None;calendar=None;observed=np.zeros(10,dtype=int)
            if a.event_runs:
                active=np.zeros((len(events),len(ids)),bool);previous_valid=np.zeros(len(ids),bool)
                duration=np.zeros_like(active,dtype=np.uint32);uncensored=np.zeros_like(active)
                starts=np.zeros_like(duration);completed=np.zeros_like(duration);total_duration=np.zeros_like(duration);censored=np.zeros_like(duration)
            for rec in files:
                with reader.open_record(rec,station_ids=ids.tolist(),years=(snap,snap+9),variables=['signal_'+e for e in EVENTS[t]]) as ds:
                    times=ds.time.values
                    for b in range(0,len(times),a.time_chunk):
                        ts=times[b:b+a.time_chunk]
                        if not len(ts):continue
                        if hasattr(ts[0],'calendar'):cal=ts[0].calendar
                        else:cal='proleptic_gregorian'
                        if calendar is None:calendar=cal
                        if calendar!=cal:raise ValueError('Calendar changed')
                        for ti in ts:
                            if previous is not None:
                                delta=ti-previous
                                hours=float(delta/np.timedelta64(1,'h')) if isinstance(delta,np.timedelta64) else delta.total_seconds()/3600
                                if hours!=3:raise ValueError('Gap/overlap in station event time axis')
                            previous=ti
                        block=np.stack([ds['signal_'+e].isel(time=slice(b,b+len(ts))).values for e in EVENTS[t]],axis=1)
                        valid=np.isin(block,[0,1]).all(axis=1);flags=block==1;flags=np.concatenate([flags.any(axis=1,keepdims=True),flags],axis=1)&valid[:,None,:]
                        dt=ds.time.isel(time=slice(b,b+len(ts)));yy=dt.dt.year.values;mm=dt.dt.month.values
                        for y,month in set(zip(yy.tolist(),mm.tolist())):
                            k=(yy==y)&(mm==month);counts[y-snap,month-1]+=flags[k].sum(axis=0,dtype=np.uint16);valid_counts[y-snap,month-1]+=valid[k].sum(axis=0,dtype=np.uint16);observed[y-snap]+=int(k.sum())
                        if a.event_runs:
                            for k in range(len(ts)):
                                v=valid[k];f=flags[k]
                                start=f&~active;end=active&~f
                                full_end=end&v[None,:]&uncensored
                                completed+=full_end;total_duration+=np.where(full_end,duration,0)
                                censored+=end&~full_end
                                starts+=start&previous_valid[None,:]
                                uncensored=np.where(start,previous_valid[None,:],uncensored)&f
                                duration=np.where(f,duration+1,0);active=f;previous_valid=v
            expected=np.array([(cftime.datetime(y+1,1,1,calendar=calendar)-cftime.datetime(y,1,1,calendar=calendar)).total_seconds()/3600 for y in range(snap,snap+10)])
            if not np.all(observed*3==expected):raise ValueError('Incomplete ten-year event window')
            fractions=valid_counts.sum(axis=1)*3/expected[:,None]
            if (fractions<MIN_TIME_COVERAGE-1e-8).any():
                write_csv(out/'insufficient_time_coverage.csv',pd.DataFrame(dict(station_id=ids,min_time_coverage=fractions.min(axis=0))))
                raise ValueError('Loss common cohort has insufficient event-time coverage; shared support must be revised before exposure publication')
            for country in ['GLOBAL',*sorted(set(countries))]:
                mask=np.ones(len(ids),bool) if country=='GLOBAL' else countries==country
                den=float(cap[mask].sum())
                for yi in range(10):
                    for month in range(12):
                        for ei,e in enumerate(events):
                            rows.append(dict(model=m,climate_ssp=c,station_ssp=s,tech=t,patch=p,snapshot=snap,year=snap+yi,month=month+1,country=country,event=e,
                                             capacity_mw=den,capacity_event_hours=float(np.dot(counts[yi,month,ei,mask]*3.,cap[mask])),
                                             capacity_valid_hours=float(np.dot(valid_counts[yi,month,mask]*3.,cap[mask]))))
                if a.event_runs:
                    for ei,e in enumerate(events):
                        frequency.append(dict(model=m,climate_ssp=c,station_ssp=s,tech=t,patch=p,snapshot=snap,country=country,event=e,capacity_mw=den,
                                              capacity_starts=float(np.dot(starts[ei,mask],cap[mask])),capacity_complete_events=float(np.dot(completed[ei,mask],cap[mask])),
                                              capacity_duration_hours=float(np.dot(total_duration[ei,mask]*3.,cap[mask])),
                                              capacity_censored_events=float(np.dot((censored+active)[ei,mask],cap[mask]))))
            audit.append(dict(model=m,climate_ssp=c,snapshot=snap,n_stations=len(ids),min_time_coverage=float(fractions.min()),calendar=calendar))
            print('events',s,t,p,m,c,snap,len(ids),flush=True)
    columns=['model','climate_ssp','station_ssp','tech','patch','snapshot','year','month','country','event','capacity_mw','capacity_event_hours','capacity_valid_hours']
    write_csv(out/'monthly.csv.gz',pd.DataFrame(rows,columns=columns));write_csv(out/'coverage.csv',pd.DataFrame(audit))
    if a.event_runs:write_csv(out/'frequency_duration.csv.gz',pd.DataFrame(frequency))
    complete(out,models=a.models,climate_ssps=a.climate_ssps,snapshots=a.snapshots,event_runs=a.event_runs,minimum_time_coverage=MIN_TIME_COVERAGE,exposure='observed hours; no extrapolation',support='Loss common station cohort; all event types share valid timestamps')

def event_worker(task):
    a,s,t,p,m,c=task
    a=copy.copy(a);a.models=[m];a.climate_ssps=[c]
    key=m+'_'+c
    run_serial(a,s,t,p,key)
    return str(a.output_root/'station_events'/s/t/p/'parts'/key)

def run(a,s,t,p):
    out=a.output_root/'station_events'/s/t/p;out.mkdir(parents=True,exist_ok=True)
    if (out/'complete.json').exists():require_complete(out);return
    tasks=[(a,s,t,p,m,c) for m,c in itertools.product(a.models,a.climate_ssps)]
    with ProcessPoolExecutor(max_workers=min(a.workers,len(tasks)),mp_context=multiprocessing.get_context('spawn')) as pool:
        folders=list(pool.map(event_worker,tasks,chunksize=1))
    for name in ['monthly.csv.gz','coverage.csv']+(['frequency_duration.csv.gz'] if a.event_runs else []):
        tables=[]
        for f in folders:
            folder=__import__('pathlib').Path(f);require_complete(folder)
            try:table=pd.read_csv(folder/name)
            except pd.errors.EmptyDataError:continue
            tables.append(table)
        write_csv(out/name,pd.concat(tables,ignore_index=True) if tables else pd.DataFrame())
    complete(out,models=a.models,climate_ssps=a.climate_ssps,snapshots=a.snapshots,workers=a.workers,event_runs=a.event_runs,
             minimum_time_coverage=MIN_TIME_COVERAGE,exposure='observed hours; no extrapolation',support='Loss common station cohort')

def main():
    p=parser(__doc__);p.add_argument('--time-chunk',type=int,default=80);p.add_argument('--event-runs',action='store_true');p.add_argument('--workers',type=int,default=min(4,int(os.environ.get('SLURM_CPUS_PER_TASK','4'))));a=p.parse_args()
    if not 1<=a.workers<=int(os.environ.get('SLURM_CPUS_PER_TASK',str(a.workers))):raise ValueError('Workers exceed allocated CPUs')
    if not a.patches or a.time_chunk<1:raise ValueError('Positive time chunk and source patches required')
    for s,t,patch in itertools.product(a.station_ssps,a.techs,a.patches):run(a,s,t,patch)
if __name__=='__main__':main()
