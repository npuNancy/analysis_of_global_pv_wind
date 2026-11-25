"""Overlay fixed-2025 and suitable-grid exposure, intensity and loss curves."""
from pathlib import Path
import argparse
import hashlib,json,sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from paper_figures.config import MODELS,SSPS,SSP_COLORS
from paper_figures.common.plotting import configure,export_panel_png
OUT=HERE/'outputs';DATA=OUT/'source_data'
TECHS=('wind','solar');NAMES={'wind':'Wind','solar':'Solar PV'}
FIELDS=('exposure_days','intensity_pct','net_loss_per_mw')
TITLES=('Exposure','Event-period intensity','Annual net loss')
YLABELS=('Exposure (days yr$^{-1}$)','Event-period net loss (%)','Net loss (MWh MW$^{-1}$ yr$^{-1}$)')
Y_SEGMENTS={
    'a': [(29.5,32.5),(35,39.5)],
    'b': [(50,57),(64,74)],
    'c': [(79,85),(115,129)],
    'd': [(30.5,34),(42,46.5)],
    'e': [(53.5,58)],
}
Y_TICKS={
    'a': [[30,31,32],[35,37,39]],
    'b': [[51,54,57],[64,68,72]],
    'c': [[80,82,84],[115,120,125]],
    'd': [[31,32,33,34],[42,44,46]],
    'e': [[54,55,56,57,58]],
}

