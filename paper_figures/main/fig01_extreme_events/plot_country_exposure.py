"""Country grid/station exposure maps for the 2050s and their decadal change."""
import argparse
import itertools
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter

from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SHAPEFILE, INDEXES
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.spatial import countries, assign
from paper_figures.common.plotting import configure, export_panel_png

FOLDER = ROOT / 'paper_figures/main/fig01_extreme_events'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
EXTENT = [-180, 180, -60, 85]
KEYS = ['model', 'climate_ssp', 'tech', 'country']
TECH_LABELS = {'wind': 'Wind', 'solar': 'Solar PV'}
SSP_LABELS = dict(zip(SSPS, ['SSP1-2.6', 'SSP2-4.5', 'SSP5-8.5']))
DIAMETER_RATIO = .75
MAX_CIRCLE_AREA = 1000 * DIAMETER_RATIO ** 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def input_record(path):
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest(path))


def geometries():
    result = countries()
    require(sum(iso == 'CHN' for iso, _, _ in result) == 1, 'China must be one analysis unit')
    require(not any(iso == 'TWN' or not g.is_valid for iso, _, g in result), 'Invalid country geometry')
    require('WGS_1984' in SHAPEFILE.with_suffix('.prj').read_text(), 'Expected WGS84 boundaries')
    return result


def aggregate_grid(geographies, pilot=False):
    manifest = require_complete(OUTPUT / 'event_summary')
    require(set(manifest['models']) == set(MODELS), 'Incomplete climate models')
    patches = ['R02C08'] if pilot else manifest['patches']
    require(pilot or len(set(patches)) == 47, 'Expected 47 published patches')
    rows, inputs, checks = [], [], []
    for tech, patch in itertools.product(TECHS, patches):
        folder = OUTPUT / 'grid_events' / tech / patch
        receipt = require_complete(folder)
        require(set(receipt['models']) == set(MODELS) and set(receipt['climate_ssps']) == set(SSPS),
                'Incomplete grid cache scope')
        path = folder / 'period_hours.nc'
        inputs.extend(input_record(p) for p in [folder / 'complete.json', folder / 'sources.json', path])
        with xr.open_dataset(path) as ds:
            require(ds.event_hours.attrs['units'] == 'h yr-1', 'Unexpected grid exposure unit')
            common = ds.common_mask.astype(bool).all('snapshot').values
            area = ds.cell_area_km2.values.astype(float)
            xx, yy = np.meshgrid(ds.lon.values, ds.lat.values)
            ids = assign(xx[common], yy[common], geographies)
            weights = area[common]
            labels, codes = np.unique(ids, return_inverse=True)
            den = np.bincount(codes, weights=weights, minlength=len(labels))
            counts = np.bincount(codes, minlength=len(labels))
            require(np.allclose(den.sum(), weights.sum()), 'Grid area conservation')
            for model, ssp, snap in itertools.product(MODELS, SSPS, [2030, 2050]):
                values = ds.event_hours.sel(model=model, climate_ssp=ssp, snapshot=snap, event='all').values[common]
                require(np.isfinite(values).all() and (values >= 0).all(), 'Invalid common-support grid exposure')
                num = np.bincount(codes, weights=values * weights, minlength=len(labels))
                require(np.isclose(num.sum(), np.dot(values, weights)), 'Grid exposure numerator conservation')
                for i, country in enumerate(labels):
                    rows.append(dict(model=model, climate_ssp=ssp, tech=tech, snapshot=snap,
                                     country=country, area_event_hours=float(num[i]),
                                     valid_area_km2=float(den[i]), n_cells=int(counts[i])))
            checks.append(dict(tech=tech, patch=patch, valid_area_km2=float(weights.sum()),
                               n_cells=int(common.sum()), countries=len(labels)))
        print(f'Country grid: {tech}/{patch}', flush=True)
    grid = pd.DataFrame(rows).groupby(KEYS + ['snapshot'], as_index=False)[
        ['area_event_hours', 'valid_area_km2', 'n_cells']].sum()
    grid['grid_days'] = grid.area_event_hours / grid.valid_area_km2 / 24
    grid['event'] = 'all'
    grid['window_start'] = grid.snapshot
    grid['window_end'] = grid.snapshot + 9
    grid['station_ssp'] = 'not_applicable'
    grid['unit'] = 'day yr-1'
    return grid, inputs, checks


