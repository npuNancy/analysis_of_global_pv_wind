"""Fig. S09: fixed climate-126 normal-CF baseline sensitivity."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=read(BASE,"contrasts.csv")
    assert d.closure.abs().max()<1e-7
    fig,axs=plt.subplots(2,2,figsize=(7.2,8.3),gridspec_kw={"height_ratios":[1,1.8]})
    names=["GLOBAL",*CASES[:8]]
    for j,tech in enumerate(TECHS):
        ax=axs[0,j];t=d[d.tech==tech]
        for k,metric in enumerate(["delta_C_126","delta_C_585"]):
            q=t[~t.country.isin(["GLOBAL","UNASSIGNED","AMBIGUOUS"])].pivot(index=["country","model"],columns="baseline",values=metric)
            s=q.groupby("country").mean();s[q.groupby("country").count()!=4]=np.nan
            ax.scatter(s.original_common_time,s.fixed_baseline,s=12,marker=["o","^"][k],color=COLORS[k*2],alpha=.6)
        zero(ax,True);identity(ax)
        ax.set_xlabel("Original-baseline loss change\n(MWh MW⁻¹ yr⁻¹)")
        ax.set_ylabel("Fixed-baseline loss change\n(MWh MW⁻¹ yr⁻¹)")
        panel(ax,"ab"[j],tech.title()+" · country means")
        ax=axs[1,j]
        for ci,country in enumerate(names):
            for fi,(factor,color) in enumerate([("Phi_C","#3182bd"),("Phi_S","#e6ab02")]):
                for bi,base in enumerate(["original_common_time","fixed_baseline"]):
                    vals=t[(t.country==country)&(t.baseline==base)].set_index("model").reindex(MODELS)[factor].values
                    y=ci*2+fi+(bi-.5)*.3
                    if not four(vals):continue
                    ax.hlines(y,vals.min(),vals.max(),color=color,lw=.8)
                    ax.scatter(vals.mean(),y,s=18,marker=["o","D"][bi],color=color,edgecolors=".3",linewidths=.3)
            ax.axhline(ci*2+1.5,color=".92",lw=.5)
        ax.set_yticks([ci*2+.5 for ci in range(len(names))],names);ax.invert_yaxis()
        ax.axvline(0,c=".5",lw=.5);ax.set_xlabel("Contribution (MWh MW⁻¹ yr⁻¹)")
        panel(ax,"cd"[j],tech.title()+" · climate / deployment")
    fig.legend([Line2D([],[],marker=m,ls="",c=c) for m,c in [("o",COLORS[0]),("^",COLORS[2])]],
               ["Deployment SSP1-2.6 (a–b)","Deployment SSP5-8.5 (a–b)"],loc="lower center",bbox_to_anchor=(.5,.072),ncol=2)
    fig.legend([Line2D([],[],color=c,lw=2) for c in ["#3182bd","#e6ab02"]]+[Line2D([],[],marker=m,ls="",c=".3") for m in ["o","D"]],
               ["Climate contribution","Deployment contribution","Original baseline","Fixed baseline"],
               loc="lower center",bbox_to_anchor=(.5,.025),ncol=4)
    fig.text(.5,.005,"2050–2059 · climate SSP5-8.5 minus SSP1-2.6",ha="center",fontsize=6)
    fig.subplots_adjust(left=.13,right=.98,top=.95,bottom=.16,wspace=.48,hspace=.38)
    finish(fig,BASE,"fig_s09_baseline_sensitivity",{"max_decomposition_closure":float(d.closure.abs().max())},
           "2050–2059; original and fixed baselines on identical valid timestamps within each climate; intervals = four-model min–max; all nine combinations recalculated.")
if __name__=="__main__":main()
