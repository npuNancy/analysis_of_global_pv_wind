"""Audit existing Fig. 2 tables, supplement display data and render six panels."""
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
from matplotlib.patches import Rectangle
from matplotlib.text import Text
from PIL import Image
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS, SSP_COLORS
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.metrics import ensemble
from paper_figures.common.plotting import configure, save_png

FOLDER = ROOT / 'paper_figures/main/fig02_generation_loss'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
UNIT = 'MWh MW⁻¹ yr⁻¹'
MARKERS = dict(zip(SSPS, ['o', 's', '^']))
NAMES = {'low_resource': 'Low resource', 'high_temp': 'High temperature',
         'icing': 'Icing', 'hot_humid': 'Hot–humid', 'high_wind': 'High wind',
         'high_humidity': 'High humidity', 'freezing_rain': 'Freezing rain',
         'rainstorm': 'Rainstorm', 'cold_highwind': 'Cold + high wind'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit():
    OUT.mkdir(parents=True, exist_ok=True)
    final_path = ROOT / 'logs/paper_figures/completion_status/final_audit.json'
    final = json.loads(final_path.read_text())
    require(final['acceptance']['status'] == 'PASSED' and
            final['verified_output_units'] == final['manifest_units'] == 664,
            'Preparation acceptance incomplete')
    for folder in ['loss_summary', 'event_summary', 'panel_loss', 'catalogues']:
        require_complete(OUTPUT / folder)
    a, c, e = [pd.read_csv(SOURCE / name) for name in
               ['panel_ab.csv', 'panel_cd.csv', 'panel_ef.csv']]
    keys = ['model', 'climate_ssp', 'station_ssp', 'tech', 'snapshot', 'country', 'event', 'support']
    first = a.iloc[0]
    require(np.isclose(first.R, first.net_mwh / first.capacity_mw), 'Sample normalization')
    for t, count in [(a, 720), (c, 24), (e, 132)]:
        require(len(t) == count, 'Incomplete panel table')
        require(t.country.eq('GLOBAL').all() and t.support.eq('common').all(), 'Scope mismatch')
        require(set(t.model) == set(MODELS), 'Model coverage')
    require(not c.duplicated(['model', 'tech', 'snapshot']).any(), 'Duplicate contrast')
    require(c.event.eq('all').all() and c.metric.eq('R').all(), 'Contrast metric mismatch')
    for t, extra in [(a, ['year']), (e, [])]:
        require(not t.duplicated(keys + extra).any(), 'Duplicate loss record')
        require(t.climate_ssp.eq(t.station_ssp).all(), 'Unpaired pathway')
        require(np.isfinite(t[['R', 'net_mwh', 'capacity_mw']]).all().all(), 'Missing loss value')
        require(t.capacity_mw.gt(0).all(), 'Non-positive denominator')
        require(np.allclose(t.R, t.net_mwh / t.capacity_mw, rtol=1e-11), 'Normalization mismatch')
    require(a.event.eq('all').all(), 'Annual table must use event union')
    expected = set(itertools.product(MODELS, SSPS, TECHS, range(2030, 2060)))
    require(set(a[['model', 'climate_ssp', 'tech', 'year']].itertuples(index=False, name=None))
            == expected, 'Missing annual combination')
    require((a.snapshot == (a.year // 10) * 10).all(), 'Year/snapshot mismatch')
    cap = a.groupby(['station_ssp', 'tech', 'snapshot']).capacity_mw.agg(['min', 'max'])
    require(np.allclose(cap['min'], cap['max']), 'Common support capacity varies')
    window = a.groupby(keys, as_index=False).agg(
        R=('R', 'mean'), net_mwh=('net_mwh', 'mean'), capacity_mw=('capacity_mw', 'first'),
        available_capacity_mw=('available_capacity_mw', 'first'), n_stations=('n_stations', 'first'),
        n_years=('year', 'nunique'))
    require(window.n_years.eq(10).all(), 'Incomplete decade')
    window['year_start'] = window.snapshot
    window['year_end'] = window.snapshot + 9
    wide = window.pivot(index=['model', 'tech', 'snapshot'], columns='climate_ssp', values='R')
    contrasts = []
    for ssp, field in [('ssp245', 'D245'), ('ssp585', 'D')]:
        reference = c.set_index(['model', 'tech', 'snapshot'])[field].sort_index()
        delta = (wide[ssp] - wide.ssp126).sort_index()
        require(reference.index.equals(delta.index) and np.allclose(reference, delta, atol=1e-10),
                'Stored contrast differs from within-model annual means')
        block = window[window.climate_ssp.eq(ssp)].copy()
        base = window[window.climate_ssp.eq('ssp126')][
            ['model', 'tech', 'snapshot', 'R', 'capacity_mw', 'n_stations']].rename(
                columns={'R': 'reference_R', 'capacity_mw': 'reference_capacity_mw',
                         'n_stations': 'reference_n_stations'})
        block = block.merge(base, on=['model', 'tech', 'snapshot'], validate='one_to_one')
        block['difference'] = block.R - block.reference_R
        block['reference_climate_ssp'] = 'ssp126'
        block['reference_station_ssp'] = 'ssp126'
        contrasts.append(block)
    contrasts = pd.concat(contrasts, ignore_index=True)
    require(e.snapshot.eq(2050).all(), 'Wrong event period')
    expected_events = {(m, s, t, ev) for m in MODELS for s in SSPS for t in TECHS for ev in EVENTS[t]}
    require(set(e[['model', 'climate_ssp', 'tech', 'event']].itertuples(index=False, name=None))
            == expected_events, 'Missing event combination')
    denominator = window[window.snapshot.eq(2050)][
        ['model', 'climate_ssp', 'tech', 'capacity_mw']].rename(columns={'capacity_mw': 'all_capacity_mw'})
    check = e.merge(denominator, on=['model', 'climate_ssp', 'tech'], validate='many_to_one')
    require(np.allclose(check.capacity_mw, check.all_capacity_mw), 'Event denominator differs from all valid capacity')
    event_path = OUTPUT / 'event_summary/window.csv.gz'
    chunks = []
    for part in pd.read_csv(event_path, chunksize=50000):
        chunks.append(part[part.country.eq('GLOBAL') & part.snapshot.eq(2050) &
                           part.climate_ssp.eq('ssp126') & part.station_ssp.eq('ssp126') &
                           part.event.ne('all')])
    exposure = pd.concat(chunks, ignore_index=True)
    require(len(exposure) == 44 and np.isfinite(exposure.E).all(), 'Incomplete ordering exposure')
    require(not exposure.duplicated(['model', 'tech', 'event']).any(), 'Duplicate ordering exposure')
    order = {}
    for tech in TECHS:
        g = exposure[exposure.tech.eq(tech)].groupby('event', as_index=False).E.mean()
        order[tech] = g.sort_values(['E', 'event'], ascending=[False, True]).event.tolist()
        require(set(order[tech]) == set(EVENTS[tech]), 'Ordering event mismatch')
    refs_path = OUTPUT / 'catalogues/capacity_by_country.csv'
    refs = pd.read_csv(refs_path).groupby(['station_ssp', 'tech', 'snapshot']).capacity_mw.sum()
    coverage = window.copy()
    coverage['catalogue_capacity_mw'] = [
        refs.loc[(r.station_ssp, r.tech, r.snapshot)] for r in coverage.itertuples()]
    coverage['capacity_coverage_pct'] = 100 * coverage.capacity_mw / coverage.catalogue_capacity_mw
    require(coverage.capacity_coverage_pct.between(0, 100 + 1e-8).all(), 'Invalid capacity coverage')
    annual_display = ensemble(a, ['tech', 'climate_ssp', 'snapshot', 'year'], 'R')
    contrast_display = ensemble(contrasts, ['tech', 'climate_ssp', 'snapshot'], 'difference')
    event_display = ensemble(e, ['tech', 'climate_ssp', 'event'], 'R')
    event_display['row'] = [order[r.tech].index(r.event) for r in event_display.itertuples()]
    for t in [annual_display, contrast_display, event_display]:
        require(t.n_models.eq(4).all() and t['mean'].notna().all(), 'Ensemble incomplete')
        t['units'] = UNIT
    for name, table in {
        'panel_ab_display.csv': annual_display, 'panel_cd_models.csv': contrasts,
        'panel_cd_display.csv': contrast_display, 'panel_ef_display.csv': event_display,
        'panel_ef_ordering.csv': exposure, 'capacity_coverage.csv': coverage}.items():
        write_csv(SOURCE / name, table)
    inputs = [SOURCE / n for n in ['panel_ab.csv', 'panel_cd.csv', 'panel_ef.csv']]
    inputs += [event_path, refs_path, final_path]
    result = {
        'status': 'PASSED', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'input_rows': {'ab': len(a), 'cd': len(c), 'ef': len(e)},
        'display_rows': {'ab': len(annual_display), 'cd': len(contrast_display), 'ef': len(event_display)},
        'checks': ['664 accepted units', 'full model/pathway/year/event coverage', 'unique records',
                   'signed energy divided by common capacity', 'fixed capacity within snapshot',
                   'ten-year means and within-model paired differences', 'event denominators equal all valid capacity',
                   'Fig. 1 exposure-based event order', 'four-model equal weighting', 'catalogue capacity coverage'],
        'event_order': order, 'capacity_coverage_pct': [float(coverage.capacity_coverage_pct.min()),
                                                       float(coverage.capacity_coverage_pct.max())],
        'negative_event_model_values': int(e.R.lt(0).sum()), 'zero_event_model_values': int(e.R.eq(0).sum()),
        'input_sha256': {str(p.relative_to(ROOT)): digest(p) for p in inputs},
        'support': 'Common finite annual fields across climates, models, events and ten years within each deployment snapshot',
        'limitation': 'Annual Loss validity does not establish identical valid three-hourly timestamps',
        'units': UNIT, 'wind_energy_scale': 1,
    }
    write_json(OUT / 'data_audit.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return annual_display, contrasts, contrast_display, event_display, order


def label(fig, x, y, letter, title):
    fig.text(x, y, letter, fontsize=8, fontweight='bold', va='bottom')
    fig.text(x + 0.024, y, title, fontsize=7, va='bottom')


def main():
    a, models, c, e, order = audit()
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6.5, 'xtick.labelsize': 6, 'ytick.labelsize': 6,
                         'axes.linewidth': 0.6, 'xtick.major.size': 2, 'ytick.major.size': 2,
                         'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 165 / 25.4), facecolor='white')
    fig.legend([Line2D([], [], color=SSP_COLORS[s], marker=MARKERS[s], lw=1, ms=3.5)
                for s in SSPS], [s.upper() for s in SSPS], loc='upper center',
               bbox_to_anchor=(0.5, 0.995), ncol=3, fontsize=6.5)
    fig.text(0.5, 0.949, 'Paired climate and deployment pathways', ha='center', fontsize=6)
    annual_limits = (float(np.floor(a.minimum.min() / 10) * 10 - 5), float(a.maximum.max()) * 1.06)
    delta_limit = float(np.ceil(max(abs(c.minimum.min()), abs(c.maximum.max())) / 5) * 5 + 2)
    event_limits = (min(-2, float(e['mean'].min()) * 1.2), float(e['mean'].max()) * 1.08)
    for col, tech in enumerate(TECHS):
        left = 0.102 + col * 0.50
        width = 0.365
        ax = fig.add_axes([left, 0.678, width, 0.224])
        label(fig, left - 0.07, 0.912, 'ab'[col], tech.title() + ' | Annual net loss')
        for ssp in SSPS:
            for snap in SNAPSHOTS:
                g = a[a.tech.eq(tech) & a.climate_ssp.eq(ssp) & a.snapshot.eq(snap)].sort_values('year')
                ax.fill_between(g.year, g.minimum, g.maximum, color=SSP_COLORS[ssp], alpha=0.12, linewidth=0)
                ax.plot(g.year, g['mean'], color=SSP_COLORS[ssp], marker=MARKERS[ssp], ms=1.9,
                        lw=0.9, markeredgewidth=0)
        for year in [2040, 2050]:
            ax.axvline(year, color='#999999', ls=':', lw=0.55)
        ax.set(xlim=(2029.4, 2059.6), ylim=annual_limits, xticks=[2030, 2040, 2050, 2059],
               xlabel='Year', ylabel='Net loss (' + UNIT + ')')
        ax.grid(axis='y', color='#eeeeee', linewidth=0.4)
        ax.set_axisbelow(True)

        ax = fig.add_axes([left, 0.385, width, 0.19])
        label(fig, left - 0.07, 0.590, 'cd'[col], tech.title() + ' | Difference from SSP126')
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

        ax = fig.add_axes([left + 0.045, 0.105, width - 0.045, 0.171])
        label(fig, left - 0.07, 0.299, 'ef'[col], tech.title() + ' | Event losses, 2050–59')
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
    fig.text(0.5, 0.613, 'Lines and symbols: four-model means; shading: model min–max. Dotted lines: capacity snapshots.',
             ha='center', fontsize=6)
    fig.text(0.5, 0.320, 'Small open points: four models; large symbols: means; bars: model min–max.',
             ha='center', fontsize=6)
    fig.text(0.5, 0.039, 'Event labels may overlap; their losses cannot be added to recover the event union.',
             ha='center', fontsize=6)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    for artist in fig.findobj(Text):
        if artist.get_visible() and artist.get_text():
            box = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
            if box.x0 < -0.002 or box.y0 < -0.002 or box.x1 > 1.002 or box.y1 > 1.002:
                outside.append(artist.get_text())
    require(not outside, 'Text outside canvas: ' + repr(outside))
    fig.add_artist(Rectangle((0, 0), 1, 1, transform=fig.transFigure, fill=False, edgecolor='none', linewidth=0))
    save_png(fig, OUT / 'fig02.png')
    plt.close(fig)
    with Image.open(OUT / 'fig02.png') as im:
        info = {'pixels': list(im.size), 'dpi': list(im.info.get('dpi', []))}
        im.verify()
    metadata = {'created_utc': datetime.now(timezone.utc).isoformat(), 'slurm_job_id': os.getenv('SLURM_JOB_ID'),
                'figure': 'Fig. 2', 'panels': 'a–f', 'backend': 'matplotlib', 'size_mm': [183, 165],
                'image': info, 'annual_limits': annual_limits, 'difference_limits': [-delta_limit, delta_limit],
                'event_limits': event_limits, 'out_of_canvas_text': outside, 'n_models': 4,
                'model_offset_order': list(MODELS), 'event_order': order,
                'figure_sha256': digest(OUT / 'fig02.png'), 'code_sha256': digest(FOLDER / 'plot.py'),
                'source_sha256': {p.name: digest(p) for p in sorted(SOURCE.glob('*.csv'))}}
    (OUT / 'caption.md').write_text((FOLDER / 'caption.md').read_text(), encoding='utf-8')
    write_json(OUT / 'metadata.json', metadata)
    print(json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
