"""Map observed 2025 GEM phases against the original LCOE candidate cells."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import matplotlib.ticker as mticker
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import numpy as np
import pandas as pd
from rasterio.transform import from_origin, rowcol

ROOT = Path(__file__).resolve().parents[3]
LCOE = ROOT / 'runtime/lcoe_gem_2025'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LCOE / 'LCOE'))
from prepare_baseline import grid_indices, rating_reference, solar_dc_capacity
from paper_figures.common.spatial import countries

HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
SOURCE = ROOT / 'data/stations/gem_2026_02'
EXTENT = (-180, 180, -60, 85)
COLORS = {'inside': '#0072B2', 'outside': '#D55E00'}
EXPECTED = {'solar': (70196, 40509), 'wind': (17759, 10076)}
DPI = 600


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare():
    paths = [SOURCE / 'raw/Global-Solar-Power-Tracker-February-2026.xlsx']
    reference = rating_reference(paths[0])
    tables, summary, audits = [], [], {}
    for tech, prefix in [('solar', 'solar_pv'), ('wind', 'wind')]:
        path = SOURCE / f'{prefix}_operating_start_year_le_2025.csv'
        original = pd.read_csv(path, low_memory=False)
        frame = original.copy()
        if tech == 'wind':
            frame = frame[frame['Installation Type'].isin(['Onshore', 'Unknown'])].copy()
        if frame['GEM phase ID'].duplicated().any() or not frame.Status.eq('operating').all():
            raise ValueError('Unexpected phase identity or status')
        if not pd.to_numeric(frame['Start year']).le(2025).all():
            raise ValueError('Non-historical phase')
        capacity = frame['Capacity (MW)'].to_numpy(float)
        if tech == 'solar':
            capacity, factor, level = solar_dc_capacity(frame, reference)
        else:
            factor, level = np.ones(len(frame)), np.full(len(frame), 'wind_nameplate')
        ids, parent_ids = grid_indices(frame.Latitude, frame.Longitude)
        cache = LCOE / f'cache/{tech}/child_lin_idx.npy'
        records = np.load(cache, mmap_mode='r')
        candidates = np.unique(records)
        inside = np.isin(ids, candidates)
        if (len(frame), int((~inside).sum())) != EXPECTED[tech]:
            raise ValueError(f'Coverage counts changed for {tech}')
        longitude = frame.Longitude.to_numpy(float)
        latitude = frame.Latitude.to_numpy(float)
        if not (np.isfinite(capacity).all() and (capacity > 0).all()):
            raise ValueError('Invalid capacity')
        if not ((latitude >= EXTENT[2]) & (latitude <= EXTENT[3])).all():
            raise ValueError('Map extent excludes a source phase')
        # An independent affine transform checks non-boundary records. Exact
        # boundaries use the explicit east/south convention in grid_indices.
        r, c = rowcol(from_origin(-180, 90, .1, .1), longitude, latitude)
        yr, xc = (90-latitude)*10, (longitude+180)*10
        interior = (np.abs(yr-np.rint(yr)) > 1e-7) & (np.abs(xc-np.rint(xc)) > 1e-7)
        reference_ids = np.asarray(r)*3600+np.asarray(c)
        if not np.array_equal(ids[interior], reference_ids[interior]):
            raise ValueError('Independent grid mapping differs')
        table = pd.DataFrame({
            'snapshot_year': 2025, 'technology': tech, 'gem_phase_id': frame['GEM phase ID'],
            'project_name': frame['Project Name'], 'country': frame['Country/Area'],
            'latitude': latitude, 'longitude': longitude, 'start_year': frame['Start year'],
            'location_accuracy': frame['Location accuracy'],
            'installation_type': frame['Installation Type'] if tech == 'wind' else 'not_applicable',
            'raw_capacity_mw': frame['Capacity (MW)'],
            'source_capacity_rating': frame['Capacity Rating'] if tech == 'solar' else 'MW',
            'capacity_mw': capacity, 'capacity_unit': 'MWp' if tech == 'solar' else 'MW',
            'capacity_conversion_factor': factor, 'conversion_geography': level,
            'child_grid_id': ids, 'parent_grid_id': parent_ids,
            'inside_candidate_grid': inside, 'candidate_membership': np.where(inside, 'inside', 'outside'),
        }).reset_index(drop=True)
        for label, selected in [('inside', inside), ('outside', ~inside)]:
            sub = table.loc[selected]
            summary.append(dict(technology=tech, candidate_membership=label, phase_count=len(sub),
                                percentage=100*len(sub)/len(table), unique_01deg_cells=sub.child_grid_id.nunique(),
                                capacity_mw=float(sub.capacity_mw.sum()), capacity_unit=table.capacity_unit.iloc[0]))
        audits[tech] = dict(input_phases=len(original), retained_phases=len(frame),
                           excluded_installation_type_phases=len(original)-len(frame),
                           candidate_records=len(records), unique_candidate_cells=len(candidates),
                           extra_records_sharing_candidate_cells=len(records)-len(candidates),
                           independent_transform_checked_phases=int(interior.sum()),
                           boundary_convention_phases=int((~interior).sum()),
                           installation_type_counts=table.installation_type.value_counts().to_dict())
        paths.extend([path, cache])
        tables.append(table)
    table = pd.concat(tables, ignore_index=True)
    if table.duplicated(['technology', 'gem_phase_id']).any():
        raise ValueError('Duplicate source phase')
    summary = pd.DataFrame(summary)
    source_out = OUT / 'source_data'
    source_out.mkdir(parents=True, exist_ok=True)
    table.to_csv(source_out / 'stations_2025_candidate_membership.csv', index=False, float_format='%.12g')
    summary.to_csv(source_out / 'coverage_summary.csv', index=False, float_format='%.12g')
    paths.extend([LCOE / 'LCOE/prepare_baseline.py', HERE / 'plot.py', HERE / 'figure_contract.json'])
    metadata = dict(passed=True, projection='PlateCarree', source_release='GEM February 2026',
                    snapshot_year=2025, resolution_degrees=.1, scope='Solar PV; onshore and unknown wind only',
                    phase_count=len(table), input_sha256={str(p):sha256(p) for p in paths}, technologies=audits,
                    classification='Original LCOE cache containing-cell membership; outside is not a physical-unsuitability diagnosis',
                    displayed_coordinates='Original GEM phase coordinates; overlapping phases remain separate in source CSV',
                    capacity_basis='Solar MWp/DC; known AC divided by .87; unknown GEM AC estimate divided by .87',
                    extent=list(EXTENT), point_order_seed=2025, point_size_points_squared=.65)
    return table, summary, metadata


def panel(ax, frame, summary, geometries, letter, title):
    projection = ccrs.PlateCarree()
    ax.set_extent(EXTENT, crs=projection)
    ax.set_facecolor('white')
    ax.add_geometries([g for iso, name, g in geometries], crs=projection,
                      facecolor='#F2F2F2', edgecolor='#B8B8B8', linewidth=.24, zorder=1)
    shuffled = frame.sample(frac=1, random_state=2025)
    ax.scatter(shuffled.longitude, shuffled.latitude, s=.65,
               c=shuffled.candidate_membership.map(COLORS), alpha=.83, linewidths=0,
               transform=projection, zorder=3)
    grid = ax.gridlines(crs=projection, draw_labels=True, linewidth=.3, color='#CCCCCC',
                       alpha=.6, linestyle=':', zorder=2)
    grid.top_labels = grid.right_labels = False
    grid.xlocator = mticker.FixedLocator([-120, -60, 0, 60, 120, 180])
    grid.ylocator = mticker.FixedLocator([-60, -30, 0, 30, 60])
    grid.xformatter, grid.yformatter = LONGITUDE_FORMATTER, LATITUDE_FORMATTER
    grid.xlabel_style = grid.ylabel_style = {'size': 7, 'color': '#555555'}
    ax.spines['geo'].set_linewidth(.5)
    ax.spines['geo'].set_edgecolor('#A0A0A0')
    ax.text(0, 1.035, f'{letter}  {title}', transform=ax.transAxes,
            ha='left', va='bottom', fontsize=9, fontweight='bold', clip_on=False)
    ax.text(1, 1.035, f'{len(frame):,} project phases', transform=ax.transAxes,
            ha='right', va='bottom', fontsize=8, clip_on=False)
    handles=[]
    for label in ['inside', 'outside']:
        row=summary.loc[summary.candidate_membership.eq(label)].iloc[0]
        handles.append(Line2D([], [], linestyle='', marker='o', markersize=4,
                              markeredgewidth=0, color=COLORS[label],
                              label=f'{label.capitalize()}: {int(row.phase_count):,} ({row.percentage:.1f}%)'))
    ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(.5, -.105),
              frameon=False, ncol=2, fontsize=8, handletextpad=.35, columnspacing=2.4)


def main():
    table, summary, audit = prepare()
    geometry_path = ROOT / 'data/maps/natural_earth/ne_110m_admin_0_countries.shp'
    geometries = countries(geometry_path)
    if sum(iso == 'CHN' for iso, name, g in geometries) != 1 or any(iso == 'TWN' for iso, name, g in geometries):
        raise ValueError('Country geometry union was not applied')
    audit['map_sha256'] = {str(p):sha256(p) for p in geometry_path.parent.glob('ne_110m_admin_0_countries.*') if p.suffix in {'.shp','.shx','.dbf','.prj'}}
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':8,
                         'axes.linewidth':.6, 'legend.frameon':False,
                         'savefig.facecolor':'white'})
    panels=[('solar','a','Solar PV, 2025'),('wind','b','Onshore wind, 2025 (including unknown type)')]
    fig, axes = plt.subplots(2, 1, figsize=(183/25.4,174/25.4), subplot_kw={'projection':ccrs.PlateCarree()})
    fig.subplots_adjust(left=.07,right=.99,top=.95,bottom=.075,hspace=.39)
    for ax,(tech,letter,title) in zip(axes,panels):
        panel(ax,table[table.technology.eq(tech)],summary[summary.technology.eq(tech)],geometries,letter,title)
    full=OUT/'gem_2025_candidate_coverage.png'
    fig.savefig(full,dpi=DPI)
    plt.close(fig)
    for tech,letter,title in panels:
        fig, ax = plt.subplots(figsize=(183/25.4,85/25.4),subplot_kw={'projection':ccrs.PlateCarree()})
        fig.subplots_adjust(left=.07,right=.99,top=.86,bottom=.17)
        panel(ax,table[table.technology.eq(tech)],summary[summary.technology.eq(tech)],geometries,letter,title)
        fig.savefig(OUT/f'gem_2025_candidate_coverage_{letter}.png',dpi=DPI)
        plt.close(fig)
    audit['artifacts']={str(p.relative_to(OUT)):sha256(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='data_audit.json'}
    (OUT/'data_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    print(summary.to_string(index=False),flush=True)
    print('Created complete map, panels a/b, source CSV and audit. No siting pipeline executed.',flush=True)


if __name__ == '__main__':
    main()
