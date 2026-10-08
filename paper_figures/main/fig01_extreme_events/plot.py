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
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import MaxNLocator
from matplotlib.transforms import Bbox
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from PIL import Image
from paper_figures.config import ROOT, MODELS, SSPS, SSP_COLORS, TECHS, SNAPSHOTS, EVENTS
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
HOURS_PER_DAY = 24.0
MAP_LIMIT = 300 / HOURS_PER_DAY
CAPACITY_SCALE = 0.45
SCOPES = ('grid', 'stations')



def exposure_in_days(table, columns, filename):
    converted = table.copy()
    converted[columns] = table[columns] / HOURS_PER_DAY
    if not np.allclose(converted[columns] * HOURS_PER_DAY, table[columns],
                       rtol=1e-12, atol=1e-12, equal_nan=True):
        raise ValueError(f'Hour-to-day conversion failed: {filename}')
    converted['unit'] = 'day yr-1'
    converted.to_csv(SOURCE / filename, index=False)
    return converted


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


def export(fig, filename, bounds=None, close=True):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        bbox = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
        if bbox.x0 < -.002 or bbox.y0 < -.002 or bbox.x1 > 1.002 or bbox.y1 > 1.002:
            outside.append(artist.get_text())
    if outside:
        raise ValueError(f'Text outside figure canvas: {outside}')
    fig.add_artist(Rectangle((0, 0), 1, 1, transform=fig.transFigure, fill=False,
                             edgecolor='none', linewidth=0))
    if bounds is None:
        save_png(fig, OUT / filename)
    else:
        region = Bbox.from_extents(*bounds)
        for artist in fig.findobj(Text):
            if not artist.get_visible() or not artist.get_text():
                continue
            box = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
            if box.overlaps(region) and (box.x0 < region.x0 - .002 or box.y0 < region.y0 - .002
                                       or box.x1 > region.x1 + .002 or box.y1 > region.y1 + .002):
                raise ValueError(f'Group export clips text: {filename}: {artist.get_text()}')
        bbox = region.transformed(fig.transFigure).transformed(fig.dpi_scale_trans.inverted())
        fig.savefig(OUT / filename, dpi=600, bbox_inches=bbox, facecolor='white', pad_inches=0)
    if close:
        plt.close(fig)
    with Image.open(OUT / filename) as im:
        info = {'pixels': list(im.size), 'dpi': list(im.info.get('dpi', []))}
        im.verify()
    return {'path': filename, 'image': info, 'text_outside_canvas': outside,
            'sha256': digest(OUT / filename), 'figure_fraction_bounds': bounds}


def legends(fig, y, kind='trajectory'):
    handles = [Patch(facecolor=SSP_COLORS[s], edgecolor=SSP_COLORS[s], label=s.upper())
               for s in SSPS]
    fig.legend(handles=handles, loc='center', bbox_to_anchor=(.30, y),
               ncol=3, fontsize=6.2, columnspacing=1.25, handlelength=1.7)
    if kind == 'events':
        handles = [Line2D([], [], color='#404040', linewidth=.7,
                          label='Line: four-model min–max')]
        fig.legend(handles=handles, loc='center', bbox_to_anchor=(.76, y), fontsize=6)
    else:
        fig.text(.76, y, 'Lines and symbols: four-model means',
                 ha='center', va='center', fontsize=6)


