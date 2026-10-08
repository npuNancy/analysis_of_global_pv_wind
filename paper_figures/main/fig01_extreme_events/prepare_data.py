"""Validate existing Fig. 1 tables and add only figure-specific display data."""
import json
import os
import numpy as np
import pandas as pd
import xarray as xr
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.spatial import countries

FOLDER = ROOT / 'paper_figures/main/fig01_extreme_events'
SOURCE = FOLDER / 'outputs/source_data'


def require(condition, message):
    if not condition:
        raise ValueError(message)



def grid_exposure():
    manifest = require_complete(OUTPUT / 'event_summary')
    patches = manifest['patches']
    require(len(patches) == 47 and len(set(patches)) == 47, 'Incomplete grid patch scope')
    parts, inputs, coverage = [], [], []
    for tech in TECHS:
        for patch in patches:
            folder = OUTPUT / 'grid_events' / tech / patch
            receipt = require_complete(folder)
            require(set(receipt['models']) == set(MODELS) and set(receipt['climate_ssps']) == set(SSPS),
                    'Incomplete grid cache')
            path = folder / 'period_hours.nc'
            inputs.extend([folder / 'complete.json', path])
            with xr.open_dataset(path) as ds:
                require(set(ds.event.values.astype(str)) == {'all', *EVENTS[tech]}, 'Grid event definitions')
                require(set(ds.snapshot.values) == set(SNAPSHOTS), 'Grid windows')
                common = ds.common_mask.astype(bool).all('snapshot')
                area = ds.cell_area_km2.where(common, 0)
                total_area = float(area.sum())
                count = int(common.sum())
                for snap in SNAPSHOTS:
                    available = float(ds.cell_area_km2.where(ds.common_mask.sel(snapshot=snap).astype(bool), 0).sum())
                    coverage.append(dict(tech=tech, patch=patch, snapshot=snap,
                                         valid_area_km2=total_area, window_available_area_km2=available,
                                         n_cells=count))
                hours = ds.event_hours.load()
                require(np.isfinite(hours.where(common, 0)).all().item(), 'Missing grid hours on common support')
                weighted = (hours.astype('float64').where(common, 0) * area).sum(['lat', 'lon'])
                table = weighted.to_dataframe(name='area_event_hours').reset_index()
                table['valid_area_km2'] = total_area
                table['n_cells'] = count
                table['tech'] = tech
                parts.append(table)
            print(f'Grid aggregation: {tech}/{patch}', flush=True)
    keys = ['model', 'climate_ssp', 'tech', 'snapshot', 'event']
    grid = pd.concat(parts).groupby(keys, as_index=False)[['area_event_hours', 'valid_area_km2', 'n_cells']].sum()
    require(grid.valid_area_km2.gt(0).all(), 'Empty global grid support')
    grid['E'] = grid.area_event_hours / grid.valid_area_km2
    grid['station_ssp'] = 'not_applicable'
    grid['scope'] = 'grid'
    grid['country'] = 'GLOBAL'
    grid['window_start'] = grid.snapshot
    grid['window_end'] = grid.snapshot + 9
    grid['weighting'] = 'native_cell_area'
    require(len(grid) == 468, 'Incomplete grid event/window matrix')
    return grid, inputs, pd.DataFrame(coverage)

