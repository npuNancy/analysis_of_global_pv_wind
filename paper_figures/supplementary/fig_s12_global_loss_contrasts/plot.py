"""Fig. S12: paired pathway differences and event-specific net losses."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from paper_figures.config import MODELS, SSPS, TECHS, SNAPSHOTS, SSP_COLORS
from paper_figures.common.io import digest, write_json
from paper_figures.common.plotting import configure, export_panel_png

FOLDER = Path(__file__).resolve().parent
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
UNIT = 'MWh MW⁻¹ yr⁻¹'
MARKERS = dict(zip(SSPS, ['o', 's', '^']))
NAMES = {'low_resource': 'Low resource', 'high_temp': 'High temperature',
         'icing': 'Icing', 'hot_humid': 'Hot–humid', 'high_wind': 'High wind',
         'high_humidity': 'High humidity', 'freezing_rain': 'Freezing rain',
         'rainstorm': 'Rainstorm', 'cold_highwind': 'Cold + high wind'}

def label(fig, x, y, letter, title):
    fig.text(x, y, letter, fontsize=8, fontweight='bold', va='bottom')
    fig.text(x + 0.024, y, title, fontsize=7, va='bottom')


def main():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    if audit['status'] != 'PASSED':
        raise ValueError('S12 source audit failed')
    for name, sha in audit['source_data_sha256'].items():
        if digest(SOURCE / name) != sha:
            raise ValueError(f'S12 source changed: {name}')
    models = pd.read_csv(SOURCE / 'panel_ab_models.csv')
    c = pd.read_csv(SOURCE / 'panel_ab_display.csv')
    e = pd.read_csv(SOURCE / 'panel_cd_display.csv')
    order = audit['event_order']
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6.5, 'xtick.labelsize': 6, 'ytick.labelsize': 6,
                         'axes.linewidth': .6, 'xtick.major.size': 2, 'ytick.major.size': 2,
                         'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 140 / 25.4), facecolor='white')
    for y in [.967, .429]:
        fig.legend([Line2D([], [], color=SSP_COLORS[s], marker=MARKERS[s], lw=1, ms=3.5)
                    for s in SSPS], [s.upper() for s in SSPS], loc='center',
                   bbox_to_anchor=(.5, y), ncol=3, fontsize=6.5)
    fig.text(.5, .932, 'Paired climate and deployment pathways', ha='center', fontsize=6)
    delta_limit = float(np.ceil(max(abs(c.minimum.min()), abs(c.maximum.max())) / 5) * 5 + 2)
    event_limits = (min(-2, float(e['mean'].min()) * 1.2), float(e['mean'].max()) * 1.08)
    for col, tech in enumerate(TECHS):
        left = .102 + col * .50
        width = .365
        ax = fig.add_axes([left, 0.600, width, 0.265])
        label(fig, left - 0.07, 0.890, 'ab'[col], tech.title() + ' | Difference from SSP126')
        for si, ssp in enumerate(SSPS[1:]):
            for xi, snap in enumerate(SNAPSHOTS):
                x = xi + (-0.16 if si == 0 else 0.16)
                g = c[c.tech.eq(tech) & c.climate_ssp.eq(ssp) & c.snapshot.eq(snap)].iloc[0]
                ax.vlines(x, g.minimum, g.maximum, color=SSP_COLORS[ssp], lw=0.8)
                ax.hlines([g.minimum, g.maximum], x - 0.045, x + 0.045, color=SSP_COLORS[ssp], lw=0.6)
                vals = models[models.tech.eq(tech) & models.climate_ssp.eq(ssp) &
                              models.snapshot.eq(snap)].set_index('model').loc[list(MODELS), 'difference']
                ax.scatter(x + np.linspace(-0.065, 0.065, 4), vals, s=8,
                           facecolors='white', edgecolors=SSP_COLORS[ssp], linewidths=0.5, zorder=3)
                ax.plot(x, g['mean'], marker=MARKERS[ssp], color=SSP_COLORS[ssp], ms=4,
                        markeredgecolor='white', markeredgewidth=0.3, zorder=4)
        ax.axhline(0, color='#666666', lw=0.65)
        ax.set(xlim=(-0.5, 2.5), ylim=(-delta_limit, delta_limit),
               xticks=[0, 1, 2], xticklabels=['2030–39', '2040–49', '2050–59'],
               xlabel='Ten-year window', ylabel='Net-loss difference\n(' + UNIT + ')')
        ax.grid(axis='y', color='#eeeeee', linewidth=0.4)
        ax.set_axisbelow(True)

        ax = fig.add_axes([left + 0.045, 0.140, width - 0.045, 0.245])
        label(fig, left - 0.07, 0.462, 'cd'[col], tech.title() + ' | Event losses, 2050–59')
        rows = order[tech]
        vals = e[e.tech.eq(tech)].set_index(['event', 'climate_ssp'])['mean']
        for yi, event in enumerate(rows):
            ax.axhline(yi, color='#eeeeee', linewidth=0.4, zorder=0)
            ax.plot([vals.loc[event, 'ssp126'], vals.loc[event, 'ssp585']], [yi, yi],
                    color='#b0b0b0', lw=1.6, zorder=1)
            for ssp in SSPS:
                ax.plot(vals.loc[event, ssp], yi, marker=MARKERS[ssp], ms={'ssp126': 5.5, 'ssp245': 4.3, 'ssp585': 3.8}[ssp],
                        color=SSP_COLORS[ssp], markeredgecolor='white', markeredgewidth=0.35, zorder=3)
        ax.axvline(0, color='#888888', linewidth=0.55)
        ax.set(yticks=range(len(rows)), yticklabels=[NAMES[ev] for ev in rows],
               ylim=(len(rows) - 0.5, -0.5), xlim=event_limits, xlabel='Net loss (' + UNIT + ')')
        ax.tick_params(axis='y', length=0, pad=3)
    fig.text(.5, .512, 'Small open points: four models; large symbols: means; bars: model min–max.',
             ha='center', fontsize=6)
    fig.text(.5, .026, 'Event labels may overlap; their losses cannot be added to recover the event union.',
             ha='center', fontsize=6)
    products = [export_panel_png(fig, OUT / 'fig_s12.png', close=False)]
    groups = {'ab': [0, .493, 1, 1], 'cd': [0, 0, 1, .489]}
    for group, bounds in groups.items():
        products.append(export_panel_png(fig, OUT / f'fig_s12_{group}.png', bounds=bounds, close=False))
    plt.close(fig)
    (OUT / 'caption.md').write_text((FOLDER / 'caption.md').read_text())
    write_json(OUT / 'metadata.json', {
        'figure': 'Fig. S12', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'job_id': os.getenv('SLURM_JOB_ID'), 'backend': 'Python/matplotlib', 'size_mm': [183, 140],
        'products': products, 'panel_groups': groups, 'event_order': order,
        'source_data': audit['source_data_sha256'], 'code_sha256': digest(FOLDER / 'plot.py'),
        'migration': 'Fig. 2 c-d -> S12 a-b; Fig. 2 e-f -> S12 c-d',
        'data_audit': 'PASSED', 'visual_review': 'PENDING'})
    print(json.dumps({'figure': 'Fig. S12', 'products': products}), flush=True)


if __name__ == '__main__':
    main()
