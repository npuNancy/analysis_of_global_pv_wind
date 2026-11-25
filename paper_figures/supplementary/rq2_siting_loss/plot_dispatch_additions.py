"""Compare cumulative capacity additions in the three accepted dispatch-2025 layouts."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from paper_figures.common.io import digest
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import SSPS, SSP_COLORS, TECHS

ROOT = Path(__file__).resolve().parents[3]
RELEASE = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585")
BUNDLE = ROOT / "tmp/RQ1_20261119_candidates"
DATA = BUNDLE / "source_data/rq2_candidates"
IMAGES = BUNDLE / "images/rq2_candidates"
YEARS = (2030, 2040, 2050)
LABELS = {"wind": ("Wind", "TW", "MW"), "solar": ("Solar PV", r"TW$_p$", "MWp")}


def read_additions():
    index_path = RELEASE / "runtime/authoritative_index.json"
    completion = json.loads((RELEASE / "runtime/completion.json").read_text())
    index = json.loads(index_path.read_text())
    assert completion["status"] == index["status"] == "COMPLETED"
    assert digest(index_path) == completion["index_sha256"]
    provenance = index["provenance"]["station_provenance.json"]
    assert digest(Path(provenance["path"])) == provenance["sha256"]
    entries = json.loads(Path(provenance["path"]).read_text())
    assert len(entries) == len(SSPS) * len(YEARS)
    catalogue_entry = index["summaries"]["catalogue_capacity.csv"]
    catalogue_path = Path(catalogue_entry["path"])
    assert digest(catalogue_path) == catalogue_entry["sha256"]
    catalogue = pd.read_csv(catalogue_path).set_index(["station_ssp", "snapshot", "tech"])
    cols = ["technology", "grid_id", "year", "initialization_mode", "capacity_unit", "capacity_mw",
            "baseline_capacity_mw", "new_capacity_since_2025_mw", "added_capacity_mw"]
    records, inputs, baseline = [], [], {}
    for entry in sorted(entries, key=lambda e: (e["scenario"], e["year"])):
        scenario, year = entry["scenario"], entry["year"]
        assert scenario in SSPS and year in YEARS
        path = Path(entry["path"])
        checksum = digest(path)
        assert checksum == entry["sha256"], path
        data = pd.read_csv(path, usecols=cols)
        assert len(data) == entry["rows"] and not data.duplicated(["technology", "grid_id"]).any()
        assert data.year.eq(year).all() and data.initialization_mode.eq("gem_2025").all()
        inputs.append({"path": str(path), "sha256": checksum})
        for tech, group in data.groupby("technology"):
            assert set(group.capacity_unit) == {LABELS[tech][2]}
            stock = group.baseline_capacity_mw
            added = group.new_capacity_since_2025_mw
            assert np.isfinite(group[cols[-4:]]).all().all()
            assert group.capacity_mw.gt(0).all() and stock.ge(0).all() and added.ge(0).all()
            np.testing.assert_allclose(group.capacity_mw, stock + added, rtol=1e-9, atol=1e-8)
            base_cells = group.loc[stock.gt(0)].set_index("grid_id").baseline_capacity_mw.sort_index()
            if tech in baseline:
                pd.testing.assert_series_equal(base_cells, baseline[tech])
            else:
                baseline[tech] = base_cells
            new_cells = added.loc[stock.eq(0)].sum()
            expected = catalogue.loc[(scenario, year, tech)]
            assert len(group) == expected.n_catalogue
            np.testing.assert_allclose(group.capacity_mw.sum(), expected.catalogue_capacity_mw,
                                       rtol=1e-10, atol=1e-7)
            records.append(dict(
                station_ssp=scenario, year=year, tech=tech, native_capacity_unit=LABELS[tech][2],
                baseline_capacity_mw=stock.sum(), snapshot_capacity_mw=group.capacity_mw.sum(),
                cumulative_added_mw=added.sum(), previous_snapshot_added_mw=group.added_capacity_mw.sum(),
                existing_grid_added_mw=added.loc[stock.gt(0)].sum(), new_grid_added_mw=new_cells,
                new_grid_share_pct=100*new_cells/added.sum() if added.sum() > 0 else np.nan,
            ))
    table = pd.DataFrame(records).sort_values(["tech", "station_ssp", "year"])
    assert len(table) == 18 and not table.duplicated(["tech", "station_ssp", "year"]).any()
    delta = table.groupby(["tech", "station_ssp"]).cumulative_added_mw.diff().fillna(table.cumulative_added_mw)
    np.testing.assert_allclose(delta, table.previous_snapshot_added_mw, rtol=1e-9, atol=1e-7)
    return table, {"index_sha256": completion["index_sha256"], "inputs": inputs,
                   "catalogue_sha256": catalogue_entry["sha256"],
                   "checks": ["same grid-level 2025 stock across all snapshots",
                              "snapshot = baseline + additions", "full catalogue capacity reproduced",
                              "increments reconcile between snapshots"]}


def render(table, techs, suffix):
    full = len(techs) == 2
    fig, axes = plt.subplots(len(techs), 2, squeeze=False, figsize=(190/25.4, (151 if full else 94)/25.4))
    fig.subplots_adjust(left=.121, right=.974, bottom=.14 if full else .20,
                        top=.85 if full else .77, wspace=.35, hspace=.72)
    fig.suptitle("Dispatch-2025 | Capacity added since 2025", y=.982, fontsize=10)
    fig.text(.54, .933 if full else .902, "Global capacity snapshots and the location of additions",
             ha="center", va="top", fontsize=7, color=".32")
    colors = ["#3F779F", "#D6DBDE"]
    for (trend, composition), tech in zip(axes, techs):
        group = table.loc[table.tech.eq(tech)]
        tech_label, unit, _ = LABELS[tech]
        panel_offset = 0 if tech == "wind" else 2
        trend.set_title("abcd"[panel_offset] + "  " + tech_label + " | Cumulative additions", loc="left", fontsize=8)
        composition.set_title("abcd"[panel_offset+1] + "  " + tech_label + " | Additions by grid type in 2050",
                              loc="left", fontsize=8)
        for scenario, marker in zip(SSPS, ("o", "s", "^")):
            series = group.loc[group.station_ssp.eq(scenario)].sort_values("year")
            trend.plot([2025, *series.year], [0, *(series.cumulative_added_mw/1e6)],
                       marker=marker, ms=3.7, lw=1.4, color=SSP_COLORS[scenario], label=scenario.upper())
        trend.set_xticks([2025, *YEARS])
        trend.set_ylabel(f"Added capacity ({unit})")
        trend.set_ylim(bottom=0)
        trend.legend(loc="upper left", fontsize=7)
        share = group.loc[group.year.eq(2050)].set_index("station_ssp").loc[list(SSPS), "new_grid_share_pct"]
        ticks = range(len(SSPS))
        composition.bar(ticks, share, width=.57, color=colors[0])
        composition.bar(ticks, 100-share, bottom=share, width=.57, color=colors[1])
        for x, pct in zip(ticks, share):
            composition.text(x, 48, f"{pct:.1f}%", ha="center", va="center", fontsize=8, color="white")
        composition.set_ylim(0, 100)
        composition.set_yticks([0, 25, 50, 75, 100])
        composition.set_xticks(ticks, [scenario.upper() for scenario in SSPS])
        composition.set_ylabel("Share of additions (%)")
        for ax in (trend, composition):
            ax.set_axisbelow(True)
            ax.grid(axis="y", color=".91", lw=.5)
    fig.legend(handles=[Patch(facecolor=c, label=label) for c, label in zip(
        colors, ["Grid cells without 2025 capacity", "Grid cells with 2025 capacity"])],
        loc="lower center", bbox_to_anchor=(.535, .023), ncol=2, fontsize=7)
    return export_panel_png(fig, IMAGES/f"dispatch2025_capacity_additions{suffix}.png")


def main():
    configure()
    table, metadata = read_additions()
    DATA.mkdir(parents=True, exist_ok=True)
    table.to_csv(DATA / "dispatch2025_capacity_additions.csv", index=False)
    metadata["products"] = [render(table, techs, suffix)
                            for techs, suffix in [(TECHS, ""), (TECHS[:1], "_ab"), (TECHS[1:], "_cd")]]
    (DATA / "dispatch2025_capacity_validation.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
