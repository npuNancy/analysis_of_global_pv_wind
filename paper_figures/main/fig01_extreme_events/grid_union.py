"""Cross-technology union of all grid weather events on a shared 3-hour interval axis.

Each solar step (3-hour radiation mean, e.g. 01:30) is paired with the wind step at the end of the
same interval (03:00). A paired step is valid only when every wind and solar signal is binary, and
its year is the year of the solar step. Annual exposure follows the RQ1 cache rule: observed hours
only, with at least 99% of the nominal year valid.
"""
import argparse
import logging
import multiprocessing as mp
import os
import resource
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import netCDF4
import numpy as np

from paper_figures.config import MODELS, SSPS, EVENTS
from paper_figures.common.io import write_json
from paper_figures.main.fig01_extreme_events.meeting_common import (OUT, CACHE_ROOT, GRID_YEARS, MIN_TIME_COVERAGE,
                                                 load_grid_common, patch_manifest, patches, decode_time, OpenFiles)
from utils.data_access.read_extreme_grid import find_records

PAIR_OFFSET_DAYS = 0.0625
DT_HOURS = 3.0
BLOCK_STEPS = 240
LOGGER = logging.getLogger('grid_union')


class Source:
    """Signals of one technology concatenated along time across the published files."""

    def __init__(self, model, ssp, patch, tech):
        records = sorted(find_records(model=model, climate_scenario=ssp, patch=patch, tech=tech),
                         key=lambda r: r['start_year'])
        if not records:
            raise ValueError(f'No signals for {model}/{ssp}/{patch}/{tech}')
        self.events = EVENTS[tech]
        times, years, owners, local = [], [], [], []
        self.calendar = None
        grids = []
        for i, record in enumerate(records):
            with netCDF4.Dataset(record['path']) as ds:
                ds.set_auto_mask(False)
                numeric, calendar, yrs, _, _ = decode_time(ds['time'])
                if i == 0:
                    self.fill = [getattr(ds['signal_' + e], '_FillValue', None) for e in self.events]
                    self.domain = ds['domain_mask'][:] == 1
                grids.append((ds['lat'][:], ds['lon'][:]))
            if self.calendar is None:
                self.calendar = calendar
            elif calendar != self.calendar:
                raise ValueError(f'{tech}: calendar changes between files')
            times.append(numeric); years.append(yrs)
            owners.append(np.full(len(numeric), i)); local.append(np.arange(len(numeric)))
        self.datasets = OpenFiles([r['path'] for r in records], ['signal_' + e for e in self.events], 32 * 1024**2)
        self.time = np.concatenate(times); self.year = np.concatenate(years)
        self.file = np.concatenate(owners); self.local = np.concatenate(local)
        if not np.allclose(np.diff(self.time), DT_HOURS / 24, rtol=0, atol=1e-6):
            raise ValueError(f'{tech}: irregular, overlapping or gapped time axis')
        if any(f is None for f in self.fill):
            raise ValueError(f'{tech}: int8 signals without _FillValue')
        self.lat, self.lon = grids[0]
        if any(not (np.array_equal(a, self.lat) and np.array_equal(b, self.lon)) for a, b in grids[1:]):
            raise ValueError(f'{tech}: grid changes between files')

    def read(self, index):
        """Return (event, time, lat, lon) int8 signals; index -1 yields missing values."""
        out = np.empty((len(self.events), len(index), len(self.lat), len(self.lon)), dtype=np.int8)
        for j, fill in enumerate(self.fill):
            out[j, index < 0] = fill
        present = np.flatnonzero(index >= 0)
        if not len(present):
            return out
        files = self.file[index[present]]
        for f in np.unique(files):
            pos = present[files == f]
            loc = self.local[index[pos]]
            if not np.array_equal(loc, np.arange(loc[0], loc[0] + len(loc))):
                raise ValueError('Paired indices are not contiguous within a file')
            ds = self.datasets[f]
            for j, event in enumerate(self.events):
                out[j, pos] = ds['signal_' + event][loc[0]:loc[-1] + 1]
        return out

    def close(self):
        self.datasets.close()


