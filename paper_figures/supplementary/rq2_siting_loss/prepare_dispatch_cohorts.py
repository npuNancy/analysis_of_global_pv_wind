"""Split published dispatch-2025 losses into retained and cumulative added capacity."""
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.common.io import digest
from paper_figures.config import MODELS, ROOT, SNAPSHOTS, SSPS, TECHS

DISPATCH = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585")
GEM = Path("/work/home/acxujo26gv/lcoe_gem2025_climate_storage")
DATA = ROOT / "tmp/RQ1_20261123_candidates/source_data/rq2_candidates"
PREFIX = "dispatch2025_stock_added"
STOCK = "baseline_capacity_mw"
ADDED = "new_capacity_since_2025_mw"


def release(root):
    source = root / "runtime/authoritative_index.json"
    marker = json.loads((root / "runtime/completion.json").read_text())
    index = json.loads(source.read_text())
    assert index["status"] == marker["status"] == "COMPLETED"
    assert digest(source) == marker["index_sha256"]
    return index, marker["index_sha256"]


def verified(entry):
    path = Path(entry["path"])
    assert digest(path) == entry["sha256"], path
    return path


def capacities(index):
    provenance = index["provenance"]["station_provenance.json"]
    files = json.loads(verified(provenance).read_text())
    tables, baseline = {}, {}
    for entry in files:
        scenario, year = entry["scenario"], entry["year"]
        table = pd.read_csv(verified(entry), usecols=[
            "technology", "grid_id", "initialization_mode", "capacity_mw", STOCK, ADDED,
        ])
        assert len(table) == entry["rows"] and table.initialization_mode.eq("gem_2025").all()
        assert not table.duplicated(["technology", "grid_id"]).any()
        assert table[[STOCK, ADDED]].ge(0).all().all() and table.capacity_mw.gt(0).all()
        np.testing.assert_allclose(table[STOCK] + table[ADDED], table.capacity_mw, rtol=1e-9, atol=1e-8)
        for tech, group in table.groupby("technology"):
            table_by_grid = group.set_index("grid_id")[[STOCK, ADDED]].sort_index()
            stock = table_by_grid.loc[table_by_grid[STOCK].gt(0), STOCK]
            pd.testing.assert_series_equal(stock, baseline.setdefault(tech, stock))
            tables[scenario, year, tech] = table_by_grid
    assert set(tables) == {(s, y, t) for s in SSPS for y in SNAPSHOTS for t in TECHS}
    return tables, baseline, files


def annual(entry):
    fields = ("grid_id", "years", "capacity_mw", "net_loss_mwh", "common_support")
    with np.load(verified(entry), allow_pickle=False) as data:
        return [data[field] for field in fields]


def load_future(task):
    scenario, tech, catalogue, entries, published = task
    periods = np.repeat(SNAPSHOTS, 10)
    stock = catalogue[0].loc[lambda x: x[STOCK].gt(0), STOCK]
    grid_ids = np.unique(np.concatenate([table.index.to_numpy() for table in catalogue]))
    allocation = np.stack([table.reindex(grid_ids, fill_value=0).to_numpy() for table in catalogue])
    capacity = allocation.sum(axis=2)
    rates, masks = [], []
    for model, entry in zip(MODELS, entries, strict=True):
        grid, years, capacity_mw, net_loss, mask = annual(entry)
        order = np.argsort(grid)
        np.testing.assert_array_equal(grid[order], grid_ids)
        np.testing.assert_array_equal(years, np.arange(2030, 2060))
        capacity_mw, net_loss, mask = capacity_mw[:, order], net_loss[:, order], mask[order]
        np.testing.assert_allclose(capacity_mw, np.repeat(capacity, 10, axis=0), rtol=1e-9, atol=1e-8)
        expected = published.loc[model].reindex(years)
        np.testing.assert_allclose(capacity_mw[:, mask].sum(axis=1), expected.capacity_mw)
        active = (capacity_mw > 0) & mask
        assert np.isfinite(net_loss[active]).all()
        np.testing.assert_allclose(np.where(active, net_loss, 0).sum(axis=1), expected.net_loss_mwh)
        unit_loss = np.divide(net_loss, capacity_mw, where=active, out=np.zeros_like(net_loss))
        active_per_period = active.reshape(3, 10, -1).all(axis=1)
        split_capacity = allocation[np.searchsorted(SNAPSHOTS, periods)]
        split_loss = np.einsum("ygc,yg->yc", split_capacity, unit_loss)
        np.testing.assert_allclose(split_loss.sum(axis=1), expected.net_loss_mwh)
        rates.append(np.where(active_per_period, unit_loss.reshape(3, 10, -1).mean(axis=1), np.nan))
        masks.append(mask)
    for mask in masks[1:]:
        np.testing.assert_array_equal(mask, masks[0])
    assert np.isin(stock.index, grid_ids).all()
    print(f"Validated {scenario} {tech}: 4 archives and 120 annual totals", flush=True)
    return (scenario, tech), (grid_ids, allocation, np.stack(rates), masks[0])


