"""National exposure comparisons: paired-difference intervals and grid/station scatter."""
import argparse
import itertools
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SSP_COLORS
from paper_figures.common.io import digest, write_csv, write_json
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.common.spatial import countries

FOLDER = ROOT / 'paper_figures/main/fig01_extreme_events'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
REPRESENTATIVE = ['AUS', 'DEU', 'ZAF', 'USA', 'BRA', 'CHN', 'IND']
SSP_LABELS = dict(zip(SSPS, ['SSP1-2.6', 'SSP2-4.5', 'SSP5-8.5']))
MARKERS = dict(zip(SSPS, ['o', 's', '^']))
TECH_LABELS = {'wind': 'Wind', 'solar': 'Solar PV'}
KEYS = ['country', 'tech', 'climate_ssp']
METRICS = [f'{scope}_{period}' for period in ['2050', 'change']
           for scope in ['grid', 'station', 'gap']]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(k):
    model_path = SOURCE / 'country_exposure_models.csv.gz'
    display_path = SOURCE / 'country_exposure_display.csv'
    capacity_path = OUTPUT / 'catalogues/capacity_by_country.csv'
    audit_path = OUT / 'country_exposure_data_audit.json'
    audit = json.loads(audit_path.read_text())
    require(audit['status'] == 'PASSED', 'Country source audit failed')
    for path in [model_path, display_path]:
        expected = next(x['sha256'] for x in audit['source_data']
                        if x['path'].endswith('/' + path.name))
        require(digest(path) == expected, f'Source hash mismatch: {path.name}')
    expected = next(x['sha256'] for x in audit['inputs']
                    if x['path'].endswith('/catalogues/capacity_by_country.csv'))
    require(digest(capacity_path) == expected, 'Reference capacity catalogue changed')
    names = {iso: name for iso, name, _ in countries() if iso != 'ATA'}
    names.update(USA='USA', ZAF='South Africa')
    capacity = pd.read_csv(capacity_path)
    capacity = capacity[capacity.station_ssp.eq('ssp126') & capacity.snapshot.eq(2050)
                        & capacity.country.isin(names) & capacity.tech.isin(TECHS)]
    require(not capacity.duplicated(['country', 'tech']).any(), 'Duplicate capacities')
    ranking = capacity.groupby('country', as_index=False).capacity_mw.sum()
    ranking = ranking[ranking.capacity_mw.gt(0)].sort_values(
        ['capacity_mw', 'country'], ascending=[False, True]).reset_index(drop=True)
    require(1 <= k <= len(ranking), f'k must be between 1 and {len(ranking)}')
    ranking['rank'] = np.arange(1, len(ranking) + 1)
    ranking['reference_capacity_gw'] = ranking.capacity_mw / 1000
    groups = {'representative': REPRESENTATIVE, f'top{k}': ranking.country.head(k).tolist()}
    selected = set(itertools.chain.from_iterable(groups.values()))
    data = pd.read_csv(model_path)
    data = data[data.country.isin(selected)].copy()
    require(not data.duplicated(KEYS + ['model']).any(), 'Duplicate model rows')
    require(data.climate_ssp.eq(data.station_ssp).all(), 'Expected paired SSPs')
    require(data.unit.eq('day yr-1').all() and data.event.eq('all').all(), 'Unexpected metric')
    expected = pd.MultiIndex.from_product(
        [sorted(selected), TECHS, SSPS, MODELS], names=KEYS + ['model'])
    require(set(data.set_index(KEYS + ['model']).index) == set(expected),
            'Incomplete country/technology/SSP/model matrix')
    base = [f'{scope}_days_{year}' for scope in ['grid', 'station'] for year in [2030, 2050]]
    valid = np.isfinite(data[base]).all(axis=1)
    require(valid.all(), 'Missing exposure (no country replaced or missing value filled): '
            + str(data.loc[~valid, KEYS + ['model']].to_dict('records')))
    for scope in ['grid', 'station']:
        data[f'{scope}_2050'] = data[f'{scope}_days_2050']
        data[f'{scope}_change'] = data[f'{scope}_days_2050'] - data[f'{scope}_days_2030']
        require(np.allclose(data[f'{scope}_change'], data[f'{scope}_change_days']),
                f'{scope} change does not reproduce source')
    data['gap_2050'] = data.grid_2050 - data.station_2050
    data['gap_change'] = data.grid_change - data.station_change
    require(np.allclose(data.gap_change, data.gap_2050 -
                        (data.grid_days_2030 - data.station_days_2030)), 'Gap-change identity')
    rows = []
    for key, frame in data.groupby(KEYS):
        require(set(frame.model) == set(MODELS), 'Four complete paired models required')
        row = dict(zip(KEYS, key))
        row.update(station_ssp=key[2], unit='day yr-1', event='all', n_models=4,
                   capacity_gw=float(frame.capacity_gw.iloc[0]))
        for metric in METRICS:
            row[metric] = float(frame[metric].mean())
            row[metric + '_min'] = float(frame[metric].min())
            row[metric + '_max'] = float(frame[metric].max())
        rows.append(row)
    summary = pd.DataFrame(rows)
    match = summary.merge(pd.read_csv(display_path), on=KEYS, suffixes=('', '_source'),
                          validate='one_to_one')
    require(len(match) == len(summary), 'Incomplete display reference')
    for ours, theirs in [('grid_2050', 'grid_days_2050'), ('station_2050', 'station_days_2050'),
                        ('grid_change', 'grid_change_days'), ('station_change', 'station_change_days')]:
        require(np.allclose(match[ours], match[theirs]), 'Display reproduction: ' + ours)
    selection = []
    for group, codes in groups.items():
        for order, code in enumerate(codes, 1):
            ref = ranking[ranking.country.eq(code)].iloc[0]
            selection.append(dict(group=group, order=order, country=code, name=names[code],
                                  reference_capacity_gw=float(ref.reference_capacity_gw),
                                  global_capacity_rank=int(ref['rank'])))
    inputs = [dict(path=str(p), sha256=digest(p))
              for p in [model_path, display_path, capacity_path, audit_path]]
    return data, summary, pd.DataFrame(selection), groups, names, inputs


