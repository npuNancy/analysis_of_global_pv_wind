"""Global station exposure, fixed-cohort transitions and first-appearance cohorts."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys

import netCDF4
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RQ = HERE.parents[1]
sys.path.insert(0, str(RQ/"country/distribution_maps"))
from prepare_country_exposure import validate_cache_source, sha
from grid_common import (MODELS, SSPS, TECHS, cache_dataset, year_hours, write_json,
                         digest_json, configure_logging, LOGGER)

OUTPUT = HERE/"outputs"
INDEX = Path("/work/share/acp6varuz3/extreme_grid/stations_v2/runtime/authoritative_index.json")
YEARS = np.arange(2015,2061)
SNAPSHOTS = np.array([2030,2040,2050])
TRANSITIONS = ("remain_non_high","new_high","remain_high","deescalate")


def weighted_quantile(values, weights, q=0.8):
    valid = np.isfinite(values) & np.isfinite(weights) & (weights>0)
    if not valid.any():
        return np.nan
    x,w = values[valid],weights[valid]
    order=np.argsort(x,kind="stable")
    return float(x[order][np.searchsorted(np.cumsum(w[order]),q*w.sum(),side="left")])


def exposure_summary(days, capacity, threshold=np.nan):
    known=np.isfinite(capacity)&(capacity>0)
    valid=known&np.isfinite(days)
    total=float(capacity[known].sum())
    denom=float(capacity[valid].sum())
    numerator=float(np.dot(days[valid],capacity[valid]))
    high=float(capacity[valid & (days>threshold)].sum()) if np.isfinite(threshold) else np.nan
    return dict(total_capacity_gw=total,valid_capacity_gw=denom,
                station_count=int(known.sum()),valid_station_count=int(valid.sum()),
                capacity_days_gw=numerator,exposure_days=numerator/denom if denom>0 else np.nan,
                capacity_coverage_pct=100*denom/total if total>0 else np.nan,
                high_capacity_gw=high,high_share_pct=100*high/denom if denom>0 else np.nan)


def transition_summary(base, target, weights, threshold):
    valid=np.isfinite(base)&np.isfinite(target)&np.isfinite(weights)&(weights>0)
    total=float(weights[np.isfinite(weights)&(weights>0)].sum())
    denom=float(weights[valid].sum())
    b,t=base>threshold,target>threshold
    masks=(~b&~t,~b&t,b&t,b&~t)
    rows=[]
    for name,mask in zip(TRANSITIONS,masks):
        cap=float(weights[valid&mask].sum())
        rows.append(dict(transition=name,capacity_gw=cap,capacity_share_pct=100*cap/denom if denom>0 else np.nan,
                         station_count=int((valid&mask).sum()),paired_capacity_gw=denom,
                         reference_capacity_gw=total,paired_coverage_pct=100*denom/total if total>0 else np.nan))
    return rows


def raw_check(outputs, column, expected, matched):
    counts=np.zeros(len(YEARS))
    hours=np.zeros(len(YEARS))
    nominal=np.zeros(len(YEARS))
    for item in outputs:
        with netCDF4.Dataset(item["artifact"]["path"]) as ds:
            ds.set_auto_mask(False)
            time=ds["time"]
            calendar=getattr(time,"calendar","standard")
            dates=netCDF4.num2date(time[:],time.units,calendar=calendar)
            year=np.array([d.year for d in dates])
            step=(dates[1]-dates[0]).total_seconds()/3600
            flags=[ds[n][:,column] for n in ds.variables if n.startswith("signal_")]
            valid=np.logical_and.reduce([(f==0)|(f==1) for f in flags])&matched
            any_event=np.logical_or.reduce([f==1 for f in flags])
            for j,y in enumerate(YEARS):
                sel=year==y
                counts[j]+=np.count_nonzero(valid&any_event&sel)*step/24
                hours[j]+=np.count_nonzero(valid&sel)*step
                nominal[j]=year_hours(int(y),calendar)
    values=np.where(hours/nominal>=0.99-1e-8,counts,np.nan)
    if not np.allclose(values,expected,atol=2e-5,equal_nan=True):
        raise ValueError("Raw station series differs from annual cache")
    return dict(column=int(column),matched=bool(matched),years=YEARS.tolist(),
                raw_days=values.tolist(),cache_days=expected.tolist())


def build_station_cache(task):
    model,scenario,tech,records,grids,catalog,capacity_path,identity,outdir=task
    target=Path(outdir)/"cache"/model/f"{scenario}_{tech}.nc"
    receipt=target.with_suffix(".json")
    fingerprint=digest_json({**identity,"model":model,"scenario":scenario,"tech":tech})
    if target.exists() and receipt.exists():
        info=json.loads(receipt.read_text())
        if info.get("fingerprint")==fingerprint and info.get("sha256")==sha(target):
            return str(target)
    cap=pd.read_csv(capacity_path,usecols=["station_id","type","year","capacity_gw"])
    cap=cap[cap.type==tech]
    if set(cap.year)!=set(SNAPSHOTS) or not np.isfinite(cap.capacity_gw).all() or (cap.capacity_gw<0).any():
        raise ValueError("Invalid capacity snapshots")
    cap=cap.groupby(["station_id","year"]).capacity_gw.sum().unstack(fill_value=0)
    catalog_frame=pd.read_csv(catalog["path"]).set_index("station_id")
    chunks=[]
    seen=set()
    checks=[]
    empty=0
    for patch,record in records:
        if record["status"]=="SKIPPED_NO_STATIONS":
            if record["outputs"] or not Path(record["audit"]["path"]).is_file():
                raise ValueError("Missing empty-combination evidence")
            empty+=1
            continue
        if record["status"]!="COMPLETED" or len(record["outputs"])!=10:
            raise ValueError("Incomplete published station combination")
        mapping_path=record["outputs"][0]["contract"]["mapping_file"]["path"]
        with netCDF4.Dataset(mapping_path) as mapping, cache_dataset(grids[patch]) as grid:
            validate_cache_source(grid,record,mapping)
            ids=np.asarray(mapping["station_id"][:],dtype=str)
            if seen.intersection(ids) or len(np.unique(ids))!=len(ids):
                raise ValueError("Duplicate station identities")
            seen.update(ids)
            catalog_rows=catalog_frame.loc[ids]
            activation=np.asarray(mapping["activation_year"][:],dtype=np.int32)
            if not np.array_equal(activation,catalog_rows.activation_year):
                raise ValueError("Activation differs from station catalog")
            capacity=cap.reindex(ids,fill_value=0)[SNAPSHOTS].to_numpy(float).T
            if np.any((capacity>0)&(activation[None,:]>SNAPSHOTS[:,None])):
                raise ValueError("Capacity before first appearance")
            iy=np.asarray(mapping["source_iy"][:])
            ix=np.asarray(mapping["source_ix"][:])
            matched=np.asarray(mapping["mapping_status"][:])==0
            if np.any(matched&((iy<0)|(ix<0)|(iy>=len(grid["lat"]))|(ix>=len(grid["lon"])))):
                raise ValueError("Mapping outside grid dimensions")
            y=np.clip(iy,0,len(grid["lat"])-1)
            x=np.clip(ix,0,len(grid["lon"])-1)
            if not np.all(grid["domain_mask"][:][y[matched],x[matched]]==1):
                raise ValueError("Mapping outside cached domain")
            if not np.allclose(grid["lat"][:][y[matched]],mapping["source_grid_lat"][:][matched],atol=1e-6):
                raise ValueError("Latitude mismatch")
            delta=(grid["lon"][:][x[matched]]-mapping["source_grid_lon"][:][matched]+180)%360-180
            if not np.allclose(delta,0,atol=1e-6):
                raise ValueError("Longitude mismatch")
            if not np.array_equal(grid["year"][:],YEARS):
                raise ValueError("Unexpected cache years")
            event=list(grid["event"][:]).index("any")
            days=np.stack([grid["event_days"][j,event][:][y,x] for j in range(len(YEARS))])
            days[:,~matched]=np.nan
            chunks.append(dict(ids=ids,activation=activation,capacity=capacity,days=days,
                               lon=np.asarray(mapping["lon"][:]),lat=np.asarray(mapping["lat"][:]),
                               matched=matched,patch=np.repeat(patch,len(ids))))
            for flag in (True,False):
                if any(c["matched"]==flag for c in checks):
                    continue
                candidates=np.flatnonzero((matched==flag)&(capacity.max(axis=0)>0))
                if len(candidates):
                    k=int(candidates[0])
                    checks.append({"patch":patch,"station_id":ids[k],**raw_check(record["outputs"],k,days[:,k],flag)})
    if seen!=set(catalog_frame.index) or set(cap.index)-seen:
        raise ValueError("Station inventory and catalog differ")
    def cat(key,axis=0):
        return np.concatenate([c[key] for c in chunks],axis=axis)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(".tmp.nc")
    with netCDF4.Dataset(temp,"w") as ds:
        ds.createDimension("station",len(seen))
        ds.createDimension("year",len(YEARS))
        ds.createDimension("snapshot",len(SNAPSHOTS))
        ds.createVariable("year","i4",("year",))[:]=YEARS
        ds.createVariable("snapshot_year","i4",("snapshot",))[:]=SNAPSHOTS
        for name,key in (("station_id","ids"),("patch","patch")):
            ds.createVariable(name,str,("station",))[:]=cat(key).astype(object)
        for name,key,dtype in (("activation_year","activation","i4"),("lon","lon","f8"),("lat","lat","f8"),("matched","matched","i1")):
            ds.createVariable(name,dtype,("station",),zlib=True)[:]=cat(key)
        ds.createVariable("capacity_gw","f8",("snapshot","station"),zlib=True,complevel=1)[:]=cat("capacity",1)
        v=ds.createVariable("exposure_days","f4",("year","station"),fill_value=np.nan,
                            zlib=True,complevel=1,chunksizes=(1,min(len(seen),8192)))
        v[:]=cat("days",1)
        v.units="days per year"
        ds.setncatts(dict(model=model,scenario=scenario,tech=tech,fingerprint=fingerprint,
                         event="any",min_time_coverage=0.99,activation_mask="off"))
    temp.replace(target)
    write_json(receipt,dict(fingerprint=fingerprint,sha256=sha(target),station_count=len(seen),
                           empty_combinations=empty,raw_checks=checks,code_sha256=sha(__file__)))
    return str(target)


def aggregate_group(path):
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        common=dict(model=ds.model,scenario=ds.scenario,tech=ds.tech)
        days=ds["exposure_days"][:].astype(float)
        cap=ds["capacity_gw"][:]
        activation=ds["activation_year"][:]
    base_index=int(np.flatnonzero(YEARS==2030)[0])
    baseline_weights=np.where(activation==2030,cap[0],0)
    base=days[base_index]
    threshold=weighted_quantile(base,baseline_weights)
    threshold_row={**common,"baseline_year":2030,"quantile":0.8,"threshold_days":threshold,
                   **exposure_summary(base,baseline_weights,threshold)}
    annual,cohort,newbuild,transition=[],[],[],[]
    for j,year in enumerate(YEARS):
        snap=int(year) if year in SNAPSHOTS else None
        if snap is None:
            weights=np.full(cap.shape[1],np.nan)
        else:
            weights=cap[int(np.flatnonzero(SNAPSHOTS==snap)[0])]
        row={**common,"year":int(year),"capacity_snapshot_year":snap,
             "capacity_available":snap is not None,**exposure_summary(days[j],weights,threshold)}
        if snap is None:
            for key in ("total_capacity_gw","valid_capacity_gw","station_count","valid_station_count","capacity_days_gw","high_capacity_gw"):
                row[key]=np.nan
        annual.append(row)
        if year>=2030:
            cohort.append({**common,"year":int(year),"cohort_year":2030,
                           **exposure_summary(days[j],baseline_weights,threshold)})
        if year in SNAPSHOTS:
            k=int(np.flatnonzero(SNAPSHOTS==year)[0])
            weights=np.where(activation==year,cap[k],0)
            newbuild.append({**common,"year":int(year),"threshold_days":threshold,
                             **exposure_summary(days[j],weights,threshold)})
        if year in (2040,2050):
            transition.extend({**common,"year":int(year),"threshold_days":threshold,**r}
                              for r in transition_summary(base,days[j],baseline_weights,threshold))
    return {"annual":annual,"cohort":cohort,"newbuild":newbuild,"transitions":transition,"thresholds":[threshold_row]}


def ensemble(table,keys):
    metrics=[c for c in table.select_dtypes(include=[np.number]).columns if c not in keys]
    rows=[]
    for labels,part in table.groupby(keys,dropna=False,sort=True):
        if not isinstance(labels,tuple):
            labels=(labels,)
        if part.model.nunique()!=4 or len(part)!=4:
            raise ValueError("Ensemble requires one row from each of four models")
        row=dict(zip(keys,labels))
        row["n_models"]=4
        for metric in metrics:
            vals=part[metric].to_numpy(float)
            complete=np.isfinite(vals).all()
            row[metric]=float(vals.mean()) if complete else np.nan
            row[metric+"_min"]=float(vals.min()) if complete else np.nan
            row[metric+"_max"]=float(vals.max()) if complete else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(paths,output):
    tables={k:[] for k in ("annual","cohort","newbuild","transitions","thresholds")}
    for path in paths:
        for key,rows in aggregate_group(path).items():
            tables[key].extend(rows)
    csv=output/"csv"
    csv.mkdir(parents=True,exist_ok=True)
    for key,rows in tables.items():
        data=pd.DataFrame(rows)
        data.to_csv(csv/(key+"_by_model.csv"),index=False)
        keys=["scenario","tech"]+([] if key=="thresholds" else ["year"])+(["transition"] if key=="transitions" else [])
        ensemble(data,keys).to_csv(csv/(key+"_ensemble.csv"),index=False)
    grids=[]
    for model in MODELS:
        p=RQ/f"global/grid/outputs/{model}/csv/annual_exposure.csv"
        data=pd.read_csv(p)
        data=data[data.event=="any"]
        grids.append(data[["model","scenario","tech","year","exposure_days","coverage_pct"]])
    grid=pd.concat(grids,ignore_index=True)
    grid.to_csv(csv/"grid_comparison_by_model.csv",index=False)
    ensemble(grid,["scenario","tech","year"]).to_csv(csv/"grid_comparison_ensemble.csv",index=False)
    # Independent reconciliation with previously generated country caches, including UNASSIGNED.
    country_path=RQ/"country/distribution_maps/outputs/csv/station_country_annual_2050s.csv"
    reconciliation=[]
    if country_path.exists():
        country=pd.read_csv(country_path)
        country=country[country.year==2050].groupby(["model","scenario","tech"]).agg(
            total_capacity_gw=("capacity_gw","sum"),valid_capacity_gw=("valid_capacity_gw","sum"),
            capacity_days_gw=("capacity_days_gw","sum"))
        actual=pd.DataFrame(tables["annual"])
        actual=actual[actual.year==2050].set_index(["model","scenario","tech"])
        for key in country.index:
            a=actual.loc[key]
            c=country.loc[key]
            for metric in ("total_capacity_gw","valid_capacity_gw","capacity_days_gw"):
                if not np.isclose(a[metric],c[metric],rtol=1e-9,atol=1e-5):
                    raise ValueError("Country/global reconciliation failed")
            reconciliation.append(dict(zip(["model","scenario","tech"],key)))
    receipts=[json.loads(Path(p).with_suffix(".json").read_text()) for p in paths]
    write_json(output/"validation.json",dict(cache_groups=len(paths),country_reconciliations=len(reconciliation),
              raw_station_series_checks=sum(len(r["raw_checks"]) for r in receipts),
              raw_annual_checks=sum(len(c["years"]) for r in receipts for c in r["raw_checks"]),
              nonempty_combinations=1128-sum(r["empty_combinations"] for r in receipts),
              empty_combinations=sum(r["empty_combinations"] for r in receipts)))

def plot_outputs(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from PIL import Image
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.titlesize":10,
                         "axes.spines.top":False,"axes.spines.right":False,"legend.frameon":False})
    csv=output/"csv"
    figs=output/"figures"
    figs.mkdir(parents=True,exist_ok=True)
    preview=output/"qa"
    preview.mkdir(parents=True,exist_ok=True)
    tables={key:pd.read_csv(csv/(key+"_ensemble.csv")) for key in
            ("annual","cohort","transitions","newbuild","thresholds","grid_comparison")}
    labels={"ssp126":"SSP1-2.6","ssp245":"SSP2-4.5","ssp585":"SSP5-8.5"}
    names={"wind":"Wind","solar":"Solar PV"}
    blue="#236b8e"
    orange="#c87936"
    saved=[]
    def canvas(title,ylabel):
        fig,axes=plt.subplots(2,3,figsize=(12.5,6.8),sharey="row")
        fig.subplots_adjust(left=0.075,right=0.985,bottom=0.14,top=0.84,hspace=0.42,wspace=0.29)
        fig.suptitle(title,y=0.985,fontsize=14)
        for i,tech in enumerate(TECHS):
            for j,ssp in enumerate(SSPS):
                ax=axes[i,j]
                ax.set_title(f"({chr(97+i*3+j)}) {names[tech]} | {labels[ssp]}",loc="left")
                ax.grid(axis="y",color="#dddddd",linewidth=0.5,zorder=0)
                if j==0:
                    ax.set_ylabel(ylabel)
        return fig,axes
    def subset(key,tech,ssp):
        d=tables[key]
        d=d[(d.tech==tech)&(d.scenario==ssp)]
        return d.sort_values("year") if "year" in d else d
    def series(ax,data,metric,color,label,points=False):
        valid=data[metric].notna()
        d=data[valid]
        x=d.year.to_numpy()
        y=d[metric].to_numpy()
        low=d[metric+"_min"].to_numpy()
        high=d[metric+"_max"].to_numpy()
        if points:
            ax.errorbar(x,y,yerr=np.vstack([y-low,high-y]),fmt="o",color=color,capsize=3,
                        markersize=4,zorder=4,label=label)
        else:
            ax.plot(x,y,color=color,lw=1.6,label=label)
            ax.fill_between(x,low,high,color=color,alpha=0.16,linewidth=0)
    def finish(fig,stem,note):
        fig.text(0.075,0.055,note,fontsize=8,color="#444444")
        path=figs/(stem+".png")
        fig.savefig(path,dpi=300,facecolor="white")
        plt.close(fig)
        with Image.open(path) as im:
            im.thumbnail((1600,1200))
            im.save(preview/(stem+"_preview.png"))
        saved.append(str(path))
    fig,axes=canvas("Global station exposure and grid background","Exposure (days/year)")
    for i,tech in enumerate(TECHS):
        for j,ssp in enumerate(SSPS):
            ax=axes[i,j]
            series(ax,subset("grid_comparison",tech,ssp),"exposure_days",orange,"Grid: area weighted")
            series(ax,subset("annual",tech,ssp),"exposure_days",blue,"Stations: capacity weighted",points=True)
            ax.set_xlim(2015,2060)
            ax.set_xlabel("Year")
    fig.legend(handles=[Line2D([],[],color=orange,label="Grid: area weighted"),
                        Line2D([],[],color=blue,marker="o",label="Stations: capacity weighted")],
               loc="upper center",bbox_to_anchor=(0.5,0.943),ncol=2)
    finish(fig,"global_station_vs_grid",
           "Four-model mean; bands/error bars: model min–max. "+"Station capacity is available only in 2030, 2040 and 2050.")
    fig,axes=canvas("Fixed 2030 location cohort: annual exposure","Exposure (days/year)")
    for i,tech in enumerate(TECHS):
        for j,ssp in enumerate(SSPS):
            ax=axes[i,j]
            series(ax,subset("cohort",tech,ssp),"exposure_days",blue,"Fixed cohort")
            threshold=subset("thresholds",tech,ssp).iloc[0]
            ax.axhline(threshold.threshold_days,color="#777777",ls="--",lw=1)
            ax.set_xlim(2030,2060)
            ax.set_xlabel("Year")
    fig.legend(handles=[Line2D([],[],color=blue,label="2030 capacity weights"),
                        Line2D([],[],color="#777777",ls="--",label="Mean model-specific 2030 P80 threshold")],
               loc="upper center",bbox_to_anchor=(0.5,0.943),ncol=2)
    finish(fig,"global_station_cohort_exposure",
           "Four-model mean and range. Fixed 2030 positions and capacities; annual valid-capacity denominator.")
    fig,axes=canvas("Fixed 2030 cohort: changes in high-exposure status","Paired capacity share (%)")
    transition_labels=["Still\nnon-high","Newly\nhigh","Still\nhigh","Exited\nhigh"]
    for i,tech in enumerate(TECHS):
        for j,ssp in enumerate(SSPS):
            ax=axes[i,j]
            data=subset("transitions",tech,ssp)
            x=np.arange(4)
            for k,(year,color) in enumerate(((2040,blue),(2050,orange))):
                d=data[data.year==year].set_index("transition").loc[list(TRANSITIONS)]
                mean=d.capacity_share_pct.to_numpy()
                ax.bar(x+(k-0.5)*0.34,mean,width=0.32,color=color,zorder=2)
                ax.errorbar(x+(k-0.5)*0.34,mean,
                            yerr=np.vstack([mean-d.capacity_share_pct_min,d.capacity_share_pct_max-mean]),
                            fmt="none",color="#333333",capsize=2,lw=0.8,zorder=3)
            ax.set_xticks(x,transition_labels,fontsize=8)
            ax.set_ylim(0,100)
    fig.legend(handles=[Line2D([],[],color=blue,lw=6,label="2030 → 2040"),
                        Line2D([],[],color=orange,lw=6,label="2030 → 2050")],
               loc="upper center",bbox_to_anchor=(0.5,0.943),ncol=2)
    finish(fig,"global_station_cohort_transitions",
           "Fixed model-specific capacity-weighted 2030 P80; high = exposure > P80. Paired valid stations; 2030 capacity weights.")
    fig,axes=canvas("First-appearance location cohorts: high-exposure capacity","High-exposure capacity share (%)")
    for i,tech in enumerate(TECHS):
        for j,ssp in enumerate(SSPS):
            ax=axes[i,j]
            d=subset("newbuild",tech,ssp)
            y=d.high_share_pct.to_numpy()
            ax.bar(np.arange(3),y,color=blue,width=0.55,zorder=2)
            ax.errorbar(np.arange(3),y,yerr=np.vstack([y-d.high_share_pct_min,d.high_share_pct_max-y]),
                        fmt="none",color="#333333",capsize=3,zorder=3)
            ax.set_xticks(np.arange(3),["2030*","2040","2050"])
            ax.set_xlabel("First appearance in capacity snapshots")
            ax.set_ylim(0,100)
    fig.text(0.5,0.923,"Four-model mean; error bars: model min–max; fixed model-specific 2030 P80",
             ha="center",fontsize=9)
    finish(fig,"global_station_newbuild_high_exposure",
           "*2030 is the baseline inventory. Later cohorts are newly appearing locations, not documented commissioning or expansion at existing locations.")
    fig,axes=canvas("Station exposure: valid-capacity coverage","Valid capacity / total capacity (%)")
    for i,tech in enumerate(TECHS):
        for j,ssp in enumerate(SSPS):
            ax=axes[i,j]
            series(ax,subset("cohort",tech,ssp),"capacity_coverage_pct",orange,"Fixed 2030 cohort")
            series(ax,subset("annual",tech,ssp),"capacity_coverage_pct",blue,"Available fleet",points=True)
            ax.set_xlim(2030,2060)
            ax.set_ylim(0,101)
            ax.set_xlabel("Year")
    fig.legend(handles=[Line2D([],[],color=blue,marker="o",label="Available fleet"),
                        Line2D([],[],color=orange,label="Fixed 2030 cohort")],
               loc="upper center",bbox_to_anchor=(0.5,0.943),ncol=2)
    finish(fig,"global_station_capacity_coverage",
           "Four-model mean and range. Missing mapping or annual temporal coverage <99% reduces valid capacity; missing is not zero exposure.")
    write_json(figs/"figure_manifest.json",{"figures":saved,"dpi":300,"capacity_policy":"snapshots",
               "ensemble":"four-model equal mean; min–max across models","code_sha256":sha(__file__)})
    LOGGER.info("Saved %d figures",len(saved))


def main():
    configure_logging()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=OUTPUT)
    parser.add_argument("--workers",type=int,default=min(16,int(os.environ.get("SLURM_CPUS_PER_TASK","1"))))
    parser.add_argument("--plot-only",action="store_true")
    args=parser.parse_args()
    output=args.output_dir.resolve()
    if args.plot_only:
        plot_outputs(output)
        return
    if args.workers<1 or args.workers>int(os.environ.get("SLURM_CPUS_PER_TASK",str(args.workers))):
        parser.error("Workers must not exceed allocated CPUs")
    index=json.loads(INDEX.read_text())
    grid_path=RQ/"global/grid/outputs/cache_manifest.json"
    manifest=json.loads(grid_path.read_text())
    if index["release"]["index_sha256"]!=manifest["input_index_sha256"]:
        raise ValueError("Grid/station source identity differs")
    if set(manifest["scope"]["models"])!=set(MODELS) or set(manifest["scope"]["ssps"])!=set(SSPS):
        raise ValueError("Full four-model, three-SSP cache required")
    if not np.array_equal(manifest["scope"]["years"],YEARS):
        raise ValueError("Full 2015–2060 grid cache required")
    expected={f"{m}/{s}/{p}/{t}" for m in MODELS for s in SSPS for p in manifest["scope"]["patches"] for t in TECHS}
    if set(index["combinations"])!=expected:
        raise ValueError("Station inventory is incomplete")
    grids={(r["model"],r["scenario"],r["tech"],r["patch"]):r for r in manifest["records"]}
    identity={"station_index":sha(INDEX),"grid_manifest":sha(grid_path),
              "cache_code":hashlib.sha256("".join(inspect.getsource(f) for f in
                  (build_station_cache,raw_check,validate_cache_source)).encode()).hexdigest()}
    tasks=[]
    for model in MODELS:
        for ssp in SSPS:
            cat=index["catalogs"][ssp]
            cp=next(p for p in cat["files"] if p.endswith("capacity_rows.csv.gz"))
            for tech in TECHS:
                records=[(p,index["combinations"][f"{model}/{ssp}/{p}/{tech}"]) for p in manifest["scope"]["patches"]]
                gr={p:grids[model,ssp,tech,p] for p in manifest["scope"]["patches"]}
                tasks.append((model,ssp,tech,records,gr,cat["catalogs"][tech],cp,identity,output))
    paths=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=mp.get_context("spawn")) as pool:
        for path in pool.map(build_station_cache,tasks):
            paths.append(path)
            LOGGER.info("Station annual cache %d/24: %s",len(paths),path)
    summarize(paths,output)
    write_json(output/"cache_manifest.json",{"identity":identity,"years":YEARS.tolist(),"records":paths})
    write_json(output/"run_config.json",{"identity":identity,"capacity_policy":"snapshots",
              "models":MODELS,"ssps":SSPS,"snapshots":SNAPSHOTS.tolist(),"event":"any",
              "cohort":"activation_year first-appearance locations; fixed 2030 capacity",
              "threshold":"model/SSP/technology-specific 2030 capacity-weighted P80; strict >",
              "code_sha256":sha(__file__),"workers":args.workers})
    plot_outputs(output)


if __name__=="__main__":
    main()
