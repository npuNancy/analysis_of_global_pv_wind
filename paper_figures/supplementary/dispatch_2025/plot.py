"""Render the eight dispatch-2025 triptychs from accepted annual summaries."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

from paper_figures.common.plotting import configure, export_panel_png, independent_y_ticks
from paper_figures.config import SSP_COLORS

HERE=Path(__file__).resolve().parent
ROOT=Path("/work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585")
SSPS=["ssp126","ssp245","ssp585"]
TECHS=[("wind+solar","Wind + solar"),("wind","Wind"),("solar","Solar")]
METRICS=[
    ("capacity","catalogue_capacity_mw",1e-6,"Installed capacity (TW)","装机容量",False,False),
    ("exposure_total","exposure_mw_days",1.,"Capacity-weighted exposure (MW day yr⁻¹)","装机加权暴露总量",False,False),
    ("exposure_mean","exposure_days",1.,"Mean exposure (day yr⁻¹)","装机加权年均暴露时长",False,False),
    ("total_loss","net_loss_mwh",1.,"Total net loss (MWh yr⁻¹)","总净损失",True,False),
    ("unit_loss","unit_loss_mwh_per_mw",1.,"Net loss (MWh MW⁻¹ yr⁻¹)","单位装机净损失",True,True),
    ("loss_fraction","loss_fraction_pct",1.,"Loss / annual normal generation (%)","净损失占全年正常基准电量比例",True,True),
    ("total_generation","generation_mwh",1e-9,"Generation (PWh yr⁻¹)","全年总发电量",True,False),
    ("unit_generation","unit_generation_mwh_per_mw",1.,"Generation (MWh MW⁻¹ yr⁻¹)","单位装机全年发电量",True,True),
]
TITLES=dict(capacity="Installed capacity",exposure_total="Capacity-weighted exposure",
    exposure_mean="Mean exposure duration",total_loss="Total net generation loss",
    unit_loss="Net loss per unit capacity",loss_fraction="Loss / annual normal generation",
    total_generation="Total generation",unit_generation="Generation per unit capacity")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tables(root,out):
    indexpath=root/"runtime/authoritative_index.json"
    index=json.loads(indexpath.read_text())
    done=json.loads((root/"runtime/completion.json").read_text())
    assert index["status"]==done["status"]=="COMPLETED"
    assert digest(indexpath)==done["index_sha256"]
    record=index["summaries"]["global_annual_models.csv"]
    assert digest(record["path"])==record["sha256"]
    all_models=pd.read_csv(record["path"])
    models=all_models[all_models.climate_ssp.eq(all_models.station_ssp)].copy()
    keys=["model","climate_ssp","tech","year"]
    expected=set(itertools.product(index["models"],SSPS,[t[0] for t in TECHS],range(2030,2060)))
    assert not models.duplicated(keys).any()
    assert set(models[keys].itertuples(index=False,name=None))==expected
    models.to_csv(out/"source_data/annual_models.csv",index=False)
    return models,indexpath,index


def metric_table(models,metric,out):
    name,field,scale,_,_,annual,_=metric
    if name=="capacity":
        frame=models[models.year.isin([2030,2040,2050])].copy()
        group=["climate_ssp","station_ssp","tech","year"]
        assert frame.groupby(group)[field].nunique().eq(1).all()
        frame=frame.groupby(group,as_index=False)[field].first()
        frame["model"]="catalogue"
    elif annual:
        frame=models.copy()
    else:
        frame=models.copy()
        frame["period_start"]=frame.year//10*10
        group=["model","climate_ssp","station_ssp","tech","period_start"]
        assert frame.groupby(group).size().eq(10).all()
        frame=frame.groupby(group,as_index=False)[[field,"capacity_mw","catalogue_capacity_mw","capacity_coverage"]].mean()
        frame["year"]=frame.period_start
        frame["period_end"]=frame.year+9
        frame["n_years"]=10
    frame["value"]=frame[field]*scale
    assert np.isfinite(frame.value).all()
    frame.to_csv(out/"source_data"/(name+"_models.csv"),index=False)
    display=frame.groupby(["climate_ssp","station_ssp","tech","year"]).value.agg(
        mean="mean",minimum="min",maximum="max",n_models="count").reset_index()
    assert display.n_models.eq(1 if name=="capacity" else 4).all()
    display.to_csv(out/"source_data"/(name+"_display.csv"),index=False)
    return display


def panel(ax,display,tech,title,letter,metric):
    name,_,_,_,_,annual,_=metric
    fits=[]
    for ssp,marker in zip(SSPS,["o","s","^"]):
        f=display[display.tech.eq(tech)&display.climate_ssp.eq(ssp)].sort_values("year")
        x=f.year.to_numpy(float);y=f["mean"].to_numpy(float)
        ax.plot(x,y,color=SSP_COLORS[ssp],lw=1.15,marker=None if annual else marker,ms=3.5)
        if name!="capacity":
            ax.fill_between(x,f.minimum.to_numpy(float),f.maximum.to_numpy(float),color=SSP_COLORS[ssp],alpha=.13,lw=0)
        if annual:
            slope,intercept=np.polyfit(x-2030,y,1)
            ax.plot(x,intercept+slope*(x-2030),color=SSP_COLORS[ssp],lw=1,ls="--")
            fits.append(dict(figure=name,tech=tech,climate_ssp=ssp,n_years=30,start=2030,end=2059,
                             slope_per_year=float(slope),fitted_value_2030=float(intercept)))
    ax.set_title(title,fontsize=9,pad=8)
    ax.text(0,1.11,letter,transform=ax.transAxes,fontweight="bold",fontsize=9)
    if annual:
        ax.set_xticks([2030,2040,2050,2059]);ax.set_xlim(2029,2060);ax.set_xlabel("Year")
    else:
        ax.set_xticks([2030,2040,2050],["2030s","2040s","2050s"]);ax.set_xlim(2028,2052);ax.set_xlabel("Decade")
    ax.grid(axis="y",color=".9",lw=.45)
    ax.ticklabel_format(axis="y",style="sci",scilimits=(-3,5),useMathText=True)
    ax.tick_params(length=3,width=.7)
    return fits


def decorate(fig,metric,solo):
    from matplotlib.lines import Line2D
    name=metric[0]
    fig.suptitle("Dispatch-2025 global stations"+("\n" if solo else " | ")+TITLES[name],
                 fontsize=9 if solo else 10,y=.97)
    handles=[Line2D([],[],color=SSP_COLORS[s],lw=1.5,label=s.upper()) for s in SSPS]
    if metric[5]:
        handles.append(Line2D([],[],color=".4",lw=1,ls="--",label="2030–2059 linear fit"))
    fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.53,.11 if solo and metric[6] else .07),ncol=2 if solo and metric[5] else len(handles),fontsize=7)
    note="Total capacity snapshots" if name=="capacity" else "Four-GCM mean; shading: model min–max"
    if metric[6]:note+="; independent y axes"
    fig.text(.53,.025,note if not solo else note.replace("; ","\n"),ha="center",fontsize=6.5,color=".35")


def render_metric(display, metric, out):
    import matplotlib.pyplot as plt
    name=metric[0]
    fig,axes=plt.subplots(1,3,figsize=(240/25.4,85/25.4),sharey=not metric[6])
    fig.subplots_adjust(left=.10,right=.985,bottom=.27,top=.78,wspace=.35 if metric[6] else .15)
    fits=[]
    for ax,(tech,title),letter in zip(axes,TECHS,"abc"):
        fits+=panel(ax,display,tech,title,letter,metric)
    if metric[6]:
        # Include model-range shading when choosing the six evenly spaced ticks.
        for ax,(tech,_) in zip(axes,TECHS):
            f=display[display.tech.eq(tech)]
            bounds=np.array([f.minimum.min(),f.maximum.max()])
            guide,=ax.plot([2030,2059],bounds,alpha=0,lw=0)
            independent_y_ticks(ax,intervals=5)
            guide.remove()
    limits=[list(ax.get_ylim()) for ax in axes]
    ticks=[ax.get_yticks().tolist() for ax in axes]
    axes[0].set_ylabel(metric[3],labelpad=7)
    decorate(fig,metric,False)
    filename="dispatch2025_"+name
    full=export_panel_png(fig,out/(filename+".png"))
    panels=[]
    for i,((tech,title),letter) in enumerate(zip(TECHS,"abc")):
        fig,ax=plt.subplots(figsize=(105/25.4,100/25.4))
        fig.subplots_adjust(left=.25,right=.97,bottom=.30,top=.74)
        panel(ax,display,tech,title,letter,metric)
        ax.set_yticks(ticks[i]);ax.set_ylim(limits[i])
        np.testing.assert_allclose(ax.get_ylim(),limits[i],rtol=0,atol=0)
        ax.set_ylabel(metric[3],labelpad=7)
        decorate(fig,metric,True)
        panels.append(export_panel_png(fig,out/(filename+"_"+letter+".png")))
    if fits:
        pd.DataFrame(fits).to_csv(out/"source_data"/(name+"_fits.csv"),index=False)
    record=dict(name=name,title=metric[4],field=metric[1],scale=metric[2],annual=metric[5],
                        independent_y=metric[6],figure=filename+".png",panels=[filename+"_"+c+".png" for c in "abc"],
                        ylimits=limits,yticks=ticks,export=full,panel_export=panels)
    print("Rendered",filename,flush=True)
    return record,fits


def render(root,out):
    out.mkdir(parents=True,exist_ok=True);(out/"source_data").mkdir(exist_ok=True)
    os.environ.setdefault("MPLBACKEND","Agg")
    os.environ.setdefault("MPLCONFIGDIR",str(out/".mplconfig"))
    import matplotlib.pyplot as plt
    configure();plt.rcParams.update({"font.size":8})
    models,indexpath,index=tables(root,out)
    records=[];allfits=[]
    for metric in METRICS:
        name=metric[0];display=metric_table(models,metric,out)
        record,fits=render_metric(display,metric,out)
        records.append(record);allfits+=fits
    pd.DataFrame(allfits).to_csv(out/"source_data/trend_fits.csv",index=False)
    assert len(records)==8 and len(allfits)==45
    pngs=list(out.glob("*.png"))
    assert len(pngs)==32
    manifest=dict(status="COMPLETED",source_index=str(indexpath),source_index_sha256=digest(indexpath),
        models=index["models"],climate_ssps=SSPS,station_ssps=SSPS,years=[2030,2059],
        figures=records,files={p.name:dict(sha256=digest(p),size_bytes=p.stat().st_size) for p in pngs},
        source_tables={p.name:dict(sha256=digest(p),rows=len(pd.read_csv(p))) for p in (out/"source_data").glob("*.csv")},
        backend="Python/matplotlib",dpi=600,paired_pathways=True)
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    (out/"capacity_manifest.json").unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--output-dir",type=Path,default=HERE/"outputs")
    a=p.parse_args();render(a.root,a.output_dir)


if __name__=="__main__":
    main()
