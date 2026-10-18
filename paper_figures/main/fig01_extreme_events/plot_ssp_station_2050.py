"""Render 2050s capacity-weighted extreme-event SSP comparisons."""
import argparse,json,os
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Rectangle,Patch
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox
from matplotlib.text import Text
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter,LatitudeFormatter
from PIL import Image
from paper_figures.config import ROOT,MODELS,TECHS,EVENTS,SSPS,SSP_COLORS
from paper_figures.common.spatial import countries
from paper_figures.common.io import require_complete,write_json,digest
from .analyze_ssp_station import KEY,additive_overlap,differences,summarize_diff
from .summarize_ssp_dynamics import ensemble

BASE=ROOT/"paper_figures/main/fig01_extreme_events"
OUT=BASE/"outputs"
STATION=OUT/"ssp_station"
GRID=OUT/"ssp_grid/dynamics/summary"
SOURCE=OUT/"source_data/ssp_station_2050"
STEM="fig01_ssp_station_2050"
METRICS=("exposure_days","starts_per_year","mean_complete_hours","p95_capacity_pct")
METRIC_NAMES=("Exposure","Frequency","Mean duration","Capacity P95")
UNITS=("days yr⁻¹","events yr⁻¹","h event⁻¹","% of capacity")
DIFF_UNITS=("days yr⁻¹","events yr⁻¹","h event⁻¹","percentage points")
PAIRS=(("ssp245","ssp126"),("ssp585","ssp126"),("ssp585","ssp245"))
PAIR_NAMES=("245 − 126","585 − 126","585 − 245")
REGIONS=("CHN","USA","IND","DEU","BRA","RUS","AUS")
REGION_NAMES=("China","USA","India","Germany","Brazil","Russia","Australia")
NAMES={"high_temp":"High temperature","high_wind":"High wind","hot_humid":"Hot–humid",
       "icing":"Icing","low_resource":"Low resource","cold_highwind":"Cold + high wind",
       "freezing_rain":"Freezing rain","high_humidity":"High humidity","rainstorm":"Rainstorm",
       "overlap_correction":"Overlap","all":"Union"}
SHORT=dict(NAMES,high_temp="High temp.",cold_highwind="Cold + wind",high_humidity="High humid.")
HEIGHTS=(3.2,3.0,3.0,3.4,3.4)
WIDTH=16.
INPUTS=[STATION/"dynamics/summary/combined_models.csv.gz",GRID/"levels_models.csv.gz",
        STATION/"levels.csv",STATION/"contrasts.csv",STATION/"station_grid.csv",
        STATION/"capacity_coverage.csv",STATION/"audit.json",GRID/"audit.json"]
TABLES=("global_levels","global_models","event_levels","event_models","country_contrasts",
        "country_contrast_models","comparison","comparison_models","capacity_coverage","global_extra_metrics")

def need(ok,message):
    if not ok:raise ValueError(message)

def select(path,condition):
    result=[]
    for d in pd.read_csv(path,chunksize=100000):
        q=d.loc[condition(d)]
        if len(q):result.append(q)
    need(bool(result),f"No rows selected: {path}")
    return pd.concat(result,ignore_index=True)

def identity():
    return {str(p):{"bytes":p.stat().st_size,"mtime_ns":p.stat().st_mtime_ns} for p in INPUTS}

