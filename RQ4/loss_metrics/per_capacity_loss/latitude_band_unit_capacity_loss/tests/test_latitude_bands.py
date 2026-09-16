from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from common import (  # noqa: E402
    BAND_EDGES,
    LAT_BANDS,
    aggregate_band_rates,
    assign_lat_band,
    band_event_losses,
)


class AssignLatBandTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(assign_lat_band(29.99), "N-low")
        self.assertEqual(assign_lat_band(30.0), "N-mid")
        self.assertEqual(assign_lat_band(49.9), "N-mid")
        self.assertEqual(assign_lat_band(50.0), "N-high")
        self.assertEqual(assign_lat_band(-50.0), "S-high")
        self.assertEqual(assign_lat_band(-49.9), "S-mid")
        self.assertEqual(assign_lat_band(-29.9), "S-low")
        self.assertEqual(assign_lat_band(0.0), "N-low")

    def test_band_order_covers_all_six(self):
        self.assertEqual(len(LAT_BANDS), 6)
        self.assertEqual(BAND_EDGES, (30.0, 50.0))


class AggregateBandRatesTests(unittest.TestCase):
    def _frame(self):
        return pd.DataFrame({
            "lat_band": ["N-low", "N-low", "S-high"],
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
        n_low = metrics[metrics["lat_band"].eq("N-low")].iloc[0]
        # 十年损失先求和，再除以总装机和十年长度。
        self.assertEqual(n_low["n_stations"], 2)
        self.assertAlmostEqual(n_low["unit_capacity_loss"], 4.0 / 30.0 / 10.0)

    def test_nonpositive_denominator_is_nan(self):
        metrics = aggregate_band_rates(self._frame())
        s_high = metrics[metrics["lat_band"].eq("S-high")].iloc[0]
        self.assertTrue(np.isnan(s_high["unit_capacity_loss"]))


class BandEventLossesTests(unittest.TestCase):
    def test_loss_weighted_share_and_residual(self):
        frame = pd.DataFrame({
            "lat_band": ["N-mid"] * 3,
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
        # low_resource 不参与残差口径。
        self.assertTrue(
            summary[summary["event"].eq("low_resource")]["loss_weighted_residual_share"].isna().all()
        )

    def test_negative_loss_clipped_in_share_pool(self):
        frame = pd.DataFrame({
            "lat_band": ["N-mid"] * 2,
            "scenario": ["ssp245"] * 2,
            "tech": ["solar"] * 2,
            "snapshot_year": [2050] * 2,
            "station_id": ["a", "b"],
            "event": ["high_temp", "icing"],
            "net_generation_loss_mwh": [-5.0, 5.0],
            "normal_all_generation_mwh": [100.0, 100.0],
        })
        summary = band_event_losses(frame)
        icing = summary[summary["event"].eq("icing")].iloc[0]
        # 负损失截断为 0 后，icing 在正损失池中占比 100%。
        self.assertAlmostEqual(icing["loss_weighted_share"], 1.0)
        self.assertAlmostEqual(icing["positive_net_loss_mwh_decade"], 5.0)


if __name__ == "__main__":
    unittest.main()
