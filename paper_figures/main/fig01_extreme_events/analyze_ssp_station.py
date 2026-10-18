"""Compare SSP pathways for capacity-weighted extreme-event exposure and dynamics."""
import argparse
from pathlib import Path
import json
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS
from paper_figures.common.io import write_csv, write_json, require_complete, digest
from .summarize_ssp_dynamics import ensemble
from .analyze_ssp_grid import PAIRS

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/ssp_station"
KEY = ["model", "climate_ssp", "station_ssp", "tech", "snapshot", "region", "event"]
COMPARE = ["model", "tech", "snapshot", "region", "event", "metric"]

def metric_definitions(metrics):
    specs={
      "exposure_days":("天/年","容量加权累计暴露小时除以24；事件并集先按时间合并"),
      "starts_per_year":("次/年","容量加权已知0到1事件起点；窗口左端已有事件不计作已知起点"),
      "complete_frequency_per_year":("次/年","完整事件的容量加权年频次，用于频次与持时分解"),
      "mean_complete_hours":("小时","完整事件池的容量加权总持时除以容量加权事件数"),
      "p90_complete_hours":("小时","完整事件池的容量加权持时P90；三小时时间分辨率"),
      "complete_exposure_days":("天/年","完整事件贡献的累计暴露"),
      "censored_exposure_days":("天/年","窗口或缺测截断片段贡献的已观测暴露"),
      "censored_fragment_fraction":("比例0–1","容量加权删失片段数占完整事件和删失片段总数"),
      "complete_ge24h_per_year":("次/年","完整持时达到24小时的容量加权年频次"),
      "complete_ge72h_per_year":("次/年","完整持时达到72小时的容量加权年频次"),
      "annual_max_observed_hours_mean":("小时","各站年内最长观测连续片段的十年容量加权均值，含年界/缺测截断"),
      "p95_capacity_pct":("%；路径差为百分点","逐时受影响容量占固定共同容量比例的P95"),
      "p95_capacity_upper_pct":("%；路径差为百分点","将未知容量全部视作受影响时的P95上界"),
      "maximum_capacity_pct":("%；路径差为百分点","十年窗口内逐时受影响容量比例的最大值"),
      "maximum_capacity_upper_pct":("%；路径差为百分点","将未知容量全部视作受影响时的最大比例上界"),
      "accepted_time_fraction":("比例0–1","区域有效容量达到固定共同容量99%的时刻比例"),
      "mean_available_capacity_fraction":("比例0–1","逐时有效容量占固定共同容量比例的时间平均"),
      "mean_observed_capacity_pct":("%；路径差为百分点","逐时已观测受影响容量比例的时间平均；与累计暴露积分对应")}
    for t in (10,20,30):
        specs[f"above{t}_observed_hours_per_year"]=("小时/年",f"受影响容量严格超过{t}%且有效容量达到99%的已观测时间")
        specs[f"above{t}_longest_observed_hours"]=("小时",f"满足上述{t}%阈值的最长观测连续片段；缺测/窗口边界可能截断")
    if set(metrics)-set(specs):raise ValueError("Undocumented metrics: "+str(set(metrics)-set(specs)))
    return pd.DataFrame([dict(metric=m,unit=specs[m][0],definition=specs[m][1]) for m in metrics])

def differences(long):
    rows=[]
    for high,low in PAIRS:
        for layout in ["paired", *SSPS]:
            a=long[long.climate_ssp.eq(high)&long.station_ssp.eq(high if layout=="paired" else layout)]
            b=long[long.climate_ssp.eq(low)&long.station_ssp.eq(low if layout=="paired" else layout)]
            d=a[COMPARE+["value"]].merge(b[COMPARE+["value"]],on=COMPARE,suffixes=("_high","_low"),validate="one_to_one",how="outer",indicator=True)
            if not d._merge.eq("both").all():
                # Regions with no capacity in one deployment have no defined paired contrast.
                d=d[d._merge.eq("both")]
            d=d.drop(columns="_merge")
            d["difference"]=d.value_high-d.value_low
            d["high"],d["low"],d["comparison"]=high,low,layout
            rows.append(d)
    return pd.concat(rows,ignore_index=True)

def summarize_diff(d):
    return ensemble(d,[k for k in COMPARE if k!="model"]+["high","low","comparison"],"difference")