def prepare(reuse=False):
    for p in (STATION,STATION/"dynamics/summary",GRID):require_complete(p)
    for p in (STATION/"audit.json",GRID/"audit.json"):
        need(json.loads(p.read_text())["status"]=="PASSED","Source audit")
    SOURCE.mkdir(parents=True,exist_ok=True);manifest=SOURCE/"manifest.json"
    if reuse:
        old=json.loads(manifest.read_text())
        need(old["inputs"]==identity(),"Source inputs changed")
        need(all(digest(SOURCE/f)==h for f,h in old["table_hashes"].items()),"Source cache changed")
        return {k:pd.read_csv(SOURCE/(k+".csv")) for k in TABLES},old["validation"]
    print("PREPARE station models",flush=True)
    raw=select(INPUTS[0],lambda d:d.snapshot.eq(2050)&d.climate_ssp.eq(d.station_ssp)&
               (d.region.eq("global:GLOBAL")|d.region.str.startswith("country:")))
    need(not raw.duplicated(KEY).any(),"Duplicate station rows")
    need(set(raw.model)==set(MODELS),"Model membership")
    global_raw=raw[raw.region.eq("global:GLOBAL")]
    gm=global_raw[global_raw.event.eq("all")].melt(id_vars=KEY,value_vars=list(METRICS),var_name="metric",value_name="value")
    gl=ensemble(gm,[k for k in KEY if k!="model"]+["metric"],"value")
    need(len(gl)==24 and gl.n_finite.eq(4).all(),"Overview model matrix")
    em=global_raw[global_raw.event.ne("all")][KEY+["exposure_days"]].rename(columns={"exposure_days":"value"})
    el=ensemble(em,[k for k in KEY if k!="model"],"value")
    need(len(el)==33 and el.n_finite.eq(4).all(),"Event model matrix")
    ref=select(STATION/"levels.csv",lambda d:d.snapshot.eq(2050)&d.region.eq("global:GLOBAL")&
               d.event.eq("all")&d.climate_ssp.eq(d.station_ssp)&d.metric.isin(METRICS))
    keys=[k for k in KEY if k!="model"]+["metric"]
    merged=gl.merge(ref,on=keys,suffixes=("_new","_reference"),validate="one_to_one")
    overview_error=float((merged.mean_new-merged.mean_reference).abs().max())
    need(len(merged)==24 and overview_error<1e-8,"Overview reference reproduction")
    print("PREPARE country event accounting",flush=True)
    country=raw[raw.region.str.startswith("country:")][KEY+["exposure_days"]].rename(columns={"exposure_days":"value"})
    country["metric"]="exposure_days";country=additive_overlap(country,["exposure_days"])
    cm=differences(country);cm=cm[cm.comparison.eq("paired")].copy();cc=summarize_diff(cm)
    closure=0.
    for tech in TECHS:
        d=cm[cm.tech.eq(tech)].pivot(index=["model","region","high","low"],columns="event",values="difference")
        closure=max(closure,float((d[list(EVENTS[tech])].sum(axis=1)+d.overlap_correction-d["all"]).abs().max()))
    need(closure<1e-8,"Country event accounting")
    ref=select(STATION/"contrasts.csv",lambda d:d.snapshot.eq(2050)&d.comparison.eq("paired")&
               d.metric.eq("exposure_days")&d.region.str.startswith("country:"))
    kk=["tech","snapshot","region","event","metric","high","low","comparison"]
    matched=cc.merge(ref,on=kk,suffixes=("_new","_reference"),validate="one_to_one")
    country_error=float((matched.mean_new-matched.mean_reference).abs().max())
    need(len(matched)==len(cc) and country_error<1e-8,"Country contrast reference reproduction")
    print("PREPARE paired grid comparison",flush=True)
    metric_grid=[m.replace("_capacity_","_area_") for m in METRICS]
    grid=select(GRID/"levels_models.csv.gz",lambda d:d.snapshot.eq(2050)&d.region.eq("global:GLOBAL")&
                d.event.eq("all")&d.metric.isin(metric_grid))
    grid["metric"]=grid.metric.str.replace("_area_","_capacity_",regex=False)
    station_diff=differences(gm);station_diff=station_diff[station_diff.comparison.eq("paired")]
    grid_diffs=[];join=["model","tech","snapshot","region","event","metric"]
    for high,low in PAIRS:
        h=grid[grid.climate_ssp.eq(high)][join+["value"]];l=grid[grid.climate_ssp.eq(low)][join+["value"]]
        x=h.merge(l,on=join,suffixes=("_high","_low"),validate="one_to_one")
        x["grid_difference"]=x.value_high-x.value_low;x["high"],x["low"]=high,low
        grid_diffs.append(x[join+["high","low","grid_difference"]])
    comparison_models=station_diff.merge(pd.concat(grid_diffs),on=join+["high","low"],validate="one_to_one")
    need(len(comparison_models)==96,"Comparison model matrix")
    sk=[x for x in join if x!="model"]+["high","low","comparison"]
    a=ensemble(comparison_models,sk,"difference");b=ensemble(comparison_models,sk,"grid_difference")
    b=b.rename(columns={c:"grid_"+c for c in b if c not in sk});comp=a.merge(b,on=sk,validate="one_to_one")
    need(comp.n_finite.eq(4).all() and comp.grid_n_finite.eq(4).all(),"Comparison finite models")
    ref=select(STATION/"station_grid.csv",lambda d:d.snapshot.eq(2050)&d.region.eq("global:GLOBAL")&
               d.event.eq("all")&d.comparison.eq("paired")&d.metric.isin(METRICS))
    q=comp.merge(ref,on=sk,suffixes=("_new","_reference"),validate="one_to_one")
    comparison_error=max(float((q.mean_new-q.mean_reference).abs().max()),float((q.grid_mean_new-q.grid_mean_reference).abs().max()))
    need(len(q)==24 and comparison_error<1e-5,"Grid comparison reference reproduction")
    coverage=pd.read_csv(STATION/"capacity_coverage.csv").query("snapshot == 2050").copy()
    tables=dict(global_levels=gl,global_models=gm,event_levels=el,event_models=em,country_contrasts=cc,
                country_contrast_models=cm,comparison=comp,comparison_models=comparison_models,
                capacity_coverage=coverage,global_extra_metrics=global_raw[global_raw.event.eq("all")])
    for name,data in tables.items():data.to_csv(SOURCE/(name+".csv"),index=False)
    validation={"overview_reference_max_error":overview_error,"country_reference_max_error":country_error,
                "comparison_reference_max_error":comparison_error,"event_closure_max_days":closure,"n_models":4,
                "global_level_rows":len(gl),"country_contrast_rows":len(cc),"comparison_rows":len(comp),
                "window":"2050–2059","snapshot":2050}
    write_json(manifest,{"inputs":identity(),"validation":validation,
                        "table_hashes":{k+".csv":digest(SOURCE/(k+".csv")) for k in TABLES}})
    return tables,validation

