from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np


RQ4_DIR = Path(__file__).resolve().parents[1]
if str(RQ4_DIR) not in sys.path:
    sys.path.insert(0, str(RQ4_DIR))

from cluster_country_tradeoff import (  # noqa: E402
    choose_partition,
    describe_pattern,
    symmetric_relative_gap,
)


class CountryClusteringTests(unittest.TestCase):
    def test_symmetric_relative_gap_direction_and_bounds(self) -> None:
        result = symmetric_relative_gap(
            np.array([[3.0, 1.0, 0.0]]),
            np.array([[1.0, 3.0, 0.0]]),
        )
        self.assertGreater(result[0, 0], 0)
        self.assertLess(result[0, 1], 0)
        self.assertAlmostEqual(result[0, 2], 0.0)
        self.assertTrue(np.all(np.abs(result) <= 2.0))

    def test_choose_partition_recovers_two_groups(self) -> None:
        features = np.array(
            [
                [0.8, 0.7, 0.6],
                [0.7, 0.8, 0.7],
                [0.9, 0.7, 0.8],
                [-0.8, -0.7, -0.6],
                [-0.7, -0.8, -0.7],
                [-0.9, -0.7, -0.8],
            ]
        )
        labels, _, scores = choose_partition(
            features, k_min=2, k_max=3, min_cluster_size=2
        )
        self.assertEqual(len(np.unique(labels)), 2)
        self.assertTrue(scores.loc[scores["requested_k"].eq(2), "eligible"].iloc[0])

    def test_pattern_description(self) -> None:
        self.assertEqual(describe_pattern(np.array([0.4, 0.3, 0.2])), "SSP126持续较高")
        self.assertEqual(describe_pattern(np.array([-0.4, -0.2, 0.3])), "SSP585→SSP126交叉")


if __name__ == "__main__":
    unittest.main()