def additive_overlap(long, metrics):
    pieces=[long]
    keys=[k for k in KEY if k!="event"]+["metric"]
    selected=long[long.metric.isin(metrics)]
    union=selected[selected.event.eq("all")].set_index(keys).value
    total=selected[selected.event.ne("all")].groupby(keys).value.sum(min_count=1)
    overlap=(union-total).rename("value").reset_index()
    overlap["event"]="overlap_correction"
    pieces.append(overlap)
    return pd.concat(pieces,ignore_index=True)

def cached_levels():
    root=OUTPUT/"event_summary"
    receipt=require_complete(root)
    w=pd.read_csv(root/"window.csv.gz")
    f=pd.read_csv(root/"frequency_duration.csv.gz")
    k=["model","climate_ssp","station_ssp","tech","snapshot","country","event"]
    c=w.merge(f,on=k,suffixes=("","_frequency"),validate="one_to_one")
    if not np.allclose(c.capacity_mw,c.capacity_mw_frequency): raise ValueError("Exposure/frequency supports differ")
    c["region"]=np.where(c.country.eq("GLOBAL"),"global:GLOBAL","country:"+c.country)
    c["exposure_days"]=c.capacity_event_hours/c.capacity_mw/24
    c["starts_per_year"]=c.capacity_starts/c.capacity_mw/10
    c["complete_frequency_per_year"]=c.capacity_complete_events/c.capacity_mw/10
    c["mean_complete_hours"]=c.capacity_duration_hours/c.capacity_complete_events.replace(0,np.nan)
    c["complete_exposure_days"]=c.capacity_duration_hours/c.capacity_mw/10/24
    c["censored_exposure_days"]=c.exposure_days-c.complete_exposure_days
    if c.censored_exposure_days.min() < -1e-7: raise ValueError("Negative censored exposure")
    metrics=["exposure_days","starts_per_year","complete_frequency_per_year","mean_complete_hours","complete_exposure_days","censored_exposure_days"]
    return c[KEY+["capacity_mw"]+metrics],receipt

def decomposition(combined):
    metrics=["complete_frequency_per_year","mean_complete_hours","censored_exposure_days","exposure_days"]
    d=differences(combined.melt(id_vars=KEY,value_vars=metrics,var_name="metric",value_name="value"))
    keys=[k for k in COMPARE if k!="metric"]+["high","low","comparison"]
    tables={m:g.set_index(keys) for m,g in d.groupby("metric")}
    f=tables["complete_frequency_per_year"];h=tables["mean_complete_hours"]
    out=pd.DataFrame(index=f.index)
    out["frequency_days"]=(f.value_high-f.value_low)*(h.value_high+h.value_low)/2/24
    out["duration_days"]=(h.value_high-h.value_low)*(f.value_high+f.value_low)/2/24
    out["censored_days"]=tables["censored_exposure_days"].difference
    out["net_days"]=tables["exposure_days"].difference
    ok=out.notna().all(axis=1)
    error=(out.loc[ok,["frequency_days","duration_days","censored_days"]].sum(axis=1)-out.loc[ok,"net_days"]).abs().max()
    if error>1e-8: raise ValueError("Frequency-duration closure")
    return out.reset_index(),float(error)

def climate_deployment(long):
    keys=COMPARE
    result=[]
    for h,l in PAIRS:
        selected=[]
        for climate,station,label in [(l,l,"ll"),(h,l,"hl"),(l,h,"lh"),(h,h,"hh")]:
            f=long[long.climate_ssp.eq(climate)&long.station_ssp.eq(station)]
            selected.append(f[keys+["value"]].rename(columns={"value":label}).set_index(keys))
        x=pd.concat(selected,axis=1,join="inner").reset_index()
        x["climate_component"]=((x.hl-x.ll)+(x.hh-x.lh))/2
        x["deployment_component"]=((x.lh-x.ll)+(x.hh-x.hl))/2
        x["paired_difference"]=x.hh-x.ll
        finite=x[["climate_component","deployment_component","paired_difference"]].notna().all(axis=1)
        if not np.allclose((x.climate_component+x.deployment_component)[finite],x.paired_difference[finite],atol=1e-8): raise ValueError("Climate/deployment closure")
        x["high"],x["low"]=h,l
        result.append(x)
    return pd.concat(result,ignore_index=True)

