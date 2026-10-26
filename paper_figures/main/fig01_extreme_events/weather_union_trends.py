"""Native-interval union of ten weather types and annual SSP comparisons."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr

from paper_figures.config import ROOT, MODELS, SSPS, EVENTS, SSP_COLORS
from utils.data_access.read_extreme_grid import find_records

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/weather_union_trends"
NAMES = {"wind": EVENTS["wind"], "solar": tuple(x for x in EVENTS["solar"] if x != "icing")}
UNITS = "hours since 2000-01-01"
FIELDS = ("union_area_hours", "valid_area_hours", "wind_common_area_hours",
          "solar_selected_common_area_hours", "overlap_area_hours", "wind_native_area_hours",
          "wind_native_valid_area_hours", "expected_area_hours")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    records = find_records(years=(2015, 2060))
    groups = {}
    for r in records:
        key = (r["model"], r["climate_scenario"], r["patch"])
        groups.setdefault(key, {"wind": [], "solar": []})[r["tech"]].append(r)
    tasks = []
    for key, group in sorted(groups.items()):
        for tech in NAMES:
            group[tech].sort(key=lambda r: r["start_year"])
            periods = [(r["start_year"], r["end_year"]) for r in group[tech]]
            if periods != [(y, min(y+4,2060)) for y in range(2015,2061,5)]:
                raise ValueError((key, tech, periods))
        tasks.append(dict(model=key[0], climate_ssp=key[1], patch=key[2], records=group))
    if len(tasks) != 564:
        raise ValueError("Expected four models, three SSPs and 47 patches")
    contract = dict(question="How does the annual union of ten weather types evolve across SSPs?",
        backend="Python/matplotlib", archetype="quantitative grid", years=[2015,2060],
        events=NAMES, icing="Wind-product native 00:00/03:00 timestamps only in the ten-type union",
        temporal_rule="Each published sample represents [t,t+3h); union uses actual interval overlap. The 1.5h breakpoints integrate offset native intervals, not new weather observations or reclassified meteorology.",
        validity="All selected variables must be valid at each overlapping interval; missing periods are excluded, never filled with zero or extrapolated.",
        weighting="Fixed shared land support; native cell area; model metrics before four-model equal-weight mean and min-max.",
        outputs=["weather_union_trend.png","weather_union_comparison.png",
                 "weather_union_comparison_a.png","weather_union_comparison_b.png","weather_union_comparison_c.png"],
        dpi=600, comparison="Panels b/c retain the published wind/PV union and their native time/missingness conventions; c includes the original PV icing.",
        dimensions_mm={"single":[130,85],"comparison":[183,80]},
        index=str(Path(records[0]["index"])), index_sha256=digest(Path(records[0]["index"])))
    write_json(OUT/"tasks.json", tasks)
    write_json(OUT/"figure_contract.json", contract)
    print(json.dumps(dict(tasks=len(tasks), files=len(records))), flush=True)


def support(patch):
    masks=[]
    for tech in ("wind","solar"):
        path=ROOT/"paper_figures/prepare/outputs/grid_events"/tech/patch/"period_hours.nc"
        with xr.open_dataset(path) as ds:
            masks.append(ds.common_mask.astype(bool).all("snapshot").values)
            if tech=="wind":
                lat,lon,area=ds.lat.values,ds.lon.values,ds.cell_area_km2.values
            elif not (np.array_equal(lat,ds.lat.values) and np.array_equal(lon,ds.lon.values)):
                raise ValueError("Spatial axes differ")
    mask=masks[0]&masks[1]
    return lat,lon,mask,area[mask]


def read_union(ds, tech, begin, end, mask):
    shape=(end-begin,int(mask.sum()))
    event=np.zeros(shape,dtype=bool)
    valid=np.ones(shape,dtype=bool)
    for name in NAMES[tech]:
        var=ds["signal_"+name]
        var.set_auto_mask(False)
        var.set_var_chunk_cache(1024**2,101,.5)
        values=np.asarray(var[begin:end])[:,mask]
        good=(values==0)|(values==1)
        if np.any(~good & (values != -127)):
            raise ValueError("Unknown signal encoding")
        event |= values==1
        valid &= good
    return event,valid


def read_aligned(ds, tech, positions, begin, end, mask):
    event = np.zeros((end-begin, int(mask.sum())), dtype=bool)
    valid = np.zeros_like(event)
    lo, hi = np.searchsorted(positions, [begin, end])
    if hi > lo:
        values, observed = read_union(ds, tech, int(lo), int(hi), mask)
        target = positions[lo:hi]-begin
        event[target] = values
        valid[target] = observed
    return event, valid


def half_stats(w, wv, s, sv, weights):
    valid=wv&sv
    both=w&s&valid
    union=(w|s)&valid
    total=lambda x: float(np.dot(np.count_nonzero(x,axis=0),weights))*1.5
    return np.array([total(union),total(valid),total(w&valid),total(s&valid),total(both)])


def self_check():
    # Independent interval enumeration checks phase, overlap and missing-time handling.
    w=np.array([[1,0],[0,1],[1,1],[0,0]],dtype=bool)
    s=np.array([[0,1],[1,0],[1,1],[0,0]],dtype=bool)
    wv=np.ones_like(w);sv=np.ones_like(s);sv[1,0]=False
    weights=np.array([2.,5.])
    previous=np.vstack([np.zeros((1,2),bool),s[:-1]])
    previous_valid=np.vstack([np.zeros((1,2),bool),sv[:-1]])
    actual=half_stats(w,wv,previous,previous_valid,weights)+half_stats(w,wv,s,sv,weights)
    expected=np.zeros(5)
    for t in np.arange(0.,12.,1.5):
        wi=int(t//3)
        si=int(np.floor((t-1.5)/3))
        if si<0:
            continue
        for c,a in enumerate(weights):
            if wv[wi,c] and sv[si,c]:
                x,y=bool(w[wi,c]),bool(s[si,c])
                expected+=1.5*a*np.array([x or y,True,x,y,x and y])
    np.testing.assert_allclose(actual,expected)
    np.testing.assert_allclose(actual[0],actual[2]+actual[3]-actual[4])
    # A wind-only sample has two half-intervals when both sets are observed.
    blank=np.zeros((2,1),bool);full=np.ones((2,1),bool)
    assert half_stats(full,full,blank,full,np.ones(1))[0]*2==6
    print("Interval/overlap/missingness checks passed",flush=True)


def run_task(index, pilot_chunks=0):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Signal-array reads require a SLURM compute node")
    tasks=json.loads((OUT/"tasks.json").read_text())
    task=tasks[index]
    model,ssp,patch=(task[k] for k in ("model","climate_ssp","patch"))
    lat,lon,mask,weights=support(patch)
    area=float(weights.sum());cells=len(weights)
    target=OUT/("pilot" if pilot_chunks else "shards")/f"{model}_{ssp}_{patch}"
    target.mkdir(parents=True,exist_ok=True)
    previous=np.zeros(cells,bool);previous_valid=np.zeros(cells,bool)
    last_end=None;started=time.monotonic();chunks=0
    for wr,sr in zip(task["records"]["wind"],task["records"]["solar"]):
        name=str(wr["start_year"])
        result_file=target/(name+".json");state_file=target/(name+".npz")
        if not pilot_chunks and result_file.exists() and state_file.exists():
            meta=json.loads(result_file.read_text())
            if meta["complete"] and meta["version"]==1:
                with np.load(state_file) as saved:
                    previous=saved["event"];previous_valid=saved["valid"]
                last_end=meta["last_wind_hour"]+3.
                continue
        totals={};chunk_count=0
        with netCDF4.Dataset(wr["path"]) as wd, netCDF4.Dataset(sr["path"]) as sd:
            for ds in (wd,sd):
                if not (np.array_equal(ds["lat"][:],lat) and np.array_equal(ds["lon"][:],lon)):
                    raise ValueError("Signal/support grid differs")
            cal=getattr(wd["time"],"calendar","standard")
            if cal != getattr(sd["time"],"calendar","standard"):
                raise ValueError("Native calendars differ")
            dates=netCDF4.num2date(wd["time"][:],wd["time"].units,calendar=cal,only_use_cftime_datetimes=True)
            solar_dates=netCDF4.num2date(sd["time"][:],sd["time"].units,calendar=cal,only_use_cftime_datetimes=True)
            wt=np.asarray(netCDF4.date2num(dates,UNITS,calendar=cal))
            st=np.asarray(netCDF4.date2num(solar_dates,UNITS,calendar=cal))
            date_type = type(dates[0])
            block_start = float(netCDF4.date2num(date_type(wr["start_year"],1,1), UNITS, calendar=cal))
            block_end = float(netCDF4.date2num(date_type(wr["end_year"]+1,1,1), UNITS, calendar=cal))
            canonical = np.arange(block_start, block_end, 3.)
            positions = []
            for source_times, phase in ((wt,0.), (st,1.5)):
                raw = (source_times-block_start-phase)/3.
                native_index = np.rint(raw).astype(int)
                if (not np.allclose(raw,native_index,rtol=0,atol=1e-7)
                    or np.any(np.diff(native_index)!=1) or native_index[0]<0 or native_index[-1]>=len(canonical)):
                    raise ValueError("Unexpected native phase, internal gap or out-of-window timestamp")
                positions.append(native_index)
            if last_end is not None and not np.isclose(block_start,last_end):
                raise ValueError("Gap or overlap across native calendar windows")
            dates = netCDF4.num2date(canonical, UNITS, calendar=cal, only_use_cftime_datetimes=True)
            years=np.array([d.year for d in dates])
            for begin in range(0,len(canonical),240):
                end=min(begin+240,len(canonical))
                w,wv=read_aligned(wd,"wind",positions[0],begin,end,mask)
                s,sv=read_aligned(sd,"solar",positions[1],begin,end,mask)
                sp=np.vstack([previous[None,:],s[:-1]])
                spv=np.vstack([previous_valid[None,:],sv[:-1]])
                for year in np.unique(years[begin:end]):
                    select=years[begin:end]==year
                    values=half_stats(w[select],wv[select],sp[select],spv[select],weights)
                    values+=half_stats(w[select],wv[select],s[select],sv[select],weights)
                    native=float(np.dot(np.count_nonzero(w[select]&wv[select],axis=0),weights))*3.
                    native_valid=float(np.dot(np.count_nonzero(wv[select],axis=0),weights))*3.
                    values=np.r_[values,native,native_valid,select.sum()*3.*area]
                    totals.setdefault(int(year),np.zeros(len(FIELDS)))
                    totals[int(year)]+=values
                previous=s[-1].copy();previous_valid=sv[-1].copy()
                chunks+=1;chunk_count+=1
                if chunk_count==1 or chunk_count%30==0:
                    print("READ",model,ssp,patch,name,chunk_count,round(time.monotonic()-started,1),flush=True)
                if pilot_chunks and chunks>=pilot_chunks:
                    break
            complete=(end==len(canonical))
            last_end=float(canonical[end-1]+3.)
        rows=[]
        for year,values in sorted(totals.items()):
            if not np.isclose(values[0],values[2]+values[3]-values[4],rtol=1e-11,atol=.1):
                raise ValueError("Union identity did not close")
            if not (values[0]>=max(values[2],values[3])-.1 and values[0]<=values[1]+.1):
                raise ValueError("Union bounds violated")
            rows.append(dict(model=model,climate_ssp=ssp,patch=patch,year=year,area_km2=area,n_cells=cells,
                             calendar=cal,**dict(zip(FIELDS,map(float,values)))))
        with state_file.open("wb") as f:
            np.savez_compressed(f,event=previous,valid=previous_valid)
        write_json(result_file,dict(version=1,complete=complete,task=index,rows=rows,
                                   last_wind_hour=float(last_end-3),sources=[wr,sr],
                                   absent_wind_timestamps=int(len(canonical)-len(wt)),
                                   absent_solar_timestamps=int(len(canonical)-len(st)),
                                   elapsed_seconds=time.monotonic()-started))
        if pilot_chunks:
            print(json.dumps(dict(pilot_seconds=time.monotonic()-started,chunks=chunks,rows=rows)),flush=True)
            return index
        print("BLOCK_COMPLETE",index,name,round(time.monotonic()-started,1),flush=True)
    write_json(target/"complete.json",dict(task=index,complete=True,blocks=10,elapsed_seconds=time.monotonic()-started))
    print("TASK_COMPLETE",index,model,ssp,patch,round(time.monotonic()-started,1),flush=True)
    return index


def aggregate():
    tasks=json.loads((OUT/"tasks.json").read_text())
    rows=[]
    missing_stamps = {"wind": 0, "solar": 0}
    for i,task in enumerate(tasks):
        d=OUT/"shards"/f'{task["model"]}_{task["climate_ssp"]}_{task["patch"]}'
        for r in task["records"]["wind"]:
            value=json.loads((d/(str(r["start_year"])+".json")).read_text())
            if not value["complete"] or value["task"]!=i or value["version"]!=1:
                raise ValueError("Incomplete or inconsistent shard")
            expected=set(range(r["start_year"],r["end_year"]+1))
            if {x["year"] for x in value["rows"]}!=expected:
                raise ValueError("Missing years")
            rows.extend(value["rows"])
            for tech in missing_stamps:
                missing_stamps[tech] += value.get("absent_"+tech+"_timestamps", 0)
    frame=pd.DataFrame(rows)
    if frame.duplicated(["model","climate_ssp","patch","year"]).any() or len(frame)!=564*46:
        raise ValueError("Incomplete patch-year matrix")
    for (calendar, year), part in frame.groupby(["calendar", "year"]):
        base = netCDF4.num2date(0., f"hours since {year}-01-01", calendar=calendar,
                               only_use_cftime_datetimes=True)
        nominal = float(netCDF4.date2num(type(base)(int(year)+1,1,1),
                                        f"hours since {year}-01-01", calendar=calendar))
        if not np.allclose(part.expected_area_hours, nominal*part.area_km2, rtol=1e-10, atol=.1):
            raise ValueError("Annual signal axes do not cover the full native calendar")
    keys=["model","climate_ssp","year"]
    if not frame.groupby(keys).calendar.nunique().eq(1).all():
        raise ValueError("Calendar differs across geographic patches")
    data=frame.groupby(keys,as_index=False)[list(FIELDS)+["area_km2","n_cells"]].sum()
    if not np.allclose(data.area_km2,133258894.86744922) or not data.n_cells.eq(1526295).all():
        raise ValueError("Shared geographic support differs")
    data["exposure_days"]=data.union_area_hours/data.area_km2/24
    data["time_coverage_pct"]=100*data.valid_area_hours/data.expected_area_hours
    if data.time_coverage_pct.min()<99:
        raise ValueError("Insufficient common valid time")
    # Reproduce an independently accepted native wind union using this full signal read.
    previous=BASE/"outputs/meeting_grid/source_data/annual_models.csv"
    original=pd.read_csv(previous)
    wind=original[original.tech.eq("wind")&original.event.eq("all")]
    check=data.merge(wind[keys+["exposure_days"]],on=keys,suffixes=("_new","_published"),validate="one_to_one")
    error=float(np.max(np.abs(check.wind_native_area_hours/check.area_km2/24-check.exposure_days_published)))
    if error>1e-6:
        raise ValueError(f"Native wind validation error: {error}")
    data["panel"]="all"
    native=original[original.event.eq("all")].copy()
    native["panel"]=native.tech.map({"wind":"wind","solar":"pv"})
    combined=pd.concat([data[keys+["panel","exposure_days","time_coverage_pct"]],
                        native[keys+["panel","exposure_days","time_coverage_pct"]]],ignore_index=True)
    summary=combined.groupby(["panel","climate_ssp","year"],as_index=False).agg(
        mean=("exposure_days","mean"),minimum=("exposure_days","min"),maximum=("exposure_days","max"),
        n_models=("exposure_days","size"))
    if not summary.n_models.eq(4).all() or len(summary)!=3*3*46:
        raise ValueError("Incomplete ensemble matrix")
    source=OUT/"source_data";source.mkdir(exist_ok=True)
    frame.to_csv(source/"union_patch_annual.csv.gz",index=False)
    data.to_csv(source/"union_annual_models.csv",index=False)
    combined.to_csv(source/"comparison_annual_models.csv",index=False)
    summary.to_csv(source/"comparison_annual_summary.csv",index=False)
    stats=[]
    for (panel,ssp,model),a in combined.groupby(["panel","climate_ssp","model"]):
        stats.append(dict(panel=panel,climate_ssp=ssp,model=model,
                          slope_days_per_decade=float(np.polyfit(a.year,a.exposure_days,1)[0]*10)))
    pd.DataFrame(stats).to_csv(source/"trend_models.csv",index=False)
    closure=float(np.max(np.abs(data.union_area_hours-data.wind_common_area_hours-data.solar_selected_common_area_hours+data.overlap_area_hours)))
    metadata=dict(status="PASSED",tasks=564,blocks=5640,model_year_rows=len(data),
        area_km2=float(data.area_km2.iloc[0]),n_cells=1526295,
        minimum_time_coverage_pct=float(data.time_coverage_pct.min()),native_wind_max_error_days=error,
        union_closure_area_hours=closure,source_annual_sha256=digest(previous),
        absent_native_timestamps=missing_stamps,
        code_sha256=digest(Path(__file__)),contract=json.loads((OUT/"figure_contract.json").read_text()))
    write_json(OUT/"metadata.json",metadata)
    plot(summary)
    print(json.dumps(metadata,indent=2),flush=True)


def draw(ax, summary, panel, title, letter=None, legend=False, limits=None):
    for ssp in SSPS:
        a=summary[summary.panel.eq(panel)&summary.climate_ssp.eq(ssp)].sort_values("year")
        ax.fill_between(a.year,a.minimum,a.maximum,color=SSP_COLORS[ssp],alpha=.12,lw=0)
        ax.plot(a.year,a["mean"],color=SSP_COLORS[ssp],lw=1.2,label=ssp.upper())
    ax.set_title(title,fontsize=8,loc="left",pad=8)
    if letter:
        ax.text(-.17,1.07,letter,transform=ax.transAxes,fontsize=10,fontweight="bold")
    ax.set(xlim=(2015,2060),xticks=[2015,2030,2045,2060],xlabel="Year",
           ylabel="Annual exposure (day yr"+chr(8315)+chr(185)+")")
    if limits is not None:
        ax.set_ylim(*limits)
    ax.grid(axis="y",color="#e2e6ea",lw=.4)
    ax.tick_params(length=2.5,width=.6)
    if legend:
        ax.legend(frameon=False,fontsize=7,loc="best")


def plot(summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"sans-serif","font.sans-serif":["Arial","DejaVu Sans"],
                         "font.size":7,"axes.spines.top":False,"axes.spines.right":False,
                         "axes.linewidth":.7})
    fig,ax=plt.subplots(figsize=(130/25.4,85/25.4))
    draw(ax,summary,"all","All-weather event union",legend=True)
    fig.subplots_adjust(left=.14,right=.97,bottom=.20,top=.87)
    fig.text(.14,.045,"Four-model mean and range; native-time icing",fontsize=6.5)
    fig.savefig(OUT/"weather_union_trend.png",dpi=600)
    plt.close(fig)
    labels=[("all","All-weather event union"),("wind","Wind-event union"),("pv","PV-event union")]
    lo=float(summary.minimum.min());hi=float(summary.maximum.max());pad=(hi-lo)*.08
    limits=(max(0,lo-pad),hi+pad)
    fig,axes=plt.subplots(1,3,figsize=(183/25.4,80/25.4))
    for i,(panel,title) in enumerate(labels):
        draw(axes[i],summary,panel,title,chr(97+i),limits=limits)
    handles,legend_labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,legend_labels,loc="lower center",bbox_to_anchor=(.5,.06),
               ncol=3,frameon=False,fontsize=7)
    fig.subplots_adjust(left=.075,right=.975,bottom=.28,top=.85,wspace=.45)
    fig.text(.5,.018,"Four-model mean and range; common vertical scale",ha="center",fontsize=6.5)
    fig.savefig(OUT/"weather_union_comparison.png",dpi=600)
    plt.close(fig)
    for i,(panel,title) in enumerate(labels):
        fig,ax=plt.subplots(figsize=(89/25.4,80/25.4))
        draw(ax,summary,panel,title,chr(97+i),legend=True,limits=limits)
        fig.subplots_adjust(left=.20,right=.95,bottom=.17,top=.85)
        fig.savefig(OUT/f"weather_union_comparison_{chr(97+i)}.png",dpi=600)
        plt.close(fig)
    caption=("Annual global area-weighted cumulative event exposure, 2015-2060. "
        "Lines show equal-weight means of four GCMs; shading is their minimum-maximum range, not a confidence interval. "
        "Three colors denote SSP126/245/585. One day is 24 exposure hours, not a calendar day with any event. "
        "Panel a and the standalone chart use the union of ten weather types: five wind-product signals, "
        "including native-time icing, and five solar-product signals excluding solar icing. "
        "Each native 3-hour sample is assigned [t,t+3h); the wind and solar interval starts differ by 90 minutes. "
        "Overlapping portions are counted once, with continuity carried across file and year boundaries. "
        "The 1.5-hour integration breakpoints do not imply higher-resolution observations or new weather threshold calculations. "
        "All selected signals must be observed on the overlapping interval; missing times are excluded without extrapolation. "
        "Panels b and c retain the original native wind/PV union, including original PV icing in c; "
        "their valid-time supports can differ slightly from a. "
        "All panels use the same 1,526,295 land grid cells and native cell-area weights. "
        "Source tables retain each GCM, scenario, year and valid-time coverage.\n")
    (OUT/"caption.txt").write_text(caption)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=["prepare","check","run","aggregate"],default="run")
    p.add_argument("--models",nargs="+",choices=MODELS,default=list(MODELS))
    p.add_argument("--task-index",type=int)
    p.add_argument("--pilot-chunks",type=int,default=0)
    p.add_argument("--batch-index",type=int,default=int(os.environ.get("SLURM_ARRAY_TASK_ID",0)))
    p.add_argument("--batches",type=int,default=8)
    p.add_argument("--workers",type=int,default=16)
    args=p.parse_args()
    if args.mode=="prepare":prepare();return
    if args.mode=="check":self_check();return
    if args.mode=="aggregate":aggregate();return
    if args.task_index is not None:run_task(args.task_index,args.pilot_chunks);return
    tasks=json.loads((OUT/"tasks.json").read_text())
    selected=[i for i,t in enumerate(tasks) if i%args.batches==args.batch_index and t["model"] in args.models]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run_task,i) for i in selected]
        for f in as_completed(futures):f.result()

if __name__=="__main__":
    main()
