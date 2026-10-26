"""Meeting follow-up: annual station exposure and controlled deployment attribution."""
from pathlib import Path
from datetime import datetime, timezone
import json
import string
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, EVENTS, SSP_COLORS
from paper_figures.common.io import require_complete, digest

BASE = ROOT / 'paper_figures/main/fig01_extreme_events'
OUT = BASE / 'outputs/meeting_station'
SOURCE = OUT / 'source_data'
KEY = ['model', 'climate_ssp', 'station_ssp', 'tech', 'snapshot', 'country', 'event']
PAIRS = [('ssp585', 'ssp126'), ('ssp245', 'ssp126'), ('ssp245', 'ssp585')]
NAMES = dict(all='All events (time union)', high_temp='High temperature', high_wind='High wind',
             hot_humid='Hot and humid', icing='Icing', low_resource='Low resource',
             cold_highwind='Cold and high wind', freezing_rain='Freezing rain',
             high_humidity='High humidity', rainstorm='Rainstorm', overlap_correction='Overlap correction')
COLORS = dict(climate='#487A96', deployment='#D39A54', between='#D39A54', within='#487A96')
AUDIT = {}


def check(ok, message):
    if not ok:
        raise ValueError(message)


def write(name, frame):
    frame.to_csv(SOURCE / (name + '.csv'), index=False)
    return frame


def summary(frame, keys, value):
    out = frame.groupby(keys, dropna=False)[value].agg(mean='mean', minimum='min', maximum='max', n_models='count').reset_index()
    counts = frame.assign(positive=frame[value].gt(1e-9).astype(int), negative=frame[value].lt(-1e-9).astype(int)).groupby(keys, dropna=False)[['positive', 'negative']].sum().reset_index()
    return out.merge(counts, on=keys, validate='one_to_one')


def prepare():
    require_complete(OUTPUT / 'event_summary')
    require_complete(OUTPUT / 'acceptance')
    window = pd.read_csv(OUTPUT / 'event_summary/window.csv.gz')
    check(not window.duplicated(KEY).any(), 'Duplicate window key')
    check(set(window.model) == set(MODELS), 'Four models required')
    check(window.groupby(['station_ssp','tech','snapshot','country','event']).capacity_mw.nunique().max() == 1,
          'Common capacity changes across climates/models')
    check(np.allclose(window.E, window.capacity_event_hours / window.capacity_mw), 'Exposure definition')
    window['exposure_days'] = window.E / 24
    global_ = window[window.country.eq('GLOBAL')].copy()
    regional = window[window.country.ne('GLOBAL')]
    keys = [k for k in KEY if k != 'country']
    totals = regional.groupby(keys)[['capacity_mw','capacity_event_hours']].sum().sort_index()
    reference = global_.set_index(keys)[['capacity_mw','capacity_event_hours']].sort_index()
    check(np.allclose(totals, reference, rtol=1e-10, atol=.01), 'Country/global conservation')
    check(len(global_) == 4*9*3*13, 'Complete global window/event matrix')
    annual = pd.concat([d[d.country.eq('GLOBAL')] for d in pd.read_csv(OUTPUT / 'event_summary/annual.csv.gz', chunksize=100000)], ignore_index=True)
    annual['exposure_days'] = annual.E/24
    check(not annual.duplicated(KEY+['year']).any(), 'Duplicate annual row')
    check(len(annual) == len(global_)*10, 'Annual matrix size')
    check(annual.groupby(KEY).year.nunique().eq(10).all(), 'Ten years per window')
    annual_mean = annual.groupby(KEY).exposure_days.mean().sort_index()
    error = float((annual_mean - global_.set_index(KEY).exposure_days.sort_index()).abs().max())
    check(error < 1e-10, 'Annual/window reconstruction')
    valid = annual.capacity_valid_hours / annual.capacity_mw
    check(valid.between(.99*365*24, 366*24+1e-6).all(), 'Valid annual exposure support')
    AUDIT.update(annual_to_window_max_days=error, annual_global_rows=len(annual), window_global_rows=len(global_),
                 common_capacity_identical_across_climates_and_models=True, country_capacity_and_exposure_conservation=True,
                 minimum_capacity_weighted_valid_hours=float(valid.min()), maximum_capacity_weighted_valid_hours=float(valid.max()))
    write('global_annual_models', annual)
    write('global_window_models', global_)
    annual_summary = summary(annual, ['climate_ssp','station_ssp','tech','snapshot','year','event'], 'exposure_days')
    window_summary = summary(global_, ['climate_ssp','station_ssp','tech','snapshot','event'], 'exposure_days')
    write('global_annual_summary', annual_summary)
    write('global_window_summary', window_summary)
    raw_capacity = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv').groupby(['station_ssp','tech','snapshot']).capacity_mw.sum().rename('catalogue_capacity_mw').reset_index()
    retained = global_[global_.event.eq('all')][['station_ssp','tech','snapshot','capacity_mw']].drop_duplicates()
    coverage = retained.merge(raw_capacity, on=['station_ssp','tech','snapshot'], validate='one_to_one')
    coverage['retained_fraction'] = coverage.capacity_mw/coverage.catalogue_capacity_mw
    write('capacity_coverage', coverage)
    AUDIT['minimum_global_retained_capacity_fraction'] = float(coverage.retained_fraction.min())
    return window, global_, annual, annual_summary, window_summary


