"""Prepare global suitable-grid loss curves from accepted tile manifests."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import itertools
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset

from paper_figures.config import MODELS, SSPS, OUTPUT

ROOT = Path('/work/home/acsep06cn2/generation_loss_suitable_grid/suitable_grid')
OUT = OUTPUT / 'suitable_grid_loss'
WINDOWS = (2030, 2040, 2050)
VARIABLES = {'net': 'net_generation_loss_per_mw_all',
             'positive': 'generation_loss_per_mw_all'}


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def index(root):
    raw = (root / 'runtime/completion.json').read_bytes()
    completion = json.loads(raw)
    checked(completion['status'] == 'COMPLETED', 'Campaign incomplete')
    checked(completion['completed'] == 1044 and len(completion['receipts']) == 1044,
            'Unexpected campaign coverage')
    groups = {}
    sources = []
    identities = set()
    for path in completion['receipts']:
        receipt = json.loads(Path(path).read_text())
        checked(receipt['status'] == 'COMPLETED', str(path))
        checked(receipt['pack_sha256'] == completion['pack_sha256'], 'Pack mismatch')
        mp = Path(receipt['manifest'])
        data = mp.read_bytes()
        checked(digest(data) == receipt['manifest_sha256'], f'Manifest hash: {mp}')
        manifest = json.loads(data)
        request = manifest['request']
        m, s, t, p = (request[k] for k in ('model', 'climate_scenario', 'tech', 'patch'))
        checked(m in MODELS and s in SSPS and t in ('wind', 'solar'), 'Unknown identity')
        checked(manifest['status'] == 'COMPLETED' and
                manifest['unit_id'] == receipt['unit_id'] == f'sgl_{m}_{s}_{t}_{p}',
                'Unit identity mismatch')
        checked(request['window_starts'] == list(WINDOWS), 'Unexpected windows')
        identity = (m, s, t, p)
        checked(identity not in identities, 'Duplicate unit')
        identities.add(identity)
        records = {}
        for tile in manifest['tiles']:
            selected = [f for f in tile['files'] if Path(f['path']).name == 'annual_loss.nc']
            checked(len(selected) == 1, 'Expected one annual file per tile')
            item = selected[0]
            key = (int(tile['window_start']), tile['tile'])
            checked(key not in records, 'Duplicate tile window')
            records[key] = dict(path=str(mp.parent / item['path']), sha256=item['sha256'],
                                station_count=tile['station_count'])
        groups.setdefault((t, p), {})[(m, s)] = records
        sources.append(dict(receipt=path, manifest=str(mp), sha256=digest(data),
                            model=m, climate_ssp=s, tech=t, patch=p,
                            station_count=manifest['station_count']))
    for key, combinations in groups.items():
        checked(set(combinations) == set(itertools.product(MODELS, SSPS)),
                f'Incomplete model/SSP coverage: {key}')
        reference = set(next(iter(combinations.values())))
        checked(all(set(v) == reference for v in combinations.values()), f'Tile coverage: {key}')
        tiles = {tile for _, tile in reference}
        checked(reference == set(itertools.product(WINDOWS, tiles)), f'Window coverage: {key}')
    return groups, sources, digest(raw)


def aggregate_tile(values):
    """values: model/SSP/window x year x grid x metric; missing is never zero."""
    common = np.isfinite(values).all(axis=(0, 1, 3))
    own = np.isfinite(values).all(axis=3)
    result = {}
    for policy in ('common', 'original'):
        mask = np.broadcast_to(common, own.shape) if policy == 'common' else own
        sums = np.where(mask[..., None], values, 0).sum(axis=2, dtype=np.float64)
        count = mask.sum(axis=2)
        result[policy] = (sums, count)
    return common, result


def prepare_group(task):
    (tech, patch), records, out, completion_sha = task
    folder = Path(out) / 'shards' / tech / patch
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / 'complete.json'
    if marker.exists():
        previous = json.loads(marker.read_text())
        checked(previous['completion_sha256'] == completion_sha, 'Input release changed')
        for name, expected in previous['outputs'].items():
            checked(digest((folder / name).read_bytes()) == expected, 'Cached shard changed')
        return str(folder)
    combinations = list(itertools.product(MODELS, SSPS, WINDOWS))
    totals = {p: [np.zeros((36, 10, 2)), np.zeros((36, 10), dtype=np.int64)]
              for p in ('common', 'original')}
    seen = set()
    support = []
    tile_names = sorted({tile for _, tile in next(iter(records.values()))})
    for ti, tile in enumerate(tile_names):
        payload = []
        refids = None
        for m, s, window in combinations:
            item = records[(m, s)][(window, tile)]
            path = Path(item['path'])
            checked(digest(path.read_bytes()) == item['sha256'], f'Annual hash: {path}')
            with Dataset(path) as ds:
                checked(list(ds['analysis_year'][:]) == list(range(window, window + 10)),
                        f'Annual coverage: {path}')
                for attr, expected in [('model', m), ('climate_scenario', s), ('tech', tech), ('patch', patch)]:
                    checked(ds.getncattr(attr) == expected, f'Identity mismatch: {path}')
                ids = np.asarray(ds['station_id'][:]).astype(str)
                order = np.argsort(ids)
                ids = ids[order]
                checked(len(ids) == item['station_count'] and len(set(ids)) == len(ids),
                        f'Grid identity: {path}')
                checked(np.all(ds['capacity_mw'][:] == 1), f'Expected 1 MW: {path}')
                if refids is None:
                    refids = ids
                checked(np.array_equal(ids, refids), f'Grid membership differs: {path}')
                for v in VARIABLES.values():
                    checked(ds[v].dimensions == ('analysis_year', 'station'), f'Unexpected dimensions: {path}')
                payload.append(np.stack([np.ma.asarray(ds[v][:], dtype=float).filled(np.nan)[:, order]
                                         for v in VARIABLES.values()], axis=-1))
        checked(not seen.intersection(refids), f'Duplicate grid across tiles: {tech}/{patch}')
        seen.update(refids)
        common, aggregated = aggregate_tile(np.asarray(payload))
        support.append(pd.DataFrame(dict(station_id=refids, common=common)))
        for policy, (sums, count) in aggregated.items():
            totals[policy][0] += sums
            totals[policy][1] += count
        if ti % 50 == 0:
            print(tech, patch, ti + 1, '/', len(tile_names), flush=True)
    rows = []
    for policy, (sums, counts) in totals.items():
        for i, (m, s, window) in enumerate(combinations):
            for j, year in enumerate(range(window, window + 10)):
                rows.append(dict(model=m, climate_ssp=s, tech=tech, patch=patch,
                                 window_start=window, year=year, support=policy,
                                 n_valid=int(counts[i, j]), n_available=len(seen),
                                 net_sum=sums[i, j, 0], positive_sum=sums[i, j, 1]))
    pd.DataFrame(rows).to_csv(folder / 'annual.csv.gz', index=False)
    pd.concat(support).to_csv(folder / 'support.csv.gz', index=False)
    marker.write_text(json.dumps(dict(completion_sha256=completion_sha, n_available=len(seen),
        outputs={name: digest((folder / name).read_bytes()) for name in ('annual.csv.gz', 'support.csv.gz')})))
    return str(folder)


def summarize(out, groups, completion_sha):
    frames = []
    for (tech, patch) in groups:
        folder = out / 'shards' / tech / patch
        checked(json.loads((folder / 'complete.json').read_text())['completion_sha256'] ==
                completion_sha, 'Mixed input releases')
        frames.append(pd.read_csv(folder / 'annual.csv.gz'))
    data = pd.concat(frames, ignore_index=True)
    keys = ['model', 'climate_ssp', 'tech', 'window_start', 'year', 'support']
    annual = data.groupby(keys, as_index=False)[['net_sum', 'positive_sum', 'n_valid', 'n_available']].sum()
    for tech, expected in [('wind', 591798), ('solar', 557406)]:
        checked(annual.loc[annual.tech == tech, 'n_available'].eq(expected).all(),
                f'Global reference count differs: {tech}')
        ids = pd.concat([pd.read_csv(out / 'shards' / t / p / 'support.csv.gz')
                         for t, p in groups if t == tech]).station_id
        checked(len(ids) == expected and ids.is_unique, f'Global grid union: {tech}')
    checked(len(annual) == 4 * 3 * 2 * 30 * 2, 'Incomplete global table')
    checked(annual.n_valid.gt(0).all(), 'Empty global support')
    for metric in VARIABLES:
        annual[metric + '_loss_per_mw'] = annual[metric + '_sum'] / annual.n_valid
    annual['coverage'] = annual.n_valid / annual.n_available
    annual.to_csv(out / 'annual.csv.gz', index=False)
    keys = ['model', 'climate_ssp', 'tech', 'window_start', 'support']
    annual.groupby(keys, as_index=False)[['net_loss_per_mw', 'positive_loss_per_mw', 'coverage',
                                         'n_valid', 'n_available']].mean().to_csv(out / 'decadal.csv', index=False)
    (out / 'complete.json').write_text(json.dumps(dict(
        completion_sha256=completion_sha, rows=len(annual), models=list(MODELS),
        support='finite net and positive all loss across 4 models, 3 SSPs and all 30 years',
        spatial_weight='one MW per suitable grid; equal grid weights',
        units='MWh/MW/year', uncertainty='equal-model mean and min-max'), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--workers', type=int, default=min(16, int(os.environ.get('SLURM_CPUS_PER_TASK', '4'))))
    parser.add_argument('--summarize-only', action='store_true')
    args = parser.parse_args()
    checked(1 <= args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', args.workers)),
            'Workers exceed allocated CPUs')
    groups, sources, sha = index(args.root)
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.summarize_only:
        (args.output / 'sources.json').write_text(json.dumps(sources, indent=2))
        tasks = [(key, records, str(args.output), sha) for key, records in sorted(groups.items())]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for folder in pool.map(prepare_group, tasks):
                print('Completed', folder, flush=True)
    summarize(args.output, groups, sha)


if __name__ == '__main__':
    main()
