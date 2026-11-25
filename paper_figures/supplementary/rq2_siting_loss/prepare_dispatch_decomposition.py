"""Attribute the dispatch-2025 unit-loss change from the 2030s to the 2050s."""
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
import os

import numpy as np
import pandas as pd

from paper_figures.config import MODELS, ROOT, SSPS, TECHS
from paper_figures.supplementary.rq2_siting_loss.prepare_dispatch_cohorts import DISPATCH, release, verified

DATA = ROOT / "tmp/RQ1_20261123_candidates/source_data"
NAME = "rq2_dispatch2025_time_decomposition"
WINDOWS = (2030, 2050)
YEARS = np.arange(2030, 2060)
TERMS = ("layout", "exposure", "intensity", "change")
KEYS = ("tech", "climate_ssp", "model")
RAW_FIELDS = ("net_loss_per_mw", "loss_event_hours", "event_normal_per_mw", "event_hours")


def reduce_model(archive, entries, published):
    with np.load(verified(archive), allow_pickle=False) as source:
        np.testing.assert_array_equal(source["years"], YEARS)
        capacity = source["capacity_mw"]
        support = source["common_support"]
        mapped = source["mapped"]
        grid = pd.Index(source["grid_id"])
    day_weights = capacity[:, support]
    np.testing.assert_allclose(day_weights.sum(axis=1), published.capacity_mw, rtol=1e-11)
    np.testing.assert_allclose(capacity.sum(axis=1), published.catalogue_capacity_mw, rtol=1e-11)
    seen = np.zeros(len(grid), dtype=bool)
    diagonal = np.zeros((30, 3))
    # The first two axes are climate window and capacity snapshot, respectively.
    crossed = np.zeros((2, 2, 3))
    for entry in entries:
        receipt = json.loads(verified(entry["receipt"]).read_text())
        assert receipt["status"] == "COMPLETED"
        native, = [item for item in receipt["outputs"] if item["product"] == "loss"]
        assert all(entry[k] == native[k] for k in ("path", "sha256", "size_bytes", "station_count"))
        raw, = [item for item in receipt["outputs"] if item["product"] == "annual_union"]
        assert raw["station_count"] == entry["station_count"] and raw["years"] == entry["years"]
        with np.load(verified(raw), allow_pickle=False) as source:
            np.testing.assert_array_equal(source["years"], YEARS)
            positions = grid.get_indexer(source["grid_id"])
            assert (positions >= 0).all() and not seen[positions].any()
            assert len(np.unique(positions)) == len(positions) == entry["station_count"]
            seen[positions] = True
            np.testing.assert_allclose(source["capacity_mw"], capacity[:, positions], rtol=1e-12, atol=1e-7)
            keep = support[positions]
            weights = capacity[:, positions[keep]]
            values = np.stack([source[field][:, keep] for field in RAW_FIELDS], axis=2)
        assert np.isfinite(values).all()
        assert (values[:, :, 1] >= 0).all() and (values[:, :, 1] <= values[:, :, 3]).all()
        diagonal += np.einsum("ys,ysf->yf", weights, values[:, :, [0, 2, 3]])
        snapshots = weights[[0, 20]]
        for i, start in enumerate((0, 20)):
            crossed[i] += snapshots @ values[start:start+10, :, :3].mean(axis=0)
    np.testing.assert_array_equal(seen, mapped)
    expected = published[["net_loss_mwh", "event_normal_mwh", "exposure_mw_days"]].to_numpy()
    diagonal[:, 2] /= 24
    np.testing.assert_allclose(diagonal, expected, rtol=1e-10, atol=1e-5)
    snapshot_caps = day_weights[[0, 20]].sum(axis=1)
    snapshot_full = capacity[[0, 20]].sum(axis=1)
    rows = []
    for i, j in product(range(2), repeat=2):
        net, event_hours, normal = crossed[i, j]
        cap = snapshot_caps[j]
        assert min(cap, event_hours, normal) > 0
        rows.append({
            **{k: archive[k] for k in KEYS},
            "climate_window": WINDOWS[i], "capacity_snapshot": WINDOWS[j],
            "catalogue_capacity_mw": snapshot_full[j], "supported_capacity_mw": cap,
            "capacity_coverage": cap / snapshot_full[j],
            "net_loss_mwh": net, "capacity_event_hours": event_hours, "normal_event_mwh": normal,
            "unit_loss": net / cap, "exposure_hours": event_hours / cap,
            "loss_per_exposed_mw_hour": net / event_hours,
        })
        if i == j:
            np.testing.assert_allclose(net / cap, published.unit_loss_mwh_per_mw.iloc[i*20:i*20+10].mean(),
                                       rtol=1e-10, atol=1e-10)
    print(f"Validated {tuple(archive[k] for k in KEYS)} ({len(entries)} shards, 30 years)", flush=True)
    return rows