def prepare(pilot=False):
    for name in ['catalogues', 'event_summary', 'acceptance']:
        require_complete(OUTPUT / name)
    geographies = geometries()
    grid, inputs, checks = aggregate_grid(geographies, pilot=pilot)
    station_path = OUTPUT / 'event_summary/window.csv.gz'
    capacity_path = OUTPUT / 'catalogues/capacity_by_country.csv'
    inputs.extend(input_record(p) for p in [station_path, capacity_path,
                  OUTPUT / 'acceptance/complete.json', OUTPUT / 'event_summary/complete.json'])
    inputs.extend(input_record(p) for p in INDEXES.values())
    inputs.extend(input_record(SHAPEFILE.with_suffix(s)) for s in ['.shp', '.dbf', '.shx', '.prj'])
    station = pd.read_csv(station_path)
    station = station[station.event.eq('all') & station.climate_ssp.eq(station.station_ssp)
                      & station.snapshot.isin([2030, 2050])].copy()
    require(not station.duplicated(KEYS + ['snapshot']).any(), 'Duplicate station rows')
    require(np.isfinite(station.E).all() and station.capacity_mw.gt(0).all(), 'Invalid station metrics')
    require(np.allclose(station.E, station.capacity_event_hours / station.capacity_mw),
            'Capacity-weighted exposure normalization')
    require((station.capacity_event_hours <= station.capacity_valid_hours + .001).all(),
            'Event hours exceed observed valid hours')
    capacity = pd.read_csv(capacity_path)
    station = station.merge(capacity.rename(columns={'capacity_mw': 'catalogue_capacity_mw'}),
                            on=['station_ssp', 'tech', 'snapshot', 'country'], how='left', validate='many_to_one')
    mapped = station.country.ne('GLOBAL')
    require(station.loc[mapped, 'catalogue_capacity_mw'].notna().all(), 'Missing country capacity')
    station['capacity_coverage_fraction'] = station.capacity_mw / station.catalogue_capacity_mw
    require(station.loc[mapped, 'capacity_coverage_fraction'].between(0, 1 + 1e-9).all(), 'Invalid capacity coverage')
    station['station_days'] = station.E / 24
    station['window_start'] = station.snapshot
    station['window_end'] = station.snapshot + 9
    station['unit'] = 'day yr-1'
    # Preserve the original capacity-weighted numerator and denominator for every model.
    for key, group in station.groupby(['model', 'climate_ssp', 'tech', 'snapshot']):
        global_row = group[group.country.eq('GLOBAL')]
        others = group[group.country.ne('GLOBAL')]
        require(len(global_row) == 1, 'Missing global station reference')
        for column in ['capacity_mw', 'capacity_event_hours']:
            require(np.isclose(others[column].sum(), global_row.iloc[0][column]),
                    f'Station country/global conservation: {key} {column}')
    if pilot:
        write_json(OUT / 'country_exposure_pilot.json',
                   dict(status='PASSED', grid_patch_checks=checks, station_rows=len(station),
                        job_id=os.environ.get('SLURM_JOB_ID'), inputs=inputs))
        print('Representative two-technology grid patch and full station-table pilot PASSED', flush=True)
        return
    global_grid = grid.groupby(['model', 'climate_ssp', 'tech', 'snapshot'], as_index=False)[
        ['area_event_hours', 'valid_area_km2']].sum()
    previous = SOURCE / 'panel_cd_grid.csv'
    if previous.exists():
        ref = pd.read_csv(previous)
        ref = ref[ref.snapshot.isin([2030, 2050])]
        match = global_grid.merge(ref, on=['model', 'climate_ssp', 'tech', 'snapshot'],
                                  suffixes=('', '_ref'), validate='one_to_one')
        require(len(match) == 48, 'Incomplete global grid reproduction')
        for col in ['area_event_hours', 'valid_area_km2']:
            require(np.allclose(match[col], match[col + '_ref'], rtol=1e-7, atol=1e-4),
                    'Country aggregation does not reproduce accepted global ' + col)
        inputs.append(input_record(previous))
    cap = capacity[capacity.snapshot.eq(2050)].copy()
    cap['climate_ssp'] = cap.station_ssp
    cap['capacity_gw'] = cap.capacity_mw / 1000
    all_countries = sorted(set(grid.country) | set(cap.country))
    scaffold = pd.DataFrame(itertools.product(MODELS, SSPS, TECHS, all_countries), columns=KEYS)
    data = scaffold
    for snap in [2030, 2050]:
        columns = KEYS + ['grid_days', 'valid_area_km2', 'area_event_hours', 'n_cells']
        g = grid[grid.snapshot.eq(snap)][columns].rename(columns={c: f'{c}_{snap}' for c in columns if c not in KEYS})
        columns = KEYS + ['station_days', 'capacity_mw', 'capacity_coverage_fraction', 'capacity_event_hours', 'capacity_valid_hours']
        st = station[station.snapshot.eq(snap) & station.country.ne('GLOBAL')][columns].rename(
            columns={c: f'{c}_{snap}' for c in columns if c not in KEYS})
        data = data.merge(g, on=KEYS, how='left', validate='one_to_one').merge(st, on=KEYS, how='left', validate='one_to_one')
    data = data.merge(cap[['climate_ssp', 'tech', 'country', 'capacity_gw']],
                      on=['climate_ssp', 'tech', 'country'], how='left', validate='many_to_one')
    data['grid_change_days'] = data.grid_days_2050 - data.grid_days_2030
    data['station_change_days'] = data.station_days_2050 - data.station_days_2030
    data['station_ssp'] = data.climate_ssp
    data['event'] = 'all'
    data['capacity_snapshot'] = 2050
    data['unit'] = 'day yr-1'
    require(not data.country.eq('TWN').any(), 'China country records must be merged upstream')
    metrics = ['grid_days_2030', 'grid_days_2050', 'grid_change_days',
               'station_days_2030', 'station_days_2050', 'station_change_days']
    ensemble_rows = []
    for key, group in data.groupby(['climate_ssp', 'tech', 'country']):
        require(set(group.model) == set(MODELS) and len(group) == 4, 'Incomplete four-model rows')
        row = dict(zip(['climate_ssp', 'tech', 'country'], key))
        row.update(station_ssp=key[0], model='ensemble_mean', unit='day yr-1',
                   event='all', capacity_snapshot=2050, capacity_gw=group.capacity_gw.iloc[0])
        for metric in metrics:
            valid = group[metric].notna()
            row[metric + '_n_models'] = int(valid.sum())
            row[metric] = float(group[metric].mean()) if valid.all() else np.nan
            row[metric + '_min'] = float(group[metric].min()) if valid.all() else np.nan
            row[metric + '_max'] = float(group[metric].max()) if valid.all() else np.nan
        ensemble_rows.append(row)
    display = pd.DataFrame(ensemble_rows)
    files = {'country_exposure_grid_windows.csv.gz': grid,
             'country_exposure_station_windows.csv.gz': station,
             'country_exposure_models.csv.gz': data, 'country_exposure_display.csv': display}
    for filename, table in files.items():
        write_csv(SOURCE / filename, table)
    reference_capacity = cap.groupby(['climate_ssp', 'country']).capacity_gw.sum()
    reference_capacity = reference_capacity[reference_capacity.index.get_level_values('country').isin(
        [iso for iso, _, _ in geographies if iso != 'ATA'])]
    write_json(OUT / 'country_exposure_data_audit.json',
               dict(status='PASSED', created_utc=datetime.now(timezone.utc).isoformat(),
                    job_id=os.environ.get('SLURM_JOB_ID'), inputs=inputs, grid_patch_checks=checks,
                    reference_capacity_max_gw=float(reference_capacity.max()),
                    source_data=[input_record(SOURCE / name) for name in files],
                    checks=['country/global area and exposure conservation', 'country/global station conservation',
                            'accepted global grid reproduction', 'four models per ensemble',
                            'China merged geometry and records', 'units and capacity coverage'],
                    grid_support='All valid native cells common to four models, three climates and three windows.',
                    station_support='Accepted common station cohort within each deployment and snapshot; annual time coverage >=99%.',
                    station_change='2050 capacity-weighted exposure minus 2030 capacity-weighted exposure; includes deployment change.'))
    print('Country source data prepared and validated', flush=True)


