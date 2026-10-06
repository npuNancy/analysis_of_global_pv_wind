"""Fig. S04: paginated complete-country counterfactual heat maps."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=select(read(BASE,"panel_abcdefgh.csv"),event="all",support="common",metric="R")
    d=d[~d.country.isin(["GLOBAL","UNASSIGNED","AMBIGUOUS"])]
    cap=pd.read_csv(ROOT/"paper_figures/prepare/outputs/loss_summary/window.csv.gz")
    cap=select(cap,climate_ssp="ssp126",station_ssp="ssp126",snapshot=2050,event="all",support="common")
    order=cap.groupby(["country","tech"]).capacity_mw.mean().groupby("country").sum().sort_values(ascending=False).index.tolist()
    catalogue=pd.read_csv(ROOT/"paper_figures/prepare/outputs/catalogues/capacity_by_country.csv")
    countries=sorted(set(catalogue.country)-{"GLOBAL","UNASSIGNED","AMBIGUOUS"});order=[c for c in order if c in countries]+[c for c in countries if c not in order]
    assert len(order)==len(countries)
    metric_names={"D":"Paired-path change","Phi_C":"Climate contribution","Phi_S":"Deployment contribution","J":"Interaction"}
    pages=[]
    for mi,(metric,title) in enumerate(metric_names.items()):
        s=summary(d,["tech","country","snapshot"],metric)
        signs=d.groupby(["tech","country","snapshot"])[metric].agg(lambda v: (np.asarray(v)>0).sum())
        lim=max(float(s["mean"].abs().max()),1e-8)
        for page,start in enumerate(range(0,len(order),30),1):
            cs=order[start:start+30];fig,axs=plt.subplots(1,2,figsize=(7.2,7.2))
            for j,tech in enumerate(TECHS):
                ax=axs[j];q=s[s.tech==tech]
                arr=q.pivot(index="country",columns="snapshot",values="mean").reindex(index=cs,columns=[2030,2040,2050])
                cmap=plt.get_cmap("RdBu_r").copy();cmap.set_bad("#dddddd")
                im=ax.imshow(arr.values,aspect="auto",cmap=cmap,vmin=-lim,vmax=lim)
                for y,c in enumerate(cs):
                    for x,year in enumerate([2030,2040,2050]):
                        n=signs.get((tech,c,year),np.nan)
                        if np.isfinite(arr.iloc[y,x]) and n not in (0,4):
                            ax.text(x,y,"·",ha="center",va="center",fontsize=9,color="k")
                ax.set_xticks(range(3),["2030s","2040s","2050s"]);ax.set_yticks(range(len(cs)),cs)
                panel(ax,chr(97+2*mi+j),tech.title()+" · "+title)
                ax.texts[-1].set_position((-.14,1.025))
                cb=fig.colorbar(im,ax=ax,orientation="horizontal",pad=.07,fraction=.035)
                cb.set_label(DELTA)
            fig.suptitle(f"Fig. S04 · {metric} · countries {start+1}–{start+len(cs)} of {len(order)}",fontsize=8,y=.985)
            fig.text(.5,.025,"· Mixed model directions    Grey: fewer than four valid models",ha="center",fontsize=6)
            fig.subplots_adjust(left=.12,right=.97,top=.92,bottom=.12,wspace=.4)
            name=f"fig_s04_country_counterfactuals_{metric}_page{page:02d}";pages.append(name+".png")
            finish(fig,BASE,name,{"countries_on_page":len(cs),"country_total":len(order),"symmetric_limit":lim},
                   "All countries; same order and per-metric scale on every page; four-model mean; all windows.")
    (BASE/"outputs/page_manifest.json").write_text(json.dumps({"countries":order,"pages":pages},indent=2)+"\n")
if __name__=="__main__":main()