def load_history(entry, stock, published):
    grid, years, capacity, net_loss, mask = annual(entry)
    year = list(years).index(2025)
    result = pd.DataFrame({"capacity": capacity[year], "loss": net_loss[year], "valid": mask}, index=grid)
    active = result.loc[result.capacity.gt(0)]
    np.testing.assert_array_equal(active.sort_index().index, stock.index)
    np.testing.assert_allclose(active.reindex(stock.index).capacity, stock, rtol=1e-9, atol=1e-8)
    np.testing.assert_allclose(result.loc[mask, "capacity"].sum(), published.capacity_mw)
    np.testing.assert_allclose(result.loc[mask, "loss"].sum(), published.net_loss_mwh)
    at_stock = active.loc[active.valid].reindex(stock.index)
    return at_stock.loss / at_stock.capacity


def summarize(future, history, baseline):
    records, historical, plot_data, coverage = [], [], {}, {}
    for tech, stock in baseline.items():
        valid = history[tech].notna().to_numpy()
        for scenario in SSPS:
            grid, _, _, mask = future[scenario, tech]
            valid &= mask[np.searchsorted(grid, stock.index)]
        common = stock.loc[valid]
        values = history[tech].loc[common.index].to_numpy()
        history_mean = np.average(values, weights=common)
        historical.append(dict(tech=tech, year=2025, model="ERA5-Land",
                               stock_unit_loss=history_mean, stock_capacity_mw=common.sum(),
                               stock_grids=len(common)))
        coverage[tech] = dict(nominal_mw=stock.sum(), common_mw=common.sum(),
                              common_grids=len(common), coverage_pct=100 * common.sum() / stock.sum())
        plot = {"stock_2025_values": values, "stock_2025_weights": common.to_numpy()}
        gray = []
        for scenario in SSPS:
            grid, allocation, rates, mask = future[scenario, tech]
            stock_rates = rates[:, :, np.searchsorted(grid, common.index)]
            gray.append(stock_rates.mean(axis=0))
            for period, year in enumerate(SNAPSHOTS):
                added = allocation[period, :, 1]
                supported = (added > 0) & mask
                weights = added[supported]
                added_rates = rates[:, period, supported]
                values = added_rates.mean(axis=0)
                plot[f"{scenario}_{year}_values"] = values
                plot[f"{scenario}_{year}_weights"] = weights
                for model, old, new in zip(MODELS, stock_rates[:, period], added_rates, strict=True):
                    assert np.isfinite(old).all() and np.isfinite(new).all()
                    stock_mean = np.average(old, weights=common)
                    new_mean = np.average(new, weights=weights) if weights.size else np.nan
                    records.append(dict(tech=tech, ssp=scenario, decade=year, model=model,
                                        stock_unit_loss=stock_mean, added_unit_loss=new_mean,
                                        added_minus_stock=new_mean - stock_mean,
                                        stock_capacity_mw=common.sum(), added_capacity_mw=weights.sum(),
                                        added_nominal_mw=added.sum(), added_grids=len(weights)))
        for year, values in zip(SNAPSHOTS, np.mean(gray, axis=0), strict=True):
            plot[f"stock_{year}_values"] = values
            plot[f"stock_{year}_weights"] = common.to_numpy()
        plot_data[tech] = plot
    return pd.DataFrame(records), pd.DataFrame(historical), plot_data, coverage