def grid_comparison(diff, output):
    grid=pd.read_csv(BASE/"outputs/ssp_grid/levels_models.csv.gz")
    grid["region"]=grid.scope+":"+grid.region
    grid["metric"]="exposure_days";grid["value"]=grid.days_per_year
    dyn=BASE/"outputs/ssp_grid/dynamics/summary/levels_models.csv.gz"
    ready=(dyn.parent/"complete.json").exists()
    if ready:
        require_complete(dyn.parent)
        g=pd.read_csv(dyn)
        g["metric"]=g.metric.str.replace("_area_","_capacity_",regex=False)
        grid=pd.concat([grid[COMPARE+["climate_ssp","value"]],g[g.metric.ne("exposure_days")]],ignore_index=True)
    rows=[]
    for h,l in PAIRS:
        a=grid[grid.climate_ssp.eq(h)];b=grid[grid.climate_ssp.eq(l)]
        p=a[COMPARE+["value"]].merge(b[COMPARE+["value"]],on=COMPARE,suffixes=("_h","_l"),validate="one_to_one")
        p["grid_difference"]=p.value_h-p.value_l;p["high"],p["low"]=h,l
        rows.append(p[COMPARE+["high","low","grid_difference"]])
    matched=diff.merge(pd.concat(rows),on=COMPARE+["high","low"],validate="many_to_one")
    matched["station_minus_grid_difference"]=matched.difference-matched.grid_difference
    tol=1e-8
    matched["same_direction"]=(np.sign(matched.difference.where(matched.difference.abs()>tol,0))==np.sign(matched.grid_difference.where(matched.grid_difference.abs()>tol,0)))&matched.difference.notna()&matched.grid_difference.notna()
    write_csv(output/"station_grid_models.csv.gz",matched)
    keys=[k for k in COMPARE if k!="model"]+["high","low","comparison"]
    a=summarize_diff(matched)
    b=ensemble(matched,keys,"grid_difference").rename(columns={c:"grid_"+c for c in ["mean","minimum","maximum","n_finite","n_models","positive","negative"]})
    a=a.merge(b,on=keys)
    a["same_mean_direction"]=(np.sign(a["mean"])==np.sign(a.grid_mean))&a["mean"].notna()&a.grid_mean.notna()
    write_csv(output/"station_grid.csv",a)
    return a,ready

def regional_patterns(diff):
    keys=["tech","snapshot","region","comparison","high","low","metric"]
    select=diff[diff.metric.isin(["starts_per_year","mean_complete_hours","p90_complete_hours","annual_max_observed_hours_mean","p95_capacity_pct","maximum_capacity_pct"])]
    union=select[select.event.eq("all")][keys+["mean","positive","negative"]].rename(columns={"mean":"union_difference","positive":"union_positive_models","negative":"union_negative_models"})
    events=select[~select.event.isin(["all","overlap_correction"])&select["mean"].notna()]
    for ascending,label in [(False,"increase"),(True,"decrease")]:
        top=events.sort_values("mean",ascending=ascending).drop_duplicates(keys)[keys+["event","mean"]]
        top=top.rename(columns={"event":"largest_event_"+label,"mean":"largest_"+label})
        sign=top["largest_"+label]>0 if label=="increase" else top["largest_"+label]<0
        top.loc[~sign,"largest_event_"+label]=""
        top.loc[~sign,"largest_"+label]=0
        union=union.merge(top,on=keys,how="left",validate="one_to_one")
    return union

