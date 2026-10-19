"""Global and country deployment trade-offs from audited 2050s summary tables."""
import argparse
from datetime import datetime, timezone
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator, LogLocator
import numpy as np
import pandas as pd

from paper_figures.config import ROOT, SSPS, TECHS, SSP_COLORS
from paper_figures.common.io import digest, write_json
from paper_figures.common.plotting import configure, export_panel_png

FOLDER = ROOT / 'paper_figures/main/country_deployment_tradeoffs'
WIDTH = 183 / 25.4
TARGETS = ('ssp245', 'ssp585')
CLIMATES = ('ssp126', 'ssp245', 'ssp585')
TECH_LABELS = {'wind': 'Wind', 'solar': 'Solar'}
DIVERGING = LinearSegmentedColormap.from_list('difference', ['#487A96', '#F8F8F6', '#AF5146'])
DIVERGING.set_bad('#E5E5E5')
SCALE_COLOR, LAYOUT_COLOR = '#487A96', '#D39A54'
SSP_MARKERS = {'ssp126': 'o', 'ssp245': 's', 'ssp585': '^'}
METRICS = {'C_GW': 'Capacity (GW)', 'L_TWh': 'Net loss (TWh yr⁻¹)',
           'G0_TWh': 'Normal generation (TWh yr⁻¹)'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def truth(series):
    return series.astype(str).str.lower().eq('true')


def add_axes(fig, x, y, width, height):
    fw, fh = fig.get_size_inches()
    return fig.add_axes([x / fw, y / fh, width / fw, height / fh])


def text_inches(fig, x, y, value, **kwargs):
    fw, fh = fig.get_size_inches()
    return fig.text(x / fw, y / fh, value, **kwargs)


def country_axis(ax, countries, labels, show=True):
    n = len(countries)
    ax.set_yticks(np.arange(n), labels if show else [])
    ax.set_ylim(n - .5, -.5)
    ax.tick_params(axis='y', length=0, pad=4)
    ax.axhline(.5, color='#8D9297', lw=.55, zorder=6)
    for label, country in zip(ax.get_yticklabels(), countries):
        if country == 'GLOBAL':
            label.set_fontweight('bold')


def export(fig, stem, out, products, groups, details):
    info = export_panel_png(fig, out / f'{stem}.png', close=False)
    info.update(is_group=False, stem=stem, details=details)
    products.append(info)
    for index, (suffix, bounds) in enumerate(groups):
        info = export_panel_png(fig, out / f'{stem}_{suffix}.png', bounds=bounds,
                                close=index == len(groups) - 1)
        info.update(is_group=True, stem=stem, panels=suffix, details=details)
        products.append(info)
    if not groups:
        plt.close(fig)


def series(table, countries, **selectors):
    selected = table
    for name, value in selectors.items():
        selected = selected.loc[selected[name].eq(value)]
    require(not selected.country.duplicated().any(), f'Duplicate plotting row: {selectors}')
    return selected.set_index('country').reindex(countries)


def finite_limit(values, minimum=.1):
    values = np.asarray(values, dtype=float)
    return max(minimum, float(np.nanmax(np.abs(values))))


def overview(tables, countries, labels, out, products):
    table = tables['metrics_summary']
    table = table.loc[table.climate_ssp.eq(table.station_ssp)]
    n = len(countries)
    rh = .205 * n + 1.03
    fig = plt.figure(figsize=(WIDTH, 2 * rh), facecolor='white')
    xstarts = [.60, 2.85, 5.10]
    colors = [SSP_COLORS[s] for s in CLIMATES]
    limits = {}
    for metric in METRICS:
        part = table.loc[table.metric.eq(metric)]
        lo, hi = part.minimum.min(), part.maximum.max()
        limits[metric] = ((lo / 1.5, hi * 1.5), 'log') if lo > 0 else ((lo - .05*(hi-lo), hi + .05*(hi-lo)), 'linear')
    for row, tech in enumerate(TECHS):
        b = (1 - row) * rh
        text_inches(fig, .20, b + rh - .18,
                    f'{TECH_LABELS[tech]} | paired pathways | 2050–2059', fontsize=7.5, weight='bold')
        for col, metric in enumerate(METRICS):
            ax = add_axes(fig, xstarts[col], b + .58, 1.84, rh - 1.01)
            for j, ssp in enumerate(CLIMATES):
                values = series(table, countries, tech=tech, climate_ssp=ssp, metric=metric)
                y = np.arange(n) + (j - 1) * .23
                ax.hlines(y, values.minimum, values.maximum, color=colors[j], lw=.7)
                ax.scatter(values['mean'], y, marker=SSP_MARKERS[ssp], s=11,
                           color=colors[j], edgecolor='white', linewidth=.25, zorder=3)
            country_axis(ax, countries, labels, show=col == 0)
            ax.set_xscale(limits[metric][1])
            ax.set_xlim(*limits[metric][0])
            ax.set_xlabel(METRICS[metric] + ('; log scale' if limits[metric][1] == 'log' else ''), fontsize=6)
            if limits[metric][1] == 'log':
                ticks = LogLocator(base=10, numticks=5).tick_values(*limits[metric][0])
                ax.set_xticks(ticks[(ticks >= limits[metric][0][0]) & (ticks <= limits[metric][0][1])])
                ax.minorticks_off()
            else:
                ax.xaxis.set_major_locator(MaxNLocator(nbins=4, prune='both'))
            ax.grid(axis='x', color='#DEDEDE', lw=.35)
            ax.set_axisbelow(True)
            ax.set_title('abcdef'[row * 3 + col], loc='left', fontsize=8, weight='bold', pad=4)
        handles = [Line2D([], [], marker=SSP_MARKERS[s], lw=.7, color=SSP_COLORS[s],
                          markersize=3, label=s.upper()) for s in CLIMATES]
        fig.legend(handles=handles, ncol=3, loc='center',
                   bbox_to_anchor=(.43, (b + .13) / (2 * rh)), fontsize=6, handlelength=1.3,
                   columnspacing=1.4)
        text_inches(fig, WIDTH - .18, b + .13, 'Mean; range: 4 models', ha='right', va='center', fontsize=5.8)
    export(fig, 'paired_path_overview', out, products,
           [('abc', [0, .5, 1, 1]), ('def', [0, 0, 1, .5])],
           {'axes': limits, 'capacity': 'effective capacity on common valid support',
            'summary': 'four-model mean and min-max; capacity identical across models'})


def contribution_limit(table, countries):
    chosen = table.loc[table.country.isin(countries)]
    keys = ['country', 'tech', 'climate_ssp', 'target_ssp']
    pivot = chosen.pivot(index=keys, columns='metric', values='mean')
    parts = pivot[['scale_refG0_pct', 'layout_refG0_pct']].to_numpy()
    low = np.minimum(parts, 0).sum(axis=1).min()
    high = np.maximum(parts, 0).sum(axis=1).max()
    net = chosen.loc[chosen.metric.eq('delta_L_refG0_pct')]
    low = min(low, net.minimum.min(), 0)
    high = max(high, net.maximum.max(), 0)
    span = max(high - low, .1)
    return float(low - .055 * span), float(high + .055 * span)


def decompositions(tables, countries, labels, out, products):
    table = tables['contrasts_summary']
    limits = contribution_limit(table, countries)
    rh = .205 * len(countries) + 1.16
    for climate in CLIMATES:
        fig = plt.figure(figsize=(WIDTH, rh * 2), facecolor='white')
        for row, target in enumerate(TARGETS):
            b = (1 - row) * rh
            text_inches(fig, .20, b + rh - .16,
                        f'Climate {climate[3:]} | deployment {target[3:]} − 126 | 2050–2059',
                        fontsize=7.2, weight='bold')
            for col, tech in enumerate(TECHS):
                ax = add_axes(fig, .64 + col * 3.56, b + .70, 2.68, rh - 1.22)
                pos, neg = np.zeros(len(countries)), np.zeros(len(countries))
                for metric, color in [('scale_refG0_pct', SCALE_COLOR), ('layout_refG0_pct', LAYOUT_COLOR)]:
                    v = series(table, countries, climate_ssp=climate, target_ssp=target,
                               tech=tech, metric=metric)['mean'].to_numpy(float)
                    left = np.where(v >= 0, pos, neg)
                    ax.barh(np.arange(len(countries)), v, left=left, height=.52,
                            color=color, edgecolor='white', linewidth=.25, zorder=3)
                    pos += np.where(v >= 0, v, 0)
                    neg += np.where(v < 0, v, 0)
                net = series(table, countries, climate_ssp=climate, target_ssp=target,
                             tech=tech, metric='delta_L_refG0_pct')
                ax.hlines(np.arange(len(countries)), net.minimum, net.maximum, color='#30363C', lw=.6, zorder=5)
                ax.scatter(net['mean'], np.arange(len(countries)), marker='D', s=10,
                           color='#30363C', edgecolor='white', linewidth=.3, zorder=6)
                country_axis(ax, countries, labels)
                ax.axvline(0, color='#757C81', lw=.6, zorder=4)
                ax.set_xlim(*limits)
                ax.xaxis.set_major_locator(MaxNLocator(nbins=5, prune='both'))
                ax.grid(axis='x', color='#E0E0E0', lw=.35)
                ax.set_axisbelow(True)
                ax.set_xlabel('Contribution / reference normal generation (%)', fontsize=5.8)
                ax.set_title('abcd'[row * 2 + col] + '  ' + TECH_LABELS[tech], loc='left',
                             fontsize=7, weight='bold', pad=4)
            handles = [Patch(facecolor=SCALE_COLOR, label='Scale'),
                       Patch(facecolor=LAYOUT_COLOR, label='Layout'),
                       Line2D([], [], color='#30363C', lw=.7, marker='D', markersize=3, label='Net; model min–max')]
            fig.legend(handles=handles, ncol=3, loc='center',
                       bbox_to_anchor=(.5, (b + .23) / (2 * rh)), fontsize=6,
                       handlelength=1.3, columnspacing=1.7)
            text_inches(fig, WIDTH / 2, b + .065,
                        'Reference: deployment 126, same climate and model. Model-level normalization, then ensemble mean.',
                        ha='center', fontsize=5.6)
        export(fig, 'scale_layout_climate' + climate[3:], out, products,
               [('ab', [0, .5, 1, 1]), ('cd', [0, 0, 1, .5])],
               {'xlim': limits, 'normalization': '100 * model contribution / model climate-specific deployment-126 normal annual generation',
                'uncertainty': 'net min-max of four normalized model contributions', 'climate': climate})


def matrix(table, countries, metric, tech, value='mean'):
    array = np.full((len(countries), 6), np.nan)
    for j, (climate, target) in enumerate((c, t) for c in CLIMATES for t in TARGETS):
        array[:, j] = series(table, countries, tech=tech, climate_ssp=climate,
                             target_ssp=target, metric=metric)[value].to_numpy(float)
    return array


def heatmap(ax, values, countries, labels, limit, marked=None, fmt='{:+.1f}', xlabel='Deployment difference'):
    im = ax.imshow(np.ma.masked_invalid(values), cmap=DIVERGING,
                   norm=Normalize(-limit, limit), aspect='auto', interpolation='nearest')
    country_axis(ax, countries, labels)
    ax.set_xticks(np.arange(6), ['245−126', '585−126'] * 3)
    ax.tick_params(axis='x', length=0, labelsize=5.6)
    ax.set_xlabel(xlabel, fontsize=5.8, labelpad=3)
    for j, climate in enumerate(CLIMATES):
        ax.text(2 * j + .5, 1.03, 'Climate ' + climate[3:], transform=ax.get_xaxis_transform(),
                ha='center', va='bottom', fontsize=6)
    for boundary in [1.5, 3.5]:
        ax.axvline(boundary, color='white', lw=1)
    for i in range(len(countries)):
        for j in range(6):
            value = values[i, j]
            color = 'white' if np.isfinite(value) and abs(value) > .65 * limit else '#252A2E'
            threshold = .005 if '.2f' in fmt else .05
            label = fmt.format(0. if abs(value) < threshold else value) if np.isfinite(value) else 'NA'
            ax.text(j, i, label, ha='center', va='center', fontsize=5.7, color=color)
            if marked is not None and marked[i, j]:
                ax.plot(j + .35, i - .28, marker='o', color=color, markersize=1.9, clip_on=True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return im


def generation_tradeoff(tables, countries, labels, out, products):
    table, models = tables['contrasts_summary'], tables['contrasts_models']
    fields = table.loc[table.metric.eq('expansion_delta_H0_pct')]
    limit = finite_limit(fields['mean'])
    n = len(countries)
    h = .215 * n + 1.68
    fig = plt.figure(figsize=(WIDTH, h), facecolor='white')
    for col, tech in enumerate(TECHS):
        left = col * (WIDTH / 2)
        text_inches(fig, left + .18, h - .18,
                    'ab'[col] + '  ' + TECH_LABELS[tech] + ' | generation trade-off | 2050s',
                    fontsize=7.1, weight='bold')
        ax = add_axes(fig, left + .60, .99, 2.80, h - 1.66)
        values = matrix(table, countries, 'expansion_delta_H0_pct', tech)
        marked = np.zeros_like(values, dtype=bool)
        for j, (climate, target) in enumerate((c, t) for c in CLIMATES for t in TARGETS):
            part = models.loc[models.tech.eq(tech) & models.climate_ssp.eq(climate) & models.target_ssp.eq(target)]
            for i, country in enumerate(countries):
                cells = part.loc[part.country.eq(country)]
                marked[i, j] = len(cells) == 4 and bool((cells.expansion_scale_TWh.gt(0) & cells.expansion_layout_TWh.lt(0)).all())
        im = heatmap(ax, values, countries, labels, limit, marked,
                     xlabel='Deployment pair (higher minus lower capacity)')
        ax.set_xticklabels(['245/126', '585/126'] * 3)
        cbax = add_axes(fig, left + .76, .58, 2.40, .095)
        cb = fig.colorbar(im, cax=cbax, orientation='horizontal')
        cb.ax.tick_params(labelsize=5.5, length=2, pad=1)
        cb.set_label('Change in normal generation per MW (%)', fontsize=5.8, labelpad=2)
        text_inches(fig, left + WIDTH / 4, .16,
                    'Corner dot: layout offsets scale in all 4 models.\nNegative value + dot: offset with lower generation per MW.',
                    ha='center', fontsize=5.4, linespacing=1.6)
    export(fig, 'generation_tradeoff', out, products,
           [('a', [0, 0, .5, 1]), ('b', [.5, 0, 1, 1])],
           {'color_limits': [-limit, limit], 'metric': 'expansion_delta_H0_pct',
            'direction': 'higher-capacity deployment minus lower-capacity deployment within each pair',
            'corner_dot': 'all four models expansion_scale_TWh > 0 and expansion_layout_TWh < 0'})


def performance(tables, countries, labels, out, products):
    table = tables['contrasts_summary']
    n = len(countries)
    rh = .205 * n + 1.51
    fig = plt.figure(figsize=(WIDTH, 2 * rh), facecolor='white')
    definitions = [('delta_R', 'Unit-capacity net loss', 'Difference in net loss (MWh MW⁻¹ yr⁻¹)'),
                   ('delta_rho_pp', 'Annual relative net loss', 'Difference in loss rate (percentage points)')]
    details = {}
    for row, (metric, title, unit) in enumerate(definitions):
        b = (1 - row) * rh
        limit = finite_limit(table.loc[table.metric.eq(metric), 'mean'], minimum=.001)
        details[metric] = [-limit, limit]
        text_inches(fig, .20, b + rh - .17, title + ' | deployment contrasts | 2050–2059',
                    fontsize=7.2, weight='bold')
        for col, tech in enumerate(TECHS):
            ax = add_axes(fig, .60 + col * 3.61, b + 1.02, 2.80, rh - 1.75)
            values = matrix(table, countries, metric, tech)
            marked = matrix(table, countries, metric, tech, 'sign_agreement') == 4
            im = heatmap(ax, values, countries, labels, limit, marked,
                         fmt='{:+.1f}' if metric == 'delta_R' else '{:+.2f}')
            text_inches(fig, .60 + col * 3.61, b + rh - .43,
                        'abcd'[row * 2 + col] + '  ' + TECH_LABELS[tech], fontsize=7, weight='bold')
        cbax = add_axes(fig, 1.60, b + .52, 4.2, .10)
        cb = fig.colorbar(im, cax=cbax, orientation='horizontal')
        cb.ax.tick_params(labelsize=5.7, length=2, pad=1)
        cb.set_label(unit, fontsize=6, labelpad=2)
        text_inches(fig, WIDTH / 2, b + .12,
                    'Cell: four-model mean. Corner dot: all four models agree on direction; not statistical significance.',
                    ha='center', fontsize=5.6)
    export(fig, 'deployment_performance', out, products,
           [('ab', [0, .5, 1, 1]), ('cd', [0, 0, 1, .5])],
           {'color_limits': details, 'center': 'four-model mean of model-level fixed-climate contrasts',
            'corner_dot': 'four-model nonzero sign agreement; not statistical significance'})


def robustness(tables, countries, labels, out, products):
    wins, robust = tables['wins_summary'], tables['robustness']
    n = len(countries)
    rh = .205 * n + 1.27
    fig = plt.figure(figsize=(WIDTH, 2 * rh), facecolor='white')
    palette = [SSP_COLORS[s] for s in CLIMATES] + ['#E2E2E2', '#FFFFFF']
    cmap = ListedColormap(palette)
    for row, metric in enumerate(['R', 'rho_pct']):
        b = (1 - row) * rh
        title = 'Unit-capacity net loss' if metric == 'R' else 'Annual relative net loss'
        text_inches(fig, .20, b + rh - .17, title + ' | lowest-loss deployment | 2050–2059',
                    fontsize=7.2, weight='bold')
        for col, tech in enumerate(TECHS):
            ax = add_axes(fig, .60 + col * 3.61, b + .63, 2.80, rh - 1.31)
            colors = np.full((n, 4), 3.)
            annotations = np.full((n, 4), 'Mixed', dtype=object)
            for i, country in enumerate(countries):
                for j, climate in enumerate(CLIMATES):
                    choices = wins.loc[wins.country.eq(country) & wins.tech.eq(tech) & wins.metric.eq(metric)
                                       & wins.climate_ssp.eq(climate)]
                    choices = choices.loc[truth(choices.ensemble_best) & choices.n_comparable_models.eq(4) & choices.n_models.eq(4)]
                    if len(choices) == 1:
                        chosen = choices.iloc[0]
                        colors[i, j] = CLIMATES.index(chosen.station_ssp)
                        annotations[i, j] = chosen.station_ssp[3:] + f' ({int(chosen.model_wins)}/{int(chosen.n_comparable_models)})'
                    elif len(choices) > 1:
                        annotations[i, j] = '/'.join(choices.station_ssp.str[3:])
                    else:
                        colors[i, j], annotations[i, j] = 4, 'NA'
                choices = robust.loc[robust.country.eq(country) & robust.tech.eq(tech) & robust.metric.eq(metric)]
                available = choices.groups_available.max() if len(choices) else 0
                best = choices.loc[truth(choices.robust_best) & choices.groups_available.eq(12)]
                if len(best) == 1:
                    colors[i, 3] = CLIMATES.index(best.iloc[0].station_ssp)
                    annotations[i, 3] = best.iloc[0].station_ssp[3:]
                elif len(best) > 1:
                    annotations[i, 3] = '/'.join(best.station_ssp.str[3:])
                elif available < 12:
                    colors[i, 3], annotations[i, 3] = 4, 'NA'
            ax.imshow(colors, cmap=cmap, norm=BoundaryNorm(np.arange(-.5, 5.5), cmap.N),
                      aspect='auto', interpolation='nearest')
            country_axis(ax, countries, labels)
            ax.set_xticks(range(4), ['Climate\n126', 'Climate\n245', 'Climate\n585', 'All climates\n& models'])
            ax.tick_params(axis='x', length=0, pad=4, labelsize=6)
            ax.axvline(2.5, color='white', lw=2)
            for i in range(n):
                for j in range(4):
                    ax.text(j, i, annotations[i, j], ha='center', va='center', fontsize=5.9,
                            color='white' if colors[i, j] < 3 else '#3B3F43')
            for spine in ax.spines.values():
                spine.set_visible(False)
            text_inches(fig, .60 + col * 3.61, b + rh - .43,
                        'abcd'[row * 2 + col] + '  ' + TECH_LABELS[tech], fontsize=7, weight='bold')
        text_inches(fig, WIDTH / 2, b + .20,
                    'Climate columns: lowest ensemble mean; parentheses = models supporting that deployment.\n'
                    'Last column: lowest in all 12 climate × model combinations; Mixed = no common winner.',
                    ha='center', va='center', fontsize=5.7, linespacing=1.65)
    export(fig, 'deployment_robustness', out, products,
           [('ab', [0, .5, 1, 1]), ('cd', [0, 0, 1, .5])],
           {'climate_columns': 'ensemble mean minimizer, with supporting-model count',
            'last_column': 'deployment jointly minimizing all 3 climates x 4 models; Mixed when absent',
            'ties': 'show all tied deployment labels; minimization uses source-table tolerance'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top-k', type=int, default=10)
    args = parser.parse_args()
    require(args.top_k >= 1, '--top-k must be positive')
    out = FOLDER / 'outputs' / f'top{args.top_k}'
    source = out / 'source_data'
    names = ['selection', 'metrics_summary', 'contrasts_summary', 'contrasts_models',
             'wins_summary', 'robustness']
    tables = {name: pd.read_csv(source / f'{name}.csv') for name in names}
    for name in ('metrics_summary', 'contrasts_summary'):
        incomplete = tables[name].n_models.ne(4)
        fields = [field for field in ('mean', 'minimum', 'maximum', 'sign_agreement') if field in tables[name]]
        tables[name].loc[incomplete, fields] = np.nan
    selection = tables['selection'].sort_values('rank')
    countries = selection.country.tolist()
    require(countries[0] == 'GLOBAL', 'Selection must start with GLOBAL')
    require(len(countries) == args.top_k + 1, 'Top-k selection size differs from requested k')
    labels = ['Global' if x == 'GLOBAL' else x for x in countries]
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6, 'xtick.labelsize': 6, 'ytick.labelsize': 6.2,
                         'axes.linewidth': .6, 'xtick.major.size': 2,
                         'ytick.major.size': 2, 'savefig.pad_inches': 0})
    products = []
    overview(tables, countries, labels, out, products)
    decompositions(tables, countries, labels, out, products)
    generation_tradeoff(tables, countries, labels, out, products)
    performance(tables, countries, labels, out, products)
    robustness(tables, countries, labels, out, products)
    metadata = {'created_utc': datetime.now(timezone.utc).isoformat(), 'top_k': args.top_k,
                'countries': countries, 'backend': 'Python/matplotlib', 'dpi': 600,
                'archetype': 'quantitative grids', 'width_mm': 183,
                'period': [2050, 2059], 'capacity_snapshot': 2050,
                'selection': 'SSP126 2050 catalogue wind + solar capacity; common country list',
                'center': 'equal-weight four-model mean after model-level calculations',
                'spread': 'four-model min-max, not confidence intervals',
                'source_support': 'common valid support across climate and model within each deployment',
                'interpretation': 'signed net losses; generation differences refer to normal baseline generation',
                'missing_data': 'Only complete four-model groups displayed; incomplete groups are missing, not zero',
                'image_integrity': 'Direct matplotlib rendering from source tables; no image modifications',
                'visual_review': 'PENDING', 'products': products,
                'source_sha256': {n: digest(source / f'{n}.csv') for n in names},
                'code_sha256': digest(FOLDER / 'plot.py'), 'slurm_job_id': os.getenv('SLURM_JOB_ID')}
    write_json(out / 'plot_metadata.json', metadata)
    print(json.dumps({'top_k': args.top_k, 'countries': countries, 'png_files': len(products),
                      'complete_figures': sum(not p['is_group'] for p in products)}))


if __name__ == '__main__':
    main()
