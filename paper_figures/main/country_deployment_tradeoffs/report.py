"""Generate the Chinese country-level interpretation from audited model tables."""
import argparse
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, SSPS, TECHS
from paper_figures.common.io import digest, write_csv, write_json

FOLDER = ROOT / 'paper_figures/main/country_deployment_tradeoffs'
NAMES = {'GLOBAL': '全球', 'USA': '美国', 'CHN': '中国', 'BRA': '巴西', 'RUS': '俄罗斯',
         'IND': '印度', 'IRN': '伊朗', 'KAZ': '哈萨克斯坦', 'AUS': '澳大利亚',
         'ARG': '阿根廷', 'SAU': '沙特阿拉伯'}
TECH_NAMES = {'wind': '风电', 'solar': '光伏'}


def fmt(value, digits=2, signed=False):
    if not np.isfinite(value):
        return '不可用'
    return format(value, ('+' if signed else '') + ',.' + str(digits) + 'f')


def table(headers, rows):
    result = '<div class="table-wrap"><table><thead><tr>'
    result += ''.join('<th>' + html.escape(str(x)) + '</th>' for x in headers)
    result += '</tr></thead><tbody>'
    for row in rows:
        result += '<tr>' + ''.join('<td>' + html.escape(str(x)) + '</td>' for x in row) + '</tr>'
    return result + '</tbody></table></div>'


def best_label(frame, country, tech, metric, climate):
    g = frame[(frame.country == country) & (frame.tech == tech)
              & (frame.metric == metric) & (frame.climate_ssp == climate)]
    g = g[g.ensemble_best.eq(True)]
    if g.empty:
        return '不可比'
    return ' / '.join(str(r.station_ssp).replace('ssp', '') + f' ({int(r.model_wins)}/4)'
                      for r in g.itertuples())


def robust_label(frame, country, tech, metric):
    g = frame[(frame.country == country) & (frame.tech == tech) & (frame.metric == metric)]
    best = g[g.robust_best.eq(True)]
    if not best.empty:
        return '/'.join(best.station_ssp.str.replace('ssp', '', regex=False))
    if g.empty or not g.groups_available.eq(12).all():
        return '数据不足'
    return '无全组合一致最优'