def circle_area(capacity, maximum):
    return np.asarray(capacity) / maximum * MAX_CIRCLE_AREA


def circle_position(geometry):
    parts = list(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else [geometry]
    point = max(parts, key=lambda p: p.area).representative_point()
    return point.x, point.y


def draw_panel(ax, panel, features, cmap, norm, change, maximum, letter):
    projection = ccrs.PlateCarree()
    ax.set_extent(EXTENT, crs=projection)
    ax.set_facecolor('white')
    grid_metric = 'grid_change_days' if change else 'grid_days_2050'
    station_metric = 'station_change_days' if change else 'station_days_2050'
    circles = []
    for iso, _, geom in features:
        values = panel.loc[iso] if iso in panel.index else None
        value = values[grid_metric] if values is not None else np.nan
        ax.add_geometries([geom], crs=projection, facecolor=cmap(norm(value)) if np.isfinite(value) else '#DEDEDE',
                          edgecolor='#90969B', linewidth=.25, zorder=1)
        if values is not None and np.isfinite(values.capacity_gw) and values.capacity_gw > 0:
            circles.append((*circle_position(geom), values.capacity_gw, values[station_metric]))
    for lon, lat, cap, value in sorted(circles, key=lambda c: -c[2]):
        ax.scatter(lon, lat, s=circle_area(cap, maximum), transform=projection,
                   facecolor=[cmap(norm(value)) if np.isfinite(value) else '#A6A6A6'],
                   edgecolor='#242B30', linewidth=.38, zorder=3)
    ax.gridlines(crs=projection, xlocs=[-120, -60, 0, 60, 120], ylocs=[-30, 0, 30, 60],
                 linewidth=.2, color='#91999E', alpha=.3, zorder=2)
    ax.set_xticks([-120, 0, 120], crs=projection)
    ax.set_yticks([-30, 0, 60], crs=projection)
    ax.xaxis.set_major_formatter(LongitudeFormatter())
    ax.yaxis.set_major_formatter(LatitudeFormatter())
    ax.tick_params(labelsize=6, length=2, width=.35, pad=2)
    ax.spines['geo'].set_linewidth(.4)
    ax.spines['geo'].set_edgecolor('#92999F')
    ax.text(.014, .97, letter, transform=ax.transAxes, va='top', weight='bold', fontsize=8, zorder=4)


def draw(data, features, maximum, change, limit, techs=TECHS):
    full = len(techs) == 2
    height = 133 if full else 86
    fig = plt.figure(figsize=(240 / 25.4, height / 25.4))
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit) if change else Normalize(0, limit)
    cmap = plt.get_cmap('RdBu_r' if change else 'YlOrBr')
    title = 'Country extreme-event exposure | ' + ('2050s − 2030s' if change else '2050s')
    fig.text(.52, .957, title, ha='center', fontsize=10, weight='bold')
    fig.text(.52, .903 if full else .871,
             'Four-model mean  |  Fill: area-weighted grids  |  Circles: capacity-weighted stations',
             ha='center', fontsize=6.5, color='#40494F')
    for row, tech in enumerate(techs):
        bottom = [.562, .240][row] if full else .357
        map_height = .265 if full else .410
        for col, ssp in enumerate(SSPS):
            ax = fig.add_axes([.058 + .318 * col, bottom, .298, map_height], projection=ccrs.PlateCarree())
            panel = data[data.tech.eq(tech) & data.climate_ssp.eq(ssp)].set_index('country')
            letter = 'abcdef'[list(TECHS).index(tech) * 3 + col]
            draw_panel(ax, panel, features, cmap, norm, change, maximum, letter)
            if col > 0:
                ax.tick_params(axis='y', labelleft=False, length=0)
            ax.set_title(f'{TECH_LABELS[tech]} | {SSP_LABELS[ssp]}', loc='left', fontsize=7, pad=5)
    bar_y = .139 if full else .214
    cax = fig.add_axes([.090, bar_y, .43, .017 if full else .026])
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation='horizontal',
                      extend='both' if change else 'neither', extendfrac=.04)
    cb.set_label(('Exposure change' if change else 'Annual exposure') + ' (day yr⁻¹)  ·  fill and circles',
                 fontsize=7, labelpad=3)
    cb.ax.tick_params(labelsize=6, length=2, width=.4)
    cb.outline.set_linewidth(.4)
    power = 10 ** np.floor(np.log10(maximum))
    refs = [power / 10, power / 2, power]
    handles = [Line2D([], [], marker='o', linestyle='', markersize=np.sqrt(circle_area(v, maximum)),
                      markerfacecolor='#B4BAC0', markeredgecolor='#242B30', markeredgewidth=.38,
                      label=f'{v:,.0f}') for v in refs]
    fig.legend(handles=handles, title='2050 installed capacity (GW)', loc='center',
               bbox_to_anchor=(.758, bar_y + .005), ncol=3, fontsize=6, title_fontsize=7,
               handletextpad=.6, columnspacing=1.1)
    fig.text(.058, .048 if full else .069,
             'Gray: missing exposure. No circle: zero / unavailable capacity. Circle area ∝ GW.',
             fontsize=6, color='#465057')
    fig.text(.058, .018 if full else .024,
             '2030s / 2050s: 2030–2039 / 2050–2059. SSP585 deployment source: SSP5-6.0.',
             fontsize=6, color='#465057')
    stem = 'fig01_country_exposure_' + ('change_2050s_minus_2030s' if change else '2050s')
    suffix = '' if full else ('_abc' if techs[0] == 'wind' else '_def')
    return export_panel_png(fig, OUT / (stem + suffix + '.png'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--skip-prepare', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    if not args.skip_prepare:
        prepare(pilot=args.pilot)
    if args.pilot:
        return
    audit = json.loads((OUT / 'country_exposure_data_audit.json').read_text())
    for record in audit['source_data']:
        require(digest(__import__('pathlib').Path(record['path'])) == record['sha256'], 'Source table hash mismatch')
    data = pd.read_csv(SOURCE / 'country_exposure_display.csv')
    features = [g for g in geometries() if g[0] != 'ATA']
    data = data[data.country.isin([iso for iso, _, _ in features])].copy()
    maximum = audit['reference_capacity_max_gw']
    require(np.isclose(circle_area(4, maximum), 4 * circle_area(1, maximum)), 'Circle area is not linear')
    absolute_values = data[['grid_days_2050', 'station_days_2050']].to_numpy().ravel()
    absolute_values = absolute_values[np.isfinite(absolute_values)]
    absolute_limit = float(np.ceil(absolute_values.max() / 10) * 10)
    changes = data[['grid_change_days', 'station_change_days']].to_numpy().ravel()
    changes = changes[np.isfinite(changes)]
    # Symmetric robust range retains outliers in source data and marks saturation with extensions.
    change_limit = float(max(2.5, np.ceil(np.quantile(np.abs(changes), .95) / 2.5) * 2.5))
    configure()
    plt.rcParams.update({'axes.linewidth': .4})
    outputs = []
    for change, limit in [(False, absolute_limit), (True, change_limit)]:
        for techs in [TECHS, ('wind',), ('solar',)]:
            outputs.append(draw(data, features, maximum, change, limit, techs))
    saturation = {}
    for metric in ['grid_change_days', 'station_change_days']:
        saturation[metric] = []
        for (tech, ssp), group in data.groupby(['tech', 'climate_ssp']):
            v = group[metric].dropna()
            saturation[metric].append(dict(tech=tech, climate_ssp=ssp, valid_countries=len(v),
                minimum=float(v.min()), maximum=float(v.max()), below=int((v < -change_limit).sum()),
                above=int((v > change_limit).sum())))
    write_json(OUT / 'country_exposure_metadata.json', dict(
        created_utc=datetime.now(timezone.utc).isoformat(), job_id=os.environ.get('SLURM_JOB_ID'),
        code_sha256=digest(__file__), projection='PlateCarree', extent=EXTENT,
        archetype='quantitative grid', question='How do country grid and station exposure differ across pathways and decades?',
        rows=list(TECHS), columns=list(SSPS), unit='day yr-1', event='all: temporal union',
        model_statistic='Equal mean of all four model metrics; model-wise subtraction before averaging.',
        uncertainty='Model extrema retained in source data; no significance claim.',
        grid='Native-cell area-weighted exposure on common valid support; country assignment uses cell centres.',
        stations='Capacity-weighted exposure of accepted common station cohort within each snapshot.',
        station_change='2050s at 2050 capacity minus 2030s at 2030 capacity; climate and deployment both vary.',
        capacity='2050 total installed capacity of each pathway and technology, including capacity with unavailable exposure.',
        circle_area_reference='Reference map scale: 1000 pt² at maximum country wind+solar capacity; diameter multiplied by 0.75.',
        circle_diameter_ratio=DIAMETER_RATIO, max_circle_area_pt2=MAX_CIRCLE_AREA,
        reference_capacity_max_gw=maximum, absolute_limits=[0, absolute_limit],
        change_limits=[-change_limit, change_limit], change_extend='both',
        palettes={'absolute':'YlOrBr', 'change':'RdBu_r'}, shared_fill_circle_scale=True,
        saturation=saturation, outputs=outputs, data_audit='country_exposure_data_audit.json',
        source_data=audit['source_data'], visual_review='pending'))
    print(json.dumps({'outputs':outputs, 'absolute_limit':absolute_limit,
                      'change_limit':change_limit, 'saturation':saturation}, indent=2), flush=True)


if __name__ == '__main__':
    main()
