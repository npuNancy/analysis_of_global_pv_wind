"""Fig. S01: exact three-factor Shapley attribution on common support."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=select(read(BASE,"panel_abcdef.csv"),snapshot=2050,event="all",support="common")
    err=float(d.closure.abs().max());assert err<1e-7
    fig,axs=plt.subplots(3,2,figsize=(7.2,8.5))
    factors=["psi_E","psi_CF","psi_r"];cols=["#3182bd","#e6ab02","#8c6bb1"]
    for j,tech in enumerate(TECHS):
        t=d[d.tech==tech];ax=axs[0,j]
        for k,ssp in enumerate(["ssp126","ssp585"]):
            g=t[(t.country=="GLOBAL")&(t.station_ssp==ssp)].set_index("model")
            for n,v in enumerate(factors+["delta_C"]):
                vals=g.reindex(MODELS)[v].values;x=n+(k-.5)*.34
                if four(vals):
                    ax.bar(x,vals.mean(),.3,color=(cols+[".65"])[n],hatch="" if k==0 else "///",
                           edgecolor=".3",lw=.5)
                    for mi,val in enumerate(vals):ax.scatter(x+(mi-1.5)*.035,val,marker=MARKERS[mi],s=8,c=".2",zorder=3)
        zero(ax);ax.set_xticks(range(4),["Exposure","Event CF","Severity","Total"])
        ax.set_ylabel(DELTA);panel(ax,"ab"[j],tech.title()+" · global")
        ax=axs[1,j]
        for i,country in enumerate(CASES[:8]):
            for k,ssp in enumerate(["ssp126","ssp585"]):
                q=t[(t.country==country)&(t.station_ssp==ssp)]
                y=i+(k-.5)*.32;pos=neg=0.
                for f,col in zip(factors,cols):
                    vals=q[f].values
                    if not four(vals):continue
                    v=vals.mean();left=pos if v>=0 else neg
                    ax.barh(y,v,.28,left=left,color=col,hatch="" if k==0 else "///",edgecolor=".4",lw=.3)
                    if v>=0:pos+=v
                    else:neg+=v
                if four(q.delta_C):ax.scatter(q.delta_C.mean(),y,marker="D",c="k",s=10,zorder=4)
        ax.set_yticks(range(8),CASES[:8]);ax.invert_yaxis();ax.axvline(0,c=".5",lw=.5)
        ax.set_xlabel(DELTA);panel(ax,"cd"[j],tech.title()+" · selected countries")
        ax=axs[2,j]
        for k,ssp in enumerate(["ssp126","ssp585"]):
            q=t[(t.country!="GLOBAL")&(t.station_ssp==ssp)]
            s=q.groupby("country").agg(x=("delta_E","mean"),y=("delta_C","mean"),n=("delta_C","count"))
            s=s[s.n==4];ax.scatter(s.x,s.y,marker=["o","^"][k],s=14,alpha=.65,color=COLORS[k*2],
                                 label=["Deployment SSP1-2.6","Deployment SSP5-8.5"][k])
            for c in CASES[:3]:
                if k==0 and c in s.index:ax.annotate(c,(s.loc[c,"x"],s.loc[c,"y"]),xytext={"USA":(50,-10),"CHN":(20,12),"BRA":(-30,20)}[c],textcoords="offset points",fontsize=6,arrowprops=dict(arrowstyle="-",lw=.4,color=".4"))
        zero(ax,True);ax.set_xlabel("Exposure change (h yr⁻¹)");ax.set_ylabel(DELTA)
        panel(ax,"ef"[j],tech.title()+" · country means")
    axs[0,0].legend([plt.Rectangle((0,0),1,1,fc=".85",ec=".3",hatch=h) for h in ["","///"]],
                       ["Deployment SSP1-2.6","Deployment SSP5-8.5"],fontsize=6,loc="best")
    axs[2,1].legend(fontsize=6)
    fig.subplots_adjust(left=.11,right=.98,top=.96,bottom=.08,hspace=.58,wspace=.42)
    model_legend(fig,.005)
    finish(fig,BASE,"fig_s01_three_factor_decomposition",{"max_shapley_closure":err},
           "2050–2059; climate SSP5-8.5 minus SSP1-2.6; four-model means; diamond = net change; undefined factors omitted.")
if __name__=="__main__":main()
