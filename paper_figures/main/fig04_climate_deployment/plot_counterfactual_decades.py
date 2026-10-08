"""Render 2030s, 2040s, 2050s and equal-decade-mean station counterfactual matrices."""
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, INDEXES
from paper_figures.common.io import write_csv, write_json, digest
from paper_figures.common.metrics import ensemble, climate_deployment
from paper_figures.main.fig04_climate_deployment.prepare_cf_counterfactual import cache_root, tasks
from paper_figures.main.fig04_climate_deployment.plot_counterfactuals import (
    OUT, SOURCE, KEYS, STATION_FILES, render)

SNAPSHOTS = (2030, 2040, 2050)
MEAN_PERIOD = "mean_2030s_2050s"
METRICS = ("cf_pct", "exposure_days", "net_loss")
UNITS = {"cf_pct": "%", "exposure_days": "day yr-1", "net_loss": "MWh MW-1 yr-1"}

def cf_annual(snapshot):
    if snapshot == 2050:
        audit = json.loads((OUT / "counterfactual_data_audit.json").read_text())
        assert audit["status"] == "PASSED"
        assert audit["input_sha256"][str(INDEXES["cf_stations"])] == digest(INDEXES["cf_stations"])
        annual = pd.read_csv(SOURCE / "counterfactual_cf_annual.csv")
        assert len(annual) == 720 and annual.snapshot.eq(snapshot).all()
        return annual, []
    parts, audits = [], []
    for s, tech, patch, model in tasks():
        dest = cache_root(snapshot) / s / tech / patch / model
        meta = json.loads((dest / "complete.json").read_text())
        assert meta["task"] == [s, tech, patch, model]
        if meta["status"] == "EMPTY":
            continue
        assert meta["status"] == "COMPLETED"
        assert digest(dest / "annual.csv") == meta["annual_sha256"]
        f = pd.read_csv(dest / "annual.csv")
        assert len(f) == 30 and f.snapshot.eq(snapshot).all()
        assert set(f.year) == set(range(snapshot, snapshot + 10))
        assert set(f.climate_ssp) == set(SSPS)
        assert not f.duplicated(["climate_ssp", "year"]).any()
        parts.append(f)
        audits.append(dict(snapshot=snapshot, station_ssp=s, tech=tech, patch=patch, model=model,
            support_sha256=meta["support_sha256"], annual_sha256=meta["annual_sha256"],
            source_records_sha256=digest(dest / "sources.json"), job_id=meta["job_id"]))
    patch = pd.concat(parts, ignore_index=True)
    assert not patch.duplicated(KEYS + ["patch", "year"]).any()
    fixed = patch.groupby(["station_ssp", "tech", "patch"]).capacity_mw.agg(["min", "max"])
    assert np.allclose(fixed["min"], fixed["max"], rtol=1e-10)
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
    annual["snapshot"], annual["country"] = snapshot, "GLOBAL"
    return annual, audits

def select_window(path, loss=False):
    parts = []
    for f in pd.read_csv(path, chunksize=50000):
        take = f.country.eq("GLOBAL") & f.event.eq("all") & f.snapshot.isin(SNAPSHOTS)
        if loss:
            take &= f.support.eq("common")
        parts.append(f.loc[take])
    result = pd.concat(parts, ignore_index=True)
    assert len(result) == 216 and not result.duplicated(KEYS + ["snapshot"]).any()
    return result