def findings_html(levels,diff,drivers,cd):
    def table(d):return d.to_html(index=False,border=0,float_format=lambda x:f"{x:.3f}",na_rep="—")
    main=levels.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all' and metric == 'exposure_days'")
    paired=main[main.climate_ssp.eq(main.station_ssp)].pivot(index="tech",columns="climate_ssp",values="mean")
    d=diff.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all' and metric == 'exposure_days'")
    cd=cd.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all' and metric == 'exposure_days' and high == 'ssp585' and low == 'ssp126'")
    parts=["<h2>主要结果：装机权重会改变路径排序</h2>",table(paired.reset_index()),
           "<p>上表单位为累计暴露天/年，属于气候和装机布局同时变化的配对路径。以下分解和固定布局检查用于判断变化来自哪里。</p>"]
    for tech,name in [("wind","风电"),("solar","光伏")]:
        q=d[d.tech.eq(tech)&d.comparison.eq("paired")&d.high.eq("ssp585")&d.low.eq("ssp126")].iloc[0]
        c=cd[cd.tech.eq(tech)].set_index("term")["mean"]
        fixed=d[d.tech.eq(tech)&d.comparison.ne("paired")&d.high.eq("ssp585")&d.low.eq("ssp126")]
        parts.append(f'<p><b>{name}：</b>SSP585−SSP126配对暴露差为{q["mean"]:+.3f}天/年，模式范围{q.minimum:+.3f}至{q.maximum:+.3f}，{int(q.positive)}个模式增加、{int(q.negative)}个减少。对称分解中气候项为{c["climate_component"]:+.3f}、部署项为{c["deployment_component"]:+.3f}天/年。三个固定装机布局下，气候SSP585−126的四模式平均差介于{fixed["mean"].min():+.3f}与{fixed["mean"].max():+.3f}天/年；这不是每个模式都同向的声明。</p>')
    parts.append("<p>逐事件、全部三组SSP差、区域贡献和模式范围见下表及CSV；不要用SSP585−126一个端点差替代三路径排序。</p>")
    example=drivers.query("snapshot == 2050 and comparison == 'paired' and high == 'ssp585' and low == 'ssp126' and region in ['country:CHN','country:USA','country:DEU','country:IND','country:BRA','country:RUS','country:AUS']")
    parts.extend(["<h3>区域示例与事件来源</h3>",table(example)])
    return "\n".join(parts)

