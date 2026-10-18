"""Aggregate grid event frequency, duration and synchronous-area SSP contrasts."""
import argparse
import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import write_csv, write_json, digest, require_complete
from paper_figures.common.spatial import countries
from .prepare_ssp_dynamics import OUT, BASE, marker, write_nc
from .analyze_ssp_grid import PAIRS
from .grid_event_dynamics import STAT_NAMES

def longest_observed(flag):
    edges=np.diff(np.r_[False,flag,False].astype("i1"))
    starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
    return int((ends-starts).max())*3 if len(starts) else 0

def pooled_p90(hist):
    total=hist.sum()
    if total==0:return np.nan
    return float(np.searchsorted(np.cumsum(hist),.9*total)*3)

def ensemble(frame, keys, value):
    out=frame.groupby(keys,dropna=False)[value].agg(mean="mean",minimum="min",maximum="max",n_finite="count",n_models="size").reset_index()
    if not out.n_models.eq(4).all():raise ValueError("Missing or duplicate model rows")
    missing=out.n_finite.ne(4)
    out.loc[missing,["mean","minimum","maximum"]]=np.nan
    votes=frame.assign(positive=frame[value]>1e-8,negative=frame[value]<-1e-8).groupby(keys,dropna=False)[["positive","negative"]].sum().reset_index()
    return out.merge(votes,on=keys)

def contrasts(frame, keys, value):
    pieces=[]
    for high,low in PAIRS:
        a=frame[frame.climate_ssp.eq(high)]
        b=frame[frame.climate_ssp.eq(low)]
        pair=a[keys+[value]].merge(b[keys+[value]],on=keys,suffixes=("_high","_low"),validate="one_to_one")
        if len(pair)!=len(a) or len(a)!=len(b):raise ValueError("Unpaired SSP records")
        pair["high"],pair["low"]=high,low
        pair["difference"]=pair[value+"_high"]-pair[value+"_low"]
        pieces.append(pair)
    return pd.concat(pieces,ignore_index=True)

def native_contrasts(root, summary, patches):
    fractions=[];files=[]
    metrics=["starts_per_year","complete_frequency_per_year","mean_complete_hours",
             "annual_max_observed_hours_mean","complete_ge72h_per_year"]
    for tech,patch,snap in itertools.product(TECHS,patches,SNAPSHOTS):
        values=[]
        for model in MODELS:
            by_ssp=[]
            for ssp in SSPS:
                path=root/"shards"/tech/model/ssp/patch/f"cells_{snap}.nc"
                with xr.open_dataset(path) as ds:
                    count=ds.complete_count.values.astype(float)
                    duration=np.divide(ds.complete_steps.values*3.,count,
                                       out=np.full(count.shape,np.nan),where=count>0)
                    by_ssp.append(np.stack([ds.known_starts.values/10,count/10,duration,
                            ds.annual_max_observed_steps_sum.values*3/10,ds.complete_ge72h.values/10]))
                    area=ds.cell_area_km2.values;lat=ds.lat.values;lon=ds.lon.values
                    events=ds.event.values.astype(str)
            values.append(np.stack(by_ssp))
        v=np.stack(values) # model, SSP, metric, event, cell
        differences=np.stack([v[:,SSPS.index(h)]-v[:,SSPS.index(l)] for h,l in PAIRS])
        for pi,(high,low) in enumerate(PAIRS):
            for mi,metric in enumerate(metrics):
                for ei,event in enumerate(events):
                    d=differences[pi,:,mi,ei]
                    ok=np.isfinite(d).all(axis=0)
                    avg=np.where(ok,d,0).mean(axis=0)
                    fractions.append(dict(tech=tech,snapshot=snap,high=high,low=low,
                        metric=metric,event=event,full_area_km2=area.sum(),valid_area_km2=area[ok].sum(),
                        positive_area_km2=area[ok&(avg>1e-8)].sum(),
                        negative_area_km2=area[ok&(avg<-1e-8)].sum(),
                        positive4_area_km2=area[ok&((d>1e-8).sum(axis=0)==4)].sum(),
                        negative4_area_km2=area[ok&((d<-1e-8).sum(axis=0)==4)].sum()))
        target=summary/"native"/tech/f"{patch}_{snap}.nc";target.parent.mkdir(parents=True,exist_ok=True)
        ds=xr.Dataset(dict(difference=(("contrast","model","metric","event","cell"),differences.astype("f4"))),
            coords=dict(contrast=[h+"-"+l for h,l in PAIRS],model=list(MODELS),metric=metrics,
                        event=events,cell=np.arange(len(area)),lat=("cell",lat),lon=("cell",lon),
                        cell_area_km2=("cell",area)))
        write_nc(target,ds);files.append(target)
        print("NATIVE",tech,patch,snap,flush=True)
    f=pd.DataFrame(fractions)
    keys=["tech","snapshot","high","low","metric","event"]
    f=f.groupby(keys,as_index=False).sum(numeric_only=True)
    for name in ("positive","negative","positive4","negative4"):
        f[name+"_fraction"]=f[name+"_area_km2"]/f.valid_area_km2.replace(0,np.nan)
    f["valid_area_fraction"]=f.valid_area_km2/f.full_area_km2
    write_csv(summary/"native_spatial_fractions.csv",f)
    return files