def question_analysis(selection, metrics, contrasts, findings, wins, robust, names_map,
                      source, data_dir, data_prefix):
    """Answer the five deployment questions with model-paired, country-level evidence."""
    countries = list(selection.country)
    nationals = [c for c in countries if c != 'GLOBAL']
    climates = list(SSPS)
    rows = []
    for r in findings.itertuples():
        target = 'ssp' + r.pair.split('/')[0]
        c = contrasts[(contrasts.country == r.country) & (contrasts.tech == r.tech)
                      & (contrasts.climate_ssp == r.climate_ssp) & (contrasts.target_ssp == target)]
        assert c.model.nunique() == 4 and len(c) == 4
        low = metrics[(metrics.country == r.country) & (metrics.tech == r.tech)
                      & (metrics.climate_ssp == r.climate_ssp)
                      & (metrics.station_ssp == r.low_capacity_ssp)].set_index('model')
        high = metrics[(metrics.country == r.country) & (metrics.tech == r.tech)
                       & (metrics.climate_ssp == r.climate_ssp)
                       & (metrics.station_ssp == r.high_capacity_ssp)].set_index('model')
        assert low.index.equals(high.index) or set(low.index) == set(high.index)
        high = high.reindex(low.index)
        dc, dl, dg = high.C_GW-low.C_GW, high.L_TWh-low.L_TWh, high.G0_TWh-low.G0_TWh
        assert len(low) == 4 and np.isfinite(low[['C_GW','L_TWh','G0_TWh','H0']]).all().all()
        assert np.isfinite(high[['C_GW','L_TWh','G0_TWh','H0']]).all().all()
        assert np.allclose(dl.sort_index(), c.set_index('model').expansion_delta_L_TWh.sort_index())
        assert np.allclose(c.expansion_scale_TWh+c.expansion_layout_TWh, c.expansion_delta_L_TWh)
        offset = (c.expansion_scale_TWh > 1e-10) & (c.expansion_layout_TWh < -1e-10)
        cost = offset & c.expansion_delta_H0_pct.lt(-1e-8)
        efficiency = offset & c.expansion_delta_H0_pct.ge(-1e-8)
        rows.append(dict(country=r.country, tech=r.tech, climate_ssp=r.climate_ssp, pair=r.pair,
            low=r.low_capacity_ssp, high=r.high_capacity_ssp,
            C_low_GW=low.C_GW.mean(), C_high_GW=high.C_GW.mean(), delta_C_GW=dc.mean(),
            delta_L_TWh=dl.mean(), L_increase_models=int(dl.gt(0).sum()),
            delta_G0_TWh=dg.mean(), G0_increase_models=int(dg.gt(0).sum()),
            scale_TWh=r.scale_TWh, layout_TWh=r.layout_TWh,
            offset_pct=(-100*r.layout_TWh/r.scale_TWh if r.scale_TWh>1e-10 and r.layout_TWh<0 else np.nan),
            delta_H0_pct=r.delta_H0_pct, offset_models=int(offset.sum()),
            cost_models=int(cost.sum()), offset_without_H0_decline_models=int(efficiency.sum())))
    q = pd.DataFrame(rows)
    assert len(q) == len(countries)*2*3*2
    stability = []
    for country in countries:
        for tech in TECHS:
            for metric in ['R','rho_pct']:
                g = wins[(wins.country==country)&(wins.tech==tech)&(wins.metric==metric)&wins.ensemble_best.eq(True)]
                sets = [set(g.loc[g.climate_ssp.eq(climate),'station_ssp']) for climate in climates]
                common = set.intersection(*sets)
                rg = robust[(robust.country==country)&(robust.tech==tech)&(robust.metric==metric)]
                strict = rg[rg.robust_best.eq(True)]
                stability.append(dict(country=country,tech=tech,metric=metric,
                    climate126='/'.join(sorted(sets[0])),climate245='/'.join(sorted(sets[1])),
                    climate585='/'.join(sorted(sets[2])),consistent_ensemble='/'.join(sorted(common)),
                    strict_best='/'.join(sorted(strict.station_ssp)),complete=bool(rg.groups_available.eq(12).all())))
    stable = pd.DataFrame(stability)
    for stem, frame in [('five_questions_summary',q),('five_questions_stability',stable)]:
        write_csv(source/(stem+'.csv'),frame)
        shutil.copy2(source/(stem+'.csv'),data_dir/(stem+'.csv'))
    def para(text):
        return '<p>'+text+'</p>'
    def direction(row):
        return row.low[3:]+' → '+row.high[3:]
    def pick(country,tech,pair,climate='ssp126'):
        return q[(q.country==country)&(q.tech==tech)&(q.pair==pair)&(q.climate_ssp==climate)].iloc[0]
    def country_names(codes):
        return '、'.join(names_map[c] for c in countries if c in set(codes)) or '无'
    def winner(country,tech,metric,climate):
        g=wins[(wins.country==country)&(wins.tech==tech)&(wins.metric==metric)
               &(wins.climate_ssp==climate)&wins.ensemble_best.eq(True)]
        return ' / '.join(f'{r.station_ssp[3:]}（{fmt(r.mean)}；{int(r.model_wins)}/4）' for r in g.itertuples()) or '不可比'
    parts=['<h2 id="question-1">问题1：装机规模增加伴随多少总损失变化？</h2>',
        para('回答这个问题必须同时报告容量变化和总损失变化。下文固定气候，比较部署245与126、585与126，'
             '并将每对部署统一为“低容量→高容量”。这比较的是同一2050年代的不同部署配置，'
             '不是随时间扩建的观测过程，也不是把所有配对路径差归因于规模。'
             '总损失L的差由规模项与布局项共同形成；规模项才是固定气候下的容量贡献。')]
    if q.high.eq('ssp126').all():
        parts.append(para('在当前样本的全部对照中，部署126的共同有效容量都高于部署245和585。'
                          '因此本节扩张方向为245→126与585→126，与前文585−126的路径差方向相反。'
                          '不能因为585的气候强迫更高，就把585预设为装机更多的一端。'))
    positive=int(q.delta_L_TWh.gt(0).sum())
    allmodels=int(q.L_increase_models.eq(4).sum())
    parts.append(para(f'全球与{len(nationals)}国、两技术、三气候、两部署对共{len(q)}组比较中，'
                      f'{positive}组的集合平均总损失随高容量部署增加，其中{allmodels}组由4/4模式支持。'
                      '这些是条件组合的描述性计数，不能视为独立样本或国家概率。'))
    grows=[]
    for tech in TECHS:
        for pair in ['245/126','585/126']:
            r=pick('GLOBAL',tech,pair)
            grows.append([TECH_NAMES[tech],direction(r),fmt(r.C_low_GW),fmt(r.C_high_GW),
                          fmt(r.delta_C_GW),fmt(r.scale_TWh,signed=True),fmt(r.layout_TWh,signed=True),
                          fmt(r.delta_L_TWh,signed=True),fmt(r.delta_G0_TWh,signed=True)])
    parts.append(para('全球固定气候126：新增装机既带来新增正常发电量，也伴随新增总损失。'
                      '因此总损失更低并不单独代表配置更好，还要同时看供给规模和单位发电损失率。'))
    parts.append(table(['技术','部署方向','低容量/GW','高容量/GW','增加/GW','规模/TWh','布局/TWh',
                        '总损失变化/TWh','全年正常电量变化/TWh'],grows))
    for tech in TECHS:
        local=q[q.tech.eq(tech)&q.country.isin(nationals)&q.climate_ssp.eq('ssp126')]
        biggest=local.nlargest(3,'delta_L_TWh')
        parts.append(para(TECH_NAMES[tech]+'固定气候126时，样本中总损失增量最大的三个部署对是：'+
            '；'.join(f'{names_map[r.country]}{direction(r)}，容量增加{fmt(r.delta_C_GW)} GW，'
                      f'总损失增加{fmt(r.delta_L_TWh)} TWh/年' for r in biggest.itertuples())+'。'
            '这说明增量大小必须按国家和技术分别量化，不能用全球单位装机均值代替。'))
        values=[]
        for country in countries:
            for pair in ['245/126','585/126']:
                r=pick(country,tech,pair)
                g=q[(q.country==country)&(q.tech==tech)&(q.pair==pair)]
                values.append([names_map[country],direction(r),fmt(r.delta_C_GW),
                    fmt(r.delta_L_TWh,signed=True),f'{fmt(g.delta_L_TWh.min())}—{fmt(g.delta_L_TWh.max())}',
                    fmt(r.delta_G0_TWh,signed=True)])
        parts.append('<h3>'+TECH_NAMES[tech]+'：各国扩张对应的电量变化</h3>')
        parts.append(table(['区域','部署方向','气候126容量增量/GW','气候126总损失增量/TWh',
                            '三气候均值的总损失增量范围/TWh','气候126正常电量增量/TWh'],values))
    parts.append(para('上表的三气候范围比较三种气候条件下的集合均值，不是四模式范围。'
                      '<a href="#paired_path_overview">配对路径绝对量图</a>同时包含气候与部署变化，'
                      '应与这里固定气候的部署比较区分。'))

    parts.extend(['<h2 id="question-2">问题2：布局变化能否抵消规模带来的损失？</h2>',
        para('能否抵消取决于国家、技术和部署对。固定气候下，正的规模贡献与负的布局贡献同时出现才称为抵消。'
             '以下抵消比例定义为“−集合平均布局贡献/集合平均规模贡献”；它不是逐模式抵消比例的均值。'
             '比例小于100%表示部分抵消，不能写成总损失下降。')])
    for tech in TECHS:
        g=q[q.tech.eq(tech)]
        partial=(g.scale_TWh.gt(0)&g.layout_TWh.lt(0)&g.delta_L_TWh.gt(0))
        full=(g.scale_TWh.gt(0)&g.layout_TWh.lt(0)&g.delta_L_TWh.le(0))
        amplify=(g.scale_TWh.gt(0)&g.layout_TWh.ge(0))
        parts.append(para(f'{TECH_NAMES[tech]}的{len(g)}组全球及国家比较中，'
            f'{int(partial.sum())}组部分抵消、{int(full.sum())}组完全抵消，'
            f'{int(amplify.sum())}组布局项与规模项同向增加损失。'))
    r=pick('GLOBAL','wind','585/126');r2=pick('GLOBAL','wind','245/126')
    parts.append(para(f'全球风电在气候126下，585→126的规模项为+{fmt(r.scale_TWh)} TWh/年，'
        f'布局项为{fmt(r.layout_TWh,signed=True)}，抵消约{fmt(r.offset_pct)}%，'
        f'但总损失仍增加{fmt(r.delta_L_TWh)}。245→126的布局项则为+{fmt(r2.layout_TWh)}，'
        '会放大而非抵消规模损失。同一技术不能给部署126贴上统一的“布局好”或“布局差”标签。'))
    for country in ['CHN','BRA']:
        if country in countries:
            r=pick(country,'wind','585/126')
            parts.append(para(f'{names_map[country]}风电585→126在气候126下，布局抵消{fmt(-r.layout_TWh)} TWh/年，'
                f'相当于规模项的{fmt(r.offset_pct)}%；三种气候的集合均值均呈抵消，'
                '但总损失仍增加。'))
    for tech in TECHS:
        for pair in ['245/126','585/126']:
            g=q[q.tech.eq(tech)&q.pair.eq(pair)&q.country.isin(nationals)]
            counts=g.groupby('country').layout_TWh.agg(lambda x:int((x<0).sum()))
            consistent=country_names(counts[counts.eq(3)].index)
            amplifying=country_names(counts[counts.eq(0)].index)
            switching=country_names(counts[counts.between(1,2)].index)
            parts.append(para(TECH_NAMES[tech]+'的'+pair.split('/')[0]+'→126对照中，'
                '三气候集合均值均抵消的国家：'+consistent+'；均不抵消的国家：'+amplifying+
                '；抵消与否随气候切换的国家：'+switching+'。'))
    parts.append(para('逐国对照还能区分持续抵消与气候依赖：下面将三个气候下的布局贡献依次列出，'
                      '并单独报告每个气候中支持抵消的模式数。仅均值为负，不代表四模式一致。'))
    for tech in TECHS:
        values=[]
        for country in countries:
            for pair in ['245/126','585/126']:
                gs=[pick(country,tech,pair,c) for c in climates]
                values.append([names_map[country],direction(gs[0]),
                    ' / '.join(fmt(r.layout_TWh,signed=True) for r in gs),
                    ' / '.join(fmt(r.offset_pct)+'%' if np.isfinite(r.offset_pct) else '不抵消' for r in gs),
                    ' / '.join(str(r.offset_models)+'/4' for r in gs)])
        parts.append('<h3>'+TECH_NAMES[tech]+'：布局贡献是否随气候改变方向</h3>')
        parts.append(table(['区域','部署方向','布局TWh：气候126/245/585',
                            '抵消比例：气候126/245/585','抵消模式数：气候126/245/585'],values))
    parts.append(para('对应图件：<a href="#scale_layout_climate126">固定气候126</a>、'
                      '<a href="#scale_layout_climate245">固定气候245</a>、'
                      '<a href="#scale_layout_climate585">固定气候585</a>。图中的归一化分母为参考正常电量，'
                      '不同于本节“相对于规模项”的抵消比例。'))

    parts.extend(['<h2 id="question-3">问题3：这种抵消是否伴随发电能力下降？</h2>',
        para('需要区分每MW正常发电能力H0与全年正常总电量G0。H0下降表示新增配置的单位容量产出较低；'
             '即使H0下降，更大的装机容量仍可能使G0增加。因而不能把H0下降直接写成国家总发电能力下降。'
             '下面仅在布局与规模确有抵消时判断H0是否下降，并保留同一模式中两个条件同时满足的支持数。')])
    parts.append(para(f'本样本中，{len(q)}组对照有{int(q.delta_G0_TWh.gt(0).sum())}组的'
        f'全年正常总电量集合均值随高容量部署增加，其中{int(q.G0_increase_models.eq(4).sum())}组获4/4模式支持。'
        '因此本次出现的发电能力代价是每MW正常产出下降，而不是正常总电量下降。'))
    r=pick('GLOBAL','wind','585/126')
    parts.append(para(f'全球风电585→126在气候126下，布局抵消与H0下降同时出现于{r.cost_models}/4模式：'
        f'H0平均变化{fmt(r.delta_H0_pct,signed=True)}%，但全年正常总电量仍增加{fmt(r.delta_G0_TWh)} TWh。'
        '因此该案例是“每MW产出降低的同时，布局项减少损失”，而不是扩张使正常总电量减少。'
        '这种共同出现只是给定配置间的权衡，不证明低产出是减损的必然原因。'))
    for tech,country,pair in [('wind','CHN','585/126'),('wind','BRA','585/126'),
                              ('solar','USA','245/126'),('solar','BRA','245/126')]:
        if country in countries:
            r=pick(country,tech,pair)
            parts.append(para(f'{names_map[country]}{TECH_NAMES[tech]}{direction(r)}在气候126下：'
                f'布局项{fmt(r.layout_TWh,signed=True)} TWh，H0变化{fmt(r.delta_H0_pct,signed=True)}%，'
                f'正常总电量变化{fmt(r.delta_G0_TWh,signed=True)} TWh；'
                f'抵消且H0下降{r.cost_models}/4模式，抵消且H0不下降{r.offset_without_H0_decline_models}/4模式。'))
    parts.append(para('比较上述案例可见，较低损失有时伴随单位容量产出下降，有时可以与产出改善同时出现。'
                      '全球光伏245→126是后一类：三种气候下的集合均值均抵消且H0提高。'
                      '应同时报告R、H0和ρ；相同正常发电目标下的损失取决于ρ，而不是R单独决定。'))
    costrows=[]
    for tech in TECHS:
        for country in countries:
            for pair in ['245/126','585/126']:
                gs=[pick(country,tech,pair,c) for c in climates]
                if not any(r.layout_TWh<0 for r in gs):
                    continue
                labels=[]
                for r in gs:
                    if r.layout_TWh>=0:
                        labels.append('均值不抵消')
                    else:
                        labels.append('抵消；H0'+fmt(r.delta_H0_pct,signed=True)+'%')
                costrows.append([names_map[country],TECH_NAMES[tech],direction(gs[0]),
                    *labels,' / '.join(str(r.cost_models)+'/4' for r in gs),
                    ' / '.join(str(r.offset_without_H0_decline_models)+'/4' for r in gs)])
    parts.append(table(['区域','技术','部署方向','气候126','气候245','气候585',
                        '抵消且H0下降：126/245/585','抵消且H0不下降：126/245/585'],costrows))
    for tech in TECHS:
        for pair in ['245/126','585/126']:
            g=q[q.tech.eq(tech)&q.pair.eq(pair)&q.country.isin(nationals)]
            cost=g.groupby('country').cost_models.sum()
            gain=g.groupby('country').offset_without_H0_decline_models.sum()
            if cost.eq(12).any() or gain.eq(12).any():
                parts.append(para(TECH_NAMES[tech]+'的'+pair.split('/')[0]+'→126对照中，'
                    '全部12个气候—模式组合都出现“抵消且H0下降”的国家：'+country_names(cost[cost.eq(12)].index)+
                    '；全部12组合都出现“抵消且H0不下降”的国家：'+country_names(gain[gain.eq(12)].index)+'。'))
    parts.append(para('本表保留至少一种气候集合均值有抵消的部署对。即使某一格写“均值不抵消”，'
                      '个别模式仍可能抵消，因此均值判定与模式计数可以不同。'
                      '详见<a href="#generation_tradeoff">发电能力权衡图</a>及后文相同正常发电目标的容量需求表。'))

    parts.extend(['<h2 id="question-4">问题4：同一气候下，哪种部署的单位装机损失或相对损失率更低？</h2>',
        para('必须固定气候后比较三个部署，并分别给R和ρ排序。R回答每MW损失多少；'
             'ρ回答每单位正常发电量损失多少。二者可能给出不同答案，因为R=H0×ρ（ρ取小数）。'
             '较低R可能只是正常发电能力较低，不能直接称为更高发电效率。')])
    parts.append(para('全球风电在三种气候下，R均由部署245最低，而ρ均由部署585最低，'
                      '且两项各自都有全部12组合支持。全球光伏的两项集合均值均由部署126最低，'
                      '但前两个气候下只有3/4模式支持，不能称为全模式一致。'))
    values=[]
    for tech in TECHS:
        for deploy in SSPS:
            g=metrics[(metrics.country=='GLOBAL')&(metrics.tech==tech)&
                      (metrics.climate_ssp=='ssp126')&(metrics.station_ssp==deploy)]
            a=g[['R','H0','rho_pct']].mean()
            values.append([TECH_NAMES[tech],deploy[3:],fmt(a.R),fmt(a.H0),fmt(a.rho_pct)+'%'])
    parts.append(table(['技术','部署（固定气候126）','R / MWh/MW/年','H0 / 小时/年','ρ'],values))
    for tech in TECHS:
        parts.append('<h3>'+TECH_NAMES[tech]+'：各国最低损失部署及支持程度</h3>')
        values=[]
        for country in countries:
            values.append([names_map[country],
                *[winner(country,tech,metric,c) for metric in ['R','rho_pct'] for c in climates]])
        parts.append(table(['区域','R：气候126','R：气候245','R：气候585',
                            'ρ：气候126','ρ：气候245','ρ：气候585'],values))
    parts.append(para('单元格为“最低部署（该指标均值；支持该部署的模式数/4）”，'
                      'R单位MWh/MW/年，ρ单位%。数值容差内允许并列。'
                      '例如集合均值最低部署只获1/4模式支持也可能发生：模式平均的排序与模式投票多数不是同一个统计量。'))
    for tech in TECHS:
        for metric,label in [('R','单位装机损失'),('rho_pct','相对损失率')]:
            ss=stable[(stable.tech==tech)&(stable.metric==metric)&stable.country.isin(nationals)]
            groups=[]
            for deploy in SSPS:
                cs=ss.loc[ss.consistent_ensemble.eq(deploy),'country']
                if len(cs):groups.append(deploy[3:]+'：'+country_names(cs))
            changed=ss.loc[ss.consistent_ensemble.eq(''),'country']
            parts.append(para(TECH_NAMES[tech]+'按'+label+'比较，三种气候下集合均值最低部署保持一致的国家分组为：'
                              +'；'.join(groups)+'。最低部署随气候切换的国家：'+country_names(changed)+'。'))
    parts.append(para('美国光伏对应126、中国和澳大利亚光伏对应585，体现不同国家可以偏向不同的部署配置；'
                      '这里的结论只针对当前候选配置和发电损失指标，不等于这些国家应选择相应的全球SSP。'
                      '<a href="#deployment_performance">固定气候部署表现图</a>展示其差值大小。')
                 if all(c in countries for c in ['USA','CHN','AUS']) else
                 para('这些排名只针对当前候选部署和发电损失指标，不等于国家应选择对应全球SSP。'))

    parts.extend(['<h2 id="question-5">问题5：这种表现是否跨气候情景保持一致？</h2>',
        para('答案分两层：第一层是三种气候下的集合均值最低部署相同；第二层更严格，'
             '要求该部署在3种气候×4个模式全部12组合都不劣于其他部署。'
             '第一层成立不保证第二层成立，也不代表差异达到统计显著性。')])
    countrows=[]
    for tech in TECHS:
        for metric,label in [('R','R'),('rho_pct','ρ')]:
            g=stable[stable.tech.eq(tech)&stable.metric.eq(metric)&stable.country.isin(nationals)]
            consistent=g[g.consistent_ensemble.ne('')]
            strict=g[g.strict_best.ne('')]
            countrows.append([TECH_NAMES[tech],label,f'{len(consistent)}/{len(nationals)}',
                f'{len(strict)}/{len(nationals)}',country_names(strict.country)])
    parts.append(table(['技术','指标','三气候均值最低部署一致的国家数','12组合一致的国家数','12组合一致的国家'],countrows))
    for tech in TECHS:
        for metric,label in [('R','单位装机损失'),('rho_pct','相对损失率')]:
            g=stable[stable.tech.eq(tech)&stable.metric.eq(metric)&stable.country.isin(nationals)]
            nmean=int(g.consistent_ensemble.ne('').sum())
            nstrict=int(g.strict_best.ne('').sum())
            parts.append(para(f'{TECH_NAMES[tech]}按{label}评价时，{len(nationals)}国中有{nmean}国'
                f'在三种气候下保持相同的均值最低部署，但只有{nstrict}国达到全部12组合一致。'
                '这一区别决定结果应表述为平均表现稳定，还是跨模式也一致的优势。'))
    values=[]
    for tech in TECHS:
        for country in countries:
            r=stable[(stable.country==country)&(stable.tech==tech)].set_index('metric')
            values.append([names_map[country],TECH_NAMES[tech],
                r.loc['R','consistent_ensemble'].replace('ssp','') or '随气候切换',
                r.loc['R','strict_best'].replace('ssp','') or '无',
                r.loc['rho_pct','consistent_ensemble'].replace('ssp','') or '随气候切换',
                r.loc['rho_pct','strict_best'].replace('ssp','') or '无'])
    parts.append(table(['区域','技术','R：三气候均值共同最低','R：12组合共同最低',
                        'ρ：三气候均值共同最低','ρ：12组合共同最低'],values))
    parts.append(para('因此应把“跨气候平均排序稳定”与“跨气候且跨模式稳定”分开写。'
                      '一些国家在三种气候下始终由同一配置取得最低均值，但模式之间仍有不同排序；'
                      '仅靠平均热图会高估结论的一致性。对于会发生排序切换的国家，'
                      '更合适的结论是部署表现依赖气候条件，而不是强行给出一条统一最优路径。'))
    parts.append(para('国家结论应连成完整证据链：增加多少容量→增加多少总损失和正常电量→'
                      '布局抵消多少→是否降低每MW正常产出→R与ρ分别偏向哪种配置→这些偏向在多少气候与模式中成立。'
                      '比较不同配置时，不能用总损失、单位装机损失或相对损失率其中一项代替其余问题。'))
    parts.append(para('本节源表：'
        f'<a href="{data_prefix}/five_questions_summary.csv">容量—损失—布局—发电能力汇总</a> · '
        f'<a href="{data_prefix}/five_questions_stability.csv">两层跨气候一致性</a>。'
        '源表保留所有区域、两技术、三气候与两部署对；'
        '<a href="#deployment_robustness">跨气候与模式排名图</a>提供图示对应。'))
    return parts


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--top-k', type=int, default=10)
    args = parser.parse_args()
    out = FOLDER / 'outputs' / f'top{args.top_k}'
    source = out / 'source_data'
    report_path = ROOT / 'paper_figures/analysis/analysis_20261019_005216' / f'country_deployment_tradeoffs_top{args.top_k}.html'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    plot_prefix = f'assets/images/country_deployment_tradeoffs_top{args.top_k}'
    data_prefix = f'assets/data/country_deployment_tradeoffs_top{args.top_k}'
    audit = json.loads((out / 'data_audit.json').read_text())
    if audit.get('status') != 'PASSED':
        raise ValueError('Data audit did not pass')
    names = ['selection', 'metrics_models', 'contrasts_models', 'wins_summary', 'robustness']
    data = {n: pd.read_csv(source / (n + '.csv')) for n in names}
    selection = data['selection'].sort_values('rank')
    metrics, contrasts = data['metrics_models'], data['contrasts_models']
    wins, robust = data['wins_summary'], data['robustness']
    names_map = {r.country: NAMES.get(r.country, r.country_name) for r in selection.itertuples()}
    overview_rows, findings = [], []
    for country in selection.country:
        for tech in TECHS:
            for ssp in SSPS:
                g = metrics[(metrics.country == country) & (metrics.tech == tech)
                            & (metrics.climate_ssp == ssp) & (metrics.station_ssp == ssp)]
                cols = ['C_GW', 'L_TWh', 'G0_TWh', 'H0', 'R', 'rho_pct']
                complete = (g.model.nunique() == len(MODELS)
                            and np.isfinite(g[cols]).all().all())
                avg = g[cols].mean() if complete else pd.Series(np.nan, index=cols)
                overview_rows.append([names_map[country], TECH_NAMES[tech], ssp[3:],
                                      *[fmt(avg[c]) for c in avg.index]])
    for (country, tech, climate, target), g in contrasts.groupby(
            ['country', 'tech', 'climate_ssp', 'target_ssp']):
        required = ['expansion_scale_TWh', 'expansion_layout_TWh',
                    'expansion_delta_L_TWh', 'expansion_delta_H0_pct',
                    'equal_generation_capacity_ratio', 'equal_generation_loss_TWh']
        valid = g[np.isfinite(g[required]).all(axis=1)]
        complete = valid.model.nunique() == len(MODELS)
        offsets = (valid.expansion_scale_TWh > 1e-10) & (valid.expansion_layout_TWh < -1e-10)
        cost = offsets & (valid.expansion_delta_H0_pct < -1e-8)
        scale, layout = valid.expansion_scale_TWh.mean(), valid.expansion_layout_TWh.mean()
        if not complete:
            category = '不可比'
        elif scale <= 1e-10:
            category = '规模项非正或容量相同'
        elif layout >= 0:
            category = '布局放大规模损失'
        elif -layout < scale:
            category = '布局部分抵消'
        else:
            category = '布局完全抵消'
        findings.append(dict(country=country, country_name=names_map.get(country, country),
                             tech=tech, climate_ssp=climate, pair=target[3:] + '/126',
                             high_capacity_ssp=g.high_capacity_ssp.iloc[0],
                             low_capacity_ssp=g.low_capacity_ssp.iloc[0],
                             scale_TWh=scale, layout_TWh=layout,
                             delta_L_TWh=valid.expansion_delta_L_TWh.mean(),
                             delta_H0_pct=valid.expansion_delta_H0_pct.mean(),
                             H0_minimum=valid.expansion_delta_H0_pct.min(),
                             H0_maximum=valid.expansion_delta_H0_pct.max(),
                             offset_models=int(offsets.sum()),
                             offset_with_lower_H0_models=int(cost.sum()),
                             n_models=int(valid.model.nunique()), category=category,
                             equal_generation_capacity_ratio=g.equal_generation_capacity_ratio.mean(),
                             equal_generation_loss_TWh=g.equal_generation_loss_TWh.mean(),
                             complete=complete))
        if not complete:
            for field in ['scale_TWh', 'layout_TWh', 'delta_L_TWh', 'delta_H0_pct',
                          'H0_minimum', 'H0_maximum', 'equal_generation_capacity_ratio',
                          'equal_generation_loss_TWh']:
                findings[-1][field] = np.nan
    findings = pd.DataFrame(findings)
    write_csv(source / 'country_findings.csv', findings)
    plot_names = [
        ('paired_path_overview', '1．各路径装机、总损失与正常发电量'),
        ('scale_layout_climate126', '2．规模与布局贡献：固定气候126'),
        ('scale_layout_climate245', '2．规模与布局贡献：固定气候245'),
        ('scale_layout_climate585', '2．规模与布局贡献：固定气候585'),
        ('generation_tradeoff', '3．抵消是否伴随每MW正常发电能力下降'),
        ('deployment_performance', '4．固定气候下的单位装机损失与相对损失率'),
        ('deployment_robustness', '5．跨气候与模式的部署排名稳健性')]
    image_dir = report_path.parent / plot_prefix
    data_dir = report_path.parent / data_prefix
    image_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for stem, _ in plot_names:
        shutil.copy2(out / (stem + '.png'), image_dir / (stem + '.png'))
    for path in sorted(source.glob('*.csv')):
        shutil.copy2(path, data_dir / path.name)
    shutil.copy2(out / 'data_audit.json', data_dir / 'data_audit.json')
    css = """body{max-width:1250px;margin:40px auto;padding:0 24px;color:#24313b;background:#fff;
font:16px/1.7 system-ui,sans-serif}h1,h2,h3{line-height:1.35;color:#193b55}h2{margin-top:42px}
p,li{max-width:1100px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #d8e0e4;padding:8px 10px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{background:#eff3f5}.table-wrap{overflow:auto}
img{width:100%;height:auto;border:1px solid #e3e7e9}a{color:#256088}code{background:#f2f5f6;
padding:2px 4px}aside{border-left:4px solid #91afc0;padding:8px 18px;background:#f6f8fa}
details{margin:18px 0}summary{font-weight:600;cursor:pointer}.small{font-size:14px;color:#52636e}"""
    body = [f'<h1>全球与装机Top-{args.top_k}国家：部署规模、布局与发电损失</h1>',
            '<p>小凯，本报告分析2050年容量快照在2050–2059年的年均结果。'
            '按SSP126的2050年风电＋光伏目录容量选出固定国家名单，风光分别分析。'
            'GLOBAL采用原全球汇总，包含Top-k以外地区，不是所选国家之和。</p>',
            '<aside>所有差值、比值、分解与排名先逐气候模式计算，再对四模式等权汇总。'
            '模式min–max不是置信区间；“最优”仅指指定发电损失指标在所比较部署中的最低值。'
            'SSP585部署查询标签来源于SSP5-6.0场站文件。净损失保留符号。</aside>',
            '<h2>分析对象</h2>']
    selected_rows = [[int(r.rank), names_map[r.country], r.country,
                      fmt(r.wind_capacity_mw / 1000), fmt(r.solar_capacity_mw / 1000),
                      fmt(r.capacity_mw / 1000)] for r in selection.itertuples()]
    body.append(table(['排名', '区域', '代码', '风电/GW', '光伏/GW', '合计/GW'], selected_rows))
    body.extend(question_analysis(selection, metrics, contrasts, findings, wins, robust, names_map,
                                  source, data_dir, data_prefix))
    body.extend(['<h2>五个问题的计算口径</h2><ol>',
        '<li><b>装机规模与总损失：</b>配对路径图展示气候与部署一起变化的结果；不能将这些差异解释为单独的规模效应。</li>',
        '<li><b>布局抵消：</b>固定气候比较部署245−126、585−126，采用 '
        'ΔL = ΔC × 平均R + 平均C × ΔR。两项分别为规模和布局贡献，交互已分摊。'
        '贡献图按同模式、同气候、部署126的全年正常电量归一为百分数，绝对TWh保留源表。</li>',
        '<li><b>发电能力代价：</b>为准确描述装机增加，另将每对部署定向为“高容量−低容量”。'
        '检查正规模贡献是否伴随负布局贡献，并检查H0=全年正常电量/容量是否下降。'
        '这里是不同部署之间的比较，不是同一部署的时间增长。</li>',
        '<li><b>固定气候的部署表现：</b>分别比较R=L/C和ρ=100L/G0，不能用时刻相对损失百分比的均值替代ρ。</li>',
        '<li><b>稳健性：</b>每个气候下标出四模式均值最低的部署及0–4模式支持数；'
        '严格跨情景优势要求同一部署在全部3气候×4模式中都不劣于另外两种部署。'
        '数值容差内允许并列，缺组合标记不可比，不能将12组视为12个独立样本。</li></ol>',
        '<p>共同正常发电目标取同一国家、技术、模式和气候下部署126的G0。'
        '容量比例C*/C126=H0_126/H0_target；损失L*=G0_126×ρ_target（ρ取小数）。'
        '这是假设空间份额不变且容量线性缩放的标准化比较，未验证土地、电网或成本可行性；'
        'G0是模型定义的正常发电量，不是实际供电保证。</p>'])
    complete_findings = findings[findings.complete.eq(True)]
    categories = complete_findings.category.value_counts()
    partial = int(categories.get('布局部分抵消', 0))
    full = int(categories.get('布局完全抵消', 0))
    amplify = int(categories.get('布局放大规模损失', 0))
    body.extend(['<h2>主要结果</h2>',
                 f'<p>在{len(complete_findings)}个完整的区域×技术×气候×部署对比中，'
                 f'{partial}组的布局部分抵消规模项，{full}组完全抵消，'
                 f'{amplify}组的布局与规模项同向增加损失。'
                 '这是集合均值的描述性计数，各组并非独立样本，也没有按国家等权推断全球结果。</p>'])
    rows = []
    for tech in TECHS:
        g = complete_findings[(complete_findings.country == 'GLOBAL')
                             & (complete_findings.tech == tech)
                             & (complete_findings.climate_ssp == 'ssp126')
                             & (complete_findings.pair == '585/126')]
        for r in g.itertuples():
            rows.append([TECH_NAMES[tech], r.low_capacity_ssp[3:] + ' → ' + r.high_capacity_ssp[3:],
                         fmt(r.scale_TWh, signed=True), fmt(r.layout_TWh, signed=True),
                         fmt(r.delta_L_TWh, signed=True), fmt(r.delta_H0_pct, signed=True) + '%',
                         f'{r.offset_models}/{r.n_models}',
                         f'{r.offset_with_lower_H0_models}/{r.n_models}'])
    body.append('<p>全球例子：固定气候126，比较部署585与126，并按低容量→高容量定向。'
                '风电中布局降低损失可伴随每MW正常发电能力下降；'
                '光伏须结合模式支持数读取，而非仅据均值称一致抵消。</p>')
    body.append(table(['技术', '低→高容量部署', '规模/TWh', '布局/TWh', '净差/TWh',
                       'H0变化', '抵消模式数', '抵消且H0下降'], rows))
    body.append('<p>下表给出每个区域跨全部3气候×4模式都最低的部署。'
                '“无全组合一致最优”不代表平均表现相同，而表示严格稳健条件未满足。'
                '全球风电中R与相对损失率的排名不同，因此两个指标需要同时报告。</p>')
    rows = [[names_map[c], *[robust_label(robust, c, t, m)
                             for t in TECHS for m in ['R', 'rho_pct']]]
            for c in selection.country]
    body.append(table(['区域', '风电：R', '风电：相对损失率',
                       '光伏：R', '光伏：相对损失率'], rows))
    body.append('<p>这些比较评价给定部署配置在指定气候下的发电损失表现。'
                '更低的总损失可能来自更小的装机规模，更低的单位装机损失也可能伴随更低的正常发电能力；'
                '因此不应直接将单个指标最低解释为某国应选择某条SSP路径。</p>')
    body.append('<h2>图件导航</h2><ul>')
    for stem, title in plot_names:
        body.append(f'<li><a href="#{stem}">{title}</a></li>')
    body.append('</ul>')
    for stem, title in plot_names:
        body.append(f'<h2 id="{stem}">{title}</h2><a href="{plot_prefix}/{stem}.png"><img src="{plot_prefix}/{stem}.png" alt="{title}"></a>')
    body.append('<h2>逐国分析</h2><p>以下规模—布局例子固定气候126；三个气候的完整结果均保留在图件与CSV。'
                '高容量−低容量的方向与图中固定的245−126、585−126方向可能相反。'
                '“抵消且H0下降”列报告同时满足这两个条件的模式数。</p>')
    for country in selection.country:
        body.append(f'<h3>{html.escape(names_map[country])}（{country}）</h3>')
        rows = []
        for tech in TECHS:
            g = findings[(findings.country == country) & (findings.tech == tech)
                         & (findings.climate_ssp == 'ssp126')]
            for r in g.itertuples():
                rows.append([TECH_NAMES[tech], str(r.low_capacity_ssp)[3:] + ' → ' + str(r.high_capacity_ssp)[3:],
                             fmt(r.scale_TWh, signed=True), fmt(r.layout_TWh, signed=True),
                             fmt(r.delta_L_TWh, signed=True), r.category,
                             fmt(r.delta_H0_pct, signed=True) + '%',
                             f'{r.offset_models}/{r.n_models}', f'{r.offset_with_lower_H0_models}/{r.n_models}'])
        body.append(table(['技术', '低→高容量部署', '规模/TWh', '布局/TWh', '净差/TWh',
                           '均值关系', 'H0变化', '抵消模式数', '抵消且H0下降'], rows))
        rows = []
        for tech in TECHS:
            for metric, label in [('R', '单位装机损失'), ('rho_pct', '相对损失率')]:
                rows.append([TECH_NAMES[tech], label, *[best_label(wins, country, tech, metric, c) for c in SSPS],
                             robust_label(robust, country, tech, metric)])
        body.append(table(['技术', '指标', '气候126', '气候245', '气候585', '全部12组一致最低部署'], rows))
        rows = []
        for tech in TECHS:
            g = findings[(findings.country == country) & (findings.tech == tech)
                         & (findings.climate_ssp == 'ssp126')]
            for r in g.itertuples():
                rows.append([TECH_NAMES[tech], r.pair, fmt(100*r.equal_generation_capacity_ratio) + '%',
                             fmt(r.equal_generation_loss_TWh)])
        body.append('<details><summary>相同正常发电目标下的容量需求与损失（气候126）</summary>'
                    + table(['技术', '目标/参考部署', '容量需求/参考容量', '对应损失/TWh'], rows) + '</details>')
    body.append('<h2>配对路径的绝对量</h2>')
    body.append(table(['区域', '技术', '配对路径', '容量/GW', '净损失/TWh', '正常电量/TWh',
                       'H0/小时', 'R/(MWh/MW)', 'ρ/%'], overview_rows))
    body.append('<p><a href="report.html#country-tradeoffs">返回综合报告国家分析章节</a></p>')
    body.append('<h2>可追溯性与解释范围</h2><ul>'
                '<li>源表：' + ' · '.join(f'<a href="{data_prefix}/{path.name}">{path.name}</a>' for path in sorted(source.glob('*.csv'))) + '；'
                f'<a href="{data_prefix}/data_audit.json">data_audit.json</a>记录输入哈希、覆盖和恒等式核验。</li>'
                '<li>排名采用完整目录容量，损失指标采用每种部署内跨气候、模式和十年的共同有效容量；两者不混用。</li>'
                '<li>年度共同有效支持不能证明三小时有效时间完全相同。</li>'
                '<li>中国沿用已合并China与Taiwan的CHN统计单元。</li>'
                '<li>年均净损失不等于停电风险；不据此给出国家最优SSP或选址优化收益。</li></ul>'
                '<p>希望对你有帮助，小凯！</p>')
    result = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    result += '<title>国家部署与损失分析</title><style>' + css + '</style><body>' + '\n'.join(body) + '</body></html>'
    report_path.write_text(result, encoding='utf-8')
    write_json(out / 'report_metadata.json', {
        'created_utc': datetime.now(timezone.utc).isoformat(), 'top_k': args.top_k,
        'source_hashes': {name: digest(source / (name + '.csv')) for name in names},
        'report_path': str(report_path.relative_to(ROOT)), 'report_sha256': digest(report_path), 'script_sha256': digest(Path(__file__)),
        'profile_count': len(selection), 'findings_rows': len(findings),
        'question_sections': 5, 'question_source_hashes': {name: digest(source / (name + '.csv'))
            for name in ['five_questions_summary', 'five_questions_stability']}})
    print(json.dumps({'report': str(report_path), 'profiles': len(selection),
                      'findings_rows': len(findings)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
