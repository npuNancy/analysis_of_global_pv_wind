"""Prepare country map data from existing annual grid caches and station mappings."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys

import netCDF4
import numpy as np
import pandas as pd
import shapely

HERE = Path(__file__).resolve().parent
RQ = HERE.parents[1]
sys.path.insert(0, str(RQ / "global/grid"))
from grid_common import (MODELS, SSPS, TECHS, SHAPEFILE, EVENTS, cache_dataset,
                         country_geometries, configure_logging, LOGGER, write_json, digest_json)

OUTPUT = HERE / "outputs"
STATIONS = Path("/work/share/acp6varuz3/extreme_grid/stations_v2")
YEARS = list(range(2050, 2060))
BASELINE = list(range(2030, 2040))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assign_countries(lon, lat, geometries):
    x = (np.asarray(lon) + 180) % 360 - 180
    y = np.asarray(lat)
    ids = np.full(len(x), -1, dtype=np.int32)
    for i, geom in enumerate(geometries):
        west, south, east, north = geom.bounds
        sel = np.flatnonzero((ids < 0) & (x >= west) & (x <= east) & (y >= south) & (y <= north))
        inside = shapely.intersects_xy(geom, x[sel], y[sel])
        ids[sel[inside]] = i
    return ids


def capacity_snapshot(path, tech):
    parts = []
    for chunk in pd.read_csv(path, usecols=["station_id", "type", "year", "capacity_gw"], chunksize=200000):
        part = chunk[(chunk.type == tech) & (chunk.year == 2050)]
        parts.append(part[["station_id", "capacity_gw"]])
    data = pd.concat(parts, ignore_index=True)
    if data.empty or not np.isfinite(data.capacity_gw).all() or (data.capacity_gw < 0).any():
        raise ValueError("Invalid or missing 2050 capacity snapshot: " + str(path))
    # Multiple source rows at the same station in one snapshot contribute capacity.
    return data.groupby("station_id").capacity_gw.sum()


def validate_cache_source(ds, record, mapping):
    signature = json.loads(ds.source_signature)
    source_files = {str(Path(p).resolve()): (size, mtime) for p, size, mtime in signature["files"]}
    for out in record["outputs"]:
        src = out["source"]["stat"]
        if source_files.get(str(Path(src["path"]).resolve())) != (src["size"], src["mtime_ns"]):
            raise ValueError("Station source and grid-cache source differ")
        with netCDF4.Dataset(out["artifact"]["path"]) as st:
            if st.activation_mask != "off" or st.mapping_sha256 != record["mapping_identity"]:
                raise ValueError("Station masking or mapping differs from cache-reuse contract")
            if st.identity != out["identity"] or set(n.removeprefix("signal_") for n in st.variables if n.startswith("signal_")) != set(EVENTS[ds.tech]):
                raise ValueError("Station artifact identity or event set differs")
            if not np.array_equal(st["station_id"][:], mapping["station_id"][:]):
                raise ValueError("Station order differs from mapping")
    if not np.isclose(float(ds.min_time_coverage), 0.99):
        raise ValueError("Expected 99% annual temporal coverage")
    return signature


def sample_raw_check(outputs, station_index, expected, matched):
    """Verify one real station over the full future decade; no full hourly scan."""
    counts = dict.fromkeys(YEARS, 0)
    valid_counts = dict.fromkeys(YEARS, 0)
    nominal = {}
    from grid_common import year_hours
    for out in outputs:
        with netCDF4.Dataset(out["artifact"]["path"]) as st:
            st.set_auto_mask(False)
            tv = st["time"]
            calendar = getattr(tv, "calendar", "standard")
            times = netCDF4.num2date(tv[:], tv.units, calendar=calendar)
            years = np.array([t.year for t in times])
            step = (times[1] - times[0]).total_seconds() / 3600
            flags = [st[n][:, station_index] for n in st.variables if n.startswith("signal_")]
            valid = np.logical_and.reduce([(a == 0) | (a == 1) for a in flags]) & matched
            union = np.logical_or.reduce([a == 1 for a in flags])
            for y in YEARS:
                sel = years == y
                counts[y] += int((valid & union & sel).sum()) * step / 24
                valid_counts[y] += int((valid & sel).sum()) * step
                nominal[y] = year_hours(y, calendar)
    actual = np.array([counts[y] if valid_counts[y] / nominal[y] >= 0.99 - 1e-8 else np.nan for y in YEARS])
    if not np.allclose(actual, expected, atol=2e-5, equal_nan=True):
        raise ValueError("Raw station events disagree with annual cache")
    return {"station_column": int(station_index), "years": YEARS, "raw_days": actual.tolist(),
            "cache_days": expected.tolist(), "matched": bool(matched)}


def station_group(task):
    model, ssp, tech, records, grid_records, capacity_path, shp, output, identity = task
    target = Path(output) / "cache" / model / (ssp + "_" + tech + ".csv")
    receipt = target.with_suffix(".json")
    fingerprint = digest_json({"identity": identity, "model": model, "ssp": ssp, "tech": tech, "script": sha(__file__)})
    if target.exists() and receipt.exists():
        meta = json.loads(receipt.read_text())
        if meta.get("fingerprint") == fingerprint and meta.get("csv_sha256") == sha(target):
            return str(target)
    metadata, geoms = country_geometries(shp)
    labels = [{"country": "UNASSIGNED", "country_iso3": "UNK"}, *metadata]
    n = len(labels)
    capacity = capacity_snapshot(capacity_path, tech)
    totals = np.zeros(n)
    stations = np.zeros(n)
    numerators = np.zeros((len(YEARS), n))
    denominators = np.zeros_like(numerators)
    valid_stations = np.zeros_like(numerators)
    seen = set()
    checks = []
    for patch, record in records:
        if record["status"] == "SKIPPED_NO_STATIONS":
            if record["outputs"] or not Path(record["audit"]["path"]).is_file():
                raise ValueError("Invalid empty-combination evidence")
            continue
        if record["status"] != "COMPLETED":
            raise ValueError("Incomplete station combination")
        outputs = [o for o in record["outputs"] if o["period"] in ("2050-2054", "2055-2059")]
        if len(outputs) != 2:
            raise ValueError("Missing future station segments")
        record = {**record, "outputs": outputs}
        mapping_path = outputs[0]["contract"]["mapping_file"]["path"]
        gr = grid_records[patch]
        with netCDF4.Dataset(mapping_path) as mapping, cache_dataset(gr) as ds:
            validate_cache_source(ds, record, mapping)
            ids = np.array(mapping["station_id"][:], dtype=str)
            if seen.intersection(ids) or len(set(ids)) != len(ids):
                raise ValueError("Stations repeated across patches")
            seen.update(ids)
            cap = capacity.reindex(ids, fill_value=0).to_numpy(float)
            if np.any((cap > 0) & (mapping["activation_year"][:] > 2050)):
                raise ValueError("2050 snapshot contains inactive station")
            country = assign_countries(mapping["lon"][:], mapping["lat"][:], geoms) + 1
            totals += np.bincount(country, weights=cap, minlength=n)
            stations += np.bincount(country, weights=(cap > 0).astype(float), minlength=n)
            iy, ix = mapping["source_iy"][:], mapping["source_ix"][:]
            matched = mapping["mapping_status"][:] == 0
            if np.any(matched & ((iy < 0) | (iy >= len(ds["lat"])) | (ix < 0) | (ix >= len(ds["lon"])))):
                raise ValueError("Mapping index outside cached grid")
            safe_y, safe_x = np.clip(iy, 0, len(ds["lat"])-1), np.clip(ix, 0, len(ds["lon"])-1)
            if not np.all(ds["domain_mask"][:][safe_y[matched], safe_x[matched]] == 1):
                raise ValueError("Matched station falls outside cached domain ownership")
            if not np.allclose(ds["lat"][:][safe_y[matched]], mapping["source_grid_lat"][:][matched], atol=1e-6):
                raise ValueError("Grid latitude differs from station mapping")
            lon_diff = (ds["lon"][:][safe_x[matched]] - mapping["source_grid_lon"][:][matched] + 180) % 360 - 180
            if not np.allclose(lon_diff, 0, atol=1e-6):
                raise ValueError("Grid longitude differs from station mapping")
            yi = {int(y): i for i, y in enumerate(ds["year"][:])}
            event = list(ds["event"][:]).index("any")
            annual = np.stack([ds["event_days"][yi[y], event][:][safe_y, safe_x] for y in YEARS])
            annual[:, ~matched] = np.nan
            for j in range(len(YEARS)):
                valid = np.isfinite(annual[j]) & (cap > 0)
                numerators[j] += np.bincount(country[valid], weights=cap[valid] * annual[j, valid], minlength=n)
                denominators[j] += np.bincount(country[valid], weights=cap[valid], minlength=n)
                valid_stations[j] += np.bincount(country[valid], minlength=n)
            # One matched and one unmatched point per model/SSP/technology when available.
            for flag in (True, False):
                if any(c["matched"] == flag for c in checks):
                    continue
                candidates = np.flatnonzero((matched == flag) & (cap > 0))
                if len(candidates):
                    k = int(candidates[0])
                    checks.append({"patch": patch, "station_id": ids[k],
                                   **sample_raw_check(outputs, k, annual[:, k], flag)})
    absent = set(capacity[capacity > 0].index) - seen
    if absent:
        raise ValueError(f"{len(absent)} capacity stations missing from mapping inventory")
    rows = []
    for j, year in enumerate(YEARS):
        for k, label in enumerate(labels):
            valid_cap = denominators[j, k]
            rows.append({**label, "model": model, "scenario": ssp, "tech": tech, "year": year,
                         "capacity_gw": totals[k], "station_count": stations[k],
                         "valid_capacity_gw": valid_cap, "valid_station_count": valid_stations[j,k],
                         "capacity_days_gw": numerators[j,k],
                         "station_days": numerators[j,k] / valid_cap if valid_cap > 0 else np.nan,
                         "capacity_coverage_pct": 100 * valid_cap / totals[k] if totals[k] > 0 else np.nan})
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp.csv")
    pd.DataFrame(rows).to_csv(temp, index=False)
    temp.replace(target)
    write_json(receipt, {"fingerprint": fingerprint, "csv_sha256": sha(target), "raw_station_checks": checks,
                         "capacity_snapshot": 2050, "source": "annual grid cache at published station mapping indices"})
    return str(target)


def add_combined_station(data):
    keys = ["country", "country_iso3", "model", "scenario", "year"]
    summed = data.groupby(keys, as_index=False)[["capacity_gw", "valid_capacity_gw", "capacity_days_gw",
                                                 "station_count", "valid_station_count"]].sum(min_count=1)
    summed["station_days"] = summed.capacity_days_gw / summed.valid_capacity_gw.where(summed.valid_capacity_gw > 0)
    summed["capacity_coverage_pct"] = 100 * summed.valid_capacity_gw / summed.capacity_gw.where(summed.capacity_gw > 0)
    summed["tech"] = "combined"
    return pd.concat([data, summed], ignore_index=True)


def require_mean(values, expected):
    return float(values.mean()) if len(values) == expected and values.notna().all() else np.nan


def map_table(grid, station, models):
    grid = grid.copy()
    keys = ["country", "country_iso3", "model", "scenario", "year"]
    combined = grid.groupby(keys, as_index=False).agg(
        grid_days=("grid_days", lambda s: s.sum() if len(s)==2 and s.notna().all() else np.nan),
        grid_coverage_pct=("grid_coverage_pct", "min"))
    combined["tech"] = "combined"
    grid = pd.concat([grid, combined], ignore_index=True)
    keys = ["country", "country_iso3", "model", "scenario", "tech"]
    pieces = []
    for start in (2030, 2050):
        part = grid[grid.year.between(start, start+9)].groupby(keys, as_index=False).agg(
            **{f"grid_{start}_days": ("grid_days", lambda s: require_mean(s, 10)),
               f"grid_{start}_coverage_pct": ("grid_coverage_pct", "mean")})
        pieces.append(part)
    result = pieces[0].merge(pieces[1], on=keys, how="outer", validate="one_to_one")
    stat = add_combined_station(station).groupby(keys, as_index=False).agg(
        station_2050_days=("station_days", lambda s: require_mean(s, 10)),
        capacity_gw=("capacity_gw", lambda s: require_mean(s, 10)),
        valid_capacity_gw=("valid_capacity_gw", "mean"),
        capacity_coverage_pct=("capacity_coverage_pct", "mean"),
        station_count=("station_count", "mean"))
    result = result.merge(stat, on=keys, how="outer", validate="one_to_one")
    result["grid_change_days"] = result.grid_2050_days - result.grid_2030_days
    keys.remove("model")
    numeric = [c for c in result.columns if c not in (*keys, "model")]
    ensemble = result.groupby(keys, as_index=False)[numeric].agg(lambda s: require_mean(s, len(models)))
    ensemble["model"] = "ensemble_mean"
    return pd.concat([result, ensemble], ignore_index=True)


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--station-root", type=Path, default=STATIONS)
    parser.add_argument("--workers", type=int, default=min(16, int(os.environ.get("SLURM_CPUS_PER_TASK", "1"))))
    args = parser.parse_args()
    if args.workers < 1 or args.workers > int(os.environ.get("SLURM_CPUS_PER_TASK", str(args.workers))):
        parser.error("Invalid worker count")
    output = args.output_dir.resolve()
    index_path = args.station_root / "runtime/authoritative_index.json"
    index = json.loads(index_path.read_text())
    grid_path = RQ / "global/grid/outputs/cache_manifest.json"
    manifest = json.loads(grid_path.read_text())
    if index["release"]["index_sha256"] != manifest["input_index_sha256"]:
        raise ValueError("Grid and station source index identities differ")
    models, ssps = manifest["scope"]["models"], manifest["scope"]["ssps"]
    if set(models) != set(MODELS) or set(ssps) != set(SSPS):
        raise ValueError("Four models and three SSPs are required")
    if not set(BASELINE + YEARS) <= set(manifest["scope"]["years"]):
        raise ValueError("Required decades are not cached")
    grid_records = {(r["model"], r["scenario"], r["tech"], r["patch"]): r for r in manifest["records"]}
    expected = {(m,s,p,t) for m in models for s in ssps for p in manifest["scope"]["patches"] for t in TECHS}
    if set(tuple(k.split("/")) for k in index["combinations"]) != expected:
        raise ValueError("Incomplete station index")
    boundary_sha = hashlib.sha256(b"".join(SHAPEFILE.with_suffix(s).read_bytes() for s in (".shp",".shx",".dbf"))).hexdigest()
    grid_config = json.loads((RQ/"country/grid/outputs/run_config.json").read_text())
    if grid_config["boundary_sha256"] != boundary_sha or grid_config["grid_manifest_sha256"] != sha(grid_path):
        raise ValueError("Country grid tables do not match cached grid or boundaries")
    identity = {"station_index": sha(index_path), "grid_manifest": sha(grid_path), "boundary": boundary_sha}
    tasks = []
    for model in models:
        for ssp in ssps:
            capacity_files = [p for p in index["catalogs"][ssp]["files"] if p.endswith("capacity_rows.csv.gz")]
            if len(capacity_files) != 1:
                raise ValueError("Missing capacity rows")
            for tech in TECHS:
                records = [(p, index["combinations"][f"{model}/{ssp}/{p}/{tech}"]) for p in manifest["scope"]["patches"]]
                records_grid = {p:grid_records[model,ssp,tech,p] for p in manifest["scope"]["patches"]}
                tasks.append((model, ssp, tech, records, records_grid, capacity_files[0], SHAPEFILE, output, identity))
    paths = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=mp.get_context("spawn")) as pool:
        for path in pool.map(station_group, tasks):
            paths.append(path)
            LOGGER.info("Station country cache %d/%d: %s", len(paths), len(tasks), path)
    station = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    grids = []
    for model in models:
        path = RQ / f"country/grid/outputs/{model}/csv/country_annual_exposure.csv"
        frame = pd.read_csv(path)
        frame = frame[(frame.event == "any") & frame.year.isin(BASELINE+YEARS)]
        if frame.duplicated(["country","model","scenario","tech","year"]).any():
            raise ValueError("Duplicate annual country grid rows")
        grids.append(frame.rename(columns={"exposure_days":"grid_days", "coverage_pct":"grid_coverage_pct"}))
    table = map_table(pd.concat(grids, ignore_index=True), station, models)
    (output/"csv").mkdir(parents=True, exist_ok=True)
    station.to_csv(output/"csv/station_country_annual_2050s.csv", index=False)
    table.to_csv(output/"csv/country_map_metrics.csv", index=False)
    write_json(output/"run_config.json", {**identity, "models": models, "ssps": ssps,
        "grid_periods": {"2030s":BASELINE,"2050s":YEARS}, "capacity_snapshot":2050,
        "station_period":YEARS, "workers":args.workers, "event":"any",
        "combined_grid":"wind + solar", "combined_station":"annual valid-capacity-weighted wind + solar",
        "decadal_mean":"equal annual mean within each model, then equal mean across all four models",
        "circle_area":"2050 installed capacity including stations with missing exposure",
        "boundary":str(SHAPEFILE), "code_sha256":sha(__file__), "group_caches":paths})
    LOGGER.info("Saved country map metrics: %s", output/"csv/country_map_metrics.csv")


if __name__ == "__main__":
    main()
