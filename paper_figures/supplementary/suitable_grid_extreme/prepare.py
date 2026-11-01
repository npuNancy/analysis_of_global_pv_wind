"""Reduce accepted annual event caches on the fixed suitable-grid catalogue."""
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, SSPS, TECHS, EVENTS, SNAPSHOTS

HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
SOURCE = OUT / 'source_data'
CACHE = ROOT / 'RQ1_extreme/global/grid/outputs'
PERIOD = ROOT / 'paper_figures/prepare/outputs/grid_events'
MAPPING = ROOT / 'data/stations/suitable_grid_1mw/grid_mapping.csv.gz'
YEARS = np.arange(2030, 2060)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(2**20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def indices(axis, values):
    # Coordinate matching, never assume CF and event grids share row positions.
    require(len(np.unique(axis)) == len(axis), 'Duplicate cache axis')
    lookup = {round(float(x), 6): i for i, x in enumerate(axis)}
    require(len(lookup) == len(axis), 'Coordinate rounding collision')
    return np.array([lookup[round(float(x), 6)] for x in values], dtype=int)


def process(task):
    tech, patch, mapping, records = task
    events = ['all', *EVENTS[tech]]
    arrays, hours, nominal, provenance, sample_checks = [], [], [], [], []
    lat = lon = area = common = rr = cc = None
    index_disagreements = 0
    for model in MODELS:
        reference = pd.read_csv(CACHE / model / 'csv/patch_coverage.csv')
        for ssp in SSPS:
            record = records[(model, ssp, tech, patch)]
            path = CACHE / model / 'cache' / ssp / tech / (patch + '.nc')
            with netCDF4.Dataset(path) as ds:
                ds.set_auto_mask(False)
                require(ds.fingerprint == record['fingerprint'], f'Fingerprint: {path}')
                require((ds.model, ds.scenario, ds.tech, ds.patch) == (model, ssp, tech, patch), 'Cache identity')
                require(list(ds['event'][:]) == ['any', *EVENTS[tech]], 'Event definitions')
                require(np.isclose(ds.min_time_coverage, .99), 'Temporal coverage threshold')
                yy = list(ds['year'][:]); yi = [yy.index(y) for y in YEARS]
                this_lat, this_lon = ds['lat'][:], ds['lon'][:] % 360
                if lat is None:
                    lat, lon = this_lat, this_lon
                    rr = indices(lat, mapping.lat.values)
                    cc = indices(lon, mapping.lon.values % 360)
                    require(len(set(zip(rr, cc))) == len(mapping), 'Duplicate matched cells')
                    require(np.allclose(lat[rr], mapping.lat, atol=1e-6, rtol=0), 'Latitude alignment')
                    require(np.allclose(lon[cc], mapping.lon.values % 360, atol=1e-6, rtol=0), 'Longitude alignment')
                    index_disagreements = int(np.count_nonzero((rr != mapping.cf_lat_index) | (cc != mapping.cf_lon_index)))
                    area = ds['cell_area_km2'][:][rr, cc].astype(float)
                    require(np.isfinite(area).all() and (area > 0).all(), 'Cell area')
                    common = np.ones(len(mapping), dtype=bool)
                else:
                    require(np.array_equal(lat, this_lat) and np.array_equal(lon, this_lon), 'Model grid mismatch')
                    require(np.array_equal(area, ds['cell_area_km2'][:][rr, cc]), 'Area mismatch')
                domain = ds['domain_mask'][:] == 1
                valid_hours = ds['valid_hours'][yi][:, rr, cc].astype(float)
                nom = ds['nominal_hours'][yi].astype(float)
                values = np.empty((30, len(events), len(mapping)), dtype=np.float32)
                # One year at a time bounds memory and permits independent RQ1 table checks.
                for j, iy in enumerate(yi):
                    full = ds['event_days'][iy].astype(float)
                    values[j] = full[:, rr, cc]
                    if YEARS[j] in (2030, 2040, 2050):
                        weight = np.where(domain, ds['cell_area_km2'][:], 0)
                        old = reference[(reference.scenario == ssp) & (reference.tech == tech)
                                        & (reference.patch == patch) & (reference.year == YEARS[j])].set_index('event')
                        for k, ev in enumerate(['any', *EVENTS[tech]]):
                            numerator = float(np.nansum(full[k] * weight))
                            denominator = float(weight[np.isfinite(full[k]) & domain].sum())
                            require(np.isclose(numerator, old.loc[ev, 'weighted_days_km2'], rtol=1e-12, atol=1e-6), 'RQ1 numerator reproduction')
                            require(np.isclose(denominator, old.loc[ev, 'valid_area_km2'], rtol=1e-12, atol=1e-6), 'RQ1 area reproduction')
                            sample_checks.append(abs(numerator / denominator - old.loc[ev, 'weighted_days_km2'] / old.loc[ev, 'valid_area_km2']) if denominator else 0.)
                finite = np.isfinite(values).all(axis=1)
                valid = domain[rr, cc][None, :] & (valid_hours / nom[:, None] >= .99 - 1e-8)
                require(np.array_equal(finite, valid), 'Finite/coverage masks disagree')
                require(np.array_equal(np.isfinite(values), np.broadcast_to(finite[:, None, :], values.shape)), 'Different event support')
                require(np.all(np.where(finite[:, None, :], values >= 0, True)), 'Negative event days')
                require(np.all(np.where(finite[:, None, :], values <= valid_hours[:, None, :] / 24 + 1e-6, True)), 'Exposure exceeds valid time')
                require(np.all(np.where(finite[:, None, :], values[:, 1:] <= values[:, :1] + 1e-6, True)), 'Union smaller than event')
                require(np.all(np.where(finite, values[:, 0] <= values[:, 1:].sum(axis=1) + 1e-6, True)), 'Union exceeds event sum')
                common &= valid.all(axis=0)
                arrays.append(values); hours.append(valid_hours); nominal.append(nom)
                stat = path.stat()
                provenance.append(dict(path=str(path), resolved_path=str(path.resolve()), fingerprint=ds.fingerprint,
                                       size=stat.st_size, mtime_ns=stat.st_mtime_ns))
    values = np.stack(arrays).astype(float)  # combination, year, event, cell
    hours = np.stack(hours); nominal = np.stack(nominal)
    period_file = PERIOD / tech / patch / 'period_hours.nc'
    max_error = 0.; checked = 0
    with netCDF4.Dataset(period_file) as ds:
        ds.set_auto_mask(False)
        require(np.array_equal(ds['lat'][:], lat) and np.array_equal(ds['lon'][:] % 360, lon), 'Snapshot coordinates')
        require(list(ds['event'][:]) == events, 'Snapshot event definitions')
        snapshot_common = (ds['common_mask'][:] == 1)[:, rr, cc].all(axis=0)
        require(np.array_equal(common, snapshot_common), 'Annual/snapshot common support mismatch')
        for mi, model in enumerate(MODELS):
            for si, ssp in enumerate(SSPS):
                im = list(ds['model'][:]).index(model); ic = list(ds['climate_ssp'][:]).index(ssp)
                for di, decade in enumerate(SNAPSHOTS):
                    ip = list(ds['snapshot'][:]).index(decade)
                    expected = ds['event_hours'][im, ic, ip].astype(float)[:, rr, cc][:, common] / 24
                    actual = values[mi * 3 + si, di * 10:di * 10 + 10, :, :].mean(axis=0)[:, common]
                    error = float(np.max(np.abs(expected - actual))) if actual.size else 0.
                    max_error = max(max_error, error); checked += actual.size
                    require(np.allclose(actual, expected, rtol=2e-7, atol=3e-5), 'Snapshot exposure mismatch')
    rows, cover = [], []
    for i, (model, ssp) in enumerate((m, s) for m in MODELS for s in SSPS):
        for j, year in enumerate(YEARS):
            available = np.isfinite(values[i, j]).all(axis=0)
            cover.append(dict(tech=tech, patch=patch, model=model, climate_ssp=ssp, year=int(year),
                              catalogue_cells=len(mapping), available_cells=int(available.sum()),
                              common_cells=int(common.sum()), catalogue_area_km2=float(area.sum()),
                              available_area_km2=float(area[available].sum()), common_area_km2=float(area[common].sum()),
                              common_valid_hours_sum=float(hours[i, j, common].sum()), nominal_hours=float(nominal[i, j])))
            for weighting, weight in [('equal', np.ones(int(common.sum()))), ('area', area[common])]:
                v = values[i, j][:, common]
                overlap = v[0] - v[1:].sum(axis=0)
                for event, vector in zip([*events, 'overlap_correction'], [*v, overlap]):
                    rows.append(dict(tech=tech, patch=patch, model=model, climate_ssp=ssp, year=int(year),
                                     event=event, weighting=weighting, numerator=float((vector * weight).sum()),
                                     denominator=float(weight.sum())))
    dest = SOURCE / 'patches' / tech / patch
    dest.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(dest / 'annual.csv.gz', index=False)
    pd.DataFrame(cover).to_csv(dest / 'coverage.csv.gz', index=False)
    selected = mapping.copy()
    selected['event_lat_index'] = rr; selected['event_lon_index'] = cc
    selected['common_valid'] = common; selected['cell_area_km2'] = area
    selected.to_csv(dest / 'mapping.csv.gz', index=False)
    report = dict(tech=tech, patch=patch, catalogue_cells=len(mapping), matched_cells=len(mapping),
                  common_cells=int(common.sum()), index_disagreements=index_disagreements,
                  snapshot_checked_values=int(checked), snapshot_max_abs_days=max_error,
                  rq1_checked_patch_event_years=len(sample_checks), rq1_max_abs_days=max(sample_checks),
                  snapshot_sha256=digest(period_file), caches=provenance)
    write_json(dest / 'validation.json', report)
    print(f'PASSED {tech}/{patch}: {common.sum()}/{len(mapping)}; snapshot error {max_error:.3g}', flush=True)
    return report


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    mapping = pd.read_csv(MAPPING)
    require(set(mapping.type) == set(TECHS), 'Catalogue technologies')
    mapping['lon_normalized'] = np.round(mapping.lon % 360, 6)
    mapping['lat_normalized'] = np.round(mapping.lat, 6)
    checks = {}
    for tech, group in mapping.groupby('type'):
        checks[tech] = dict(catalogue_cells=len(group),
                           duplicate_patch_indices=int(group.duplicated(['patch', 'cf_lat_index', 'cf_lon_index']).sum()),
                           duplicate_coordinates=int(group.duplicated(['lat_normalized', 'lon_normalized']).sum()),
                           duplicate_raster_cells=int(group.duplicated(['raster_row', 'raster_col']).sum()))
        require(all(checks[tech][k] == 0 for k in checks[tech] if k.startswith('duplicate')), 'Duplicate catalogue cells')
    manifest = json.loads((CACHE / 'cache_manifest.json').read_text())
    records = {(r['model'], r['scenario'], r['tech'], r['patch']): r for r in manifest['records']}
    require(len(records) == len(manifest['records']), 'Duplicate cache records')
    tasks = [(tech, patch, group.copy(), records) for (tech, patch), group in mapping.groupby(['type', 'patch'])]
    # Representative patch must pass before processing the full catalogue.
    reports = [process(tasks[0])]
    workers = min(8, int(os.environ.get('SLURM_CPUS_PER_TASK', '1')))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        reports.extend(pool.map(process, tasks[1:]))
    tables = [pd.read_csv(SOURCE / 'patches' / r['tech'] / r['patch'] / 'annual.csv.gz') for r in reports]
    keys = ['tech', 'model', 'climate_ssp', 'year', 'event', 'weighting']
    annual = pd.concat(tables).groupby(keys, as_index=False)[['numerator', 'denominator']].sum()
    require(annual.denominator.gt(0).all(), 'Empty global support')
    annual['exposure_days'] = annual.numerator / annual.denominator
    annual['snapshot'] = (annual.year // 10) * 10
    decade_keys = ['tech', 'model', 'climate_ssp', 'snapshot', 'event', 'weighting']
    decadal = annual.groupby(decade_keys, as_index=False).agg(exposure_days=('exposure_days', 'mean'), n_years=('year', 'count'))
    require(decadal.n_years.eq(10).all(), 'Incomplete decades')
    union = decadal[decadal.event.eq('all')]
    require(len(union) == 144 and not union.duplicated(decade_keys).any(), 'Incomplete 4 x 3 x 3 x 2 x 2 matrix')
    closure = decadal.pivot(index=['tech', 'model', 'climate_ssp', 'snapshot', 'weighting'], columns='event', values='exposure_days')
    errors = []
    for tech in TECHS:
        g = closure.loc[tech]
        errors.extend(np.abs(g[list(EVENTS[tech])].sum(axis=1) + g.overlap_correction - g['all']))
    require(max(errors) < 1e-10, 'Aggregated overlap closure')
    annual.to_csv(SOURCE / 'annual.csv', index=False)
    decadal.to_csv(SOURCE / 'decadal.csv', index=False)
    coverage = pd.concat([pd.read_csv(SOURCE / 'patches' / r['tech'] / r['patch'] / 'coverage.csv.gz') for r in reports])
    sumcols = ['catalogue_cells', 'available_cells', 'common_cells', 'catalogue_area_km2', 'available_area_km2', 'common_area_km2', 'common_valid_hours_sum']
    cov = coverage.groupby(['tech', 'model', 'climate_ssp', 'year'], as_index=False)[sumcols].sum()
    cov['common_coverage_pct'] = 100 * cov.common_cells / cov.catalogue_cells
    cov['available_coverage_pct'] = 100 * cov.available_cells / cov.catalogue_cells
    cov.to_csv(SOURCE / 'coverage_annual.csv', index=False)
    coverage['snapshot'] = coverage.year // 10 * 10
    per = coverage.groupby(['tech', 'patch', 'model', 'climate_ssp', 'snapshot'], as_index=False).agg(
        catalogue_cells=('catalogue_cells', 'first'), common_cells=('common_cells', 'first'), min_available_cells=('available_cells', 'min'))
    per = per.groupby(['tech', 'model', 'climate_ssp', 'snapshot'], as_index=False)[['catalogue_cells', 'common_cells', 'min_available_cells']].sum()
    per['common_coverage_pct'] = 100 * per.common_cells / per.catalogue_cells
    per.to_csv(SOURCE / 'coverage_decadal.csv', index=False)
    for tech in TECHS:
        checks[tech].update(matched_cells=sum(r['matched_cells'] for r in reports if r['tech'] == tech),
                           common_cells=int(cov[cov.tech.eq(tech)].common_cells.iloc[0]),
                           common_coverage_pct=float(cov[cov.tech.eq(tech)].common_coverage_pct.iloc[0]))
    ensemble = decadal.groupby(['tech', 'climate_ssp', 'snapshot', 'event', 'weighting']).exposure_days.agg(['mean', 'min', 'max', 'count']).reset_index()
    require(ensemble['count'].eq(4).all(), 'Incomplete ensemble')
    ensemble.to_csv(SOURCE / 'decadal_ensemble.csv', index=False)
    annual.groupby(['tech', 'climate_ssp', 'year', 'event', 'weighting']).exposure_days.agg(['mean', 'min', 'max', 'count']).reset_index().to_csv(SOURCE / 'annual_ensemble.csv', index=False)
    comparison = ensemble[ensemble.event.eq('all')].pivot(index=['tech', 'climate_ssp', 'snapshot'], columns='weighting', values='mean').reset_index()
    comparison['area_minus_equal'] = comparison.area - comparison.equal
    comparison.to_csv(SOURCE / 'weighting_comparison.csv', index=False)
    trends = []
    for (tech, ssp), group in comparison.groupby(['tech', 'climate_ssp']):
        g = group.set_index('snapshot')
        eq = g.loc[2050, 'equal'] - g.loc[2030, 'equal']; ar = g.loc[2050, 'area'] - g.loc[2030, 'area']
        trends.append(dict(tech=tech, climate_ssp=ssp, equal_change_days=float(eq), area_change_days=float(ar), same_direction=bool(np.sign(eq) == np.sign(ar))))
    audit = dict(status='PASSED', catalogue=checks, patches=len(reports), matched_one_to_one=True,
                 unmatched_cells=0, cache_duplicate_cells=0,
                 cf_vs_event_index_disagreements=sum(r['index_disagreements'] for r in reports),
                 model_ssp_decade_coverage=dict(expected_per_tech=36, complete_per_tech=36, fraction=1.0),
                 union_ge_each_event='PASSED for every selected cell/year/combination',
                 union_le_sum_events='PASSED', overlap_closure_max_abs_days=float(max(errors)),
                 overlap_definition='union minus sum of event exposures; negative repeated-event excess, not independent intersection measurement',
                 snapshot_checked_values=sum(r['snapshot_checked_values'] for r in reports),
                 snapshot_max_abs_days=max(r['snapshot_max_abs_days'] for r in reports),
                 snapshot_tolerance=dict(rtol=2e-7, atol_days=3e-5),
                 rq1_sample_years=[2030, 2040, 2050],
                 rq1_checked_patch_event_years=sum(r['rq1_checked_patch_event_years'] for r in reports),
                 rq1_max_abs_days=max(r['rq1_max_abs_days'] for r in reports),
                 weighting_trends=trends, weighting_max_abs_days=float(comparison.area_minus_equal.abs().max()),
                 risks=['Exposure is observed event hours/24, not calendar event days; missing time is not extrapolated.',
                        'Common spatial support is fixed across all four models, three SSPs and 30 years; excluded cells remain missing.',
                        'Low-resource thresholds use each model/scenario 2015–2024 baseline.',
                        'Overlap correction is accounting identity; annual caches do not retain intersection chronology.'])
    write_json(OUT / 'validation.json', audit)
    write_json(OUT / 'metadata.json', dict(metric='annual event exposure', unit='day yr-1', main_event='all',
               models=list(MODELS), ssps=list(SSPS), years=YEARS.tolist(), snapshots=list(SNAPSHOTS),
               weighting='equal suitable-cell primary; spherical cell area sensitivity',
               centre='four-model arithmetic mean', band='four-model min-max, not confidence interval',
               source_mapping=str(MAPPING), mapping_sha256=digest(MAPPING), manifest_sha256=digest(CACHE / 'cache_manifest.json'),
               preparation_code_sha256=digest(Path(__file__)), patch_reports=[str(SOURCE / 'patches' / r['tech'] / r['patch'] / 'validation.json') for r in reports]))
    print(ensemble[ensemble.event.eq('all') & ensemble.weighting.eq('equal')].to_string(index=False), flush=True)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
