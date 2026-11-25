"""Evaluate each dispatch-2025 capacity increment using losses in its destination decade."""
import numpy as np

from paper_figures.config import SNAPSHOTS
from paper_figures.supplementary.rq2_siting_loss.prepare_dispatch_cohorts import (
    load_inputs, summarize, write_outputs,
)

PREFIX = "dispatch2025_decade_added"


def adjacent_increments(future):
    increments = {}
    for key, (grid, allocation, rates, mask) in future.items():
        cumulative = allocation[:, :, 1]
        added = np.diff(cumulative, axis=0, prepend=np.zeros_like(cumulative[:1]))
        np.testing.assert_array_less(-1e-8, added, err_msg=f"Capacity decreased in {key}")
        added = np.maximum(added, 0)
        np.testing.assert_allclose(added.cumsum(axis=0), cumulative, rtol=1e-9, atol=1e-8)
        increments[key] = (grid, np.stack([allocation[:, :, 0], added], axis=-1), rates, mask)
    return increments


def main():
    future, history, baseline, checks = load_inputs()
    increments = adjacent_increments(future)
    checks["increment_windows"] = dict(zip(SNAPSHOTS, ([2025, 2030], [2030, 2040], [2040, 2050])))
    checks["increment_checks"] = [
        "Capacity differences matched by technology and grid ID within each layout",
        "Cumulative adjacent increments reproduce additions since 2025 at every grid",
        "Increment evaluated with annual unit-capacity losses in the destination decade",
    ]
    write_outputs(PREFIX, summarize(increments, history, baseline), checks)


if __name__ == "__main__":
    main()
