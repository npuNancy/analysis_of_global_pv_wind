"""Fig. S10: coverage, common support, and threshold robustness."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    a=select(read(BASE,"panel_ab.csv"),snapshot=2050,support="original")
    c=select(read(BASE,"panel_cd.csv"),snapshot=2050,event="all",metric="R")
    e=read(BASE,"panel_ef.csv")
    fig,axs=plt.subplots(3,2,figsize=(7.2,9.4))
    combos=[(cs,ss) for cs in SSPS for ss in SSPS]
    for j,tech in enumerate(TECHS):
        ax=axs[0,j]
        q=a[a.tech==tech].groupby(["country","climate_ssp","station_ssp"]).coverage_pct.min()
        arr=np.array([[q.get((country,cs,ss),np.nan) for cs,ss in combos] for country in CASES])
        cmap=plt.get_cmap("viridis").copy();cmap.set_bad(".8")
        im=ax.imshow(arr,aspect="auto",vmin=0,vmax=100,cmap=cmap)
        ax.set_xticks(range(9),[f"{cs[-3:]}\n{ss[-3:]}" for cs,ss in combos],fontsize=6)
        ax.set_xlabel("Climate SSP / deployment SSP");ax.set_yticks(range(len(CASES)),CASES)
        panel(ax,"ab"[j],tech.title()+" · minimum coverage")
        cb=fig.colorbar(im,ax=ax,fraction=.035,pad=.02);cb.set_label("Capacity coverage (%)",fontsize=6)
        ax=axs[1,j]
        t=c[(c.tech==tech)&~c.country.isin(["GLOBAL","UNASSIGNED","AMBIGUOUS"])]
        wide=t.pivot(index=["country","model"],columns="support",values="D")
        s=wide.groupby("country").mean();s[wide.groupby("country").count()!=4]=np.nan
        ax.scatter(s.original,s.common,s=12,c=COLORS[0],alpha=.55)
        for country in CASES[:4]:
            if country in s.index:ax.annotate(country,(s.loc[country,"original"],s.loc[country,"common"]),xytext={"USA":(-25,15),"CHN":(20,20),"BRA":(20,-22),"RUS":(-25,-25)}[country],textcoords="offset points",fontsize=6,arrowprops=dict(arrowstyle="-",lw=.4,color=".4"))
        zero(ax,True);identity(ax);ax.set_xlabel("Original-support "+DELTA.replace("Loss","loss"));ax.set_ylabel("Common-support "+DELTA.replace("Loss","loss"))
        panel(ax,"cd"[j],tech.title()+" · support sensitivity")
        ax=axs[2,j];q=e[e.tech==tech]
        for s,col in zip(SSPS,COLORS):
            z=q[q.reference_ssp==s].sort_values("quantile")
            ax.plot(z["quantile"],z.capacity_pct,"o-",color=col,lw=1,ms=3,label=f"SSP{s[-3:]} capacity")
        z=q[q.reference_ssp=="ssp126"].sort_values("quantile")
        ax.plot(z["quantile"],z.country_pct,"s--",c=".2",lw=1,ms=3,label="Country share")
        ax.set_xticks([.5,.75,.9],["50th","75th","90th"]);ax.set_ylim(0,100)
        ax.set_xlabel("Early-reference loss quantile");ax.set_ylabel("High-loss share (%)")
        panel(ax,"ef"[j],tech.title()+" · fixed country population")
    axs[2,1].legend(fontsize=6)
    fig.subplots_adjust(left=.13,right=.97,top=.96,bottom=.06,wspace=.5,hspace=.56)
    finish(fig,BASE,"fig_s10_coverage_weights_thresholds",{"coverage_rows":int(len(a))},
           "2050–2059 coverage minimum across models and years; selected-country coverage, all-country support comparison; SSP labels in e–f denote reference capacity weights.")
if __name__=="__main__":main()