def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    audit_path = ROOT / 'logs/paper_figures/completion_status/final_audit.json'
    audit = json.loads(audit_path.read_text())
    require(audit['verified_output_units'] == 664 and audit['acceptance']['status'] == 'PASSED',
            'The completed preparation campaign did not pass acceptance')
    for name in ('catalogues', 'grid_summary', 'event_summary', 'panel_events', 'acceptance'):
        require_complete(OUTPUT / name)
    maps = pd.read_csv(SOURCE / 'panel_ab.csv.gz')
    trajectory = pd.read_csv(SOURCE / 'panel_cd.csv')
    events = pd.read_csv(SOURCE / 'panel_ef.csv')
    require(len(trajectory) == 72 and len(events) == 132, 'Incomplete station panel matrix')
    for table, label in ((trajectory, 'cd'), (events, 'ef')):
        keys = ['model', 'climate_ssp', 'station_ssp', 'tech', 'snapshot', 'country', 'event']
        require(not table.duplicated(keys).any(), f'Duplicate {label} records')
        require(table.climate_ssp.eq(table.station_ssp).all(), 'Station panels require paired pathways')
        require(table.country.eq('GLOBAL').all(), 'Station panels require global results')
        require(np.isfinite(table[['capacity_mw', 'capacity_event_hours', 'capacity_valid_hours', 'E']]).all().all(),
                'Nonfinite station quantities')
        require((table.capacity_mw > 0).all() and (table.E >= 0).all(), 'Invalid capacity or exposure')
        require(np.allclose(table.E, table.capacity_event_hours / table.capacity_mw), 'Exposure normalization')
        require((table.capacity_event_hours <= table.capacity_valid_hours + 1e-3).all(), 'Exposure exceeds valid hours')
        for _, group in table.groupby(['tech', 'climate_ssp', 'snapshot', 'event']):
            require(set(group.model) == set(MODELS), 'Incomplete model coverage')
    for tech in TECHS:
        for ssp in SSPS:
            require(set(trajectory.query('tech == @tech and climate_ssp == @ssp').snapshot) == set(SNAPSHOTS),
                    'Missing trajectory window')
            e = events.query('tech == @tech and climate_ssp == @ssp')
            require(set(e.event) == set(EVENTS[tech]) and e.snapshot.eq(2050).all(), 'Wrong event scope')
    require(trajectory.event.eq('all').all(), 'Trajectory must use event union')
    require(maps.snapshot.eq(2050).all() and maps.n_models.eq(4).all(), 'Incomplete map coverage')
    require(not maps.duplicated(['tech', 'lat', 'lon']).any(), 'Duplicate map cells')
    require(np.isfinite(maps[['mean', 'minimum', 'maximum']]).all().all(), 'Nonfinite map values')

    model_map_path = OUTPUT / 'grid_summary/model_differences.csv.gz'
    model_maps = pd.read_csv(model_map_path)
    model_maps = model_maps[model_maps.snapshot.eq(2050)].copy()
    require(np.allclose(model_maps.difference, model_maps.ssp585 - model_maps.ssp126), 'Grid difference mismatch')
    keys = ['tech', 'snapshot', 'lat', 'lon']
    grouped = model_maps.groupby(keys).difference.agg(['mean', 'min', 'max', 'count']).reset_index()
    comparison = maps.merge(grouped, on=keys, suffixes=('', '_check'), validate='one_to_one')
    require(len(comparison) == len(maps) and len(model_maps) == 4 * len(maps), 'Grid model support mismatch')
    for a, b in [('mean', 'mean_check'), ('minimum', 'min'), ('maximum', 'max')]:
        require(np.allclose(comparison[a], comparison[b]), f'Map ensemble mismatch: {a}')
    require(comparison['count'].eq(4).all(), 'Missing grid models')
    model_sets = model_maps.groupby(keys).model.agg(lambda v: len(set(v)))
    require(model_sets.eq(4).all() and set(model_maps.model) == set(MODELS), 'Grid model identities')
    write_csv(SOURCE / 'panel_ab_models.csv.gz', model_maps)

    bubble_path = OUTPUT / 'catalogues/capacity_bubbles.csv'
    bubbles = pd.read_csv(bubble_path)
    bubbles = bubbles[bubbles.station_ssp.eq('ssp126')].copy()
    bubbles['lon_bin'] = np.floor((bubbles.lon_bin + 180) / 3) * 3 - 178.5
    bubbles['lat_bin'] = np.floor((bubbles.lat_bin + 90) / 3) * 3 - 88.5
    bubbles = bubbles.groupby(['station_ssp', 'tech', 'lon_bin', 'lat_bin'], as_index=False).capacity_mw.sum()
    bubbles['snapshot'] = 2050
    bubbles['capacity_gw'] = bubbles.capacity_mw / 1000
    require((bubbles.capacity_gw > 0).all(), 'Invalid reference bubbles')
    refs_path = OUTPUT / 'catalogues/capacity_by_country.csv'
    refs = pd.read_csv(refs_path)
    refs = refs[refs.station_ssp.eq('ssp126')]
    for tech in TECHS:
        expected = refs[refs.tech.eq(tech) & refs.snapshot.eq(2050)].capacity_mw.sum()
        require(np.isclose(bubbles[bubbles.tech.eq(tech)].capacity_mw.sum(), expected), 'Bubble capacity conservation')
    write_csv(SOURCE / 'panel_ab_capacity.csv', bubbles)

    coverage = trajectory.copy()
    all_refs = pd.read_csv(refs_path).groupby(['station_ssp', 'tech', 'snapshot']).capacity_mw.sum()
    coverage['catalogue_capacity_mw'] = [
        all_refs.loc[(r.station_ssp, r.tech, r.snapshot)] for r in coverage.itertuples()]
    coverage['capacity_coverage_fraction'] = coverage.capacity_mw / coverage.catalogue_capacity_mw
    coverage['mean_valid_hours_per_year'] = coverage.capacity_valid_hours / coverage.capacity_mw
    require(coverage.capacity_coverage_fraction.between(0, 1 + 1e-9).all(), 'Capacity coverage outside bounds')
    write_csv(SOURCE / 'panel_cd_coverage.csv', coverage)

    station_path = OUTPUT / 'event_summary/window.csv.gz'
    station = pd.read_csv(station_path)
    station = station[station.country.eq('GLOBAL') & station.climate_ssp.eq(station.station_ssp)].copy()
    station['scope'] = 'stations'
    station['window_start'] = station.snapshot
    station['window_end'] = station.snapshot + 9
    station['weighting'] = 'capacity'
    require(len(station) == 468, 'Incomplete station event/window matrix')
    for old, new in ((trajectory, station[station.event.eq('all')]),
                     (events, station[station.snapshot.eq(2050) & station.event.ne('all')])):
        identity = ['model', 'climate_ssp', 'station_ssp', 'tech', 'snapshot', 'event']
        merged = old.merge(new, on=identity, validate='one_to_one', suffixes=('_old', '_new'))
        require(len(merged) == len(old) and np.allclose(merged.E_old, merged.E_new),
                'Shared station summary does not reproduce existing panels')

    grid, grid_inputs, grid_coverage = grid_exposure()
    require(np.allclose(station.E, station.capacity_event_hours / station.capacity_mw),
            'Station normalization across all windows')
    require((station.capacity_event_hours <= station.capacity_valid_hours + 1e-3).all(),
            'Station event hours exceed valid time')
    display_path = OUTPUT / 'grid_summary/display_hours.csv.gz'
    grid_check = {'common_area_fraction': float(grid_coverage.valid_area_km2.sum()
                                               / grid_coverage.window_available_area_km2.sum())}
    if np.allclose(grid_coverage.valid_area_km2, grid_coverage.window_available_area_km2):
        display = pd.read_csv(display_path)
        keys = ['model', 'climate_ssp', 'tech', 'snapshot']
        display = display.groupby(keys, as_index=False)[['weighted_hours', 'area']].sum()
        display['display_E'] = display.weighted_hours / display.area
        match = grid[grid.event.eq('all')].merge(display, on=keys, validate='one_to_one')
        require(len(match) == 72, 'Missing grid union comparison')
        require(np.allclose(match.valid_area_km2, match.area), 'Grid area conservation')
        require(np.allclose(match.E, match.display_E, rtol=1e-7, atol=1e-4),
                'Native-grid exposure disagrees with accepted display-grid numerator/denominator')
        grid_check['union_reproduction_max_abs_hours'] = float((match.E - match.display_E).abs().max())
        grid_check['union_reproduction'] = 'PASSED'
    else:
        grid_check['union_reproduction'] = 'Different temporal support; direct equality not applicable'
    grid_inputs.append(display_path)
    write_csv(SOURCE / 'panel_cd_grid.csv', grid[grid.event.eq('all')])
    write_csv(SOURCE / 'grid_coverage.csv', grid_coverage)
    windows = pd.concat([grid, station], ignore_index=True)
    require(not windows.duplicated(['scope', 'model', 'climate_ssp', 'tech', 'snapshot', 'event']).any(),
            'Duplicate exposure records')
    require(np.isfinite(windows.E).all() and windows.E.ge(0).all(), 'Invalid exposure')
    for _, group in windows.groupby(['scope', 'tech', 'climate_ssp', 'snapshot', 'event']):
        require(set(group.model) == set(MODELS) and len(group) == 4, 'Incomplete four-model matrix')
    union = windows[windows.event.eq('all')][['scope', 'model', 'climate_ssp', 'tech', 'snapshot', 'E']]
    check = windows.merge(union.rename(columns={'E': 'union_E'}),
                          on=['scope', 'model', 'climate_ssp', 'tech', 'snapshot'], validate='many_to_one')
    require((check.E <= check.union_E + 1e-4).all(), 'Individual event exceeds union')
    write_csv(SOURCE / 'panel_event_windows.csv', windows)
    keys = ['scope', 'model', 'climate_ssp', 'station_ssp', 'tech', 'event']
    changes = []
    for earlier, later in ((2030, 2050), (2040, 2050), (2030, 2040)):
        a = windows[windows.snapshot.eq(earlier)]
        b = windows[windows.snapshot.eq(later)]
        pair = a.merge(b, on=keys, suffixes=('_earlier', '_later'), validate='one_to_one')
        require(len(pair) == 312, 'Incomplete paired temporal comparison')
        pair['earlier'] = earlier
        pair['later'] = later
        pair['difference'] = pair.E_later - pair.E_earlier
        changes.append(pair)
    changes = pd.concat(changes, ignore_index=True)
    write_csv(SOURCE / 'panel_event_changes.csv', changes)
    closure = changes.pivot(index=keys, columns=['earlier', 'later'], values='difference')
    require(np.allclose(closure[(2030, 2050)], closure[(2030, 2040)] + closure[(2040, 2050)],
                        rtol=1e-9, atol=1e-9), 'Temporal difference closure failed')
    event_summary = changes.groupby(['scope', 'tech', 'climate_ssp', 'event', 'earlier', 'later'],
                                    as_index=False).difference.agg(['mean', 'min', 'max', 'count']).reset_index()
    write_csv(SOURCE / 'panel_event_summary.csv', event_summary)
    trajectory_summary = windows[windows.event.eq('all')].groupby(
        ['scope', 'tech', 'climate_ssp', 'snapshot'], as_index=False).E.agg(['mean', 'min', 'max', 'count']).reset_index()
    write_csv(SOURCE / 'panel_cd_display.csv', trajectory_summary)
    order = {tech: list(EVENTS[tech]) for tech in TECHS}
    visible = maps[maps.lat.between(-60, 85)]
    colour_stats = {tech: {'absolute_quantiles': g['mean'].abs().quantile([.5, .9, .95, .98, .99]).to_dict(),
                          'limits': {str(limit): {'below': int((g['mean'] < -limit).sum()),
                                                 'above': int((g['mean'] > limit).sum()),
                                                 'saturated_fraction': float((g['mean'].abs() > limit).mean())}
                                     for limit in (100, 150, 200, 250, 300, 400, 600)},
                          'visible_cells': len(g)} for tech, g in visible.groupby('tech')}

    geo = countries()
    require(sum(iso == 'CHN' for iso, _, _ in geo) == 1 and all(iso != 'TWN' for iso, _, _ in geo),
            'China geometry merge')
    require(all(g.is_valid for _, _, g in geo), 'Invalid country geometry')
    grid_stats = {tech: dict(cells=int(len(g)), minimum=float(g['mean'].min()), maximum=float(g['mean'].max()))
                  for tech, g in maps.groupby('tech')}
    inputs = [SOURCE / n for n in ('panel_ab.csv.gz', 'panel_cd.csv', 'panel_ef.csv')]
    inputs += [model_map_path, bubble_path, refs_path, audit_path, station_path] + grid_inputs
    write_json(FOLDER / 'outputs/data_audit.json', {
        'status': 'PASSED', 'job_id': os.environ.get('SLURM_JOB_ID'),
        'upstream_tasks_verified': 664, 'panel_rows': {'ab': len(maps), 'cd': len(windows[windows.event.eq('all')]),
                       'event_windows': len(windows), 'event_changes': len(changes)},
        'grid_aggregation_check': grid_check,
        'grid': grid_stats, 'map_colour_diagnostics': colour_stats, 'grid_coverage': grid_coverage.to_dict('records'), 'models': MODELS, 'windows': [[s, s + 9] for s in SNAPSHOTS],
        'event_order': order, 'reference_capacity_gw': bubbles.groupby('tech').capacity_gw.sum().to_dict(),
        'capacity_coverage_minimum': float(coverage.capacity_coverage_fraction.min()),
        'map_aggregation': '1 degree; native-cell area weighted on common model/climate support',
        'capacity_bubbles': '3 degrees; SSP126 deployment, 2050 total snapshot; area proportional to GW',
        'country_geometry': 'WGS84; China and Taiwan union; one CHN; all geometries valid',
        'inputs': [{'path': str(p), 'sha256': digest(p)} for p in inputs],
        'checks': ['complete panel/model/event/window matrices', 'map mean/min/max reproduced from model differences',
                   'event normalization and union bounds', 'three temporal contrasts close within each model', 'native grid area aggregation', 'independent accepted grid-union reproduction when support matches', 'reference capacity conserved',
                   'finite values and unique keys', 'capacity coverage', 'China geometry union'],
        'limitations': [
            'Meteorological exposure uses observed valid timestamps, without missing-time extrapolation.',
            'Shared station support does not establish identical timestamps with annual Loss.',
            'station_ssp585 originates from stations_SSP5-6.0.csv; climate_ssp585 and deployment are separate dimensions.',
            'Four models describe ensemble spread, not confidence intervals or significance.']})
    print(json.dumps({'status': 'PASSED', 'grid': grid_stats, 'event_order': order,
                      'trajectory_range': [trajectory.E.min(), trajectory.E.max()],
                      'event_difference_range': [changes.difference.min(), changes.difference.max()],
                      'map_colour_diagnostics': colour_stats,
                      'maximum_bubble_gw': bubbles.capacity_gw.max()}, default=float), flush=True)


if __name__ == '__main__':
    main()
