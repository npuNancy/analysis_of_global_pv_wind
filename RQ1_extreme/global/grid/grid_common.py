"""Shared grid exposure reduction and figure utilities; no work on import."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import cftime
import netCDF4
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
INPUT_ROOT = Path("/work/share/acp6varuz3/extreme_grid/grid_v2")
MODELS = ("CANESM5", "MPI-ESM1-2-HR", "MRI-ESM2-0", "BCC-CSM2-MR")
SSPS = ("ssp126", "ssp245", "ssp585")
TECHS = ("wind", "solar")
EVENTS = {
    "wind": ("high_temp", "high_wind", "hot_humid", "icing", "low_resource"),
    "solar": ("cold_highwind", "freezing_rain", "high_humidity", "icing", "low_resource", "rainstorm"),
}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp245": "#b77c19", "ssp585": "#9e1b1b"}
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
EVENT_LABEL = {
    "any": "Any event", "high_temp": "High temperature", "high_wind": "High wind",
    "hot_humid": "Hot and humid", "icing": "Icing", "low_resource": "Low resource",
    "cold_highwind": "Cold and high wind", "freezing_rain": "Freezing rain",
    "high_humidity": "High humidity", "rainstorm": "Rainstorm",
}
EVENT_COLOR = ("#3b6fb6", "#d95f02", "#b2182b", "#67a9cf", "#7570b3", "#1b9e77")
SHAPEFILE = ROOT / "data/maps/natural_earth/ne_110m_admin_0_countries.shp"
LOGGER = logging.getLogger("rq1_extreme.grid")


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s]: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", force=True)


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def grid_geometry(lat, lon, bbox):
    """Unique half-open patch ownership and exact spherical cell areas."""
    lat, lon = np.asarray(lat), np.asarray(lon)
    if len(lat) < 2 or len(lon) < 2:
        raise ValueError("Need at least two coordinates on each spatial axis")
    dlat, dlon = float(np.median(np.diff(lat))), float(np.median(np.diff(lon)))
    if dlat <= 0 or dlon <= 0 or not np.allclose(np.diff(lat), dlat) or not np.allclose(np.diff(lon), dlon):
        raise ValueError("Expected increasing regular spatial coordinates")
    west, east, south, north = bbox
    xx = lon % 360
    eps = 1e-6
    own_lon = (xx >= west - eps) & (xx < east - eps)
    own_lat = (lat >= south - eps) & ((lat < north - eps) | ((north == 90) & (lat <= 90)))
    owner = own_lat[:, None] & own_lon[None, :]
    lower, upper = np.clip(lat - dlat / 2, -90, 90), np.clip(lat + dlat / 2, -90, 90)
    row_area = 6371.0088**2 * np.deg2rad(dlon) * (np.sin(np.deg2rad(upper)) - np.sin(np.deg2rad(lower)))
    area = np.broadcast_to(row_area[:, None], (len(lat), len(lon))).copy()
    return owner, area


def year_hours(year, calendar):
    first = cftime.datetime(int(year), 1, 1, calendar=calendar)
    last = cftime.datetime(int(year) + 1, 1, 1, calendar=calendar)
    return (last - first).total_seconds() / 3600


def event_block(arrays, fills, domain):
    """Return common valid mask and event/union flags, preserving missingness."""
    shape = arrays[0].shape
    valid = np.broadcast_to(domain, shape).copy()
    flags = []
    for raw, fill in zip(arrays, fills):
        binary = (raw == 0) | (raw == 1)
        missing = np.isnan(raw) if fill is None else raw == fill
        if np.any(~binary & ~missing & domain[None, :, :]):
            raise ValueError("Non-binary, non-fill event value inside domain")
        valid &= binary
        flags.append(raw == 1)
    union = np.logical_or.reduce(flags)
    return valid, [union, *flags]


def reduce_block(counts, valid_counts, arrays, fills, domain, block_years, year_indices):
    valid, flags = event_block(arrays, fills, domain)
    for year in np.unique(block_years):
        if int(year) not in year_indices:
            continue
        i = year_indices[int(year)]
        selected = block_years == year
        vv = valid[selected]
        valid_counts[i] += vv.sum(axis=0, dtype=np.uint32)
        for j, flag in enumerate(flags):
            counts[i, j] += (flag[selected] & vv).sum(axis=0, dtype=np.uint32)


def select_inventory(input_root, models, ssps, techs, selected_patches=None):
    raw = (input_root / "runtime/authoritative_index.json").read_bytes()
    index = json.loads(raw)
    manifest = json.loads((input_root / "runtime/patch_manifest.json").read_text())
    patches = sorted(selected_patches or manifest["patches"])
    if set(patches) - set(manifest["patches"]):
        raise ValueError("Unknown patch selection")
    expected = {(m, s, p, t) for m in models for s in ssps for p in patches for t in techs}
    found = {}
    for unit, row in index["combinations"].items():
        key = (row["model"], row["scenario"], row["patch"], row["tech"])
        if key not in expected:
            continue
        if key in found:
            raise ValueError("Duplicate combination: " + str(key))
        record = dict(row)
        record["unit_id"] = unit
        record["bbox"] = manifest["patches"][row["patch"]]["core_bbox_360"]
        found[key] = record
    if set(found) != expected:
        raise ValueError("Missing combinations: " + str(sorted(expected - set(found))[:10]))
    return [found[k] for k in sorted(found)], patches, hashlib.sha256(raw).hexdigest()


def aggregate_combination(task):
    row, years, output, min_coverage, block_size = task
    model, scenario, tech, patch = (row[k] for k in ("model", "scenario", "tech", "patch"))
    events = ("any", *EVENTS[tech])
    paths = sorted((a for a in row["artifacts"] if a["stage"] == "signals"), key=lambda a: a["years"])
    paths = [a for a in paths if any(int(a["years"].split("-")[0]) <= y <= int(a["years"].split("-")[1]) for y in years)]
    signature = {
        "unit": row["unit_id"], "years": years, "bbox": row["bbox"], "min_coverage": min_coverage,
        "code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "files": [(a["unified_output"], Path(a["unified_output"]).stat().st_size,
                   Path(a["unified_output"]).stat().st_mtime_ns) for a in paths],
    }
    fingerprint = digest_json(signature)
    target = Path(output) / model / "cache" / scenario / tech / (patch + ".nc")
    if target.exists():
        with netCDF4.Dataset(target) as ds:
            if getattr(ds, "fingerprint", "") == fingerprint:
                LOGGER.info("Cached %s/%s/%s/%s", model, scenario, tech, patch)
                return {"model": model, "scenario": scenario, "tech": tech, "patch": patch,
                        "path": str(target.resolve()), "fingerprint": fingerprint}
    counts = valid_counts = lat = lon = domain = area = calendar = dt_hours = None
    source_steps = np.zeros(len(years), dtype=np.int32)
    year_indices = {y: i for i, y in enumerate(years)}
    last_time = None
    for artifact in paths:
        with netCDF4.Dataset(artifact["unified_output"]) as ds:
            ds.set_auto_mask(False)
            this_lat, this_lon = ds["lat"][:], ds["lon"][:]
            owner, this_area = grid_geometry(this_lat, this_lon, row["bbox"])
            this_domain = (ds["domain_mask"][:] == 1) & owner
            time = ds["time"]
            cal = getattr(time, "calendar", "standard")
            numeric = np.asarray(time[:], dtype=np.float64)
            if len(numeric) < 2 or not np.all(np.diff(numeric) > 0) or not np.allclose(np.diff(numeric), np.diff(numeric)[0]):
                raise ValueError("Irregular time axis: " + artifact["unified_output"])
            dates = netCDF4.num2date(numeric, time.units, calendar=cal, only_use_cftime_datetimes=True)
            step = (dates[1] - dates[0]).total_seconds() / 3600
            if step <= 0:
                raise ValueError("Invalid timestep")
            year_by_step = np.array([v.year for v in dates], dtype=np.int32)
            if lat is None:
                lat, lon, domain, area, calendar, dt_hours = this_lat, this_lon, this_domain, this_area, cal, step
                counts = np.zeros((len(years), len(events), len(lat), len(lon)), dtype=np.uint32)
                valid_counts = np.zeros((len(years), len(lat), len(lon)), dtype=np.uint32)
            elif not (np.array_equal(lat, this_lat) and np.array_equal(lon, this_lon)
                      and np.array_equal(domain, this_domain) and cal == calendar and np.isclose(step, dt_hours)):
                raise ValueError("Grid, mask, calendar or timestep changes within combination")
            if last_time is not None and dates[0] <= last_time:
                raise ValueError("Overlapping source segments")
            last_time = dates[-1]
            variables = [ds["signal_" + e] for e in EVENTS[tech]]
            for variable in variables:
                if variable.dimensions != ("time", "lat", "lon"):
                    raise ValueError("Unexpected signal dimensions")
                variable.set_var_chunk_cache(16 * 1024**2, 1009, 0.75)
            fills = [getattr(v, "_FillValue", None) for v in variables]
            wanted = np.isin(year_by_step, years)
            for first in range(0, len(numeric), block_size):
                last = min(first + block_size, len(numeric))
                if not wanted[first:last].any():
                    continue
                block_years = year_by_step[first:last]
                arrays = [v[first:last, :, :] for v in variables]
                reduce_block(counts, valid_counts, arrays, fills, domain, block_years, year_indices)
            for y, i in year_indices.items():
                source_steps[i] += int(np.count_nonzero(year_by_step == y))
    if lat is None:
        raise ValueError("No source segments selected")
    nominal_hours = np.array([year_hours(y, calendar) for y in years])
    if np.any(source_steps * dt_hours > nominal_hours + 1e-4) or np.any(source_steps * dt_hours / nominal_hours < min_coverage):
        raise ValueError("Time axis does not cover requested years: " + str(source_steps))
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp.nc")
    with netCDF4.Dataset(temp, "w") as ds:
        for name, size in (("year", len(years)), ("event", len(events)), ("lat", len(lat)), ("lon", len(lon))):
            ds.createDimension(name, size)
        ds.createVariable("year", "i4", ("year",))[:] = years
        ev = ds.createVariable("event", str, ("event",))
        ev[:] = np.array(events, dtype=object)
        ds.createVariable("lat", "f8", ("lat",))[:] = lat
        ds.createVariable("lon", "f8", ("lon",))[:] = lon
        ds.createVariable("domain_mask", "u1", ("lat", "lon"), zlib=True)[:] = domain.astype("u1")
        ds.createVariable("cell_area_km2", "f8", ("lat", "lon"), zlib=True)[:] = area
        ds.createVariable("nominal_hours", "f8", ("year",))[:] = nominal_hours
        ds.createVariable("source_hours", "f8", ("year",))[:] = source_steps * dt_hours
        hours = ds.createVariable("valid_hours", "f4", ("year", "lat", "lon"), zlib=True, complevel=1,
                                  chunksizes=(1, min(32, len(lat)), min(32, len(lon))))
        days = ds.createVariable("event_days", "f4", ("year", "event", "lat", "lon"), fill_value=np.nan,
                                 zlib=True, complevel=1, chunksizes=(1, 1, min(32, len(lat)), min(32, len(lon))))
        days.units = "days per year"
        hours.units = "hours"
        for i in range(len(years)):
            hh = valid_counts[i] * dt_hours
            hours[i] = hh
            valid = domain & (hh / nominal_hours[i] >= min_coverage - 1e-8)
            for j in range(len(events)):
                days[i, j] = np.where(valid, counts[i, j] * dt_hours / 24, np.nan)
        ds.setncatts({"model": model, "scenario": scenario, "tech": tech, "patch": patch,
                      "calendar": calendar, "dt_hours": dt_hours, "min_time_coverage": min_coverage,
                      "fingerprint": fingerprint, "source_run_id": row["source_run_id"],
                      "source_signature": json.dumps(signature)})
    temp.replace(target)
    LOGGER.info("Reduced %s/%s/%s/%s", model, scenario, tech, patch)
    return {"model": model, "scenario": scenario, "tech": tech, "patch": patch,
            "path": str(target.resolve()), "fingerprint": fingerprint}


def cache_dataset(record):
    ds = netCDF4.Dataset(record["path"])
    ds.set_auto_mask(False)
    if ds.fingerprint != record["fingerprint"]:
        ds.close()
        raise ValueError("Cache fingerprint mismatch: " + record["path"])
    return ds


def global_patch_rows(record):
    rows = []
    with cache_dataset(record) as ds:
        area = ds["cell_area_km2"][:]
        domain = ds["domain_mask"][:] == 1
        weight = np.where(domain, area, 0)
        reference = float(weight.sum())
        events = list(ds["event"][:])
        for i, year in enumerate(ds["year"][:]):
            time_area = float((ds["valid_hours"][i] / ds["nominal_hours"][i] * weight).sum())
            for j, event in enumerate(events):
                days = ds["event_days"][i, j]
                valid = np.isfinite(days) & domain
                rows.append({**{k: record[k] for k in ("model", "scenario", "tech", "patch")},
                             "year": int(year), "event": event,
                             "weighted_days_km2": float(np.nansum(days * weight)),
                             "valid_area_km2": float(weight[valid].sum()),
                             "reference_area_km2": reference, "valid_cells": int(valid.sum()),
                             "domain_cells": int(domain.sum()), "time_area_km2": time_area})
    return rows


def aggregate_rows(rows, groups):
    sums = ["weighted_days_km2", "valid_area_km2", "reference_area_km2", "valid_cells", "domain_cells", "time_area_km2"]
    table = pd.DataFrame(rows).groupby(groups, as_index=False, dropna=False)[sums].sum()
    table["exposure_days"] = table["weighted_days_km2"].div(table["valid_area_km2"].replace(0, np.nan))
    denominator = table["reference_area_km2"].replace(0, np.nan)
    table["coverage_pct"] = 100 * table["valid_area_km2"].div(denominator)
    table["time_coverage_pct"] = 100 * table["time_area_km2"].div(denominator)
    return table


def ensemble_table(table, keys, models):
    rows = []
    values = ["exposure_days", "coverage_pct", "time_coverage_pct", "valid_area_km2",
              "reference_area_km2", "valid_cells", "domain_cells"]
    for identity, group in table.groupby(keys, dropna=False, sort=True):
        if group["model"].duplicated().any():
            raise ValueError("Duplicate model records")
        group = group.set_index("model").reindex(models)
        if not isinstance(identity, tuple):
            identity = (identity,)
        row = dict(zip(keys, identity))
        row["model"] = "ensemble_mean"
        row["n_models"] = int(group["exposure_days"].notna().sum())
        for column in values:
            vals = group[column].to_numpy(dtype=float)
            row[column] = float(vals.mean()) if np.isfinite(vals).all() else np.nan
        exp = group["exposure_days"].to_numpy(dtype=float)
        row["model_min"] = float(exp.min()) if np.isfinite(exp).all() else np.nan
        row["model_max"] = float(exp.max()) if np.isfinite(exp).all() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def period_table(annual, baseline, future, country=False):
    keys = (["country", "country_iso3"] if country else []) + ["model", "scenario", "tech", "event"]
    rows = []
    for identity, group in annual.groupby(keys, dropna=False):
        row = dict(zip(keys, identity))
        by_year = group.set_index("year")
        for label, years in (("baseline", baseline), ("future", future)):
            sample = by_year.reindex(years)
            for col in ("exposure_days", "coverage_pct"):
                vals = sample[col].to_numpy(dtype=float)
                row[label + "_" + col] = float(vals.mean()) if np.isfinite(vals).all() else np.nan
        row["change_days"] = row["future_exposure_days"] - row["baseline_exposure_days"]
        rows.append(row)
    return pd.DataFrame(rows)


def period_ensemble(table, models, country=False):
    keys = (["country", "country_iso3"] if country else []) + ["scenario", "tech", "event"]
    metrics = ["baseline_exposure_days", "future_exposure_days", "baseline_coverage_pct", "future_coverage_pct", "change_days"]
    rows = []
    for identity, group in table.groupby(keys, dropna=False):
        if group["model"].duplicated().any():
            raise ValueError("Duplicate model period rows")
        group = group.set_index("model").reindex(models)
        row = dict(zip(keys, identity))
        row["model"] = "ensemble_mean"
        row["n_models"] = int(group["change_days"].notna().sum())
        for column in metrics:
            a = group[column].to_numpy(dtype=float)
            row[column] = float(a.mean()) if np.isfinite(a).all() else np.nan
        a = group["change_days"].to_numpy(dtype=float)
        row["model_min"] = float(a.min()) if np.isfinite(a).all() else np.nan
        row["model_max"] = float(a.max()) if np.isfinite(a).all() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def configure_style():
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"],
                         "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": 0.7, "legend.frameon": False,
                         "figure.facecolor": "white", "axes.facecolor": "white"})


def save_figure(fig, path):
    import matplotlib.pyplot as plt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def period_label(years):
    return str(years[0]) if len(years) == 1 else f"{years[0]}–{years[-1]}"


def model_title(model, models):
    return f"{len(models)}-model equal-weight mean (range shaded)" if model == "ensemble_mean" else model


def country_geometries(shp_path):
    import shapefile
    from shapely.geometry import shape
    from shapely.ops import unary_union
    grouped, metadata = {}, {}
    with shapefile.Reader(str(shp_path), encoding="utf-8") as reader:
        for record in reader.iterShapeRecords():
            attrs = record.record.as_dict()
            name = attrs["NAME"]
            country = "China" if name == "Taiwan" else name
            geom = shape(record.shape.__geo_interface__)
            if not geom.is_valid:
                geom = geom.buffer(0)
            grouped.setdefault(country, []).append(geom)
            if country not in metadata or name == country:
                iso = "CHN" if country == "China" else attrs.get("ISO_A3", "")
                if iso in ("", "-99"):
                    iso = attrs.get("ADM0_A3", country)
                metadata[country] = {"country": country, "country_iso3": iso}
    names = sorted(grouped)
    return [metadata[n] for n in names], [unary_union(grouped[n]) for n in names]
