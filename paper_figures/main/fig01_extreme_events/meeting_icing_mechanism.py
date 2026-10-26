"""Northern high-latitude cold/humid joint-event diagnostics on native timestamps."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import itertools
import json
import os
import time
from pathlib import Path

import cftime
import netCDF4
import numpy as np
import pandas as pd
import xarray as xr

from paper_figures.config import ROOT, MODELS, SSPS
from paper_figures.common.io import digest, write_json
from utils.data_access.read_extreme_grid import find_records

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/meeting_icing_mechanism"
SHARED = ROOT / "paper_figures/prepare/outputs/grid_events"
SUMS = ["valid_area_steps", "cold_area_steps", "joint_area_steps",
        "temp_area_steps", "rh_area_steps", "expected_area_steps"]
COLORS = dict(zip(SSPS, ["#1d3b6f", "#b77c19", "#9e1b1b"]))

def require(ok, message):
    if not ok:
        raise ValueError(message)

def support(patch):
    masks = []
    for tech in ("wind", "solar"):
        with xr.open_dataset(SHARED / tech / patch / "period_hours.nc") as ds:
            masks.append(ds.common_mask.astype(bool).all("snapshot").values)
            if tech == "wind":
                area, lat, lon = ds.cell_area_km2.values, ds.lat.values, ds.lon.values
            else:
                require(np.array_equal(lat, ds.lat.values) and np.array_equal(lon, ds.lon.values), "Support grid")
    mask = masks[0] & masks[1] & (lat[:, None] >= 60)
    return mask, area, lat, lon

def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    patches = json.loads((ROOT / "paper_figures/prepare/outputs/event_summary/complete.json").read_text())["patches"]
    selected = []
    for patch in patches:
        with xr.open_dataset(SHARED / "wind" / patch / "period_hours.nc") as ds:
            if float(ds.lat.max()) < 60:
                continue
        mask, area, lat, lon = support(patch)
        if mask.any():
            selected.append(dict(patch=patch, n_cells=int(mask.sum()), area_km2=float(area[mask].sum())))
    records = find_records(tech="wind", years=(2015, 2015))
    lookup = {(r["model"], r["climate_scenario"], r["patch"]):r["path"] for r in records}
    jobs = []
    for model, ssp, record in itertools.product(MODELS, SSPS, selected):
        jobs.append(dict(model=model, climate_ssp=ssp, **record, signal_path=lookup[(model,ssp,record["patch"])]))
    write_json(out/"tasks.json", jobs)
    write_json(out/"contract.json", dict(
        scientific_question="Does cold-condition humidity offset or exceed changing cold exposure at 60–90N?",
        periods=[2015,2050], models=MODELS, scenarios=SSPS, backend="Python",
        weighting="Native cell area times valid three-hour samples on wind/solar common spatial support",
        temperature_rule="T < -2 degrees C", humidity_rule="RH >= 85 percent",
        temperature_units="Raw tas interpreted as Kelvin; four-model small-slice reproduction of published wind icing has zero mismatches",
        temperature_validation=dict(patch="R02C08", climate_ssp="ssp126", n_valid_each=2688,
                                    icing_counts=[408,567,607,356], model_order=list(MODELS), mismatches_each=0),
        scope="Native hurs time axis; not re-timed to the solar-product timestamps",
        task_count=len(jobs), patches=selected, archetype="quantitative grid",
        output_format="PNG, complete figure and independent panels"))
    print("PREPARED", len(jobs), "tasks", len(selected), "patches", flush=True)

def time_axis(tas, hurs):
    t, h = tas["time"], hurs["time"]
    cal = getattr(h, "calendar", "standard")
    require(getattr(t, "calendar", "standard") == cal, "Different native calendars")
    require(np.array_equal(t[:],h[:]), "Different time coordinates")
    require(np.array_equal(netCDF4.num2date([0,1],t.units,calendar=cal),
                           netCDF4.num2date([0,1],h.units,calendar=cal)), "Different time unit semantics")
    dates = netCDF4.num2date(h[:],h.units,calendar=cal,only_use_cftime_datetimes=True)
    stamps = netCDF4.date2num(dates,"hours since 2000-01-01",calendar=cal)
    require(np.allclose(np.diff(stamps),3), "Native sampling is not three-hourly")
    return dates, cal

def nominal_month_steps(start, month, cal):
    total = 0.
    for year in range(start, start+10):
        a = cftime.datetime(year,month,1,calendar=cal)
        b = cftime.datetime(year+int(month==12),1 if month==12 else month+1,1,calendar=cal)
        total += (b-a).total_seconds()/10800
    return total

def run_one(index, snapshots, pilot_chunks, out):
    require(bool(os.environ.get("SLURM_JOB_ID")), "Raw input reads require SLURM")
    jobs=json.loads((out/"tasks.json").read_text())
    job=jobs[index]
    model,ssp,patch=job["model"],job["climate_ssp"],job["patch"]
    folder=out/("pilot" if pilot_chunks else "shards")
    folder.mkdir(parents=True,exist_ok=True)
    stem=f"{model}_{ssp}_{patch}"
    started=time.monotonic()
    existing=folder/(stem+".json")
    if existing.exists() and (folder/(stem+".csv")).exists() and not pilot_chunks:
        old=json.loads(existing.read_text())
        if old.get("complete") and old.get("snapshots")==snapshots:
            require(all(old[k]==job[k] for k in ("model","climate_ssp","patch","signal_path")), "Resume identity")
            require(all(Path(v["path"]).stat().st_size==v["size"] for v in old["inputs"].values()), "Resume source size")
            print("REUSE",stem,flush=True)
            return
    with netCDF4.Dataset(job["signal_path"]) as ds:
        prov=json.loads(ds.provenance)["inputs"]
    inputs={v:prov[v] for v in ("tas","hurs")}
    for v, r in inputs.items():
        require(Path(r["path"]).stat().st_size==r["size"], "Input size differs from published provenance: "+v)
    mask,area,lat,lon=support(patch)
    yy,xx=np.where(mask)
    ys,xs=slice(int(yy.min()),int(yy.max())+1),slice(int(xx.min()),int(xx.max())+1)
    local=mask[ys,xs]
    weights=area[ys,xs][local].astype(float)
    rows=[]
    with netCDF4.Dataset(inputs["tas"]["path"]) as tas, netCDF4.Dataset(inputs["hurs"]["path"]) as hurs:
        for ds in (tas,hurs):
            require(np.array_equal(ds["lat"][:],lat) and np.array_equal(ds["lon"][:],lon), "Raw/support coordinates")
        dates,cal=time_axis(tas,hurs)
        years=np.fromiter((d.year for d in dates),dtype=int)
        months=np.fromiter((d.month for d in dates),dtype=int)
        tv,hv=tas["tas"],hurs["hurs"]
        for var in (tv,hv):
            require(var.dimensions==("time","lat","lon"),"Variable dimension order")
            var.set_var_chunk_cache(128*1024**2,1009,.75)
        units=getattr(tv,"units",None)
        require(units in (None,"K","kelvin","Kelvin"),"Unexpected temperature units")
        ranges=[float("inf"),float("-inf"),float("inf"),float("-inf")]
        complete=True
        for snap in snapshots:
            indices=np.flatnonzero((years>=snap)&(years<snap+10))
            require(len(indices)>0 and np.array_equal(indices,np.arange(indices[0],indices[-1]+1)),"Year window")
            totals=np.zeros((12,len(SUMS)),dtype=float)
            sampled=np.zeros(12,dtype=int)
            n_chunks=0
            for chunk_start in range(int(indices[0])//240*240,int(indices[-1])+1,240):
                begin=max(chunk_start,int(indices[0]))
                if pilot_chunks and n_chunks>=pilot_chunks:
                    complete=False
                    break
                end=min(chunk_start+240,int(indices[-1])+1)
                temp=np.ma.filled(tv[begin:end,ys,xs],np.nan)[:,local].astype(np.float64)-273.15
                rh=np.ma.filled(hv[begin:end,ys,xs],np.nan)[:,local].astype(np.float64)
                valid=np.isfinite(temp)&np.isfinite(rh)
                require(not np.any(valid&((rh<0)|(rh>100)|(temp < -100)|(temp>70))),"Physical value range")
                if valid.any():
                    ranges[0]=min(ranges[0],float(temp[valid].min()));ranges[1]=max(ranges[1],float(temp[valid].max()))
                    ranges[2]=min(ranges[2],float(rh[valid].min()));ranges[3]=max(ranges[3],float(rh[valid].max()))
                cold=valid&(temp < -2)
                joint=cold&(rh>=85)
                mm=months[begin:end]
                for month in np.unique(mm):
                    sel=mm==month
                    vv=valid[sel]
                    totals[month-1,0] += np.sum(vv,axis=0,dtype=float)@weights
                    totals[month-1,1] += np.sum(cold[sel],axis=0,dtype=float)@weights
                    totals[month-1,2] += np.sum(joint[sel],axis=0,dtype=float)@weights
                    totals[month-1,3] += np.sum(np.where(vv,temp[sel],0),axis=0,dtype=float)@weights
                    totals[month-1,4] += np.sum(np.where(vv,rh[sel],0),axis=0,dtype=float)@weights
                    sampled[month-1] += int(sel.sum())
                n_chunks+=1
                if n_chunks==1 or n_chunks%30==0:
                    print("READ",model,ssp,patch,snap,n_chunks,round(time.monotonic()-started,2),flush=True)
            window_complete=int(sampled.sum())==len(indices)
            complete &= window_complete
            for month in range(1,13):
                nominal=nominal_month_steps(snap,month,cal)
                totals[month-1,5]=weights.sum()*(nominal if window_complete else sampled[month-1])
                rows.append(dict(model=model,climate_ssp=ssp,patch=patch,snapshot=snap,month=month,
                                 calendar=cal,n_steps=int(sampled[month-1]),n_expected_steps=int(nominal),
                                 area_km2=float(weights.sum()),n_cells=int(mask.sum()),
                                 complete=window_complete,**dict(zip(SUMS,totals[month-1]))))
            rows.append(dict(model=model,climate_ssp=ssp,patch=patch,snapshot=snap,month=0,
                             calendar=cal,n_steps=int(sampled.sum()),
                             n_expected_steps=int(sum(nominal_month_steps(snap,m,cal) for m in range(1,13))),
                             area_km2=float(weights.sum()),n_cells=int(mask.sum()),
                             complete=window_complete,**dict(zip(SUMS,totals.sum(axis=0)))))
    pd.DataFrame(rows).to_csv(folder/(stem+".csv"),index=False)
    write_json(folder/(stem+".json"),dict(**job,task_index=index,snapshots=snapshots,complete=bool(complete),
        inputs=inputs,temperature_units_attribute=units,temperature_conversion="tas Kelvin minus 273.15",
        input_time_equality="Full numeric axes, calendar and decoded [0,1] unit origins match",
        temperature_range_C=ranges[:2],humidity_range_pct=ranges[2:],
        elapsed_seconds=time.monotonic()-started,job_id=os.environ.get("SLURM_JOB_ID"),
        code_sha256=digest(Path(__file__))))
    print("COMPLETE",stem,complete,round(time.monotonic()-started,2),flush=True)

def summary(frame,keys,col):
    return frame.groupby(keys,as_index=False).agg(
        mean=(col,"mean"),minimum=(col,"min"),maximum=(col,"max"),
        n_models=(col,"size"),positive_models=(col,lambda v:int((v>1e-10).sum())),
        negative_models=(col,lambda v:int((v < -1e-10).sum())))

def aggregate(out,snapshots):
    jobs=json.loads((out/"tasks.json").read_text())
    tables=[]
    for job in jobs:
        stem=f'{job["model"]}_{job["climate_ssp"]}_{job["patch"]}'
        meta=json.loads((out/"shards"/(stem+".json")).read_text())
        require(meta["complete"] and meta["snapshots"]==snapshots,"Incomplete/mismatched shard")
        table=pd.read_csv(out/"shards"/(stem+".csv"))
        require(len(table)==len(snapshots)*13 and not table.duplicated(["snapshot","month"]).any(),"Shard matrix")
        require(set(zip(table.snapshot,table.month))==set(itertools.product(snapshots,range(13))),"Shard windows/months")
        tables.append(table)
    patches=pd.concat(tables,ignore_index=True)
    keys=["model","climate_ssp","snapshot","month"]
    levels=patches.groupby(keys,as_index=False)[SUMS].sum()
    require(len(levels)==len(MODELS)*len(SSPS)*len(snapshots)*13,"Model matrix")
    require((levels.valid_area_steps>0).all() and (levels.cold_area_steps>0).all(),"Undefined conditional probability")
    levels["cold_probability"]=levels.cold_area_steps/levels.valid_area_steps
    levels["humid_given_cold"]=levels.joint_area_steps/levels.cold_area_steps
    levels["joint_probability"]=levels.joint_area_steps/levels.valid_area_steps
    levels["mean_temperature_C"]=levels.temp_area_steps/levels.valid_area_steps
    levels["mean_rh_pct"]=levels.rh_area_steps/levels.valid_area_steps
    levels["coverage"]=levels.valid_area_steps/levels.expected_area_steps
    require(levels.coverage.between(.99,1+1e-12).all(),"Invalid area-time coverage")
    require(np.allclose(levels.joint_probability,levels.cold_probability*levels.humid_given_cold),"Joint product identity")
    src=out/"source_data";src.mkdir(exist_ok=True)
    patches.to_csv(src/"patch_moments.csv",index=False)
    levels.to_csv(src/"joint_models.csv",index=False)
    metrics=["cold_probability","humid_given_cold","joint_probability","mean_temperature_C","mean_rh_pct"]
    long=levels.melt(id_vars=keys,value_vars=metrics,var_name="metric",value_name="value")
    summary(long,["climate_ssp","snapshot","month","metric"],"value").to_csv(src/"joint_summary.csv",index=False)
    contrasts=[]
    for snap in snapshots:
        p=levels[(levels.snapshot==snap)&levels.climate_ssp.eq("ssp126")].set_index(["model","month"])
        h=levels[(levels.snapshot==snap)&levels.climate_ssp.eq("ssp585")].set_index(["model","month"])
        d=pd.DataFrame(index=p.index)
        d["joint_difference"]=h.joint_probability-p.joint_probability
        d["cold_probability_contribution"]=(h.cold_probability-p.cold_probability)*(h.humid_given_cold+p.humid_given_cold)/2
        d["conditional_humidity_contribution"]=(h.humid_given_cold-p.humid_given_cold)*(h.cold_probability+p.cold_probability)/2
        for metric in metrics:
            d["change_"+metric]=h[metric]-p[metric]
        d["snapshot"]=snap
        contrasts.append(d.reset_index())
    contrast=pd.concat(contrasts,ignore_index=True)
    error=float((contrast.joint_difference-contrast.cold_probability_contribution-contrast.conditional_humidity_contribution).abs().max())
    require(error<1e-12,"Symmetric factor closure")
    contrast.to_csv(src/"ssp_decomposition_models.csv",index=False)
    dl=contrast.melt(id_vars=["model","snapshot","month"],var_name="term",value_name="value")
    ds=summary(dl,["snapshot","month","term"],"value")
    ds.to_csv(src/"ssp_decomposition_summary.csv",index=False)
    temporal=levels.pivot(index=["model","climate_ssp","month"],columns="snapshot",values=metrics)
    changes=pd.DataFrame({m:temporal[m][2050]-temporal[m][2015] for m in metrics}).reset_index()
    changes.to_csv(src/"temporal_changes_models.csv",index=False)
    summary(changes.melt(id_vars=["model","climate_ssp","month"],var_name="metric",value_name="value"),
            ["climate_ssp","month","metric"],"value").to_csv(src/"temporal_changes_summary.csv",index=False)
    diagnostics = write_diagnostics(out, patches, levels, contrast)
    plot(out,long,contrast)
    write_json(out/"metadata.json",dict(status="PASSED",n_tasks=len(jobs),snapshots=snapshots,
        minimum_coverage=float(levels.coverage.min()),factor_closure_max_error=error,models=MODELS,
        **diagnostics,code_sha256=digest(Path(__file__)),uncertainty="Four-model min-max; not confidence intervals",
        spatial_support="60–90N common wind/solar native cells",time_basis="Native hurs and tas; wind product phase",
        mechanism_scope="Exact probability-factor accounting, not a causal intervention",
        figures=[dict(path=str(p),sha256=digest(p)) for p in sorted(out.glob("icing_*.png"))]))
    print(ds[(ds.snapshot==2050)&(ds.month==0)].to_string(index=False),flush=True)
    print("AGGREGATED",out,flush=True)

def write_diagnostics(out, patches, levels, contrast):
    """Write seasonal accounting and compare native diagnostics with released wind signals."""
    src = out / "source_data"
    month_season = {12:"DJF",1:"DJF",2:"DJF",3:"MAM",4:"MAM",5:"MAM",
                    6:"JJA",7:"JJA",8:"JJA",9:"SON",10:"SON",11:"SON"}
    monthly = levels[levels.month > 0].copy()
    monthly["season"] = monthly.month.map(month_season)
    seasonal = monthly.groupby(["model","climate_ssp","snapshot","season"],as_index=False)[SUMS].sum()
    seasonal["cold_probability"] = seasonal.cold_area_steps / seasonal.valid_area_steps
    seasonal["humid_given_cold"] = seasonal.joint_area_steps / seasonal.cold_area_steps
    seasonal["joint_probability"] = seasonal.joint_area_steps / seasonal.valid_area_steps
    seasonal["mean_temperature_C"] = seasonal.temp_area_steps / seasonal.valid_area_steps
    seasonal["mean_rh_pct"] = seasonal.rh_area_steps / seasonal.valid_area_steps
    seasonal.to_csv(src/"seasonal_joint_models.csv",index=False)
    pieces = []
    for snap in (2015,2050):
        p = seasonal[(seasonal.snapshot == snap)&seasonal.climate_ssp.eq("ssp126")].set_index(["model","season"])
        h = seasonal[(seasonal.snapshot == snap)&seasonal.climate_ssp.eq("ssp585")].set_index(["model","season"])
        d = pd.DataFrame(index=p.index)
        d["joint_difference"] = h.joint_probability-p.joint_probability
        d["cold_probability_contribution"] = (h.cold_probability-p.cold_probability)*(h.humid_given_cold+p.humid_given_cold)/2
        d["conditional_humidity_contribution"] = (h.humid_given_cold-p.humid_given_cold)*(h.cold_probability+p.cold_probability)/2
        annual = levels[(levels.snapshot==snap)&levels.month.eq(0)].set_index(["model","climate_ssp"])
        amodels = p.index.get_level_values("model")
        den_p = annual.xs("ssp126",level="climate_ssp").reindex(amodels).valid_area_steps.to_numpy()
        den_h = annual.xs("ssp585",level="climate_ssp").reindex(amodels).valid_area_steps.to_numpy()
        d["annual_joint_difference_contribution"] = h.joint_area_steps/den_h-p.joint_area_steps/den_p
        d["snapshot"] = snap
        pieces.append(d.reset_index())
    seasons = pd.concat(pieces,ignore_index=True)
    require(np.allclose(seasons.joint_difference,
                        seasons.cold_probability_contribution+seasons.conditional_humidity_contribution,
                        rtol=0,atol=1e-12),"Seasonal factor closure")
    annual_check = contrast[contrast.month.eq(0)].set_index(["model","snapshot"]).joint_difference
    seasonal_check = seasons.groupby(["model","snapshot"]).annual_joint_difference_contribution.sum()
    season_error = float((seasonal_check-annual_check).abs().max())
    require(season_error<1e-12,"Season contributions do not sum to annual joint change")
    seasons.to_csv(src/"seasonal_ssp_decomposition_models.csv",index=False)
    season_summary = summary(seasons.melt(id_vars=["model","snapshot","season"],var_name="term",value_name="value"),
                             ["snapshot","season","term"],"value")
    season_summary.to_csv(src/"seasonal_ssp_decomposition_summary.csv",index=False)

    annual_patches = patches[patches.month.eq(0)]
    areas = annual_patches.groupby(["model","climate_ssp","snapshot"]).area_km2.sum()
    require(float(areas.max()-areas.min())<1e-6,"Spatial support changes between model/scenario/window")
    raw = annual_patches[annual_patches.snapshot.eq(2050)].groupby(
        ["model","climate_ssp","snapshot"],as_index=False)[["joint_area_steps","area_km2"]].sum()
    raw["native_joint_days_per_year"] = raw.joint_area_steps/raw.area_km2/80
    formal = pd.read_csv(BASE/"outputs/ssp_grid/levels_models.csv.gz")
    formal = formal[formal.tech.eq("wind")&formal.scope.eq("latitude")&
                    formal.region.eq("60N-90N")&formal.snapshot.eq(2050)&formal.event.eq("icing")]
    compare = raw.merge(formal[["model","climate_ssp","snapshot","days_per_year","area_km2"]],
                        on=["model","climate_ssp","snapshot"],validate="one_to_one",suffixes=("_native","_published"))
    require(len(compare)==12,"Incomplete published wind comparison")
    require(np.allclose(compare.area_km2_native,compare.area_km2_published,rtol=0,atol=1e-6),
            "Different native/published spatial support")
    compare["native_minus_published_days_per_year"] = compare.native_joint_days_per_year-compare.days_per_year
    macro_error = float(compare.native_minus_published_days_per_year.abs().max())
    require(macro_error < .01,"Published wind aggregate differs by >=0.01 day/year")
    compare.to_csv(src/"published_wind_icing_comparison.csv",index=False)

    report_terms = ["change_mean_temperature_C","change_mean_rh_pct","change_cold_probability",
                    "change_humid_given_cold","joint_difference","cold_probability_contribution",
                    "conditional_humidity_contribution"]
    report = contrast[(contrast.snapshot==2050)&contrast.month.eq(0)][["model"]+report_terms].melt(
        id_vars="model",var_name="term",value_name="value")
    report.loc[~report.term.isin(["change_mean_temperature_C","change_mean_rh_pct"]),"value"] *= 100
    annual_stats = summary(report,["term"],"value")
    annual_stats.to_csv(src/"annual_contrasts_display_units.csv",index=False)
    season_display = season_summary[(season_summary.snapshot==2050)&
                                    season_summary.term.eq("annual_joint_difference_contribution")].copy()
    season_display = season_display.set_index("season").loc[["DJF","MAM","JJA","SON"]].reset_index()
    for col in ("mean","minimum","maximum"):
        season_display[col] *= 100
    month_display = summary(contrast[(contrast.snapshot==2050)&contrast.month.gt(0)],
                            ["month"],"joint_difference")
    for col in ("mean","minimum","maximum"):
        month_display[col] *= 100
    formatter = lambda v:f"{v:.6f}"
    task_meta = [json.loads(p.read_text()) for p in (out/"shards").glob("*.json")]
    contract = json.loads((out/"contract.json").read_text())
    cells = sum(p["n_cells"] for p in contract["patches"])
    report_text = (
        "北纬60–90°冷湿阈值诊断（完整144任务；2015–2024、2050–2059）\n\n"
        f"空间支持：12个patch，{cells:,}个共同有效陆地原生格点，面积{areas.iloc[0]:,.2f} km²。"
        "四模式×三条SSP×两个十年窗口，面积×三小时时刻加权，模式等权。\n"
        "冷条件为T<−2°C；湿条件为RH≥85%；joint是二者同时出现的面积—时间份额。\n"
        "使用原生hurs/tas共同时间轴，时间、日历、格点坐标逐文件校验；不直接复现光伏的插值时间轴。\n"
        "tas原始units属性缺失，按Kelvin转换；四模式代表小切片与已发布wind阈值分类吻合，"
        "原始温度数值范围也支持该单位。完整计算先转float64再减273.15；正式上游为float32转换。\n\n"
        "2050s SSP585−SSP126（概率与贡献为百分点；温度为°C，平均RH为百分点）\n"+
        annual_stats.to_string(index=False,float_format=formatter)+"\n\n"
        "两因子对称分解：冷条件贡献=(cold585−cold126)×(q585+q126)/2；"
        "条件湿度贡献=(q585−q126)×(cold585+cold126)/2；q=P(RH≥85|T<−2)。\n"
        "这是精确统计恒等式。条件湿度项含冷样本构成变化，不等同于独立湿度物理因果效应；"
        "该事件也不是实际覆冰质量或过冷液态水测量。\n\n"
        "四季对全年joint差的贡献（百分点；四项逐模式精确加总到全年净差）\n"+
        season_display[["season","mean","minimum","maximum","positive_models","negative_models"]].to_string(
            index=False,float_format=formatter)+"\n"
        "DJF/MAM/JJA/SON按窗口内日历月份汇总，不是跨年冬季轨迹。季节内两因子分解另见seasonal源表；"
        "其条件概率分母与全年不同，不能将季节内两因子贡献直接无权相加当作全年分解。\n\n"
        "逐月joint路径差（百分点）\n"+
        month_display.to_string(index=False,float_format=formatter)+"\n\n"
        f"覆盖与验收：最小月面积—时间覆盖{levels.coverage.min():.9f}；"
        "CAN/MPI的2015年首个原生三小时时刻缺失已计入覆盖率。"
        f"全年—四季净差闭合误差{season_error:.3e}。\n"
        f"12组2050s北纬wind宏观暴露与正式产品最大绝对差{macro_error:.9f} day/yr"
        f"（{macro_error*86400:.2f}秒/年），详见published_wind_icing_comparison.csv。"
        "微差与上游float32/本诊断float64阈值运算差异相容；未声称逐点完全相等。\n"
        "四模式min–max是模式范围，不是置信区间；方向支持数不等于统计显著性。\n\n"
        "输出：icing_mechanism.png及_a至_f独立PNG；source_data中逐模式、季节、月度、分解、源产品比较表；"
        "caption.txt、metadata.json、visual_review.json。全部原始读取由SLURM完成；汇总与绘图仅读小型缓存。\n")
    (out/"analysis.txt").write_text(report_text)
    (out/"caption.txt").write_text(
        "Cold–humid weather conditions at 60–90°N. The fixed spatial support contains 381,790 common wind/solar "
        "native land grid cells. Values are weighted by grid-cell area and valid three-hour samples on the native tas/hurs "
        "time axis. Cold means T < −2°C and humid means RH ≥ 85%. a–c, Cold probability, humidity exceedance "
        "conditional on cold, and their joint probability for 2015–2024 and 2050–2059. d, Exact symmetric two-factor "
        "accounting of the 2050–2059 SSP585−SSP126 joint-probability difference; circles show individual models and "
        "diamonds show four-model means. e, Monthly joint probability in 2050–2059. f, Monthly factor contributions "
        "and joint differences for the same period. Error bars and shading show the four-model min–max range, not "
        "confidence intervals. Conditional-humidity changes can include changes in the composition of cold samples; "
        "the factor accounting is statistical, not an independent causal attribution of temperature and humidity. "
        "The threshold proxy does not measure actual ice accretion. Raw temperature is interpreted as Kelvin, "
        "validated against released wind-event classifications; aggregate comparison with the released wind product "
        "and the small floating-point precision discrepancy are documented in the source data.\n")
    return dict(n_cells=cells,area_km2=float(areas.iloc[0]),
                seasonal_annual_closure_max_error=season_error,
                published_wind_max_absolute_error_days_per_year=macro_error,
                native_temperature_arithmetic="float64 Kelvin minus 273.15",
                published_temperature_arithmetic="float32; see icing_sampling_audit.json",
                raw_job_ids=sorted({r["job_id"] for r in task_meta}),
                raw_code_sha256=sorted({r["code_sha256"] for r in task_meta}))

def plot(out,long,contrast):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":7,"axes.spines.top":False,"axes.spines.right":False,
                         "axes.linewidth":.6,"legend.frameon":False})
    specs=[("cold_probability","Cold share of area–time (%)"),
           ("humid_given_cold","Humid share of cold conditions (%)"),
           ("joint_probability","Cold–humid share of area–time (%)")]
    def draw(ax,i):
        if i<3:
            metric,title=specs[i]
            a=long[long.metric.eq(metric)&long.month.eq(0)]
            for ssp in SSPS:
                g=a[a.climate_ssp.eq(ssp)].groupby("snapshot").value.agg(["mean","min","max"]).loc[[2015,2050]]*100
                ax.errorbar([0,1],g["mean"],yerr=[g["mean"]-g["min"],g["max"]-g["mean"]],
                            color=COLORS[ssp],marker="o",markersize=3,linewidth=.9,capsize=2,label=ssp.upper())
            ax.set_xticks([0,1],["2015–2024","2050–2059"]);ax.set_xlim(-.15,1.15)
            ax.set_ylabel(title);ax.legend(fontsize=5.8)
        elif i==3:
            terms=["cold_probability_contribution","conditional_humidity_contribution","joint_difference"]
            labels=["Cold share","Humidity within cold","Joint change"]
            g=contrast[(contrast.snapshot==2050)&(contrast.month==0)]
            for j,term in enumerate(terms):
                values=g[term].to_numpy()*100
                ax.hlines(j,values.min(),values.max(),color="#657689",lw=1)
                ax.scatter(values,np.full(4,j),color="#91a3b7",s=12)
                ax.scatter(values.mean(),j,marker="D",s=24,color=["#487A96","#D39A54","#353d46"][j],zorder=3)
            ax.axvline(0,color=".4",lw=.6);ax.set_yticks(range(3),labels);ax.invert_yaxis()
            ax.set_xlabel("SSP585 − SSP126 (percentage points)")
        elif i==4:
            a=long[long.metric.eq("joint_probability")&(long.month>0)&long.snapshot.eq(2050)]
            for ssp in SSPS:
                g=a[a.climate_ssp.eq(ssp)].groupby("month").value.agg(["mean","min","max"])*100
                ax.plot(g.index,g["mean"],color=COLORS[ssp],label=ssp.upper())
                ax.fill_between(g.index,g["min"],g["max"],color=COLORS[ssp],alpha=.12)
            ax.set_xticks([1,4,7,10,12]);ax.set_xlabel("Month");ax.set_ylabel("Cold–humid share of area–time (%)")
            ax.legend(fontsize=5.8)
        else:
            a=contrast[(contrast.snapshot==2050)&(contrast.month>0)]
            for term,label,color in [("cold_probability_contribution","Cold share","#487A96"),
                                    ("conditional_humidity_contribution","Humidity within cold","#D39A54"),
                                    ("joint_difference","Joint change","#353d46")]:
                g=a.groupby("month")[term].mean()*100
                ax.plot(g.index,g.values,color=color,label=label)
            ax.axhline(0,color=".4",lw=.6);ax.set_xticks([1,4,7,10,12])
            ax.set_xlabel("Month");ax.set_ylabel("SSP585 − SSP126 (pp)")
            ax.legend(fontsize=5.6)
        if i>=3:
            ax.set_title(["2050–2059 pathway difference","2050–2059 seasonality","2050–2059 factor contributions"][i-3],fontsize=7)
        ax.grid(axis="y" if i!=3 else "x",lw=.4,color="#e3e8ed")
        ax.text(-.19,1.04,chr(97+i),transform=ax.transAxes,fontweight="bold",fontsize=10)
    fig,axes=plt.subplots(3,2,figsize=(183/25.4,205/25.4))
    fig.text(.5,.012,"Cold: T < −2°C; humid: RH ≥ 85%. Four-model mean and range.",ha="center",fontsize=6.2)
    fig.suptitle("Cold–humid conditions at 60–90°N",fontsize=10,y=.985)
    for i,ax in enumerate(axes.flat):draw(ax,i)
    fig.subplots_adjust(left=.13,right=.98,top=.91,bottom=.07,wspace=.70,hspace=.52)
    fig.savefig(out/"icing_mechanism.png",dpi=600,bbox_inches="tight");plt.close(fig)
    for i in range(6):
        fig,ax=plt.subplots(figsize=(95/25.4,76/25.4));draw(ax,i)
        fig.text(.5,.012,"Cold: T < −2°C; humid: RH ≥ 85%.",ha="center",fontsize=6.2)
        fig.suptitle("60–90°N",fontsize=9,y=.99)
        fig.subplots_adjust(left=.31 if i==3 else .20,right=.97,top=.88,bottom=.22)
        fig.savefig(out/f"icing_mechanism_{chr(97+i)}.png",dpi=600,bbox_inches="tight");plt.close(fig)

def run_task(args):
    return run_one(*args)

def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--prepare",action="store_true");p.add_argument("--aggregate",action="store_true")
    p.add_argument("--task-index",type=int)
    p.add_argument("--batch-index",type=int,default=int(os.environ.get("SLURM_ARRAY_TASK_ID","0")))
    p.add_argument("--batches",type=int,default=8)
    p.add_argument("--pilot-chunks",type=int,default=0)
    p.add_argument("--snapshots",nargs="+",type=int,default=[2015,2050])
    p.add_argument("--output-root",type=Path,default=OUT)
    a=p.parse_args()
    require(a.snapshots==[2015,2050],"Use the two prespecified reference/future decades")
    if a.prepare:prepare(a.output_root)
    elif a.aggregate:aggregate(a.output_root,a.snapshots)
    elif a.task_index is not None:
        run_one(a.task_index,a.snapshots,a.pilot_chunks,a.output_root)
    else:
        jobs=json.loads((a.output_root/"tasks.json").read_text())
        require(0 <= a.batch_index < a.batches, "Invalid batch")
        work=[(index,a.snapshots,a.pilot_chunks,a.output_root)
              for index in range(a.batch_index,len(jobs),a.batches)]
        with ProcessPoolExecutor(max_workers=2,mp_context=get_context("spawn")) as pool:
            list(pool.map(run_task,work))

if __name__=="__main__":
    main()
