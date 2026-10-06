"""Fig. S07: seasonal contributions to annual exposure and signed-loss differences."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    exposure=select(read(BASE,"panel_ab.csv"),country="GLOBAL",snapshot=2050,station_ssp="ssp126",climate_ssp=["ssp126","ssp585"])
    loss=select(read(BASE,"panel_cd.csv"),country="GLOBAL",station_ssp="ssp126",climate_ssp=["ssp126","ssp585"])
    checks=read(BASE,"annual_reproduction.csv")
    err=float((checks.seasonal_sum-checks.R).abs().max());assert err<.002
    fig,axs=plt.subplots(2,2,figsize=(7.2,6.4));seasons=["DJF","MAM","JJA","SON"]
    for i,(df,value,unit) in enumerate([(exposure,"E","Exposure change (h yr⁻¹)"),(loss,"R",DELTA)]):
        w=df.pivot(index=["tech","model","event","season"],columns="climate_ssp",values=value)
        w["difference"]=w.ssp585-w.ssp126
        q=summary(w.reset_index(),["tech","event","season"],"difference")
        lim=max(float(q["mean"].abs().max()),1e-8)
        for j,tech in enumerate(TECHS):
            ax=axs[i,j];events=event_order(tech)+["all"]
            a=q[q.tech==tech].pivot(index="event",columns="season",values="mean").reindex(index=events,columns=seasons)
            cmap=plt.get_cmap("RdBu_r").copy();cmap.set_bad(".8")
            im=ax.imshow(a.values,aspect="auto",cmap=cmap,vmin=-lim,vmax=lim)
            for row in range(len(events)):
                for col in range(4):
                    v=a.iloc[row,col]
                    if np.isfinite(v):ax.text(col,row,f"{0.0 if abs(v)<.05 else v:.1f}",ha="center",va="center",fontsize=6,color="white" if abs(v)>.6*lim else ".1")
            ax.axhline(len(events)-1.5,color="white",lw=3)
            ax.set_xticks(range(4),seasons);ax.set_yticks(range(len(events)),[NAMES[e] for e in events])
            panel(ax,"abcd"[2*i+j],tech.title())
            cb=fig.colorbar(im,ax=ax,orientation="horizontal",pad=.12,fraction=.06);cb.set_label(unit)
    fig.text(.5,.02,"2050–2059 · climate SSP5-8.5 minus SSP1-2.6 · fixed SSP1-2.6 deployment",ha="center",fontsize=6)
    fig.subplots_adjust(left=.17,right=.98,top=.94,bottom=.13,hspace=.4,wspace=.55)
    finish(fig,BASE,"fig_s07_seasonal_patterns",{"annual_loss_reproduction_error":err},
           "DJF = Jan, Feb, Dec within each year; four-model means; seasons sum to annual, overlapping event types do not sum to all.")
if __name__=="__main__":main()
