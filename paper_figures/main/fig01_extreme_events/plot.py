"""Render the complete six-panel Fig. 1 from audited, existing source tables."""
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
from matplotlib.text import Text
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from PIL import Image
from paper_figures.config import ROOT, MODELS, SSPS, SSP_COLORS, TECHS, SNAPSHOTS
from paper_figures.common.io import digest, write_json
from paper_figures.common.plotting import configure, save_png
from paper_figures.common.spatial import countries
from paper_figures.main.fig01_extreme_events.prepare_data import main as prepare

FOLDER = ROOT / 'paper_figures/main/fig01_extreme_events'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
NAMES = {'low_resource': 'Low resource', 'high_temp': 'High temperature',
         'icing': 'Icing', 'hot_humid': 'Hot–humid', 'high_wind': 'High wind',
         'high_humidity': 'High humidity', 'freezing_rain': 'Freezing rain',
         'rainstorm': 'Rainstorm', 'cold_highwind': 'Cold + high wind'}
MARKERS = {'ssp126': 'o', 'ssp245': 's', 'ssp585': '^'}
MAP_LIMIT = 1200
EVENT_LIMIT = 50
CAPACITY_SCALE = 0.45
EVENT_SCALE = 0.32


def label(fig, x, y, letter, title):
    fig.text(x, y, letter, fontsize=8, fontweight='bold', va='bottom')
    fig.text(x + 0.025, y, title, fontsize=7, va='bottom')


def size_legend(fig, rect, values, scale, title, edge, fill):
    ax = fig.add_axes(rect)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.text(0, 0.56, title, ha='left', va='center', fontsize=6)
    for x, value in zip([0.59, 0.75, 0.93], values):
        ax.scatter([x], [0.56], s=value * scale, facecolors=fill,
                   edgecolors=edge, linewidths=0.45, clip_on=False)
        ax.text(x, 0.08, str(value), ha='center', va='top', fontsize=6)
    return ax