def result_findings(summary, level, diff, decomp, tail_diff, combined):
    """Readable results with paired SSP contrasts and explicit event attribution scope."""
    tech_names={"wind":"风电","solar":"光伏"}
    event_names={"all":"全部事件并集","high_temp":"高温","high_wind":"强风",
                 "hot_humid":"湿热","icing":"结冰","low_resource":"低资源",
                 "cold_highwind":"低温强风","freezing_rain":"冻雨",
                 "high_humidity":"高湿","rainstorm":"暴雨","overlap_correction":"重叠修正"}
    metric_names={"starts_per_year":"频次差（次/格点/年）",
                  "mean_complete_hours":"完整事件平均持时差（小时）",
                  "p95_area_pct":"同步面积P95差（百分点）",
                  "annual_max_observed_hours_mean":"年最长片段差（小时）"}
    country_names={iso:name for iso,name,_ in countries()}
    def region_name(r):
        return country_names.get(r.split(":")[1],r)
    def fmt(v):
        return "未定义" if not np.isfinite(v) else f"{v:+.3f}"
    def table(df):
        return df.to_html(index=False,border=0,escape=True,float_format=lambda v:f"{v:.3f}",na_rep="—")
    d=diff[diff.snapshot.eq(2050)].copy()
    t=tail_diff[tail_diff.snapshot.eq(2050)].copy()
    levels=level.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all'")
    area=combined.query("snapshot == 2050 and event == 'all'").groupby(["tech","region"]).area_km2.mean()
    html=["<h2>结果解读：以SSP路径为自变量</h2>",
          "<p>以下为2050–2059年四模式等权结果；SSP差值先在同一模式内计算。正负号表示前一路径减后一路径，不能预设所有事件都随SSP126→245→585单调增加。</p>"]
    support="、".join(f"{tech_names[t]}{area.loc[(t, 'global:GLOBAL')]/1e6:.3f}百万km²" for t in TECHS)
    html.append(f"<p>全球指正式产品的共同有效网格域（{support}）；同步面积百分比以该域为分母，不以地球全部表面积为分母。</p>")
    for tech in TECHS:
        html.append(f"<h3>{tech_names[tech]}：全球事件并集</h3>")
        rows=[]
        for ssp in SSPS:
            g=levels[levels.tech.eq(tech)&levels.climate_ssp.eq(ssp)].set_index("metric")
            rows.append({"路径":ssp,"暴露（日/年）":g.loc["exposure_days","mean"],
                         "频次（次/格点/年）":g.loc["starts_per_year","mean"],
                         "平均完整持时（小时）":g.loc["mean_complete_hours","mean"],
                         "同步面积P95（%）":g.loc["p95_area_pct","mean"],
                         "同步面积峰值（%）":g.loc["maximum_area_pct","mean"]})
        html.append(table(pd.DataFrame(rows)))
        for high,low in PAIRS:
            sel=d[d.tech.eq(tech)&d.region.eq("global:GLOBAL")&d.high.eq(high)&d.low.eq(low)]
            u=sel[sel.event.eq("all")].set_index("metric")
            clauses=[]
            for metric,label in metric_names.items():
                r=u.loc[metric]
                clauses.append(f'{label}{fmt(r["mean"])}（增加/减少模式数{int(r.positive)}/{int(r.negative)}）')
            html.append(f"<p><b>{high} − {low}</b>："+"；".join(clauses)+"。</p>")
            terms=decomp[(decomp.tech.eq(tech))&(decomp.snapshot.eq(2050))&
                         decomp.region.eq("global:GLOBAL")&decomp.event.eq("all")&
                         decomp.high.eq(high)&decomp.low.eq(low)].set_index("term")["mean"]
            html.append("<p>并集暴露差分解（日/年）：频次项"+
                        fmt(terms["frequency_contribution_days"])+"，持时项"+
                        fmt(terms["duration_contribution_days"])+"，窗口/缺测截断片段项"+
                        fmt(terms["censored_contribution_days"])+"；合计"+
                        fmt(terms["net_difference_days"])+"。</p>")
    native=pd.read_csv(summary/"native_spatial_fractions.csv")
    native=native[native.snapshot.eq(2050)&native.event.eq("all")&
                  native.metric.isin(["starts_per_year","mean_complete_hours","annual_max_observed_hours_mean"])].copy()
    columns={"tech":"技术","high":"前一路径","low":"后一路径","metric":"指标",
             "valid_area_fraction":"有效支持占共同域（%）","positive_fraction":"均值增加面积（%）",
             "negative_fraction":"均值减少面积（%）","positive4_fraction":"四模式一致增加面积（%）",
             "negative4_fraction":"四模式一致减少面积（%）"}
    native["tech"]=native.tech.map(tech_names)
    native["metric"]=native.metric.map({"starts_per_year":"频次","mean_complete_hours":"平均完整持时",
                                       "annual_max_observed_hours_mean":"年最长已观测片段"})
    for column in columns:
        if column.endswith("_fraction"):native[column]*=100
    html += ["<h3>原生格点：SSP差异覆盖多大面积</h3>",
             "<p>以下为全部事件并集的格点差值。增加、减少和四模式同向面积比例的分母为该指标四模式均定义的共同支持；有效支持占共同域单独列出。持时只在两路径都有完整事件的格点上比较。均值差的空间分布与四模式方向一致性分别报告。</p>",
             table(native[list(columns)].rename(columns=columns))]
    html += ["<h3>空间分布与事件构成</h3>",
             "<p>列出全部纬度带，以及共同域面积至少50万km²、并集同步面积P95差增幅和降幅各最大的三个国家。国家筛选用于展示，不代表统计显著性。事件变化列用于对照；其差值不与并集频次、持时或P95作加法。高值时段构成差则可以按事件项与重叠修正求和，等于两路径各自并集高值时段平均面积之差。</p>"]
    patterns=pd.read_csv(summary/"regional_patterns.csv")
    for tech, (high,low) in itertools.product(TECHS,PAIRS):
        sel=d[d.tech.eq(tech)&d.high.eq(high)&d.low.eq(low)]
        pu=sel[sel.event.eq("all")&sel.metric.eq("p95_area_pct")].copy()
        pu["area"]=pu.region.map(area.loc[tech])
        eligible=pu[pu.region.str.startswith("country:")&pu.area.ge(5e5)&
                    ~pu.region.isin(["country:UNASSIGNED","country:AMBIGUOUS"])&
                    pu["mean"].notna()]
        selected=list(pu[pu.region.str.startswith("latitude:")].region)
        selected+=list(eligible[eligible["mean"]>0].nlargest(3,"mean").region)
        selected+=list(eligible[eligible["mean"]<0].nsmallest(3,"mean").region)
        selected=list(dict.fromkeys(selected))
        rows=[];tail_rows=[]
        for region in selected:
            u=sel[sel.event.eq("all")&sel.region.eq(region)].set_index("metric")
            row={"地区":region_name(region)}
            for metric,label in metric_names.items():
                row[label]=u.loc[metric,"mean"]
            p95=u.loc["p95_area_pct"]
            row["P95增加/减少模式数"]=f"{int(p95.positive)}/{int(p95.negative)}"
            pat=patterns[(patterns.tech.eq(tech))&patterns.snapshot.eq(2050)&
                         patterns.region.eq(region)&patterns.high.eq(high)&patterns.low.eq(low)&
                         patterns.metric.eq("p95_area_pct")].iloc[0]
            row["分类事件P95增幅最大"]=event_names.get(pat.largest_event_increase,"—")
            row["分类事件P95降幅最大"]=event_names.get(pat.largest_event_decrease,"—")
            rows.append(row)
            tg=t[t.tech.eq(tech)&t.high.eq(high)&t.low.eq(low)&t.region.eq(region)]
            tr={"地区":region_name(region)}
            for r in tg.itertuples():
                tr[event_names.get(r.event,r.event)]=r.mean
            tail_rows.append(tr)
        html.append(f"<h4>{tech_names[tech]}：{high} − {low}</h4>")
        html.append(table(pd.DataFrame(rows)))
        html.append("<p>对应地区的大范围事件构成差（百分点；每一路径自身的并集P95及以上时段）：</p>")
        html.append(table(pd.DataFrame(tail_rows)))
    html.append("<p>上述归因属于事件构成与频次—持时的统计分解。解释气候物理机制还需要温度、湿度、风速、降水等连续气象量；仅凭事件二值信号不能确认机制。</p>")
    return "\n".join(html)


