"""Prepare country CF maps from authoritative native CF products."""
import argparse
import itertools
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cftime
import numpy as np
import pandas as pd
import xarray as xr

from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, INDEXES
from paper_figures.common.io import digest, write_csv, write_json, require_complete
from paper_figures.common.spatial import assign
from paper_figures.main.fig01_extreme_events.plot_country_exposure import geometries, input_record, require
from utils.data_access import read_cf_grid, read_cf_stations

OUT = ROOT / 'paper_figures/main/fig01_extreme_events/outputs'
CACHE = OUT / 'country_cf_cache'
SOURCE = OUT / 'source_data'
WINDOWS = (2030, 2050)
YEARS = tuple(range(2030, 2040)) + tuple(range(2050, 2060))


def tasks():
    records = read_cf_grid.find_records(years=(2030, 2059))
    patches = sorted({r['patch'] for r in records})
    require(len(patches) == 47, 'Expected 47 patches')
    return list(itertools.product(TECHS, patches))


def annual_means(records, tech, station=False):
    """Stream native chunks; retain each year's valid coverage before window means."""
    annual, coverage, coordinates, sources = {}, {}, None, []
    for record in records:
        needed = [y for y in YEARS if record['start_year'] <= y <= record['end_year']]
        if not needed:
            continue
        sources.append(record)
        with xr.open_dataset(record['path']) as ds:
            variable = ds[tech + '_cf']
            dims = ('station',) if station else ('lat', 'lon')
            require(variable.dims == ('time', *dims), 'Unexpected CF dimensions')
            if coordinates is None:
                coordinates = {k: ds[k].values for k in (['station_id', 'lon', 'lat'] if station else ['lat', 'lon'])}
                if station:
                    coordinates['station_id'] = coordinates['station_id'].astype(str)
                    require(len(np.unique(coordinates['station_id'])) == len(coordinates['station_id']), 'Duplicate station ID')
                else:
                    coordinates['domain_mask'] = ds.domain_mask.values == 1
            else:
                for k in (['station_id', 'lon', 'lat'] if station else ['lat', 'lon']):
                    actual = ds[k].values.astype(str) if k == 'station_id' else ds[k].values
                    require(np.array_equal(coordinates[k], actual), 'CF coordinates changed between blocks')
            year_values = ds.time.dt.year.values
            calendar = str(ds.time.dt.calendar)
            chunk = variable.encoding.get('chunksizes', (240,))[0]
            for year in needed:
                require(year not in annual, 'Duplicate CF year')
                ix = np.flatnonzero(year_values == year)
                expected = int((cftime.datetime(year + 1, 1, 1, calendar=calendar)
                                - cftime.datetime(year, 1, 1, calendar=calendar)).total_seconds() / 10800)
                require(len(ix) == expected and np.all(np.diff(ix) == 1), 'Incomplete native year')
                times = ds.time.values[ix]
                steps = np.array([d / np.timedelta64(1, 'h') if isinstance(d, np.timedelta64)
                                  else d.total_seconds() / 3600 for d in np.diff(times)])
                require(np.all(steps == 3), 'Non-three-hour CF time')
                total = np.zeros(variable.shape[1:], dtype=np.float64)
                count = np.zeros_like(total, dtype=np.int32)
                # Align reads to the stored time chunks to avoid repeated decompression.
                for begin in range((int(ix[0]) // chunk) * chunk, int(ix[-1]) + 1, chunk):
                    left, right = max(begin, int(ix[0])), min(begin + chunk, int(ix[-1]) + 1)
                    values = variable.isel(time=slice(left, right)).values
                    finite = np.isfinite(values)
                    if finite.any():
                        require(values[finite].min() >= -1e-6 and values[finite].max() <= 1 + 1e-6,
                                'CF outside [0,1]')
                    total += np.where(finite, values, 0).sum(axis=0, dtype=np.float64)
                    count += finite.sum(axis=0)
                mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
                fraction = count / expected
                mean[fraction < .99] = np.nan
                if not station:
                    mean[~coordinates['domain_mask']] = np.nan
                annual[year], coverage[year] = mean, fraction
    require(set(annual) == set(YEARS), 'Missing CF annual means')
    means = np.stack([np.mean(np.stack([annual[y] for y in range(s, s + 10)]), axis=0) for s in WINDOWS])
    minimum = np.stack([np.min(np.stack([coverage[y] for y in range(s, s + 10)]), axis=0) for s in WINDOWS])
    return dict(cf=means, minimum_annual_coverage=minimum, **coordinates), sources


def run_combination(task):
    tech, patch, model, ssp = task
    dest = CACHE / tech / patch / model / ssp
    dest.mkdir(parents=True, exist_ok=True)
    signature = {k: digest(INDEXES[k]) for k in ('cf_grid', 'cf_stations')}
    receipt = dest / 'complete.json'
    if receipt.exists():
        old = json.loads(receipt.read_text())
        if old.get('indexes') == signature and old.get('code_sha256') == digest(__file__):
            require(all((dest / p).exists() for p in old['artifacts']), 'Missing CF cache')
            return
    kwargs = dict(model=model, climate_scenario=ssp, patch=patch, tech=tech, years=(2030, 2059))
    grid, sources = annual_means(read_cf_grid.find_records(**kwargs), tech)
    np.savez_compressed(dest / 'grid.npz', **grid)
    station_records = read_cf_stations.find_records(**kwargs, station_scenario=ssp)
    artifacts = ['grid.npz']
    if station_records:
        station, station_sources = annual_means(station_records, tech, station=True)
        sources.extend(station_sources)
        np.savez_compressed(dest / 'station.npz', **station)
        artifacts.append('station.npz')
    write_json(dest / 'sources.json', sources)
    write_json(receipt, dict(status='COMPLETED', task=task, indexes=signature, artifacts=artifacts,
                            code_sha256=digest(__file__), job_id=os.environ.get('SLURM_JOB_ID')))
    print('Completed CF', task, flush=True)


def aggregate():
    require_complete(OUTPUT / 'catalogues')
    features = geometries()
    grid_rows, station_rows, checks, inputs = [], [], [], []
    signature = {k: digest(INDEXES[k]) for k in ('cf_grid', 'cf_stations')}
    code = digest(__file__)
    for tech, patch in tasks():
        grids, stations = {}, {}
        for model, ssp in itertools.product(MODELS, SSPS):
            dest = CACHE / tech / patch / model / ssp
            receipt = json.loads((dest / 'complete.json').read_text())
            require(receipt['status'] == 'COMPLETED' and receipt['indexes'] == signature
                    and receipt['code_sha256'] == code, 'Stale / incomplete CF cache')
            inputs.append(input_record(dest / 'sources.json'))
            with np.load(dest / 'grid.npz') as z:
                grids[model, ssp] = {k: z[k] for k in z.files}
            if 'station.npz' in receipt['artifacts']:
                with np.load(dest / 'station.npz') as z:
                    stations[model, ssp] = {k: z[k] for k in z.files}
        ref = next(iter(grids.values()))
        common = np.ones(ref['cf'].shape[1:], dtype=bool)
        for values in grids.values():
            require(np.array_equal(values['lat'], ref['lat']) and np.array_equal(values['lon'], ref['lon']),
                    'Grid coordinates differ across models or SSPs')
            common &= np.isfinite(values['cf']).all(axis=0)
        xx, yy = np.meshgrid(ref['lon'], ref['lat'])
        ids = assign(xx[common], yy[common], features)
        labels, codes = np.unique(ids, return_inverse=True)
        counts = np.bincount(codes, minlength=len(labels))
        for (model, ssp), values in grids.items():
            for wi, snap in enumerate(WINDOWS):
                v = values['cf'][wi][common]
                num = np.bincount(codes, weights=v, minlength=len(labels))
                require(np.isclose(num.sum(), v.sum()), 'Grid numerator conservation')
                for i, country in enumerate(labels):
                    grid_rows.append(dict(model=model, climate_ssp=ssp, station_ssp='not_applicable',
                        tech=tech, patch=patch, snapshot=snap, country=country,
                        cf_sum=num[i], n_cells=int(counts[i]),
                        minimum_annual_coverage=float(values['minimum_annual_coverage'][wi][common][codes == i].min())))
        checks.append(dict(tech=tech, patch=patch, common_cells=int(common.sum()),
                           domain_cells=int(ref['domain_mask'].sum())))
        for ssp in SSPS:
            available = [m for m in MODELS if (m, ssp) in stations]
            require(len(available) in (0, 4), 'Station task coverage differs across models')
            if not available:
                continue
            ref = stations[MODELS[0], ssp]
            ids = ref['station_id']
            require(len(np.unique(ids)) == len(ids), 'Duplicate station IDs')
            common = np.ones(len(ids), dtype=bool)
            aligned = {}
            for model in MODELS:
                val = stations[model, ssp]
                positions = pd.Index(val['station_id']).get_indexer(ids)
                require((positions >= 0).all() and len(val['station_id']) == len(ids), 'Station model ID mismatch')
                aligned[model] = val['cf'][:, positions]
                common &= np.isfinite(aligned[model]).all(axis=0)
            capacity_path = OUTPUT / 'catalogues' / f'capacity_{ssp}_{tech}.csv.gz'
            capacity = pd.read_csv(capacity_path, dtype={'station_id': str})
            capacity = capacity[capacity.station_id.isin(ids)]
            for snap in WINDOWS:
                c = capacity[capacity.snapshot.eq(snap)].set_index('station_id').reindex(ids)
                present = c.capacity_mw.fillna(0).to_numpy() > 0
                valid = common & present
                countries = c.country.to_numpy()
                caps = c.capacity_mw.fillna(0).to_numpy()
                for model in MODELS:
                    v = aligned[model][WINDOWS.index(snap)]
                    for country in np.unique(countries[present]):
                        keep = valid & (countries == country)
                        all_country = present & (countries == country)
                        station_rows.append(dict(model=model, climate_ssp=ssp, station_ssp=ssp,
                            tech=tech, patch=patch, snapshot=snap, country=country,
                            capacity_cf_sum=float(np.dot(v[keep], caps[keep])),
                            valid_capacity_mw=float(caps[keep].sum()),
                            mapped_capacity_mw=float(caps[all_country].sum()), n_stations=int(keep.sum())))
        print('Aggregated CF', tech, patch, flush=True)
    keys = ['model', 'climate_ssp', 'tech', 'snapshot', 'country']
    grid_patch = pd.DataFrame(grid_rows)
    station_patch = pd.DataFrame(station_rows)
    grid = grid_patch.groupby(keys, as_index=False)[['cf_sum', 'n_cells']].sum()
    grid['grid_cf'] = grid.cf_sum / grid.n_cells
    station = station_patch.groupby(keys, as_index=False)[
        ['capacity_cf_sum', 'valid_capacity_mw', 'mapped_capacity_mw', 'n_stations']].sum()
    station['station_cf'] = station.capacity_cf_sum / station.valid_capacity_mw.replace(0, np.nan)
    capacity_path = OUTPUT / 'catalogues/capacity_by_country.csv'
    capacity = pd.read_csv(capacity_path)
    capacity['climate_ssp'] = capacity.station_ssp
    station = station.merge(capacity.rename(columns={'capacity_mw': 'catalogue_capacity_mw'}),
        on=['climate_ssp', 'tech', 'snapshot', 'country'], validate='many_to_one')
    station['capacity_coverage_fraction'] = station.valid_capacity_mw / station.catalogue_capacity_mw
    require(station.capacity_coverage_fraction.between(0, 1 + 1e-9).all(), 'Capacity coverage exceeds catalogue')
    cap = capacity[capacity.snapshot.eq(2050)].copy()
    cap['capacity_gw'] = cap.capacity_mw / 1000
    countries = sorted(set(grid.country) | set(cap.country))
    keys = ['model', 'climate_ssp', 'tech', 'country']
    data = pd.DataFrame(itertools.product(MODELS, SSPS, TECHS, countries), columns=keys)
    for snap in WINDOWS:
        for table, cols in [(grid, ['grid_cf', 'cf_sum', 'n_cells']),
                            (station, ['station_cf', 'capacity_cf_sum', 'valid_capacity_mw', 'capacity_coverage_fraction'])]:
            part = table[table.snapshot.eq(snap)][keys + cols]
            data = data.merge(part.rename(columns={c: f'{c}_{snap}' for c in cols}),
                              on=keys, how='left', validate='one_to_one')
    data = data.merge(cap[['climate_ssp', 'tech', 'country', 'capacity_gw']],
                      on=['climate_ssp', 'tech', 'country'], how='left', validate='many_to_one')
    for kind in ['grid', 'station']:
        data[kind + '_change_cf'] = data[kind + '_cf_2050'] - data[kind + '_cf_2030']
    data['station_ssp'] = data.climate_ssp
    data['capacity_snapshot'] = 2050
    data['unit'] = '1'
    metrics = [f'{kind}_{metric}' for kind in ['grid', 'station']
               for metric in ['cf_2030', 'cf_2050', 'change_cf']]
    rows = []
    for key, group in data.groupby(['climate_ssp', 'tech', 'country']):
        require(set(group.model) == set(MODELS) and len(group) == 4, 'Missing model')
        row = dict(zip(['climate_ssp', 'tech', 'country'], key))
        row.update(station_ssp=key[0], model='ensemble_mean', capacity_gw=group.capacity_gw.iloc[0])
        for metric in metrics:
            valid = group[metric].notna().all()
            row[metric] = group[metric].mean() if valid else np.nan
            row[metric + '_min'] = group[metric].min() if valid else np.nan
            row[metric + '_max'] = group[metric].max() if valid else np.nan
            row[metric + '_n_models'] = int(group[metric].notna().sum())
        rows.append(row)
    display = pd.DataFrame(rows)
    require(not data.country.eq('TWN').any(), 'China records were not merged')
    for frame in (grid_patch, station_patch, grid, station):
        frame['window_start'] = frame.snapshot
        frame['window_end'] = frame.snapshot + 9
        frame['unit'] = '1'
    files = {'country_cf_grid_patches.csv.gz': grid_patch, 'country_cf_station_patches.csv.gz': station_patch,
             'country_cf_grid_windows.csv.gz': grid, 'country_cf_station_windows.csv.gz': station,
             'country_cf_models.csv.gz': data, 'country_cf_display.csv': display}
    for name, frame in files.items():
        write_csv(SOURCE / name, frame)
    write_json(OUT / 'country_cf_data_audit.json', dict(status='PASSED', indexes=signature,
        prepare_code_sha256=code, grid_patch_checks=checks, input_manifests=inputs,
        source_data=[input_record(SOURCE / name) for name in files],
        capacity_input=input_record(capacity_path),
        temporal='Annual valid-time means, then equal mean of all ten annual means; native calendar; annual coverage >=99%.',
        grid='Arithmetic mean over native cell centres inside each country; common cells across four models, three SSPs, two decades.',
        stations='Capacity-weighted CF; common valid station IDs across four models and both decades within each deployment.',
        station_change='2050 snapshot-weighted CF minus 2030 snapshot-weighted CF; includes deployment change.',
        unassigned='UNASSIGNED and AMBIGUOUS retained in source data, excluded from maps.',
        job_id=os.environ.get('SLURM_JOB_ID')))
    print('Country CF source data PASSED', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--aggregate', action='store_true')
    parser.add_argument('--task', type=int)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--shards', type=int, default=1)
    args = parser.parse_args()
    if args.aggregate:
        aggregate()
        return
    if args.pilot:
        for tech in TECHS:
            run_combination((tech, 'R02C08', MODELS[0], SSPS[0]))
        write_json(OUT / 'country_cf_pilot.json', dict(status='PASSED', patch='R02C08',
                   model=MODELS[0], climate_ssp=SSPS[0], technologies=list(TECHS), windows=list(WINDOWS)))
        return
    all_tasks = tasks()
    selected = [all_tasks[args.task]] if args.task is not None else (
        all_tasks[int(os.environ['SLURM_ARRAY_TASK_ID'])::args.shards] if 'SLURM_ARRAY_TASK_ID' in os.environ else all_tasks)
    combos = [(tech, patch, model, ssp) for tech, patch in selected
              for model, ssp in itertools.product(MODELS, SSPS)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_combination, combos))


if __name__ == '__main__':
    main()
