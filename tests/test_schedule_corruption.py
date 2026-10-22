"""
tests/test_schedule_corruption.py - Verifies multi-schedule rebalance offsets, lengths, and indices integrity.
Guards against double-assignment bugs and array sizing corruptions in TensorCubeContainer.
"""

import unittest
import sys
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.cube_builder import TensorCubeContainer


class TestScheduleCorruption(unittest.TestCase):
    def test_multi_schedule_offsets_lengths_correctness(self):
        """
        Distinct rebalance arrays per schedule:
        schedule_lengths and schedule_offsets must strictly match the concatenation order
        without duplicate assignment or array corruption.
        """
        num_dates = 300
        dates = [f"2020-01-{i:03d}" for i in range(num_dates)]
        symbols = ["SYM0"]

        sched_map = {
            "weekly": np.array([0, 5, 10], dtype=np.int32),
            "monthly": np.array([0, 20], dtype=np.int32),
            "quarterly": np.array([0, 30, 60], dtype=np.int32),
            "half_yearly": np.array([0, 120], dtype=np.int32),
            "yearly": np.array([0, 250], dtype=np.int32),
        }

        cube = TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
        )

        # 1. Verify lengths matching expected
        self.assertEqual(cube.schedule_lengths[0], 3, "Weekly length must be 3")
        self.assertEqual(cube.schedule_lengths[1], 2, "Monthly length must be 2")
        self.assertEqual(cube.schedule_lengths[2], 3, "Quarterly length must be 3")
        self.assertEqual(cube.schedule_lengths[3], 2, "Half-Yearly length must be 2")
        self.assertEqual(cube.schedule_lengths[4], 2, "Yearly length must be 2")
        self.assertEqual(cube.schedule_lengths[5], 0, "Unused slot 5 must be 0")
        self.assertEqual(cube.schedule_lengths[6], 0, "Unused slot 6 must be 0")

        # 2. Verify offsets are non-overlapping and match concatenation order
        expected_offsets = [0, 3, 5, 8, 10, 12, 12]
        np.testing.assert_array_equal(cube.schedule_offsets, expected_offsets)

        # 3. Verify slice indexing matches original arrays
        for s_idx, s_name in enumerate(["weekly", "monthly", "quarterly", "half_yearly", "yearly"]):
            offset = int(cube.schedule_offsets[s_idx])
            length = int(cube.schedule_lengths[s_idx])
            sliced = cube.rebalance_indices[offset : offset + length]
            np.testing.assert_array_equal(
                sliced,
                sched_map[s_name],
                f"Rebalance slice for {s_name} does not match original schedule!"
            )


if __name__ == "__main__":
    unittest.main()
