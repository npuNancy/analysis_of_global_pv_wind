"""Decadal combined wind and solar generation from complete annual station CF."""
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
CF_SOURCE = ROOT / "paper_figures/main/fig04_climate_deployment/outputs/source_data/counterfactual_decades_cf_annual.csv"
LOSS_SOURCE = OUT / "source_data/panel_ab.csv"


def main():
    data_dir = OUT / "source_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".mplconfig"))
    import matplotlib.pyplot as plt

    cf = pd.read_csv(CF_SOURCE)
    cf = cf[cf.climate_ssp.eq(cf.station_ssp)].copy()
    keys = ["model", "tech", "climate_ssp", "station_ssp", "snapshot", "year"]
    assert len(cf) == 720 and not cf.duplicated(keys).any()
    assert set(cf[["model", "tech", "climate_ssp", "year"]].itertuples(index=False, name=None)) == set(
        product(MODELS, TECHS, SSPS, range(2030, 2060)))
    assert cf.country.eq("GLOBAL").all()
    assert cf.snapshot.eq(cf.year // 10 * 10).all()
    assert np.isfinite(cf[["capacity_cf_mw", "capacity_mw", "expected_hours"]]).all().all()
    assert cf.capacity_mw.gt(0).all()
    assert np.allclose(cf.min_station_time_coverage, 1, rtol=0, atol=1e-12)
    assert np.allclose(cf.valid_capacity_hours, cf.capacity_mw * cf.expected_hours, rtol=1e-12)
    assert cf.expected_hours.isin([8760, 8784]).all()
    assert np.allclose(cf.cf_pct, 100 * cf.capacity_cf_mw / cf.capacity_mw)
    loss = pd.read_csv(LOSS_SOURCE)
    matched = cf.merge(loss[keys + ["capacity_mw", "n_stations", "available_capacity_mw"]],
                       on=keys, validate="one_to_one", suffixes=("", "_loss"))
    assert len(matched) == 720
    assert np.allclose(matched.capacity_mw, matched.capacity_mw_loss, rtol=1e-10)
    assert matched.n_stations.eq(matched.n_stations_loss).all()
    cf["generation_mwh"] = cf.capacity_cf_mw * cf.expected_hours
    cf["available_capacity_mw"] = cf.merge(
        loss[keys + ["available_capacity_mw"]], on=keys, validate="one_to_one").available_capacity_mw.to_numpy()
    assert cf.generation_mwh.between(0, cf.capacity_mw * cf.expected_hours).all()
    cf.to_csv(data_dir / "combined_generation_technology_annual.csv", index=False)
    combined_keys = ["model", "climate_ssp", "station_ssp", "snapshot", "year"]
    assert cf.groupby(combined_keys).tech.nunique().eq(2).all()
    annual = cf.groupby(combined_keys, as_index=False).agg(
        generation_mwh=("generation_mwh", "sum"), capacity_mw=("capacity_mw", "sum"),
        available_capacity_mw=("available_capacity_mw", "sum"),
        n_stations=("n_stations", "sum"), expected_hours=("expected_hours", "first"),
        calendar=("calendar", "first"))
    annual["generation_pwh"] = annual.generation_mwh / 1e9
    annual["unit_capacity_generation"] = annual.generation_mwh / annual.capacity_mw
    annual["capacity_coverage_pct"] = 100 * annual.capacity_mw / annual.available_capacity_mw
    annual.to_csv(data_dir / "combined_generation_annual_models.csv", index=False)
    decade_keys = ["model", "climate_ssp", "station_ssp", "snapshot"]
    assert annual.groupby(decade_keys).year.nunique().eq(10).all()
    metrics = ["generation_pwh", "unit_capacity_generation"]
    decade = annual.groupby(decade_keys, as_index=False)[
        metrics + ["generation_mwh", "capacity_mw", "capacity_coverage_pct"]].mean()
    decade.to_csv(data_dir / "combined_generation_decadal_models.csv", index=False)
    assert decade.groupby(["climate_ssp", "snapshot"]).model.nunique().eq(4).all()
    display = decade.groupby(["climate_ssp", "snapshot"], as_index=False)[metrics].mean()
    assert len(display) == 9
    display.to_csv(data_dir / "combined_generation_decadal_display.csv", index=False)
    configure()
    images = []
    for metric, label, filename in [
        ("generation_pwh", "Total generation (PWh yr⁻¹)", "combined_total_generation_decadal.png"),
        ("unit_capacity_generation", "Generation per unit capacity (MWh MW⁻¹ yr⁻¹)",
         "combined_unit_capacity_generation_decadal.png"),
    ]:
        fig, ax = plt.subplots(figsize=(183 / 25.4, 105 / 25.4))
        fig.subplots_adjust(left=.14, right=.975, bottom=.16, top=.83)
        for ssp, marker in zip(SSPS, ("o", "s", "^")):
            data = display[display.climate_ssp.eq(ssp)].sort_values("snapshot")
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
        "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (CF_SOURCE, LOSS_SOURCE)},
        "question": "How does combined wind and solar generation evolve along paired SSP pathways?",
        "generation": "CF-derived simulated annual generation: sum of station capacity times annual mean CF times native-calendar year hours",
        "temporal_coverage": "Every selected station-year has complete CF coverage",
        "unit_capacity": "Combined annual wind and solar generation divided by combined valid capacity",
        "center": "Ten-year mean within each model, then equal-weight mean of four models",
        "models": list(MODELS), "years": [2030, 2059], "snapshots": [2030, 2040, 2050],
        "wind_energy_scale": 1,
        "scope": "GLOBAL common station support matching the loss figures; paired climate and station SSP",
        "station_ssp585_source": "stations_SSP5-6.0.csv",
        "capacity_coverage_pct": [annual.capacity_coverage_pct.min(), annual.capacity_coverage_pct.max()],
        "checks": ["720 unique complete technology-year records", "native-calendar hours",
                   "capacity and station counts match loss tables", "360 combined annual records",
                   "36 model-decade records", "9 scenario-decade points per figure"],
        "images": images,
    }
    (OUT / "combined_generation_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(display.to_string(index=False))
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
