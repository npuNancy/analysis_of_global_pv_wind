"""Plot annual/decadal suitable-grid exposure and spatial-weight sensitivity."""
import json
import shutil
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from paper_figures.common.plotting import configure, save_png
from paper_figures.config import MODELS, SSPS, SSP_COLORS, TECHS, EVENTS
from paper_figures.supplementary.suitable_grid_extreme.prepare import OUT, SOURCE, digest

LABELS = dict(zip(SSPS, ('SSP1-2.6', 'SSP2-4.5', 'SSP5-8.5')))


def panel(ax, data, tech, xcol, letter, legend=False):
    for ssp, style in zip(SSPS, ('-', '--', '-.')):
        p = data[data.tech.eq(tech) & data.climate_ssp.eq(ssp)].pivot(index=xcol, columns='model', values='exposure_days').sort_index()
        if set(p.columns) != set(MODELS) or not np.isfinite(p.values).all():
            raise ValueError('Incomplete model ensemble')
        x = p.index.to_numpy()
        ax.fill_between(x, p.min(axis=1), p.max(axis=1), color=SSP_COLORS[ssp], alpha=.13, linewidth=0)
        ax.plot(x, p.mean(axis=1), style, color=SSP_COLORS[ssp], lw=1.3,
                marker='o' if xcol == 'snapshot' else None, ms=3, label=LABELS[ssp])
    title = 'Wind' if tech == 'wind' else 'Solar'
    title += ' · area weighted' if data.weighting.iloc[0] == 'area' else ' · equal grid weights'
    ax.set_title(title, loc='left')
    ax.text(-.15, 1.05, letter, transform=ax.transAxes, weight='bold', fontsize=9)
    ax.set_ylabel('Extreme-event exposure (day yr⁻¹)')
    if xcol == 'snapshot':
        ax.set_xlabel('Decade'); ax.set_xticks([2030, 2040, 2050], ['2030s', '2040s', '2050s'])
    else:
        ax.set_xlabel('Year'); ax.set_xticks([2030, 2040, 2050, 2059])
        for boundary in (2039.5, 2049.5):
            ax.axvline(boundary, color='.75', ls=':', lw=.6)
    ax.grid(axis='y', color='.9', lw=.4)
    if legend:
        ax.legend(fontsize=6, loc='upper right' if tech == 'wind' else 'lower right')


