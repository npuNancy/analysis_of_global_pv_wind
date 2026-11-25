"""Compose the RQ1 exposure maps, pathway curves, and loss histograms."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator, PercentFormatter
import numpy as np
import pandas as pd

from paper_figures.common.io import digest
from paper_figures.common.plotting import export_panel_png
from paper_figures.config import ROOT, SSPS, SSP_COLORS, TECHS
from paper_figures.main.fig01_extreme_events.meeting_plotting import configure, degree_axes, draw_borders
from paper_figures.supplementary.rq2_siting_loss.plot import COLORS
from paper_figures.supplementary.rq2_siting_loss.plot_comparison import FIELDS, Y_SEGMENTS, Y_TICKS

BUNDLE = ROOT / "tmp/RQ1_20261123_candidates"
DATA = BUNDLE / "source_data"
IMAGES = BUNDLE / "images"
GROUP_OUTPUT = Path(__file__).resolve().parent / "outputs/rq1_composite"
PROJECTION = ccrs.PlateCarree()
TECH_LABELS = {"wind":"Wind", "solar":"Solar PV"}
MARKERS = ("o","s","^")
CURVE_TITLES = (r"Exposure (days yr$^{-1}$)", "Event-period loss (%)",
                r"Net loss (MWh MW$^{-1}$ yr$^{-1}$)")
RIGHT_X = (.592,.728,.864)
RIGHT_WIDTH = .111
RIGHT_CENTER = .761
DOMAIN_LABELS = {"fixed2025":"2025 sites", "suitable":"Suitable grids"}
MAP_COLORMAP = "YlOrRd"
DPI = 600


def group_title(fig, letter, x, y, label):
    fig.text(x,y,letter,weight="bold",fontsize=11,ha="left",va="center")
    fig.text(x+.016,y,label,weight="bold",fontsize=8,ha="left",va="center")


def read_inputs():
    maps_path = DATA/"rq1_exposure_union_maps.npz"
    with np.load(maps_path) as data:
        maps = {key: data[key] for key in data.files}
    assert tuple(maps["decades"]) == (2020,2050) and tuple(maps["ssps"]) == SSPS
    assert np.array_equal(np.isfinite(maps["exposure_days"]).all(axis=(0,1)),maps["area_km2"] > 0)
    report = json.loads((DATA/"rq1_exposure_union_validation.json").read_text())
    assert report["map_sha256"] == digest(maps_path)
    area = maps["area_km2"]
    means = np.nansum(maps["exposure_days"]*area,axis=(2,3))/area.sum()
    np.testing.assert_allclose(means.ravel(),[r["global_area_weighted_exposure_days"] for r in report["records"]],
                               atol=1e-10)
    keys = ["tech","climate_ssp","time","domain"]
    curves = pd.read_csv(DATA/"curve_display.csv")
    models = pd.read_csv(DATA/"curve_models.csv")
    mean = models.groupby(keys,as_index=False)[list(FIELDS)].mean().merge(curves,on=keys,validate="one_to_one")
    assert len(curves) == len(mean) == 36 and len(models) == len(curves)*4
    for field in FIELDS:
        np.testing.assert_allclose(mean[field],mean[f"{field}_mean"],rtol=1e-12)
    bins = pd.read_csv(DATA/"histogram_bins.csv")
    assert bins.groupby(["tech","climate_ssp","domain"]).ngroups == 12
    np.testing.assert_allclose(bins.groupby(["tech","climate_ssp","domain"]).relative_frequency.sum(),1,atol=1e-12)
    axis_contract = json.loads((BUNDLE/"comparison_figure_contract.json").read_text())["y_axes"]
    return maps,curves,bins,axis_contract


def draw_maps(fig,maps):
    values = maps["exposure_days"]
    finite = values[np.isfinite(values)]
    p02,p98 = np.quantile(finite,[.02,.98])
    low,high = 5*np.ceil(p02/5),5*np.floor(p98/5)
    assert finite.min() < low < high < finite.max()
    cmap = plt.get_cmap(MAP_COLORMAP).with_extremes(bad=(0,0,0,0))
    norm = Normalize(low,high)
    for di,(decade,x) in enumerate(zip(maps["decades"],(.033,.282))):
        group_title(fig,"ab"[di],x-.007,.969,f"Wind and solar exposure | {int(decade)}s")
        for si,(ssp,y) in enumerate(zip(SSPS,(.683,.405,.127))):
            box = [.0+x,y,.222,.222]
            ax = fig.add_axes(box,projection=PROJECTION)
            ax.set_global()
            ax.add_geometries(LAND,crs=PROJECTION,facecolor="#eeeeec",edgecolor="none",zorder=0)
            ax.imshow(values[di,si],origin="lower",extent=(-180,180,-90,90),transform=PROJECTION,
                      cmap=cmap,norm=norm,interpolation="nearest",zorder=1)
            draw_borders(ax,lw=.29,color=".34")
            degree_axes(ax,(-120,0,120),(-60,0,60))
            ax.grid(True,linewidth=.22,color=".72")
            ax.spines["geo"].set_linewidth(.35)
            ax.set_title(ssp.upper(),fontsize=7,pad=3.5)
    cbax = fig.add_axes([.095,.063,.344,.014])
    fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=cbax,orientation="horizontal",
                 extend="both",ticks=np.linspace(low,high,5),
                 label=r"Area-weighted annual exposure (days yr$^{-1}$)")
    return [float(low),float(high)]


def draw_curves(fig,curves,contract):
    group_title(fig,"c",.541,.969,"Exposure, intensity and net loss | 2030s–2050s")
    for ti,tech in enumerate(TECHS):
        y = (.773,.587)[ti]
        height = .139
        fig.text(.548,y+height/2,TECH_LABELS[tech],rotation=90,ha="center",va="center",fontsize=7,weight="bold")
        for ci,(field,x) in enumerate(zip(FIELDS,RIGHT_X)):
            if ti == 0:
                fig.text(x+RIGHT_WIDTH/2,.930,CURVE_TITLES[ci],ha="center",va="center",fontsize=6.7)
            name = "abcdef"[ti*3+ci]
            axis = contract.get(name,{})
            vals = curves.loc[curves.tech.eq(tech),field+"_mean"].to_numpy()
            ranges = axis.get("segments",Y_SEGMENTS.get(name))
            if not isinstance(ranges,(tuple,list)):
                pad = max(np.ptp(vals)*.08,.12)
                ranges = [(vals.min()-pad,vals.max()+pad)]
            ticks = axis.get("ticks",Y_TICKS.get(name))
            if ticks is None:
                ticks = [[v for v in MaxNLocator(4).tick_values(lo,hi) if lo <= v <= hi] for lo,hi in ranges]
            gap = .014 if len(ranges)==2 else 0
            scale = (height-gap)/sum(hi-lo for lo,hi in ranges)
            bottom = y
            axes = []
            for j,((lo,hi),target_ticks) in enumerate(zip(ranges,ticks)):
                h = scale*(hi-lo)
                ax = fig.add_axes([x,bottom,RIGHT_WIDTH,h])
                ax.set_ylim(lo,hi)
                ax.set_yticks(target_ticks)
                ax.set_xlim(2028,2052)
                ax.set_xticks([2030,2040,2050],["2030s","2040s","2050s"])
                if j:
                    ax.spines["bottom"].set_visible(False)
                    ax.tick_params(axis="x",bottom=False,labelbottom=False)
                ax.grid(axis="y",color=".9",lw=.40)
                ax.set_axisbelow(True)
                axes.append(ax)
                bottom += h+gap
            for ssp,marker in zip(SSPS,MARKERS):
                for domain,style in [("fixed2025","-"),("suitable","--")]:
                    series = curves.loc[curves.tech.eq(tech)&curves.climate_ssp.eq(ssp)
                                        &curves.domain.eq(domain)].sort_values("time")
                    assert series.time.tolist() == [2030,2040,2050]
                    ydata = series[field+"_mean"]
                    targets = [ax for ax,(lo,hi) in zip(axes,ranges) if ydata.between(lo,hi,inclusive="neither").all()]
                    assert len(targets)==1,(tech,field,ssp,domain)
                    color = SSP_COLORS[ssp]
                    targets[0].plot(series.time,ydata,color=color,linestyle=style,lw=1,
                                    marker=marker,ms=2.4,mew=.60,mfc=color if domain=="fixed2025" else "white")
            if len(axes)==2:
                for ax,edge in zip(axes,(1,0)):
                    ax.plot([0],[edge],marker=[(-1,-.55),(1,.55)],ms=4.4,
                            transform=ax.transAxes,linestyle="none",clip_on=False,mew=.60,color=".25")
    handles = [Line2D([],[],color=SSP_COLORS[s],marker=m,ms=2.5,label=s.upper()) for s,m in zip(SSPS,MARKERS)]
    handles += [Line2D([],[],color=".2",linestyle=style,label=DOMAIN_LABELS[d])
                for d,style in [("fixed2025","-"),("suitable","--")]]
    fig.legend(handles=handles,loc="center",bbox_to_anchor=(RIGHT_CENTER,.535),ncol=5,fontsize=6.1,
               handlelength=2,columnspacing=1.2)


def draw_histograms(fig,bins):
    group_title(fig,"d",.541,.483,"Unit-capacity net-loss distributions | 2050s")
    fig.text(.530,.261,"Relative frequency",rotation=90,ha="center",va="center",fontsize=6.4)
    for ti,tech in enumerate(TECHS):
        y = (.286,.099)[ti]
        height = .137
        fig.text(.549,y+height/2,TECH_LABELS[tech],rotation=90,ha="center",va="center",fontsize=7,weight="bold")
        ymax = float(bins.loc[bins.tech.eq(tech),"relative_frequency"].max()*1.12)
        for ci,(ssp,x) in enumerate(zip(SSPS,RIGHT_X)):
            ax = fig.add_axes([x,y,RIGHT_WIDTH,height])
            if ti==0:
                ax.set_title(ssp.upper(),fontsize=6.7,pad=3.4)
            for domain in ("suitable","fixed2025"):
                b = bins.loc[bins.tech.eq(tech)&bins.climate_ssp.eq(ssp)&bins.domain.eq(domain)].sort_values("left")
                edges = np.r_[b.left,b.right.iloc[-1]]
                ax.stairs(b.relative_frequency,edges,fill=True,color=COLORS[domain],alpha=.61,lw=0)
                ax.stairs(b.relative_frequency,edges,color=COLORS[domain],lw=.55)
            lo,hi = edges[0],edges[-1]
            ax.set_xlim(lo,hi)
            ax.set_ylim(0,ymax)
            ax.set_xticks([v for v in MaxNLocator(4).tick_values(lo,hi) if lo<=v<=hi])
            ax.set_yticks([v for v in MaxNLocator(4).tick_values(0,ymax) if 0<=v<=ymax])
            ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
            if ci:
                ax.tick_params(axis="y",labelleft=False)
            ax.grid(axis="y",color=".9",lw=.4)
            ax.set_axisbelow(True)
    fig.text(RIGHT_CENTER,.063,r"Net loss (MWh MW$^{-1}$ yr$^{-1}$)",ha="center",va="center",fontsize=6.9)
    fig.legend(handles=[Patch(facecolor=COLORS[d],alpha=.7,label=label)
                        for d,label in [("fixed2025","2025 installed grids"),("suitable","Suitable grids")]],
               loc="center",bbox_to_anchor=(RIGHT_CENTER,.028),ncol=2,fontsize=6.4)


def main():
    from paper_figures.common.spatial import countries
    global LAND
    LAND = [geometry for _,_,geometry in countries()]
    configure()
    plt.rcParams.update({"xtick.labelsize":5.7,"ytick.labelsize":5.7})
    maps,curves,bins,contract = read_inputs()
    fig = plt.figure(figsize=(300/25.4,150/25.4),dpi=160)
    bounds = draw_maps(fig,maps)
    draw_curves(fig,curves,contract)
    draw_histograms(fig,bins)
    # Keep the two map columns together with their shared colour bar.
    groups = [("ab",[.004,.006,.517,.993]),("c",[.529,.509,.993,.993]),("d",[.520,.008,.993,.508])]
    products = [export_panel_png(fig,GROUP_OUTPUT/f"rq1_exposure_loss_{stem}.png",bounds=box,close=False)
                for stem,box in groups]
    products.append(export_panel_png(fig,IMAGES/"rq1_exposure_loss_composite.png"))
    report = {"backend":"Python/Matplotlib/Cartopy","projection":"PlateCarree",
              "layout":"a 2020s and b 2050s wind–solar union exposure maps, c trajectories, d loss histograms",
              "map_colormap":MAP_COLORMAP,"map_color_limits_days_per_year":bounds,"colorbar_extend":"both","products":products,
              "curve_data_sha256":digest(DATA/"curve_display.csv"),"histogram_data_sha256":digest(DATA/"histogram_bins.csv"),
              "map_data_sha256":digest(DATA/"rq1_exposure_union_maps.npz")}
    (DATA/"rq1_composite_figure_validation.json").write_text(json.dumps(report,indent=2)+"\n")
    print(f"Rendered {len(products)} PNGs with shared map limits {bounds}.",flush=True)


if __name__ == "__main__":
    main()
