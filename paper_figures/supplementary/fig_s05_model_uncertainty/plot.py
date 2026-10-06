"""Fig. S05: four-model spread and map direction agreement."""
from pathlib import Path
from matplotlib.colors import BoundaryNorm, ListedColormap
import cartopy.crs as ccrs
from paper_figures.common.spatial import countries
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def dots(ax,q,labels,keys):
    for i,key in enumerate(keys):
        a=q
        for col,value in key.items():a=a[a[col]==value]
        a=a.set_index("model").reindex(MODELS)
        c=SSP_COLORS[key["climate_ssp"]]
        vals=a.R.values
        if not four(vals):continue
        ax.hlines(i,vals.min(),vals.max(),color=c,lw=.8)
        for n,v in enumerate(vals):ax.scatter(v,i,marker=MARKERS[n],s=10,color=c,zorder=3)
        ax.scatter(vals.mean(),i,marker="D",facecolors="white",edgecolors=c,s=23,zorder=4)
    ax.set_yticks(range(len(keys)),labels);ax.invert_yaxis();ax.set_xlabel(LOSS)
def main():
    ab=read(BASE,"panel_ab.csv");cd=read(BASE,"panel_cd.csv");ef=select(read(BASE,"panel_ef.csv.gz"),snapshot=2050)
    fig=plt.figure(figsize=(7.2,9.5));gs=fig.add_gridspec(3,2,height_ratios=[1,1.8,1],hspace=.45,wspace=.5)
    for j,tech in enumerate(TECHS):
        ax=fig.add_subplot(gs[0,j])
        keys=[{"climate_ssp":c,"station_ssp":s} for c in SSPS for s in SSPS]
        labels=[f"C{c[-3:]} / S{s[-3:]}" for c in SSPS for s in SSPS]
        dots(ax,ab[ab.tech==tech],labels,keys)
        for i,label in enumerate(ax.get_yticklabels()):
            if i in [0,4,8]:label.set_weight("bold")
        panel(ax,"ab"[j],tech.title()+" · climate / deployment")
        ax=fig.add_subplot(gs[1,j]);events=event_order(tech)
        keys=[{"climate_ssp":s,"station_ssp":s,"event":e} for e in events for s in SSPS]
        labels=[NAMES[e] if s=="ssp245" else "" for e in events for s in SSPS]
        dots(ax,cd[cd.tech==tech],labels,keys)
        for i in range(1,len(events)):ax.axhline(i*3-.5,color=".9",lw=.6,zorder=0)
        panel(ax,"cd"[j],tech.title()+" · paired paths")
        ax=fig.add_subplot(gs[2,j],projection=ccrs.PlateCarree());q=ef[ef.tech==tech]
        arr=q.pivot(index="lat",columns="lon",values="agreement")
        means=q.pivot(index="lat",columns="lon",values="mean").reindex_like(arr)
        count=q.pivot(index="lat",columns="lon",values="n_models").reindex_like(arr)
        a=arr.to_numpy(float);a[(count.values!=4)|~np.isfinite(means.values)]=np.nan
        a[(means.values==0)&(count.values==4)]=5
        cmap=ListedColormap(["#f7fbff","#c6dbef","#6baed6","#2171b5","#08306b","#efb454"]);cmap.set_bad("#dddddd")
        im=ax.pcolormesh(arr.columns,arr.index,np.ma.masked_invalid(a),cmap=cmap,norm=BoundaryNorm(np.arange(-.5,6.5),6),
                         transform=ccrs.PlateCarree(),rasterized=True,shading="nearest")
        ax.add_geometries([g for _,_,g in countries()],crs=ccrs.PlateCarree(),facecolor="none",edgecolor=".4",linewidth=.25)
        ax.set_extent([-180,180,-60,85],crs=ccrs.PlateCarree())
        gl=ax.gridlines(draw_labels={"bottom":"x","left":"y"},linewidth=.2,color=".7")
        gl.xlabel_style={"size":6};gl.ylabel_style={"size":6}
        panel(ax,"ef"[j],tech.title()+" · exposure direction")
    cb=fig.colorbar(im,ax=fig.axes[-1],orientation="horizontal",ticks=range(6),fraction=.055,pad=.16)
    cb.ax.set_xticklabels(["0","1","2","3","4","Zero"]);cb.set_label("Models agreeing with mean sign",fontsize=6)
    fig.subplots_adjust(left=.16,right=.98,top=.97,bottom=.1)
    fig.text(.32,.07,"Grey: incomplete model coverage",ha="center",fontsize=6)
    model_legend(fig,.003);scenario_legend(fig,.028)
    finish(fig,BASE,"fig_s05_model_uncertainty",{"projection":"Plate Carrée","four_models":True},
           "2050–2059; min–max, not confidence intervals; grid exposure SSP585–126; orange=zero mean, grey=missing.")
if __name__=="__main__":main()