def build_report(summary, level, diff, decomp, tail, tail_diff, combined):
    names={iso:name for iso,name,_ in countries()}
    def show(frame):
        return frame.to_html(index=False,border=0,float_format=lambda v:f"{v:.3f}",na_rep="—")
    gl=level.query("snapshot == 2050 and region == 'global:GLOBAL'")
    gd=diff.query("snapshot == 2050 and region == 'global:GLOBAL'")
    regional=diff.query("snapshot == 2050 and event == 'all' and high == 'ssp585' and low == 'ssp126'").copy()
    regional["region_name"]=regional.region.map(lambda r:names.get(r.split(":")[1],r))
    main_metrics=["starts_per_year","mean_complete_hours","p90_complete_hours",
                  "annual_max_observed_hours_mean","p95_area_pct","maximum_area_pct",
                  "above20_observed_hours_per_year","above20_longest_observed_hours"]
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SSP事件频次、持时与空间同步性</title>',
          '<style>body{font:16px/1.7 system-ui;max-width:1500px;margin:36px auto;padding:0 24px;color:#24303d}table{border-collapse:collapse;display:block;overflow:auto;font-size:12px;margin:16px 0}td,th{padding:5px 9px;border-bottom:1px solid #ddd;white-space:nowrap;text-align:right}th{background:#eef3f6}details{margin:20px 0}p{max-width:1100px}</style>',
          '<h1>SSP路径对比：事件频次、持续性与空间同步性</h1>',
          '<p>小凯，本分析基于与先前暴露分析相同的原生共同有效格点，风电和光伏分别计算；主比较为2050–2059年三个气候SSP的两两差异，2030和2040年代保留为一致性检查。先逐模式计算，再对四模式等权汇总。</p>',
          '<p>连续事件按三小时相邻信号识别，跨文件和年份保持连续，十年窗口边界以及缺测导致的截断单独记录。全部事件先作时间并集，再识别连续过程。不同事件的次数、平均持时或P95不能相加。</p>',
          '<p>starts_per_year是已知0→1起点的格点面积加权年频次；mean_complete_hours及p90_complete_hours来自完整事件，以格点面积加权事件池统计，前者等于加权总持时除以加权事件数。annual_max_observed_hours_mean是各格点年内最长已观测连续片段的十年面积加权均值，含年界或缺测截断，是观察到的持续性指标。聚合平均持时也受事件发生位置与类型构成变化影响；原生格点差值用于核查局地变化，不能把区域均值增加解释为每个格点的事件都变长。</p>',
          '<p>同步性先按原始时间戳累加47分块的受影响面积，再计算区域分位数。主要面积指标以固定共同域面积为分母，水平单位为百分比、SSP差值单位为百分点；仅在至少99%区域面积有有效信号的时刻统计；未知区域的影响另以p95_area_upper_pct和maximum_area_upper_pct报告上界。above20表示受影响面积超过区域20%，不是统计显著性阈值。阈值以上时长为已观测时长，缺测不被解释为无事件。</p>',
          '<h2>全球：每个事件与事件并集的三个SSP水平</h2>']
    html.insert(-1, result_findings(summary, level, diff, decomp, tail_diff, combined))
    for metric in main_metrics:
        tab=gl[gl.metric.eq(metric)].pivot(index=["tech","event"],columns="climate_ssp",values="mean").reset_index()
        html += [f"<h3>{metric}</h3>",show(tab)]
    html += ['<h2>全球：三组SSP差异与模式一致性</h2>',
             '<p>minimum和maximum为逐模式配对差的最小值与最大值，positive/negative为差值同向模式数；不是置信区间。只有四模式指标均定义时才报告集合均值。</p>',
             show(gd[gd.metric.isin(main_metrics)]),
             '<h2>暴露差异来自频次还是持时</h2>',
             '<p>完整事件暴露 = 完整事件年频次 × 完整事件平均持时。采用对称分解：频次项为频次差乘两路径平均持时，持时项为持时差乘两路径平均频次，再加删失片段暴露差，严格闭合到全部已观测暴露差。分解使用完整事件频次，不把已知起点次数与完整持时混乘。缺少完整事件的路径不强行定义持时或分解。</p>',
             show(decomp.query("snapshot == 2050 and region == 'global:GLOBAL'")),
             '<h2>区域：并集差异的空间分布</h2>',
             show(regional[regional.metric.isin(main_metrics)]),
             '<h2>大范围并集事件由哪些类型构成</h2>',
             '<p>各SSP分别选择并集受影响面积达到本路径P95的有效时刻，在同一组时刻计算每种事件的平均受影响面积及重叠修正。事件项之和加重叠修正严格等于该路径的并集高值时段平均面积。它解释的是各路径自身的大范围事件状态，不能把分类事件P95相加，也不等同于把并集P95差唯一归因给某个事件。</p>',
             show(tail.query("snapshot == 2050 and region == 'global:GLOBAL'")),
             '<p>完整国家、纬度带、各事件和全部三组SSP差异见CSV；原生格点逐模式差值保留在native目录。先前暴露分析中的事件贡献可与本次频次、持时变化对应阅读，但各事件频次差不能直接作为并集频次的可加贡献。</p>',
             '<h2>数据与验证</h2>',
             '<p>检查包括独立逐时参考算法、分块边界不变性、缺测删失、事件并集衔接、完整与删失时长闭合、原生网格暴露复现、逐时面积积分守恒、持时直方图守恒和频次—持时分解闭合。低资源仍使用各路径自身基线；不从二值事件信号推断气象强度或物理因果。</p>',
             '<ul>']
    for name in ["levels.csv","levels_models.csv.gz","contrasts.csv","contrasts_models.csv.gz",
                 "frequency_duration_decomposition.csv","frequency_duration_decomposition_models.csv.gz",
                 "tail_composition.csv","tail_composition_models.csv.gz","tail_contrasts.csv",
                 "native_spatial_fractions.csv","regional_patterns.csv","audit.json"]:
        html.append(f'<li><a href="{name}">{name}</a></li>')
    html+=['</ul><p><a href="../../report.html">前一期SSP暴露分析</a> · <a href="../../event_definitions.json">事件定义与阈值</a></p><p>希望对你有帮助，小凯！</p></html>']
    (summary/"report.html").write_text("\n".join(html))

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument("--output-root",type=Path,default=OUT)
    a=p.parse_args();root=a.output_root;summary=root/"summary";summary.mkdir(parents=True,exist_ok=True)
    patches=require_complete(OUTPUT/"event_summary")["patches"]
    if len(patches)!=47:raise ValueError("Global scope must have 47 patches")
    shards={};base_parts=[];audits=[]
    worker_code={name:digest(BASE/name) for name in
                 ("prepare_ssp_dynamics.py","grid_event_dynamics.py","grid_event_dynamics.c")}
    for tech,model,ssp,patch in itertools.product(TECHS,MODELS,SSPS,patches):
        folder=root/"shards"/tech/model/ssp/patch
        receipt=require_complete(folder)
        if receipt["snapshots"]!=list(SNAPSHOTS):raise ValueError("Incomplete windows")
        if receipt["code"]!=worker_code:raise ValueError("Mixed worker source identities")
        if tuple(receipt[k] for k in ("tech","model","ssp","patch"))!=(tech,model,ssp,patch):
            raise ValueError("Shard identity mismatch")
        shards[tech,model,ssp,patch]=folder;audits.extend(receipt["audits"])
        base_parts.append(pd.read_csv(folder/"regional.csv.gz"))
    keys=["tech","model","climate_ssp","snapshot","region","event"]
    base=pd.concat(base_parts).groupby(keys,as_index=False)[["area_km2",*STAT_NAMES]].sum()
    base["exposure_days"]=base.observed_steps*3/base.area_km2/10/24
    base["starts_per_year"]=base.known_starts/base.area_km2/10
    base["complete_frequency_per_year"]=base.complete_count/base.area_km2/10
    base["mean_complete_hours"]=base.complete_steps*3/base.complete_count.replace(0,np.nan)
    base["complete_exposure_days"]=base.complete_steps*3/base.area_km2/10/24
    base["censored_exposure_days"]=base.censored_steps*3/base.area_km2/10/24
    base["censored_fragment_fraction"]=base.censored_count/(base.complete_count+base.censored_count).replace(0,np.nan)
    base["complete_ge24h_per_year"]=base.complete_ge24h/base.area_km2/10
    base["complete_ge72h_per_year"]=base.complete_ge72h/base.area_km2/10
    base["annual_max_observed_hours_mean"]=base.annual_max_observed_steps_sum*3/base.area_km2/10
    if not np.allclose(base.exposure_days,base.complete_exposure_days+base.censored_exposure_days):
        raise ValueError("Full exposure closure")
    old=pd.read_csv(BASE/"outputs/ssp_grid/levels_models.csv.gz")
    old["region"]=old.scope+":"+old.region
    check=base.merge(old,on=keys,suffixes=("","_reference"),validate="one_to_one")
    if len(check)!=len(base):raise ValueError("Missing regional reference")
    reproduction=float(np.abs(check.exposure_days-check.days_per_year).max())
    if reproduction>1e-4:raise ValueError(f"Regional exposure reference error: {reproduction}")
    sync_rows=[];tail_rows=[]
    for tech,model,ssp,snap in itertools.product(TECHS,MODELS,SSPS,SNAPSHOTS):
        sub=base.query("tech == @tech and model == @model and climate_ssp == @ssp and snapshot == @snap")
        regions=sorted(sub.region.unique());events=["all",*EVENTS[tech]]
        exposure_lookup=sub.set_index(["region","event"]).observed_steps.to_dict()
        area=sub.drop_duplicates("region").set_index("region").loc[regions].area_km2.to_numpy()
        ids={r:i for i,r in enumerate(regions)}
        affected=valid=hist=times=None
        for patch in patches:
            folder=shards[tech,model,ssp,patch]
            with xr.open_dataset(folder/f"sync_{snap}.nc",decode_times=False) as ds:
                ix=np.array([ids[r] for r in ds.region.values.astype(str)])
                if times is None:
                    times=ds.time.values
                    affected=np.zeros((len(times),len(events),len(regions)),dtype="f8")
                    valid=np.zeros((len(times),len(regions)),dtype="f8")
                if not np.array_equal(times,ds.time.values):raise ValueError("Misaligned patch timestamps")
                affected[:,:,ix]+=ds.affected_area_km2.values
                valid[:,ix]+=ds.valid_area_km2.values
            with xr.open_dataset(folder/f"duration_hist_{snap}.nc") as ds:
                ix=np.array([ids[r] for r in ds.region.values.astype(str)])
                if hist is None:hist=np.zeros((len(events),len(regions),ds.sizes["length_steps"]),dtype="f8")
                hist[:,ix,:]+=ds.area_event_count.values
        if not (np.isfinite(affected).all() and np.isfinite(valid).all()):
            raise ValueError("Nonfinite synchronous areas")
        if np.any(affected < -1e-6) or np.any(affected > valid[:,None,:] + 1e-5):
            raise ValueError("Affected area outside valid-area bounds")
        if np.any(valid > area[None,:] + np.maximum(1e-5, area[None,:]*1e-10)):
            raise ValueError("Valid area exceeds fixed support")
        for ri,region in enumerate(regions):
            availability=np.clip(valid[:,ri]/area[ri],0,1)
            covered=availability>=.99-1e-10
            lower=np.clip(affected[:,:,ri]/area[ri]*100,0,100)
            upper=np.minimum(100,lower+(1-availability[:,None])*100)
            if covered.sum()==0:raise ValueError(f"No covered synchronous-area samples: {region}")
            q95=np.quantile(lower[covered,0],.95)
            tail=covered&(lower[:,0]>=q95)
            tail_means=lower[tail].mean(axis=0)
            for ei,event in enumerate(events):
                identity=dict(tech=tech,model=model,climate_ssp=ssp,snapshot=snap,region=region,event=event)
                expected_steps=float(exposure_lookup[region,event])
                if not np.isclose(affected[:,ei,ri].sum(),expected_steps,rtol=1e-9,atol=1e-3):
                    raise ValueError("Global/country time-area conservation")
                stats=dict(p90_complete_hours=pooled_p90(hist[ei,ri]),
                    p95_area_pct=float(np.quantile(lower[covered,ei],.95)),
                    p95_area_upper_pct=float(np.quantile(upper[covered,ei],.95)),
                    maximum_area_pct=float(lower[covered,ei].max()),
                    maximum_area_upper_pct=float(upper[covered,ei].max()),
                    accepted_time_fraction=float(covered.mean()),
                    mean_available_area_fraction=float(availability.mean()),
                    mean_observed_area_pct=float(lower[:,ei].mean()))
                for threshold in (10,20,30):
                    flag=covered&(lower[:,ei]>threshold)
                    stats[f"above{threshold}_observed_hours_per_year"]=float(flag.sum()*3/10)
                    stats[f"above{threshold}_longest_observed_hours"]=float(longest_observed(flag))
                sync_rows.append({**identity,**stats})
                tail_rows.append({**identity,"value":tail_means[ei],"tail_time_fraction":float(tail.mean())})
            tail_rows.append(dict(tech=tech,model=model,climate_ssp=ssp,snapshot=snap,region=region,
                                  event="overlap_correction",value=float(tail_means[0]-tail_means[1:].sum()),
                                  tail_time_fraction=float(tail.mean())))
        print("REDUCED",tech,model,ssp,snap,flush=True)
    sync=pd.DataFrame(sync_rows)
    combined=base.merge(sync,on=keys,validate="one_to_one")
    metrics=["exposure_days","starts_per_year","complete_frequency_per_year","mean_complete_hours",
             "complete_exposure_days","censored_exposure_days","censored_fragment_fraction",
             "complete_ge24h_per_year","complete_ge72h_per_year","annual_max_observed_hours_mean"]+[c for c in sync if c not in keys]
    long=combined.melt(id_vars=keys,value_vars=metrics,var_name="metric",value_name="value")
    write_csv(summary/"levels_models.csv.gz",long)
    level=ensemble(long,[k for k in keys if k!="model"]+["metric"],"value")
    write_csv(summary/"levels.csv",level)
    dk=[k for k in keys if k!="climate_ssp"]+["metric"]
    dif=contrasts(long,dk,"value");write_csv(summary/"contrasts_models.csv.gz",dif)
    diff=ensemble(dif,[k for k in dk if k!="model"]+["high","low"],"difference")
    write_csv(summary/"contrasts.csv",diff)
    decomp=[]
    for high,low in PAIRS:
        kk=[k for k in keys if k!="climate_ssp"]
        pair=combined[combined.climate_ssp.eq(high)].merge(combined[combined.climate_ssp.eq(low)],on=kk,
                suffixes=("_high","_low"),validate="one_to_one")
        f1=pair.complete_frequency_per_year_high;f0=pair.complete_frequency_per_year_low
        d1=pair.mean_complete_hours_high;d0=pair.mean_complete_hours_low
        ff=(f1-f0)*(d1+d0)/2/24;dd=(d1-d0)*(f1+f0)/2/24
        cc=pair.censored_exposure_days_high-pair.censored_exposure_days_low
        net=pair.exposure_days_high-pair.exposure_days_low
        finite=np.isfinite(ff)&np.isfinite(dd)
        if not np.allclose((ff+dd+cc)[finite],net[finite],rtol=1e-8,atol=1e-8):raise ValueError("Frequency-duration decomposition")
        row=pair[kk].copy();row["high"]=high;row["low"]=low
        row["frequency_contribution_days"]=ff;row["duration_contribution_days"]=dd
        row["censored_contribution_days"]=cc;row["net_difference_days"]=net
        decomp.append(row)
    decomp=pd.concat(decomp,ignore_index=True)
    write_csv(summary/"frequency_duration_decomposition_models.csv.gz",decomp)
    dd=decomp.melt(id_vars=[k for k in keys if k!="climate_ssp"]+["high","low"],
        value_vars=["frequency_contribution_days","duration_contribution_days","censored_contribution_days","net_difference_days"],
        var_name="term",value_name="value")
    ds=ensemble(dd,[k for k in keys if k not in ("model","climate_ssp")]+["high","low","term"],"value")
    write_csv(summary/"frequency_duration_decomposition.csv",ds)
    tail=pd.DataFrame(tail_rows);write_csv(summary/"tail_composition_models.csv.gz",tail)
    tk=[k for k in keys if k!="model"]
    ts=ensemble(tail,tk,"value");write_csv(summary/"tail_composition.csv",ts)
    td=contrasts(tail,[k for k in keys if k!="climate_ssp"],"value")
    # Every tail uses all event contributions on the same timestamps.
    for _,g in td.groupby([k for k in keys if k not in ("climate_ssp","event")]+["high","low"]):
        event=g.set_index("event").difference
        if not np.isclose(event.drop("all").sum(),event["all"],atol=1e-8):raise ValueError("Tail composition closure")
    tc=ensemble(td,[k for k in keys if k not in ("climate_ssp","model")]+["high","low"],"difference")
    write_csv(summary/"tail_contrasts.csv",tc)
    patterns=[]
    for ident,g in diff.groupby(["tech","snapshot","region","high","low","metric"]):
        if ident[-1] not in ("starts_per_year","mean_complete_hours","p95_area_pct","annual_max_observed_hours_mean"):continue
        u=g[g.event.eq("all")].iloc[0]
        events=g[g.event.ne("all")&g["mean"].notna()].copy()
        inc=events.sort_values("mean",ascending=False);dec=events.sort_values("mean")
        patterns.append(dict(zip(["tech","snapshot","region","high","low","metric"],ident))|{
            "union_difference":u["mean"],"union_positive_models":u.positive,"union_negative_models":u.negative,
            "largest_event_increase":inc.iloc[0].event if len(inc) and inc.iloc[0]["mean"]>0 else "",
            "largest_increase":float(inc.iloc[0]["mean"]) if len(inc) and inc.iloc[0]["mean"]>0 else 0,
            "largest_event_decrease":dec.iloc[0].event if len(dec) and dec.iloc[0]["mean"]<0 else "",
            "largest_decrease":float(dec.iloc[0]["mean"]) if len(dec) and dec.iloc[0]["mean"]<0 else 0})
    write_csv(summary/"regional_patterns.csv",pd.DataFrame(patterns))
    native_files=native_contrasts(root,summary,patches)
    write_json(summary/"audit.json",dict(status="PASSED",shards=len(shards),models=MODELS,ssps=SSPS,
        snapshots=SNAPSHOTS,patches=patches,regional_exposure_max_error_days=reproduction,
        native_files=len(native_files),minimum_annual_time_coverage=min(x["minimum_annual_time_coverage"] for x in audits),
        method="within-model SSP contrasts; common native support; complete runs and censoring separated",
        worker_code_sha256=worker_code,code_sha256=digest(Path(__file__)),job_id=__import__("os").environ.get("SLURM_JOB_ID"),
        units=dict(frequency="events/grid cell/year (area weighted)",duration="hours",
                   synchrony="percent of fixed common regional area",decomposition="days/year"),
        caveats=["Model agreement is not statistical significance","P95 is not additive across events",
                 "Tail composition compares each SSP's own union-tail timestamps",
                 "Complete duration undefined where no complete events",
                 "Unknown event area represented by availability and lower/upper bounds"]))
    build_report(summary,level,diff,ds,ts,tc,combined)
    marker(summary,native_files=[str(p) for p in native_files],source_shards=len(shards))
    print("SUMMARY PASSED",summary,flush=True)

if __name__=="__main__":
    main()
