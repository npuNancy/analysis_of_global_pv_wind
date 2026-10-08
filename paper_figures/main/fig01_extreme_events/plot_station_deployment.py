"""Map station deployment by scenario and capacity snapshot on 1-degree or 3-degree grids."""
import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.patches import Patch, Wedge
from matplotlib.transforms import IdentityTransform
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter

from paper_figures.config import ROOT, SSPS, SNAPSHOTS, STATION_FILES, SHAPEFILE
from paper_figures.common.io import digest, write_json
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.common.spatial import countries

FOLDER = ROOT / 'paper_figures/main/fig01_extreme_events'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
COLORS = {'solar': '#D89028', 'wind': '#347CA3'}
CAPACITY_SCALE = 0.72
FIXED_MARKER_SIZE = 0.72
EXTENT = [-180, 180, -60, 85]


def aggregate(grid_size=1):
    tables, inputs, checks = [], [], []
    for ssp in SSPS:
        path = ROOT / 'data/stations' / STATION_FILES[ssp]
        parts, totals, counts = [], {}, {}
        for frame in pd.read_csv(path, chunksize=200000):
            required = ['year', 'type', 'lon', 'lat', 'capacity_gw']
            if not set(required).issubset(frame.columns):
                raise ValueError(f'Missing station fields: {path}')
            if frame[required].isna().any().any():
                raise ValueError(f'Missing station data: {path}')
            if not frame['type'].isin(['solar', 'wind']).all():
                raise ValueError(f'Unexpected technology: {path}')
            if not np.isfinite(frame[['year', 'lon', 'lat', 'capacity_gw']]).all().all():
                raise ValueError(f'Non-finite station data: {path}')
            if (frame.capacity_gw < 0).any() or not frame.lat.between(-90, 90).all():
                raise ValueError(f'Invalid capacity or latitude: {path}')
            if not frame.lon.between(-180, 360).all():
                raise ValueError(f'Unexpected longitude: {path}')
            frame = frame[frame.year.isin(SNAPSHOTS)].copy()
            for key, value in frame.groupby(['year', 'type']).capacity_gw.sum().items():
                totals[key] = totals.get(key, 0.0) + float(value)
            for key, value in frame.groupby(['year', 'type']).size().items():
                counts[key] = counts.get(key, 0) + int(value)
            frame = frame[frame.capacity_gw > 0].copy()
            lon = np.round((frame.lon.to_numpy() + 180) % 360 - 180, 8)
            lat = np.round(frame.lat.to_numpy(), 8)
            frame['lon_bin'] = np.floor(lon / grid_size).astype(int) * grid_size
            frame['lat_bin'] = np.minimum(np.floor(lat / grid_size).astype(int) * grid_size,
                                          90 - grid_size)
            parts.append(frame.groupby(['year', 'type', 'lon_bin', 'lat_bin'])
                         .capacity_gw.sum())
        grouped = pd.concat(parts).groupby(level=[0, 1, 2, 3]).sum()
        for year in SNAPSHOTS:
            for tech in ('solar', 'wind'):
                key = (year, tech)
                if key not in totals:
                    raise ValueError(f'Missing snapshot/technology: {ssp} {key}')
                actual = float(grouped.loc[key].sum())
                if not np.isclose(actual, totals[key], rtol=1e-12, atol=1e-10):
                    raise ValueError(f'Capacity conservation failed: {ssp} {key}')
                checks.append(dict(station_ssp=ssp, snapshot_year=year, tech=tech,
                                   input_rows=counts[key], input_gw=totals[key],
                                   aggregated_gw=actual, difference_gw=actual-totals[key]))
        wide = grouped.unstack('type', fill_value=0).reset_index()
        wide = wide.rename(columns={'year': 'snapshot_year', 'solar': 'solar_gw',
                                    'wind': 'wind_gw'})
        wide['lon'] = wide.lon_bin + grid_size / 2
        wide['lat'] = wide.lat_bin + grid_size / 2
        wide['total_gw'] = wide.solar_gw + wide.wind_gw
        wide['solar_share'] = wide.solar_gw / wide.total_gw
        wide['station_ssp'] = ssp
        wide['source_file'] = path.name
        wide['period'] = wide.snapshot_year.astype(str) + 's'
        if not wide.lon.between(EXTENT[0], EXTENT[1]).all() or not wide.lat.between(EXTENT[2], EXTENT[3]).all():
            raise ValueError('Station capacity lies outside map extent')
        tables.append(wide)
        inputs.append(dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size))
        print(f'{ssp}: {len(wide)} occupied snapshot-grid cells; capacity checks passed', flush=True)
    result = pd.concat(tables, ignore_index=True)
    if result.duplicated(['station_ssp', 'snapshot_year', 'lon_bin', 'lat_bin']).any():
        raise ValueError('Duplicate aggregated cell')
    print('Cell total capacity (GW):', result.total_gw.quantile([0, .5, .9, .99, 1]).to_dict(), flush=True)
    return result, inputs, checks