def contrasts(global_, annual):
    rows = []
    for high, low in PAIRS:
        for ident, frame in global_.groupby(['model','tech','snapshot','event']):
            v = frame.set_index(['climate_ssp','station_ssp']).exposure_days
            ll, hl, lh, hh = [v.loc[x] for x in [(low,low),(high,low),(low,high),(high,high)]]
            row = dict(zip(['model','tech','snapshot','event'],ident), high=high, low=low,
                       paired_difference=hh-ll, climate_component=((hl-ll)+(hh-lh))/2,
                       deployment_component=((lh-ll)+(hh-hl))/2,
                       climate_at_low_layout=hl-ll, climate_at_high_layout=hh-lh,
                       deployment_at_low_climate=lh-ll, deployment_at_high_climate=hh-hl,
                       interaction=hh-hl-lh+ll)
            rows.append(row)
    models = pd.DataFrame(rows)
    error = float((models.climate_component+models.deployment_component-models.paired_difference).abs().max())
    check(error<1e-10, 'Climate/deployment closure')
    AUDIT['climate_deployment_max_closure_days'] = error
    write('climate_deployment_models', models)
    ids = ['model','tech','snapshot','event','high','low']
    long = models.melt(ids,var_name='term',value_name='value')
    result = summary(long,[k for k in ids if k!='model']+['term'],'value')
    write('climate_deployment_summary',result)
    # Inclusive event-label accounting is closed with an explicit overlap correction.
    event_rows=[]
    for ident,g in models.groupby(['model','tech','snapshot','high','low']):
        for term in ['paired_difference','climate_component','deployment_component']:
            vals=g.set_index('event')[term]
            event_rows.append(dict(zip(['model','tech','snapshot','high','low'],ident), event='overlap_correction',
                                   term=term,value=vals['all']-vals.drop('all').sum()))
    event_long=pd.concat([long[long.term.isin(['paired_difference','climate_component','deployment_component'])],pd.DataFrame(event_rows)],ignore_index=True)
    write('event_accounting_models',event_long)
    write('event_accounting_summary',summary(event_long,[k for k in ids if k!='model']+['term'],'value'))
    slopes=[]
    paired=annual[annual.climate_ssp.eq(annual.station_ssp)]
    for ident,g in paired.groupby(['model','tech','climate_ssp','event']):
        value=np.polyfit(g.year.to_numpy()-2030,g.exposure_days.to_numpy(),1)[0]*10
        slopes.append(dict(zip(['model','tech','ssp','event'],ident),slope_days_per_decade=value))
    slopes=pd.DataFrame(slopes)
    write('annual_linear_trend_models',slopes)
    write('annual_linear_trend_summary',summary(slopes,['tech','ssp','event'],'slope_days_per_decade'))
    return models,result


