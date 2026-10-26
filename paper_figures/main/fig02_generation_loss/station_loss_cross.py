"""Per-MW station loss for every station of a paired SSP under each decadal climate window.

Station loss is linear in capacity, so a station's MWh/MW in one climate window does not depend on
which capacity snapshot weights it. The script reproduces the published Loss algorithm (decadal
12x8 normal-CF baseline excluding the event union, signed loss over union exposure) for all stations
in the 2050 catalogue and all three windows. Windows where the published Loss already covers a
station are used to check the reproduction against the published common-support totals.
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
import pandas as pd

from paper_figures.config import MODELS, SSPS, TECHS, EVENTS, OUTPUT
from paper_figures.common.io import write_json
from paper_figures.main.fig02_generation_loss.meeting_common import OUT, WINDOWS, OpenFiles, decode_time
from utils.data_access import read_cf_stations, read_extreme_stations

DT_HOURS = 3.0
TIME_BLOCK = 240
SLOTS = 96
ANNUAL_VARS = ('net', 'positive', 'normal_event', 'normal_annual', 'actual_event', 'event_hours', 'finite_hours')
LOGGER = logging.getLogger('station_loss_cross')


class StationSource:
    def __init__(self, records, variables, path_key, cache_bytes):
        self.variables = variables
        paths = sorted(r[path_key] for r in records)
        times, years, months, hours, owner, local = [], [], [], [], [], []
        self.ids = None
        self.fill = None
        for i, path in enumerate(paths):
            with netCDF4.Dataset(path) as ds:
                ds.set_auto_mask(False)
                ids = np.asarray(ds['station_id'][:]).astype(str)
                if self.ids is None:
                    self.ids = ids
                    self.fill = {v: getattr(ds[v], '_FillValue', None) for v in variables}
                elif not np.array_equal(ids, self.ids):
                    raise ValueError('Station order changes between files')
                numeric, _, y, m, h = decode_time(ds['time'])
            times.append(numeric); years.append(y); months.append(m); hours.append(h)
            owner.append(np.full(len(numeric), i)); local.append(np.arange(len(numeric)))
        self.datasets = OpenFiles(paths, variables, cache_bytes)
        order = np.argsort(np.concatenate(times), kind='stable')
        self.time = np.concatenate(times)[order]; self.year = np.concatenate(years)[order]
        self.month = np.concatenate(months)[order]; self.hour = np.concatenate(hours)[order]
        self.owner = np.concatenate(owner)[order]; self.local = np.concatenate(local)[order]
        if np.any(np.diff(self.time) <= 0):
            raise ValueError('Overlapping time axis')

    def window(self, first, last):
        index = np.flatnonzero((self.year >= first) & (self.year <= last))
        if set(np.unique(self.year[index])) != set(range(first, last + 1)):
            raise ValueError(f'Incomplete years {first}-{last}')
        if not np.allclose(np.diff(self.time[index]), DT_HOURS / 24, rtol=0, atol=1e-6):
            raise ValueError(f'Gapped time axis {first}-{last}')
        return index

    def read(self, variable, index, s0, s1, dtype):
        out = np.empty((len(index), s1 - s0), dtype=dtype)
        files = self.owner[index]
        for f in np.unique(files):
            pos = np.flatnonzero(files == f)
            loc = self.local[index[pos]]
            if not np.array_equal(loc, np.arange(loc[0], loc[0] + len(loc))):
                raise ValueError('Window not contiguous within file')
            out[pos] = self.datasets[f][variable][loc[0]:loc[-1] + 1, s0:s1]
        return out

    def close(self):
        self.datasets.close()


def baseline_sums(cf, signals, slot, sums, counts):
    normal_mask = np.logical_and.reduce([s == 0 for s in signals]) & np.isfinite(cf)
    cf0 = np.where(normal_mask, cf, 0).astype(np.float64)
    for k in np.unique(slot):
        sel = slot == k
        sums[k] += cf0[sel].sum(axis=0); counts[k] += normal_mask[sel].sum(axis=0)


def block_metrics(cf, signals, normal, year_pos, annual, event_net, event_hours):
    """Add per-MW totals of one time block to annual (var -> (years, n)) and per-event sums."""
    binary = [(s == 0) | (s == 1) for s in signals]
    valid_all = np.logical_and.reduce(binary)
    event_all = np.logical_or.reduce([s == 1 for s in signals]) & valid_all
    base_ok = np.isfinite(cf) & np.isfinite(normal)
    finite = base_ok & valid_all
    exposure = event_all & finite
    delta = (normal - cf).astype(np.float64)
    normal64 = normal.astype(np.float64)
    terms = dict(net=(delta, exposure), positive=(delta, exposure & (cf < normal)),
                 normal_event=(normal64, exposure), normal_annual=(normal64, finite),
                 actual_event=(cf.astype(np.float64), exposure), event_hours=(1.0, exposure),
                 finite_hours=(1.0, finite))
    for y in np.unique(year_pos):
        sel = year_pos == y
        for k, (values, mask) in terms.items():
            v = values[sel] if np.ndim(values) else values
            annual[k][y] += np.where(mask[sel], v, 0.0).sum(axis=0) * DT_HOURS
    for j, (s, ok) in enumerate(zip(signals, binary)):
        exp_e = (s == 1) & ok & base_ok
        event_net[j] += np.where(exp_e, delta, 0.0).sum(axis=0) * DT_HOURS
        event_hours[j] += exp_e.sum(axis=0) * DT_HOURS


def published_check(model, ssp, tech, patch, ids, annual):
    """Compare capacity-weighted sums with the published common-support shard totals."""
    shard = OUTPUT / 'loss_shards' / ssp / tech / patch
    support = pd.read_csv(shard / 'station_support.csv.gz', dtype={'station_id': str})
    totals = pd.read_csv(shard / 'annual.csv.gz')
    totals = totals[(totals.model == model) & (totals.climate_ssp == ssp) & (totals.station_ssp == ssp)
                    & (totals.country == 'GLOBAL') & (totals.event == 'all') & (totals.support == 'common')]
    position = pd.Series(np.arange(len(ids)), index=ids)
    columns = dict(net='net_mwh', positive='positive_mwh', normal_event='normal_event_mwh',
                   normal_annual='normal_annual_mwh', event_hours='capacity_event_hours')
    rows = []
    for wi, (snap, (first, last)) in enumerate(WINDOWS.items()):
        s = support[(support.snapshot == snap) & support.common]
        if s.empty:
            continue
        missing = ~s.station_id.isin(position.index)
        if missing.any():
            raise ValueError(f'{int(missing.sum())} supported stations absent from CF file')
        pos = position[s.station_id].to_numpy(); cap = s.capacity_mw.to_numpy()
        for yi, year in enumerate(range(first, last + 1)):
            ref = totals[(totals.snapshot == snap) & (totals.year == year)]
            if len(ref) != 1:
                raise ValueError(f'Expected one published total for {snap}/{year}')
            row = dict(snapshot=snap, year=year, nan_supported=int(np.isnan(annual['net'][wi, yi, pos]).sum()))
            for k, col in columns.items():
                mine = float(np.nansum(annual[k][wi, yi, pos] * cap)); theirs = float(ref[col].iloc[0])
                row[f'{k}_rel_diff'] = abs(mine - theirs) / max(abs(theirs), 1e-9)
            rows.append(row)
    return rows


def run_unit(model, ssp, tech, patch, output_root):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    target = Path(output_root) / ssp / tech / model / f'{patch}.npz'
    if target.exists() and target.with_suffix('.json').exists():
        return target
    query = dict(model=model, climate_scenario=ssp, station_scenario=ssp, patch=patch, tech=tech)
    cf_records = read_cf_stations.find_records(**query)
    sig_records = read_extreme_stations.find_records(**query)
    if not cf_records:
        return None
    events = EVENTS[tech]
    cf_src = StationSource(cf_records, [f'{tech}_cf'], 'path', 128 * 1024**2)
    sig_src = StationSource(sig_records, [f'signal_{e}' for e in events], 'path', 32 * 1024**2)
    try:
        ids = cf_src.ids; n = len(ids)
        if sorted(ids) != sorted(sig_src.ids) or len(set(ids)) != n:
            raise ValueError('CF and signal station sets differ or contain duplicates')
        perm = pd.Series(np.arange(n), index=sig_src.ids)[ids].to_numpy()
        annual = {k: np.zeros((len(WINDOWS), 10, n)) for k in ANNUAL_VARS}
        event_net = np.zeros((len(WINDOWS), len(events), n))
        event_hours = np.zeros((len(WINDOWS), len(events), n))
        cf_fill = cf_src.fill[f'{tech}_cf']

        def load(ci, si):
            cf = cf_src.read(f'{tech}_cf', ci, 0, n, np.float32)
            if cf_fill is not None:
                cf[cf == cf_fill] = np.nan
            return cf, [sig_src.read(f'signal_{e}', si, 0, n, np.int8)[:, perm] for e in events]

        for wi, (first, last) in enumerate(WINDOWS.values()):
            ci, si = cf_src.window(first, last), sig_src.window(first, last)
            if not np.array_equal(cf_src.time[ci], sig_src.time[si]):
                raise ValueError('CF and signal time axes differ')
            slot = (cf_src.month[ci].astype(int) - 1) * 8 + cf_src.hour[ci].astype(int) // 3
            if slot.min() < 0 or slot.max() >= SLOTS:
                raise ValueError('Unexpected month-hour slots')
            year_pos = cf_src.year[ci] - first
            sums = np.zeros((SLOTS, n)); counts = np.zeros((SLOTS, n))
            for b0 in range(0, len(ci), TIME_BLOCK):
                b = slice(b0, b0 + TIME_BLOCK)
                cf, signals = load(ci[b], si[b])
                baseline_sums(cf, signals, slot[b], sums, counts)
            with np.errstate(invalid='ignore', divide='ignore'):
                cf_normal = np.where(counts > 0, sums / counts, np.nan).astype(np.float32)
            window_annual = {k: v[wi] for k, v in annual.items()}
            for b0 in range(0, len(ci), TIME_BLOCK):
                b = slice(b0, b0 + TIME_BLOCK)
                cf, signals = load(ci[b], si[b])
                block_metrics(cf, signals, cf_normal[slot[b]], year_pos[b], window_annual,
                              event_net[wi], event_hours[wi])
            LOGGER.info('%s/%s/%s/%s window %d done, max RSS %.2f GB', model, ssp, tech, patch, first,
                        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2)
        no_data = annual['finite_hours'] == 0
        for k in ANNUAL_VARS:
            if k != 'finite_hours':
                annual[k][no_data] = np.nan
        checks = published_check(model, ssp, tech, patch, ids, annual)
    finally:
        cf_src.close(); sig_src.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + '.tmp.npz')
    np.savez_compressed(tmp, station_id=ids, windows=np.array(list(WINDOWS)), events=np.array(events),
                        type_net=event_net.astype(np.float32), type_hours=event_hours.astype(np.float32),
                        **{k: v for k, v in annual.items()})
    tmp.replace(target)
    worst = {k: max((r[k] for r in checks), default=None) for k in (checks[0] if checks else {}) if k.endswith('rel_diff')}
    write_json(target.with_suffix('.json'), dict(model=model, ssp=ssp, tech=tech, patch=patch, stations=int(n),
                                                 published_checks=checks, worst_rel_diff=worst,
                                                 nan_supported=sum(r['nan_supported'] for r in checks)))
    return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    p.add_argument('--ssps', nargs='+', choices=SSPS, default=list(SSPS))
    p.add_argument('--techs', nargs='+', choices=TECHS, default=list(TECHS))
    p.add_argument('--patches', nargs='+')
    p.add_argument('--workers', type=int, default=int(os.environ.get('SLURM_CPUS_PER_TASK', 1)))
    p.add_argument('--output-root', type=Path, default=OUT / 'station_loss_cross')
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    from paper_figures.main.fig02_generation_loss.meeting_common import patches
    units = [(m, s, t, q) for s in a.ssps for t in a.techs for m in a.models for q in (a.patches or patches())]
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
