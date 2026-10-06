"""Fig. S06: signed, positive-only and annual-generation-normalized contrasts."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=select(read(BASE,"panel_abcd.csv"),snapshot=2050,event="all",support="common")
    d=d[~d.country.isin(["GLOBAL","UNASSIGNED","AMBIGUOUS"])]
    fig,axs=plt.subplots(2,2,figsize=(7.2,6.4))
    for j,tech in enumerate(TECHS):
        t=d[d.tech==tech].pivot(index=["country","model"],columns="metric",values="D")
        s=t.groupby("country").mean();counts=t.groupby("country").count();s[counts!=4]=np.nan
        cap=select(pd.read_csv(ROOT/"paper_figures/prepare/outputs/loss_summary/window.csv.gz"),
                   tech=tech,climate_ssp="ssp126",station_ssp="ssp126",snapshot=2050,event="all",support="common")
        sizes=cap.groupby("country").capacity_mw.mean().reindex(s.index).fillna(0)
        sizes=sizes/10000
        for i,metric in enumerate(["R_positive","annual_loss_pct"]):
            ax=axs[i,j];ax.scatter(s.R,s[metric],s=sizes,c=COLORS[0],alpha=.5,edgecolors="white",linewidths=.3)
            for country in CASES[:4]:
                if country not in s.index:continue
                ax.annotate(country,(s.loc[country,"R"],s.loc[country,metric]),xytext={"USA":(-25,15),"CHN":(20,20),"BRA":(20,-22),"RUS":(-25,-25)}[country],textcoords="offset points",fontsize=6,arrowprops=dict(arrowstyle="-",lw=.4,color=".4"))
                vals=t.loc[country].reindex(MODELS)
                for m in range(4):ax.scatter(vals.R.iloc[m],vals[metric].iloc[m],marker=MARKERS[m],s=7,color=".4",alpha=.6)
            zero(ax,True)
            if i==0:identity(ax)
            ax.set_xlabel("Signed net "+DELTA.replace("Loss","loss"))
            ax.set_ylabel("Positive-loss change (MWh MW⁻¹ yr⁻¹)" if i==0 else "Annual loss-ratio change (percentage points)")
            panel(ax,"abcd"[2*i+j],tech.title())
    fig.subplots_adjust(left=.11,right=.98,top=.94,bottom=.17,hspace=.42,wspace=.45)
    fig.legend([Line2D([],[],marker="o",ls="",color=COLORS[0],alpha=.5,markersize=np.sqrt(v)) for v in [1,10,100]],["10 GW","100 GW","1000 GW"],title="Reference capacity",loc="lower center",bbox_to_anchor=(.5,.04),ncol=3,title_fontsize=6)
    model_legend(fig,.005)
    finish(fig,BASE,"fig_s06_loss_metric_sensitivity",{"positive_loss_from_original_metric":True},
           "2050–2059 paired-path difference; shared station support; country four-model means; area proportional to reference capacity .")
if __name__=="__main__":main()