def draw_bubbles(ax, panel, projection, fixed_size=False):
    # A radius of 0.5 matches the standard scatter circle; s is diameter squared.
    panel = panel.sort_values('total_gw', ascending=False)
    paths, sizes, offsets, colors = [], [], [], []
    for row in panel.itertuples(index=False):
        split = 90 + 360 * row.solar_share
        for start, stop, color, capacity in (
                (90, split, COLORS['solar'], row.solar_gw),
                (split, 450, COLORS['wind'], row.wind_gw)):
            if capacity <= 0:
                continue
            paths.append(Wedge((0, 0), .5, start, stop).get_path())
            sizes.append(FIXED_MARKER_SIZE if fixed_size else row.total_gw * CAPACITY_SCALE)
            offsets.append((row.lon, row.lat))
            colors.append(color)
    collection = PathCollection(paths, sizes=sizes, offsets=offsets,
                                offset_transform=projection._as_mpl_transform(ax),
                                facecolors=colors, edgecolors='none', linewidths=0,
                                antialiaseds=True, zorder=3)
    collection.set_transform(IdentityTransform())
    ax.add_collection(collection)


def draw_map(ax, panel, geographies, projection, letter, show_lon, show_lat, fixed_size=False):
    ax.set_extent(EXTENT, crs=projection)
    ax.add_geometries([g for _, _, g in geographies], crs=projection,
                      facecolor='#F2F3F3', edgecolor='#B1B7BB', linewidth=.22,
                      zorder=1)
    ax.gridlines(crs=projection, xlocs=[-120, -60, 0, 60, 120],
                 ylocs=[-30, 0, 30, 60], linewidth=.22,
                 color='#D5D9DC', alpha=.7, zorder=2)
    ax.set_xticks([-120, 0, 120] if show_lon else [], crs=projection)
    ax.set_yticks([-30, 0, 60] if show_lat else [], crs=projection)
    ax.xaxis.set_major_formatter(LongitudeFormatter())
    ax.yaxis.set_major_formatter(LatitudeFormatter())
    ax.tick_params(labelsize=6, length=2, width=.4, pad=2)
    ax.spines['geo'].set_edgecolor('#7C858C')
    draw_bubbles(ax, panel, projection, fixed_size=fixed_size)
    ax.text(.015, .96, letter, transform=ax.transAxes,
            va='top', fontsize=8, fontweight='bold', zorder=5)


def draw_legends(fig, technology_y, capacity_rect, note_y, source_y, snapshot_note, fixed_size=False, grid_size=1):
    fig.legend(handles=[Patch(facecolor=COLORS['solar'], label='Solar PV'),
                        Patch(facecolor=COLORS['wind'], label='Wind')],
               loc='center left', bbox_to_anchor=(.07, technology_y), ncol=2,
               fontsize=7, columnspacing=1.4, handlelength=1.1)

    legend = fig.add_axes(capacity_rect)
    legend.set_xlim(0, 1)
    legend.set_ylim(0, 1)
    legend.axis('off')
    if fixed_size:
        legend.text(0, .62, 'Fixed-size markers', fontsize=7, va='center')
        legend.scatter([.47], [.65], s=FIXED_MARKER_SIZE,
                       color='#92999E', linewidths=0, clip_on=False)
        legend.text(.53, .62, f'One occupied {grid_size}° cell', fontsize=6.5, va='center')
        note = 'Circle size is fixed; coloured sectors show solar / wind capacity shares.'
    else:
        legend.text(0, .62, 'Total capacity (GW)', fontsize=7, va='center')
        capacities = [1, 10, 50] if grid_size == 1 else [10, 50, 100]
        for x, capacity in zip([.47, .65, .86], capacities):
            legend.scatter([x], [.65], s=capacity * CAPACITY_SCALE,
                           color='#92999E', linewidths=0, clip_on=False)
            legend.text(x, .04, str(capacity), fontsize=6.5, va='bottom', ha='center')
        note = 'Circle area ∝ total capacity; coloured sectors show solar / wind capacity shares.'
    fig.text(.075, note_y, note, fontsize=6.5, color='#535B61')
    fig.text(.075, source_y, snapshot_note,
             fontsize=6, color='#535B61')