def dynamics_findings_html(output, levels, diff, grid):
    """Readable complete results; no additive attribution of quantiles or counts."""
    from html import escape
    from paper_figures.common.spatial import countries
    event_names={"all":"并集","high_temp":"高温","high_wind":"强风","hot_humid":"湿热","icing":"覆冰","low_resource":"低资源","cold_highwind":"低温强风","freezing_rain":"冻雨","high_humidity":"高湿","rainstorm":"暴雨","overlap_correction":"重叠修正"}
    metric_names={"starts_per_year":"频次（次/年，容量加权）","mean_complete_hours":"完整事件平均持时（小时）","p90_complete_hours":"完整事件持时P90（小时）","annual_max_observed_hours_mean":"年最长观测片段（小时）","p95_capacity_pct":"同步受影响容量P95（%）","maximum_capacity_pct":"同步受影响容量最大值（%）","above20_observed_hours_per_year":"超过20%容量的时长（小时/年）","above20_longest_observed_hours":"超过20%容量的最长片段（小时）"}
    chosen=list(metric_names)
    def table(d):
        return d.to_html(index=False,border=0,float_format=lambda x:f"{x:.3f}",na_rep="—")
    def fmt(x):
        return "未定义" if not np.isfinite(x) else f"{x:+.3f}"
    global_levels=levels.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all'")
    paired=global_levels[global_levels.climate_ssp.eq(global_levels.station_ssp)&global_levels.metric.isin(chosen)]
    global_diff=diff.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all'")
    out=['<h2>新增指标的最终结果：频次、持续性与同步装机</h2>',
         '<p>下面的排序按四模式平均值描述，模式方向数另列；P90为完整事件池的容量加权分位数，年最长为各站年内最长观测片段的容量加权平均，二者含义不同。最大同步比例是十年内的逐模式最大值再平均。</p>']
    wide=paired.pivot(index=["tech","metric"],columns="climate_ssp",values="mean").reset_index()
    wide["metric"]=wide.metric.map(metric_names)
    out.append(table(wide))
    for tech,name in [("wind","风电"),("solar","光伏")]:
        out.append(f"<h3>{name}：三条路径的排序和两两差异</h3>")
        for metric in ["starts_per_year","p90_complete_hours","annual_max_observed_hours_mean","p95_capacity_pct","maximum_capacity_pct"]:
            q=paired[paired.tech.eq(tech)&paired.metric.eq(metric)].sort_values("mean")
            if len(q)!=3:raise ValueError("Missing paired dynamics levels")
            rank=" ≤ ".join(f'{r.climate_ssp.upper()}（{r.mean:.3f}）' for r in q.itertuples())
            delta=global_diff[global_diff.tech.eq(tech)&global_diff.metric.eq(metric)&global_diff.comparison.eq("paired")]
            detail="；".join(f'{r.high.upper()}−{r.low.upper()}：{fmt(r.mean)}（增加{int(r.positive)}/4，减少{int(r.negative)}/4）' for r in delta.itertuples())
            fixed=global_diff[global_diff.tech.eq(tech)&global_diff.metric.eq(metric)&global_diff.comparison.ne("paired")&global_diff.high.eq("ssp585")&global_diff.low.eq("ssp126")]
            out.append(f'<p><b>{metric_names[metric]}</b>：{rank}。{detail}。固定三个布局后的SSP585−126均值范围为{fmt(fixed["mean"].min())}至{fmt(fixed["mean"].max())}。</p>')
    out+=['<h3>每种事件的频次、持时和同步差异</h3>',
          '<p>各事件分别计算，下表按三组路径差并列；不把事件频次或分位数相加。完整四模式范围、固定布局结果在contrasts.csv。</p>']
    events=diff[diff.snapshot.eq(2050)&diff.region.eq("global:GLOBAL")&diff.comparison.eq("paired")&diff.metric.isin(["starts_per_year","mean_complete_hours","p90_complete_hours","p95_capacity_pct"])].copy()
    events["pair"]=events.high+"−"+events.low
    ev=events.pivot(index=["tech","event","metric"],columns="pair",values="mean").reset_index()
    ev["event"]=ev.event.map(event_names);ev["metric"]=ev.metric.map(metric_names)
    out.append(table(ev))
    out+=['<h3>空间规律：纬度带与代表国家</h3>',
          '<p>国家代表集固定为中国、美国、印度、德国、巴西、俄罗斯和澳大利亚，所有国家均保留在CSV。纬度带按站点位置分配并按容量加权。</p>']
    regional=diff[diff.snapshot.eq(2050)&diff.comparison.eq("paired")&diff.event.eq("all")&diff.metric.isin(["starts_per_year","p90_complete_hours","annual_max_observed_hours_mean","p95_capacity_pct"])].copy()
    countries_keep=["country:"+x for x in ["CHN","USA","IND","DEU","BRA","RUS","AUS"]]
    regional=regional[regional.region.str.startswith("latitude:")|regional.region.isin(countries_keep)]
    regional["pair"]=regional.high+"−"+regional.low
    rt=regional.pivot(index=["tech","region","metric"],columns="pair",values="mean").reset_index()
    rt["metric"]=rt.metric.map(metric_names)
    out.append(table(rt))
    tail=pd.read_csv(output/"dynamics/summary/tail_contrasts.csv")
    tail=tail[tail.snapshot.eq(2050)&tail.comparison.eq("paired")&tail.high.eq("ssp585")&tail.low.eq("ssp126")]
    names={iso:name for iso,name,_ in countries()}
    explanations=[]
    for identity,g in tail.groupby(["tech","region"]):
        tech,region=identity
        if region!="global:GLOBAL" and region not in countries_keep and not region.startswith("latitude:"):continue
        values=g.set_index("event")["mean"]
        components=values.drop(["all","overlap_correction"])
        increase=components[components>0].sort_values(ascending=False)
        decrease=components[components<0].sort_values()
        row={"技术":tech,"地区":names.get(region.split(":")[1],region),
             "并集高值时段平均受影响容量差（百分点）":values["all"],
             "最大增加事件":event_names[increase.index[0]] if len(increase) else "无",
             "增加项":increase.iloc[0] if len(increase) else 0,
             "最大减少事件":event_names[decrease.index[0]] if len(decrease) else "无",
             "减少项":decrease.iloc[0] if len(decrease) else 0,
             "重叠修正差":values["overlap_correction"]}
        explanations.append(row)
    out+=['<h3>哪些事件构成大范围同时发生的变化</h3>',
          '<p>每条路径各自选取并集受影响容量达到本路径P95的时刻，在这些时刻统计各事件的平均受影响容量。下表为SSP585−126；全部事件项加重叠修正能闭合到并集高值时段平均容量差。它解释的是高值时段构成，不是并集P95的唯一归因。若P95处有大量相同值，所选时刻可超过5%。</p>',table(pd.DataFrame(explanations))]
    compare=grid[grid.snapshot.eq(2050)&grid.region.eq("global:GLOBAL")&grid.event.eq("all")&grid.comparison.eq("paired")&grid.metric.isin(chosen)].copy()
    out+=['<h3>装机与网格的新增指标是否一致</h3>',
          '<p>mean为装机差，grid_mean为面积加权网格差；同步比例的单位均为百分点，但分别以容量和面积为分母。same_mean_direction仅比较四模式平均差的符号。</p>',
          table(compare[["tech","metric","high","low","mean","grid_mean","same_mean_direction","positive","negative","grid_positive","grid_negative"]])]
    stable=diff[diff.region.eq("global:GLOBAL")&diff.event.eq("all")&diff.comparison.eq("paired")&diff.metric.isin(["exposure_days","starts_per_year","p95_capacity_pct"])].copy()
    stable["pair"]=stable.high+"−"+stable.low
    out+=['<h3>三个年代的路径差是否稳定</h3>',table(stable.pivot(index=["tech","metric","pair"],columns="snapshot",values="mean").reset_index())]
    return "\n".join(out)