def country_decomposition(window,global_models):
    records=[]
    union=window[window.event.eq('all')]
    for high,low in PAIRS:
        for (model,tech,snapshot,climate),g in union[union.climate_ssp.isin([high,low])].groupby(['model','tech','snapshot','climate_ssp']):
            a=g[g.station_ssp.eq(high)].set_index('country')
            b=g[g.station_ssp.eq(low)].set_index('country')
            center=(a.loc['GLOBAL','exposure_days']+b.loc['GLOBAL','exposure_days'])/2
            p=pd.DataFrame(dict(share_high=a.capacity_mw/a.loc['GLOBAL','capacity_mw'],
                                share_low=b.capacity_mw/b.loc['GLOBAL','capacity_mw'],
                                days_high=a.exposure_days,days_low=b.exposure_days)).drop('GLOBAL')
            p['both_present']=p.days_high.notna()&p.days_low.notna()
            p[['share_high','share_low']]=p[['share_high','share_low']].fillna(0)
            # Absent-country exposure is undefined; its observed counterpart is the neutral extension.
            p.days_high=p.days_high.fillna(p.days_low)
            p.days_low=p.days_low.fillna(p.days_high)
            p['reference_days']=center
            p['between_country_days']=(p.share_high-p.share_low)*((p.days_high+p.days_low)/2-center)
            p['within_country_days']=(p.share_high+p.share_low)/2*(p.days_high-p.days_low)
            p['deployment_days']=p.between_country_days+p.within_country_days
            p['uncentered_contribution_days']=p.share_high*p.days_high-p.share_low*p.days_low
            check(abs(p.deployment_days.sum()-(a.loc['GLOBAL','exposure_days']-b.loc['GLOBAL','exposure_days']))<1e-9,
                  'Country decomposition closure')
            p=p.reset_index().assign(model=model,tech=tech,snapshot=snapshot,climate_ssp=climate,high=high,low=low)
            records.append(p)
    fixed=pd.concat(records,ignore_index=True)
    write('country_deployment_fixed_climate_models',fixed)
    keys=['model','tech','snapshot','high','low','country']
    vals=['share_high','share_low','days_high','days_low','reference_days','between_country_days','within_country_days','deployment_days','uncentered_contribution_days']
    country=fixed.groupby(keys,as_index=False)[vals].mean()
    write('country_deployment_models',country)
    long=country.melt(keys,value_vars=vals,var_name='term',value_name='value')
    country_summary=summary(long,[k for k in keys if k!='model']+['term'],'value')
    write('country_deployment_summary',country_summary)
    aggregate=country.groupby([k for k in keys if k!='country'],as_index=False)[['between_country_days','within_country_days','deployment_days']].sum()
    match=aggregate.merge(global_models[global_models.event.eq('all')],on=[k for k in keys if k!='country'],validate='one_to_one')
    error=float((match.deployment_days-match.deployment_component).abs().max())
    check(error<1e-9,'Country accounting vs global deployment')
    AUDIT.update(country_deployment_max_closure_days=error,unmatched_country_comparisons=int((~fixed.both_present).sum()),
                 centered_country_reference='Mean global exposure of the two layouts within each fixed climate; symmetric averaging over the two climates.')
    write('country_component_models',aggregate)
    aggregate_long=aggregate.melt([k for k in keys if k!='country'],var_name='term',value_name='value')
    component_summary=summary(aggregate_long,['tech','snapshot','high','low','term'],'value')
    write('country_component_summary',component_summary)
    return country,country_summary,component_summary


def style():
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['DejaVu Sans'],'font.size':8,
                         'axes.titlesize':9,'axes.labelsize':8,'axes.spines.top':False,'axes.spines.right':False,
                         'axes.linewidth':.7,'xtick.labelsize':7,'ytick.labelsize':7,'legend.frameon':False})


def save(fig, stem):
    fig.savefig(OUT/(stem+'.png'),dpi=600,facecolor='white')
    plt.close(fig)


def legend(fig):
    handles=[Line2D([0],[0],color=SSP_COLORS[s],label=s.upper(),lw=1.5) for s in SSPS]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.53,.974),ncol=3,fontsize=8)


