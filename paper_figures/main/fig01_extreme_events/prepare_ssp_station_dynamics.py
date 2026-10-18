"""Stream indexed station events using fixed capacity snapshots and common support."""
import argparse
import itertools
import json
import os
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import numpy as np
import pandas as pd
import netCDF4
import xarray as xr
from scipy.sparse import csr_matrix
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import require_complete, write_csv, write_json, digest
from utils.data_access.read_extreme_stations import find_records
from .grid_event_dynamics import FastRuns, Runs, build_kernel, STAT_NAMES
from .prepare_ssp_dynamics import marker, write_nc, TIME_UNITS, year_hours
from .analyze_ssp_station import OUT

def tasks_for(models,ssps,layouts,techs,patches,snapshots,root,chunk):
    states=pd.read_csv(OUTPUT/"catalogues/event_task_states.csv.gz")
    states=states[states.status.eq("COMPLETED") & states.model.isin(models) & states.climate_scenario.isin(ssps) & states.station_scenario.isin(layouts) & states.tech.isin(techs)]
    if patches:states=states[states.patch.isin(patches)]
    return [(r.model,r.climate_scenario,r.station_scenario,r.tech,r.patch,tuple(snapshots),str(root),chunk) for r in states.sort_values(["tech","model","climate_scenario","station_scenario","patch"]).itertuples()]

def folder_for(root,model,climate,layout,tech,patch):
    return Path(root)/"shards"/tech/model/climate/layout/patch

