"""Fig. S08: capacity-weighted event starts and complete-event durations."""
from pathlib import Path
from paper_figures.supplementary.plot_support import *
BASE=Path(__file__).resolve().parent
def main():
    d=select(read(BASE,"panel_abcd.csv"),country="GLOBAL",snapshot=2050)
    d=d[d.climate_ssp==d.station_ssp]
    assert (d.frequency_per_year.dropna()>=0).all()
    fig,axs=plt.subplots(2,2,figsize=(7.2,7.5))
    audit=d.assign(censored_fraction=d.capacity_censored_events/(d.capacity_complete_events+d.capacity_censored_events))
    audit.to_csv(BASE/"outputs/source_data/plotted_frequency_duration.csv",index=False)
    for j,tech in enumerate(TECHS):
        events=event_order(tech)
        for i,metric in enumerate(["frequency_per_year","duration_hours"]):
            ax=axs[i,j]
            for n,e in enumerate(events):
                for k,(ssp,color) in enumerate(zip(SSPS,COLORS)):
                    q=d[(d.tech==tech)&(d.event==e)&(d.climate_ssp==ssp)].set_index("model").reindex(MODELS)
                    vals=q[metric].values;y=n+(k-1)*.23
                    if not four(vals):continue
                    ax.vlines(y,vals.min(),vals.max(),color=color,lw=.8)
                    for mi,v in enumerate(vals):ax.scatter(y,v,marker=MARKERS[mi],s=9,color=color)
                    ax.scatter(y,vals.mean(),marker="D",s=22,facecolors="white",edgecolors=color,zorder=4)
            ax.set_xticks(range(len(events)),[NAMES[e] for e in events],rotation=35,ha="right",fontsize=6)
            ax.set_ylabel("Event starts (yr⁻¹)" if i==0 else "Complete-event duration (h event⁻¹)")
            panel(ax,"abcd"[2*i+j],tech.title()+" · 2050–2059")
    fig.subplots_adjust(left=.11,right=.98,top=.94,bottom=.14,wspace=.35,hspace=.68)
    scenario_legend(fig,.042);model_legend(fig,.005)
    finish(fig,BASE,"fig_s08_event_frequency_duration",{"nonnegative_frequency":True},
           "Capacity-weighted starts and fully observed event duration; boundary-censored events excluded from duration; censor fractions in plotted source.")
if __name__=="__main__":main()