def main():
    prepare()
    maps = pd.read_csv(SOURCE / 'panel_ab.csv.gz')
    bubbles = pd.read_csv(SOURCE / 'panel_ab_capacity.csv')
    trajectory = pd.read_csv(SOURCE / 'panel_cd.csv')
    events = pd.read_csv(SOURCE / 'panel_ef_display.csv')
    audit = json.loads((OUT / 'data_audit.json').read_text())
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6.5, 'xtick.labelsize': 6,
                         'ytick.labelsize': 6, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.5, 'ytick.major.width': 0.5,
                         'xtick.major.size': 2, 'ytick.major.size': 2,
                         'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 165 / 25.4), facecolor='white')
    pc = ccrs.PlateCarree()
    geo = countries()
    cmap = plt.get_cmap('RdBu_r')
    mapnorm = TwoSlopeNorm(vmin=-MAP_LIMIT, vcenter=0, vmax=MAP_LIMIT)
    eventnorm = TwoSlopeNorm(vmin=-EVENT_LIMIT, vcenter=0, vmax=EVENT_LIMIT)
    for col, tech in enumerate(TECHS):
        left = 0.025 + col * 0.5
        ax = fig.add_axes([left + 0.015, 0.735, 0.435, 0.215], projection=pc)
        ax.set_extent([-180, 180, -60, 85], crs=pc)
        ax.add_geometries([g for _, _, g in geo], pc, facecolor='#f4f4f4',
                          edgecolor='none', zorder=0)
        table = maps[maps.tech.eq(tech)]
        data = np.full((180, 360), np.nan)
        iy = (table.lat + 89.5).round().astype(int)
        ix = (table.lon + 179.5).round().astype(int)
        data[iy, ix] = table['mean'].to_numpy()
        ax.pcolormesh(np.arange(-180, 181), np.arange(-90, 91), data,
                      transform=pc, cmap=cmap, norm=mapnorm, shading='flat', zorder=1)
        ax.add_geometries([g for _, _, g in geo], pc, facecolor='none',
                          edgecolor='#666666', linewidth=0.22, zorder=2)
        b = bubbles[bubbles.tech.eq(tech)].sort_values('capacity_gw', ascending=False)
        ax.scatter(b.lon_bin, b.lat_bin, s=b.capacity_gw * CAPACITY_SCALE,
                   transform=pc, facecolors='none', edgecolors='#8a8a8a',
                   linewidths=0.22, alpha=0.45, zorder=3)
        ax.gridlines(xlocs=[-120, -60, 0, 60, 120], ylocs=[-30, 0, 30, 60],
                     linewidth=0.25, color='#888888', alpha=0.45, linestyle=':')
        ax.spines['geo'].set_linewidth(0.4)
        label(fig, left, 0.976, 'ab'[col], f'{tech.title()} | Grid event-hour difference')
        ax.text(0.5, 1.012, '2050–2059 · climate SSP585 − SSP126',
                transform=ax.transAxes, ha='center', va='bottom', fontsize=6)
        ax.set_xticks([-120, 0, 120], crs=pc)
        ax.set_yticks([0, 60], crs=pc)
        ax.xaxis.set_major_formatter(LongitudeFormatter())
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(axis='both', labelsize=5.5, pad=2, length=2)
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=mapnorm, cmap=cmap),
                      cax=fig.add_axes([0.105, 0.699, 0.33, 0.012]), orientation='horizontal',
                      ticks=[-1200, -600, 0, 600, 1200])
    cb.set_label('Grid event-hour difference (h yr⁻¹)', labelpad=2)
    cb.outline.set_linewidth(0.4)
    size_legend(fig, [0.54, 0.674, 0.41, 0.052], [10, 50, 150], CAPACITY_SCALE,
                'Reference capacity\n(GW; SSP126, 2050)', '#8a8a8a', 'none')

    handles = [Line2D([], [], color=SSP_COLORS[s], marker=MARKERS[s], markersize=3.5,
                       linewidth=1, label=s.upper()) for s in SSPS]
    fig.legend(handles=handles, loc='center', bbox_to_anchor=(0.36, 0.629),
               ncol=3, fontsize=6.3, columnspacing=1.6, handlelength=1.7)
    fig.text(0.72, 0.629, 'Small points: 4 models\nLarge symbols: mean; bars: min–max',
             ha='center', va='center', fontsize=6)
    for col, tech in enumerate(TECHS):
        x0 = 0.095 + 0.50 * col
        ax = fig.add_axes([x0, 0.410, 0.375, 0.177])
        label(fig, 0.025 + 0.50 * col, 0.596, 'cd'[col], f'{tech.title()} | Global exposure')
        for si, ssp in enumerate(SSPS):
            means = []
            xpos = np.arange(3) + (si - 1) * 0.13
            for wi, snap in enumerate(SNAPSHOTS):
                g = trajectory[trajectory.tech.eq(tech) & trajectory.climate_ssp.eq(ssp)
                               & trajectory.snapshot.eq(snap)].set_index('model').loc[list(MODELS)]
                v = g.E.to_numpy()
                means.append(v.mean())
                ax.vlines(xpos[wi], v.min(), v.max(), color=SSP_COLORS[ssp], lw=0.65, alpha=0.8)
                ax.scatter(xpos[wi] + np.linspace(-0.025, 0.025, 4), v, s=6,
                           color=SSP_COLORS[ssp], edgecolors='white', linewidth=0.15, zorder=4)
            ax.plot(xpos, means, color=SSP_COLORS[ssp], marker=MARKERS[ssp],
                    lw=1.0, ms=3.8, markeredgecolor='white', markeredgewidth=0.35, zorder=5)
        ax.set_xlim(-0.35, 2.35)
        ax.set_ylim(550, 1100)
        ax.set_yticks([600, 800, 1000])
        ax.set_xticks(range(3), ['2030–2039', '2040–2049', '2050–2059'])
        ax.set_ylabel('Union exposure (h yr⁻¹)', labelpad=3)
        ax.set_xlabel('Climate window / corresponding capacity snapshot', fontsize=5.8, labelpad=3)
        ax.grid(axis='y', color='#dddddd', linewidth=0.4, zorder=0)

    for col, tech in enumerate(TECHS):
        ax = fig.add_axes([0.185 + 0.5 * col, 0.125, 0.275, 0.197])
        label(fig, 0.025 + 0.5 * col, 0.344, 'ef'[col], f'{tech.title()} | Event types, 2050–2059')
        rows = audit['event_order'][tech]
        g = events[events.tech.eq(tech)].set_index(['event', 'climate_ssp'])
        for yi, event in enumerate(rows):
            ax.axhline(yi, color='#eeeeee', linewidth=0.4, zorder=0)
            for xi, ssp in enumerate(SSPS):
                r = g.loc[(event, ssp)]
                ax.scatter(xi, yi, s=r.exposure * EVENT_SCALE, c=[r.difference],
                           cmap=cmap, norm=eventnorm, edgecolors='#555555', linewidths=0.4)
                if 0 < r.exposure < 0.1:
                    ax.text(xi, yi, '<0.1', ha='center', va='center', fontsize=5.8, color='#444444')
                elif r.exposure == 0:
                    ax.plot(xi, yi, marker='x', color='#444444', ms=3)
        ax.set_xlim(-0.55, 2.55)
        ax.set_ylim(5.5, -0.5)
        ax.set_xticks(range(3), [s.upper() for s in SSPS])
        ax.set_yticks(range(len(rows)), [NAMES[e] for e in rows])
        ax.tick_params(axis='both', length=0, pad=5)
        for spine in ax.spines.values():
            spine.set_visible(False)
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=eventnorm, cmap=cmap),
                      cax=fig.add_axes([0.105, 0.068, 0.33, 0.012]),
                      orientation='horizontal', ticks=[-50, -25, 0, 25, 50])
    cb.set_label('Exposure difference vs SSP126 (h yr⁻¹)', labelpad=2)
    cb.outline.set_linewidth(0.4)
    size_legend(fig, [0.54, 0.039, 0.41, 0.065], [100, 300, 500], EVENT_SCALE,
                'Event exposure\n(h yr⁻¹)', '#555555', '#f7f7f7')
    fig.text(0.50, 0.004, 'Station panels: paired climate–deployment pathways · Event types can overlap',
             ha='center', va='bottom', fontsize=6)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        bbox = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
        if bbox.x0 < -0.002 or bbox.y0 < -0.002 or bbox.x1 > 1.002 or bbox.y1 > 1.002:
            outside.append(artist.get_text())
    if outside:
        raise ValueError(f'Text outside figure canvas: {outside}')
    # A figure-sized invisible artist makes the shared tight export retain the exact canvas.
    from matplotlib.patches import Rectangle
    fig.add_artist(Rectangle((0, 0), 1, 1, transform=fig.transFigure, fill=False,
                             edgecolor='none', linewidth=0))
    save_png(fig, OUT / 'fig01.png')
    plt.close(fig)
    with Image.open(OUT / 'fig01.png') as im:
        image_info = {'pixels': list(im.size), 'dpi': list(im.info.get('dpi', []))}
        im.verify()
    caption = """# Fig. 1 | Spatial, temporal and event-type differences in extreme-event exposure

a–b, Wind and solar grid event-union hours in 2050–2059 under climate SSP585 minus SSP126. Differences are calculated within each of four models, then averaged equally. Native cells common to all models and climate scenarios are area-weighted to a 1° display grid. Both maps use the Plate Carrée projection and share a symmetric ±1200 h yr⁻¹ colour scale; no values are clipped. Grey hollow circles have area proportional to the SSP126 deployment's 2050 total capacity, aggregated to a 3° display grid (GW). Capacity is a location reference, not a weight for grid climate differences. Unavailable climate cells are uncoloured; the valid domain is not restricted to land. China and Taiwan geometries are united in the map boundaries.

c–d, Global capacity-weighted annual hours in the union of selected meteorological events, averaged over 2030–2039, 2040–2049 and 2050–2059 with the corresponding fixed 2030, 2040 and 2050 capacity snapshots. Each SSP line pairs its climate and deployment scenario. Small points are four individual models, large symbols the equal-model mean, and vertical bars the model minimum–maximum, not confidence intervals. Small horizontal offsets separate pathways and model points; they do not represent dates within the window. Station locations and weights may change between pathways and snapshots. The y-axis range is shared across technologies.

e–f, Capacity-weighted exposure to individual events in 2050–2059. Circle area gives the four-model mean exposure (h yr⁻¹); colour gives the mean of within-model differences from the paired SSP126 pathway (h yr⁻¹). Rows decrease by SSP126 exposure within each technology; shared types retain their relative order. Both matrices share area and symmetric ±50 h yr⁻¹ colour scales. Wind high-wind exposure is positive but below 0.1 h yr⁻¹ in all three ensemble means; these values are labelled because their correctly scaled circles are smaller than a readable symbol. Zero would be marked by a cross, and missing data would not be assigned zero. No plotted cell is missing. Event types can overlap, so their exposures cannot be summed to recover the event union.

Models: CANESM5, MPI-ESM1-2-HR, MRI-ESM2-0 and BCC-CSM2-MR (n=4). Each model contributes ten annual values to each window; models and years are not treated as 40 independent climate realizations. Observed valid event hours are retained without extrapolating missing time. Source preparation requires at least 99% temporal coverage and uses the common station support defined by the accepted preparation campaign. Effective capacity and mean valid hours per year are retained in source_data/panel_cd_coverage.csv. This meteorological exposure is distinct from the loss-valid event window in annual Loss products. station_ssp585 originates from the SSP5-6.0 station file; it is an independent deployment dimension, not a synonym for the SSP585 climate pathway.

Source data: panel_ab.csv.gz and panel_ab_models.csv.gz (grid means and model differences); panel_ab_capacity.csv (reference capacity); panel_cd.csv and panel_cd_coverage.csv (trajectory and coverage); panel_ef.csv, panel_ef_models.csv and panel_ef_display.csv (event exposure, model differences and displayed ordering). Data checks, input hashes and coverage are recorded in data_audit.json. All source data are in this figure's outputs/source_data directory.
"""
    (OUT / 'caption.md').write_text(caption, encoding='utf-8')
    files = sorted(p for p in SOURCE.iterdir() if p.is_file())
    write_json(OUT / 'metadata.json', {
        'figure': 'Fig. 1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'job_id': os.environ.get('SLURM_JOB_ID'), 'backend': 'Python/matplotlib + Cartopy',
        'map_projection': 'Plate Carrée', 'map_extent_degrees': [-180, 180, -60, 85],
        'canvas_mm': [183, 165], 'image': image_info, 'dpi': 600,
        'panels': ['a', 'b', 'c', 'd', 'e', 'f'],
        'map_colour_limits': [-MAP_LIMIT, MAP_LIMIT], 'event_colour_limits': [-EVENT_LIMIT, EVENT_LIMIT],
        'trajectory_y_limits': [550, 1100],
        'capacity_display_degrees': 3, 'capacity_area_points2_per_gw': CAPACITY_SCALE, 'event_area_points2_per_hour': EVENT_SCALE,
        'map_values_clipped': int((maps['mean'].abs() > MAP_LIMIT).sum()),
        'event_values_clipped': int((events.difference.abs() > EVENT_LIMIT).sum()),
        'text_outside_canvas': outside, 'data_audit': 'PASSED',
        'visual_review': 'PENDING', 'png_sha256': digest(OUT / 'fig01.png'),
        'source_data': [{'path': str(p.relative_to(OUT)), 'sha256': digest(p)} for p in files],
        'code_sha256': {p.name: digest(p) for p in (FOLDER / 'plot.py', FOLDER / 'prepare_data.py')}})
    print(json.dumps({'png': str(OUT / 'fig01.png'), 'image': image_info, 'data_audit': 'PASSED'}), flush=True)


if __name__ == '__main__':
    main()
