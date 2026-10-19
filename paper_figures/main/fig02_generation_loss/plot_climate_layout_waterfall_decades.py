"""Three-decade SSP585 minus SSP126 climate-mechanism and layout waterfalls."""
import itertools
import json
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, TECHS, STATION_FILES
from paper_figures.common.io import digest, write_csv, write_json
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.main.fig02_generation_loss.plot_climate_layout_waterfall import (
    FOLDER, OUT, SOURCE, INPUT, TERMS, COLORS, UNIT, prepare, require)

STEM = 'fig02_climate_layout_waterfall_2030s_2040s_2050s'
SNAPSHOTS = (2030, 2040, 2050)
TICK_LABELS = ['E', 'CF', 'r', 'S', 'Δ']


def draw_panels(fig, wide, y0=0., height=1., letters='ab'):
    def fy(y):
        return y0 + height * y
    fig.text(.5, fy(.973), 'SSP585 − SSP126 | Climate mechanisms and deployment layout',
             ha='center', va='top', fontsize=8)
    legend = fig.legend([Patch(facecolor=c) for c in COLORS],
                        ['E: Exposure', 'CF: Normal CF (event)', 'r: Relative loss (event)',
                         'S: Layout', 'Δ: Net gap'],
                        loc='center', bbox_to_anchor=(.53, fy(.925)), ncol=5, fontsize=6.2,
                        handlelength=1.4, handletextpad=.4, columnspacing=1.35)
    limits, axes = {}, []
    for row, tech in enumerate(TECHS):
        bottom = .575 if row == 0 else .165
        ax = fig.add_axes([.115, fy(bottom), .855, .28 * height])
        axes.append(ax)
        fig.text(.035, fy(bottom + .302), letters[row], fontsize=8, fontweight='bold')
        fig.text(.063, fy(bottom + .302), 'Wind' if tech == 'wind' else 'Solar', fontsize=7.5)
        all_edges = [0.]
        for snapshot in SNAPSHOTS:
            values = wide.loc[(tech, snapshot), list(TERMS)].to_numpy(float)
            all_edges.extend(np.cumsum(values[:4]))
            all_edges.append(values[4])
        pad = max(.4, np.ptp(all_edges) * .20)
        limits[tech] = [float(min(all_edges) - pad), float(max(all_edges) + 1.2 * pad)]
        for group, snapshot in enumerate(SNAPSHOTS):
            values = wide.loc[(tech, snapshot), list(TERMS)].to_numpy(float)
            require(np.isclose(values[:4].sum(), values[4], atol=1e-10),
                    'Displayed contributions do not close')
            level = 0.
            start = group * 6.
            for offset, (value, color) in enumerate(zip(values, COLORS)):
                x = start + offset
                base = level if offset < 4 else 0.
                end = base + value
                ax.bar(x, abs(value), bottom=min(base, end), width=.67,
                       color=color, edgecolor='white', linewidth=.3, zorder=3)
                below = offset == 4 and value < 0
                ax.annotate(f'{value:+.2f}',
                            (x, min(base, end) if below else max(base, end)),
                            xytext=(0, -4 if below else 4), textcoords='offset points',
                            ha='center', va='top' if below else 'bottom', fontsize=6.1,
                            fontweight='bold' if offset == 4 else 'normal')
                if offset < 4:
                    level = end
                    ax.plot([x + .335, x + .665], [level, level],
                            color='#8f969b', lw=.6, zorder=4)
            ax.text(start + 2, -.185, f'{snapshot}s', transform=ax.get_xaxis_transform(),
                    ha='center', va='top', fontsize=7)
        ax.axhline(0, color='#6d757b', lw=.65)
        ax.set(xlim=(-.75, 16.75), ylim=limits[tech],
               xticks=[group * 6 + offset for group in range(3) for offset in range(5)],
               xticklabels=TICK_LABELS * 3,
               ylabel='Contribution to net-loss gap\n(' + UNIT + ')')
        ax.tick_params(axis='x', length=0, pad=4)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.grid(axis='y', color='#dddddd', linewidth=.4)
        ax.set_axisbelow(True)
    fig.text(.5, fy(.062), 'Climate contributions: E, CF and r; deployment contribution: S.',
             ha='center', fontsize=6.2)
    fig.text(.5, fy(.033), 'Exact attribution within each model, then four-model means; panel y-scales differ.',
             ha='center', fontsize=6)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in axes:
        require(len(ax.patches) == 15, 'Each panel must contain three groups of five bars')
        for a, b in itertools.combinations([*ax.texts, *ax.get_xticklabels()], 2):
            require(not a.get_window_extent(renderer).overlaps(b.get_window_extent(renderer)),
                    'Overlapping labels: ' + a.get_text() + ' / ' + b.get_text())
    for a, b in itertools.combinations(legend.get_texts(), 2):
        require(not a.get_window_extent(renderer).overlaps(b.get_window_extent(renderer)),
                'Overlapping legend labels')
    return limits


