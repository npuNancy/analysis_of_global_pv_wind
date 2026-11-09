"""Paired LCOE capacity and observed event-union exposure on the Loss cohort."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import cftime
import netCDF4
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, MODELS
from paper_figures.supplementary.global_metric_trends.plot import combine

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DATA = OUT / "source_data"
SOURCE = Path("/work/home/acxujo26gv/lcoe_station_climate_storage")
PAIRS = {"ssp126":"ssp126", "ssp245":"ssp245", "ssp560":"ssp585"}
EVENTS = {"wind":["high_temp","high_wind","hot_humid","icing","low_resource"],
          "solar":["cold_highwind","freezing_rain","high_humidity","icing","low_resource","rainstorm"]}
YEARS = np.arange(2030,2060)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_counts(calendar):
    return np.array([int((cftime.datetime(y+1,1,1,calendar=calendar) -
                         cftime.datetime(y,1,1,calendar=calendar)).total_seconds()/10800) for y in YEARS])


def reduce_one(task):
    loss, entries, pilot = task
    s,c,m,tech = (loss[k] for k in ("station_ssp","climate_ssp","model","tech"))
    with np.load(loss["path"],allow_pickle=False) as z:
        ids=z["grid_id"].copy(); support=z["common_support"].astype(bool)
        capacity=z["capacity_mw"].copy()
        require(np.array_equal(z["years"],YEARS),"Loss year mismatch")
    require(sha(loss["path"])==loss["sha256"],"Loss archive changed")
    lookup=pd.Index(ids)
    counts=np.zeros((30,len(ids)),dtype=np.uint16)
    valid_counts=np.zeros_like(counts)
    seen=set(); provenance=[]; calendar=None
    if pilot:
        entries=[min(entries,key=lambda e:e["artifacts"][0]["station_count"])]
    for entry in sorted(entries,key=lambda e:e["patch"]):
        files=sorted([a for a in entry["artifacts"] if 2030<=a["years"][0]<=2055],key=lambda a:a["years"][0])
        require([a["years"] for a in files]==[[y,y+4] for y in range(2030,2060,5)],"Incomplete event blocks")
        previous=None; observed=np.zeros(30,dtype=int); patch_ids=None; used=False
        for artifact in files:
            path=Path(artifact["path"])
            require(path.stat().st_size==artifact["size_bytes"],"Event file size changed")
            with netCDF4.Dataset(path) as ds:
                ds.set_auto_mask(False)
                grid=ds["grid_id"][:]; ix=lookup.get_indexer(grid)
                require((ix>=0).all(),"Unknown event grid")
                if patch_ids is None:
                    patch_ids=grid.copy()
                    require(not seen.intersection(grid.tolist()),"Duplicate patch grids")
                    seen.update(grid.tolist())
                else:
                    require(np.array_equal(grid,patch_ids),"Block station order changed")
                np.testing.assert_allclose(ds["capacity_mw"][:],capacity[::10,ix],rtol=1e-12)
                require(np.array_equal(ds["snapshot_year"][:],[2030,2040,2050]),"Snapshot mismatch")
                keep=np.flatnonzero(support[ix])
                if not len(keep):
                    continue
                used=True
                tv=ds["time"]; cal=tv.calendar
                require(calendar is None or calendar==cal,"Calendar changed")
                calendar=cal
                times=netCDF4.num2date(tv[:],tv.units,cal)
                require(all((b-a).total_seconds()==10800 for a,b in zip(times[:-1],times[1:])),"Time gap")
                require(previous is None or (times[0]-previous).total_seconds()==10800,"Block time gap")
                previous=times[-1]; yy=np.array([t.year for t in times])
                for year in sorted(set(yy)):
                    loc=np.flatnonzero(yy==year); observed[year-2030]+=len(loc)
                    for start in range(int(loc[0]),int(loc[-1])+1,512):
                        stop=min(start+512,int(loc[-1])+1)
                        valid=np.ones((stop-start,len(keep)),dtype=bool); union=np.zeros_like(valid)
                        # Read labels sequentially to bound peak memory on large solar patches.
                        for event in EVENTS[tech]:
                            v=ds["signal_"+event][start:stop,:][:,keep]
                            valid &= (v==0)|(v==1)
                            union |= v==1
                        union &= valid
                        counts[year-2030,ix[keep]]+=union.sum(axis=0,dtype=np.uint16)
                        valid_counts[year-2030,ix[keep]]+=valid.sum(axis=0,dtype=np.uint16)
                # Independent union implementation on a small sample, including overlaps/missingness.
                sample=np.stack([ds["signal_"+e][:16,:][:,keep[:10]] for e in EVENTS[tech]])
                vv=np.ones(sample.shape[1:],bool); uu=np.zeros_like(vv)
                for a in sample:
                    vv &= (a==0)|(a==1); uu |= a==1
                np.testing.assert_array_equal(uu&vv,(sample==1).any(axis=0)&np.isin(sample,[0,1]).all(axis=0))
            provenance.append(dict(path=str(path),sha256=artifact["sha256"],size_bytes=artifact["size_bytes"]))
        if used:
            require(np.array_equal(observed,expected_counts(calendar)),"Incomplete calendar years")
        print("PATCH",s,c,m,tech,entry["patch"],flush=True)
    if pilot:
        support &= np.isin(ids,list(seen))
    else:
        require(set(ids[support]).issubset(seen),"Missing common-cohort stations")
    expected=expected_counts(calendar)
    fractions=valid_counts[:,support]/expected[:,None]
    require(fractions.size>0 and fractions.min()>=.99-1e-8,"Loss cohort has less than 99% valid event time")
    require((counts<=valid_counts).all(),"Union exceeds valid time")
    cap=capacity[:,support]; rows=[]
    for yi,year in enumerate(YEARS):
        rows.append(dict(model=m,station_ssp=s,climate_ssp=c,tech=tech,snapshot=int(year//10*10),
            year=int(year),event="all",capacity_mw=float(cap[yi].sum()),
            catalogue_capacity_mw=float(capacity[yi].sum()),
            capacity_event_hours=float(np.dot(cap[yi],counts[yi,support]*3.)),
            capacity_valid_hours=float(np.dot(cap[yi],valid_counts[yi,support]*3.)),
            expected_hours=int(expected[yi]*3),calendar=calendar,n_stations=int((cap[yi]>0).sum()),
            min_time_coverage=float(fractions[yi].min())))
    result=dict(rows=rows,loss_archive=loss,sources=provenance)
    cache=OUT/"lcoe_exposure_shards";cache.mkdir(parents=True,exist_ok=True)
    dest=cache/("_".join([s,c,m,tech])+("_pilot" if pilot else "")+".json")
    dest.write_text(json.dumps(result,indent=2)+"\n")
    print("FINISHED",s,c,m,tech,"min_time_coverage",fractions.min(),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--pilot",action="store_true")
    args=parser.parse_args()
    DATA.mkdir(parents=True,exist_ok=True)
    index_path=SOURCE/"runtime/authoritative_index.json"
    loss_path=SOURCE/"loss/runtime/authoritative_index.json"
    index=json.loads(index_path.read_text()); losses=json.loads(loss_path.read_text())
    require(index["status"]==losses["status"]=="COMPLETED","Unreleased input")
    tasks=[]
    for loss in losses["files"]:
        s,c,m,t=(loss[k] for k in ("station_ssp","climate_ssp","model","tech"))
        if PAIRS[s]!=c: continue
        entries=[e for e in index["entries"] if e["product"]=="extreme" and e["status"]=="COMPLETED"
                 and e["station_scenario"]==s and e["climate_scenario"]==c and e["model"]==m and e["tech"]==t]
        require(bool(entries),"Missing paired events")
        tasks.append((loss,entries,args.pilot))
    require(len(tasks)==24,"Paired model matrix")
    if args.pilot:
        result=reduce_one(tasks[0])
        (OUT/"lcoe_exposure_pilot.json").write_text(json.dumps(dict(status="PASSED",
            min_time_coverage=min(r["min_time_coverage"] for r in result["rows"]),
            files=len(result["sources"]),job_id=os.environ.get("SLURM_JOB_ID")),indent=2)+"\n")
        return
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(reduce_one,tasks))
    annual=pd.DataFrame([r for result in results for r in result["rows"]])
    keys=["model","station_ssp","climate_ssp","tech","year"]
    require(len(annual)==720 and not annual.duplicated(keys).any(),"Annual matrix")
    require(annual.groupby(["station_ssp","climate_ssp","tech","year"]).capacity_mw.agg(
        lambda v:v.max()-v.min()).max()<1e-5,"Common capacity differs across models")
    fields=["capacity_mw","catalogue_capacity_mw","capacity_event_hours","capacity_valid_hours","n_stations"]
    joint=annual.groupby(["model","station_ssp","climate_ssp","snapshot","year","event"],as_index=False)[fields].sum(min_count=2)
    joint["tech"]="wind+solar"
    annual=pd.concat([annual,joint],ignore_index=True)
    annual["exposure_days"]=annual.capacity_event_hours/24/annual.capacity_mw
    annual["capacity_fraction"]=annual.capacity_mw/annual.catalogue_capacity_mw
    annual.to_csv(DATA/"lcoe_station_exposure_annual_models.csv",index=False)
    decade=annual.groupby(["model","station_ssp","climate_ssp","tech","snapshot"],as_index=False)[
        fields+["exposure_days","capacity_fraction"]].mean()
    np.testing.assert_allclose(decade.exposure_days,decade.capacity_event_hours/24/decade.capacity_mw)
    decade.to_csv(DATA/"lcoe_station_exposure_decadal_models.csv",index=False)
    capacities=[]; inputs=[]
    for s,c in PAIRS.items():
        for snap in (2030,2040,2050):
            path=ROOT/f"data/stations/lcoe/{s}/stations_01deg_{snap}.csv"
            table=pd.read_csv(path);inputs.append(dict(path=str(path),sha256=sha(path)))
            for tech,sub in table.groupby("technology"):
                require(tech in ("wind","solar"),"Unexpected technology")
                capacities.append(dict(station_ssp=s,climate_ssp=c,snapshot=snap,tech=tech,capacity_mw=sub.capacity_mw.sum()))
    capacity=combine(pd.DataFrame(capacities),["station_ssp","climate_ssp","snapshot"],["capacity_mw"])
    check=decade.merge(capacity,on=["station_ssp","climate_ssp","snapshot","tech"],suffixes=("","_full"),validate="many_to_one")
    np.testing.assert_allclose(check.catalogue_capacity_mw,check.capacity_mw_full,rtol=1e-12)
    capacity.to_csv(DATA/"lcoe_station_capacity.csv",index=False)
    coverage=decade.groupby(["station_ssp","climate_ssp","tech","snapshot"],as_index=False)[
        ["capacity_mw","catalogue_capacity_mw","capacity_fraction"]].first()
    coverage.to_csv(DATA/"lcoe_station_exposure_coverage.csv",index=False)
    validation=dict(status="PASSED",annual_rows=len(annual),decadal_rows=len(decade),models=list(MODELS),pairs=PAIRS,
        minimum_time_coverage=float(annual.min_time_coverage.min()),
        minimum_capacity_fraction=float(coverage.capacity_fraction.min()),
        maximum_capacity_fraction=float(coverage.capacity_fraction.max()),
        support="Paired Loss four-model, 30-year common cohort; each station-year event coverage >=99%",
        event_union="Selected labels on jointly valid time; observed 3-hour intervals, no extrapolation",
        combined="Sum technology capacity-event numerators and valid capacity denominators",
        job_id=os.environ.get("SLURM_JOB_ID"),files_read=sum(len(r["sources"]) for r in results),
        indexes=[dict(path=str(p),sha256=sha(p)) for p in (index_path,loss_path)],capacity_inputs=inputs,
        sources=[dict(loss_archive=r["loss_archive"],events=r["sources"]) for r in results])
    (OUT/"lcoe_exposure_validation.json").write_text(json.dumps(validation,indent=2)+"\n")
    print("PASSED",len(annual),len(decade),flush=True)


if __name__=="__main__":
    main()
