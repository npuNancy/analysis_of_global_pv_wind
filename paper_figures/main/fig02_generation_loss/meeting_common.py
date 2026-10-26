"""Shared definitions for the meeting follow-up analyses."""
import importlib.util
import json
from pathlib import Path

import numpy as np

from paper_figures.config import ROOT

HERE = ROOT / 'paper_figures/main/fig02_generation_loss'
OUT = HERE / 'outputs'
LOGS = ROOT / 'logs/paper_figures/fig02'
GRID_ROOT = Path('/work/home/acjpoxgsdu/extreme_grid/extreme_grid_v2')
BCSD_ROOT = Path('/work/share/aczlvkl1ac/bcsd_runs/production_v2/outputs')
CACHE_ROOT = ROOT / 'RQ1_extreme/global/grid/outputs'
GRID_YEARS = tuple(range(2015, 2061))
WINDOWS = {2030: (2030, 2039), 2040: (2040, 2049), 2050: (2050, 2059)}
MIN_TIME_COVERAGE = 0.99

LAT_BANDS = (('60-90N', 60, 90), ('30-60N', 30, 60), ('0-30N', 0, 30),
             ('0-30S', -30, 0), ('30-60S', -60, -30))

WEATHER_TYPES = (
    ('high_temp', 'wind', 'high_temp', 'High temperature'),
    ('high_wind', 'wind', 'high_wind', 'High wind'),
    ('hot_humid', 'wind', 'hot_humid', 'Hot-humid'),
    ('icing', 'wind', 'icing', 'Icing'),
    ('low_wind', 'wind', 'low_resource', 'Low wind resource'),
    ('cold_highwind', 'solar', 'cold_highwind', 'Cold high wind'),
    ('freezing_rain', 'solar', 'freezing_rain', 'Freezing rain'),
    ('high_humidity', 'solar', 'high_humidity', 'High humidity'),
    ('low_light', 'solar', 'low_resource', 'Low solar resource'),
    ('rainstorm', 'solar', 'rainstorm', 'Rainstorm'),
)


def lat_band(lat):
    """Return band labels for latitudes; the equator belongs to the northern band."""
    lat = np.asarray(lat, dtype=float)
    labels = np.full(lat.shape, '', dtype=object)
    for name, south, north in LAT_BANDS:
        upper = (lat <= north) if north == 90 else (lat < north)
        labels[(lat >= south) & upper] = name
    return labels


def load_grid_common():
    """Import the RQ1 grid helpers; the package path contains the keyword ``global``."""
    path = ROOT / 'RQ1_extreme/global/grid/grid_common.py'
    spec = importlib.util.spec_from_file_location('rq1_grid_common', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_manifest():
    return json.loads((GRID_ROOT / 'runtime/patch_manifest.json').read_text())


def patches():
    return sorted(patch_manifest()['patches'])


class OpenFiles:
    """Keep at most ``keep`` NetCDF files open; HDF5 chunk caches are per open file and variable."""

    def __init__(self, paths, variables, cache_bytes, keep=2):
        self.paths, self.variables, self.cache_bytes, self.keep = list(paths), list(variables), cache_bytes, keep
        self.open = {}

    def __getitem__(self, i):
        import netCDF4
        if i in self.open:
            self.open[i] = self.open.pop(i)
            return self.open[i]
        while len(self.open) >= self.keep:
            oldest = next(iter(self.open))
            self.open.pop(oldest).close()
        ds = netCDF4.Dataset(self.paths[i])
        ds.set_auto_mask(False)
        for v in self.variables:
            ds[v].set_var_chunk_cache(self.cache_bytes, 1009, 0.75)
        self.open[i] = ds
        return ds

    def close(self):
        for ds in self.open.values():
            ds.close()
        self.open = {}


def decode_time(variable):
    import netCDF4
    numeric = np.asarray(variable[:], dtype=np.float64)
    calendar = getattr(variable, 'calendar', 'standard')
    dates = netCDF4.num2date(numeric, variable.units, calendar=calendar, only_use_cftime_datetimes=True)
    years = np.fromiter((d.year for d in dates), dtype=np.int32, count=len(dates))
    months = np.fromiter((d.month for d in dates), dtype=np.int8, count=len(dates))
    hours = np.fromiter((d.hour for d in dates), dtype=np.int8, count=len(dates))
    return numeric, calendar, years, months, hours
