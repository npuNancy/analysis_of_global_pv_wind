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
        'profile_count': len(selection), 'findings_rows': len(findings)})
    print(json.dumps({'report': str(report_path), 'profiles': len(selection),
                      'findings_rows': len(findings)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