def axes(fig,x,y,w,h,**kwargs):return fig.add_axes([x/WIDTH,y/16.,w/WIDTH,h/16.],**kwargs)
def text(fig,x,y,value,**kwargs):return fig.text(x/WIDTH,y/16.,value,**kwargs)
def panel_title(fig,x,y,letter,title):
    text(fig,x+.12,y,letter,fontsize=15,weight="bold",va="center")
    text(fig,x+.46,y,title+" | 2050–2059",fontsize=12,weight="bold",va="center")

def overview(fig,y,tables):
    for col,tech in enumerate(TECHS):
        left=8*col;panel_title(fig,left,y+3.02,"ab"[col],f"{'Wind' if tech=='wind' else 'Solar PV'} | Global event union")
        fig.legend(handles=[Patch(facecolor=SSP_COLORS[s],label=s.upper()) for s in SSPS],
                   loc="center",bbox_to_anchor=((left+2.6)/WIDTH,(y+2.72)/16),ncol=3,
                   handlelength=1.4,columnspacing=1.2,fontsize=8,frameon=False)
        text(fig,left+6.0,y+2.72,"Mean; min–max (n = 4)",ha="center",va="center",fontsize=7.5)
        ax=axes(fig,left+.80,y+.63,6.78,1.80)
        d=tables["global_levels"].query("tech == @tech").set_index(["metric","climate_ssp"])
        reference=np.array([d.loc[(m,"ssp126"),"mean"] for m in METRICS])
        for si,ssp in enumerate(SSPS):
            rows=d.loc[[(m,ssp) for m in METRICS]]
            mean=rows["mean"].to_numpy()/reference
            low=rows.minimum.to_numpy()/reference;high=rows.maximum.to_numpy()/reference
            need((low>.85).all() and (high<1.25).all(),"Overview range outside axis")
            xx=np.arange(4)+(si-1)*.24
            ax.bar(xx,mean,width=.22,color=SSP_COLORS[ssp],zorder=2)
            ax.errorbar(xx,mean,yerr=[mean-low,high-mean],fmt="none",ecolor="#333333",
                        elinewidth=.7,capsize=0,zorder=3)
            for x,top,value in zip(xx,high,rows["mean"]):
                ax.text(x,top+.008,f"{value:.2f}",rotation=90,fontsize=7,ha="center",va="bottom")
        ax.axhline(1,color="#555555",ls=(0,(3,2)),lw=.7,zorder=1)
        ax.set_ylim(.85,1.25);ax.set_yticks(np.arange(.85,1.251,.05))
        ax.text(.66,.98,"Y axis starts at 0.85",transform=ax.transAxes,ha="center",va="top",fontsize=7,color="#555555")
        for yy in (.012,.032):
            ax.plot([-.009,.009],[yy-.008,yy+.008],transform=ax.transAxes,color="#333333",lw=.8,clip_on=False)
        ax.set_xlim(-.6,3.6)
        ax.set_xticks(range(4),[name+"\n("+unit+")" for name,unit in zip(METRIC_NAMES,UNITS)],fontsize=8)
        ax.set_ylabel("Relative to SSP126 mean",fontsize=8.5)
        ax.tick_params(axis="y",labelsize=8)
        ax.grid(axis="y",color="#e6e6e6",lw=.45,zorder=0)
        text(fig,left+4,y+.10,"Labels: original values · Capacity-weighted; paired climate + deployment",ha="center",fontsize=8)