def draw_trajectories(fig, trajectory):
    axis_settings = {}
    station_offset = .06
    for col, tech in enumerate(TECHS):
        label(fig, .025 + .5 * col, .680, 'cd'[col], f'{tech.title()} | Global union exposure')
        left, bottom, width, height = .105 + .50 * col, .447, .360, .207
        if tech == 'wind':
            ax = fig.add_axes([left, bottom, width, height])
            ax.set_ylim(800 / HOURS_PER_DAY, 1350 / HOURS_PER_DAY)
            ax.set_yticks([35, 39, 43, 47, 51, 55])
            ax.set_ylabel('Union exposure (day yr⁻¹)', labelpad=3, fontsize=6)
            scope_axes = dict.fromkeys(SCOPES, ax)
            axes = [ax]
        else:
            gap = .012
            lower_height = (height - gap) * 300 / 550
            upper_height = height - gap - lower_height
            lower = fig.add_axes([left, bottom, width, lower_height])
            upper = fig.add_axes([left, bottom + lower_height + gap, width, upper_height],
                                 sharex=lower)
            lower.set_ylim(550 / HOURS_PER_DAY, 850 / HOURS_PER_DAY)
            lower.set_yticks([25, 30, 35])
            upper.set_ylim(1200 / HOURS_PER_DAY, 1450 / HOURS_PER_DAY)
            upper.set_yticks([50, 55, 60])
            lower.spines['top'].set_visible(False)
            upper.spines['bottom'].set_visible(False)
            upper.tick_params(axis='x', bottom=False, labelbottom=False)
            for segment, y in ((lower, 1), (upper, 0)):
                segment.plot([0, 1], [y, y], transform=segment.transAxes,
                             linestyle='none', marker=[(-1, -.5), (1, .5)],
                             markersize=5, markeredgewidth=.7, color='#444444',
                             clip_on=False)
            fig.text(left + width, bottom + lower_height + gap / 2,
                     '35.42–50 omitted', ha='right', va='center', fontsize=5.5,
                     color='#555555')
            fig.text(left - .057, bottom + height / 2, 'Union exposure (day yr⁻¹)',
                     rotation=90, ha='center', va='center', fontsize=6)
            scope_axes = {'grid': upper, 'stations': lower}
            axes = [lower, upper]
        for ax in axes:
            ax.set_xlim(-.35, 2.35)
            ax.set_xticks(range(3), ['2030s', '2040s', '2050s'])
            ax.grid(axis='y', color='#dddddd', linewidth=.4, zorder=0)
        for scope in SCOPES:
            ax = scope_axes[scope]
            subset = trajectory[trajectory.tech.eq(tech) & trajectory.scope.eq(scope)]
            if subset['min'].min() < ax.get_ylim()[0] or subset['max'].max() > ax.get_ylim()[1]:
                raise ValueError(f'Trajectory range outside visible axis: {tech}/{scope}')
            for si, ssp in enumerate(SSPS):
                g = subset[subset.climate_ssp.eq(ssp)].set_index('snapshot').loc[list(SNAPSHOTS)]
                color = SSP_COLORS[ssp]
                if scope == 'grid':
                    xpos = np.arange(3)
                    ax.fill_between(xpos, g['min'].to_numpy(), g['max'].to_numpy(),
                                    color=color, alpha=.15, linewidth=0, zorder=1)
                    ax.plot(xpos, g['mean'], color=color, linewidth=1.1, zorder=3)
                else:
                    xpos = np.arange(3) + (si - 1) * station_offset
                    ax.errorbar(xpos, g['mean'], yerr=[g['mean'] - g['min'], g['max'] - g['mean']],
                                color=color, marker=MARKERS[ssp], linestyle='--',
                                linewidth=.8, elinewidth=.7, capsize=2.2, capthick=.65,
                                markersize=3.4, markeredgewidth=.65, markerfacecolor='white', zorder=4)
        ticks = [float(tick) for ax in axes for tick in ax.get_yticks()]
        if len(ticks) != 6:
            raise ValueError(f'Expected six trajectory y ticks: {tech}')
        axis_settings[tech] = {'visible_y_ranges': [list(ax.get_ylim()) for ax in axes],
                               'y_ticks': ticks, 'y_tick_count': len(ticks)}
    handles = [Patch(facecolor='#bbbbbb', edgecolor='#777777', alpha=.6,
                     label='Grid: solid line + min–max band'),
               Line2D([], [], color='#555555', marker='o', markerfacecolor='white',
                      markersize=3, linestyle='--', label='Stations: mean + min–max bars')]
    fig.legend(handles=handles, loc='center', bbox_to_anchor=(.5, .416),
               ncol=2, fontsize=6, handlelength=2.2, columnspacing=2)
    fig.text(.50, .388, '2030s = 2030–2039; 2040s = 2040–2049; 2050s = 2050–2059',
             ha='center', fontsize=6)
    return {'axes': axis_settings, 'station_ssp_offset': station_offset,
            'solar_omitted_y_range': [850 / HOURS_PER_DAY, 1200 / HOURS_PER_DAY], 'range_check': 'PASSED'}


