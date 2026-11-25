"""Plot fixed-2025 curves and six spatial loss histograms for RQ2."""
from pathlib import Path
import argparse,json,sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter, MaxNLocator
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from paper_figures.config import SSPS,SSP_COLORS
from paper_figures.common.plotting import configure,export_panel_png
OUT=HERE/'outputs';DATA=OUT/'source_data'
TECHS=('wind','solar');LABELS={'wind':'Wind','solar':'Solar PV'}
COLORS={'fixed2025':'#64258c','suitable':'#e9a48e'}

def curves(models,rows,suffix):
    fields=['exposure_days','intensity_pct','net_loss_per_mw']
    names=['Exposure','Event-period intensity','Annual net loss']
    labels=['Exposure (days yr$^{-1}$)','Event-period net loss (%)','Net loss (MWh MW$^{-1}$ yr$^{-1}$)']
    display=models.groupby(['tech','climate_ssp','time'],as_index=False)[fields].mean()
    full=len(rows)==2
    fig,axs=plt.subplots(len(rows),3,figsize=(240/25.4,(150 if full else 95)/25.4),squeeze=False)
    fig.subplots_adjust(left=.09,right=.98,bottom=.14 if full else .25,top=.84 if full else .67,wspace=.56,hspace=.67)
    for ri,r in enumerate(rows):
        tech=TECHS[r]
        for col,field in enumerate(fields):
            ax=axs[ri,col]
            for ssp,marker in zip(SSPS,['o','s','^']):
                g=display[(display.tech==tech)&(display.climate_ssp==ssp)].sort_values('time')
                ax.plot(g.time,g[field],color=SSP_COLORS[ssp],marker=marker,ms=3.5,lw=1.2)
            values=display[field].to_numpy() if field=='intensity_pct' else display[display.tech==tech][field].to_numpy()
            padding=max(np.ptp(values)*.09,.12)
            ax.set_ylim(values.min()-padding,values.max()+padding)
            ax.yaxis.set_major_locator(MaxNLocator(5))
            ax.set_xticks([2030,2040,2050],['2030s','2040s','2050s']);ax.set_xlim(2028,2052)
            ax.set_xlabel('Decade');ax.set_ylabel(labels[col]);ax.grid(axis='y',color='.9',lw=.45)
            ax.set_title(LABELS[tech]+' | '+names[col],fontsize=8.5,pad=9)
            ax.text(-.20,1.08,'abcdef'[r*3+col],transform=ax.transAxes,fontweight='bold',fontsize=10)
    fig.suptitle('Fixed 2025 sites | Exposure, event-period intensity and annual net loss',fontsize=10,y=.98)
    fig.text(.53,.925 if full else .86,'2025 locations and capacities held fixed; four-model means',ha='center',fontsize=7.4,color='.35')
    fig.text(.53,.89 if full else .80,'Intensity denominator: normal generation during valid event hours',ha='center',fontsize=7.1,color='.35')
    handles=[Line2D([],[],color=SSP_COLORS[s],marker=m,ms=3.5,label=s.upper()) for s,m in zip(SSPS,['o','s','^'])]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.53,.025),ncol=3,fontsize=8)
    return export_panel_png(fig,OUT/('rq2_fixed2025'+suffix+'.png'))

def histograms(bins,summary,panels,suffix):
    full=len(panels)==6; row=len(panels)==3
    nr=2 if full else 1;nc=3 if (full or row) else 1
    fig,axs=plt.subplots(nr,nc,figsize=((240 if nc==3 else 105)/25.4,(150 if full else 95)/25.4),squeeze=False)
    fig.subplots_adjust(left=.085 if nc==3 else .19,right=.98,bottom=.16 if full else .26,top=.82 if full else (.68 if row else .72),wspace=.26,hspace=.48)
    for ax,idx in zip(axs.ravel(),panels):
        tech=TECHS[idx//3];ssp=SSPS[idx%3]
        ymax=bins[bins.tech==tech].relative_frequency.max()*1.18
        for domain in ['suitable','fixed2025']:
            group=bins[(bins.tech==tech)&(bins.climate_ssp==ssp)&(bins.domain==domain)].sort_values('left')
            edges=np.r_[group.left,group.right.iloc[-1]]
            ax.stairs(group.relative_frequency,edges,fill=True,color=COLORS[domain],alpha=.63 if domain=='suitable' else .62,lw=.7)
            ax.stairs(group.relative_frequency,edges,color=COLORS[domain],lw=.75)
        ax.set_xlim(edges[0],edges[-1]);ax.set_ylim(0,ymax)
        ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
        ax.set_yticks([v for v in MaxNLocator(4).tick_values(0,ymax) if 0<=v<=ymax])
        ax.set_xticks([v for v in MaxNLocator(5).tick_values(edges[0],edges[-1]) if edges[0]<=v<=edges[-1]])
        ax.set_xlabel('Net loss (MWh MW$^{-1}$ yr$^{-1}$)')
        if idx%3==0 or nc==1:ax.set_ylabel('Relative frequency')
        ax.set_title(LABELS[tech]+' | '+ssp.upper(),fontsize=9,pad=8)
        ax.text(-.17 if nc==1 else -.12,1.08,'abcdef'[idx],transform=ax.transAxes,fontsize=10,fontweight='bold')
        ax.grid(axis='y',color='.91',lw=.4);ax.set_axisbelow(True)
    fig.suptitle('2050–2059 | Spatial distribution of annual net loss' if nc==3 else '2050–2059 | Annual net loss',fontsize=10,y=.98)
    subtitle='Each group sums to 100%; one value per grid after decadal and four-model averaging'
    if nc==1:subtitle='Each group sums to 100%\nOne decadal four-model mean per grid'
    fig.text(.53,.925 if full else .86,subtitle,ha='center',fontsize=7.2,color='.35')
    if nc==3:
        fig.text(.53,.89 if full else .80,'Shared bins and axes across SSPs within each technology; negative values retained',ha='center',fontsize=7,color='.35')
    handles=[Patch(facecolor=COLORS[d],alpha=.7,label=label) for d,label in [('fixed2025','2025 installed grids'),('suitable','Suitable grids')]]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.53,.035),ncol=2 if nc==3 else 1,fontsize=8 if nc==3 else 7.5)
    return export_panel_png(fig,OUT/('rq2_loss_histograms'+suffix+'.png'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--only-fixed',action='store_true');args=parser.parse_args()
    configure();plt.rcParams.update({'font.size':8,'axes.labelsize':8})
    fixed=pd.read_csv(DATA/'fixed2025_decadal_models.csv')
    products=[curves(fixed,[0,1],''),curves(fixed,[0],'_abc'),curves(fixed,[1],'_def')]
    if not args.only_fixed:
        bins=pd.read_csv(DATA/'histogram_bins.csv');summary=pd.read_csv(DATA/'distribution_summary.csv')
        np.testing.assert_allclose(bins.groupby(['tech','climate_ssp','domain']).relative_frequency.sum(),1,atol=1e-12)
        products.extend([histograms(bins,summary,list(range(6)),''),histograms(bins,summary,[0,1,2],'_abc'),histograms(bins,summary,[3,4,5],'_def')])
        for idx in range(6):products.append(histograms(bins,summary,[idx],'_'+'abcdef'[idx]))
    (OUT/'figure_validation.json').write_text(json.dumps(dict(status='NUMERIC_AND_EXPORT_PASSED',visual_review='PENDING',products=products,backend='Python/matplotlib',histogram='relative frequency per bin, not density; each group sums to one'),indent=2)+'\n')
    print('Rendered',len(products),'PNGs',flush=True)
if __name__=='__main__':main()