def process(task):
    model,ssp,layout,tech,patch,snaps,root,chunk=task
    began=time.monotonic()
    folder=folder_for(root,model,ssp,layout,tech,patch);folder.mkdir(parents=True,exist_ok=True)
    events=["all",*EVENTS[tech]]
    support_file=OUTPUT/"loss_shards"/layout/tech/patch/"station_support.csv.gz"
    require_complete(support_file.parent)
    support=pd.read_csv(support_file,dtype={"station_id":str})
    source=find_records(model=model,climate_scenario=ssp,station_scenario=layout,tech=tech,patch=patch,years=(min(snaps),max(snaps)+9))
    code={p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name("grid_event_dynamics.py"),Path(__file__).with_name("grid_event_dynamics.c")]}
    identity=dict(code=code,support_sha256=digest(support_file),snapshots=list(snaps),sources=[dict(path=r["path"],identity=r["identity"],bytes=Path(r["path"]).stat().st_size,mtime_ns=Path(r["path"]).stat().st_mtime_ns) for r in source])
    if (folder/"complete.json").exists():
        old=require_complete(folder)
        if any(old[k]!=v for k,v in identity.items()):raise ValueError("Completed shard input/code identity changed")
        return str(folder)
    library=build_kernel(root)
    rows=[];audits=[]
    for snap in snaps:
        st=support[support.common.eq(True)&support.snapshot.eq(snap)&support.capacity_mw.gt(0)].sort_values("station_id")
        if st.empty:
            audits.append(dict(snapshot=snap,empty=True));continue
        files=[r for r in source if r["start_year"]<=snap+9 and r["end_year"]>=snap]
        if not files:raise ValueError("Missing indexed station files")
        with netCDF4.Dataset(files[0]["path"]) as ds:
            source_ids=np.asarray(ds["station_id"][:]).astype(str)
            if len(np.unique(source_ids))!=len(source_ids):raise ValueError("Duplicate station IDs")
            select=pd.Index(source_ids).get_indexer(st.station_id)
            if np.any(select<0):raise ValueError("Common-support ID absent from signal file")
            lon=np.asarray(ds["lon"][:])[select];lat=np.asarray(ds["lat"][:])[select]
        cap=st.capacity_mw.to_numpy();country=st.country.to_numpy()
        bands=np.select([lat < -60,lat < -30,lat < 0,lat < 30,lat < 60],["90S-60S","60S-30S","30S-0","0-30N","30N-60N"],default="60N-90N")
        regions=["global:GLOBAL"]+["country:"+x for x in np.unique(country)]+["latitude:"+x for x in np.unique(bands)]
        lookup={x:i for i,x in enumerate(regions)}
        ids=np.stack([np.zeros(len(cap),dtype=int),np.array([lookup["country:"+x] for x in country]),np.array([lookup["latitude:"+x] for x in bands])])
        weights=csr_matrix((np.tile(cap,3),(ids.ravel(),np.tile(np.arange(len(cap)),3))),shape=(len(regions),len(cap)))
        total=np.asarray(weights.sum(axis=1)).ravel()
        run=FastRuns(len(events),len(cap),cap,ids,len(regions),10*366*8,library)
        # Independent Python run accumulator on six real stations, across all blocks.
        nref=min(6,len(cap));ref_ids=np.zeros((1,nref),dtype=int)
        ref=Runs(len(events),nref,cap[:nref],ref_ids,1,10*366*8)
        affected_parts=[];valid_parts=[];time_parts=[]
        annual_valid=np.zeros((10,len(cap)),dtype="u4");annual_count=np.zeros(10,dtype=int)
        last=None;calendar=None;current_year=None
        for rec in files:
            with netCDF4.Dataset(rec["path"]) as ds:
                ds.set_auto_mask(False)
                if not np.array_equal(np.asarray(ds["station_id"][:]).astype(str),source_ids):raise ValueError("Station ordering changed between files")
                tv=ds["time"];cal=getattr(tv,"calendar","standard")
                dates=netCDF4.num2date(tv[:],tv.units,calendar=cal,only_use_cftime_datetimes=True)
                stamp=np.rint(netCDF4.date2num(dates,TIME_UNITS,calendar=cal)).astype("i8")
                years=np.array([d.year for d in dates])
                if calendar is None:calendar=cal
                if calendar!=cal or not np.all(np.diff(stamp)==10800):raise ValueError("Calendar/timestep differs")
                variables=[ds["signal_"+e] for e in EVENTS[tech]]
                for v in variables:v.set_var_chunk_cache(8*1024**2,1009,.75)
                for year in sorted(set(years)&set(range(snap,snap+10))):
                    if current_year is not None and year!=current_year:
                        run.finish_year();ref.finish_year()
                    current_year=year;ix=np.flatnonzero(years==year);annual_count[year-snap]+=len(ix)
                    for start in range(int(ix[0]),int(ix[-1])+1,chunk):
                        stop=min(start+chunk,int(ix[-1])+1);tt=stamp[start:stop]
                        if last is not None and tt[0]-last!=10800:raise ValueError("Missing/overlapping timestamps")
                        last=int(tt[-1]);flags=[];valid=None
                        for var in variables:
                            arr=var[start:stop,:][:,select];binary=(arr==0)|(arr==1)
                            if np.any(~binary&(arr!=getattr(var,"_FillValue",-127))):raise ValueError("Invalid event encoding")
                            valid=binary.copy() if valid is None else valid&binary
                            flags.append(arr==1)
                        flags=[np.logical_or.reduce(flags),*flags]
                        flags=[f&valid for f in flags]
                        affected,available=run.consume(flags,valid)
                        ref.consume([f[:,:nref] for f in flags],valid[:,:nref])
                        affected_parts.append(affected);valid_parts.append(available);time_parts.append(tt)
                        annual_valid[year-snap]+=valid.sum(axis=0).astype("u4")
            print("READ",model,ssp,layout,tech,patch,snap,rec["start_year"],flush=True)
        run.finish_year();run.finish();ref.finish_year();ref.finish()
        if not np.array_equal(run.stats[:,:,:nref],ref.stats):raise ValueError("Real-station Python/C statistics differ")
        nominal=np.array([year_hours(y,calendar)/3 for y in range(snap,snap+10)])
        if not np.array_equal(annual_count,nominal.astype(int)):raise ValueError("Incomplete time axis")
        coverage=annual_valid/nominal[:,None]
        if coverage.min()<.99-1e-8:raise ValueError("Common-support annual valid fraction below 99%")
        aggregate=np.stack([np.asarray(weights@stat.T).T for stat in run.stats])
        affected=np.concatenate(affected_parts);available=np.concatenate(valid_parts);times=np.concatenate(time_parts)
        if not np.allclose(affected.sum(axis=0),aggregate[0],rtol=1e-9,atol=1e-3):raise ValueError("Capacity time integral")
        if not np.array_equal(run.stats[0],run.stats[3]+run.stats[5]):raise ValueError("Complete/censored closure")
        if not np.allclose(run.hist.sum(axis=2),aggregate[2],rtol=1e-10,atol=1e-5):raise ValueError("Histogram count closure")
        if not np.allclose((run.hist*np.arange(run.hist.shape[2])).sum(axis=2),aggregate[3],rtol=1e-10,atol=1e-3):raise ValueError("Histogram duration closure")
        for ei,event in enumerate(events):
            for ri,region in enumerate(regions):
                rows.append(dict(model=model,climate_ssp=ssp,station_ssp=layout,tech=tech,patch=patch,snapshot=snap,region=region,event=event,capacity_mw=total[ri],**{name:aggregate[j,ei,ri] for j,name in enumerate(STAT_NAMES)}))
        cells=xr.Dataset({name:(("event","station"),run.stats[j]) for j,name in enumerate(STAT_NAMES)},coords=dict(event=events,station=st.station_id.to_numpy(),lon=("station",lon),lat=("station",lat),capacity_mw=("station",cap)))
        write_nc(folder/f"stations_{snap}.nc",cells)
        hist=xr.Dataset(dict(capacity_event_count=(("event","region","length_steps"),run.hist)),coords=dict(event=events,region=regions,length_steps=np.arange(run.hist.shape[2])))
        write_nc(folder/f"duration_hist_{snap}.nc",hist)
        syn=xr.Dataset(dict(affected_capacity_mw=(("time","event","region"),affected),valid_capacity_mw=(("time","region"),available),total_capacity_mw=("region",total)),coords=dict(time=times,event=events,region=regions))
        syn.time.attrs.update(units=TIME_UNITS,calendar=calendar)
        write_nc(folder/f"sync_{snap}.nc",syn)
        audits.append(dict(snapshot=snap,empty=False,stations=len(cap),capacity_mw=float(cap.sum()),minimum_annual_time_coverage=float(coverage.min()),calendar=calendar,n_steps=len(times),python_reference_stations=nref))
    columns=["model","climate_ssp","station_ssp","tech","patch","snapshot","region","event","capacity_mw",*STAT_NAMES]
    frame=pd.DataFrame(rows,columns=columns)
    # Per-patch frequency and duration reproduce the previously accepted station cache.
    oldpath=OUTPUT/"station_events"/layout/tech/patch/"frequency_duration.csv.gz"
    if len(frame):
        old=pd.read_csv(oldpath);old=old[old.model.eq(model)&old.climate_ssp.eq(ssp)&old.snapshot.isin(snaps)]
        actual=frame[frame.region.str.startswith(("country:","global:"))].copy();actual["country"]=actual.region.str.split(":").str[1]
        ck=["model","climate_ssp","station_ssp","tech","patch","snapshot","country","event"]
        check=actual.merge(old,on=ck,validate="one_to_one",suffixes=("","_old"))
        if len(check)!=len(actual) or len(check)!=len(old):raise ValueError("Incomplete cached regional match")
        for new,oldname,factor in [("known_starts","capacity_starts",1),("complete_count","capacity_complete_events",1),("complete_steps","capacity_duration_hours",3),("censored_count","capacity_censored_events",1)]:
            if not np.allclose(check[new]*factor,check[oldname],rtol=1e-8,atol=1e-3):raise ValueError("Cached frequency/duration mismatch: "+new)
    write_csv(folder/"regional.csv.gz",frame)
    marker(folder,**identity,model=model,ssp=ssp,station_ssp=layout,tech=tech,patch=patch,audits=audits,elapsed_seconds=time.monotonic()-began)
    print("DONE",model,ssp,layout,tech,patch,round(time.monotonic()-began,1),flush=True)
    return str(folder)

