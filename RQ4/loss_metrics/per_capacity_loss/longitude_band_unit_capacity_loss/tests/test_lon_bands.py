from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from common import (  # noqa: E402
    BAND_WIDTH,
    LON_BANDS,
    aggregate_band_rates,
    assign_lon_band,
    band_event_losses,
)


class AssignLonBandTests(unittest.TestCase):
    def test_boundaries_and_wrapping(self):
        self.assertEqual(assign_lon_band(0.0), "000-060E")
        self.assertEqual(assign_lon_band(59.9), "000-060E")
        self.assertEqual(assign_lon_band(60.0), "060-120E")
        self.assertEqual(assign_lon_band(119.9), "060-120E")
        self.assertEqual(assign_lon_band(180.0), "180-120W")
        self.assertEqual(assign_lon_band(-121.0), "180-120W")
        self.assertEqual(assign_lon_band(-120.0), "120-060W")
        self.assertEqual(assign_lon_band(-60.1), "120-060W")
        self.assertEqual(assign_lon_band(-60.0), "060-000W")
        self.assertEqual(assign_lon_band(-0.1), "060-000W")

    def test_band_layout(self):
        self.assertEqual(len(LON_BANDS), 6)
        self.assertEqual(BAND_WIDTH, 60.0)


class AggregateBandRatesTests(unittest.TestCase):
    def _frame(self):
        return pd.DataFrame({
            "lon_band": ["000-060E", "000-060E", "060-120E"],
            "scenario": ["ssp126", "ssp126", "ssp126"],
            "tech": ["wind", "wind", "wind"],
            "snapshot_year": [2030, 2030, 2030],
            "station_id": ["a", "b", "c"],
            "capacity_mw": [10.0, 20.0, 0.0],
            "event": ["all", "all", "all"],
            "net_generation_loss_mwh": [1.0, 3.0, 2.0],
            "normal_all_generation_mwh": [10.0, 30.0, 0.0],
        })

    def test_sum_then_divide(self):
        metrics = aggregate_band_rates(self._frame())
        west = metrics[metrics["lon_band"].eq("000-060E")].iloc[0]
        # 十年损失先求和，再除以总装机和十年长度。
        self.assertEqual(west["n_stations"], 2)
        self.assertAlmostEqual(west["unit_capacity_loss"], 4.0 / 30.0 / 10.0)

    def test_nonpositive_denominator_is_nan(self):
        metrics = aggregate_band_rates(self._frame())
        east = metrics[metrics["lon_band"].eq("060-120E")].iloc[0]
        self.assertTrue(np.isnan(east["unit_capacity_loss"]))


class BandEventLossesTests(unittest.TestCase):
    def test_loss_weighted_share_and_residual(self):
        frame = pd.DataFrame({
            "lon_band": ["060-120E"] * 3,
            "scenario": ["ssp245"] * 3,
            "tech": ["solar"] * 3,
            "snapshot_year": [2050] * 3,
            "station_id": ["a", "a", "b"],
            "event": ["low_resource", "high_temp", "high_humidity"],
            "net_generation_loss_mwh": [8.0, 1.0, 1.0],
            "normal_all_generation_mwh": [100.0, 100.0, 100.0],
        })
        summary = band_event_losses(frame)
        self.assertAlmostEqual(
            summary[summary["event"].eq("low_resource")]["loss_weighted_share"].iloc[0], 0.8
        )
        residual = summary[summary["event"].eq("high_temp")]["loss_weighted_residual_share"].iloc[0]
        self.assertAlmostEqual(residual, 0.5)
        self.assertTrue(
            summary[summary["event"].eq("low_resource")]["loss_weighted_residual_share"].isna().all()
        )


if __name__ == "__main__":
    unittest.main()