def events(fig,y,tables):
    segments={"wind":[(0,2),(4,16),(20,25)],"solar":[(0,4.5),(8.5,15)]}
    ticks={"wind":[0,5,10,15,25],"solar":[0,10,15]}
    for col,tech in enumerate(TECHS):
        left=8*col;panel_title(fig,left,y+2.82,"cd"[col],f"{'Wind' if tech=='wind' else 'Solar PV'} | Exposure by event")
        fig.legend(handles=[Patch(facecolor=SSP_COLORS[s],label=s.upper()) for s in SSPS],
                   loc="center",bbox_to_anchor=((left+2.6)/WIDTH,(y+2.51)/16),ncol=3,
                   handlelength=1.4,columnspacing=1.2,fontsize=8,frameon=False)
        text(fig,left+6.0,y+2.51,"Mean; min–max (n = 4)",ha="center",va="center",fontsize=7.5)
        ax=axes(fig,left+1.62,y+.63,6.05,1.65)
        d=tables["event_levels"].query("tech == @tech").set_index(["event","climate_ssp"])
        omitted=[(a[1],b[0]) for a,b in zip(segments[tech],segments[tech][1:])]
        def compress(values):
            values=np.asarray(values,dtype=float)
            return values-sum(np.clip(values-lo,0,hi-lo) for lo,hi in omitted)
        for row in d.itertuples():
            need(any(lo<=row.minimum<=row.mean<=row.maximum<=hi for lo,hi in segments[tech]),
                 "Event model range inside omitted interval")
        for si,ssp in enumerate(SSPS):
            rows=d.loc[[(e,ssp) for e in EVENTS[tech]]];yy=np.arange(len(EVENTS[tech]))+(si-1)*.24
            mean=compress(rows["mean"])
            ax.barh(yy,mean,height=.21,color=SSP_COLORS[ssp],zorder=2)
            ax.errorbar(mean,yy,xerr=[mean-compress(rows.minimum),compress(rows.maximum)-mean],
                        fmt="none",ecolor="#333333",elinewidth=.7,capsize=0,zorder=3)
        ax.set_yticks(range(len(EVENTS[tech])),[NAMES[e].replace("High temperature","High\ntemperature")
                     .replace("Cold + high wind","Cold +\nhigh wind") for e in EVENTS[tech]],fontsize=9)
        ax.set_ylim(5.5,-.6);ax.set_xlim(0,compress(segments[tech][-1][1]))
        ax.set_xticks(compress(ticks[tech]),ticks[tech]);ax.tick_params(axis="x",labelsize=8)
        ax.tick_params(axis="y",length=0,pad=4);ax.spines["left"].set_visible(False)
        ax.grid(axis="x",color="#e6e6e6",lw=.45,zorder=0)
        for lo,hi in omitted:
            x=float(compress(lo));trans=ax.get_xaxis_transform()
            dx=float(compress(segments[tech][-1][1]))*.004
            ax.plot([x-3*dx,x+3*dx],[0,0],transform=trans,color="white",lw=2,clip_on=False,zorder=4)
            for offset in (-1.2*dx,1.2*dx):
                ax.plot([x+offset-dx,x+offset+dx],[-.012,.012],transform=trans,
                        color="#444444",lw=.8,clip_on=False,zorder=5)
            for value,offset,align in ((lo,-4,"right"),(hi,4,"left")):
                ax.annotate(str(value),(x,0),xycoords=trans,xytext=(offset,-5.5),
                            textcoords="offset points",ha=align,va="top",fontsize=8)
        if tech=="wind":
            for event in ("high_wind","hot_humid"):
                yy=list(EVENTS[tech]).index(event)
                for xx,ssp in zip((6,9,12),SSPS):
                    ax.text(compress(xx),yy,f"{d.loc[(event,ssp),'mean']:.3g}",va="center",
                            color=SSP_COLORS[ssp],fontsize=8)
        text(fig,left+4.64,y+.29,"Capacity-weighted exposure (days yr⁻¹)",ha="center",fontsize=9)
        gap_label="2–4 and 16–20" if tech=="wind" else "4.5–8.5"
        text(fig,left+4,y+.07,f"Omitted: {gap_label} days yr⁻¹ · Event types may overlap",ha="center",fontsize=8)