def flags(block, fills, domain):
    valid = np.broadcast_to(domain, block.shape[1:]).copy()
    flag = np.zeros(block.shape[1:], dtype=bool)
    for raw, fill in zip(block, fills):
        binary = (raw == 0) | (raw == 1)
        if np.any(~binary & (raw != fill) & domain[None]):
            raise ValueError('Non-binary, non-fill event value inside domain')
        valid &= binary
        flag |= raw == 1
    return valid, flag & valid


def accumulate(target, values, years, year_index):
    for year in np.unique(years):
        i = year_index.get(int(year))
        if i is not None:
            target[i] += values[years == year].sum(axis=0, dtype=np.uint16)


def to_days(counts, valid, nominal, domain):
    hours = valid * DT_HOURS
    ok = domain[None] & (hours / nominal[:, None, None] >= MIN_TIME_COVERAGE - 1e-8)
    return np.where(ok, counts * DT_HOURS / 24, np.nan).astype('f4')


def compare_cache(model, ssp, tech, patch, days):
    path = CACHE_ROOT / model / 'cache' / ssp / tech / f'{patch}.nc'
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        cached = ds['event_days'][:, 0].astype('f8')
        if str(ds['event'][0]) != 'any' or list(ds['year'][:]) != list(GRID_YEARS):
            raise ValueError(f'Unexpected cache layout: {path}')
    same_mask = np.isnan(cached) == np.isnan(days)
    both = np.isfinite(cached) & np.isfinite(days)
    diff = np.abs(cached[both] - days[both])
    by_year = [float(np.nanmax(np.where(both[i], np.abs(cached[i] - days[i]), 0))) for i in range(len(GRID_YEARS))]
    return dict(cache=str(path), mask_agreement=float(same_mask.mean()),
                max_abs_diff_days=float(diff.max()) if diff.size else None, max_abs_diff_by_year=by_year)