def report(output,levels,diff,drivers,decomp,cd,grid,coverage,full,grid_ready):
    def table(d): return d.to_html(index=False,border=0,float_format=lambda x:f"{x:.4f}",na_rep="—")
    gl=levels.query("snapshot == 2050 and region == 'global:GLOBAL'")
    gd=diff.query("snapshot == 2050 and region == 'global:GLOBAL'")
    main=["exposure_days","starts_per_year","mean_complete_hours","p90_complete_hours","annual_max_observed_hours_mean","p95_capacity_pct","maximum_capacity_pct"]
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>装机极端天气 SSP 对比</title><style>body{font:16px/1.7 system-ui;max-width:1500px;margin:32px auto;padding:24px;color:#253340}table{display:block;overflow:auto;border-collapse:collapse;font-size:12px}td,th{padding:6px;border-bottom:1px solid #ddd;white-space:nowrap}th{background:#edf2f5}details{margin:20px 0}</style>',
    '<h1>装机极端天气：SSP路径之间的差异</h1>',
    '<p>小凯，以同年代SSP路径差为主问题，逐事件及时间并集分别比较。2050–2059为主窗口，2030与2040年代为稳定性检查；风电和光伏分开，先逐模式计算差值，再汇总四模式。</p>',
    '<p><b>计算状态：</b>'+("全部装机指标完成。" if full else "暴露、频次和完整事件平均持时已完成；持时尾部、年最长及同步装机指标尚待三小时序列计算。")+(" 网格动态指标已可配对。" if grid_ready else " 网格动态指标仍待上游完成；当前网格对照仅含暴露。")+'</p>',
    '<p>paired表示气候SSP与装机SSP配对变化；ssp126/ssp245/ssp585表示固定该装机布局，只改变气候SSP。装机SSP585的原始文件名称为SSP5-6.0；它是数据流程中的布局标签，不等同于SSP5-8.5气候强迫。</p>',
    '<p>容量为2030/2040/2050总装机快照，各自固定用于对应十年。单位装机暴露=容量×暴露小时数的总和÷总容量；除24后为累计天/年。频次采用容量加权已知起点次数；平均持时和P90采用容量加权完整事件池。不同场站SSP的站点不强行按ID一一配对。共同支持来自已验证的场站汇总缓存，在每个固定布局内跨四模式、三个气候SSP保持一致；覆盖表列出相对于完整布局容量的保留率。跨布局差也可能包含支持差异。</p>',
    '<p>并集先对三小时信号作逻辑或再识别过程。暴露事件项之和加重叠修正严格闭合到并集。各类频次、平均持时和P95不能相加；区域动态表中的最大增减事件仅表示相关事件差异，不是并集指标的可加因果归因。四模式同向不代表统计显著性。</p>',
    '<h2>全球配对路径水平</h2>',
    table(gl[gl.climate_ssp.eq(gl.station_ssp)&gl.metric.isin(main)].pivot(index=["tech","event","metric"],columns="climate_ssp",values="mean").reset_index()),
    '<h2>全球三组路径差及固定布局比较</h2>',table(gd[gd.metric.isin(main)]),
    '<h2>地区暴露差异：哪些事件推动、哪些抵消</h2>',table(drivers.query("snapshot == 2050 and comparison == 'paired'")),
    '<h2>暴露差异的频次与持时分解</h2><p>完整事件暴露等于完整频次乘平均持时。采用对称分解，加上删失片段差后严格闭合到总暴露差；没有完整事件时持时和分解留空。</p>',table(decomp.query("snapshot == 2050 and region == 'global:GLOBAL'")),
    '<h2>气候与部署变化的对称分解</h2><p>气候项为两种布局下气候差的平均，部署项为两种气候下布局差的平均，两项之和等于配对路径差。这是所给情景矩阵的核算分解。部署项衡量空间布局和相对容量权重的变化；各站容量同比例缩放时，单位装机指标保持相同。</p>',table(cd.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all' and metric == 'exposure_days'")),
    '<h2>装机与面积加权网格是否一致</h2><p>同步指标的网格值使用面积比例、装机值使用容量比例；可比较各自SSP变化方向和幅度，但分母不同。国家对比保留相同区域；网格包含无装机地区，因此与装机加权差异不要求相等。</p>',table(grid.query("snapshot == 2050 and region == 'global:GLOBAL' and event == 'all'")),
    '<h2>覆盖与解释边界</h2>',table(coverage.query("snapshot == 2050 and country == 'GLOBAL'")),
    '<p>低资源标签采用各SSP自身2015–2024基线，光伏事件集合不含高温。仅凭二值信号不推断气象强度、环流机制或电力系统后果。同步比例以固定共同容量为分母，先在同一时刻合并分块，再计算P95、最大值及超过10/20/30%容量的时长；缺测通过可用容量和上下界表示。每个SSP自身并集P95高值时段的事件构成用于解释大范围暴露，不能视为并集P95的唯一分解。</p>',
    '<h2>完整源数据</h2><ul>']
    html.insert(6,findings_html(levels,diff,drivers,cd))
    if full:
        html.insert(7,dynamics_findings_html(output,levels,diff,grid))
    pictures=[name for name in ["ssp_station_event_exposure","ssp_station_exposure_maps","ssp_station_dynamics","ssp_station_synchrony_maps"] if (output/(name+".png")).exists()]
    if pictures:
        html.insert(7,"<h2>全球事件比较与国家空间分布</h2>"+"".join(f'<p><img src="{name}.png" style="max-width:100%"></p>' for name in pictures))
    html.insert(-1,'<p><a href="metric_definitions.csv">指标中文定义与单位</a></p>')
    html.insert(-1,'<p><a href="regional_dynamic_patterns.csv">频次、持时与同步指标的地区差异及主要事件增减</a>（事件指标差异仅用于解释相关结构，不能相加为并集归因）。</p>')
    if full:
        html.insert(-1,'<p><a href="dynamics/summary/tail_contrasts.csv">各路径大范围并集高值时段的事件构成差异</a>；<a href="dynamics/summary/combined_models.csv.gz">逐模式全指标与纬度带数据</a>。</p>')
    for path in sorted(output.iterdir()):
        if path.suffix in (".csv",".gz",".json"):html.append(f'<li><a href="{path.name}">{path.name}</a></li>')
    html+=['</ul><p>希望对你有帮助，小凯！</p></html>']
    (output/"report.html").write_text("\n".join(html))

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument("--output-root",type=Path,default=OUT);p.add_argument("--dynamics",type=Path);a=p.parse_args()
    out=a.output_root;out.mkdir(parents=True,exist_ok=True)
    combined,receipt=cached_levels()
    full=a.dynamics is not None
    if full:
        require_complete(a.dynamics)
        fresh=pd.read_csv(a.dynamics/"combined_models.csv.gz")
        check=fresh.merge(combined,on=KEY,suffixes=("","_cache"),validate="one_to_one")
        if len(check)!=len(combined):raise ValueError("Incomplete station dynamics country coverage")
        for metric in ["exposure_days","starts_per_year","mean_complete_hours","complete_exposure_days"]:
            ok=check[[metric,metric+"_cache"]].notna().all(axis=1)
            if not np.allclose(check.loc[ok,metric],check.loc[ok,metric+"_cache"],rtol=1e-7,atol=1e-6):raise ValueError(f"Cache reproduction: {metric}")
        combined=fresh
    metrics=[c for c in combined if c not in KEY+["capacity_mw"]]
    write_csv(out/"metric_definitions.csv",metric_definitions(metrics))
    long=combined.melt(id_vars=KEY,value_vars=metrics,var_name="metric",value_name="value")
    long=additive_overlap(long,["exposure_days"])
    write_csv(out/"levels_models.csv.gz",long)
    level=ensemble(long,[k for k in KEY if k!="model"]+["metric"],"value");write_csv(out/"levels.csv",level)
    d=differences(long);write_csv(out/"contrasts_models.csv.gz",d)
    diff=summarize_diff(d);write_csv(out/"contrasts.csv",diff)
    write_csv(out/"regional_dynamic_patterns.csv",regional_patterns(diff))
    drivers=[]
    for identity,g in diff[diff.metric.eq("exposure_days")].groupby(["tech","snapshot","region","comparison","high","low"]):
        e=g.set_index("event")["mean"];labels=e.drop(["all","overlap_correction"])
        if np.isfinite(e).all() and not np.isclose(e.drop("all").sum(),e["all"],atol=1e-8):raise ValueError("Event overlap closure")
        drivers.append(dict(zip(["tech","snapshot","region","comparison","high","low"],identity))|dict(union_days=e["all"],increase_event=labels.idxmax() if labels.max()>0 else "",increase_days=max(labels.max(),0),decrease_event=labels.idxmin() if labels.min()<0 else "",decrease_days=min(labels.min(),0),overlap_days=e["overlap_correction"]))
    drivers=pd.DataFrame(drivers);write_csv(out/"regional_event_drivers.csv",drivers)
    decomp,error=decomposition(combined);write_csv(out/"frequency_duration_decomposition_models.csv.gz",decomp)
    dk=[c for c in decomp if c not in ["frequency_days","duration_days","censored_days","net_days"]]
    ds=ensemble(decomp.melt(id_vars=dk,var_name="term",value_name="value"),[k for k in dk if k!="model"]+["term"],"value")
    write_csv(out/"frequency_duration_decomposition.csv",ds)
    cd=climate_deployment(long);write_csv(out/"climate_deployment_models.csv.gz",cd)
    ck=COMPARE+["high","low"]
    cs=ensemble(cd.melt(id_vars=ck,value_vars=["climate_component","deployment_component","paired_difference"],var_name="term",value_name="value"),[k for k in ck if k!="model"]+["term"],"value")
    write_csv(out/"climate_deployment.csv",cs)
    grid,grid_ready=grid_comparison(d,out)
    cap=combined[combined.event.eq("all")&combined.region.str.startswith(("country:","global:"))].copy()
    cap["country"]=cap.region.str.split(":").str[1]
    cap=cap.groupby(["station_ssp","tech","snapshot","country"]).capacity_mw.agg(["min","max"]).reset_index()
    if not np.allclose(cap["min"],cap["max"]):raise ValueError("Changing common capacity")
    total=pd.read_csv(OUTPUT/"catalogues/capacity_by_country.csv")
    glob=total.groupby(["station_ssp","tech","snapshot"],as_index=False).capacity_mw.sum();glob["country"]="GLOBAL"
    total=pd.concat([total,glob]).rename(columns={"capacity_mw":"total_capacity_mw"})
    coverage=cap.merge(total,on=["station_ssp","tech","snapshot","country"],validate="one_to_one")
    coverage["retained_capacity_fraction"]=coverage["min"]/coverage.total_capacity_mw
    write_csv(out/"capacity_coverage.csv",coverage)
    write_json(out/"audit.json",dict(status="PASSED",dynamics_complete=full,grid_dynamics_complete=grid_ready,frequency_duration_max_error_days=error,models=MODELS,source_summary=str(OUTPUT/"event_summary"),source_hashes={f:digest(OUTPUT/"event_summary"/f) for f in ["window.csv.gz","frequency_duration.csv.gz"]},code_sha256=digest(Path(__file__))))
    import subprocess, sys
    subprocess.run([sys.executable,"-m","paper_figures.main.fig01_extreme_events.plot_ssp_station","--output-root",str(out)],check=True)
    report(out,level,diff,drivers,ds,cs,grid,coverage,full,grid_ready)
    if full and grid_ready:
        from .prepare_ssp_dynamics import marker
        marker(out,station_dynamics_complete=True,grid_dynamics_complete=True)
    print("REPORT",out,"dynamics_complete",full,"grid_dynamics_complete",grid_ready,flush=True)
if __name__=="__main__":main()