def spatial_maps(fig,y,tables,geometries):
    country=tables["country_contrasts"];cmap=plt.get_cmap("RdBu_r")
    norm=TwoSlopeNorm(vmin=-12.5,vcenter=0,vmax=12.5)
    saturation={}
    for col,tech in enumerate(TECHS):
        left=8*col;panel_title(fig,left,y+2.82,"ef"[col],f"{'Wind' if tech=='wind' else 'Solar PV'} | Country exposure difference")
        union=country[country.tech.eq(tech)&country.event.eq("all")&
                      country.high.eq("ssp585")&country.low.eq("ssp126")]
        vals=union.set_index("region")["mean"]
        saturation[tech]={"source_country_count":int(vals.notna().sum()),
                          "outside_color_range_count":int((vals.abs()>12.5).sum()),
                          "outside_color_range_fraction":float((vals.dropna().abs()>12.5).mean())}
        ax=axes(fig,left+.65,y+.65,6.80,1.90,projection=ccrs.PlateCarree())
        for iso,_,geom in geometries:
            v=vals.get("country:"+iso,np.nan)
            ax.add_geometries([geom],crs=ccrs.PlateCarree(),facecolor=cmap(norm(v)) if np.isfinite(v) else "#dddddd",
                              edgecolor="#8c8c8c",linewidth=.18)
        ax.set_extent([-180,180,-60,85],crs=ccrs.PlateCarree())
        ax.set_xticks([-120,0,120],crs=ccrs.PlateCarree());ax.set_yticks([-30,30,60],crs=ccrs.PlateCarree())
        ax.xaxis.set_major_formatter(LongitudeFormatter());ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(labelsize=8,length=2,pad=1);ax.set_title("SSP585 − SSP126",fontsize=9,pad=5)
        cax=axes(fig,left+2.10,y+.27,4.05,.10)
        cb=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=cax,orientation="horizontal",
                        ticks=[-12.5,-6.25,0,6.25,12.5],extend="both")
        cb.ax.tick_params(labelsize=7,length=2,pad=1)
        cb.set_label("Union exposure difference (days yr⁻¹); grey: undefined",fontsize=8,labelpad=1)
    return saturation