def trend_panel(ax,table,tech,event,letter):
    for ssp in SSPS:
        d=table[table.tech.eq(tech)&table.event.eq(event)&table.climate_ssp.eq(ssp)&table.station_ssp.eq(ssp)].sort_values('year')
        ax.fill_between(d.year,d.minimum,d.maximum,color=SSP_COLORS[ssp],alpha=.12,lw=0)
        ax.plot(d.year,d['mean'],color=SSP_COLORS[ssp],lw=1.25)
    for x in [2039.5,2049.5]:
        ax.axvline(x,color='.6',lw=.55,ls=':',zorder=0)
    title=NAMES[event] if event!='low_resource' else ('Low wind speed' if tech=='wind' else 'Low irradiance')
    ax.set_title(letter+'  '+title,loc='left',fontweight='bold',pad=5)
    ax.set(xlim=(2029.5,2059.5),xticks=[2030,2040,2050,2059],ylabel='Exposure (days yr⁻¹)')
    ax.grid(axis='y',lw=.4,color='.9',zorder=0)
    ax.set_ylim(bottom=0)


def plot_trends(table):
    for tech in ['wind','solar']:
        events=['all',*EVENTS[tech]]
        rows=(len(events)+1)//2
        fig,axes=plt.subplots(rows,2,figsize=(7.2,rows*2.15+1.05),squeeze=False)
        for i,event in enumerate(events):trend_panel(axes.flat[i],table,tech,event,string.ascii_lowercase[i])
        if len(events)%2:axes.flat[-1].set_visible(False)
        for ax in axes[-1]:ax.set_xlabel('Year')
        fig.suptitle(('Wind' if tech=='wind' else 'Solar PV')+' station extreme-event exposure',fontsize=12,y=.992)
        legend(fig)
        fig.text(.1,.026,'Lines: four-GCM mean; shading: four-GCM min–max (not a confidence interval).\nDotted boundaries: capacity snapshots change. 1 exposure day = 24 accumulated event hours.',fontsize=7)
        fig.subplots_adjust(left=.1,right=.985,bottom=.105,top=.89,hspace=.43,wspace=.29)
        stem='meeting_station_trends_'+tech
        save(fig,stem)
        for row in range(rows):
            fig,axes=plt.subplots(1,2,figsize=(7.2,3.15))
            letters=''
            for col in range(2):
                i=2*row+col
                if i<len(events):
                    trend_panel(axes[col],table,tech,events[i],string.ascii_lowercase[i]);letters+=string.ascii_lowercase[i]
                    axes[col].set_xlabel('Year')
                else:axes[col].set_visible(False)
            legend(fig)
            fig.text(.1,.025,'Four-GCM mean and min–max; paired climate + deployment paths. Snapshots: 2030 / 2040 / 2050.',fontsize=6.7)
            fig.subplots_adjust(left=.1,right=.985,bottom=.21,top=.78,wspace=.29)
            save(fig,stem+'_'+letters)


def driver_panel(ax,kind,tech,levels,decomp,models,letter):
    if kind=='matrix':
        d=levels[levels.tech.eq(tech)&levels.snapshot.eq(2050)&levels.event.eq('all')]
        a=d.pivot(index='climate_ssp',columns='station_ssp',values='mean').loc[list(SSPS),list(SSPS)].to_numpy()
        shared=levels[levels.snapshot.eq(2050)&levels.event.eq('all')]['mean']
        lower,upper=float(shared.min())-1,float(shared.max())+1
        im=ax.imshow(a,cmap='YlOrBr',vmin=lower,vmax=upper)
        for i in range(3):
            for j in range(3):
                ax.text(j,i,f'{a[i,j]:.2f}',ha='center',va='center',fontsize=10,color='white' if a[i,j]>(lower+.65*(upper-lower)) else 'black')
            ax.add_patch(Rectangle((i-.48,i-.48),.96,.96,fill=False,ec='.2',lw=1))
        ax.set(xticks=range(3),yticks=range(3),xticklabels=['126','245','585'],yticklabels=['126','245','585'],xlabel='Deployment SSP',ylabel='Climate SSP')
        ax.set_title(letter+'  '+('Wind' if tech=='wind' else 'Solar PV')+': exposure days yr⁻¹',loc='left',fontweight='bold')
    else:
        labels=[]
        for pi,(h,l) in enumerate(PAIRS):
            q=decomp[decomp.tech.eq(tech)&decomp.snapshot.eq(2050)&decomp.event.eq('all')&decomp.high.eq(h)&decomp.low.eq(l)].set_index('term')
            for k,(term,color) in enumerate([('climate_component',COLORS['climate']),('deployment_component',COLORS['deployment']),('paired_difference','#444444')]):
                row=q.loc[term];x=pi+(k-1)*.22
                ax.bar(x,row['mean'],.2,color=color,zorder=2)
                ax.plot([x,x],[row.minimum,row.maximum],color='.2',lw=.8,zorder=3)
                vals=models[models.tech.eq(tech)&models.snapshot.eq(2050)&models.event.eq('all')&models.high.eq(h)&models.low.eq(l)][term].to_numpy()
                ax.scatter(x+np.linspace(-.04,.04,4),vals,s=7,color='.2',zorder=4)
            labels.append(h[3:]+' − '+l[3:])
        ax.axhline(0,color='.3',lw=.6)
        ax.set(xticks=range(3),xticklabels=labels,ylabel='Exposure difference (days yr⁻¹)')
        ax.set_title(letter+'  '+('Wind' if tech=='wind' else 'Solar PV')+': pathway difference',loc='left',fontweight='bold')
        ax.grid(axis='y',color='.9',lw=.4,zorder=0)


