"""Fig. S03: positive-net-loss reference-capacity concentration."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=read(BASE,"panel_ab.csv");fig,axs=plt.subplots(1,2,figsize=(7.2,3.3))
    for j,tech in enumerate(TECHS):
        ax=axs[j];q=d[d.tech==tech]
        wide=q.pivot(index="rank",columns="model",values="cumulative_burden_pct").reindex(columns=MODELS)
        x=q.groupby("rank").cumulative_capacity_pct.mean().values
        assert wide.notna().all().all();assert np.allclose(wide.iloc[-1],100)
        assert np.isclose(x[-1],100)
        x=np.r_[0,x];y=np.vstack([np.zeros(4),wide.values])
        ax.fill_between(x,y.min(1),y.max(1),color=COLORS[0],alpha=.18)
        ax.plot(x,y.mean(1),color=COLORS[0],lw=1.4)
        ax.plot([0,100],[0,100],"--",color=".6",lw=.7)
        for n,off in [(5,(25,8)),(10,(25,18))]:
            ax.scatter(x[n],y[n].mean(),s=15,c=COLORS[0])
            ax.annotate(f"Top {n}",(x[n],y[n].mean()),xytext=off,textcoords="data",fontsize=6,arrowprops=dict(arrowstyle="-",lw=.5,color=".4"))
        ax.set(xlim=(0,100),ylim=(0,100),xlabel="Cumulative reference capacity (%)",
               ylabel="Cumulative weighted positive net loss (%)")
        panel(ax,"ab"[j],tech.title()+" · SSP1-2.6, 2050")
    fig.subplots_adjust(left=.1,right=.98,top=.86,bottom=.19,wspace=.4)
    finish(fig,BASE,"fig_s03_loss_concentration",{"endpoints_100_pct":True},
           "Fixed descending country order by four-model mean signed R; reference-capacity-weighted index, not actual loss energy; ribbon = model min–max.")
if __name__=="__main__":main()
