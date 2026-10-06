"""Reconstruct S07 seasons and S09 common baselines by streaming native time blocks."""
import os,json,argparse,multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import cftime
import numpy as np
import pandas as pd
from paper_figures.config import ROOT,MODELS,SSPS,EVENTS
from paper_figures.common.io import write_csv,write_json
from utils.data_access import read_cf_stations as cf_reader,read_extreme_stations as ev_reader,read_loss_stations as loss_reader
OUT=ROOT/"paper_figures/prepare/outputs/supplementary_reconstruction"
SEASONS=["DJF","MAM","JJA","SON"]
def tasks():
    return [(p.parent.parent.name,p.parent.name,p.name,m)
            for p in sorted((ROOT/"paper_figures/prepare/outputs/loss_shards").glob("*/*/*"))
            if p.is_dir() and (p/"station_support.csv.gz").exists() for m in MODELS]
def baseline(records,ids):
    out=None;slots=None;positions={sid:i for i,sid in enumerate(ids)};seen=set()
    for record in records:
        with loss_reader.open_record(record,variables=["station_id","cf_normal"]) as ds:
            rawids=ds.station_id.values.astype(str)
            ix=[i for i,sid in enumerate(rawids) if sid in positions]
            if not ix:continue
            picked=rawids[ix];assert not seen.intersection(picked)
            seen.update(picked)
            values=ds.cf_normal.isel(station=ix).transpose("month_hour_idx","station").values
            if out is None:
                slots=ds.month_hour_idx.values;out=np.full((len(slots),len(ids)),np.nan,dtype="float32")
            assert np.array_equal(slots,ds.month_hour_idx.values)
            out[:,[positions[sid] for sid in picked]]=values
    assert seen==set(ids),"Baseline station coverage mismatch"
    return slots,out
def verify(records,ids,cap,raw,positive,events):
    positions={sid:i for i,sid in enumerate(ids)};seen=set();maximum=0.
    for rec in records:
        names=[prefix+e for prefix in ["net_generation_loss_mwh_","generation_loss_mwh_"] for e in events]
        with loss_reader.open_record(rec,variables=["station_id","capacity_mw",*names]) as ds:
            rawids=ds.station_id.values.astype(str);ix=[i for i,sid in enumerate(rawids) if sid in positions]
            if not ix:continue
            selected=rawids[ix];assert not seen.intersection(selected);seen.update(selected)
            pos=np.array([positions[sid] for sid in selected])
            actualcap=ds.capacity_mw.values[ix]
            assert np.allclose(cap[pos],actualcap,rtol=1e-7,atol=1e-6)
            official=np.column_stack([ds["net_generation_loss_mwh_"+e].values[ix] for e in events])
            official_positive=np.column_stack([ds["generation_loss_mwh_"+e].values[ix] for e in events])
            error=max(float((np.abs(raw[pos]*cap[pos,None]-official)/cap[pos,None]).max()),
                      float((np.abs(positive[pos]*cap[pos,None]-official_positive)/cap[pos,None]).max()))
            scale=float(np.max(np.abs(official/cap[pos,None])))
            if error>max(.002,scale*2e-6):raise ValueError(f"Annual loss reproduction failed: {rec['path']} error={error}")
            maximum=max(maximum,error)
    assert seen==set(ids),"Annual loss station coverage mismatch"
    return maximum