def prepare():
    accepted = ROOT / "logs/paper_figures/completion_status/final_audit.json"
    assert json.loads(accepted.read_text())["acceptance"]["status"] == "PASSED"
    annuals, audits = [], []
    for snapshot in SNAPSHOTS:
        annual, audit = cf_annual(snapshot)
        annuals.append(annual)
        audits.extend(audit)
        print("CF annual assembled", snapshot, len(annual), flush=True)
    annual = pd.concat(annuals, ignore_index=True)
    assert len(annual) == 2160
    fixed = annual.groupby(["snapshot", "station_ssp", "tech"]).capacity_mw.agg(["min", "max"])
    assert np.allclose(fixed["min"], fixed["max"], rtol=1e-10)
    assert annual.groupby(KEYS + ["snapshot"]).year.nunique().eq(10).all()
    cf = annual.groupby(KEYS + ["snapshot"], as_index=False).agg(
        value=("cf_pct", "mean"), capacity_mw=("capacity_mw", "first"),
        n_stations=("n_stations", "first"),
        min_station_time_coverage=("min_station_time_coverage", "min"),
        capacity_time_coverage=("capacity_time_coverage", "mean"),
        calendar=("calendar", "first"), expected_hours=("expected_hours", "mean"))
    cf["metric"] = "cf_pct"
    assert cf.min_station_time_coverage.ge(.99).all()
    ep = OUTPUT / "event_summary/window.csv.gz"
    lp = OUTPUT / "loss_summary/window.csv.gz"
    ev, loss = select_window(ep), select_window(lp, loss=True)
    assert np.allclose(ev.E, ev.capacity_event_hours / ev.capacity_mw)
    assert np.allclose(loss.R, loss.net_mwh / loss.capacity_mw)
    ev["value"], ev["metric"] = ev.E / 24, "exposure_days"
    loss["value"], loss["metric"] = loss.R, "net_loss"
    ev = ev.merge(cf[KEYS + ["snapshot", "n_stations", "calendar", "expected_hours"]],
                  on=KEYS + ["snapshot"], validate="one_to_one")
    ev["capacity_time_coverage"] = ev.capacity_valid_hours / (ev.capacity_mw * ev.expected_hours)
    assert ev.capacity_time_coverage.between(.99 - 1e-9, 1 + 1e-9).all()
    for frame in (cf, ev, loss):
        assert len(frame) == 216 and np.isfinite(frame.value).all()
        assert not frame.duplicated(KEYS + ["snapshot"]).any()
        assert set(frame.model) == set(MODELS)
        check = frame.merge(loss[KEYS + ["snapshot", "capacity_mw", "n_stations"]],
            on=KEYS + ["snapshot"], suffixes=("", "_loss"), validate="one_to_one")
        assert np.allclose(check.capacity_mw, check.capacity_mw_loss, rtol=1e-9)
        assert np.array_equal(check.n_stations, check.n_stations_loss)
        frame["unit"] = frame.metric.map(UNITS)
        frame["period"] = frame.snapshot.astype(str) + "s"
        frame["window_start"], frame["window_end"] = frame.snapshot, frame.snapshot + 9
        frame["country"], frame["support"] = "GLOBAL", "Common station cohort within each snapshot and deployment"
        frame["station_source"] = frame.station_ssp.map(STATION_FILES)
    columns = KEYS + ["snapshot", "period", "metric", "value", "unit", "capacity_mw",
        "n_stations", "window_start", "window_end", "country", "support", "station_source",
        "min_station_time_coverage", "capacity_time_coverage", "calendar"]
    table = pd.concat([cf, ev, loss], ignore_index=True)[columns]
    catalogue = pd.read_csv(OUTPUT / "catalogues/capacity_by_country.csv").groupby(
        ["snapshot", "tech", "station_ssp"], as_index=False).capacity_mw.sum().rename(
        columns={"capacity_mw": "catalogue_capacity_mw"})
    table = table.merge(catalogue, on=["snapshot", "tech", "station_ssp"], validate="many_to_one")
    table["capacity_coverage_pct"] = 100 * table.capacity_mw / table.catalogue_capacity_mw
    old = pd.read_csv(SOURCE / "counterfactual_model_values.csv")
    check = table[table.snapshot.eq(2050) & table.metric.ne("net_loss")].merge(
        old[KEYS + ["metric", "value"]], on=KEYS + ["metric"], suffixes=("", "_previous"),
        validate="one_to_one")
    assert len(check) == 144 and np.allclose(check.value, check.value_previous, rtol=1e-12, atol=1e-12)
    ab = pd.read_csv(SOURCE / "panel_ab.csv")
    check_loss = loss[loss.snapshot.eq(2050)].merge(ab[KEYS + ["R"]],
        on=KEYS, suffixes=("", "_previous"), validate="one_to_one")
    assert len(check_loss) == 72 and np.allclose(check_loss.R, check_loss.R_previous, rtol=1e-12)
    groups = KEYS + ["metric", "unit"]
    means = table.groupby(groups, as_index=False).agg(
        value=("value", "mean"), n_decades=("snapshot", "nunique"))
    assert len(means) == 216 and means.n_decades.eq(3).all()
    means["period"], means["window_start"], means["window_end"] = MEAN_PERIOD, 2030, 2059
    means["snapshots"], means["decade_weights"] = "2030;2040;2050", "1/3;1/3;1/3"
    means["country"] = "GLOBAL"
    means["support"] = "Corresponding common station cohort and capacity within each decade"
    means["station_source"] = means.station_ssp.map(STATION_FILES)
    direct = table.pivot(index=groups, columns="snapshot", values="value").reindex(columns=SNAPSHOTS)
    assert direct.notna().all().all()
    expected = direct.mean(axis=1).sort_index()
    observed = means.set_index(groups).value.sort_index()
    mean_error = float(np.max(np.abs(expected - observed)))
    assert mean_error < 1e-10
    all_values = pd.concat([table, means], ignore_index=True)
    heat = ensemble(all_values, ["period", "metric", "tech", "climate_ssp", "station_ssp"], "value", 4)
    heat = heat.drop(columns=["agreement", "category"])
    assert len(heat) == 216 and heat.n_models.eq(4).all()
    contrasts = []
    for (period, metric, tech, model), g in all_values.groupby(["period", "metric", "tech", "model"]):
        d = climate_deployment(g.set_index(["climate_ssp", "station_ssp"]).value.to_dict())
        assert abs(d["closure"]) < 1e-10
        contrasts.append(dict(period=period, metric=metric, tech=tech, model=model, **d))
    contrasts = pd.DataFrame(contrasts)
    terms = ["D", "Phi_C", "Phi_S", "J", "delta_C_126", "delta_C_585", "delta_S_126", "delta_S_585"]
    mean_terms = contrasts[contrasts.period.eq(MEAN_PERIOD)].set_index(["metric", "tech", "model"])[terms].sort_index()
    direct_terms = contrasts[contrasts.period.ne(MEAN_PERIOD)].groupby(["metric", "tech", "model"])[terms].mean().sort_index()
    assert np.allclose(mean_terms, direct_terms, atol=1e-10)
    write_csv(SOURCE / "counterfactual_decades_cf_annual.csv", annual)
    write_csv(SOURCE / "counterfactual_decades_cf_shard_audit.csv", pd.DataFrame(audits))
    write_csv(SOURCE / "counterfactual_decades_model_values.csv", table)
    write_csv(SOURCE / "counterfactual_decades_mean_model_values.csv", means)
    write_csv(SOURCE / "counterfactual_decades_ensemble.csv", heat)
    write_csv(SOURCE / "counterfactual_decades_contrasts.csv", contrasts)
    coverage = table.groupby("snapshot").agg(
        min_capacity_coverage_pct=("capacity_coverage_pct", "min"),
        max_capacity_coverage_pct=("capacity_coverage_pct", "max"))
    audit = dict(status="PASSED", annual_cf_rows=len(annual), decade_model_rows=len(table),
        mean_model_rows=len(means), ensemble_cells=len(heat), plotted_ensemble_cells=216,
        min_cf_station_time_coverage=float(cf.min_station_time_coverage.min()),
        min_exposure_capacity_time_coverage=float(ev.capacity_time_coverage.min()),
        coverage_by_snapshot=coverage.to_dict(orient="index"), mean_closure_max_error=mean_error,
        previous_2050_cf_exposure_loss_reproduced=True, matched_capacity_and_station_counts=True,
        averaging="Equal 1/3 weights on the three per-model decade indicators, then equal model weights",
        input_sha256={str(p): digest(p) for p in [ep, lp, SOURCE / "counterfactual_cf_annual.csv",
            SOURCE / "counterfactual_model_values.csv", SOURCE / "panel_ab.csv",
            OUTPUT / "catalogues/capacity_by_country.csv", INDEXES["cf_stations"], accepted]},
        job_id=os.environ.get("SLURM_JOB_ID"))
    write_json(OUT / "counterfactual_decades_data_audit.json", audit)
    return heat, audit