def draw_2050s(table, geographies, fixed_size=False, grid_size=1):
    fig = plt.figure(figsize=(240 / 25.4, 75 / 25.4))
    projection = ccrs.PlateCarree()
    for col, ssp in enumerate(SSPS):
        ax = fig.add_axes([.075 + col * .306, .38, .287, .42],
                          projection=projection)
        panel = table[(table.station_ssp == ssp) & (table.snapshot_year == 2050)]
        draw_map(ax, panel, geographies, projection, 'cfi'[col],
                 show_lon=True, show_lat=col == 0, fixed_size=fixed_size)
        ax.set_title(ssp.upper(), fontsize=9, fontweight='bold', pad=7)
    fig.text(.52, .94, 'Global solar and wind deployment | 2050s', ha='center',
             fontsize=11, fontweight='bold')
    fig.text(.52, .855, f'{grid_size}° grid  |  Installed capacity snapshot  |  Plate Carrée',
             ha='center', fontsize=7, color='#535B61')
    draw_legends(fig, .22, [.39, .165, .575, .132], .115, .055,
                 '2050s uses the 2050 total capacity snapshot. SSP585 deployment source: SSP5-6.0.',
                 fixed_size=fixed_size, grid_size=grid_size)
    suffix = ('' if grid_size == 1 else f'_{grid_size}deg') + ('_fixed_size' if fixed_size else '')
    output = export_panel_png(fig, OUT / f'fig01_station_deployment_2050s{suffix}.png')
    output.update(figure_mm=[240, 75], rows=['2050s'], columns=list(SSPS),
                  original_panel_letters=['c', 'f', 'i'])
    return output