def draw_changes(fig, changes, model_changes, earlier, later, main=False):
    selected = changes[changes.earlier.eq(earlier) & changes.later.eq(later) & changes.event.ne('all')]
    models = model_changes[model_changes.earlier.eq(earlier) & model_changes.later.eq(later)
                           & model_changes.event.ne('all')]
    limits = changes[changes.event.ne('all')]
    low, high = min(0, limits['min'].min()), max(0, limits['max'].max())
    pad = (high - low) * .06
    if main:
        legends(fig, .355, kind='events')
    for col, tech in enumerate(TECHS):
        if main:
            rect = [.143 + .50 * col, .070, .320, .243]
            label(fig, .025 + .5 * col, .330, 'ef'[col], f'{tech.title()} | 2050s − 2030s')
        else:
            rect = [.143 + .50 * col, .165, .320, .575]
            label(fig, .025 + .5 * col, .795, 'ab'[col], tech.title())
        ax = fig.add_axes(rect)
        rows = list(EVENTS[tech])
        subset = selected[selected.tech.eq(tech)].set_index(['event', 'climate_ssp', 'scope'])
        model_subset = models[models.tech.eq(tech)].set_index(['event', 'climate_ssp', 'scope', 'model'])
        for ei, event in enumerate(rows):
            if ei % 2 == 0:
                ax.axhspan(ei - .48, ei + .48, color='#f4f4f4', zorder=0)
            for si, ssp in enumerate(SSPS):
                for ki, scope in enumerate(SCOPES):
                    r = subset.loc[(event, ssp, scope)]
                    y = ei + (si - 1) * .32 + (ki - .5) * .13
                    color = SSP_COLORS[ssp]
                    ax.barh(y, r['mean'], height=.115, color=color if scope == 'grid' else 'white',
                            edgecolor=color, linewidth=.5, hatch=None if scope == 'grid' else '////', zorder=2)
                    values = np.array([model_subset.loc[(event, ssp, scope, model), 'difference']
                                       for model in MODELS], dtype=float)
                    if not np.isfinite(values).all() or not np.allclose(
                            [values.mean(), values.min(), values.max()], r[['mean', 'min', 'max']].to_numpy(dtype=float)):
                        raise ValueError(f'Model range disagrees with bars: {tech}/{event}/{ssp}/{scope}')
                    bars = ax.errorbar(r['mean'], y,
                                       xerr=[[r['mean'] - r['min']], [r['max'] - r['mean']]],
                                       fmt='none', ecolor='#404040', elinewidth=.7, capsize=0, zorder=4)
                    for line in bars.lines[2]:
                        line.set_capstyle('butt')
        ax.axvline(0, color='#555555', linewidth=.65, zorder=1)
        ax.set_xlim(low - pad, high + pad)
        ax.set_ylim(5.5, -.5)
        ax.set_yticks(range(len(rows)), [NAMES[e].replace('High temperature', 'High\ntemperature')
                                       .replace('Cold + high wind', 'Cold +\nhigh wind') for e in rows])
        ax.tick_params(axis='y', length=0, pad=3, labelsize=6)
        ax.set_xlabel('Change in exposure (day yr⁻¹)', fontsize=6, labelpad=3)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4, prune='both'))
        ax.grid(axis='x', color='#dddddd', linewidth=.4, zorder=0)
        ax.spines['left'].set_visible(False)
    handles = [Patch(facecolor='#999999', edgecolor='#666666', label='Grid · area-weighted'),
               Patch(facecolor='white', edgecolor='#666666', hatch='////', label='Stations · capacity-weighted')]
    fig.legend(handles=handles, loc='center', bbox_to_anchor=(.5, .026 if main else .055),
               ncol=2, fontsize=6, handlelength=2, columnspacing=2.8)