def country_events(fig,y,tables):
    country=tables["country_contrasts"];cmap=plt.get_cmap("RdBu_r")
    for col,tech in enumerate(TECHS):
        left=8*col;panel_title(fig,left,y+3.22,"gh"[col],f"{'Wind' if tech=='wind' else 'Solar PV'} | Country event accounting")
        part=country[country.tech.eq(tech)]
        evt=[*EVENTS[tech],"overlap_correction","all"];nrows=15;values=np.full((nrows,len(evt)),np.nan)
        lookup=part.set_index(["high","low","region","event"])["mean"];positions=[]
        for pi,(high,low) in enumerate(PAIRS[:2]):
            for ri,region in enumerate(REGIONS):
                row=8*pi+ri;positions.append(row)
                for ei,event in enumerate(evt):values[row,ei]=lookup.loc[(high,low,"country:"+region,event)]
        hlim=max(1.,float(np.ceil(np.nanmax(np.abs(values)))));hnorm=TwoSlopeNorm(vmin=-hlim,vcenter=0,vmax=hlim)
        ax=axes(fig,left+1.55,y+1.00,5.65,2.05)
        ax.imshow(values,aspect="auto",cmap=cmap,norm=hnorm,interpolation="nearest")
        for ri,ei in np.argwhere(np.isfinite(values)):
            v=values[ri,ei];label="0" if abs(v)<.005 else f"{v:+.1f}" if abs(v)>=.1 else f"{v:+.2f}"
            ax.text(ei,ri,label,ha="center",va="center",fontsize=7.6,weight="bold" if evt[ei]=="all" else "normal",
                    color="white" if abs(v)>.67*hlim else "#222222")
        for row in positions:
            ei=int(np.nanargmax(abs(values[row,:len(EVENTS[tech])])))
            ax.add_patch(Rectangle((ei-.48,row-.48),.96,.96,fill=False,edgecolor="#333333",lw=.7))
        ax.set_yticks(positions,list(REGION_NAMES)*2,fontsize=8)
        ax.set_xticks(range(len(evt)),[SHORT[e] for e in evt],rotation=37,ha="right",fontsize=8)
        ax.tick_params(length=0,pad=3)
        for spine in ax.spines.values():spine.set_visible(False)
        ax.axvline(len(evt)-1.5,color="#333333",lw=.8)
        for pi,label in enumerate(PAIR_NAMES[:2]):
            ax.text(-.24,1-(8*pi+3.5)/nrows,label,transform=ax.transAxes,rotation=90,ha="center",va="center",fontsize=8)
        cax=axes(fig,left+7.40,y+1.05,.10,1.95)
        cb=fig.colorbar(plt.cm.ScalarMappable(norm=hnorm,cmap=cmap),cax=cax)
        cb.ax.tick_params(labelsize=7,length=2);cb.set_label("Exposure difference (days yr⁻¹)",fontsize=8,labelpad=5)
        text(fig,left+4,y+.16,"Capacity-weighted; union = events + overlap; outline: largest absolute event term",ha="center",fontsize=8)

def comparison(fig,y,tables):
    for col,tech in enumerate(TECHS):
        left=8*col;panel_title(fig,left,y+3.20,"ij"[col],f"{tech.title()} | Station versus grid SSP differences")
        data=tables["comparison"].query("tech == @tech").set_index(["metric","high","low"])
        handles=[Line2D([],[],marker="o",color="#234b78",ls="none",label="Capacity-weighted stations"),
                 Line2D([],[],marker="D",markerfacecolor="white",color="#666666",ls="none",label="Area-weighted grid")]
        leg=axes(fig,left+.95,y+2.68,6.6,.25);leg.axis("off");leg.legend(handles=handles,ncol=2,loc="center",fontsize=8,frameon=False)
        for mi,(metric,name,unit) in enumerate(zip(METRICS,METRIC_NAMES,DIFF_UNITS)):
            ax=axes(fig,left+.92+mi*1.76,y+.73,1.48,1.55)
            rows=data.loc[[(metric,h,l) for h,l in PAIRS]]
            lim=max(float(abs(rows[["minimum","maximum","grid_minimum","grid_maximum"]].to_numpy()).max())*1.18,.01)
            for pi,row in enumerate(rows.itertuples()):
                yy=2-pi;ax.plot([row.mean,row.grid_mean],[yy+.10,yy-.10],color="#b8b8b8",lw=1,zorder=1)
                ax.errorbar(row.mean,yy+.10,xerr=[[row.mean-row.minimum],[row.maximum-row.mean]],fmt="o",
                            color="#234b78",markersize=4,capsize=2,lw=.8,zorder=3)
                ax.errorbar(row.grid_mean,yy-.10,xerr=[[row.grid_mean-row.grid_minimum],[row.grid_maximum-row.grid_mean]],
                            fmt="D",mfc="white",color="#666666",markersize=3.7,capsize=2,lw=.8,zorder=3)
            ax.axvline(0,color="#444444",lw=.7);ax.set_xlim(-lim,lim);ax.set_ylim(-.45,2.45)
            ax.set_yticks([2,1,0],PAIR_NAMES if mi==0 else ["","",""],fontsize=8)
            ax.xaxis.set_major_locator(plt.MaxNLocator(3))
            ax.set_title(name.replace("Capacity P95","Synchronous P95"),fontsize=9,pad=8)
            ax.set_xlabel("Δ ("+unit+")",fontsize=8,labelpad=4);ax.grid(axis="x",alpha=.15);ax.tick_params(labelsize=8,length=2)
        text(fig,left+4,y+.13,"Within-model SSP contrasts; mean and min–max; P95 denominators: capacity / area",ha="center",fontsize=8)