def render(display, rows, suffix, output_dir, y_axes, legend_rows):
    full=len(rows)==2
    fig=plt.figure(figsize=(240/25.4,(160 if full else 100)/25.4))
    grid=fig.add_gridspec(len(rows),3,left=.09,right=.98,bottom=.19 if full else .29,
                          top=.83 if full else .71,wspace=.53,hspace=.67)
    checks=[]
    for ri,row in enumerate(rows):
        tech=TECHS[row]
        for col,field in enumerate(FIELDS):
            letter='abcdef'[row*3+col]
            values=display[display.tech==tech][field].to_numpy()
            pad=max(np.ptp(values)*.08,.12)
            axis = y_axes.get(letter, {})
            ranges = axis.get('segments', Y_SEGMENTS.get(letter))
            if ranges is None:
                ranges = [(float(values.min()-pad), float(values.max()+pad))]
            ticks = axis.get('ticks', Y_TICKS.get(letter))
            if ticks is None:
                ticks = [[float(x) for x in MaxNLocator(5).tick_values(lo, hi)
                          if lo <= x <= hi] for lo, hi in ranges]
            assert len(ticks) == len(ranges)
            assert all(lo <= tick <= hi for (lo, hi), group in zip(ranges, ticks) for tick in group)
            spec=grid[ri,col];box=spec.get_position(fig)
            if len(ranges)==2:
                inner=spec.subgridspec(2,1,height_ratios=[hi-lo for lo,hi in reversed(ranges)],hspace=.13)
                axes=[fig.add_subplot(inner[i]) for i in range(2)]
            else:
                axes=[fig.add_subplot(spec)]
            for ax,(low,high),yticks in zip(axes,reversed(ranges),reversed(ticks)):
                for ssp,marker in zip(SSPS,('o','s','^')):
                    for domain,style in [('fixed2025','-'),('suitable','--')]:
                        g=display[(display.tech==tech)&(display.climate_ssp==ssp)&(display.domain==domain)].sort_values('time')
                        assert g.time.tolist()==[2030,2040,2050]
                        y=g[field].to_numpy()
                        assert any(np.all((y>lo)&(y<hi)) for lo,hi in ranges), (letter,ssp,domain)
                        ax.plot(g.time,y,color=SSP_COLORS[ssp],linestyle=style,marker=marker,
                                markerfacecolor=SSP_COLORS[ssp] if domain=='fixed2025' else 'white',
                                markeredgewidth=.9,ms=3.6,lw=1.25)
                assert len(ax.lines)==6
                for j,ssp in enumerate(SSPS):
                    assert ax.lines[j*2].get_color()==ax.lines[j*2+1].get_color()==SSP_COLORS[ssp]
                    assert ax.lines[j*2].get_linestyle()=='-' and ax.lines[j*2+1].get_linestyle()=='--'
                ax.set_ylim(low,high);ax.set_yticks(yticks)
                ax.set_xticks([2030,2040,2050],['2030s','2040s','2050s']);ax.set_xlim(2028,2052)
                ax.grid(axis='y',color='.9',lw=.45)
            if len(axes)==2:
                upper,lower=axes
                upper.spines['bottom'].set_visible(False)
                upper.tick_params(axis='x',which='both',bottom=False,labelbottom=False)
                for ax,edge in [(upper,0),(lower,1)]:
                    ax.plot([0],[edge],marker=[(-1,-.6),(1,.6)],markersize=6,
                            transform=ax.transAxes,linestyle='none',clip_on=False,
                            color='.2',markeredgewidth=.8)
                scales=[ax.get_position().height/(hi-lo) for ax,(lo,hi) in zip(axes,reversed(ranges))]
                np.testing.assert_allclose(scales,scales[0],rtol=1e-12)
            axes[-1].set_xlabel('Decade')
            fig.text(box.x0-.22*box.width,box.y0+.5*box.height,YLABELS[col],
                     ha='center',va='center',rotation=90,fontsize=8)
            axes[0].set_title(NAMES[tech]+' | '+TITLES[col],fontsize=8.5,pad=9)
            fig.text(box.x0-.19*box.width,box.y1+.08*box.height,letter,fontsize=10,fontweight='bold')
            checks.append(dict(panel=letter,technology=tech,metric=field,lines=6,
                               y_segments=ranges,y_ticks=ticks,
                               omitted_interval=[ranges[0][1],ranges[1][0]] if len(ranges)==2 else None,
                               complete_curves_visible=True,equal_segment_scale=True))
    fig.suptitle('Fixed 2025 sites and suitable grids | Exposure, intensity and net loss',fontsize=10,y=.98)
    fig.text(.53,.925 if full else .875,'Fixed 2025: capacity weights; suitable grids: area weights; four-model means',ha='center',fontsize=7.4,color='.35')
    omitted='; '.join(f"{p['panel']} {p['omitted_interval'][0]:g}–{p['omitted_interval'][1]:g}"
                      for p in checks if p['omitted_interval'])
    fig.text(.53,.885 if full else .795,'Y-axis breaks: '+omitted+' (panel units)',ha='center',fontsize=6.8,color='.35')
    ssp_handles=[Line2D([],[],color=SSP_COLORS[s],marker=m,lw=1.25,ms=3.6,label=s.upper()) for s,m in zip(SSPS,('o','s','^'))]
    domain_handles=[Line2D([],[],color='.2',linestyle=style,lw=1.25,label=label) for style,label in [('-','Fixed 2025 sites'),('--','Suitable grids')]]
    if legend_rows == 1:
        fig.legend(handles=ssp_handles + domain_handles, loc='lower center',
                   bbox_to_anchor=(.53, .065 if full else .085), ncol=5,
                   fontsize=8, handlelength=3)
    else:
        fig.legend(handles=ssp_handles, loc='lower center',
                   bbox_to_anchor=(.53, .085 if full else .105), ncol=3, fontsize=8)
        fig.legend(handles=domain_handles, loc='lower center',
                   bbox_to_anchor=(.53, .035), ncol=2, fontsize=8, handlelength=3)
    return export_panel_png(fig,output_dir/('rq2_domain_comparison'+suffix+'.png')),checks

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path,
                        help='Read the RQ bundle contract and source data, then export to its images directory.')
    bundle = parser.parse_args().bundle
    data_dir, output_dir, report_dir = DATA, OUT, OUT
    y_axes = {}
    legend_rows = 2
    if bundle is not None:
        data_dir, output_dir, report_dir = bundle/'source_data', bundle/'images', bundle
        contract = json.loads((bundle/'comparison_figure_contract.json').read_text())
        legend_rows = contract.get('legend_rows', legend_rows)
        y_axes = {panel: axis for panel, axis in contract['y_axes'].items()
                  if isinstance(axis['segments'], list)}

    path=data_dir/'curve_models.csv';models=pd.read_csv(path)
    keys=['tech','climate_ssp','time','domain']
    assert len(models)==144 and not models.duplicated(['model',*keys]).any()
    assert set(models.model)==set(MODELS) and set(models.climate_ssp)==set(SSPS)
    assert models.groupby(keys).size().eq(4).all()
    assert models[models.domain=='fixed2025'].weighting.eq('capacity2025').all()
    assert models[models.domain=='suitable'].weighting.eq('area').all()
    assert np.isfinite(models[list(FIELDS)]).all().all()
    display=models.groupby(keys,as_index=False)[list(FIELDS)].mean()
    reference=pd.read_csv(data_dir/'curve_display.csv')
    check=display.merge(reference,on=keys,validate='one_to_one')
    for field in FIELDS:np.testing.assert_allclose(check[field],check[field+'_mean'],rtol=1e-12,atol=1e-12)
    configure();plt.rcParams.update({'font.size':8,'axes.labelsize':8})
    products=[];panels=[]
    for rows,suffix in [([0,1],''),([0],'_abc'),([1],'_def')]:
        product,checks=render(display, rows, suffix, output_dir, y_axes, legend_rows)
        products.append(product)
        if not suffix:panels=checks
    metadata=dict(status='NUMERIC_AND_EXPORT_PASSED',visual_review='PENDING',panels=panels,products=products,
                  legend_rows=legend_rows,
                  source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  aggregation='four equally weighted model metrics; matches existing curve_display.csv',
                  line_styles={'fixed2025':'solid','suitable':'dashed'})
    (report_dir/'comparison_figure_validation.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print('Rendered six panels with six lines each, plus two row groups.',flush=True)
if __name__=='__main__':main()