def axis_limits(summary, period, kind):
    columns = ([f'gap_{period}_min', f'gap_{period}_max'] if kind == 'interval'
               else [f'grid_{period}', f'station_{period}'])
    values = summary[columns].to_numpy()
    lo, hi = min(0, values.min()), max(0, values.max())
    span = max(hi - lo, 1)
    return (lo - .10 * span if lo < 0 else 0, hi + .12 * span)


def draw_panel(ax, summary, codes, names, colors, tech, period, kind, bounds):
    frame = summary[summary.tech.eq(tech)].set_index(['country', 'climate_ssp'])
    letter = 'a' if tech == 'wind' else 'b'
    ax.set_title(f'{letter}  {TECH_LABELS[tech]}', loc='left', fontweight='bold', pad=10)
    if kind == 'interval':
        y = np.arange(len(codes))
        for j, ssp in enumerate(SSPS):
            values = frame.loc[[(code, ssp) for code in codes]]
            metric = f'gap_{period}'
            mean = values[metric].to_numpy()
            error = np.vstack([mean - values[metric + '_min'].to_numpy(),
                               values[metric + '_max'].to_numpy() - mean])
            ax.errorbar(mean, y + (j - 1) * .24, xerr=error, fmt=MARKERS[ssp],
                        color=SSP_COLORS[ssp], markersize=3.5, elinewidth=.8,
                        capsize=0, linewidth=0, zorder=3)
        ax.axvline(0, color='#666666', linewidth=.8)
        ax.set_xlim(*bounds)
        ax.set_ylim(len(codes) - .5, -.5)
        ax.set_yticks(y, [names[code] for code in codes], fontsize=7)
        ax.set_xlabel(('Grid − station exposure' if period == '2050'
                       else 'Grid change − station change') + ' (day yr⁻¹)')
        ax.grid(axis='x', color='#e5e5e5', linewidth=.5)
    else:
        ax.plot(bounds, bounds, color='#737373', linewidth=.85, linestyle='--', zorder=1)
        if period == 'change':
            ax.axhline(0, color='#b0b0b0', linewidth=.6)
            ax.axvline(0, color='#b0b0b0', linewidth=.6)
        for code in codes:
            values = frame.loc[[(code, ssp) for ssp in SSPS]]
            x, y = values[f'grid_{period}'].to_numpy(), values[f'station_{period}'].to_numpy()
            ax.plot(x, y, color=colors[code], linewidth=.65, alpha=.65, zorder=2)
            for j, ssp in enumerate(SSPS):
                ax.scatter(x[j], y[j], s=35, marker=MARKERS[ssp], color=colors[code],
                           edgecolors='white', linewidth=.45, zorder=3)
        ax.set_xlim(*bounds)
        ax.set_ylim(*bounds)
        ax.set_aspect('equal', adjustable='box')
        ax.annotate('', xy=(.84, .56), xytext=(.70, .70),
                    xycoords='axes fraction', textcoords='axes fraction',
                    arrowprops=dict(arrowstyle='-|>', color='#444444', lw=1.1,
                                    mutation_scale=11, shrinkA=0, shrinkB=0), zorder=4)
        ax.text(.75, .56, 'better', transform=ax.transAxes, rotation=-45,
                ha='center', va='center', fontsize=8, color='#444444', zorder=4)
        prefix = 'Change in ' if period == 'change' else ''
        ax.set_xlabel(prefix + 'grid exposure (day yr⁻¹)')
        ax.set_ylabel(prefix + 'station exposure (day yr⁻¹)')
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5, prune='both'))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5, prune='both'))