def plot_drivers(levels,decomp,models):
    spec=[('matrix','wind'),('matrix','solar'),('decomp','wind'),('decomp','solar')]
    handles=[Patch(color=COLORS['climate'],label='Climate'),Patch(color=COLORS['deployment'],label='Deployment'),Patch(color='#444444',label='Total')]
    for selected,suffix,height in [(range(4),'',6.5),([0,1],'_ab',3.8),([2,3],'_cd',3.8)]:
        selected=list(selected);fig,axes=plt.subplots((len(selected)+1)//2,2,figsize=(7.2,height),squeeze=False)
        for ax,i in zip(axes.flat,selected):driver_panel(ax,*spec[i],levels,decomp,models,string.ascii_lowercase[i])
        fig.suptitle('2050–2059: climate versus deployment',fontsize=12,y=.985)
        if 2 in selected:fig.legend(handles=handles,ncol=3,loc='upper center',bbox_to_anchor=(.53,.943),fontsize=8)
        footer = ('Four-GCM mean exposure; shared color scale. Boxed cells are the paired pathways.' if selected == [0,1] else\
                  'Each contrast is calculated within a GCM, then averaged equally over four GCMs.\nPoints/ranges: individual GCMs/min–max. Deployment changes capacity weights and locations.')
        if len(selected) == 4: footer += '\nHeatmaps share one color scale; cell labels give exact means.'
        fig.text(.09,.025,footer,fontsize=6.8)
        fig.subplots_adjust(left=.1,right=.98,bottom=.16 if height<4 else .11,top=.79 if height<4 else .87,wspace=.35,hspace=.55)
        save(fig,'meeting_station_attribution'+suffix)


def spatial_panel(ax,country,tech,high,low,letter):
    d=country[country.tech.eq(tech)&country.snapshot.eq(2050)&country.high.eq(high)&country.low.eq(low)]
    d=d.groupby('country')[['between_country_days','within_country_days','deployment_days']].mean()
    chosen=d.deployment_days.abs().nlargest(8).index
    shown=d.loc[chosen].sort_values('deployment_days')
    other=d.drop(chosen).sum().to_frame().T;other.index=['Other countries']
    shown=pd.concat([shown,other])
    for i,(_,row) in enumerate(shown.iterrows()):
        positive=negative=0.
        for term,color in [('between_country_days',COLORS['between']),('within_country_days',COLORS['within'])]:
            value=row[term];left=positive if value>=0 else negative
            ax.barh(i,value,left=left,height=.63,color=color)
            if value>=0:positive+=value
            else:negative+=value
        ax.scatter(row.deployment_days,i,s=16,marker='D',color='#333333',zorder=3)
    ax.axvline(0,color='.4',lw=.6)
    ax.set(yticks=range(len(shown)),yticklabels=shown.index,xlabel='Deployment contribution (days yr⁻¹)')
    ax.invert_yaxis();ax.grid(axis='x',color='.9',lw=.4,zorder=0)
    name='Wind' if tech=='wind' else 'Solar PV'
    ax.set_title(f'{letter}  {name}: {high[3:]} − {low[3:]}',loc='left',fontweight='bold')


def plot_spatial(country):
    spec=[('wind','ssp585','ssp126'),('solar','ssp585','ssp126'),('solar','ssp245','ssp126'),('solar','ssp245','ssp585')]
    handles=[Patch(color=COLORS['between'],label='Country capacity shares'),Patch(color=COLORS['within'],label='Within-country deployment'),Line2D([0],[0],marker='D',color='none',markerfacecolor='#333333',label='Sum',markersize=4)]
    for selected,suffix,height in [(range(4),'',7.3),([0,1],'_ab',4.3),([2,3],'_cd',4.3)]:
        selected=list(selected);fig,axes=plt.subplots((len(selected)+1)//2,2,figsize=(7.6,height),squeeze=False)
        for ax,i in zip(axes.flat,selected):spatial_panel(ax,country,*spec[i],string.ascii_lowercase[i])
        fig.suptitle('Where deployment changes exposure (2050–2059)',fontsize=11,y=.99)
        fig.legend(handles=handles,ncol=3,loc='upper center',bbox_to_anchor=(.53,.95),fontsize=7)
        fig.text(.15,.025,'Country-share terms are centered on the mean global exposure of the two layouts.\nTop eight absolute country contributions; the remaining countries are summed. Four-GCM means.',fontsize=6.8)
        fig.subplots_adjust(left=.15,right=.98,bottom=.16 if height<5 else .10,top=.80 if height<5 else .88,wspace=.48,hspace=.46)
        save(fig,'meeting_station_country_attribution'+suffix)


def report(levels,decomp,components,country_summary):
    def table(d):return d.to_html(index=False,border=0,float_format=lambda x:f'{x:.3f}')
    paired=levels[levels.event.eq('all')&levels.climate_ssp.eq(levels.station_ssp)]
    overview=paired.pivot(index=['tech','snapshot'],columns='climate_ssp',values='mean').reset_index()
    out=['<!doctype html><meta charset="utf-8"><title>场站极端天气会议分析</title>',
         '<style>body{font-family:Arial,sans-serif;max-width:1150px;margin:35px auto;line-height:1.65;color:#222}table{border-collapse:collapse;font-size:13px}td,th{padding:6px 10px;border-bottom:1px solid #ddd}img{max-width:100%}code{background:#f1f1f1}</style>',
         '<h1>场站级极端天气：路径排序、年度趋势与布局解释</h1>',
         '<p>小凯，本分析基于已验收 Extreme 场站汇总，保留四模式、气候 SSP × 部署 SSP 九组合及相同部署内的共同有效容量。年均暴露为容量加权累计事件小时除以 24；不是事件发生的日历天数。每个快照应用于后续十年，all 是事件时间并集。</p>',
         '<h2>主要纠正</h2>',
         '<p>2050s 风电的 SSP585 低于 SSP126 确由部署权重主导；光伏的对应下降则由气候项主导，部署项反而增加暴露。光伏 SSP245 的额外暴露由部署主导。三条路径的排序不是三个年代都保持一致，光伏 585−126 也并非四模式一致。</p>',
         '<h2>三个年代配对路径的累计暴露（天/年）</h2>',table(overview),
         '<p>容量是对应年份的总量快照，不累加；均匀扩大全部装机不改变单位容量加权暴露。部署效应来自容量份额、位置和有效支持的变化。SSP585 部署来源仍为原始 SSP5-6.0 文件映射，不能当作另有 SSP5-8.5 原始部署资料。</p>',
         '<h2>2050s 路径差的受控分解（天/年）</h2>',
         '<p>对称分解在两个固定部署内取跨气候差的平均作为气候项，在两个固定气候内取跨部署差的平均作为部署项；两项严格闭合到配对路径总差。positive/negative 是四模式中差值为正/负的数量，不表示显著性。</p>',
         table(decomp[decomp.snapshot.eq(2050)&decomp.event.eq('all')&decomp.term.isin(['paired_difference','climate_component','deployment_component'])][['tech','high','low','term','mean','minimum','maximum','positive','negative']]),
         '<h2>部署为何改变暴露：国家份额与国家内部布局</h2>',
         '<p>在每个固定气候下，把部署差拆成国家容量份额变化项和国家内部容量加权暴露变化项。国家份额项以两布局全球暴露的均值为参照：将份额转向高于该参照的国家增加暴露，转向低于该参照的国家减少暴露。国家内部项包括站点位置和容量权重变化；这里只能作统计归因，不能代替天气物理成因。</p>',
         table(components[components.snapshot.eq(2050)][['tech','high','low','term','mean','minimum','maximum','positive','negative']]),
         '<p>国家缺少一侧装机时，缺侧暴露未定义；仅为可加分解将其延拓为另一侧暴露，把该国贡献归于份额变化。本批具体计数见 audit.json。国家分量的中心化约定影响个别国家归因值，但不影响全球部署总量。未分配/边界歧义记录保留以保证全球闭合。</p>']
    for tech,h,l in [('wind','ssp585','ssp126'),('solar','ssp585','ssp126'),('solar','ssp245','ssp126'),('solar','ssp245','ssp585')]:
        q=country_summary[country_summary.tech.eq(tech)&country_summary.snapshot.eq(2050)&country_summary.high.eq(h)&country_summary.low.eq(l)]
        q=q.pivot(index='country',columns='term',values='mean')
        ids=q.deployment_days.abs().nlargest(12).index
        q=q.loc[ids].sort_values('deployment_days').reset_index()
        q['share_high_pct']=q.share_high*100;q['share_low_pct']=q.share_low*100
        out += [f'<h3>{tech}: {h} − {l}，主要国家</h3>',table(q[['country','share_low_pct','share_high_pct','days_low','days_high','between_country_days','within_country_days','deployment_days']])]
    out += ['<h2>年度轨迹与事件类型</h2>','<p>曲线是四模式均值，阴影是四模式极差；虚线标出容量快照切换边界。2030–2059 线性斜率仅作描述，跨快照混合气候与部署变化，不能视为纯气候趋势或显著性检验。不同事件有重叠，不把事件曲线相加替代并集。</p>']
    for stem in ['meeting_station_trends_wind','meeting_station_trends_solar','meeting_station_attribution','meeting_station_country_attribution']:
        out += [f'<img src="{stem}.png" alt="{stem}">']
    out += ['<h2>可追溯输出与边界</h2>', '<p>source_data 中保留年度/年代各模式值、气候/部署分解、逐事件分解与重叠修正、国家容量份额、逐模式方向数及有效覆盖。audit.json 记录输入哈希和闭合校验。小时间隔不被转换为统一公历；年度已按上游模式原生日历累计。现有汇总支持 2030–2059，未外推 2015–2029 或 2060。</p>', '<p>希望对你有帮助，小凯！</p>']
    (OUT/'report.html').write_text('\n'.join(out),encoding='utf-8')


def main():
    SOURCE.mkdir(parents=True,exist_ok=True)
    window,global_,annual,annual_summary,levels=prepare()
    models,decomp=contrasts(global_,annual)
    country,country_summary,components=country_decomposition(window,models)
    style();plot_trends(annual_summary);plot_drivers(levels,decomp,models);plot_spatial(country)
    report(levels,decomp,components,country_summary)
    AUDIT['figure_contract'] = dict(archetype='quantitative grid', backend='Python/matplotlib', export='600 dpi PNG',
        conclusion='Test whether paired exposure contrasts are driven by climate or deployment; quantify country-share and within-country contributions.',
        uncertainty='Four GCMs, equal-weight mean and min-max; sign counts are not significance tests',
        coverage='2030-2059, three fixed decadal capacity snapshots; all nine climate/deployment combinations')
    AUDIT.update(status='PASSED',created_utc=datetime.now(timezone.utc).isoformat(),units='accumulated exposure days per year',
                 inputs={str(p):dict(sha256=digest(p),bytes=p.stat().st_size) for p in [OUTPUT/'event_summary/annual.csv.gz',OUTPUT/'event_summary/window.csv.gz',OUTPUT/'catalogues/capacity_by_country.csv']},
                 script_sha256=digest(Path(__file__)),figures=sorted(p.name for p in OUT.glob('*.png')))
    (OUT/'audit.json').write_text(json.dumps(AUDIT,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in AUDIT.items() if k not in ['inputs','figures']},indent=2))
    print('OUTPUT',OUT)

if __name__=='__main__':main()
