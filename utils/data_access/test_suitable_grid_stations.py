from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
import xarray as xr

try:
    from . import build_suitable_grid_stations as builder
except ImportError:
    import build_suitable_grid_stations as builder


class SuitableGridTests(unittest.TestCase):
    def test_pixel_boundaries_and_longitude_wrap(self):
        row, col, inside = builder.pixel_indices(
            [1, 0.9, 0.8, 1.01], [359.8, -0.1, -0.1, -0.1],
            from_origin(-0.2, 1, 0.1, 0.1), (2, 2),
        )
        np.testing.assert_array_equal(row, [0, 1, 2, -1])
        np.testing.assert_array_equal(col, [0, 1, 1, 1])
        np.testing.assert_array_equal(inside, [True, True, False, False])

    def fixture(self, root):
        for tech, values in (("solar", [[10, 0], [np.nan, 5]]), ("wind", [[100.45, 0], [2, 0]])):
            path = root / f"{tech}_onshore.tif"
            with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1,
                               dtype="float64", crs="EPSG:4326", nodata=np.nan,
                               transform=from_origin(-0.2, 1, 0.1, 0.1)) as ds:
                ds.write(np.asarray(values, dtype=float), 1)
        cf = root / "cf.nc"
        xr.Dataset(coords={"lat": [1.0, 0.9], "lon": [359.8, 359.9]}).to_netcdf(cf)
        (root / "runtime").mkdir()
        (root / "runtime/authoritative_index.json").write_text("{}")
        records = [dict(tech=t, patch=p, model="M", climate_scenario="ssp126", path=str(cf))
                   for t in ("wind", "solar") for p in ("P1", "P2")]
        args = argparse.Namespace(solar_suitability=root / "solar_onshore.tif",
                                  wind_suitability=root / "wind_onshore.tif",
                                  cf_root=root, output_dir=root / "output")
        return args, records

    def test_csv_mapping_dedup_and_two_technologies(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, records = self.fixture(Path(tmp))
            with patch.object(builder.read_cf_grid, "find_records", return_value=records):
                report = builder.build(args)
            with (args.output_dir / "stations_suitable_1mw.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 4)
            self.assertEqual({r["year"] for r in rows}, {"2015"})
            self.assertEqual({r["capacity_gw"] for r in rows}, {"0.001"})
            self.assertEqual(sum(r["type"] == "wind" for r in rows), 2)
            self.assertEqual(report["technologies"]["solar"]["matched_positive_pixels"], 2)
            self.assertEqual(report["inputs"]["wind"]["pixels_above_100_percent"], 1)
            self.assertEqual(report["patches"][1]["new_unique"], 0)
            self.assertTrue((args.output_dir / "grid_mapping.csv.gz").is_file())
            self.assertEqual(json.loads((args.output_dir / "summary.json").read_text())["status"], "COMPLETED")

    def test_coordinate_mismatch_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, records = self.fixture(Path(tmp))
            mismatch = Path(tmp) / "mismatch.nc"
            xr.Dataset(coords={"lat": [0.95, 0.85], "lon": [359.8, 359.9]}).to_netcdf(mismatch)
            records.append(dict(records[0], model="M2", path=str(mismatch)))
            with patch.object(builder.read_cf_grid, "find_records", return_value=records):
                with self.assertRaisesRegex(ValueError, "coordinates differ"):
                    builder.build(args)
            self.assertFalse(args.output_dir.exists())

    def test_combined_wind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, _ = self.fixture(Path(tmp))
            combined = Path(tmp) / "Global_Wind_Net_Area_Add_Egrid.tif"
            args.wind_suitability.rename(combined)
            with self.assertRaisesRegex(ValueError, "onshore component"):
                builder.load_suitability(combined, "wind")


if __name__ == "__main__":
    unittest.main()
