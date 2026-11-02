"""Annual combined wind and solar net losses along paired SSP pathways."""
import json
import os
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, SSPS, TECHS, SSP_COLORS
from paper_figures.common.io import digest
from paper_figures.common.plotting import configure, export_panel_png

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SOURCE = HERE / "outputs/source_data/panel_ab.csv"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".mplconfig"))
    import matplotlib.pyplot as plt

    annual = pd.read_csv(SOURCE)
    keys = ["model", "climate_ssp", "station_ssp", "snapshot", "year"]
    assert len(annual) == 720
    assert not annual.duplicated(keys + ["tech"]).any()
    assert annual.country.eq("GLOBAL").all()
    assert annual.event.eq("all").all() and annual.support.eq("common").all()
    assert annual.climate_ssp.eq(annual.station_ssp).all()
    assert set(annual[["model", "climate_ssp", "tech", "year"]].itertuples(index=False, name=None)) == set(
        product(MODELS, SSPS, TECHS, range(2030, 2060)))
    assert annual.snapshot.eq(annual.year // 10 * 10).all()
    assert np.isfinite(annual[["net_mwh", "capacity_mw", "available_capacity_mw", "R"]]).all().all()
    assert annual.capacity_mw.gt(0).all()
    assert np.allclose(annual.R, annual.net_mwh / annual.capacity_mw)
    assert annual.groupby(keys).tech.nunique().eq(2).all()
    combined = annual.groupby(keys, as_index=False)[
        ["net_mwh", "capacity_mw", "available_capacity_mw", "n_stations"]].sum()
    combined["total_loss_pwh"] = combined.net_mwh / 1e9
    combined["unit_capacity_loss"] = combined.net_mwh / combined.capacity_mw
    combined["coverage_pct"] = 100 * combined.capacity_mw / combined.available_capacity_mw
    combined["tech"] = "wind+solar"
    combined["event"] = "all"
    combined["support"] = "common"
    assert combined.coverage_pct.between(0, 100 + 1e-8).all()
    assert np.allclose(combined.total_loss_pwh * 1e9,
                       combined.unit_capacity_loss * combined.capacity_mw)
    combined.to_csv(OUT / "source_data/combined_loss_models.csv", index=False)
    records = []
    for (ssp, year), group in combined.groupby(["climate_ssp", "year"]):
        assert len(group) == 4 and set(group.model) == set(MODELS)
        for metric in ["total_loss_pwh", "unit_capacity_loss"]:
            records.append(dict(ssp=ssp, year=int(year), metric=metric,
                                mean=group[metric].mean(), minimum=group[metric].min(),
                                maximum=group[metric].max(), n_models=4))
    display = pd.DataFrame(records)
    display.to_csv(OUT / "source_data/combined_loss_display.csv", index=False)
    configure()
    images = []
    fits = []
    for metric, label, filename in [
        ("total_loss_pwh", "Total net loss (PWh yr⁻¹)", "combined_total_loss.png"),
        ("unit_capacity_loss", "Net loss per unit capacity (MWh MW⁻¹ yr⁻¹)",
         "combined_unit_capacity_loss.png"),
    ]:
        fig, ax = plt.subplots(figsize=(183 / 25.4, 105 / 25.4))
        fig.subplots_adjust(left=.14, right=.975, bottom=.16, top=.83)
        for ssp in SSPS:
            data = display[display.ssp.eq(ssp) & display.metric.eq(metric)].sort_values("year")
            ax.plot(data.year, data["mean"], color=SSP_COLORS[ssp],
                    linewidth=1.7, label=ssp.upper())
            x = data.year.to_numpy() - 2030
            y = data["mean"].to_numpy()
            assert len(data) == 30
            slope, intercept = np.polyfit(x, y, 1)
            fitted = intercept + slope * x
            assert np.isclose(np.sum(y - fitted), 0, atol=1e-10)
            assert np.isclose(np.dot(x, y - fitted), 0, atol=1e-8)
            fits.append(dict(metric=metric, ssp=ssp, year_start=2030,
                             year_end=2059, n_years=30,
                             slope_per_year=slope, fitted_start=intercept,
                             fitted_end=intercept + 29 * slope))
            ax.plot(data.year, fitted, "--", color=SSP_COLORS[ssp],
                    linewidth=1.4, zorder=4)
        ax.set(xlabel="Year", ylabel=label, xlim=(2030, 2059))
        ax.set_xticks([2030, 2035, 2040, 2045, 2050, 2055, 2059])
        ax.grid(axis="y", color="#e5e5e5", linewidth=.5)
        ax.set_axisbelow(True)
        ax.margins(y=.12)
        ax.set_title("Wind + solar", loc="left", fontsize=10, pad=14)
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.015), ncol=3,
                  borderaxespad=0, handlelength=2.5)
        fig.text(.975, .025, "Dashed: 2030–2059 linear fit", ha="right", fontsize=7)
        images.append(export_panel_png(fig, OUT / filename))
    assert len(fits) == 6
    pd.DataFrame(fits).to_csv(OUT / "source_data/combined_loss_trends.csv", index=False)
    metrics = ["total_loss_pwh", "unit_capacity_loss"]
    decade_keys = ["model", "climate_ssp", "station_ssp", "snapshot"]
    assert combined.groupby(decade_keys).year.nunique().eq(10).all()
    decades = combined.groupby(decade_keys, as_index=False)[metrics].mean()
    decades.to_csv(OUT / "source_data/combined_loss_decadal_models.csv", index=False)
    assert decades.groupby(["climate_ssp", "snapshot"]).model.nunique().eq(4).all()
    decadal_display = decades.groupby(["climate_ssp", "snapshot"], as_index=False)[metrics].mean()
    assert len(decadal_display) == 9
    decadal_display.to_csv(OUT / "source_data/combined_loss_decadal_display.csv", index=False)
    for metric, label, filename in [
        ("total_loss_pwh", "Total net loss (PWh yr⁻¹)", "combined_total_loss_decadal.png"),
        ("unit_capacity_loss", "Net loss per unit capacity (MWh MW⁻¹ yr⁻¹)",
         "combined_unit_capacity_loss_decadal.png"),
    ]:
        fig, ax = plt.subplots(figsize=(183 / 25.4, 105 / 25.4))
        fig.subplots_adjust(left=.14, right=.975, bottom=.16, top=.83)
        for ssp, marker in zip(SSPS, ("o", "s", "^")):
            data = decadal_display[decadal_display.climate_ssp.eq(ssp)].sort_values("snapshot")
            assert data.snapshot.tolist() == [2030, 2040, 2050]
            ax.plot(data.snapshot, data[metric], color=SSP_COLORS[ssp],
                    linewidth=1.7, marker=marker, markersize=4.5, label=ssp.upper())
        ax.set(xlabel="Decade", ylabel=label, xlim=(2029, 2051))
        ax.set_xticks([2030, 2040, 2050], ["2030s", "2040s", "2050s"])
        ax.grid(axis="y", color="#e5e5e5", linewidth=.5)
        ax.set_axisbelow(True)
        ax.margins(y=.12)
        ax.set_title("Wind + solar", loc="left", fontsize=10, pad=14)
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.015), ncol=3,
                  borderaxespad=0, handlelength=2.5)
        fig.text(.975, .025, "Decadal means: 2030–2039, 2040–2049, 2050–2059",
                 ha="right", fontsize=7)
        images.append(export_panel_png(fig, OUT / filename))
    metadata = {
        "source": str(SOURCE.relative_to(ROOT)), "source_sha256": digest(SOURCE),
        "question": "How do combined wind and solar losses evolve along the three paired pathways?",
        "archetype": "quantitative grid; two independent time-series figures",
        "years": [2030, 2059], "models": list(MODELS),
        "center": "Equal-weight mean of four model-specific metrics",
        "loss": "Signed net loss over the selected event union; wind energy scale = 1",
        "total": "Sum wind and solar net_mwh within model and year, divide by 1e9 for PWh",
        "unit_capacity": "Combined net_mwh divided by combined valid capacity_mw within model and year",
        "support": "Existing common support within each deployment snapshot",
        "capacity_snapshots": {"2030": "2030-2039", "2040": "2040-2049", "2050": "2050-2059"},
        "pathways": "Matching climate_ssp and station_ssp; include climate and deployment changes",
        "station_ssp585_source": "stations_SSP5-6.0.csv",
        "uncertainty": "Model min/max saved in source data; plots show only three ensemble-mean lines",
        "smoothing": "None",
        "fit": "OLS of each SSP annual ensemble mean over 2030-2059; one dashed line per SSP",
        "coverage_pct_range": [combined.coverage_pct.min(), combined.coverage_pct.max()],
        "checks": ["720 unique technology records", "360 combined model records",
                   "complete four-model three-SSP 30-year matrix",
                   "positive capacities", "normalization and energy closure"],
        "decadal_center": "Ten-year means within each model, then equal-weight four-model means; points connected by straight segments",
        "images": images,
    }
    (OUT / "combined_loss_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
