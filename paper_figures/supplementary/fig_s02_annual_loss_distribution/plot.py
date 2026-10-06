"""Fig. S02: model-wise empirical annual exceedance curves."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=read(BASE,"panel_ab.csv");assert (d.n_years==10).all()
    fig,axs=plt.subplots(1,2,figsize=(7.2,3.2))
    for j,tech in enumerate(TECHS):
        ax=axs[j]
        for s,c in zip(SSPS,COLORS):
            q=d[(d.tech==tech)&(d.climate_ssp==s)]
            wide=q.pivot(index="threshold",columns="model",values="exceedance_pct").reindex(columns=MODELS)
            assert wide.notna().all().all()
            assert (np.diff(wide.values,axis=0)<=1e-8).all()
            x=wide.index.to_numpy();y=wide.values
            # Extend below the minimum threshold to show the 100% endpoint.
            x=np.r_[x[0]-max(np.ptp(x)*.02,1e-6),x];y=np.vstack([np.full(4,100.),y])
            ax.fill_between(x,y.min(1),y.max(1),step="post",color=c,alpha=.15)
            ax.step(x,y.mean(1),where="post",color=c,lw=1.3)
        ax.set(xlabel=LOSS,ylabel="Annual exceedance (%)",ylim=(0,100))
        panel(ax,"ab"[j],tech.title()+" · 2050–2059");ax.grid(axis="y",lw=.3,alpha=.3)
    fig.subplots_adjust(left=.1,right=.98,top=.87,bottom=.23,wspace=.38);scenario_legend(fig,.01)
    finish(fig,BASE,"fig_s02_annual_loss_distribution",{"years_per_model":10,"monotonic":True},
           "Strict exceedance P(R > x); four-model mean and min–max, not 40 independent years.")
if __name__=="__main__":main()