def load_inputs():
    dispatch, dispatch_sha = release(DISPATCH)
    gem, gem_sha = release(GEM)
    catalogue, baseline, files = capacities(dispatch)
    published = pd.read_csv(verified(dispatch["summaries"]["global_annual_models.csv"]))
    weather = {(e["climate_ssp"], e["tech"], e["model"]): e
               for e in dispatch["annual_archives"] if e["station_ssp"] == e["climate_ssp"]}
    tasks = [
        (s, t, [catalogue[s, y, t] for y in SNAPSHOTS], [weather[s, t, m] for m in MODELS],
         published.loc[published.station_ssp.eq(s) & published.climate_ssp.eq(s)
                       & published.tech.eq(t)].set_index(["model", "year"]))
        for s in SSPS for t in TECHS
    ]
    gem_table = pd.read_csv(verified(gem["summaries"]["global_annual_models.csv"]))
    historical_rows = gem_table.loc[gem_table.model.eq("ERA5-Land") & gem_table.year.eq(2025)].set_index("tech")
    history = {e["tech"]: load_history(e, baseline[e["tech"]], historical_rows.loc[e["tech"]])
               for e in gem["annual_archives"] if e["phase"] == "historical" and e["model"] == "ERA5-Land"}
    with ProcessPoolExecutor(max_workers=min(6, int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))) as pool:
        future = dict(pool.map(load_future, tasks))
    checks = dict(dispatch_index_sha256=dispatch_sha, gem_index_sha256=gem_sha,
                  dispatch_archives=list(weather.values()), station_inputs=files,
                  checked_annual_totals=len(weather)*30)
    return future, history, baseline, checks


def write_outputs(prefix, results, checks):
    models, historical, plot_data, coverage = results
    summary = models.groupby(["tech", "decade", "ssp"], as_index=False).agg(
        stock_unit_loss=("stock_unit_loss", "mean"), added_unit_loss=("added_unit_loss", "mean"),
        added_minus_stock=("added_minus_stock", "mean"),
        model_min=("added_minus_stock", "min"), model_max=("added_minus_stock", "max"),
        n_models=("added_minus_stock", "count"), n_higher=("added_minus_stock", lambda x: x.gt(0).sum()),
        n_lower=("added_minus_stock", lambda x: x.lt(0).sum()),
        stock_capacity_mw=("stock_capacity_mw", "first"), added_capacity_mw=("added_capacity_mw", "first"),
        added_nominal_mw=("added_nominal_mw", "first"), added_grids=("added_grids", "first"),
    )
    DATA.mkdir(parents=True, exist_ok=True)
    models.to_csv(DATA / f"{prefix}_models.csv", index=False)
    summary.to_csv(DATA / f"{prefix}_summary.csv", index=False)
    historical.to_csv(DATA / f"{prefix}_historical.csv", index=False)
    for tech, plot in plot_data.items():
        np.savez_compressed(DATA / f"{prefix}_violin_{tech}.npz", **plot)
    checks = {**checks, "stock_coverage": coverage}
    (DATA / f"{prefix}_validation.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(historical.to_string(index=False))
    print(summary.to_string(index=False))


def main():
    future, history, baseline, checks = load_inputs()
    write_outputs(PREFIX, summarize(future, history, baseline), checks)


if __name__ == "__main__":
    main()
