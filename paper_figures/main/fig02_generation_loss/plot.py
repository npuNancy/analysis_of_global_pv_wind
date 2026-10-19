"""Fig. 2: annual losses, climate-layout attribution and event composition."""
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
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
from paper_figures.config import ROOT, SSPS, TECHS, SNAPSHOTS, SSP_COLORS
from paper_figures.common.io import digest, write_csv, write_json
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.main.fig02_generation_loss.prepare_data import main as prepare, require
from paper_figures.main.fig02_generation_loss.plot_climate_layout_waterfall_decades import (
    draw_panels as draw_waterfall_panels, prepare_tables as prepare_waterfall_tables)
from paper_figures.main.fig02_generation_loss.plot_climate_layout_waterfall import TERMS, COLORS

FOLDER = ROOT / 'paper_figures/main/fig02_generation_loss'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
UNIT = 'MWh MW⁻¹ yr⁻¹'
SSP_LABEL = dict(zip(SSPS, ['SSP1-2.6', 'SSP2-4.5', 'SSP5-8.5']))
EVENT_LABEL = {
    'low_resource': 'Low resource', 'high_temp': 'High temperature',
    'high_wind': 'High wind', 'hot_humid': 'Hot–humid', 'icing': 'Icing',
    'rainstorm': 'Rainstorm', 'cold_highwind': 'Cold + high wind',
    'freezing_rain': 'Freezing rain', 'high_humidity': 'High humidity'}
EVENT_COLOR = dict(zip(EVENT_LABEL, [
    '#3b6fb6', '#d95f02', '#b2182b', '#e78ac3', '#67a9cf',
    '#1b9e77', '#7570b3', '#80cdc1', '#66a61e']))
EVENT_ORDER = {
    'wind': ('low_resource', 'high_temp', 'high_wind', 'hot_humid', 'icing'),
    'solar': ('low_resource', 'icing', 'rainstorm', 'cold_highwind',
              'freezing_rain', 'high_humidity')}
FACTOR_COLORS = dict(zip(TERMS, COLORS))
PERCENT_LABEL_MIN = 5
PERCENT_LABEL_MIN_HEIGHT_PT = 7


def label(fig, x, y, letter, title):
    fig.text(x, y, letter, fontsize=8, fontweight='bold', va='bottom')
    fig.text(x + .024, y, title, fontsize=7, va='bottom')


def annual_panels(fig, annual, trends):
    fig.legend([Line2D([], [], color=SSP_COLORS[s], lw=1.1) for s in SSPS],
               [SSP_LABEL[s] for s in SSPS], loc='center', bbox_to_anchor=(.5, 0.9846369),
               ncol=3, fontsize=6.5, handlelength=2.5, columnspacing=2.5)
    limits = {}
    for col, tech in enumerate(TECHS):
        left = .105 + col * .5
        ax = fig.add_axes([left, 0.8009777, .360, 0.1410615])
        label(fig, left - .08, 0.9553073, 'ab'[col], tech.title() + ' | Annual net loss')
        for ssp in SSPS:
            g = annual[annual.tech.eq(tech) & annual.climate_ssp.eq(ssp)].sort_values('year')
            x, y = g.year.to_numpy(), g['mean'].to_numpy()
            require(np.array_equal(x, np.arange(2030, 2060)), 'Incomplete annual line')
            color = SSP_COLORS[ssp]
            ax.fill_between(x, g.minimum, g.maximum, color=color, alpha=.16, linewidth=0, zorder=1)
            ax.plot(x, y, color=color, lw=1.05, zorder=3)
            fit = trends[trends.tech.eq(tech) & trends.climate_ssp.eq(ssp)].iloc[0]
            require(np.allclose([fit.slope, fit.intercept], np.polyfit(x, y, 1)), 'Trend mismatch')
            ax.plot(x, fit.slope * x + fit.intercept, '--', color=color, lw=1.0, zorder=4)
        ax.set(xlabel='Year', ylabel='Unit-capacity loss\n(' + UNIT + ')',
               xlim=(2028.6, 2060.4), xticks=range(2030, 2061, 5))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.grid(axis='y', color='#dddddd', alpha=.65, linewidth=.4)
        ax.set_axisbelow(True)
        limits[tech] = list(ax.get_ylim())
    fig.text(.5, 0.7632682, 'Four-model means; shading: model min–max; dashed lines: least-squares trends.',
             ha='center', fontsize=6)
    return limits


