"""Plot SSP annual and decadal suitable-grid unit net losses."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from paper_figures.common.plotting import configure, save_png
from paper_figures.config import MODELS, SSPS, SSP_COLORS
from paper_figures.prepare.prepare_suitable_grid_loss import OUT

DEST = Path(__file__).resolve().parent / 'outputs'
LABELS = dict(zip(SSPS, ('SSP1-2.6', 'SSP2-4.5', 'SSP5-8.5')))


def panel(ax, data, tech, xcol, letter, legend=True):
    selected = data[data.tech.eq(tech) & data.support.eq('common')]
    for ssp, style in zip(SSPS, ('-', '--', '-.')):
        pivot = selected[selected.climate_ssp.eq(ssp)].pivot(
            index=xcol, columns='model', values='net_loss_per_mw').sort_index()
        if set(pivot.columns) != set(MODELS) or not np.isfinite(pivot.values).all():
            raise ValueError('Incomplete model ensemble')
        x = pivot.index.to_numpy()
        ax.fill_between(x, pivot.min(axis=1), pivot.max(axis=1),
                        color=SSP_COLORS[ssp], alpha=.13, linewidth=0)
        ax.plot(x, pivot.mean(axis=1), style, color=SSP_COLORS[ssp], lw=1.3,
                marker='o' if xcol == 'window_start' else None, ms=3, label=LABELS[ssp])
    ax.set_title('Wind' if tech == 'wind' else 'Solar', loc='left')
    ax.text(-.15, 1.05, letter, transform=ax.transAxes, weight='bold', fontsize=9)
    ax.set_ylabel('Unit net loss (MWh MW⁻¹ yr⁻¹)')
    if xcol == 'year':
        ax.set_xlabel('Year')
        ax.set_xticks([2030, 2040, 2050, 2059])
        for boundary in (2039.5, 2049.5):
            ax.axvline(boundary, color='.75', ls=':', lw=.6)
    else:
        ax.set_xlabel('Decade')
        ax.set_xticks([2030, 2040, 2050], ['2030s', '2040s', '2050s'])
    ax.grid(axis='y', color='.9', lw=.4)
    if legend:
        ax.legend(fontsize=6, loc='upper right')


def main():
    meta = json.loads((OUT / 'complete.json').read_text())
    configure()
    DEST.mkdir(parents=True, exist_ok=True)
    source = DEST / 'source_data'
    source.mkdir(exist_ok=True)
    outputs = []
    for name, filename, xcol in [('annual', 'annual.csv.gz', 'year'),
                                 ('decadal', 'decadal.csv', 'window_start')]:
        data = pd.read_csv(OUT / filename)
        data.to_csv(source / (name + '.csv'), index=False)
        ensemble = data[data.support.eq('common')].groupby(
            ['tech', 'climate_ssp', xcol]).net_loss_per_mw.agg(['mean', 'min', 'max']).reset_index()
        ensemble.to_csv(source / (name + '_ensemble.csv'), index=False)
        fig, axes = plt.subplots(1, 2, figsize=(183 / 25.4, 83 / 25.4))
        for ax, tech, letter in zip(axes, ('wind', 'solar'), 'ab'):
            panel(ax, data, tech, xcol, letter, legend=False)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='upper center', ncol=3, fontsize=7,
                   bbox_to_anchor=(.5, 1.0))
        fig.tight_layout(pad=1.2, w_pad=2, rect=(0, 0, 1, .91))
        base = 'suitable_grid_loss_' + name
        save_png(fig, DEST / (base + '.png'))
        plt.close(fig)
        outputs.append(base + '.png')
        for tech, letter in zip(('wind', 'solar'), 'ab'):
            fig, ax = plt.subplots(figsize=(95 / 25.4, 83 / 25.4))
            panel(ax, data, tech, xcol, letter)
            fig.tight_layout(pad=1.2)
            save_png(fig, DEST / (base + '_' + letter + '.png'))
            plt.close(fig)
            outputs.append(base + '_' + letter + '.png')
    meta.update(outputs=outputs, centre='four-model arithmetic mean',
                band='four-model min-max, not confidence interval',
                metric='signed net loss for event union all',
                windows='2030-2039, 2040-2049, 2050-2059; separate baseline per decade',
                formats='600 dpi PNG')
    (DEST / 'metadata.json').write_text(json.dumps(meta, indent=2))
    print('\n'.join(outputs))


if __name__ == '__main__':
    main()
