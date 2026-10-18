"""Reduce station shards before computing capacity synchrony quantiles."""
import argparse
import itertools
import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from paper_figures.config import MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import require_complete, write_csv, write_json, digest
from .prepare_ssp_station_dynamics import tasks_for, folder_for
from .prepare_ssp_dynamics import marker
from .grid_event_dynamics import STAT_NAMES
from .summarize_ssp_dynamics import pooled_p90, longest_observed, ensemble
from .analyze_ssp_station import OUT, KEY, differences, summarize_diff

def reduce_sync(root, tech, model, climate, layout, snap, sub, folders):
    regions=sorted(sub.region.unique());events=["all",*EVENTS[tech]]
    total=sub.drop_duplicates("region").set_index("region").loc[regions].capacity_mw.to_numpy()
    lookup={r:i for i,r in enumerate(regions)}
    affected=available=hist=times=None;calendar=None
    for folder in folders:
        path=folder/f"sync_{snap}.nc"
        if not path.exists():continue
        with xr.open_dataset(path,decode_times=False) as ds:
            ix=np.array([lookup[r] for r in ds.region.values.astype(str)])
            if times is None:
                times=ds.time.values;calendar=ds.time.attrs["calendar"]
                affected=np.zeros((len(times),len(events),len(regions)),dtype="f8")
                available=np.zeros((len(times),len(regions)),dtype="f8")
            if not np.array_equal(times,ds.time.values) or ds.time.attrs["calendar"]!=calendar:raise ValueError("Patch time/calendar mismatch")
            affected[:,:,ix]+=ds.affected_capacity_mw.values
            available[:,ix]+=ds.valid_capacity_mw.values
        with xr.open_dataset(folder/f"duration_hist_{snap}.nc") as ds:
            ix=np.array([lookup[r] for r in ds.region.values.astype(str)])
            if hist is None:hist=np.zeros((len(events),len(regions),ds.sizes["length_steps"]),dtype="f8")
            hist[:,ix,:]+=ds.capacity_event_count.values
    tolerance=np.maximum(1e-4,total*1e-9)
    if not np.isfinite(affected).all() or np.any(affected< -1e-5) or np.any(affected>available[:,None,:]+tolerance[None,None,:]) or np.any(available>total+tolerance):raise ValueError("Capacity synchrony bounds")
    sync=[];tails=[]
    for ri,region in enumerate(regions):
        valid=available[:,ri]/total[ri]>=.99-1e-10
        if not valid.any():raise ValueError("No accepted synchronous timestamps: "+region)
        lower=affected[:,:,ri]/total[ri]*100
        upper=np.minimum(100,lower+(1-available[:,ri,None]/total[ri])*100)
        union95=np.quantile(lower[valid,0],.95);tail=valid&(lower[:,0]>=union95)
        tailmean=lower[tail].mean(axis=0)
        for ei,event in enumerate(events):
            identity=dict(tech=tech,model=model,climate_ssp=climate,station_ssp=layout,snapshot=snap,region=region,event=event)
            expected=sub[sub.region.eq(region)&sub.event.eq(event)].iloc[0]
            if not np.isclose(affected[:,ei,ri].sum(),expected.observed_steps,rtol=1e-9,atol=1e-3):raise ValueError("Synchronous time integral")
            if not np.isclose(hist[ei,ri].sum(),expected.complete_count,rtol=1e-9,atol=1e-3):raise ValueError("Regional histogram count")
            row=dict(p90_complete_hours=pooled_p90(hist[ei,ri]),p95_capacity_pct=float(np.quantile(lower[valid,ei],.95)),p95_capacity_upper_pct=float(np.quantile(upper[valid,ei],.95)),maximum_capacity_pct=float(lower[valid,ei].max()),maximum_capacity_upper_pct=float(upper[valid,ei].max()),accepted_time_fraction=float(valid.mean()),mean_available_capacity_fraction=float((available[:,ri]/total[ri]).mean()),mean_observed_capacity_pct=float(lower[:,ei].mean()))
            for threshold in (10,20,30):
                flag=valid&(lower[:,ei]>threshold)
                row[f"above{threshold}_observed_hours_per_year"]=float(flag.sum()*3/10)
                row[f"above{threshold}_longest_observed_hours"]=longest_observed(flag)
            sync.append(identity|row)
            tails.append(identity|dict(value=float(tailmean[ei]),tail_time_fraction=float(tail.mean())))
        tails.append({**identity,"event":"overlap_correction","value":float(tailmean[0]-tailmean[1:].sum()),"tail_time_fraction":float(tail.mean())})
    print("REDUCED",tech,model,climate,layout,snap,flush=True)
    return sync,tails

