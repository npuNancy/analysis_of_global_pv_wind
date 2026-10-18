"""Plot country SSP contrasts and event exposures from small summary tables."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import cartopy.crs as ccrs
from paper_figures.config import SSPS, SSP_COLORS, EVENTS
from paper_figures.common.spatial import countries
from paper_figures.common.io import write_json
from .analyze_ssp_station import OUT
from .analyze_ssp_grid import PAIRS

LABELS={"all":"Union","high_temp":"High temperature","high_wind":"High wind","hot_humid":"Hot & humid","icing":"Icing","low_resource":"Low resource","cold_highwind":"Cold & high wind","freezing_rain":"Freezing rain","high_humidity":"High humidity","rainstorm":"Rainstorm"}
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument("--output-root",type=Path,default=OUT);a=p.parse_args()
    out=a.output_root
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    diff=pd.read_csv(out/"contrasts.csv");level=pd.read_csv(out/"levels.csv")
    data=diff[diff.snapshot.eq(2050)&diff.comparison.eq("paired")&diff.metric.eq("exposure_days")&diff.event.eq("all")&diff.region.str.startswith("country:")]
    geo=countries();projection=ccrs.PlateCarree();outputs=[]
    def save(fig,name):
        path=out/(name+".png");fig.savefig(path,dpi=240,facecolor="white");plt.close(fig);outputs.append(path.name)
    def maps(techs,name,unit="Exposure difference (days/year)"):
        fig,axes=plt.subplots(len(techs),3,figsize=(13,3.0*len(techs)+.55),subplot_kw={"projection":projection},squeeze=False)
        fig.subplots_adjust(left=.04,right=.91,bottom=.08,top=.87,wspace=.09,hspace=.32)
        for row,tech in enumerate(techs):
            part=data[data.tech.eq(tech)];limit=max(float(part["mean"].abs().max()),1)
            norm=colors.TwoSlopeNorm(vmin=-limit,vcenter=0,vmax=limit);cmap=plt.get_cmap("RdBu_r")
            for col,(high,low) in enumerate(PAIRS):
                ax=axes[row,col];values=part[part.high.eq(high)&part.low.eq(low)].set_index("region")["mean"]
                for iso,_,geom in geo:
                    v=values.get("country:"+iso,np.nan)
                    ax.add_geometries([geom],crs=projection,facecolor=cmap(norm(v)) if np.isfinite(v) else "#e5e5e5",edgecolor="#777777",linewidth=.22)
                ax.set_extent([-180,180,-60,85],crs=projection)
                ax.set_xticks([-120,0,120],crs=projection);ax.set_yticks([-30,30,60],crs=projection)
                ax.tick_params(labelsize=7,length=2)
                letter="abcdef"[("wind","solar").index(tech)*3+col]
                ax.set_title(f"{letter}  {tech.title()}: {high.upper()} − {low.upper()}",loc="left",fontsize=9)
            box=axes[row,2].get_position();cax=fig.add_axes([.93,box.y0,.012,box.height])
            cb=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=cax);cb.set_label(unit,fontsize=8)
        fig.suptitle("Paired climate and deployment pathways | 2050–2059 | four-model mean",fontsize=11,y=.97)
        note="Capacity-weighted event union. Grey: no defined paired estimate. SSP585 deployment uses the source SSP5-6.0 layout."
        if "(pp)" in unit:note+=" pp = percentage points."
        fig.text(.04,.015,note,fontsize=8)
        save(fig,name)
    maps(["wind","solar"],"ssp_station_exposure_maps")
    maps(["wind"],"ssp_station_exposure_maps_abc")
    maps(["solar"],"ssp_station_exposure_maps_def")
    def bars(techs,name):
        fig,axes=plt.subplots(len(techs),1,figsize=(11,3.6*len(techs)+.5),squeeze=False)
        for ax,tech in zip(axes[:,0],techs):
            events=["all",*EVENTS[tech]];yy=np.arange(len(events))
            d=level[level.snapshot.eq(2050)&level.region.eq("global:GLOBAL")&level.tech.eq(tech)&level.metric.eq("exposure_days")&level.climate_ssp.eq(level.station_ssp)].set_index(["climate_ssp","event"])
            for k,ssp in enumerate(SSPS):
                vals=d.loc[[(ssp,e) for e in events]]
                ax.barh(yy+(k-1)*.23,vals["mean"],height=.21,color=SSP_COLORS[ssp],label=ssp.upper())
                ax.errorbar(vals["mean"],yy+(k-1)*.23,xerr=np.array([vals["mean"]-vals.minimum,vals.maximum-vals["mean"]]),fmt="none",ecolor="#555555",elinewidth=.7,capsize=2)
            ax.set_yticks(yy,[LABELS[e] for e in events]);ax.invert_yaxis()
            ax.set_xlabel("Capacity-weighted exposure (days/year)")
            ax.set_title(("a" if tech=="wind" else "b")+"  "+tech.title(),loc="left",fontweight="bold")
            ax.grid(axis="x",alpha=.15);ax.set_axisbelow(True);ax.legend(ncol=3,loc="lower right",fontsize=8)
        fig.suptitle("Global paired pathways | 2050–2059",fontsize=12)
        fig.tight_layout(rect=(0,.045,1,.96))
        fig.text(.02,.015,"Bars: four-model means; whiskers: model range. Union is not the sum of overlapping event categories.",fontsize=8)
        save(fig,name)
    bars(["wind","solar"],"ssp_station_event_exposure")
    bars(["wind"],"ssp_station_event_exposure_a")
    bars(["solar"],"ssp_station_event_exposure_b")
    if "p95_capacity_pct" in set(level.metric):
        data=diff[diff.snapshot.eq(2050)&diff.comparison.eq("paired")&diff.metric.eq("p95_capacity_pct")&diff.event.eq("all")&diff.region.str.startswith("country:")]
        maps(["wind","solar"],"ssp_station_synchrony_maps","Capacity P95 difference (pp)")
        maps(["wind"],"ssp_station_synchrony_maps_abc","Capacity P95 difference (pp)")
        maps(["solar"],"ssp_station_synchrony_maps_def","Capacity P95 difference (pp)")
        metrics=[("starts_per_year","Event starts","Capacity-weighted count/year"),
                 ("p90_complete_hours","Event duration P90","Hours"),
                 ("annual_max_observed_hours_mean","Annual longest observed spell","Hours"),
                 ("p95_capacity_pct","Synchronous capacity P95","% of fixed capacity")]
        def dynamics(techs,name):
            fig,axes=plt.subplots(len(techs),4,figsize=(13,2.9*len(techs)+.65),squeeze=False)
            for row,tech in enumerate(techs):
                for col,(metric,title,unit) in enumerate(metrics):
                    ax=axes[row,col]
                    part=level[level.snapshot.eq(2050)&level.region.eq("global:GLOBAL")&level.event.eq("all")&level.tech.eq(tech)&level.metric.eq(metric)&level.climate_ssp.eq(level.station_ssp)].set_index("climate_ssp").loc[list(SSPS)]
                    y=part["mean"].to_numpy()
                    colour="#1d3b6f" if tech=="wind" else "#b77c19"
                    ax.errorbar(np.arange(3),y,yerr=np.array([y-part.minimum.to_numpy(),part.maximum.to_numpy()-y]),fmt="o-",color=colour,capsize=3,linewidth=1.3)
                    ax.set_xticks(range(3),["126","245","585"]);ax.set_xlabel("Paired SSP")
                    ax.set_ylabel(unit);ax.grid(axis="y",alpha=.15)
                    letter="abcdefgh"[("wind","solar").index(tech)*4+col]
                    ax.set_title(f"{letter}  {tech.title()}: {title}",loc="left",fontsize=8)
            fig.suptitle("Event union: frequency, persistence and synchrony | 2050–2059",fontsize=11)
            fig.tight_layout(rect=(.01,.075,.99,.94),w_pad=1.8)
            fig.text(.03,.025,"Points: four-model means; whiskers: model range. Climate and deployment SSPs change together.",fontsize=8)
            save(fig,name)
        dynamics(["wind","solar"],"ssp_station_dynamics")
        dynamics(["wind"],"ssp_station_dynamics_abcd")
        dynamics(["solar"],"ssp_station_dynamics_efgh")
    write_json(out/"figure_audit.json",dict(files=outputs,projection="PlateCarree",scenario_comparison="paired climate/deployment",snapshot=2050,units="as labelled: days/year, hours, counts/year, percent or percentage points",uncertainty="four-model range",country_geometry="China union Taiwan",missing="grey; no zero imputation"))
    print("PLOTS",outputs,flush=True)
if __name__=="__main__":main()
