"""Numerical regression checks for grid extreme exposure reduction."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import netCDF4
import numpy as np
import pandas as pd
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "country/grid"))
from grid_common import (EVENTS, aggregate_combination, aggregate_rows, ensemble_table,
                         event_block, grid_geometry, year_hours)
from country_grid_extremes import rasterize_countries


class GridExposureTests(unittest.TestCase):
    def test_union_and_missing_flags(self):
        a = np.array([[[1, -127, 0]], [[0, 1, 1]]], dtype="i1")
        b = np.array([[[1, 0, 0]], [[1, -127, 0]]], dtype="i1")
        valid, flags = event_block([a, b], [-127, -127], np.ones((1, 3), dtype=bool))
        self.assertEqual(int((valid & flags[0]).sum()), 3)
        self.assertEqual(int(valid.sum()), 4)
        self.assertFalse(valid[:, 0, 1].any())
        self.assertLess(int((valid & flags[0]).sum()), sum(int((valid & f).sum()) for f in flags[1:]))

    def test_nonbinary_signal_rejected(self):
        with self.assertRaises(ValueError):
            event_block([np.array([[[2]]])], [-127], np.ones((1, 1), dtype=bool))

    def test_patch_boundary_and_area(self):
        lat, lon = np.array([-1., 0., 1.]), np.array([0., 1.])
        south, area = grid_geometry(lat, lon, (0, 2, -1, 0))
        north, _ = grid_geometry(lat, lon, (0, 2, 0, 2))
        self.assertFalse((south & north).any())
        self.assertEqual(int((south | north).sum()), 6)
        self.assertTrue((area > 0).all())
        self.assertGreater(area[1, 0], area[0, 0])

    def test_calendars(self):
        self.assertEqual(year_hours(2016, "365_day"), 365 * 24)
        self.assertEqual(year_hours(2016, "proleptic_gregorian"), 366 * 24)

    def test_weighted_patch_aggregation(self):
        records = [{"key": "a", "weighted_days_km2": numerator, "valid_area_km2": area,
                    "reference_area_km2": area, "valid_cells": 1, "domain_cells": 1,
                    "time_area_km2": area} for numerator, area in [(10, 1), (180, 9)]]
        result = aggregate_rows(records, ["key"])
        self.assertAlmostEqual(float(result.exposure_days.iloc[0]), 19)
        self.assertAlmostEqual(float(result.coverage_pct.iloc[0]), 100)

    def test_ensemble_requires_all_models(self):
        row = {"model": "a", "scenario": "ssp126", "exposure_days": 10., "coverage_pct": 100.,
               "time_coverage_pct": 100., "valid_area_km2": 1., "reference_area_km2": 1.,
               "valid_cells": 1, "domain_cells": 1}
        result = ensemble_table(pd.DataFrame([row]), ["scenario"], ["a", "b"])
        self.assertTrue(np.isnan(result.exposure_days.iloc[0]))
        self.assertEqual(result.n_models.iloc[0], 1)

    def test_country_cells_not_nearest_country(self):
        domain = np.ones((2, 3), dtype=bool)
        domain[1, 0] = False
        ids = rasterize_countries(np.array([0., 1.]), np.array([0., 1., 2.]), domain,
                                  [box(-.5, -.5, .5, 1.5), box(.5, -.5, 1.5, 1.5)])
        np.testing.assert_array_equal(ids, [[0, 1, -1], [-1, 1, -1]])

    def test_netcdf_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "signals_2015-2019.nc"
            with netCDF4.Dataset(path, "w") as ds:
                for name, length in (("time", 8), ("lat", 2), ("lon", 2)):
                    ds.createDimension(name, length)
                ds.createVariable("lat", "f8", ("lat",))[:] = [0, 1]
                ds.createVariable("lon", "f8", ("lon",))[:] = [0, 1]
                ds.createVariable("domain_mask", "i1", ("lat", "lon"))[:] = 1
                time = ds.createVariable("time", "f8", ("time",))
                time.units = "hours since 2015-01-01 00:00:00"
                time.calendar = "365_day"
                time[:] = np.arange(8) * 3
                for event in EVENTS["wind"]:
                    variable = ds.createVariable("signal_" + event, "i1", ("time", "lat", "lon"), fill_value=-127)
                    values = np.zeros((8, 2, 2), dtype="i1")
                    values[:, 0, 0] = -127
                    if event in ("high_temp", "high_wind"):
                        values[:, 1, 1] = 1
                    variable[:] = values
            row = {"model": "CANESM5", "scenario": "ssp126", "tech": "wind", "patch": "R01C01",
                   "unit_id": "fixture", "bbox": [0, 2, 0, 2], "source_run_id": "fixture",
                   "artifacts": [{"stage": "signals", "years": "2015-2019", "unified_output": str(path)}]}
            task = (row, [2015], folder, .001, 3)
            result = aggregate_combination(task)
            with netCDF4.Dataset(result["path"]) as ds:
                self.assertAlmostEqual(float(ds["event_days"][0, 0, 1, 1]), 1.0)
                self.assertAlmostEqual(float(ds["event_days"][0, 1, 1, 1]), 1.0)
                self.assertTrue(np.ma.is_masked(ds["event_days"][0, 0, 0, 0]))
                self.assertEqual(float(ds["valid_hours"][0, 1, 1]), 24)
            mtime = Path(result["path"]).stat().st_mtime_ns
            self.assertEqual(aggregate_combination(task)["fingerprint"], result["fingerprint"])
            self.assertEqual(Path(result["path"]).stat().st_mtime_ns, mtime)


if __name__ == "__main__":
    unittest.main(verbosity=2)
