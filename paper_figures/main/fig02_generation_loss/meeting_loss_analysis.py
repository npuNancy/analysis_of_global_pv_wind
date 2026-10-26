"""Meeting follow-up: capacity, total loss, mechanisms and deployment candidates."""
from pathlib import Path
from itertools import product
import json
import hashlib
import os
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs' / 'meeting_loss'
DATA = OUT / 'source_data'
SSPS = ['ssp126', 'ssp245', 'ssp585']
TECHS = ['wind', 'solar']
COLORS = {'ssp126': '#1d3b6f', 'ssp245': '#b77c19', 'ssp585': '#9e1b1b'}
METRICS = ['R', 'E_loss', 'cf_event', 'r_event']
TOL = 1e-9


def save(frame, name):
    frame.to_csv(DATA / f'{name}.csv', index=False)


def summarize(frame, keys, metrics):
    rows = []
    for key, group in frame.groupby(keys, sort=True):
        base = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        for metric in metrics:
            x = group[metric].dropna().to_numpy(float)
            mean = float(x.mean()) if len(x) else np.nan
            rows.append(dict(base, metric=metric, mean=mean,
                             minimum=float(x.min()) if len(x) else np.nan,
                             maximum=float(x.max()) if len(x) else np.nan,
                             n_models=len(x), positive_models=int((x > TOL).sum()),
                             negative_models=int((x < -TOL).sum()),
                             sign_agreement=int((np.sign(x) == np.sign(mean)).sum())))
    return pd.DataFrame(rows)