def main():
    audit = json.loads((OUT / 'validation.json').read_text())
    if audit['status'] != 'PASSED':
        raise ValueError('Preparation did not pass validation')
    comparison = pd.read_csv(SOURCE / 'weighting_comparison.csv')
    sensitivity = []
    for (tech, ssp), group in comparison.groupby(['tech', 'climate_ssp']):
        g = group.set_index('snapshot')
        for first, last in ((2030, 2040), (2040, 2050), (2030, 2050)):
            equal = float(g.loc[last, 'equal'] - g.loc[first, 'equal'])
            area = float(g.loc[last, 'area'] - g.loc[first, 'area'])
            sensitivity.append(dict(tech=tech, climate_ssp=ssp, first=first, last=last,
                                    equal_change_days=equal, area_change_days=area,
                                    same_direction=bool(np.sign(equal) == np.sign(area))))
    ranking = []
    for (tech, snap), group in comparison.groupby(['tech', 'snapshot']):
        equal_order = group.sort_values('equal').climate_ssp.tolist()
        area_order = group.sort_values('area').climate_ssp.tolist()
        ranking.append(dict(tech=tech, snapshot=int(snap), equal_ascending=equal_order,
                            area_ascending=area_order, same_ranking=equal_order == area_order))
    pd.DataFrame(sensitivity).to_csv(SOURCE / 'weighting_changes.csv', index=False)
    audit.update(weighting_interval_checks=sensitivity, weighting_ssp_rankings=ranking)
    (OUT / 'validation.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    configure(); outputs = []
    for name, xcol in [('decadal', 'snapshot'), ('annual', 'year')]:
        data = pd.read_csv(SOURCE / (name + '.csv'))
        # Supplementary event tables retain individual models and overlap correction.
        data[data.event.ne('all') & data.weighting.eq('area')].to_csv(SOURCE / ('single_events_' + name + '.csv'), index=False)
        for weighting in ('area', 'equal'):
            selected = data[data.event.eq('all') & data.weighting.eq(weighting)]
            # Same scale for technology comparison and the weighting sensitivity.
            union = data[data.event.eq('all')]
            low, high = union.exposure_days.min(), union.exposure_days.max()
            pad = (high - low) * .08
            ylim = (max(0, low - pad), high + pad)
            fig, axes = plt.subplots(1, 2, figsize=(183 / 25.4, 83 / 25.4))
            for ax, tech, letter in zip(axes, TECHS, 'ab'):
                panel(ax, selected, tech, xcol, letter); ax.set_ylim(*ylim)
            handles, labels = axes[0].get_legend_handles_labels()
            fig.legend(handles, labels, loc='upper center', ncol=3, fontsize=7, bbox_to_anchor=(.5, 1))
            fig.tight_layout(pad=1.2, w_pad=2, rect=(0, 0, 1, .91))
            base = 'suitable_grid_extreme_' + name + ('_equal' if weighting == 'equal' else '')
            save_png(fig, OUT / (base + '.png')); plt.close(fig); outputs.append(base + '.png')
            for tech, letter in zip(TECHS, 'ab'):
                fig, ax = plt.subplots(figsize=(95 / 25.4, 83 / 25.4))
                panel(ax, selected, tech, xcol, letter, legend=True); ax.set_ylim(*ylim)
                fig.tight_layout(pad=1.2)
                file = base + '_' + letter + '.png'
                save_png(fig, OUT / file); plt.close(fig); outputs.append(file)
    for name in ('decadal', 'annual'):
        for suffix in ('', '_a', '_b'):
            primary = 'suitable_grid_extreme_' + name + suffix + '.png'
            for alias in ('fig_suitable_grid_extreme_' + name + suffix + '.png',
                          'suitable_grid_extreme_' + name + '_area' + suffix + '.png'):
                shutil.copyfile(OUT / primary, OUT / alias)
                outputs.append(alias)
    meta = json.loads((OUT / 'metadata.json').read_text())
    meta.update(outputs=outputs, formats='PNG only, 600 dpi', figure_size_mm=[183, 83],
                plot_code_sha256=digest(Path(__file__)),
                output_sha256={f: digest(OUT / f) for f in outputs},
                source_data_sha256={p.name: digest(p) for p in SOURCE.glob('*.csv')})
    (OUT / 'metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = audit['catalogue']
    caption = f'''全球适宜网格极端事件暴露的 SSP 变化。a，风电；b，光伏。主图为2030–2039、2040–2049、2050–2059十年年均暴露；年度补充图显示2030–2059。暴露为全部适用事件的时间并集累计小时除以24（day yr⁻¹），不是发生事件的日历天数。每一模式先在固定共同适宜格点上按球面网格面积加权平均，再对CANESM5、MPI-ESM1-2-HR、MRI-ESM2-0、BCC-CSM2-MR四模式等权平均；阴影为四模式最小值至最大值，不是置信区间。全部面板采用相同纵轴尺度，等权及面积加权版本保持同尺度。

清单来自已指定适宜网格映射，不重新筛选。风电共同有效格点 {counts['wind']['common_cells']:,}/{counts['wind']['catalogue_cells']:,}（{counts['wind']['common_coverage_pct']:.4f}%），光伏 {counts['solar']['common_cells']:,}/{counts['solar']['catalogue_cells']:,}（{counts['solar']['common_coverage_pct']:.4f}%）。共同格点要求所有模式、SSP、30年及适用事件均有效，年度有效时间至少99%；沿用模型原生日历，不把缺测填零，不按有效时间外推全年。低资源沿用各模式各SSP自己的2015–2024基线。

主图采用球面网格面积加权，分母为共同有效适宜网格的面积之和；这是入选网格面积，不代表网格内部实际可建设面积。文件名带_equal者为等权网格敏感性对照，带_area者与主图相同。单事件补充表single_events_annual.csv和single_events_decadal.csv采用面积加权，保留全部适用事件及overlap_correction（并集减单事件之和）；该校正为重复暴露核算，非物理因果归因，且不包含独立事件交集时间信息。事件之和加校正闭合到并集。数值、范围、权重敏感性及完整覆盖率见source_data和validation.json。
'''
    (OUT / 'caption.md').write_text(caption, encoding='utf-8')
    primary = comparison[['tech', 'climate_ssp', 'snapshot', 'area']]
    lines = ['# 全球适宜网格面积加权暴露', '',
             '主结果按共同有效网格面积加权；等权网格结果为敏感性对照。单位 day yr⁻¹。',
             '', '|技术|SSP|2030s|2040s|2050s|',
             '|---|---|---:|---:|---:|']
    for (tech, ssp), group in primary.groupby(['tech', 'climate_ssp']):
        values = group.set_index('snapshot').area
        lines.append(f'|{tech}|{ssp}|{values[2030]:.6f}|{values[2040]:.6f}|{values[2050]:.6f}|')
    lines += ['', '各年代及相邻年代变化的权重敏感性详见 validation.json。',
              '面积加权的年度与年代主结果见 annual_primary.csv 和 decadal_primary.csv；',
              'annual.csv 和 decadal.csv 保留两种权重，使用时必须按 weighting 筛选。',
              '单事件主表采用面积加权。图中阴影为四模式范围，不是置信区间。',
              '本次数据准备作业：' + str(audit.get('preparation_job_id')) + '。']
    (OUT / 'results.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(outputs))


if __name__ == '__main__':
    main()
