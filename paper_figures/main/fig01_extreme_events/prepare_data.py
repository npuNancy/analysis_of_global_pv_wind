"""Validate existing Fig. 1 tables and add only figure-specific display data."""
import json
import os
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.spatial import countries

FOLDER = ROOT / 'paper_figures/main/fig01_extreme_events'
SOURCE = FOLDER / 'outputs/source_data'


def require(condition, message):
    if not condition:
        raise ValueError(message)


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

    baseline = events[events.climate_ssp.eq('ssp126')][['model', 'tech', 'event', 'E']].rename(columns={'E': 'reference_E'})
    event_models = events.merge(baseline, on=['model', 'tech', 'event'], validate='many_to_one')
    event_models['difference'] = event_models.E - event_models.reference_E
    require(event_models[event_models.climate_ssp.eq('ssp126')].difference.eq(0).all(), 'Nonzero reference differences')
    union = trajectory[trajectory.snapshot.eq(2050)][['model', 'climate_ssp', 'tech', 'E']].rename(columns={'E': 'union_E'})
    check = event_models.merge(union, on=['model', 'climate_ssp', 'tech'], validate='many_to_one')
    require((check.E <= check.union_E + 1e-6).all(), 'Individual event exceeds event union')
    write_csv(SOURCE / 'panel_ef_models.csv', event_models)
    summary = event_models.groupby(['tech', 'climate_ssp', 'event'], as_index=False).agg(
        exposure=('E', 'mean'), difference=('difference', 'mean'),
        minimum=('E', 'min'), maximum=('E', 'max'), n_models=('model', 'size'))
    order = {}
    for tech in TECHS:
        order[tech] = summary[summary.tech.eq(tech) & summary.climate_ssp.eq('ssp126')].sort_values(
            ['exposure', 'event'], ascending=[False, True]).event.tolist()
    summary['row'] = [order[r.tech].index(r.event) for r in summary.itertuples()]
    write_csv(SOURCE / 'panel_ef_display.csv', summary)

    geo = countries()
    require(sum(iso == 'CHN' for iso, _, _ in geo) == 1 and all(iso != 'TWN' for iso, _, _ in geo),
            'China geometry merge')
    require(all(g.is_valid for _, _, g in geo), 'Invalid country geometry')
    grid_stats = {tech: dict(cells=int(len(g)), minimum=float(g['mean'].min()), maximum=float(g['mean'].max()))
                  for tech, g in maps.groupby('tech')}
    inputs = [SOURCE / n for n in ('panel_ab.csv.gz', 'panel_cd.csv', 'panel_ef.csv')]
    inputs += [model_map_path, bubble_path, refs_path, audit_path]
    write_json(FOLDER / 'outputs/data_audit.json', {
        'status': 'PASSED', 'job_id': os.environ.get('SLURM_JOB_ID'),
        'upstream_tasks_verified': 664, 'panel_rows': {'ab': len(maps), 'cd': len(trajectory), 'ef': len(events)},
        'grid': grid_stats, 'models': MODELS, 'windows': [[s, s + 9] for s in SNAPSHOTS],
        'event_order': order, 'reference_capacity_gw': bubbles.groupby('tech').capacity_gw.sum().to_dict(),
        'capacity_coverage_minimum': float(coverage.capacity_coverage_fraction.min()),
        'map_aggregation': '1 degree; native-cell area weighted on common model/climate support',
        'capacity_bubbles': '3 degrees; SSP126 deployment, 2050 total snapshot; area proportional to GW',
        'country_geometry': 'WGS84; China and Taiwan union; one CHN; all geometries valid',
        'inputs': [{'path': str(p), 'sha256': digest(p)} for p in inputs],
        'checks': ['complete panel/model/event/window matrices', 'map mean/min/max reproduced from model differences',
                   'event normalization and union bounds', 'reference capacity conserved',
                   'finite values and unique keys', 'capacity coverage', 'China geometry union'],
        'limitations': [
            'Meteorological exposure uses observed valid timestamps, without missing-time extrapolation.',
            'Shared station support does not establish identical timestamps with annual Loss.',
            'station_ssp585 originates from stations_SSP5-6.0.csv; climate_ssp585 and deployment are separate dimensions.',
            'Four models describe ensemble spread, not confidence intervals or significance.']})
    print(json.dumps({'status': 'PASSED', 'grid': grid_stats, 'event_order': order,
                      'trajectory_range': [trajectory.E.min(), trajectory.E.max()],
                      'event_range': [summary.exposure.min(), summary.exposure.max()],
                      'event_difference_range': [summary.difference.min(), summary.difference.max()],
                      'maximum_bubble_gw': bubbles.capacity_gw.max()}, default=float), flush=True)


if __name__ == '__main__':
    main()