def run(task,probe=False):
    s,t,p,m=task;dest=OUT/s/t/p/m;dest.mkdir(parents=True,exist_ok=True)
    if (dest/"complete.json").exists() and not probe:return
    support=pd.read_csv(ROOT/"paper_figures/prepare/outputs/loss_shards"/s/t/p/"station_support.csv.gz",dtype={"station_id":str})
    support=support[(support.snapshot==2050)&support.common].set_index("station_id")
    if not len(support):
        write_json(dest/"complete.json",{"status":"EMPTY","task":task});return
    if probe:support=support.iloc[:256]
    ids=support.index.to_list();cap=support.capacity_mw.to_numpy();countries=support.country.to_numpy()
    masks={"GLOBAL":np.ones(len(ids),bool),**{x:countries==x for x in sorted(set(countries))}}
    records={};sources=[]
    for c in SSPS:
        kw=dict(model=m,climate_scenario=c,station_scenario=s,tech=t,patch=p)
        records[c]={"base":loss_reader.find_records(**kw,kind="baseline",snapshot_year=2050),
                    "loss":loss_reader.find_records(**kw,snapshot_year=2050),
                    "cf":cf_reader.find_records(**kw,years=(2050,2059)),
                    "ev":ev_reader.find_records(**kw,years=(2050,2059))}
        for kind,recs in records[c].items():sources.extend(dict(kind=kind,climate=c,path=r["path"]) for r in recs)
    slots,b0=baseline(records["ssp126"]["base"],ids);slotmap={int(v):i for i,v in enumerate(slots)}
    seasonal=[];sensitivity=[];checks=[];events=["all",*EVENTS[t]];n=len(ids);ne=len(events)
    for c in SSPS:
        slots_c,bc=baseline(records[c]["base"],ids);assert np.array_equal(slots,slots_c)
        for year in ([2050] if probe else range(2050,2060)):
            cr=[r for r in records[c]["cf"] if r["start_year"]<=year<=r["end_year"]]
            er=[r for r in records[c]["ev"] if r["start_year"]<=year<=r["end_year"]]
            assert len(cr)==len(er)==1
            raw=np.zeros((n,ne));positive=np.zeros_like(raw);season_values=np.zeros((4,n,ne))
            original_shared=np.zeros(n);fixed_values=np.zeros(n);valid_counts=np.zeros(n,dtype=np.int64);both_counts=np.zeros_like(valid_counts)
            with cf_reader.open_record(cr[0],years=(year,year),variables=[t+"_cf"]) as cd, ev_reader.open_record(er[0],years=(year,year),variables=["signal_"+e for e in EVENTS[t]]) as ed:
                cf_positions={sid:i for i,sid in enumerate(cd.station_id.values.astype(str))}
                event_positions={sid:i for i,sid in enumerate(ed.station_id.values.astype(str))}
                cf_index=np.array([cf_positions[sid] for sid in ids])
                event_index=np.array([event_positions[sid] for sid in ids])
                times=cd.time.values;assert np.array_equal(times,ed.time.values),"Native time mismatch"
                calendar=str(cd.time.dt.calendar)
                expected=int((cftime.datetime(year+1,1,1,calendar=calendar)-cftime.datetime(year,1,1,calendar=calendar)).total_seconds()/10800)
                assert len(times)==expected,"Incomplete annual time coverage"
                hours=np.asarray([float(x/np.timedelta64(1,"h")) if isinstance(x,np.timedelta64) else x.total_seconds()/3600 for x in np.diff(times)])
                assert np.all(hours==3),"Non-three-hour time axis"
                months=cd.time.dt.month.values;hh=cd.time.dt.hour.values
                for start in range(0,len(times),240):
                    sl=slice(start,start+240);mm=months[sl]
                    ix=np.array([slotmap[int(v)] for v in mm*100+hh[sl]])
                    cf=cd[t+"_cf"].isel(time=sl).transpose("time","station").values[:,cf_index]
                    normals=bc[ix];fixed=b0[ix]
                    valid=np.isfinite(cf)&np.isfinite(normals);both=valid&np.isfinite(fixed)
                    valid_counts+=valid.sum(0);both_counts+=both.sum(0)
                    flaglist=[]
                    for e in EVENTS[t]:
                        value=ed["signal_"+e].isel(time=sl).transpose("time","station").values[:,event_index]
                        flaglist.append(np.isfinite(value)&(value!=0))
                    flags=np.stack(flaglist,axis=1);flags=np.concatenate([flags.any(axis=1,keepdims=True),flags],axis=1)
                    delta=(normals-cf)*3.;alt=(fixed-cf)*3.
                    for ei in range(ne):
                        values=np.where(flags[:,ei,:]&valid,delta,0)
                        raw[:,ei]+=values.sum(0,dtype=np.float64)
                        positive[:,ei]+=np.maximum(values,0).sum(0,dtype=np.float64)
                        if s=="ssp126" and c in ("ssp126","ssp585"):
                            for si,monthset in enumerate([(12,1,2),(3,4,5),(6,7,8),(9,10,11)]):
                                season_values[si,:,ei]+=values[np.isin(mm,monthset)].sum(0,dtype=np.float64)
                    original_shared+=np.where(flags[:,0,:]&both,delta,0).sum(0,dtype=np.float64)
                    fixed_values+=np.where(flags[:,0,:]&both,alt,0).sum(0,dtype=np.float64)
            assert (both_counts>0).all(),"No common valid time for a retained station"
            maxerr=verify([r for r in records[c]["loss"] if r["start_year"]==year],ids,cap,raw,positive,events)
            checks.append(dict(climate_ssp=c,year=year,batch="full_patch",max_error_per_mw=maxerr,n_stations=n,
                               retained_time_fraction=float(both_counts.sum()/valid_counts.sum()),n_time=len(times)))
            if s=="ssp126" and c in ("ssp126","ssp585"):assert np.allclose(season_values.sum(0),raw,rtol=1e-10,atol=1e-8)
            for country,mask in masks.items():
                capacity=float(cap[mask].sum())
                for label,val in [("original_common_time",original_shared),("fixed_baseline",fixed_values)]:
                    sensitivity.append(dict(model=m,climate_ssp=c,station_ssp=s,tech=t,patch=p,year=year,country=country,
                                            baseline=label,net_mwh=float(np.dot(val[mask],cap[mask])),capacity_mw=capacity,
                                            valid_capacity_hours=float(np.dot(both_counts[mask]*3.,cap[mask]))))
                if s=="ssp126" and c in ("ssp126","ssp585"):
                    for si,season in enumerate(SEASONS):
                        for ei,event in enumerate(events):
                            seasonal.append(dict(model=m,climate_ssp=c,station_ssp=s,tech=t,patch=p,year=year,country=country,event=event,
                                                 season=season,net_mwh=float(np.dot(season_values[si,mask,ei],cap[mask])),capacity_mw=capacity))
            print(task,c,year,"stations",n,"max_error_per_mw",maxerr,flush=True)
    prefix="probe_stream_" if probe else ""
    write_csv(dest/(prefix+"seasonal.csv.gz"),pd.DataFrame(seasonal))
    write_csv(dest/(prefix+"baseline.csv.gz"),pd.DataFrame(sensitivity))
    write_csv(dest/(prefix+"reproduction.csv"),pd.DataFrame(checks))
    write_json(dest/(prefix+"sources.json"),sources)
    write_json(dest/(prefix+"complete.json"),{"status":"COMPLETED","task":task,"checks":len(checks),"time_chunk":240,
                                              "max_error_per_mw":max((x["max_error_per_mw"] for x in checks),default=0)})
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--task",type=int);ap.add_argument("--probe",action="store_true")
    ap.add_argument("--shards",type=int,default=1);ap.add_argument("--workers",type=int,default=4)
    a=ap.parse_args();alltasks=tasks()
    if a.task is not None:run(alltasks[a.task],a.probe);return
    shard=int(os.environ.get("SLURM_ARRAY_TASK_ID","0"));assert 0<=shard<a.shards
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=multiprocessing.get_context("spawn")) as pool:
        for _ in pool.map(run,alltasks[shard::a.shards],chunksize=1):pass
if __name__=="__main__":main()