def write_followup_summary(levels, countries, country_models):
    """Small follow-up metrics derived exclusively from existing summary tables."""
    rows = []
    solar = levels[levels.tech.eq('solar') & levels.climate_ssp.eq(levels.station_ssp)]
    event_rows = solar[solar.snapshot.eq(2050) & solar.climate_ssp.eq('ssp126')]
    for metric in ['E_loss', 'R', 'cf_event']:
        values = event_rows.pivot(index='model', columns='event', values=metric)
        ratios = values.low_resource / values.high_humidity
        assert len(ratios) == 4 and np.isfinite(ratios).all()
        support = ratios.lt(1).sum() if metric == 'E_loss' else ratios.gt(1).sum()
        rows.append(dict(topic='solar_event_comparison', tech='solar', scenario='ssp126',
                         snapshot=2050, metric=metric+'_low_resource_over_high_humidity',
                         unit='ratio', statistic='mean_of_model_ratios', value=ratios.mean(),
                         model_min=ratios.min(), model_max=ratios.max(), n_models=4,
                         supporting_models=int(support), support_direction='below_one' if metric=='E_loss' else 'above_one'))
    for ssp in SSPS:
        selected = solar[solar.climate_ssp.eq(ssp) & solar.event.eq('all')]
        for metric in ['R', 'net_loss_TWh']:
            values = selected.pivot(index='model', columns='snapshot', values=metric)
            model_change = 100*(values[2050]/values[2030]-1)
            value = 100*(values[2050].mean()/values[2030].mean()-1)
            assert len(model_change) == 4 and np.isfinite(model_change).all()
            rows.append(dict(topic='solar_time_change', tech='solar', scenario=ssp,
                             first_snapshot=2030, last_snapshot=2050, metric=metric+'_change_pct',
                             unit='%', statistic='ratio_of_ensemble_means_minus_one', value=value,
                             model_min=model_change.min(), model_max=model_change.max(), n_models=4,
                             supporting_models=int((np.sign(model_change)==np.sign(value)).sum()),
                             support_direction='negative' if value<0 else 'positive',
                             baseline_value=values[2030].mean(), target_value=values[2050].mean(),
                             baseline_target_unit='MWh MW-1 yr-1' if metric=='R' else 'TWh yr-1'))
    for tech in TECHS:
        base = countries[countries.tech.eq(tech) & countries.mean_candidate & countries.joint_support.eq(4)]
        target = base[base.mean_equal_generation & base.joint_equal_generation_support.eq(4)]
        reference_capacity = base.reference_capacity_mw.sum()/1e6
        target_capacity = target.reference_capacity_mw.sum()/1e6
        rows.append(dict(topic='normal_generation_constraint', tech=tech, scenario='climate_ssp126',
                         snapshot=2050, metric='retained_reference_capacity_pct', unit='%',
                         statistic='ratio_of_reference_capacities', value=100*target_capacity/reference_capacity,
                         baseline_value=reference_capacity, target_value=target_capacity,
                         baseline_target_unit='TW', n_reference_countries=len(base), n_target_countries=len(target),
                         selection_required_models=4))
        selected = country_models[country_models.tech.eq(tech) & country_models.country.isin(target.country)]
        assert selected.groupby('model').country.nunique().eq(len(target)).all()
        assert selected.candidate_equal_generation.all()
        reductions = selected.groupby('model').equal_normal_generation_loss_reduction_TWh.sum()
        assert len(reductions) == 4 and np.isfinite(reductions).all() and reductions.gt(0).all()
        rows.append(dict(topic='normal_generation_constraint', tech=tech, scenario='climate_ssp126',
                         snapshot=2050, metric='equal_normal_generation_net_loss_reduction', unit='TWh yr-1',
                         statistic='mean_of_model_country_sums', value=reductions.mean(),
                         model_min=reductions.min(), model_max=reductions.max(), n_models=4,
                         supporting_models=int(reductions.gt(0).sum()), support_direction='positive',
                         n_reference_countries=len(base), n_target_countries=len(target),
                         selection_required_models=4))
    summary = pd.DataFrame(rows)
    save(summary, 'followup_summary')
    report = OUT / 'analysis.txt'
    marker = '\n7. 追加核验：事件强度、时间变化与正常发电目标约束。\n'
    text = report.read_text() if report.exists() else ''
    text = text.split(marker)[0].removesuffix('希望对你有帮助，小凯！\n').rstrip()
    text += marker + '新增数值见source_data/followup_summary.csv。事件比值先逐模式计算；时间百分比采用四模式均值的比值，model_min/model_max另列逐模式百分比范围，两者不是同一汇总运算。候选容量均采用SSP126/2050参考容量。\n'
    event = summary[summary.topic.eq('solar_event_comparison')].set_index('metric')
    e, r = event.loc['E_loss_low_resource_over_high_humidity'], event.loc['R_low_resource_over_high_humidity']
    text += f'2050s SSP126光伏：低光资源暴露为高湿的{100*e.model_min:.1f}%–{100*e.model_max:.1f}%，单位装机净损失却为高湿的{r.model_min:.2f}–{r.model_max:.2f}倍，逐模式均支持更少暴露、更高损失。\n'
    for ssp in ['ssp126','ssp245']:
        change=summary[summary.topic.eq('solar_time_change') & summary.scenario.eq(ssp)].set_index('metric')
        text += f'光伏{ssp.upper()}，2030s到2050s：单位装机净损失变化{change.loc["R_change_pct","value"]:+.3f}%，总净损失变化{change.loc["net_loss_TWh_change_pct","value"]:+.2f}%，两个变化方向均4/4支持。\n'
    for tech in TECHS:
        selected=summary[summary.tech.eq(tech) & summary.topic.eq('normal_generation_constraint')].set_index('metric')
        c=selected.loc['retained_reference_capacity_pct']; q=selected.loc['equal_normal_generation_net_loss_reduction']
        name='风电' if tech=='wind' else '光伏'
        text += f'{name}：同正常发电目标Q且总净损失下降的4/4候选，从{int(c.n_reference_countries)}国缩至{int(c.n_target_countries)}国，参考容量{c.baseline_value:.6f}→{c.target_value:.6f}TW，保留原候选容量的{c.value:.2f}%。这些国家的正常Q算术反事实合计年净损失减少{q.value:.6f}TWh，四模式范围{q.model_min:.6f}–{q.model_max:.6f}TWh，4/4为正。\n'
    text += '上述Q固定为各国原布局的正常年发电量，目标采用SSP585国内布局并按H0原/H0目标同比例缩放容量；气候固定126。该量没有土地、电网和成本约束，不保证实际全年发电或供电，不能称已经实现的优化收益。希望对你有帮助，小凯！\n'
    report.write_text(text)
    return summary


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('MPLBACKEND', 'Agg')
    os.environ.setdefault('MPLCONFIGDIR', str(OUT / '.mplconfig'))
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    mpl.rcParams.update({'font.family': 'sans-serif', 'font.size': 8,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.linewidth': .7, 'legend.frameon': False,
                         'savefig.dpi': 600})
    input_paths = {
        'annual': HERE / 'outputs/source_data/panel_ab.csv',
        'global_diagonal': HERE / 'outputs/source_data/global_window_models.csv',
        'window': ROOT / 'paper_figures/prepare/outputs/loss_summary/window.csv.gz',
        'capacity': ROOT / 'paper_figures/prepare/outputs/catalogues/capacity_by_country.csv',
        'countries': ROOT / 'paper_figures/prepare/outputs/catalogues/countries.csv',
        'waterfall': HERE / 'outputs/source_data/fig02_climate_layout_waterfall_2030s_2040s_2050s_models.csv',
    }
    annual = pd.read_csv(input_paths['annual'])
    diagonal = pd.read_csv(input_paths['global_diagonal'])
    catalog = pd.read_csv(input_paths['capacity'])
    names = pd.read_csv(input_paths['countries'])
    pieces = []
    for chunk in pd.read_csv(input_paths['window'], chunksize=50000):
        keep = chunk.support.eq('common') & (chunk.country.eq('GLOBAL') |
                 (chunk.snapshot.eq(2050) & chunk.event.eq('all')))
        pieces.append(chunk.loc[keep])
    window = pd.concat(pieces, ignore_index=True)
    global_all = window[window.country.eq('GLOBAL')].copy()
    save(global_all, 'global_all_combinations')
    annual['capacity_TW'] = annual.capacity_mw / 1e6
    annual['net_loss_TWh'] = annual.net_mwh / 1e6
    annual['coverage_pct'] = 100 * annual.capacity_mw / annual.available_capacity_mw
    annual['period'] = annual.snapshot.astype(str) + 's'
    save(annual, 'annual_total_loss_models')
    capacity = catalog.groupby(['tech', 'station_ssp', 'snapshot'], as_index=False).capacity_mw.sum()
    capacity['capacity_TW'] = capacity.capacity_mw / 1e6
    capacity['source'] = capacity.station_ssp.map({'ssp126': 'stations_SSP1-2.6.csv',
                                                   'ssp245': 'stations_SSP2-4.5.csv',
                                                   'ssp585': 'stations_SSP5-6.0.csv'})
    save(capacity, 'capacity_snapshots')
    annual_display = summarize(annual, ['tech', 'climate_ssp', 'snapshot', 'year'], ['net_loss_TWh', 'R', 'coverage_pct'])
    save(annual_display, 'annual_total_loss_display')
    levels = diagonal.copy()
    levels['net_loss_TWh'] = levels.net_mwh / 1e6
    levels['capacity_TW'] = levels.capacity_mw / 1e6
    save(summarize(levels, ['tech', 'climate_ssp', 'snapshot', 'event'],
                   METRICS + ['net_loss_TWh', 'capacity_TW']), 'decade_levels')
    # Distinguish diagonal path contrasts from changes with fixed deployment.
    rows = []
    for (model, tech, snapshot, event), group in global_all.groupby(['model','tech','snapshot','event']):
        g = group.set_index(['climate_ssp','station_ssp'])
        for contrast, ak, bk in [
            ('paired_585_minus_126', ('ssp126','ssp126'), ('ssp585','ssp585')),
            ('climate_at_station126', ('ssp126','ssp126'), ('ssp585','ssp126')),
            ('climate_at_station585', ('ssp126','ssp585'), ('ssp585','ssp585')),
            ('deployment_at_climate126', ('ssp126','ssp126'), ('ssp126','ssp585')),
            ('deployment_at_climate585', ('ssp585','ssp126'), ('ssp585','ssp585'))]:
            a, b = g.loc[ak], g.loc[bk]
            row = dict(model=model, tech=tech, snapshot=snapshot, event=event, contrast=contrast)
            for metric in METRICS:
                row[metric] = b[metric] - a[metric]
                row[f'{metric}_baseline'] = a[metric]
                row[f'{metric}_target'] = b[metric]
            row['loss_per_event_hour'] = b.R / b.E_loss - a.R / a.E_loss if min(a.E_loss,b.E_loss)>0 else np.nan
            rows.append(row)
    contrasts = pd.DataFrame(rows)
    save(contrasts, 'mechanism_contrasts_models')
    contrast_display = summarize(contrasts, ['tech','snapshot','event','contrast'], METRICS + ['loss_per_event_hour'])
    save(contrast_display, 'mechanism_contrasts_display')
    # Exact scale/intensity time decomposition; intensity includes climate AND redistribution.
    rows = []
    for (model, tech, ssp), group in levels[levels.event.eq('all')].groupby(['model','tech','climate_ssp']):
        g = group.set_index('snapshot')
        for first, last in [(2030,2040),(2040,2050),(2030,2050)]:
            a,b=g.loc[first],g.loc[last]
            scale=(b.capacity_mw-a.capacity_mw)*(a.R+b.R)/2/1e6
            intensity=(a.capacity_mw+b.capacity_mw)/2*(b.R-a.R)/1e6
            delta=(b.net_mwh-a.net_mwh)/1e6
            rows.append(dict(model=model,tech=tech,ssp=ssp,first=first,last=last,
                             scale_TWh=scale,intensity_TWh=intensity,delta_TWh=delta,
                             closure_TWh=scale+intensity-delta))
    temporal=pd.DataFrame(rows)
    save(temporal,'same_ssp_time_scale_intensity_models')
    save(summarize(temporal,['tech','ssp','first','last'],['scale_TWh','intensity_TWh','delta_TWh']),
         'same_ssp_time_scale_intensity_display')
    # The reference country universe is all named countries with SSP126 2050 capacity.
    ref=catalog[catalog.snapshot.eq(2050)&catalog.station_ssp.eq('ssp126')&catalog.capacity_mw.gt(0)].copy()
    ref=ref[ref.country.isin(names.country)].merge(names,on='country',validate='many_to_one')
    refs=ref.set_index(['tech','country'])
    country=window[window.country.isin(names.country)&window.snapshot.eq(2050)&window.event.eq('all')]
    crows=[]
    for (model,tech,country_code),group in country.groupby(['model','tech','country']):
        if (tech,country_code) not in refs.index:
            continue
        g=group.set_index(['climate_ssp','station_ssp'])
        keys=[('ssp126','ssp126'),('ssp585','ssp126'),('ssp126','ssp585'),('ssp585','ssp585')]
        if not all(k in g.index for k in keys):
            continue
        a,b,c,d=[g.loc[k] for k in keys]
        if not all(np.isfinite(x.R) and x.capacity_mw>0 for x in [a,b,c,d]):
            continue
        D=d.R-a.R
        layout=((c.R-a.R)+(d.R-b.R))/2
        climate=((b.R-a.R)+(d.R-c.R))/2
        fixed=c.R-a.R
        h0_a=a.normal_annual_mwh/a.capacity_mw
        h0_c=c.normal_annual_mwh/c.capacity_mw
        rho_a=a.net_mwh/a.normal_annual_mwh
        rho_c=c.net_mwh/c.normal_annual_mwh
        crows.append(dict(model=model,tech=tech,country=country_code,D=D,layout=layout,climate=climate,
                           fixed_climate126_deployment=fixed,delta_H0=h0_c-h0_a,
                           delta_rho_pp=100*(rho_c-rho_a),R126=a.R,R126_target=c.R,
                           potential_equal_capacity_reduction_TWh=-fixed*a.capacity_mw/1e6,
                           equal_normal_generation_loss_reduction_TWh=a.net_mwh/1e6-a.normal_annual_mwh*rho_c/1e6,
                           reference_common_capacity_mw=a.capacity_mw,
                           target_common_capacity_mw=c.capacity_mw,
                           candidate=(D < -TOL and layout < -TOL and fixed < -TOL),
                           candidate_normal_output=(D < -TOL and layout < -TOL and fixed < -TOL and h0_c>=h0_a-TOL),
                           candidate_equal_generation=(D < -TOL and layout < -TOL and fixed < -TOL and rho_c < rho_a-TOL),
                           equal_generation_capacity_ratio=h0_a/h0_c,
                           closure=D-layout-climate))
    cm=pd.DataFrame(crows)
    save(cm,'country_candidates_models')
    ce=[]
    for (tech,code),r in refs.iterrows():
        g=cm[cm.tech.eq(tech)&cm.country.eq(code)]
        row=dict(tech=tech,country=code,name=r['name'],reference_capacity_mw=r.capacity_mw,n_models=len(g))
        for metric in ['D','layout','climate','fixed_climate126_deployment','delta_H0','delta_rho_pp',
                       'potential_equal_capacity_reduction_TWh','equal_normal_generation_loss_reduction_TWh']:
            row[metric]=g[metric].mean() if len(g) else np.nan
        row['joint_support']=int(g.candidate.sum())
        row['joint_normal_output_support']=int(g.candidate_normal_output.sum())
        row['joint_equal_generation_support']=int(g.candidate_equal_generation.sum())
        row['equal_generation_capacity_ratio']=g.equal_generation_capacity_ratio.mean() if len(g) else np.nan
        row['paired_negative_support']=int((g.D < -TOL).sum())
        row['layout_negative_support']=int((g.layout < -TOL).sum())
        row['fixed126_negative_support']=int((g.fixed_climate126_deployment < -TOL).sum())
        row['mean_candidate']=(len(g)==4 and row['D'] < -TOL and row['layout'] < -TOL and row['fixed_climate126_deployment'] < -TOL)
        row['mean_normal_output']=bool(row['mean_candidate'] and row['delta_H0']>=-TOL)
        row['mean_equal_generation']=bool(row['mean_candidate'] and row['delta_rho_pp'] < -TOL)
        ce.append(row)
    ce=pd.DataFrame(ce)
    save(ce,'country_candidates_ensemble')
    save(ce[ce.mean_candidate & ce.joint_support.eq(4)],'country_candidates_4of4')
    save(ce[ce.mean_candidate & ce.joint_support.ge(3)],'country_candidates_3of4')
    totals=[]
    for tech in TECHS:
        g=ce[ce.tech.eq(tech)]
        global_ref=catalog[catalog.snapshot.eq(2050)&catalog.station_ssp.eq('ssp126')&catalog.tech.eq(tech)].capacity_mw.sum()
        for additional in ['base','normal_output','equal_generation']:
            for threshold in ['mean','3/4','4/4']:
                mask={'base':g.mean_candidate,'normal_output':g.mean_normal_output,'equal_generation':g.mean_equal_generation}[additional]
                support={'base':g.joint_support,'normal_output':g.joint_normal_output_support,'equal_generation':g.joint_equal_generation_support}[additional]
                if threshold!='mean':
                    mask=mask & (support>=int(threshold[0]))
                selected=g[mask]
                totals.append(dict(tech=tech,criterion={'base':'candidate','normal_output':'candidate_with_normal_output','equal_generation':'candidate_equal_normal_generation'}[additional],
                                   support=threshold,n_countries=len(selected),denominator_countries=len(g),
                                   country_pct=100*len(selected)/len(g),
                                   comparable_countries=int(g.n_models.eq(4).sum()),
                                   country_comparable_pct=100*len(selected)/g.n_models.eq(4).sum(),
                                   reference_capacity_TW=selected.reference_capacity_mw.sum()/1e6,
                                   denominator_capacity_TW=g.reference_capacity_mw.sum()/1e6,
                                   capacity_pct=100*selected.reference_capacity_mw.sum()/g.reference_capacity_mw.sum(),
                                   global_capacity_pct=100*selected.reference_capacity_mw.sum()/global_ref,
                                   countries=';'.join(selected.sort_values('reference_capacity_mw',ascending=False).country)))
    totals=pd.DataFrame(totals)
    save(totals,'country_candidate_shares')
    followup = write_followup_summary(levels, ce, cm)
    # Plot contract: quantitative grid; snapshots distinguish deployment scale from annual total losses.
    def trend_panel(ax,tech,kind,label):
        ax.text(-.14,1.04,label,transform=ax.transAxes,fontweight='bold')
        ax.set_title(('Wind' if tech=='wind' else 'Solar')+(' capacity' if kind=='capacity' else ' total net loss'),loc='left')
        for ssp, marker in zip(SSPS,['o','s','^']):
            if kind=='capacity':
                g=capacity[capacity.tech.eq(tech)&capacity.station_ssp.eq(ssp)].sort_values('snapshot')
                ax.plot(g.snapshot,g.capacity_TW,color=COLORS[ssp],marker=marker,ms=4,label=ssp.upper())
            else:
                g=annual_display[annual_display.tech.eq(tech)&annual_display.climate_ssp.eq(ssp)&annual_display.metric.eq('net_loss_TWh')].sort_values('year')
                ax.plot(g.year,g['mean'],color=COLORS[ssp],label=ssp.upper(),lw=1.3)
                ax.fill_between(g.year,g.minimum,g.maximum,color=COLORS[ssp],alpha=.12,lw=0)
        ax.set_ylabel('Installed capacity (TW)' if kind=='capacity' else 'Annual net loss (TWh yr⁻¹)')
        ax.set_xlabel('Capacity snapshot' if kind=='capacity' else 'Year')
        ax.set_xticks([2030,2040,2050] if kind=='capacity' else [2030,2040,2050,2059])
        ax.grid(axis='y',alpha=.15)
    fig,axes=plt.subplots(2,2,figsize=(7.2,5.7),layout='constrained')
    for row,kind in enumerate(['capacity','loss']):
        for col,tech in enumerate(TECHS):
            trend_panel(axes[row,col],tech,kind,'abcd'[row*2+col])
    axes[0,0].legend(fontsize=7)
    fig.savefig(OUT/'capacity_total_loss_trends.png')
    plt.close(fig)
    for kind,labels in [('capacity','ab'),('loss','cd')]:
        fig,axes=plt.subplots(1,2,figsize=(7.2,2.9),layout='constrained')
        for ax,tech,label in zip(axes,TECHS,labels): trend_panel(ax,tech,kind,label)
        axes[0].legend(fontsize=7)
        fig.savefig(OUT/f'capacity_total_loss_trends_{labels}.png')
        plt.close(fig)
    def country_panel(ax,tech,label):
        ax.text(-.14,1.04,label,transform=ax.transAxes,fontweight='bold')
        ax.set_title('Wind' if tech=='wind' else 'Solar',loc='left')
        g=totals[totals.tech.eq(tech)&totals.criterion.eq('candidate')].set_index('support').loc[['mean','3/4','4/4']]
        x=np.arange(3)
        ax.bar(x-.17,g.country_pct,.32,color='#487A96',label='Countries')
        ax.bar(x+.17,g.capacity_pct,.32,color='#D39A54',label='SSP126 capacity')
        for i,(_,r) in enumerate(g.iterrows()):
            ax.text(i-.17,r.country_pct+1.2,f'{r.n_countries}/{r.denominator_countries}',ha='center',fontsize=6)
            ax.text(i+.17,r.capacity_pct+1.2,f'{r.capacity_pct:.1f}%',ha='center',fontsize=6)
        ax.set_xticks(x,['Ensemble mean','≥3/4 models','4/4 models'])
        ax.set_ylim(0,100)
        ax.set_ylabel('Share of reference countries / capacity (%)')
        ax.grid(axis='y',alpha=.15)
    fig,axes=plt.subplots(1,2,figsize=(7.2,3.0),layout='constrained')
    for ax,tech,label in zip(axes,TECHS,'ab'): country_panel(ax,tech,label)
    axes[0].legend(fontsize=7,loc='upper left')
    fig.savefig(OUT/'deployment_candidates.png');plt.close(fig)
    for tech,label in zip(TECHS,'ab'):
        fig,ax=plt.subplots(figsize=(3.65,3.0),layout='constrained')
        country_panel(ax,tech,label);ax.legend(fontsize=7,loc='upper left')
        fig.savefig(OUT/f'deployment_candidates_{label}.png');plt.close(fig)
    waterfall=pd.read_csv(input_paths['waterfall'])
    save(summarize(waterfall,['tech','snapshot'],['climate_exposure','climate_normal_cf','climate_relative_loss','layout','gap']),
         'climate_layout_shapley_display')
    cross=[]
    for ssp,tech in product(SSPS,TECHS):
        for weather,capacity_year in product([2030,2050],[2030,2050]):
            cross.append(dict(climate_ssp=ssp,station_ssp=ssp,tech=tech,
                              weather_window=f'{weather}-{weather+9}',capacity_snapshot=capacity_year,
                              loss_available=weather==capacity_year,
                              needed_for_time_climate_deployment=True,
                              baseline_requirement='Use a common normal-CF baseline for climate-only interpretation, or report baseline effect'))
    save(pd.DataFrame(cross),'same_ssp_time_required_cross_cells')
    audit=dict(annual_rows=len(annual),annual_four_models=bool(annual.groupby(['tech','climate_ssp','year']).model.nunique().eq(4).all()),
               maximum_R_identity_error=float(np.max(abs(window.R-window.net_mwh/window.capacity_mw))),
               maximum_temporal_closure_TWh=float(temporal.closure_TWh.abs().max()),
               maximum_country_closure=float(cm.closure.abs().max()),
               minimum_annual_common_capacity_coverage_pct=float(annual.coverage_pct.min()),
               countries_with_incomplete_models=ce.loc[ce.n_models.ne(4),['tech','country','n_models']].to_dict('records'),
               inputs={k:dict(path=str(v.relative_to(ROOT)),sha256=hashlib.sha256(v.read_bytes()).hexdigest()) for k,v in input_paths.items()},
               candidate_definition='D<0 AND Shapley layout<0 AND fixed-climate126 deployment585-minus126<0; mean signs plus joint per-model support',
               normal_output_sensitivity='Additional H0_target>=H0_reference; normal annual CF baseline, not observed annual generation',
               denominator='Named countries with positive SSP126 2050 catalogue capacity; CHN merged; unassigned/ambiguous excluded from country denominator and retained in global_capacity_pct',
               time_counterfactual_status='Off-diagonal capacity-snapshot/weather-window loss cells unavailable; exact scale/intensity decomposition supplied instead',
               followup_summary=dict(source='outputs/meeting_loss/source_data/followup_summary.csv',
                                     rows=len(followup),
                                     sha256=hashlib.sha256((DATA/'followup_summary.csv').read_bytes()).hexdigest(),
                                     normal_Q_limit='Normal-generation arithmetic counterfactual; not actual supply'),
               statistics='Four-model arithmetic mean and min-max; sign support is not significance',
               figures=['capacity_total_loss_trends.png','capacity_total_loss_trends_ab.png','capacity_total_loss_trends_cd.png','deployment_candidates.png','deployment_candidates_a.png','deployment_candidates_b.png'],
               visual_review='pending')
    assert audit['annual_four_models']
    assert audit['maximum_temporal_closure_TWh']<1e-8
    assert audit['maximum_country_closure']<1e-8
    assert audit['maximum_R_identity_error']<1e-8
    (OUT/'data_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    print(totals.drop(columns='countries').to_string(index=False))
    print('Saved:',OUT)


if __name__ == '__main__':
    main()