def reduce_task(task):
    return reduce_sync(*task)

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument("--output-root",type=Path,default=OUT/"dynamics");p.add_argument("--workers",type=int,default=min(4,int(os.environ.get("SLURM_CPUS_PER_TASK","4"))));a=p.parse_args()
    if not 1<=a.workers<=int(os.environ.get("SLURM_CPUS_PER_TASK",str(a.workers))):p.error("Workers exceed allocated CPUs")
    root=a.output_root;out=root/"summary";out.mkdir(parents=True,exist_ok=True)
    tasks=tasks_for(MODELS,SSPS,SSPS,TECHS,None,SNAPSHOTS,root,240)
    grouped={};tables=[];audits=[]
    for model,climate,layout,tech,patch,*_ in tasks:
        folder=folder_for(root,model,climate,layout,tech,patch)
        receipt=require_complete(folder)
        if receipt["snapshots"]!=list(SNAPSHOTS):raise ValueError("Incomplete snapshot set")
        audits.extend(receipt["audits"])
        grouped.setdefault((tech,model,climate,layout),[]).append(folder)
        tables.append(pd.read_csv(folder/"regional.csv.gz"))
    base=pd.concat(tables,ignore_index=True).groupby(KEY,as_index=False)[["capacity_mw",*STAT_NAMES]].sum()
    base["exposure_days"]=base.observed_steps*3/base.capacity_mw/10/24
    base["starts_per_year"]=base.known_starts/base.capacity_mw/10
    base["complete_frequency_per_year"]=base.complete_count/base.capacity_mw/10
    base["mean_complete_hours"]=base.complete_steps*3/base.complete_count.replace(0,np.nan)
    base["complete_exposure_days"]=base.complete_steps*3/base.capacity_mw/10/24
    base["censored_exposure_days"]=base.censored_steps*3/base.capacity_mw/10/24
    base["censored_fragment_fraction"]=base.censored_count/(base.complete_count+base.censored_count).replace(0,np.nan)
    base["complete_ge24h_per_year"]=base.complete_ge24h/base.capacity_mw/10
    base["complete_ge72h_per_year"]=base.complete_ge72h/base.capacity_mw/10
    base["annual_max_observed_hours_mean"]=base.annual_max_observed_steps_sum*3/base.capacity_mw/10
    if not np.allclose(base.exposure_days,base.complete_exposure_days+base.censored_exposure_days):raise ValueError("Exposure closure")
    sr=[];tr=[];reduction_tasks=[]
    for tech,model,climate,layout,snap in itertools.product(TECHS,MODELS,SSPS,SSPS,SNAPSHOTS):
        sub=base[base.tech.eq(tech)&base.model.eq(model)&base.climate_ssp.eq(climate)&base.station_ssp.eq(layout)&base.snapshot.eq(snap)]
        if sub.empty:raise ValueError("Missing scenario group")
        reduction_tasks.append((root,tech,model,climate,layout,snap,sub,grouped[tech,model,climate,layout]))
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=get_context("spawn")) as pool:
        for sync,tail in pool.map(reduce_task,reduction_tasks,chunksize=1):
            sr.extend(sync);tr.extend(tail)
    combined=base.drop(columns=list(STAT_NAMES)).merge(pd.DataFrame(sr),on=KEY,validate="one_to_one")
    write_csv(out/"combined_models.csv.gz",combined)
    tail=pd.DataFrame(tr);write_csv(out/"tail_composition_models.csv.gz",tail)
    write_csv(out/"tail_composition.csv",ensemble(tail,[k for k in KEY if k!="model"],"value"))
    tail["metric"]="tail_mean_capacity_pct"
    td=differences(tail)
    for _,g in td.groupby(["model","tech","snapshot","region","comparison","high","low"]):
        e=g.set_index("event").difference
        if not np.isclose(e.drop("all").sum(),e["all"],atol=1e-8):raise ValueError("Tail event closure")
    write_csv(out/"tail_contrasts_models.csv.gz",td)
    write_csv(out/"tail_contrasts.csv",summarize_diff(td))
    write_json(out/"audit.json",dict(status="PASSED",shards=len(tasks),minimum_annual_time_coverage=min(x["minimum_annual_time_coverage"] for x in audits if not x["empty"]),code_sha256=digest(Path(__file__)),definition="Fixed snapshot capacity, complete-event pool, all-event union; native calendars; all patch timestamps summed before quantiles"))
    marker(out,source_shards=len(tasks))
    print("STATION DYNAMICS SUMMARY PASSED",out,flush=True)
if __name__=="__main__":main()