def render(summary, codes, names, colors, group, period, kind, bounds):
    width = 260
    legend_rows = int(np.ceil(len(codes) / 5))
    height = max(140, 62 + 8 * len(codes)) if kind == 'interval' else max(140, 115 + 6 * legend_rows)
    fig, axes = plt.subplots(1, 2, figsize=(width / 25.4, height / 25.4), squeeze=False)
    fig.subplots_adjust(left=.12 if kind == 'interval' else .075,
                        right=.97, bottom=.28 if kind == 'scatter' else .23,
                        top=.81, wspace=.48 if kind == 'interval' else .28)
    for ax, tech in zip(axes[0], TECHS):
        draw_panel(ax, summary, codes, names, colors, tech, period, kind, bounds)
    period_label = '2050–2059' if period == '2050' else '2050–2059 minus 2030–2039'
    group_label = 'Intercontinental representatives' if group == 'representative' else (
        f'Top {len(codes)} countries: SSP1-2.6 / 2050 wind + solar capacity')
    fig.suptitle(f'{period_label}\n{group_label}', fontsize=8, y=.98)
    handles = [Line2D([], [], marker=MARKERS[s], linestyle='none',
                      color=SSP_COLORS[s] if kind == 'interval' else '#555555',
                      markersize=4, label=SSP_LABELS[s]) for s in SSPS]
    if kind == 'scatter':
        handles_country = [Line2D([], [], color=colors[c], marker='o', linewidth=.7,
                                  markersize=4, label=names[c]) for c in codes]
        fig.legend(handles=handles_country, loc='upper center', bbox_to_anchor=(.5, .21),
                   ncol=5, fontsize=6, columnspacing=1.2)
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.5, .075),
               ncol=3, fontsize=6, columnspacing=1.2)
    note = ('Mean and min–max of four model-paired differences.' if kind == 'interval'
            else 'Four-model means; dashed line: grid = station.')
    fig.text(.5, .049, note, ha='center', va='center', fontsize=5.5)
    fig.text(.5, .023, 'Paired climate/deployment SSPs; station changes include deployment changes.',
             ha='center', va='center', fontsize=5.5)
    stem = f'country_exposure_{kind}_{group}_{period}'
    return export_panel_png(fig, OUT / f'{stem}.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--k', type=int, default=10,
                        help='Top-k countries by SSP126 2050 wind + solar capacity (default: 10)')
    args = parser.parse_args()
    data, summary, selection, groups, names, inputs = prepare(args.k)
    configure()
    selected = list(dict.fromkeys(itertools.chain.from_iterable(groups.values())))
    palette = plt.get_cmap('tab20', max(20, len(selected)))
    order = list(range(0, 20, 2)) + list(range(1, 20, 2)) if len(selected) <= 20 else list(range(len(selected)))
    colors = {country: palette(order[i]) for i, country in enumerate(selected)}
    files = {f'country_comparison_k{args.k}_models.csv.gz': data,
             f'country_comparison_k{args.k}_summary.csv': summary,
             f'country_comparison_k{args.k}_selection.csv': selection}
    for name, frame in files.items():
        write_csv(SOURCE / name, frame)
    products = []
    for kind, period in itertools.product(['interval', 'scatter'], ['2050', 'change']):
        bounds = axis_limits(summary, period, kind)
        for group, codes in groups.items():
            products.append(render(summary, codes, names, colors, group, period, kind, bounds))
    metadata = dict(status='PASSED', created_utc=datetime.now(timezone.utc).isoformat(),
                    job_id=os.environ.get('SLURM_JOB_ID'), k=args.k, inputs=inputs,
                    code_sha256=digest(__file__), products=products, country_groups=groups,
                    selection='SSP126 2050 total wind + solar catalogue capacity; ISO tie-break',
                    gap='grid area-weighted exposure minus station capacity-weighted exposure',
                    gap_change='(grid2050-grid2030) minus (station2050-station2030), within model',
                    unit='day yr-1', event='all: time union', ensemble='equal mean of four models',
                    interval='min–max of four model-paired differences; not a confidence interval',
                    scatter='country colour, SSP shape, fixed marker size; equal-scale axes',
                    better_arrow='Perpendicular to 1:1 line towards lower station relative to grid exposure (or change)',
                    checks=['source hashes', 'complete selected model matrix', 'finite data',
                            'paired SSPs', 'gap-change identity', 'existing display reproduction',
                            'text bounds and PNG integrity'],
                    source_data=[dict(path=str(SOURCE / n), sha256=digest(SOURCE / n)) for n in files],
                    visual_review='PENDING')
    write_json(OUT / f'country_comparison_k{args.k}_metadata.json', metadata)
    print(json.dumps(dict(status='PASSED', k=args.k, groups=groups, png_count=len(products))), flush=True)


if __name__ == '__main__':
    main()
