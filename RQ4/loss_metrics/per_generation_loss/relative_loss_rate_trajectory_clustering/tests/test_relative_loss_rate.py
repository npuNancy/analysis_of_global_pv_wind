from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from cluster_relative_loss_rate import choose_partition  # noqa: E402
from common import COMPARE_SSPS, FEATURE_NAMES  # noqa: E402


class RelativeLossRateTests(unittest.TestCase):
    def test_feature_order_contains_three_scenarios(self):
        self.assertEqual(len(FEATURE_NAMES), 9)
        self.assertEqual(FEATURE_NAMES[:3], ["ssp126_2030", "ssp126_2040", "ssp126_2050"])
        self.assertEqual(COMPARE_SSPS, ("ssp126", "ssp245", "ssp585"))

    def test_ward_partition_and_small_k_tolerance(self):
        features = np.array([
            [2.0] * 9, [2.1] * 9, [1.9] * 9,
            [-2.0] * 9, [-2.1] * 9, [-1.9] * 9,
        ])
        labels, _, diagnostics = choose_partition(
            features, k_min=2, k_max=3, min_cluster_size=2
        )
        self.assertEqual(len(np.unique(labels)), 2)
        self.assertEqual(int(diagnostics.loc[diagnostics.selected, "requested_k"].iloc[0]), 2)


if __name__ == "__main__":
    unittest.main()