def decompose(cells):
    records = []
    for key, group in cells.groupby(list(KEYS)):
        cells_by_state = group.set_index(["climate_window", "capacity_snapshot"], verify_integrity=True)
        early, late = WINDOWS
        base = cells_by_state.loc[(early, early), "unit_loss"]
        target = cells_by_state.loc[(late, late), "unit_loss"]
        layout = cells_by_state.unit_loss.unstack("capacity_snapshot").diff(axis=1)[late].mean()
        fixed_layout = []
        for snapshot in WINDOWS:
            first, last = (cells_by_state.loc[(window, snapshot)] for window in WINDOWS)
            exposure = (last.exposure_hours - first.exposure_hours) * (
                first.loss_per_exposed_mw_hour + last.loss_per_exposed_mw_hour) / 2
            intensity = (last.loss_per_exposed_mw_hour - first.loss_per_exposed_mw_hour) * (
                first.exposure_hours + last.exposure_hours) / 2
            np.testing.assert_allclose(exposure + intensity, last.unit_loss - first.unit_loss, atol=1e-10)
            fixed_layout.append((exposure, intensity))
        exposure, intensity = np.mean(fixed_layout, axis=0)
        change = target - base
        closure = layout + exposure + intensity - change
        assert abs(closure) < 1e-10
        records.append(dict(zip(KEYS, key, strict=True), loss_2030s=base, loss_2050s=target,
                            layout=layout, exposure=exposure, intensity=intensity,
                            climate=exposure + intensity, change=change, closure=closure))
    return pd.DataFrame(records)


def main():
    index, checksum = release(DISPATCH)
    published_file = index["summaries"]["global_annual_models.csv"]
    published = pd.read_csv(verified(published_file))
    published = published.loc[published.climate_ssp.eq(published.station_ssp) & published.tech.isin(TECHS)]
    by_key = {key: group.set_index("year", verify_integrity=True).loc[YEARS]
              for key, group in published.groupby(list(KEYS))}
    archives = [entry for entry in index["annual_archives"] if entry["station_ssp"] == entry["climate_ssp"]]
    shards = [entry for entry in index["loss_files"] if entry["station_ssp"] == entry["climate_ssp"]]
    expected = set(product(TECHS, SSPS, MODELS))
    assert len(archives) == len(expected) and set(by_key) == expected
    assert {tuple(a[k] for k in KEYS) for a in archives} == expected
    jobs = []
    for archive in archives:
        key = tuple(archive[k] for k in KEYS)
        entries = [e for e in shards if tuple(e[k] for k in KEYS) == key]
        assert entries and len({entry["patch"] for entry in entries}) == len(entries)
        jobs.append((archive, entries, by_key[key]))
    cpus = int(os.environ.get("SLURM_CPUS_PER_TASK", 1))
    with ProcessPoolExecutor(max_workers=cpus) as pool:
        cells = pd.DataFrame([row for result in pool.map(reduce_model, *zip(*jobs, strict=True)) for row in result])
    models = decompose(cells)
    columns = [*TERMS, "climate", "loss_2030s", "loss_2050s"]
    display = models.groupby(list(KEYS[:2]))[columns].mean().reset_index()
    np.testing.assert_allclose(display[list(TERMS[:3])].sum(axis=1), display.change, atol=1e-10)
    DATA.mkdir(parents=True, exist_ok=True)
    for name, table in (("cells", cells), ("models", models), ("display", display)):
        table.to_csv(DATA / f"{NAME}_{name}.csv", index=False)
    validation = {
        "dispatch_index_sha256": checksum,
        "published_annual_source": published_file,
        "shards_verified": len(shards),
        "checked_published_model_years": len(published),
        "climate_windows": ["2030–2039", "2050–2059"],
        "capacity_snapshots": WINDOWS,
        "minimum_supported_capacity_fraction": float(cells.capacity_coverage.min()),
        "maximum_model_closure_error": float(models.closure.abs().max()),
        "intensity": "Signed net loss divided by capacity-weighted loss-valid union exposure hours.",
        "method": "Symmetric two-state climate and layout changes; within each fixed layout split climate into exposure and intensity by averaging both replacement orders.",
    }
    (DATA / f"{NAME}_validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    print(display.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
