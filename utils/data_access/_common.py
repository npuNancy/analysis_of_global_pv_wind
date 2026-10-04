"""Shared metadata queries, command-line output and bounded NetCDF selection."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path


MODELS = ('CANESM5', 'MPI-ESM1-2-HR', 'MRI-ESM2-0', 'BCC-CSM2-MR')
SCENARIOS = ('ssp126', 'ssp245', 'ssp585')


def load_json(path):
    """Read the current metadata document, including updates in this process."""
    with open(path, encoding='utf-8') as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def resolve_path(value, root):
    """Resolve a relative index path against its documented base directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path(root).expanduser() / path).absolute()


def matches(value, wanted):
    if isinstance(wanted, (list, tuple, set, frozenset)):
        return value in wanted
    return wanted is None or value == wanted


def _year_bounds(years):
    if len(years) != 2 or any(not isinstance(y, int) for y in years) or years[0] > years[1]:
        raise ValueError('years must be (start_year, end_year), with start_year <= end_year')
    return years[0], years[1]


def overlaps(start, end, years):
    if years is None:
        return True
    low, high = _year_bounds(years)
    return int(start) <= high and int(end) >= low


def _path(record_or_path):
    value = record_or_path.get('path') if isinstance(record_or_path, dict) else record_or_path
    if not value:
        raise ValueError('A record must contain a nonempty path')
    return Path(value).expanduser()


def open_record(record_or_path, *, variables=None, years=None, station_ids=None,
                lat_range=None, lon_range=None, chunks=None):
    """Open one file lazily and select data; close it with a ``with`` block.

    ``years`` is inclusive. Latitude/longitude bounds use the file's native
    coordinates, including its longitude convention. ``station_ids`` applies
    to the selected file only and rejects missing IDs. No scale correction,
    event union, activation mask or cross-file concatenation is applied.
    """
    import numpy as np
    import xarray as xr

    source = xr.open_dataset(_path(record_or_path), chunks=chunks)
    try:
        data = source
        if 'station_id' in data and 'station_id' not in data.coords:
            data = data.set_coords('station_id')
        if years is not None:
            low, high = _year_bounds(years)
            if 'time' not in data.coords or data.time.ndim != 1:
                raise ValueError('This file has no one-dimensional time coordinate; select annual or baseline years in find_records()')
            coordinate = data.time.dt.year
            data = data.isel({data.time.dims[0]: np.flatnonzero(((coordinate >= low) & (coordinate <= high)).values)})
        if station_ids is not None:
            if 'station_id' not in data or data.station_id.ndim != 1:
                raise ValueError('This file has no one-dimensional station_id coordinate')
            wanted = [station_ids] if isinstance(station_ids, str) else list(station_ids)
            wanted = [str(s) for s in wanted]
            if len(set(wanted)) != len(wanted):
                raise ValueError('station_ids contains duplicates')
            available = data.station_id.values.astype(str).tolist()
            if len(set(available)) != len(available):
                raise ValueError('The file contains duplicate station IDs')
            positions = {s:i for i,s in enumerate(available)}
            missing = [s for s in wanted if s not in positions]
            if missing:
                raise KeyError(f'Station IDs absent from this file: {missing[:10]}')
            data = data.isel({data.station_id.dims[0]: [positions[s] for s in wanted]})
        for names, bounds in [(('lat', 'latitude'), lat_range), (('lon', 'longitude'), lon_range)]:
            if bounds is None:
                continue
            if len(bounds) != 2 or bounds[0] > bounds[1]:
                raise ValueError(f'{names[0]}_range requires ordered (minimum, maximum) bounds')
            name = next((name for name in names if name in data), None)
            if name is None or data[name].ndim != 1:
                raise ValueError(f'This file has no one-dimensional {names[0]} coordinate')
            coordinate = data[name]
            keep = np.flatnonzero(((coordinate >= bounds[0]) & (coordinate <= bounds[1])).values)
            data = data.isel({coordinate.dims[0]: keep})
        if variables is not None:
            selected = [variables] if isinstance(variables, str) else list(variables)
            missing = sorted(set(selected) - set(data.variables))
            if missing:
                raise KeyError(f'Variables absent from this file: {missing}')
            data = data[selected]
        data.set_close(source.close)
        return data
    except BaseException:
        source.close()
        raise


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k,v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, 'tolist'):
        return _json_safe(value.tolist())
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def inspect_record(record_or_path):
    """Read dimensions and variable metadata, without loading array values."""
    import netCDF4

    with netCDF4.Dataset(_path(record_or_path)) as data:
        return _json_safe(dict(
            dimensions={k:len(v) for k,v in data.dimensions.items()},
            attributes={k:data.getncattr(k) for k in data.ncattrs()},
            variables={k:dict(dimensions=list(v.dimensions), dtype=str(v.dtype),
                              attributes={a:v.getncattr(a) for a in v.ncattrs()})
                       for k,v in data.variables.items()},
        ))


def run_cli(find_records, default_root, dataset, *, station=False, kinds=('cf',), snapshots=False):
    parser = argparse.ArgumentParser(description=f'Query {dataset} metadata and locate published NetCDF files.')
    parser.add_argument('--root', type=Path, default=default_root, help='Data run root (not its outputs subdirectory)')
    parser.add_argument('--model', choices=MODELS)
    parser.add_argument('--climate-ssp', choices=SCENARIOS)
    if station:
        parser.add_argument('--station-ssp', choices=SCENARIOS)
    parser.add_argument('--patch', help='Patch ID, for example R02C08')
    parser.add_argument('--tech', choices=('wind', 'solar'))
    parser.add_argument('--years', type=int, nargs=2, metavar=('START', 'END'), help='Inclusive analysis-year range; matches overlapping files')
    parser.add_argument('--kind', choices=kinds, default=kinds[0])
    if snapshots:
        parser.add_argument('--snapshot-year', type=int, choices=(2030, 2040, 2050))
    parser.add_argument('--limit', type=int, default=20, help='Number of records to print; 0 prints every match')
    parser.add_argument('--format', choices=('json', 'paths'), default='json')
    parser.add_argument('--check', action='store_true', help='Check existence and readability of the printed records')
    parser.add_argument('--inspect', action='store_true', help='Include NetCDF headers for the printed records, without reading arrays')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit must be >= 0')
    if args.inspect and args.format != 'json':
        parser.error('--inspect requires --format json')
    try:
        if args.years is not None:
            _year_bounds(args.years)
        records = find_records(args.root, model=args.model, climate_scenario=args.climate_ssp,
                               station_scenario=getattr(args, 'station_ssp', None), patch=args.patch,
                               tech=args.tech, years=args.years, kind=args.kind,
                               snapshot_year=getattr(args, 'snapshot_year', None))
        shown = [dict(row) for row in (records[:args.limit] if args.limit else records)]
        failed = False
        for row in shown:
            if args.check:
                path = _path(row)
                row.update(exists=path.is_file(), readable=os.access(path, os.R_OK))
                failed |= not (row['exists'] and row['readable'])
            if args.inspect:
                row['header'] = inspect_record(row)
        if args.format == 'paths':
            for row in shown:
                print(row['path'])
        else:
            print(json.dumps(_json_safe(dict(dataset=dataset, root=str(args.root), matched_files=len(records),
                                            shown_files=len(shown), records=shown)), ensure_ascii=False, indent=2))
        if failed:
            raise SystemExit(1)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
