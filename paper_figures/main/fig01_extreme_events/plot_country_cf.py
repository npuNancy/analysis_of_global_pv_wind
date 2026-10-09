"""Country grid/station CF maps for the 2050s and their decadal change."""
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
    grid_metric = 'grid_change_cf' if change else 'grid_cf_2050'
    station_metric = 'station_change_cf' if change else 'station_cf_2050'
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
    cmap = plt.get_cmap('RdBu_r' if change else 'viridis')
    title = 'Country wind and solar capacity factors | ' + ('2050s − 2030s' if change else '2050s')
    fig.text(.52, .957, title, ha='center', fontsize=10, weight='bold')
    fig.text(.52, .903 if full else .871,
             'Four-model mean  |  Fill: mean grid CF  |  Circles: capacity-weighted CF',
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
                      extend='both' if change else 'max', extendfrac=.04)
    cb.set_label(('CF change' if change else 'Capacity factor') + ' (1)  ·  fill and circles',
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
             'Gray: missing CF. No circle: zero / unavailable capacity. Circle area ∝ GW.'
             + (' Colorbar tips: values beyond scale.' if change else ' Colorbar tip: CF > 0.3.'),
             fontsize=6, color='#465057')
    fig.text(.058, .018 if full else .024,
             '2030s / 2050s: 2030–2039 / 2050–2059. SSP585 deployment source: SSP5-6.0.'
             + (' Station change includes deployment.' if change else ''),
             fontsize=6, color='#465057')
    stem = 'fig01_country_cf_' + ('change_2050s_minus_2030s' if change else '2050s')
    suffix = '' if full else ('_abc' if techs[0] == 'wind' else '_def')
    return export_panel_png(fig, OUT / (stem + suffix + '.png'))



def main():
    audit = json.loads((OUT / 'country_cf_data_audit.json').read_text())
    require(audit['status'] == 'PASSED', 'CF preparation not validated')
    independent = OUT / 'country_cf_independent_check.json'
    if independent.exists():
        require(json.loads(independent.read_text())['status'] == 'PASSED', 'Independent CF check failed')
    for record in audit['source_data']:
        require(digest(__import__('pathlib').Path(record['path'])) == record['sha256'], 'CF source hash mismatch')
    data = pd.read_csv(SOURCE / 'country_cf_display.csv')
    features = [g for g in geometries() if g[0] != 'ATA']
    data = data[data.country.isin([iso for iso, _, _ in features])].copy()
    maximum = float(data.groupby(['climate_ssp', 'country']).capacity_gw.sum().max())
    changes = data[['grid_change_cf', 'station_change_cf']].to_numpy()
    absolute_limit = 0.3
    change_limit = float(max(.005, np.ceil(np.quantile(np.abs(changes[np.isfinite(changes)]), .95) / .005) * .005))
    require(0 < absolute_limit <= 1, 'Invalid absolute CF range')
    require(np.isclose(circle_area(4, maximum), 4 * circle_area(1, maximum)), 'Nonlinear circle area')
    configure()
    plt.rcParams.update({'axes.linewidth': .4})
    outputs = []
    for change, limit in [(False, absolute_limit), (True, change_limit)]:
        for techs in [TECHS, ('wind',), ('solar',)]:
            outputs.append(draw(data, features, maximum, change, limit, techs))
    saturation = []
    for metric in ['grid_change_cf', 'station_change_cf']:
        for (tech, ssp), group in data.groupby(['tech', 'climate_ssp']):
            values = group[metric].dropna()
            saturation.append(dict(metric=metric, tech=tech, climate_ssp=ssp,
                valid_countries=len(values), below=int((values < -change_limit).sum()),
                above=int((values > change_limit).sum()),
                minimum=float(values.min()) if len(values) else None,
                maximum=float(values.max()) if len(values) else None))
    write_json(OUT / 'country_cf_metadata.json', dict(
        created_utc=datetime.now(timezone.utc).isoformat(), job_id=os.environ.get('SLURM_JOB_ID'),
        code_sha256=digest(__file__), projection='PlateCarree', extent=EXTENT,
        boundary_inputs=[input_record(SHAPEFILE.with_suffix(s)) for s in ['.shp','.shx','.dbf','.prj']],
        capacity_inputs=[input_record(OUTPUT / 'catalogues' / f'capacity_{s}_{t}.csv.gz')
                         for s, t in itertools.product(SSPS, TECHS)],
        archetype='quantitative grid', rows=list(TECHS), columns=list(SSPS),
        question='How do national grid-mean and installed-capacity-weighted CF vary across SSPs and decades?',
        unit='1', windows={'2030s':[2030,2039], '2050s':[2050,2059]},
        model_statistic='Equal mean of four model results; changes computed within each model first.',
        uncertainty='Four-model extrema in source data; no significance claim.',
        grid=audit['grid'], temporal=audit['temporal'], stations=audit['stations'],
        station_change=audit['station_change'],
        capacity='2050 total installed capacity for each corresponding station SSP and technology.',
        station_ssp585_source='stations_SSP5-6.0.csv',
        absolute_limits=[0, absolute_limit], absolute_extend='max', change_limits=[-change_limit,change_limit],
        change_limit_quantile=.95, change_extend='both', saturation=saturation,
        palettes={'absolute':'viridis','change':'RdBu_r'}, shared_fill_circle_scale=True,
        reference_capacity_max_gw=maximum, max_circle_area_pt2=MAX_CIRCLE_AREA,
        source_data=audit['source_data'], independent_check=input_record(independent) if independent.exists() else None,
        outputs=outputs, visual_review='pending'))
    print(json.dumps(dict(outputs=outputs, absolute_limit=absolute_limit, change_limit=change_limit), indent=2), flush=True)

if __name__ == '__main__':
    main()