def main(fixed_size=False, grid_size=1):
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    table, inputs, checks = aggregate(grid_size=grid_size)
    source_path = SOURCE / f'station_deployment_{grid_size}deg.csv.gz'
    if fixed_size and source_path.exists():
        pd.testing.assert_frame_equal(table, pd.read_csv(source_path),
                                      check_dtype=False, check_names=False,
                                      rtol=1e-12, atol=1e-12)
    else:
        table.to_csv(source_path, index=False, compression='gzip')
    if grid_size == 3:
        fine_path = SOURCE / 'station_deployment_1deg.csv.gz'
        if fine_path.exists():
            fine = pd.read_csv(fine_path)
            for axis in ('lon_bin', 'lat_bin'):
                fine[axis] = np.floor(fine[axis] / grid_size).astype(int) * grid_size
            keys = ['station_ssp', 'snapshot_year', 'lon_bin', 'lat_bin']
            capacities = ['solar_gw', 'wind_gw']
            expected = fine.groupby(keys)[capacities].sum().sort_index()
            actual = table.set_index(keys)[capacities].sort_index()
            pd.testing.assert_frame_equal(actual, expected, check_dtype=False,
                                          check_names=False, rtol=1e-12, atol=1e-12)
            print('3-degree cells independently reproduced from 1-degree source data.', flush=True)
    geographies = countries()
    if sum(iso == 'CHN' for iso, _, _ in geographies) != 1 or any(
            iso == 'TWN' or not geom.is_valid for iso, _, geom in geographies):
        raise ValueError('Country geometry validation failed')
    if 'WGS_1984' not in SHAPEFILE.with_suffix('.prj').read_text():
        raise ValueError('Expected WGS84 geographic country boundaries')

    configure()
    plt.rcParams.update({'font.size': 7, 'axes.linewidth': .45})
    fig = plt.figure(figsize=(240 / 25.4, 148 / 25.4))
    projection = ccrs.PlateCarree()
    panels = []
    left, width, gap = .075, .287, .019
    bottoms = [.658, .414, .170]
    for row, ssp in enumerate(SSPS):
        fig.text(.021, bottoms[row] + .091, ssp.upper(), rotation=90,
                 va='center', ha='center', fontsize=9, fontweight='bold')
        for col, year in enumerate(SNAPSHOTS):
            x = left + col * (width + gap)
            ax = fig.add_axes([x, bottoms[row], width, .208], projection=projection)
            panel = table[(table.station_ssp == ssp) & (table.snapshot_year == year)]
            draw_map(ax, panel, geographies, projection, 'abcdefghi'[row * 3 + col],
                     show_lon=row == 2, show_lat=col == 0, fixed_size=fixed_size)
            if row == 0:
                ax.set_title(f'{year}s', fontsize=9, fontweight='bold', pad=7)
            mixed = (panel.solar_gw > 0) & (panel.wind_gw > 0)
            panels.append(dict(station_ssp=ssp, snapshot_year=year, cells=len(panel),
                               mixed_cells=int(mixed.sum()), total_gw=float(panel.total_gw.sum())))
    fig.text(.52, .954, 'Global solar and wind deployment', ha='center',
             fontsize=11, fontweight='bold')
    fig.text(.52, .918, f'{grid_size}° grid  |  Installed capacity snapshots  |  Plate Carrée',
             ha='center', fontsize=7, color='#535B61')
    draw_legends(fig, .097, [.39, .068, .575, .067], .047, .018,
                 '2030s / 2040s / 2050s use 2030 / 2040 / 2050 snapshots. SSP585 deployment source: SSP5-6.0.',
                 fixed_size=fixed_size, grid_size=grid_size)

    suffix = ('' if grid_size == 1 else f'_{grid_size}deg') + ('_fixed_size' if fixed_size else '')
    output = export_panel_png(fig, OUT / f'fig01_station_deployment{suffix}.png')
    output_2050s = draw_2050s(table, geographies, fixed_size=fixed_size, grid_size=grid_size)
    metadata = dict(slurm_job_id=os.environ.get('SLURM_JOB_ID'),
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    projection='Plate Carree', extent=EXTENT, figure_mm=[240, 148], grid_size_degrees=grid_size,
                    archetype='quantitative grid',
                    question='How does installed solar and wind capacity vary across deployment scenarios and snapshots?',
                    rows=list(SSPS), columns=[str(y)+'s' for y in SNAPSHOTS],
                    inputs=inputs, source_data=dict(path=str(source_path), sha256=digest(source_path)),
                    code_sha256=digest(__file__),
                    aggregation=f'Sum positive capacity separately by technology in half-open {grid_size}-degree cells; normalize longitude to [-180,180); plot cell centres.',
                    snapshots='Total installed capacity snapshots; no accumulation across years.',
                    model_and_climate='Not applicable: deployment inputs only.',
                    uncertainty='Not applicable: no climate-model aggregation or statistical inference.',
                    marker=('One equal-size pie circle per occupied grid cell; sectors show technology capacity shares.'
                            if fixed_size else
                            'One pie circle per occupied grid cell; area proportional to total GW; sector area proportional to technology GW.'),
                    scatter_size_pt2_per_gw=None if fixed_size else CAPACITY_SCALE,
                    fixed_scatter_size_pt2=FIXED_MARKER_SIZE if fixed_size else None, colors=COLORS,
                    capacity_checks=checks, panel_summary=panels,
                    zero_capacity='Zero-capacity rows excluded; no lower size threshold or clipping.',
                    missing_data='Non-finite/missing inputs fail validation.',
                    countries='CHN and TWN geometries merged into CHN; all output geometries valid.',
                    boundary_sha256={p.name: digest(p) for p in [
                        SHAPEFILE, SHAPEFILE.with_suffix('.dbf'), SHAPEFILE.with_suffix('.shx'),
                        SHAPEFILE.with_suffix('.prj')]},
                    output=output, output_2050s=output_2050s)
    write_json(OUT / f'station_deployment{suffix}_metadata.json', metadata)
    print(json.dumps({'output': output, 'output_2050s': output_2050s, 'panels': panels}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixed-size', action='store_true',
                        help='Export both layouts using equal-size grid-cell circles.')
    parser.add_argument('--grid-size', type=int, choices=(1, 3), default=1,
                        help='Grid-cell width in degrees.')
    args = parser.parse_args()
    main(fixed_size=args.fixed_size, grid_size=args.grid_size)
