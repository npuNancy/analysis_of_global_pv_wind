"""Shared presentation and audit helpers for supplementary figures."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from paper_figures.config import ROOT, MODELS, SSPS, SSP_COLORS, EVENTS
from paper_figures.common.plotting import configure, save_png

configure()
plt.rcParams.update({"axes.titlesize":8,"axes.labelsize":7,"xtick.labelsize":6,
                     "ytick.labelsize":6,"legend.fontsize":6,"hatch.linewidth":0.5})
COLORS=[SSP_COLORS[x] for x in SSPS]
MARKERS=["o","s","^","v"]
TECHS=["wind","solar"]
NAMES={"high_temp":"High temperature","high_wind":"High wind","hot_humid":"Hot–humid",
"icing":"Icing","low_resource":"Low resource","cold_highwind":"Cold–high wind",
"freezing_rain":"Freezing rain","high_humidity":"High humidity","rainstorm":"Rainstorm","all":"All (union)"}
LOSS="Net loss (MWh MW⁻¹ yr⁻¹)"
DELTA="Loss change (MWh MW⁻¹ yr⁻¹)"
CASES=pd.read_csv(ROOT/"paper_figures/prepare/outputs/panel_loss/country_selection.csv").country.tolist()
def read(base,name):
    return pd.read_csv(base/"outputs/source_data"/name)
def select(df,**filters):
    for key,value in filters.items():
        if key in df: df=df[df[key].isin(value if isinstance(value,list) else [value])]
    return df.copy()
def four(values):
    a=np.asarray(values,dtype=float)
    return len(a)==4 and np.isfinite(a).all()
def summary(df,keys,value):
    g=df.groupby(keys,dropna=False)[value]
    result=g.agg(["mean","min","max","count"]).reset_index()
    result.loc[result["count"]!=4,["mean","min","max"]]=np.nan
    return result
def panel(ax,letter,title):
    ax.set_title(title,loc="left",pad=9)
    ax.text(-.14,1.08,letter,transform=ax.transAxes,weight="bold",fontsize=10)
def zero(ax,both=False):
    ax.axhline(0,color=".6",lw=.5,zorder=0)
    if both: ax.axvline(0,color=".6",lw=.5,zorder=0)
def identity(ax):
    lo=min(*ax.get_xlim(),*ax.get_ylim()); hi=max(*ax.get_xlim(),*ax.get_ylim())
    ax.set(xlim=(lo,hi),ylim=(lo,hi));ax.plot([lo,hi],[lo,hi],color=".55",ls="--",lw=.7,zorder=0)
def model_legend(fig,y=0):
    fig.legend([Line2D([],[],marker=m,color=".4",ls="",markersize=3) for m in MARKERS],
               MODELS,loc="lower center",bbox_to_anchor=(.5,y),ncol=4)
def scenario_legend(fig,y=0):
    fig.legend([Line2D([],[],color=c,lw=2) for c in COLORS],
               ["SSP1-2.6","SSP2-4.5","SSP5-8.5"],loc="lower center",bbox_to_anchor=(.5,y),ncol=3)
def event_order(tech):
    path=ROOT/"paper_figures/prepare/outputs/event_summary/window.csv.gz"
    d=select(pd.read_csv(path),tech=tech,snapshot=2050,country="GLOBAL",
             climate_ssp="ssp126",station_ssp="ssp126")
    return d[d.event!="all"].groupby("event").E.mean().sort_values(ascending=False).index.tolist()
def finish(fig,base,name,checks=None,note=""):
    out=base/"outputs";out.mkdir(exist_ok=True,parents=True)
    save_png(fig,out/(name+".png"));plt.close(fig)
    files=sorted((out/"source_data").glob("*.csv*"))
    audit={"figure":name,"dpi":600,"source_files":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
           "checks":checks or {},"note":note,"visual_review":"pending"}
    (out/(name+"_audit.json")).write_text(json.dumps(audit,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print(out/(name+".png"),flush=True)
def point_range(ax,values,pos,color,vertical=False):
    vals=np.asarray(values,dtype=float)
    if not four(vals):return
    mean=vals.mean()
    if vertical:
        ax.vlines(pos,vals.min(),vals.max(),color=color,lw=1)
        ax.scatter(np.full(4,pos),vals,c=color,s=10,zorder=3)
        ax.scatter(pos,mean,marker="D",facecolors="white",edgecolors=color,s=24,zorder=4)
    else:
        ax.hlines(pos,vals.min(),vals.max(),color=color,lw=1)
        ax.scatter(vals,np.full(4,pos),c=color,s=10,zorder=3)
        ax.scatter(mean,pos,marker="D",facecolors="white",edgecolors=color,s=24,zorder=4)