def render(tables,validation):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,
                         "axes.spines.right":False,"axes.linewidth":.65,"legend.frameon":False})
    geoms=countries()
    need(sum(iso=="CHN" for iso,_,_ in geoms)==1 and all(iso!="TWN" for iso,_,_ in geoms),"China union")
    need(all(g.is_valid for _,_,g in geoms),"Geometry validity")
    fig=plt.figure(figsize=(WIDTH,16),facecolor="white");row_bounds={};cursor=16.
    for pair,height,draw in zip(("ab","cd","ef","gh","ij"),HEIGHTS,(overview,events,spatial_maps,country_events,comparison)):
        cursor-=height;row_bounds[pair]=(cursor,height)
        if pair=="ef":saturation=draw(fig,cursor,tables,geoms)
        else:draw(fig,cursor,tables)
    fig.canvas.draw();files=[];renderer=fig.canvas.get_renderer()
    def save(suffix,bbox=None):
        region=bbox if bbox is not None else Bbox.from_bounds(0,0,WIDTH,16)
        clipped=[]
        for artist in fig.findobj(Text):
            if not artist.get_visible() or not artist.get_text():continue
            box=artist.get_window_extent(renderer).transformed(fig.dpi_scale_trans.inverted())
            if box.overlaps(region) and (box.x0<region.x0-.01 or box.x1>region.x1+.01
                                        or box.y0<region.y0-.01 or box.y1>region.y1+.01):
                clipped.append(artist.get_text())
        need(not clipped,f"Clipped text in {suffix}: {clipped}")
        name=STEM+suffix+".png";fig.savefig(OUT/name,dpi=300,facecolor="white",bbox_inches=bbox,pad_inches=0)
        with Image.open(OUT/name) as im:size=list(im.size);im.verify()
        files.append({"file":name,"pixels":size,"sha256":digest(OUT/name),"text_clipping":"PASSED"})
    save("")
    for pair,(y,height) in row_bounds.items():
        save("_"+pair,Bbox.from_bounds(0,y,WIDTH,height))
        for col,letter in enumerate(pair):save("_"+letter,Bbox.from_bounds(col*8,y,8,height))
    plt.close(fig)
    write_json(OUT/(STEM+"_metadata.json"),{"status":"COMPUTED_AWAITING_VISUAL_REVIEW",
        "generated_utc":datetime.now(timezone.utc).isoformat(),"files":files,"validation":validation,
        "code_sha256":digest(Path(__file__)),"source_manifest":str(SOURCE/"manifest.json"),
        "projection":"PlateCarree","country_geometry":"China union Taiwan",
        "comparison":"paired climate and station SSP","period":"2050–2059","capacity_snapshot":2050,
        "uncertainty":"four-model min–max","impact_extent":"time P95 of simultaneous affected capacity fraction",
        "overview_scaling":"relative to technology/metric SSP126 ensemble mean; original-value labels",
        "overview_y_limits":[.85,1.25],
        "event_axes":{"wind":{"omitted_ranges":[[2,4],[16,20]],"x_max":25},
                      "solar":{"omitted_ranges":[[4.5,8.5]],"x_max":15},
                      "continuous_bars":True,"break_marks":"bottom x-axis only"},
        "panels":{"ab":"global union metrics","cd":"event exposure","ef":"country exposure maps",
                  "gh":"country event heatmaps","ij":"station versus grid contrasts"},
        "map_limits_days":[-12.5,12.5],"map_extend":"both",
        "map_color_reference":"fig01_ssp_grid_2050, panels g/h",
        "map_saturation":saturation,
        "spatial_map_pairs":[["ssp585","ssp126"]],
        "spatial_heatmap_pairs":[["ssp245","ssp126"],["ssp585","ssp126"]],"job_id":os.environ.get("SLURM_JOB_ID"),
        "dpi":300,"figure_inches":[16,16]})
    print("RENDERED",len(files),"PNGs",flush=True)

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument("--reuse-source",action="store_true")
    p.add_argument("--prepare-only",action="store_true");args=p.parse_args()
    tables,validation=prepare(args.reuse_source);print("SOURCE_VALIDATED",validation,flush=True)
    if not args.prepare_only:render(tables,validation)

if __name__=="__main__":main()
