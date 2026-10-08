"""Render three station-level climate-by-deployment counterfactual matrices."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, INDEXES
from paper_figures.common.io import write_csv, write_json, digest
from paper_figures.common.metrics import ensemble, climate_deployment
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.main.fig04_climate_deployment.prepare_cf_counterfactual import CACHE, tasks

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SOURCE = OUT / "source_data"
KEYS = ["model", "tech", "climate_ssp", "station_ssp"]
STATION_FILES = {"ssp126": "stations_SSP1-2.6.csv",
                 "ssp245": "stations_SSP2-4.5.csv", "ssp585": "stations_SSP5-6.0.csv"}

def prepare():
    final = ROOT / "logs/paper_figures/completion_status/final_audit.json"
    assert json.loads(final.read_text())["acceptance"]["status"] == "PASSED"
    parts, shard_audit = [], []
    for s, tech, patch, model in tasks():
        dest = CACHE / s / tech / patch / model
        meta = json.loads((dest / "complete.json").read_text())
        assert meta["task"] == [s, tech, patch, model]
        if meta["status"] == "EMPTY":
            continue
        assert meta["status"] == "COMPLETED"
        assert digest(dest / "annual.csv") == meta["annual_sha256"]
        f = pd.read_csv(dest / "annual.csv")
        assert len(f) == 30 and f.year.nunique() == 10
        assert not f.duplicated(["climate_ssp", "year"]).any()
        assert set(f.climate_ssp) == set(SSPS)
        parts.append(f)
        shard_audit.append(dict(station_ssp=s, tech=tech, patch=patch, model=model,
            support_sha256=meta["support_sha256"], annual_sha256=meta["annual_sha256"],
            source_records_sha256=digest(dest / "sources.json"), job_id=meta["job_id"]))
    patch = pd.concat(parts, ignore_index=True)
    assert not patch.duplicated(KEYS + ["patch", "year"]).any()
    caps = patch.groupby(["station_ssp", "tech", "patch"]).capacity_mw.agg(["min", "max"])
    assert np.allclose(caps["min"], caps["max"])
    annual = patch.groupby(KEYS + ["year"], as_index=False).agg(
        capacity_mw=("capacity_mw", "sum"), n_stations=("n_stations", "sum"),
        capacity_cf_mw=("capacity_cf_mw", "sum"),
        valid_capacity_hours=("valid_capacity_hours", "sum"),
        expected_hours=("expected_hours", "first"),
        min_station_time_coverage=("min_station_time_coverage", "min"),
        calendar=("calendar", "first"))
    assert len(annual) == 720
    annual["cf_pct"] = 100 * annual.capacity_cf_mw / annual.capacity_mw
    annual["capacity_time_coverage"] = annual.valid_capacity_hours / (
        annual.capacity_mw * annual.expected_hours)
    assert annual.cf_pct.between(0, 100).all()
    annual["snapshot"] = 2050
    annual["country"] = "GLOBAL"
    write_csv(SOURCE / "counterfactual_cf_annual.csv", annual)
    cf = annual.groupby(KEYS, as_index=False).agg(
        value=("cf_pct", "mean"), capacity_mw=("capacity_mw", "first"),
        n_stations=("n_stations", "first"),
        min_station_time_coverage=("min_station_time_coverage", "min"),
        capacity_time_coverage=("capacity_time_coverage", "mean"),
        calendar=("calendar", "first"))
    cf["metric"] = "cf_pct"
    cf["unit"] = "%"
    ep = OUTPUT / "event_summary/window.csv.gz"
    selected = []
    for f in pd.read_csv(ep, chunksize=50000):
        selected.append(f[f.country.eq("GLOBAL") & f.snapshot.eq(2050) & f.event.eq("all")])
    ev = pd.concat(selected, ignore_index=True)
    assert len(ev) == 72
    assert np.allclose(ev.E, ev.capacity_event_hours / ev.capacity_mw)
    ev["value"] = ev.E / 24
    ev["metric"] = "exposure_days"
    ev["unit"] = "day yr-1"
    ev = ev.merge(cf[KEYS + ["n_stations", "calendar"]], on=KEYS, validate="one_to_one")
    hours = annual.groupby(KEYS, as_index=False).expected_hours.mean()
    ev = ev.merge(hours, on=KEYS, validate="one_to_one")
    ev["capacity_time_coverage"] = ev.capacity_valid_hours / (ev.capacity_mw * ev.expected_hours)
    assert ev.capacity_time_coverage.between(.99 - 1e-9, 1 + 1e-9).all()
    loss = pd.read_csv(SOURCE / "panel_ab.csv")
    assert loss.snapshot.eq(2050).all() and loss.country.eq("GLOBAL").all()
    assert loss.event.eq("all").all() and loss.support.eq("common").all()
    assert np.allclose(loss.R, loss.net_mwh / loss.capacity_mw)
    loss["value"] = loss.R
    loss["metric"] = "net_loss"
    loss["unit"] = "MWh MW-1 yr-1"
    ref = loss[KEYS + ["capacity_mw"]]
    for f in (cf, ev, loss):
        assert not f.duplicated(KEYS).any() and len(f) == 72
        assert set(f.model) == set(MODELS)
        check = f.merge(ref, on=KEYS, suffixes=("", "_loss"), validate="one_to_one")
        assert np.allclose(check.capacity_mw, check.capacity_mw_loss, rtol=1e-9)
        f["snapshot"] = 2050
        f["window_start"] = 2050
        f["window_end"] = 2059
        f["country"] = "GLOBAL"
        f["support"] = "Fig4 Loss common station cohort"
        f["station_source"] = f.station_ssp.map(STATION_FILES)
    catalogue = pd.read_csv(OUTPUT / "catalogues/capacity_by_country.csv")
    catalogue = catalogue[catalogue.snapshot.eq(2050)].groupby(
        ["tech", "station_ssp"], as_index=False).capacity_mw.sum().rename(
        columns={"capacity_mw": "catalogue_capacity_mw"})
    table = pd.concat([cf, ev, loss], ignore_index=True).merge(catalogue,
        on=["tech", "station_ssp"], validate="many_to_one")
    table["capacity_coverage_pct"] = 100 * table.capacity_mw / table.catalogue_capacity_mw
    write_csv(SOURCE / "counterfactual_model_values.csv", table)
    write_csv(SOURCE / "counterfactual_cf_shard_audit.csv", pd.DataFrame(shard_audit))
    heat = ensemble(table, ["metric", "tech", "climate_ssp", "station_ssp"], "value", 4)
    heat = heat.drop(columns=["agreement", "category"])
    assert len(heat) == 54 and heat.n_models.eq(4).all()
    write_csv(SOURCE / "counterfactual_ensemble.csv", heat)
    terms = []
    for (metric, tech, model), g in table.groupby(["metric", "tech", "model"]):
        d = climate_deployment(g.set_index(["climate_ssp", "station_ssp"]).value.to_dict())
        assert abs(d["closure"]) < 1e-10
        terms.append(dict(metric=metric, tech=tech, model=model, **d))
    write_csv(SOURCE / "counterfactual_contrasts.csv", pd.DataFrame(terms))
    audit = dict(status="PASSED", model_rows=len(table), ensemble_cells=len(heat),
        annual_cf_rows=len(annual), cf_nonempty_shards=len(shard_audit),
        cf_min_station_time_coverage=float(cf.min_station_time_coverage.min()),
        exposure_min_capacity_time_coverage=float(ev.capacity_time_coverage.min()),
        min_capacity_coverage_pct=float(table.capacity_coverage_pct.min()),
        max_capacity_coverage_pct=float(table.capacity_coverage_pct.max()),
        capacity_matches_original_fig04=True,
        input_sha256={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): digest(p)
            for p in [ep, SOURCE / "panel_ab.csv", final, INDEXES["cf_stations"]]},
        job_id=os.environ.get("SLURM_JOB_ID"))
    write_json(OUT / "counterfactual_data_audit.json", audit)
    return heat, audit

def render(heat, metric, *, stem=None, subtitle="2050 capacity snapshot | 2050–2059 climate",
           limits=None, footer="Common station cohort; capacity-weighted four-model mean. Outlines: paired SSPs."):
    configure()
    plt.rcParams.update({"font.size": 7, "axes.labelsize": 7,
                         "xtick.labelsize": 7, "ytick.labelsize": 7})
    f = heat[heat.metric.eq(metric)]
    definitions = {
        "cf_pct": ("cf", "Global station capacity factor", "Capacity factor (%)", 5, 2),
        "exposure_days": ("exposure", "Global station extreme-event exposure",
                          r"Exposure (day yr$^{-1}$)", 10, 2),
        "net_loss": ("loss", "Global station net loss per unit capacity",
                     r"Net loss (MWh MW$^{-1}$ yr$^{-1}$)", 10, 1),
    }
    short, title, unit, step, digits = definitions[metric]
    stem = stem or f"fig04_{short}_counterfactual_2050s"
    low, high = float(f["mean"].min()), float(f["mean"].max())
    vmin, vmax = limits or (np.floor(low / step) * step, np.ceil(high / step) * step)
    assert vmin <= low and high <= vmax
    if vmin < 0:
        bound = max(abs(vmin), abs(vmax))
        norm, cmap = TwoSlopeNorm(vmin=-bound, vcenter=0, vmax=bound), "RdBu_r"
    else:
        norm, cmap = Normalize(vmin, vmax), "Blues"
    fig = plt.figure(figsize=(183 / 25.4, 82 / 25.4))
    fig.text(.5, .951, title, ha="center", va="center", fontsize=9)
    fig.text(.5, .884, subtitle, ha="center", fontsize=7)
    for i, tech in enumerate(TECHS):
        left = .10 + i * .435
        ax = fig.add_axes([left, .265, .32, .485])
        matrix = f[f.tech.eq(tech)].pivot(index="climate_ssp", columns="station_ssp",
            values="mean").reindex(index=SSPS, columns=SSPS).to_numpy()
        assert np.isfinite(matrix).all()
        im = ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
        for row in range(3):
            for col in range(3):
                value = matrix[row, col]
                rgba = im.cmap(norm(value))
                luminance = .2126 * rgba[0] + .7152 * rgba[1] + .0722 * rgba[2]
                ax.text(col, row, f"{value:.{digits}f}", ha="center", va="center",
                        color="white" if luminance < .5 else "#182735", fontsize=8)
            ax.add_patch(Rectangle((row - .47, row - .47), .94, .94, fill=False,
                                  lw=1, edgecolor="#242424"))
        ax.set(xticks=range(3), xticklabels=["126", "245", "585"],
               yticks=range(3), yticklabels=["126", "245", "585"],
               xlabel="Station SSP", ylabel="Climate SSP")
        ax.tick_params(length=0, pad=4)
        fig.text(left - .038, .79, "ab"[i], fontweight="bold", fontsize=9)
        fig.text(left, .79, "Wind" if tech == "wind" else "Solar", fontsize=8)
    cax = fig.add_axes([.895, .265, .014, .485])
    bar = fig.colorbar(im, cax=cax)
    bar.set_label(unit, labelpad=6)
    bar.set_ticks(np.arange(norm.vmin, norm.vmax + step / 2, step))
    bar.ax.tick_params(labelsize=6.5, length=2)
    fig.text(.5, .067, footer,
             ha="center", fontsize=6.5)
    images = [export_panel_png(fig, OUT / (stem + ".png"))]
    return dict(metric=metric, shared_color_limits=[norm.vmin, norm.vmax],
                unit=unit, files=images)

def main():
    heat, audit = prepare()
    figures = [render(heat, metric) for metric in ("cf_pct", "exposure_days", "net_loss")]
    write_json(OUT / "counterfactual_metadata.json", dict(
        created_utc=datetime.now(timezone.utc).isoformat(), job_id=os.environ.get("SLURM_JOB_ID"),
        snapshot=2050, window=[2050, 2059], models=MODELS, climate_ssps=SSPS, station_ssps=SSPS,
        cf="Annual mean native-time CF per station, capacity weighted, ten years equally weighted, then four models equally weighted; percent",
        exposure="Observed applicable-event union hours, capacity weighted, ten-year annual mean /24; then four models equally weighted",
        loss="Signed net event-union loss energy / common capacity; ten-year annual mean, MWh/MW/year; raw wind values",
        support="Existing Fig4 common station cohort; fixed capacities within each deployment",
        missing_cf="Station-year finite-time means; require at least 99% native-time coverage, report actual coverage",
        uncertainty="Four-model minimum and maximum retained in source data; heatmaps annotate means",
        station_sources=STATION_FILES, figures=figures, data_audit=audit,
        visual_review="PENDING"))
    print("COUNTERFACTUAL FIGURES COMPLETE", flush=True)

if __name__ == "__main__":
    main()