def main():
    heat, audit = prepare()
    figures, scales = [], {}
    for metric, step in zip(METRICS, [5, 10, 10]):
        values = heat[heat.metric.eq(metric)]["mean"]
        limits = [float(np.floor(values.min() / step) * step),
                  float(np.ceil(values.max() / step) * step)]
        if limits[0] < 0:
            bound = max(abs(x) for x in limits)
            limits = [-bound, bound]
        scales[metric] = limits
    for period in ("2030s", "2040s", "2050s", MEAN_PERIOD):
        if period == MEAN_PERIOD:
            subtitle = "Equal mean of 2030s, 2040s and 2050s | decade-specific capacity snapshots"
        else:
            year = int(period[:4])
            subtitle = f"{year} capacity snapshot | {year}–{year + 9} climate"
        for metric, short in zip(METRICS, ["cf", "exposure", "loss"]):
            result = render(heat[heat.period.eq(period)], metric,
                stem=f"fig04_{short}_counterfactual_{period}",
                subtitle=subtitle, limits=scales[metric],
                footer=("Cohorts fixed within each decade; capacity-weighted four-model mean. Outlines: paired SSPs."
                        if period == MEAN_PERIOD else
                        "Common station cohort; capacity-weighted four-model mean. Outlines: paired SSPs."))
            result["period"] = period
            figures.append(result)
    assert len(figures) == 12 and all(len(f["files"]) == 1 for f in figures)
    write_json(OUT / "counterfactual_decades_metadata.json", dict(
        created_utc=datetime.now(timezone.utc).isoformat(), job_id=os.environ.get("SLURM_JOB_ID"),
        scientific_question="How do station CF, event exposure and net loss respond to climate and deployment across decades?",
        snapshots=SNAPSHOTS, models=MODELS, climate_ssps=SSPS, station_ssps=SSPS,
        mean="Per-model arithmetic mean of the three decade indicators; then four-model arithmetic mean",
        support="Fixed common station cohort and capacities within each deployment and decade; cohorts and capacities may change between decades",
        cf="Native-time annual CF per station, capacity weighted; ten-year mean, in percent",
        exposure="Observed applicable-event union duration, capacity weighted; annual hours divided by 24, in day/year",
        loss="Signed net event-union loss energy / common capacity; ten-year annual mean, MWh/MW/year; raw wind values",
        uncertainty="Four-model min/max calculated after each model's decade averaging and retained in source tables",
        color_scales=scales, figures=figures, data_audit=audit, visual_review="PENDING"))
    print("DECADE COUNTERFACTUAL FIGURES COMPLETE", len(figures), flush=True)

if __name__ == "__main__":
    main()
