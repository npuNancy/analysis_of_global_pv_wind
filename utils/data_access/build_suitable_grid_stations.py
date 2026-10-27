"""Map positive suitability pixels to published BCSD coordinates (1 MW per grid)."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import rasterio
import xarray as xr

try:
    from . import read_cf_grid
except ImportError:
    import read_cf_grid

REPO = Path(__file__).resolve().parents[2]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_suitability(path, tech):
    with rasterio.open(path) as ds:
        if ds.crs != rasterio.crs.CRS.from_epsg(4326):
            raise ValueError(f"Expected EPSG:4326: {path}")
        t = ds.transform
        if not np.allclose([t.a, t.b, t.d, t.e], [0.1, 0, 0, -0.1], atol=1e-10):
            raise ValueError(f"Expected north-up 0.1 degree raster: {path}")
        tags = ds.tags()
        # The combined wind raster includes offshore pixels and is not an onshore input.
        if tech == "wind" and "onshore" not in (Path(path).name + " " + tags.get("description", "")).lower():
            raise ValueError("Wind input must be the explicitly labelled onshore component")
        values = ds.read(1, masked=True).astype("float64").filled(np.nan)
        finite = np.isfinite(values)
        if np.any(values[finite] < 0):
            raise ValueError(f"Negative suitability: {path}")
        return values, t, tags


def pixel_indices(lat, lon, transform, shape):
    """Containing pixel; west/north inclusive, east/south exclusive.

    Snap roundoff at pixel edges before floor; never shift the BCSD coordinates
    to raster centres. Longitude is normalized to [-180, 180).
    """
    lon = (np.asarray(lon, dtype="float64") + 180) % 360 - 180
    lat = np.asarray(lat, dtype="float64")
    r = (lat - transform.f) / transform.e
    c = (lon - transform.c) / transform.a
    r = np.where(np.abs(r - np.rint(r)) < 1e-6, np.rint(r), r)
    c = np.where(np.abs(c - np.rint(c)) < 1e-6, np.rint(c), c)
    row, col = np.floor(r).astype("int64"), np.floor(c).astype("int64")
    inside = (row >= 0) & (row < shape[0]) & (col >= 0) & (col < shape[1])
    return row, col, inside


def read_coordinates(path):
    with xr.open_dataset(path, decode_times=False) as ds:
        lat, lon = ds.lat.values.astype("float64"), ds.lon.values.astype("float64")
    for name, values in (("lat", lat), ("lon", lon)):
        if values.ndim != 1 or not np.all(np.isfinite(values)):
            raise ValueError(f"Invalid {name} coordinates: {path}")
        if len(np.unique(np.round(values, 6))) != len(values):
            raise ValueError(f"Duplicate {name} coordinates: {path}")
        if len(values) > 1 and not np.allclose(np.abs(np.diff(values)), 0.1, atol=2e-5):
            raise ValueError(f"Expected contiguous 0.1 degree {name}: {path}")
    if np.any(np.abs(lat) > 90):
        raise ValueError(f"Invalid latitude range: {path}")
    return lat, lon


def build(args):
    output = Path(args.output_dir)
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    rasters = {tech: load_suitability(path, tech) for tech, path in
               (("solar", args.solar_suitability), ("wind", args.wind_suitability))}
    records = read_cf_grid.find_records(root=args.cf_root, years=(2015, 2015))
    groups = {}
    for record in records:
        groups.setdefault((record["tech"], record["patch"]), []).append(record)
    if set(tech for tech, _ in groups) != {"solar", "wind"}:
        raise ValueError("Both solar and wind CF grids are required")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "year": 2015, "capacity_gw": 0.001,
        "mapping": "BCSD point in raster pixel; north/west inclusive, south/east exclusive; longitude [-180,180)",
        "selection": "finite suitability > 0; no capacity density or CF-value filtering",
        "coordinate_validation": "2015-containing CF block for every indexed model/scenario/patch/technology",
        "cf_index": str(Path(args.cf_root) / read_cf_grid.INDEX_PATH),
        "cf_index_sha256": sha256(Path(args.cf_root) / read_cf_grid.INDEX_PATH),
        "inputs": {}, "technologies": {}, "patches": [],
    }
    with tempfile.TemporaryDirectory(prefix=".suitable_grid_", dir=output.parent) as tmp:
        staging = Path(tmp)
        with (staging / "stations_suitable_1mw.csv").open("w", newline="") as out, gzip.open(
            staging / "grid_mapping.csv.gz", "wt", newline=""
        ) as audit:
            writer, mapping = csv.writer(out), csv.writer(audit)
            writer.writerow(["year", "type", "lon", "lat", "capacity_gw"])
            mapping.writerow(["type", "patch", "cf_lat_index", "cf_lon_index", "lon", "lat",
                              "raster_row", "raster_col", "suitability_percent"])
            for tech in ("solar", "wind"):
                values, transform, tags = rasters[tech]
                seen, matched_pixels = set(), np.zeros(values.shape, dtype=bool)
                source = Path(getattr(args, f"{tech}_suitability"))
                report["inputs"][tech] = {"path": str(source.resolve()), "sha256": sha256(source),
                                          "tags": tags, "shape": list(values.shape),
                                          "pixels_above_100_percent": int(np.sum(values > 100)),
                                          "maximum_percent": float(np.nanmax(values))}
                for _, patch in sorted(key for key in groups if key[0] == tech):
                    sources = sorted(groups[(tech, patch)], key=lambda r: (r["model"], r["climate_scenario"]))
                    lat, lon = read_coordinates(sources[0]["path"])
                    for record in sources[1:]:
                        other_lat, other_lon = read_coordinates(record["path"])
                        if not (np.array_equal(lat, other_lat) and np.array_equal(lon, other_lon)):
                            raise ValueError(f"CF coordinates differ across model/scenario: {record['path']}")
                    rr, cc = np.indices((lat.size, lon.size))
                    yy, xx = lat[rr.ravel()], lon[cc.ravel()]
                    rows, cols, inside = pixel_indices(yy, xx, transform, values.shape)
                    sampled = np.full(xx.size, np.nan)
                    sampled[inside] = values[rows[inside], cols[inside]]
                    selected = np.flatnonzero(np.isfinite(sampled) & (sampled > 0))
                    added = 0
                    for i in selected:
                        x, y = (float(xx[i]) + 180) % 360 - 180, float(yy[i])
                        key = (round(x, 6), round(y, 6))
                        mapping.writerow([tech, patch, int(rr.ravel()[i]), int(cc.ravel()[i]),
                                          repr(x), repr(y), int(rows[i]), int(cols[i]), sampled[i]])
                        matched_pixels[rows[i], cols[i]] = True
                        if key not in seen:
                            seen.add(key)
                            writer.writerow([2015, tech, repr(x), repr(y), "0.001"])
                            added += 1
                    report["patches"].append({"tech": tech, "patch": patch, "selected": len(selected),
                                               "new_unique": added, "cf_sources": [r["path"] for r in sources]})
                    print(f"{tech} {patch}: selected={len(selected)}, new_unique={added}", flush=True)
                positive = np.isfinite(values) & (values > 0)
                report["technologies"][tech] = {
                    "csv_rows": len(seen), "positive_raster_pixels": int(positive.sum()),
                    "matched_positive_pixels": int(matched_pixels.sum()),
                    "positive_pixels_without_published_cf_point": int((positive & ~matched_pixels).sum()),
                }
                if not seen:
                    raise ValueError(f"No suitable published BCSD points for {tech}")
        report["total_csv_rows"] = sum(t["csv_rows"] for t in report["technologies"].values())
        report["csv_sha256"] = sha256(staging / "stations_suitable_1mw.csv")
        report["status"] = "COMPLETED"
        (staging / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        staging.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solar-suitability", type=Path, default=REPO / "data/suitability/Global_Solar_Net_Area_Add_Egrid.tif")
    parser.add_argument("--wind-suitability", type=Path, default=REPO / "data/suitability/Global_Wind_Net_Area_onshore_component.tif")
    parser.add_argument("--cf-root", type=Path, default=Path(read_cf_grid.DEFAULT_ROOT))
    parser.add_argument("--output-dir", type=Path, default=REPO / "data/stations/suitable_grid_1mw")
    report = build(parser.parse_args())
    print(json.dumps(report["technologies"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
