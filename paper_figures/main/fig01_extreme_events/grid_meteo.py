"""Raw BCSD temperature, humidity, radiation and wind diagnostics on the event land domain.

For each model, SSP and patch the script accumulates area x time weighted sums by latitude row for the
2015-2024 and 2050-2059 windows: annual and monthly temperature/humidity statistics, RH histograms,
radiation and wind-speed means, and per-cell window sums for maps. Vapour pressure uses the Magnus
form over water, so ln RH = ln e - ln e_s holds exactly for every sample.
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

from paper_figures.config import MODELS, SSPS
from paper_figures.common.io import write_json
from paper_figures.main.fig01_extreme_events.meeting_common import OUT, BCSD_ROOT, CACHE_ROOT, patches, decode_time

WINDOWS = {'2015-2024': (2015, 2024), '2050-2059': (2050, 2059)}
WINDOW_YEARS = [y for a, b in WINDOWS.values() for y in range(a, b + 1)]
CHUNK_STEPS = 240
HIST_BINS = 102
TRH_STATS = ('w', 'T', 'RH', 'lnRH', 'lnes', 'rh85', 'rh90', 'rh95', 'cold', 'coldhum')
MAP_STATS = TRH_STATS + ('w_rsds', 'rsds', 'w_ws', 'ws')
ICING_T_C, ICING_RH, HUMID_RH = -2.0, 85.0, 95.0
RH_FLOOR = 0.1
LOGGER = logging.getLogger('grid_meteo')


def magnus_ln_es(t_c):
    return np.log(6.1094) + 17.625 * t_c / (t_c + 243.04)


def source(model, ssp, variable, patch):
    path = BCSD_ROOT / model / ssp / variable / f'{variable}_{model}_{ssp}_{patch}.nc'
    ds = netCDF4.Dataset(path)
    ds.set_auto_mask(False)
    ds[variable].set_var_chunk_cache(256 * 1024**2, 1009, 0.75)
    _, calendar, years, months, _ = decode_time(ds['time'])
    return ds, years, months, calendar


def blocks(years, first_year, last_year):
    """Yield chunk-aligned index ranges covering the requested years."""
    wanted = np.flatnonzero((years >= first_year) & (years <= last_year))
    if not len(wanted) or not np.array_equal(wanted, np.arange(wanted[0], wanted[-1] + 1)):
        raise ValueError(f'Non-contiguous or missing years {first_year}-{last_year}')
    if set(np.unique(years[wanted])) != set(range(first_year, last_year + 1)):
        raise ValueError(f'Incomplete year coverage {first_year}-{last_year}')
    start, stop = wanted[0], wanted[-1] + 1
    for b in range((start // CHUNK_STEPS) * CHUNK_STEPS, stop, CHUNK_STEPS):
        yield max(b, start), min(b + CHUNK_STEPS, stop)


class Land:
    """Domain cells in row-major order; rows are contiguous, so row sums use reduceat."""

    def __init__(self, domain, area):
        self.domain = domain
        self.area = area[domain]
        rows = np.nonzero(domain)[0]
        self.rows_present = np.unique(rows)
        self.starts = np.searchsorted(rows, self.rows_present)
        self.ny = domain.shape[0]

    def row_sum(self, values):
        """values (L,) -> (ny,) area-weighted row sums."""
        out = np.zeros(self.ny)
        if values.shape[0]:
            out[self.rows_present] = np.add.reduceat(values * self.area, self.starts)
        return out

    def read(self, ds, name, i0, i1):
        x = ds[name][i0:i1][:, self.domain].astype(np.float32)
        fill = getattr(ds[name], '_FillValue', None)
        if fill is not None:
            x[x == fill] = np.nan
        return x


def runs(mask):
    """Bounds of the single contiguous True run in a time mask."""
    idx = np.flatnonzero(mask)
    if not len(idx) or idx[-1] - idx[0] + 1 != len(idx):
        raise ValueError('Expected one contiguous time run')
    return idx[0], idx[-1] + 1


def to_celsius(x):
    finite = x[np.isfinite(x)]
    if not finite.size:
        return x
    if np.median(finite) > 100:
        return x - 273.15
    raise ValueError('Temperature is not in Kelvin by range check')


def trh_fields(t_c, rh):
    valid = np.isfinite(t_c) & np.isfinite(rh)
    t = np.where(valid, t_c, 0.0)
    h = np.where(valid, rh, 0.0)
    cold = valid & (t < ICING_T_C)
    return valid, dict(w=valid.astype(np.float32), T=t, RH=h,
                       lnRH=np.where(valid, np.log(np.maximum(h, RH_FLOOR) / 100), 0.0),
                       lnes=np.where(valid, magnus_ln_es(t), 0.0), rh85=valid & (h >= ICING_RH),
                       rh90=valid & (h >= 90.0), rh95=valid & (h >= HUMID_RH), cold=cold,
                       coldhum=cold & (h >= ICING_RH))


def run_unit(model, ssp, patch, output_root):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    target = Path(output_root) / model / ssp / f'{patch}.npz'
    if target.exists():
        return target
    with netCDF4.Dataset(CACHE_ROOT / model / 'cache' / ssp / 'wind' / f'{patch}.nc') as c:
        c.set_auto_mask(False)
        domain = c['domain_mask'][:] == 1
        area = c['cell_area_km2'][:].astype(np.float64)
        lat, lon = c['lat'][:], c['lon'][:]
    land = Land(domain, area)
    ny, nx = domain.shape
    tas, years_t, months_t, calendar = source(model, ssp, 'tas', patch)
    hurs, years_h, months_h, _ = source(model, ssp, 'hurs', patch)
    annual = {k: np.zeros((len(WINDOW_YEARS), ny)) for k in TRH_STATS}
    monthly = {k: np.zeros((len(WINDOWS), 12, ny)) for k in MAP_STATS}
    hist = np.zeros((len(WINDOWS), ny, HIST_BINS))
    maps = {k: np.zeros((len(WINDOWS), int(domain.sum()))) for k in MAP_STATS}
    window_of_year = {y: wi for wi, (a, b) in enumerate(WINDOWS.values()) for y in range(a, b + 1)}
    row_of_cell = np.nonzero(domain)[0]
    rh_scale = None
    try:
        for ds in (tas, hurs):
            if not (np.array_equal(ds['lat'][:], lat) and np.array_equal(ds['lon'][:], lon)):
                raise ValueError('BCSD grid differs from event grid')
        if not (np.array_equal(years_t, years_h) and np.array_equal(months_t, months_h)):
            raise ValueError('tas and hurs time axes differ')
        for i0, i1 in (blk for a, b in WINDOWS.values() for blk in blocks(years_t, a, b)):
            t_c = to_celsius(land.read(tas, 'tas', i0, i1))
            rh = land.read(hurs, 'hurs', i0, i1)
            if rh_scale is None and np.isfinite(rh).any():
                q = np.nanpercentile(rh, 99)
                if not 50 < q < 110:
                    raise ValueError(f'hurs does not look like percent: P99={q}')
                rh_scale = float(q)
            valid, fields = trh_fields(t_c, rh)
            yy, mm = years_t[i0:i1], months_t[i0:i1]
            for y in np.unique(yy):
                yi = WINDOW_YEARS.index(int(y))
                wi = window_of_year[int(y)]
                sel = yy == y
                for m in np.unique(mm[sel]):
                    a, b = runs(sel & (mm == m))
                    for k in TRH_STATS:
                        total = fields[k][a:b].sum(axis=0, dtype=np.float64)
                        rows = land.row_sum(total)
                        annual[k][yi] += rows
                        monthly[k][wi, m - 1] += rows
                        maps[k][wi] += total
                rh_sel = rh[sel]
                idx = np.where(rh_sel < 0, 0, np.where(rh_sel >= 100, HIST_BINS - 1,
                                                       np.floor(np.nan_to_num(rh_sel)) + 1)).astype(np.int64)
                key = (idx + row_of_cell[None, :] * HIST_BINS)[valid[sel]]
                wts = np.broadcast_to(land.area[None], rh_sel.shape)[valid[sel]]
                hist[wi] += np.bincount(key, weights=wts, minlength=ny * HIST_BINS).reshape(ny, HIST_BINS)
        LOGGER.info('%s/%s/%s T/RH done, max RSS %.2f GB', model, ssp, patch,
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2)
    finally:
        tas.close(); hurs.close()
    for name, (wvar, var) in (('rsds', ('w_rsds', 'rsds')), ('ws', ('w_ws', 'ws'))):
        if name == 'rsds':
            ds, yrs, mons, _ = source(model, ssp, 'rsds', patch)
            dsets = [ds]
        else:
            u, yrs, mons, _ = source(model, ssp, 'uas', patch)
            v, yv, mv, _ = source(model, ssp, 'vas', patch)
            if not (np.array_equal(yrs, yv) and np.array_equal(mons, mv)):
                raise ValueError('uas and vas time axes differ')
            dsets = [u, v]
        try:
            for wi, (a, b) in enumerate(WINDOWS.values()):
                for i0, i1 in blocks(yrs, a, b):
                    if name == 'rsds':
                        x = land.read(dsets[0], 'rsds', i0, i1)
                    else:
                        x = np.hypot(land.read(dsets[0], 'uas', i0, i1), land.read(dsets[1], 'vas', i0, i1))
                    ok = np.isfinite(x)
                    x0 = np.where(ok, x, 0.0)
                    mm = mons[i0:i1]
                    for m in np.unique(mm):
                        a, b = runs(mm == m)
                        n_ok = ok[a:b].sum(axis=0, dtype=np.float64); total = x0[a:b].sum(axis=0, dtype=np.float64)
                        monthly[wvar][wi, m - 1] += land.row_sum(n_ok)
                        monthly[var][wi, m - 1] += land.row_sum(total)
                        maps[wvar][wi] += n_ok; maps[var][wi] += total
        finally:
            for ds in dsets:
                ds.close()
    full_maps = {}
    for k, v in maps.items():
        grid = np.zeros((len(WINDOWS), ny, nx))
        grid[:, domain] = v
        full_maps[k] = grid
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + '.tmp.npz')
    np.savez_compressed(tmp, lat=lat, lon=lon, area=area, domain=domain, years=np.array(WINDOW_YEARS),
                        windows=np.array(list(WINDOWS)), hist=hist,
                        **{f'annual_{k}': v for k, v in annual.items()},
                        **{f'monthly_{k}': v for k, v in monthly.items()},
                        **{f'map_{k}': v for k, v in full_maps.items()})
    tmp.replace(target)
    write_json(target.with_suffix('.json'), dict(model=model, ssp=ssp, patch=patch, calendar=calendar,
                                                 rh_p99_first_block=rh_scale, domain_cells=int(domain.sum())))
    return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    p.add_argument('--ssps', nargs='+', choices=SSPS, default=list(SSPS))
    p.add_argument('--patches', nargs='+')
    p.add_argument('--workers', type=int, default=int(os.environ.get('SLURM_CPUS_PER_TASK', 1)))
    p.add_argument('--output-root', type=Path, default=OUT / 'grid_meteo')
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