def waterfall_panels(fig, wide):
    limits = draw_waterfall_panels(fig, wide, y0=.285, height=.46, letters='cd')
    for ax in fig.axes[-2:]:
        for text in ax.texts:
            if text.get_text().startswith(('+', '-')):
                text.set_bbox(dict(facecolor='white', edgecolor='none', pad=.3))
    return limits


def composition_panels(fig, summary):
    summary = summary.copy()
    keys = ['tech', 'climate_ssp', 'snapshot']
    summary['event_sum'] = summary.groupby(keys)['mean'].transform('sum')
    require(summary.event_sum.gt(0).all(), 'Event pool must be positive')
    summary['share_pct'] = 100 * summary['mean'] / summary.event_sum
    require(np.allclose(summary.groupby(keys).share_pct.sum(), 100), 'Composition shares')
    summary['units'] = UNIT
    totals = summary.groupby(keys)['mean'].agg(
        positive=lambda x: x.clip(lower=0).sum(), negative=lambda x: x.clip(upper=0).sum())
    limits = [float(min(0, totals.negative.min()) * 1.08), float(totals.positive.max() * 1.08)]
    segment_points = summary['mean'].abs() / (limits[1] - limits[0]) * fig.get_figheight() * 72 * 0.1375862
    summary['percentage_label_shown'] = (
        summary.share_pct.abs().ge(PERCENT_LABEL_MIN) & segment_points.ge(PERCENT_LABEL_MIN_HEIGHT_PT))
    write_csv(SOURCE / 'event_composition_display.csv', summary)
    for col, tech in enumerate(TECHS):
        left = .105 + col * .5
        ax = fig.add_axes([left, 0.0724138, .360, 0.1375862])
        label(fig, left - .08, 0.2639080, 'ef'[col], tech.title() + ' | Event loss composition')
        fig.legend([Patch(facecolor=EVENT_COLOR[e]) for e in EVENT_ORDER[tech]],
                   [EVENT_LABEL[e] for e in EVENT_ORDER[tech]], loc='center',
                   bbox_to_anchor=(left + .180, 0.2365517), ncol=3, fontsize=5.7,
                   handlelength=1.2, handletextpad=.4, columnspacing=.8, labelspacing=.55)
        for gi, snapshot in enumerate(SNAPSHOTS):
            positions = gi * 3.5 + np.arange(3) * .8
            for si, ssp in enumerate(SSPS):
                block = summary[summary.tech.eq(tech) & summary.snapshot.eq(snapshot) &
                                summary.climate_ssp.eq(ssp)].set_index('event')
                pos = neg = 0.
                for event in EVENT_ORDER[tech]:
                    row = block.loc[event]
                    value = row['mean']
                    bottom = pos if value >= 0 else neg
                    ax.bar(positions[si], value, bottom=bottom, width=.66,
                           color=EVENT_COLOR[event], edgecolor='white', linewidth=.35, zorder=3)
                    if row.percentage_label_shown:
                        color = 'white' if event in ['low_resource', 'high_temp', 'high_wind',
                                                     'rainstorm', 'cold_highwind', 'high_humidity'] else '#222222'
                        ax.text(positions[si], bottom + value / 2, f'{row.share_pct:.0f}%',
                                ha='center', va='center', color=color, fontsize=5.5, zorder=4)
                    if value >= 0:
                        pos += value
                    else:
                        neg += value
                require(np.isclose(pos + neg, block.event_sum.iloc[0]), 'Stack total mismatch')
            ax.text(positions[1], -.26, f'{snapshot}s', transform=ax.get_xaxis_transform(),
                    ha='center', va='top', fontsize=6.3)
        ax.set(xticks=[gi * 3.5 + si * .8 for gi in range(3) for si in range(3)],
               xticklabels=['126', '245', '585'] * 3, xlim=(-.6, 9.2), ylim=limits,
               ylabel='Event-labelled net loss\n(' + UNIT + ')')
        ax.tick_params(axis='x', length=0, pad=3, labelsize=5.8)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.grid(axis='y', color='#dddddd', linewidth=.4)
        ax.set_axisbelow(True)
    fig.text(.5, 0.0040230, 'Bars within each decade: SSP126, SSP245, SSP585.\n'
             'Percentages ≥5% of summed event-labelled losses; event categories can overlap.',
             ha='center', va='bottom', fontsize=6)
    return limits


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--skip-prepare', action='store_true')
    args = parser.parse_args()
    if not args.skip_prepare:
        prepare()
    audit = json.loads((OUT / 'data_audit.json').read_text())
    require(audit['status'] == 'PASSED', 'Source audit failed')
    for name, sha in audit['input_sha256'].items():
        require(digest(ROOT / name) == sha, 'Audited input changed: ' + name)
    annual = pd.read_csv(SOURCE / 'panel_ab_display.csv')
    trends = pd.read_csv(SOURCE / 'annual_trends.csv')
    waterfall_tables, decomposition = prepare_waterfall_tables()
    events = pd.read_csv(SOURCE / 'event_composition_display.csv')
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6, 'xtick.labelsize': 6, 'ytick.labelsize': 6,
                         'axes.linewidth': .6, 'xtick.major.size': 2, 'ytick.major.size': 2,
                         'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 270 / 25.4), facecolor='white')
    annual_limits = annual_panels(fig, annual, trends)
    waterfall_limits = waterfall_panels(fig, decomposition)
    event_limits = composition_panels(fig, events)
    products = [export_panel_png(fig, OUT / 'fig02.png', close=False)]
    groups = {'ab': [0, .75, 1, 1], 'cd': [0, .285, 1, .745], 'ef': [0, 0, 1, .28]}
    for group, bounds in groups.items():
        products.append(export_panel_png(fig, OUT / f'fig02_{group}.png', bounds=bounds, close=False))
    plt.close(fig)
    (OUT / 'caption.md').write_text((FOLDER / 'caption.md').read_text())
    write_json(OUT / 'metadata.json', {
        'figure': 'Fig. 2', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'job_id': os.getenv('SLURM_JOB_ID'), 'backend': 'Python/matplotlib',
        'archetype': 'quantitative grid', 'size_mm': [183, 270], 'dpi': 600,
        'products': products, 'panel_groups': groups, 'n_models': 4,
        'annual_limits': annual_limits, 'waterfall_limits': waterfall_limits, 'event_limits': event_limits,
        'annual_encoding': 'continuous mean lines; four-model min-max shading; 2030-2059 OLS dashed trends',
        'climate_layout_definition': 'Three within-deployment Shapley climate terms plus symmetric layout; paired SSP585 minus SSP126 per model',
        'climate_layout_max_closure': float(waterfall_tables['models'].closure.abs().max()),
        'event_encoding': 'signed ensemble-mean event losses in physical units; percentage of displayed event sum',
        'percentage_label_min_pct': PERCENT_LABEL_MIN,
        'percentage_label_min_segment_height_pt': PERCENT_LABEL_MIN_HEIGHT_PT,
        'waterfall_label_overlap_check': 'PASSED', 'negative_event_means': audit['negative_event_means'],
        'event_order': EVENT_ORDER, 'event_colours': EVENT_COLOR, 'factor_colours': FACTOR_COLORS,
        'source_data': {p.name: digest(p) for p in sorted(SOURCE.glob('*.csv'))},
        'code_sha256': {str(p.relative_to(ROOT)): digest(p) for p in
                       (FOLDER / 'plot.py', FOLDER / 'prepare_data.py',
                        FOLDER / 'plot_climate_layout_waterfall.py',
                        FOLDER / 'plot_climate_layout_waterfall_decades.py',
                        ROOT / 'paper_figures/common/metrics.py',
                        ROOT / 'paper_figures/common/plotting.py')},
        'reference_style': 'Annual and event panels retain project styling; c-d use the three-decade climate-layout waterfall',
        'data_audit': 'PASSED', 'visual_review': 'PENDING'})
    print(json.dumps({'figure': 'Fig. 2', 'products': products}), flush=True)
    from paper_figures.supplementary.fig_s12_global_loss_contrasts.plot import main as supplement
    supplement()


if __name__ == '__main__':
    main()