def main():
    import argparse
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--skip-prepare', action='store_true', help='Use existing audited source tables')
    args = parser.parse_args()
    if not args.skip_prepare:
        prepare()
    maps = pd.read_csv(SOURCE / 'panel_ab.csv.gz')
    bubbles = pd.read_csv(SOURCE / 'panel_ab_capacity.csv')
    trajectory = pd.read_csv(SOURCE / 'panel_cd_display.csv')
    changes = pd.read_csv(SOURCE / 'panel_event_summary.csv')
    model_changes = pd.read_csv(SOURCE / 'panel_event_changes.csv')
    identity = ['scope', 'tech', 'climate_ssp', 'event', 'earlier', 'later', 'model']
    if model_changes.duplicated(identity).any():
        raise ValueError('Duplicate model changes')
    audit = json.loads((OUT / 'data_audit.json').read_text())
    if audit['status'] != 'PASSED':
        raise ValueError('Fig. 1 source audit failed')
    for item in audit['inputs']:
        if digest(item['path']) != item['sha256']:
            raise ValueError(f"Audited input changed: {item['path']}")
    if not trajectory['count'].eq(4).all() or not changes['count'].eq(4).all():
        raise ValueError('Incomplete ensemble')
    maps = exposure_in_days(maps, ['mean', 'minimum', 'maximum'], 'panel_ab_days.csv.gz')
    trajectory = exposure_in_days(trajectory, ['mean', 'min', 'max'], 'panel_cd_display_days.csv')
    changes = exposure_in_days(changes, ['mean', 'min', 'max'], 'panel_event_summary_days.csv')
    model_changes = exposure_in_days(
        model_changes[identity + ['station_ssp', 'E_earlier', 'E_later', 'difference']],
        ['E_earlier', 'E_later', 'difference'], 'panel_event_changes_days.csv')
    if not np.allclose(model_changes['E_later'] - model_changes['E_earlier'],
                       model_changes['difference'], rtol=1e-10, atol=1e-10):
        raise ValueError('Exposure differences disagree after day conversion')
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6.5, 'xtick.labelsize': 6,
                         'ytick.labelsize': 6, 'axes.linewidth': .6,
                         'xtick.major.width': .5, 'ytick.major.width': .5,
                         'xtick.major.size': 2, 'ytick.major.size': 2,
                         'hatch.linewidth': .35, 'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 220 / 25.4), facecolor='white')
    pc = ccrs.PlateCarree()
    geo = countries()
    cmap = plt.get_cmap('RdBu_r')
    mapnorm = TwoSlopeNorm(vmin=-MAP_LIMIT, vcenter=0, vmax=MAP_LIMIT)
    for col, tech in enumerate(TECHS):
        left = 0.025 + col * 0.5
        ax = fig.add_axes([left + 0.015, 0.796, 0.435, 0.170], projection=pc)
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
        label(fig, left, 0.979, 'ab'[col], f'{tech.title()} | Grid exposure difference')
        ax.text(0.5, 1.012, '2050–2059 · climate SSP585 − SSP126',
                transform=ax.transAxes, ha='center', va='bottom', fontsize=6)
        ax.set_xticks([-120, 0, 120], crs=pc)
        ax.set_yticks([0, 60], crs=pc)
        ax.xaxis.set_major_formatter(LongitudeFormatter())
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(axis='both', labelsize=5.5, pad=2, length=2)
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=mapnorm, cmap=cmap),
                      cax=fig.add_axes([0.105, 0.762, 0.33, 0.009]), orientation='horizontal',
                      ticks=[-MAP_LIMIT, -MAP_LIMIT / 2, 0, MAP_LIMIT / 2, MAP_LIMIT], extend="both")
    cb.set_label('Grid exposure difference (day yr⁻¹)', labelpad=2)
    cb.outline.set_linewidth(0.4)
    size_legend(fig, [0.54, 0.746, 0.41, 0.040], [10, 50, 150], CAPACITY_SCALE,
                'Reference capacity\n(GW; SSP126, 2050)', '#8a8a8a', 'none')


    legends(fig, .716)
    trajectory_axes = draw_trajectories(fig, trajectory)
    draw_changes(fig, changes, model_changes, 2030, 2050, main=True)
    fig.text(.5, .005, 'Station pathways pair climate and deployment · Event types may overlap',
             ha='center', va='bottom', fontsize=6)
    products = [export(fig, 'fig01.png', close=False)]
    group_bounds = {'ab': [0, .726, 1, 1], 'cd': [0, .375, 1, .726], 'ef': [0, 0, 1, .373]}
    for group, bounds in group_bounds.items():
        products.append(export(fig, f'fig01_{group}.png', bounds=bounds, close=False))
    plt.close(fig)
    for earlier, later in ((2040, 2050), (2030, 2040)):
        fig = plt.figure(figsize=(183 / 25.4, 110 / 25.4), facecolor='white')
        fig.text(.5, .965, f'Event exposure change | {later}s − {earlier}s', ha='center', va='top', fontsize=8)
        legends(fig, .880, kind='events')
        draw_changes(fig, changes, model_changes, earlier, later)
        fig.text(.5, .008, 'Station pathways pair climate and deployment · Event types may overlap',
                 ha='center', va='bottom', fontsize=6)
        stem = f'event_changes_{later}s_minus_{earlier}s'
        products.append(export(fig, stem + '.png', close=False))
        products.append(export(fig, stem + '_ab.png', bounds=[0, 0, 1, 1]))

    caption = f"""# Fig. 1 | Spatial, temporal and event-type changes in extreme-event exposure

a–b, Wind and solar event-union exposure in 2050–2059 under climate SSP585 minus SSP126. Differences are calculated within each model and then averaged equally. Native cells common to the four models and three climates are area-weighted to a 1° display grid. Both Plate Carrée maps use a zero-centred ±{MAP_LIMIT} day yr⁻¹ colour scale with triangular extensions at both ends. Out-of-scale values retain their original values in source data and use saturated end colours. Original hour-based quantiles are recorded in data_audit.json; displayed day units and saturation fractions are recorded in metadata.json. Grey hollow circle area is proportional to SSP126 deployment capacity in the 2050 snapshot, aggregated to 3° cells (GW). Capacity does not weight map colours. Unavailable cells are uncoloured; China and Taiwan geometries are united.

c–d, Global event-union exposure in three ten-year windows. Each technology panel combines area-weighted grid exposure and capacity-weighted station exposure. Wind uses a continuous 33.33–56.25 day yr⁻¹ axis. Solar uses a broken axis retaining 22.92–35.42 and 50–60.42 day yr⁻¹ (rounded bounds); the omitted 35.42–50 interval contains no data or model ranges and is marked explicitly. Both panels have six labelled y ticks. The two solar segments use the same vertical scale per day. Solid grid lines show equal-model window means, with translucent bands spanning model minima–maxima. Station symbols are equal-model means, capped error bars are model minima–maxima, and dashed lines join window means. Only station SSP positions are offset by −0.06, 0 and +0.06 decade spacings to separate overlapping bars. Grid statistics cover all valid native cells in the 47-patch published domain, not just cells with stations. Grid support is common across models, climates and all three windows. Stations use each paired climate–deployment pathway and the corresponding 2030, 2040 or 2050 total-capacity snapshot. Thus station temporal changes include deployment and capacity-weight changes.

e–f, Change in annual event-specific exposure, 2050–2059 minus 2030–2039. Each event has three coloured SSP pairs: solid bars show area-weighted grid changes and hatched bars show capacity-weighted station changes. Bar length is the four-model mean of within-model differences; one dark-grey horizontal error bar spans the minimum to maximum of the four within-model differences. Error bars are plain straight lines with capsize=0 and flat stroke ends. Bar thickness and SSP spacing are shared across comparisons. The two standalone figures use identical encodings and axis limits for 2050s minus 2040s and 2040s minus 2030s. Types can overlap and must not be summed to obtain the event union. Near-zero bar lengths and model values remain at their actual values.

All panels and standalone temporal comparisons use day yr⁻¹, with 1 day = 24 hours. These are annual mean accumulated exposure durations, not counts of calendar days with any event. Models: CANESM5, MPI-ESM1-2-HR, MRI-ESM2-0 and BCC-CSM2-MR (n=4); ranges describe model spread, not confidence intervals. Each model contributes ten annual values per window. Missing time is not extrapolated; accepted preparation requires at least 99% temporal coverage. Grid coverage and station effective capacity are retained in source data. Meteorological exposure differs from the loss-valid event window. station_ssp585 originates from the SSP5-6.0 station file and is an independent deployment dimension.

Day-unit display data: panel_ab_days.csv.gz, panel_cd_display_days.csv, panel_event_summary_days.csv and panel_event_changes_days.csv; each includes a unit column. The preparation tables retain their audited hour units. Preparation source data: panel_ab.csv.gz, panel_ab_models.csv.gz and panel_ab_capacity.csv (maps); panel_cd_grid.csv and panel_cd_coverage.csv (union exposure and coverage); panel_event_windows.csv (model-resolved exposure windows); panel_event_changes.csv (paired temporal differences and endpoint weights); panel_cd_display.csv and panel_event_summary.csv (hour-based means and ranges); grid_coverage.csv (native support by patch and window). Input hashes and checks: data_audit.json. Independent group exports fig01_ab.png, fig01_cd.png and fig01_ef.png preserve the original letters, 600 dpi, and required legends/colour bar. Each additional temporal comparison also has an _ab.png group export.
"""
    (OUT / 'caption.md').write_text(caption, encoding='utf-8')
    names = ['panel_ab.csv.gz', 'panel_ab_models.csv.gz', 'panel_ab_capacity.csv',
             'panel_cd_grid.csv', 'panel_cd_coverage.csv', 'panel_event_windows.csv',
             'panel_event_changes.csv', 'panel_cd_display.csv', 'panel_event_summary.csv', 'grid_coverage.csv']
    visible = maps[maps.lat.between(-60, 85)]
    saturation = {tech: {'below': int((g['mean'] < -MAP_LIMIT).sum()),
                        'above': int((g['mean'] > MAP_LIMIT).sum()),
                        'fraction': float((g['mean'].abs() > MAP_LIMIT).mean()),
                        'visible_cells': len(g)} for tech, g in visible.groupby('tech')}
    write_json(OUT / 'metadata.json', {
        'figure': 'Fig. 1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'job_id': os.environ.get('SLURM_JOB_ID'), 'backend': 'Python/matplotlib + Cartopy',
        'archetype': 'quantitative grid', 'map_projection': 'Plate Carrée',
        'map_extent_degrees': [-180, 180, -60, 85], 'canvas_mm': [183, 220], 'dpi': 600,
        'panels': ['a', 'b', 'c', 'd', 'e', 'f'], 'products': products,
        'panel_groups': group_bounds,
        'exposure_unit': 'day yr-1', 'preparation_exposure_unit': 'h yr-1',
        'hours_per_day': HOURS_PER_DAY, 'unit_conversion_check': 'PASSED',
        'display_source_data': [{'path': str((SOURCE / name).relative_to(OUT)),
                                 'sha256': digest(SOURCE / name), 'unit': 'day yr-1'}
                                for name in ('panel_ab_days.csv.gz', 'panel_cd_display_days.csv',
                                             'panel_event_summary_days.csv', 'panel_event_changes_days.csv')],
        'trajectory_encoding': 'grid solid mean lines + min-max shading; station dashed mean lines + capped min-max bars; technology-specific y limits and solar axis break',
        'trajectory_axes': trajectory_axes,
        'event_encoding': 'mean bars + plain dark-grey min-max error bars',
        'event_bar_height': .115, 'event_ssp_spacing': .32,
        'event_errorbar_capsize': 0, 'event_errorbar_linewidth': .7, 'event_errorbar_capstyle': 'butt',
        'map_colour_limits': [-MAP_LIMIT, MAP_LIMIT], 'colourbar_extend': 'both',
        'map_colour_saturation': saturation, 'capacity_display_degrees': 3,
        'capacity_area_points2_per_gw': CAPACITY_SCALE,
        'temporal_comparisons': [[2050, 2030], [2050, 2040], [2040, 2030]],
        'grid_weighting': 'native area; common across models, climates and windows',
        'station_weighting': 'paired climate/deployment; corresponding total capacity snapshot',
        'ensemble': 'equal-model mean; trajectory min-max of n=4; event min-max of four within-model differences',
        'data_audit': 'PASSED', 'visual_review': 'PENDING',
        'source_data': [{'path': str((SOURCE / name).relative_to(OUT)), 'sha256': digest(SOURCE / name)} for name in names],
        'code_sha256': {p.name: digest(p) for p in (FOLDER / 'plot.py', FOLDER / 'prepare_data.py')}})
    print(json.dumps({'products': products, 'map_colour_saturation': saturation, 'data_audit': 'PASSED'}), flush=True)


if __name__ == '__main__':
    main()