def run_unit(model, ssp, patch, output_root):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    target = Path(output_root) / model / ssp / f'{patch}.nc'
    if target.exists() and target.with_suffix('.json').exists():
        return target.with_suffix('.json')
    gc = load_grid_common()
    wind, solar = Source(model, ssp, patch, 'wind'), Source(model, ssp, patch, 'solar')
    try:
        if not (np.array_equal(wind.lat, solar.lat) and np.array_equal(wind.lon, solar.lon)):
            raise ValueError('Wind and solar grids differ')
        if wind.calendar != solar.calendar:
            raise ValueError('Wind and solar calendars differ')
        bbox = patch_manifest()['patches'][patch]['core_bbox_360']
        owner, area = gc.grid_geometry(wind.lat, wind.lon, bbox)
        domain = wind.domain & solar.domain & owner
        wanted = solar.time + PAIR_OFFSET_DAYS
        pair = np.clip(np.searchsorted(wind.time, wanted), 0, len(wind.time) - 1)
        matched = np.isclose(wind.time[pair], wanted, rtol=0, atol=1e-6)
        pair = np.where(matched, pair, -1)
        unpaired_wind = len(wind.time) - len(np.unique(pair[matched]))
        ny, nx = domain.shape
        year_index = {y: i for i, y in enumerate(GRID_YEARS)}
        acc = {k: np.zeros((len(GRID_YEARS), ny, nx), dtype=np.uint16)
               for k in ('union', 'union_valid', 'wind_any', 'wind_valid', 'solar_any', 'solar_valid')}
        for k0 in range(0, len(solar.time), BLOCK_STEPS):
            k = np.arange(k0, min(k0 + BLOCK_STEPS, len(solar.time)))
            if not np.isin(solar.year[k], GRID_YEARS).any():
                continue
            s_valid, s_flag = flags(solar.read(k), solar.fill, domain)
            w_index = pair[k]
            w_valid, w_flag = flags(wind.read(w_index), wind.fill, domain)
            both = s_valid & w_valid
            accumulate(acc['union'], (s_flag | w_flag) & both, solar.year[k], year_index)
            accumulate(acc['union_valid'], both, solar.year[k], year_index)
            accumulate(acc['solar_any'], s_flag, solar.year[k], year_index)
            accumulate(acc['solar_valid'], s_valid, solar.year[k], year_index)
            keep = w_index >= 0
            w_years = wind.year[w_index[keep]]
            accumulate(acc['wind_any'], w_flag[keep], w_years, year_index)
            accumulate(acc['wind_valid'], w_valid[keep], w_years, year_index)
            if (k0 // BLOCK_STEPS) % 120 == 0:
                LOGGER.info('%s/%s/%s step %d/%d, max RSS %.2f GB', model, ssp, patch, k0, len(solar.time),
                            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2)
        nominal = np.array([gc.year_hours(y, wind.calendar) for y in GRID_YEARS])
        union_days = to_days(acc['union'], acc['union_valid'], nominal, domain)
        checks = dict(
            wind=compare_cache(model, ssp, 'wind', patch, to_days(acc['wind_any'], acc['wind_valid'], nominal, domain)),
            solar=compare_cache(model, ssp, 'solar', patch, to_days(acc['solar_any'], acc['solar_valid'], nominal, domain)))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix('.tmp.nc')
        with netCDF4.Dataset(tmp, 'w') as ds:
            for name, size in (('year', len(GRID_YEARS)), ('lat', ny), ('lon', nx)):
                ds.createDimension(name, size)
            ds.createVariable('year', 'i4', ('year',))[:] = GRID_YEARS
            ds.createVariable('lat', 'f8', ('lat',))[:] = wind.lat
            ds.createVariable('lon', 'f8', ('lon',))[:] = wind.lon
            ds.createVariable('domain_mask', 'u1', ('lat', 'lon'), zlib=True)[:] = domain.astype('u1')
            ds.createVariable('cell_area_km2', 'f8', ('lat', 'lon'), zlib=True)[:] = area
            ds.createVariable('nominal_hours', 'f8', ('year',))[:] = nominal
            v = ds.createVariable('valid_hours', 'f4', ('year', 'lat', 'lon'), zlib=True, complevel=1)
            v[:] = acc['union_valid'] * DT_HOURS
            v = ds.createVariable('union_days', 'f4', ('year', 'lat', 'lon'), zlib=True, complevel=1, fill_value=np.nan)
            v[:] = union_days
            v.units = 'days per year'
            ds.setncatts(dict(model=model, scenario=ssp, patch=patch, calendar=wind.calendar,
                              wind_events=','.join(EVENTS['wind']), solar_events=','.join(EVENTS['solar']),
                              pairing='solar step t paired with wind step t+1.5 h; year of solar step'))
        tmp.replace(target)
        info = dict(model=model, ssp=ssp, patch=patch, path=str(target), solar_steps=int(len(solar.time)),
                    wind_steps=int(len(wind.time)), unpaired_solar=int((~matched).sum()),
                    unpaired_wind=int(unpaired_wind), domain_cells=int(domain.sum()), cache_checks=checks)
        write_json(target.with_suffix('.json'), info)
        return target.with_suffix('.json')
    finally:
        wind.close(); solar.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    p.add_argument('--ssps', nargs='+', choices=SSPS, default=list(SSPS))
    p.add_argument('--patches', nargs='+')
    p.add_argument('--workers', type=int, default=int(os.environ.get('SLURM_CPUS_PER_TASK', 1)))
    p.add_argument('--output-root', type=Path, default=OUT / 'grid_union')
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    units = [(m, s, q) for m in a.models for s in a.ssps for q in (a.patches or patches())]
    LOGGER.info('Units: %d, workers: %d', len(units), a.workers)
    failures = []
    with ProcessPoolExecutor(a.workers, mp_context=mp.get_context('spawn')) as pool:
        futures = {pool.submit(run_unit, *u, a.output_root): u for u in units}
        for f in as_completed(futures):
            try:
                LOGGER.info('Done %s -> %s', futures[f], f.result())
            except Exception as exc:
                failures.append((futures[f], repr(exc)))
                LOGGER.error('Failed %s: %r', futures[f], exc)
    if failures:
        raise SystemExit(f'{len(failures)} units failed: {failures[:5]}')


if __name__ == '__main__':
    main()
