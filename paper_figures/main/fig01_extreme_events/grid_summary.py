"""Area-weighted annual grid exposure by latitude row on a common support, plus 1-degree period maps.

Products: the cross-technology union, the wind and solar unions ('any') and every event of the RQ1
annual caches. The common support of a patch is the set of domain cells with finite exposure in every
model, SSP, product and year, so all event types and the union share one denominator.
"""
import argparse
import logging
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import netCDF4
import numpy as np

from paper_figures.config import MODELS, SSPS, EVENTS
from paper_figures.main.fig01_extreme_events.meeting_common import OUT, CACHE_ROOT, GRID_YEARS, patches

PRODUCTS = [('union', 'all')] + [('wind', e) for e in ('any', *EVENTS['wind'])] + [('solar', e) for e in ('any', *EVENTS['solar'])]
PERIODS = {'2015-2024': (2015, 2024), '2030-2039': (2030, 2039), '2040-2049': (2040, 2049), '2050-2059': (2050, 2059)}
LOGGER = logging.getLogger('grid_summary')


def read_product(model, ssp, tech, patch, union_root):
    if tech == 'union':
        with netCDF4.Dataset(union_root / model / ssp / f'{patch}.nc') as ds:
            ds.set_auto_mask(False)
            return ds['union_days'][:][:, None].astype(np.float32), ds['lat'][:], ds['lon'][:], ds['cell_area_km2'][:]
    with netCDF4.Dataset(CACHE_ROOT / model / 'cache' / ssp / tech / f'{patch}.nc') as ds:
        ds.set_auto_mask(False)
        if [str(e) for e in ds['event'][:]] != ['any', *EVENTS[tech]] or list(ds['year'][:]) != list(GRID_YEARS):
            raise ValueError('Unexpected cache layout')
        return ds['event_days'][:].astype(np.float32), ds['lat'][:], ds['lon'][:], ds['cell_area_km2'][:]


def run_patch(patch, union_root, output_root):
    target = Path(output_root) / f'{patch}.npz'
    if target.exists():
        return target
    techs = ('union', 'wind', 'solar')
    common = lat = lon = area = None
    for model in MODELS:
        for ssp in SSPS:
            for tech in techs:
                v, la, lo, ar = read_product(model, ssp, tech, patch, union_root)
                ok = np.isfinite(v).all(axis=(0, 1))
                if common is None:
                    common, lat, lon, area = ok, la, lo, ar
                else:
                    if not (np.array_equal(la, lat) and np.array_equal(lo, lon)):
                        raise ValueError('Grid mismatch')
                    common &= ok
    ny, nx = common.shape
    w = np.where(common, area, 0.0)
    rows = np.zeros((len(MODELS), len(SSPS), len(PRODUCTS), len(GRID_YEARS), ny))
    lon_bins = np.floor(((lon + 180) % 360) - 180).astype(int) + 180
    lat_bins = np.floor(lat).astype(int) + 90
    keys = (lat_bins[:, None] * 360 + lon_bins[None, :])[common]
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    map_area = np.bincount(inverse, weights=area[common])
    maps = np.zeros((len(MODELS), len(SSPS), len(PRODUCTS), len(PERIODS), len(unique_keys)))
    years = np.array(GRID_YEARS)
    for mi, model in enumerate(MODELS):
        for si, ssp in enumerate(SSPS):
            j = 0
            for tech in techs:
                v, *_ = read_product(model, ssp, tech, patch, union_root)
                v = np.where(common[None, None], v, 0.0)
                for e in range(v.shape[1]):
                    rows[mi, si, j] = (v[:, e] * w[None]).sum(axis=2)
                    for pi, (a, b) in enumerate(PERIODS.values()):
                        sel = (years >= a) & (years <= b)
                        mean = v[sel, e].mean(axis=0)[common]
                        maps[mi, si, j, pi] = np.bincount(inverse, weights=mean * area[common], minlength=len(unique_keys))
                    j += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + '.tmp.npz')
    np.savez_compressed(tmp, lat=lat, row_area=w.sum(axis=1), rows=rows, map_keys=unique_keys, map_area=map_area,
                        maps=maps, products=np.array([f'{t}:{e}' for t, e in PRODUCTS]), periods=np.array(list(PERIODS)),
                        models=np.array(MODELS), ssps=np.array(SSPS), years=years,
                        common_cells=int(common.sum()))
    tmp.replace(target)
    return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--patches', nargs='+')
    p.add_argument('--workers', type=int, default=int(os.environ.get('SLURM_CPUS_PER_TASK', 1)))
    p.add_argument('--union-root', type=Path, default=OUT / 'grid_union')
    p.add_argument('--output-root', type=Path, default=OUT / 'grid_summary')
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    failures = []
    with ProcessPoolExecutor(a.workers, mp_context=mp.get_context('spawn')) as pool:
        futures = {pool.submit(run_patch, q, a.union_root, a.output_root): q for q in (a.patches or patches())}
        for f in as_completed(futures):
            try:
                LOGGER.info('Done %s -> %s', futures[f], f.result())
            except Exception as exc:
                failures.append((futures[f], repr(exc)))
                LOGGER.error('Failed %s: %r', futures[f], exc)
    if failures:
        raise SystemExit(f'{len(failures)} patches failed: {failures[:5]}')


if __name__ == '__main__':
    main()