def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--models",nargs="+",default=list(MODELS),choices=MODELS)
    p.add_argument("--ssps",nargs="+",default=list(SSPS),choices=SSPS)
    p.add_argument("--layouts",nargs="+",default=list(SSPS),choices=SSPS)
    p.add_argument("--techs",nargs="+",default=list(TECHS),choices=TECHS)
    p.add_argument("--patches",nargs="+")
    p.add_argument("--snapshots",nargs="+",type=int,default=list(SNAPSHOTS),choices=SNAPSHOTS)
    p.add_argument("--output-root",type=Path,default=OUT/"dynamics")
    p.add_argument("--workers",type=int,default=min(8,int(os.environ.get("SLURM_CPUS_PER_TASK","8"))))
    p.add_argument("--time-chunk",type=int,default=240)
    p.add_argument("--batch",type=int,default=0);p.add_argument("--batches",type=int,default=1)
    a=p.parse_args()
    if not 0<=a.batch<a.batches or not 1<=a.workers<=int(os.environ.get("SLURM_CPUS_PER_TASK",str(a.workers))) or a.time_chunk<1:p.error("Invalid workers/batches/chunk")
    tasks=tasks_for(a.models,a.ssps,a.layouts,a.techs,a.patches,a.snapshots,a.output_root,a.time_chunk)[a.batch::a.batches]
    if not tasks:raise ValueError("Empty batch")
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=get_context("spawn")) as pool:folders=list(pool.map(process,tasks))
    target=a.output_root/"batches"/f"{a.batch:03d}";target.mkdir(parents=True,exist_ok=True)
    write_json(target/"shards.json",folders);marker(target,batch=a.batch,batches=a.batches,shard_count=len(folders))
    print("BATCH PASSED",a.batch,len(folders),flush=True)
if __name__=="__main__":main()