def render(wide):
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6.5, 'xtick.labelsize': 6.5,
                         'ytick.labelsize': 6, 'axes.linewidth': .6,
                         'xtick.major.size': 2, 'ytick.major.size': 2,
                         'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 150 / 25.4), facecolor='white')
    limits = draw_panels(fig, wide)
    product = export_panel_png(fig, OUT / f'{STEM}.png')
    return product, limits


def prepare_tables():
    table_parts = {name: [] for name in ['inputs', 'fixed_deployment', 'models', 'display']}
    for snapshot in SNAPSHOTS:
        _, _, tables = prepare(snapshot=snapshot, save=False)
        for name, table in tables.items():
            table_parts[name].append(table)
    tables = {name: pd.concat(parts, ignore_index=True) for name, parts in table_parts.items()}
    wide = tables['display'].pivot(index=['tech', 'snapshot'], columns='term', values='mean')
    require(len(tables['models']) == len(MODELS) * len(TECHS) * len(SNAPSHOTS),
            'Incomplete model-by-technology-by-decade results')
    for name, table in tables.items():
        write_csv(SOURCE / f'{STEM}_{name}.csv', table)
    return tables, wide


def main():
    tables, wide = prepare_tables()
    product, limits = render(wide)
    metadata = dict(
        created_utc=datetime.now(timezone.utc).isoformat(), job_id=os.getenv('SLURM_JOB_ID'),
        backend='Python/matplotlib', archetype='quantitative grid', size_mm=[183, 150],
        dpi=600, snapshots=list(SNAPSHOTS), analysis_windows=[[s, s + 9] for s in SNAPSHOTS],
        models=list(MODELS), comparison='SSP585 minus SSP126',
        panels={'a': 'wind, upper', 'b': 'solar, lower'}, bars_per_panel=15,
        products=[product], units=UNIT, factor_colors=dict(zip(TERMS, COLORS)),
        figure_question='How do climate mechanisms and deployment layout contributions change across decades?',
        decomposition='Within-deployment three-factor Shapley (six orders), averaged over deployments 126 and 585; symmetric layout contribution',
        center='Equal-weight mean of four model-level contributions',
        uncertainty='Model min-max retained in source tables; bars display means only',
        support='Common stations and capacity across climates and models within each deployment and snapshot',
        event='all: selected-event time union', wind_energy_scale=1, station_sources=STATION_FILES,
        axis_limits=limits, within_technology_decades_share_y_scale=True,
        definitions={'E': 'capacity_event_hours / capacity_mw',
                     'CF_event': 'normal_event_mwh / capacity_event_hours',
                     'r_event': 'net_mwh / normal_event_mwh'},
        maximum_closure=float(tables['models'].closure.abs().max()),
        data_audit='PASSED', label_overlap_check='PASSED', visual_review='PENDING',
        input_sha256={str(INPUT.relative_to(ROOT)): digest(INPUT)},
        source_sha256={name: digest(SOURCE / f'{STEM}_{name}.csv') for name in tables},
        code_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                     (FOLDER / 'plot_climate_layout_waterfall_decades.py',
                      FOLDER / 'plot_climate_layout_waterfall.py',
                      ROOT / 'paper_figures/common/metrics.py',
                      ROOT / 'paper_figures/common/plotting.py')})
    write_json(OUT / f'{STEM}_metadata.json', metadata)
    print(wide.to_string())
    print(json.dumps({'product': product, 'maximum_closure': metadata['maximum_closure']}))


if __name__ == '__main__':
    main()
