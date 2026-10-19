"""Compare country deployment scale, layout and net generation loss in the 2050s."""
import argparse
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import MODELS, OUTPUT, ROOT, SSPS, STATION_FILES, TECHS
from paper_figures.common.io import digest, write_csv, write_json

HERE = Path(__file__).resolve().parent
SNAPSHOT = 2050
KEYS = ["model", "country", "tech", "climate_ssp", "station_ssp"]
GROUPS = ["country", "tech", "climate_ssp", "station_ssp"]
METRICS = ["C_GW", "L_TWh", "G0_TWh", "H0", "R", "rho_pct", "coverage_pct"]
CONTRAST_METRICS = [
    "scale_TWh", "layout_TWh", "delta_L_TWh", "scale_refG0_pct",
    "layout_refG0_pct", "delta_L_refG0_pct", "delta_H0_pct", "delta_R",
    "delta_rho_pp", "delta_C_pct", "delta_G0_pct", "equal_generation_capacity_ratio",
    "equal_generation_loss_TWh", "reference_loss_TWh", "expansion_scale_TWh",
    "expansion_layout_TWh", "expansion_delta_L_TWh", "expansion_delta_H0_pct",
    "expansion_delta_R", "offset_ratio",
]
TIE_RTOL = 1e-10
TIE_ATOL = 1e-8


def summarize(frame, keys, columns, agreement=False):
    records = []
    for key, group in frame.groupby(keys, dropna=False, sort=False):
        base = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        for metric in columns:
            values = group.loc[np.isfinite(group[metric]), metric].to_numpy(float)
            count = len(values)
            mean = float(np.mean(values)) if count else np.nan
            row = dict(base, metric=metric, mean=mean,
                       minimum=float(np.min(values)) if count else np.nan,
                       maximum=float(np.max(values)) if count else np.nan, n_models=count)
            if agreement:
                row["sign_agreement"] = int(np.sum(np.sign(values) == np.sign(mean))) if count else 0
            records.append(row)
    return pd.DataFrame(records)


def select_countries(catalogue, names, top_k):
    refs = catalogue[catalogue.snapshot.eq(SNAPSHOT) & catalogue.station_ssp.eq("ssp126")]
    table = refs.pivot(index="country", columns="tech", values="capacity_mw").reindex(columns=TECHS).fillna(0)
    table.columns = ["wind_capacity_mw", "solar_capacity_mw"]
    table["capacity_mw"] = table.sum(axis=1)
    table = table.loc[table.index.isin(names.country) & table.capacity_mw.gt(0)]
    table = table.reset_index().sort_values(["capacity_mw", "country"], ascending=[False, True])
    if not 1 <= top_k <= len(table):
        raise ValueError(f"--top-k must be between 1 and {len(table)}")
    table = table.head(top_k).copy()
    table["rank"] = np.arange(1, top_k + 1)
    table = table.merge(names.rename(columns={"name": "country_name"}), on="country", validate="one_to_one")
    totals = refs.groupby("tech").capacity_mw.sum()
    global_row = dict(country="GLOBAL", country_name="Global", rank=0,
                      capacity_mw=float(totals.sum()), wind_capacity_mw=float(totals.wind),
                      solar_capacity_mw=float(totals.solar))
    return pd.concat([pd.DataFrame([global_row]), table], ignore_index=True)[
        ["country", "country_name", "rank", "capacity_mw", "wind_capacity_mw", "solar_capacity_mw"]]


def build_metrics(catalogue, selection, path):
    chunks = []
    for chunk in pd.read_csv(path, chunksize=50000):
        keep = (chunk.snapshot.eq(SNAPSHOT) & chunk.event.eq("all") & chunk.support.eq("common")
                & chunk.country.isin(selection.country))
        chunks.append(chunk.loc[keep])
    frame = pd.concat(chunks, ignore_index=True)
    if frame.duplicated(KEYS).any():
        raise ValueError("Duplicate model/climate/deployment/country rows")
    expected = pd.MultiIndex.from_tuples(
        list(product(MODELS, selection.country, TECHS, SSPS, SSPS)), names=KEYS)
    frame["source_present"] = True
    frame = frame.set_index(KEYS).reindex(expected).reset_index()
    frame["source_present"] = frame.source_present.eq(True)
    frame["snapshot"] = SNAPSHOT
    frame["event"] = "all"
    frame["support"] = "common"
    ref = catalogue[catalogue.snapshot.eq(SNAPSHOT)].copy()
    total = ref.groupby(["tech", "station_ssp", "snapshot"], as_index=False).capacity_mw.sum()
    total["country"] = "GLOBAL"
    ref = pd.concat([ref, total], ignore_index=True).rename(columns={"capacity_mw": "catalogue_capacity_mw"})
    frame = frame.merge(ref[["country", "tech", "station_ssp", "catalogue_capacity_mw"]],
                        on=["country", "tech", "station_ssp"], how="left", validate="many_to_one")
    finite = np.isfinite(frame[["net_mwh", "normal_annual_mwh", "capacity_mw"]]).all(axis=1)
    valid = finite & frame.capacity_mw.gt(0) & frame.normal_annual_mwh.gt(0)
    ratio = frame.net_mwh / frame.capacity_mw
    check = valid & frame.R.notna()
    if not np.allclose(frame.loc[check, "R"], ratio[check], rtol=1e-10, atol=1e-8):
        raise ValueError("Source R differs from net energy / common capacity")
    frame["C_GW"] = frame.capacity_mw / 1000
    frame["L_TWh"] = frame.net_mwh / 1e6
    frame["G0_TWh"] = frame.normal_annual_mwh / 1e6
    frame["H0"] = np.where(valid, frame.normal_annual_mwh / frame.capacity_mw, np.nan)
    frame["R"] = np.where(valid, ratio, np.nan)
    frame["rho_pct"] = np.where(valid, 100 * frame.net_mwh / frame.normal_annual_mwh, np.nan)
    frame["coverage_pct"] = np.where(frame.catalogue_capacity_mw.gt(0),
                                      100 * frame.capacity_mw / frame.catalogue_capacity_mw, np.nan)
    frame["window_start"] = SNAPSHOT
    frame["window_end"] = SNAPSHOT + 9
    frame["station_source"] = frame.station_ssp.map(STATION_FILES)
    frame["sample_status"] = np.select(
        [~frame.source_present, ~finite, frame.capacity_mw.le(0), frame.normal_annual_mwh.le(0)],
        ["missing_source_row", "nonfinite_source", "no_positive_capacity", "no_positive_normal_generation"],
        default="complete")
    return frame


def contrasts(frame):
    rows = []
    for key, group in frame.groupby(["model", "country", "tech", "climate_ssp"], sort=False):
        indexed = group.set_index("station_ssp")
        a = indexed.loc["ssp126"]
        for target in SSPS[1:]:
            b = indexed.loc[target]
            row = dict(zip(["model", "country", "tech", "climate_ssp"], key))
            row.update(target_ssp=target, baseline_ssp="ssp126", snapshot=SNAPSHOT,
                       window_start=SNAPSHOT, window_end=SNAPSHOT + 9)
            for prefix, record in [("baseline", a), ("target", b)]:
                for column in ["capacity_mw", "catalogue_capacity_mw", "coverage_pct", "R", "H0", "rho_pct"]:
                    row[f"{prefix}_{column}"] = record[column]
            complete = a.sample_status == "complete" and b.sample_status == "complete"
            row["sample_status"] = "complete" if complete else "incomplete"
            row.update({metric: np.nan for metric in CONTRAST_METRICS})
            row.update(high_capacity_ssp="", low_capacity_ssp="", expansion_status="incomplete")
            if complete:
                scale = (b.capacity_mw - a.capacity_mw) * (a.R + b.R) / 2 / 1e6
                layout = (a.capacity_mw + b.capacity_mw) * (b.R - a.R) / 2 / 1e6
                delta = b.L_TWh - a.L_TWh
                row.update(scale_TWh=scale, layout_TWh=layout, delta_L_TWh=delta,
                           scale_refG0_pct=scale / a.G0_TWh * 100,
                           layout_refG0_pct=layout / a.G0_TWh * 100,
                           delta_L_refG0_pct=delta / a.G0_TWh * 100,
                           delta_H0_pct=(b.H0 / a.H0 - 1) * 100,
                           delta_R=b.R - a.R, delta_rho_pp=b.rho_pct - a.rho_pct,
                           delta_C_pct=(b.capacity_mw / a.capacity_mw - 1) * 100,
                           delta_G0_pct=(b.G0_TWh / a.G0_TWh - 1) * 100,
                           equal_generation_capacity_ratio=a.H0 / b.H0,
                           equal_generation_loss_TWh=a.G0_TWh * b.rho_pct / 100,
                           reference_loss_TWh=a.L_TWh)
                if np.isclose(a.capacity_mw, b.capacity_mw, rtol=1e-10, atol=1e-6):
                    row.update(high_capacity_ssp="equal", low_capacity_ssp="equal", expansion_status="equal_capacity")
                else:
                    sign = 1 if b.capacity_mw > a.capacity_mw else -1
                    low, high = (a, b) if sign == 1 else (b, a)
                    row.update(high_capacity_ssp=target if sign == 1 else "ssp126",
                               low_capacity_ssp="ssp126" if sign == 1 else target,
                               expansion_scale_TWh=sign * scale,
                               expansion_layout_TWh=sign * layout,
                               expansion_delta_L_TWh=sign * delta,
                               expansion_delta_H0_pct=(high.H0 / low.H0 - 1) * 100,
                               expansion_delta_R=high.R - low.R,
                               expansion_status="complete")
                    if sign * scale > 1e-12:
                        row["offset_ratio"] = -layout / scale
                        row["offset_status"] = "defined"
                    else:
                        row["offset_status"] = "nonpositive_or_negligible_scale_contribution"
            row.setdefault("offset_status", "not_applicable")
            rows.append(row)
    return pd.DataFrame(rows)


def rankings(frame):
    keys = ["country", "tech", "climate_ssp", "model"]
    rows = []
    for key, group in frame.groupby(keys, sort=False):
        for metric in ("R", "rho_pct"):
            values = group.set_index("station_ssp")[metric].reindex(SSPS)
            complete = np.isfinite(values).all() and group.sample_status.eq("complete").all()
            minimum = values.min() if complete else np.nan
            for station in SSPS:
                row = dict(zip(keys, key))
                row.update(metric=metric, station_ssp=station, value=values[station],
                           is_best=bool(complete and np.isclose(values[station], minimum, rtol=TIE_RTOL, atol=TIE_ATOL)),
                           group_complete=bool(complete), group_status="complete" if complete else "incomplete")
                rows.append(row)
    models = pd.DataFrame(rows)
    summary = []
    for key, group in models.groupby(["country", "tech", "climate_ssp", "metric", "station_ssp"], sort=False):
        row = dict(zip(["country", "tech", "climate_ssp", "metric", "station_ssp"], key))
        values = group.loc[np.isfinite(group.value), "value"]
        row.update(mean=values.mean(), minimum=values.min(), maximum=values.max(), n_models=len(values),
                   model_wins=int(group.is_best.sum()), n_comparable_models=int(group.group_complete.sum()))
        summary.append(row)
    summary = pd.DataFrame(summary)
    summary["ensemble_best"] = False
    for _, group in summary.groupby(["country", "tech", "climate_ssp", "metric"], sort=False):
        complete = len(group) == len(SSPS) and group.n_comparable_models.eq(len(MODELS)).all()
        if complete:
            summary.loc[group.index, "ensemble_best"] = np.isclose(
                group["mean"], group["mean"].min(), rtol=TIE_RTOL, atol=TIE_ATOL)
    robust = []
    for key, group in models.groupby(["country", "tech", "metric", "station_ssp"], sort=False):
        row = dict(zip(["country", "tech", "metric", "station_ssp"], key))
        available = int(group.group_complete.sum())
        wins = int(group.is_best.sum())
        sm = summary[(summary.country == key[0]) & (summary.tech == key[1])
                     & (summary.metric == key[2]) & (summary.station_ssp == key[3])]
        row.update(groups_available=available, total_groups=len(MODELS) * len(SSPS), win_groups=wins,
                   robust_best=available == 12 and wins == 12,
                   ensemble_climate_wins=int(sm.ensemble_best.sum()),
                   status="complete" if available == 12 else "incomplete")
        robust.append(row)
    return models, summary, pd.DataFrame(robust)


def max_residual(series):
    values = np.asarray(series, dtype=float)
    values = values[np.isfinite(values)]
    return float(np.max(np.abs(values))) if len(values) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=10, help="Countries ranked by SSP126 2050 combined wind + solar catalogue capacity")
    args = parser.parse_args()
    out = HERE / "outputs" / f"top{args.top_k}"
    source = out / "source_data"
    paths = {"window": OUTPUT / "loss_summary/window.csv.gz",
             "capacity": OUTPUT / "catalogues/capacity_by_country.csv",
             "countries": OUTPUT / "catalogues/countries.csv",
             "upstream_audit": ROOT / "logs/paper_figures/completion_status/final_audit.json"}
    acceptance = json.loads(paths["upstream_audit"].read_text())
    if acceptance["acceptance"]["status"] != "PASSED":
        raise ValueError("Upstream loss summary not accepted")
    catalogue = pd.read_csv(paths["capacity"])
    names = pd.read_csv(paths["countries"])
    if "TWN" in set(catalogue.country):
        raise ValueError("Country catalogue has not merged China and Taiwan")
    selection = select_countries(catalogue, names, args.top_k)
    metrics = build_metrics(catalogue, selection, paths["window"])
    caps = metrics.groupby(["country", "tech", "station_ssp"]).capacity_mw.agg(["min", "max"])
    cap_error = max_residual(caps["max"] - caps["min"])
    if cap_error is not None and cap_error > 1e-6:
        raise ValueError("Common-support capacity differs across climate/models")
    values = contrasts(metrics)
    wins_models, wins_summary, robustness = rankings(metrics)
    summary = summarize(metrics, GROUPS, METRICS)
    contrast_summary = summarize(values, ["country", "tech", "climate_ssp", "target_ssp"], CONTRAST_METRICS, agreement=True)
    residuals = {
        "R_times_capacity_minus_net_mwh": max_residual(metrics.R * metrics.capacity_mw - metrics.net_mwh),
        "R_minus_H0_times_rho": max_residual(metrics.R - metrics.H0 * metrics.rho_pct / 100),
        "scale_plus_layout_minus_delta_TWh": max_residual(values.scale_TWh + values.layout_TWh - values.delta_L_TWh),
        "expansion_closure_TWh": max_residual(values.expansion_scale_TWh + values.expansion_layout_TWh - values.expansion_delta_L_TWh),
        "normalized_closure_percentage_points": max_residual(values.scale_refG0_pct + values.layout_refG0_pct - values.delta_L_refG0_pct),
    }
    equal_r = values.equal_generation_capacity_ratio * values.target_R - values.baseline_H0 * values.target_rho_pct / 100
    residuals["equal_generation_loss_per_reference_mw"] = max_residual(equal_r)
    if any(value is not None and value > (1e-5 if name.endswith("net_mwh") else 1e-8)
           for name, value in residuals.items()):
        raise ValueError(f"Decomposition / identity residuals too large: {residuals}")
    if metrics.coverage_pct.dropna().gt(100 + 1e-6).any():
        raise ValueError("Analyzed capacity exceeds catalogue capacity")
    frames = {"selection.csv": selection, "metrics_models.csv": metrics, "metrics_summary.csv": summary,
              "contrasts_models.csv": values, "contrasts_summary.csv": contrast_summary,
              "wins_models.csv": wins_models, "wins_summary.csv": wins_summary, "robustness.csv": robustness}
    for filename, frame in frames.items():
        write_csv(source / filename, frame)
    coverage = metrics.groupby(["country", "tech", "station_ssp"], as_index=False).agg(
        capacity_mw=("capacity_mw", "first"), catalogue_capacity_mw=("catalogue_capacity_mw", "first"),
        coverage_pct=("coverage_pct", "first"), valid_rows=("sample_status", lambda x: int(x.eq("complete").sum())))
    write_csv(source / "coverage.csv", coverage)
    excluded = sorted(set(catalogue.country) - set(names.country))
    missing = metrics.loc[metrics.sample_status.ne("complete"), KEYS + ["sample_status"]]
    audit = {
        "status": "PASSED", "created_utc": datetime.now(timezone.utc).isoformat(),
        "top_k": args.top_k, "countries": selection.country.tolist(), "snapshot": SNAPSHOT,
        "window": [SNAPSHOT, SNAPSHOT + 9], "models": list(MODELS), "climate_ssps": list(SSPS),
        "station_ssps": list(SSPS), "ranking": "SSP126 2050 catalogue wind + solar capacity; fixed country list for both technologies",
        "excluded_ranking_codes": excluded, "global": "Full upstream GLOBAL including unmapped country assignments; never sum of Top-k",
        "common_support": "Within each deployment: common finite station fields across four models, three climates and ten years",
        "time_support_limitation": "Annual Loss summaries do not establish identical valid timestamps",
        "china": "China and Taiwan merged upstream; no separate TWN row",
        "station_sources": STATION_FILES,
        "metric_definitions": {"H0": "normal_annual_mwh / capacity_mw; MWh MW-1 yr-1",
            "rho_pct": "100 * net_mwh / normal_annual_mwh", "R": "net_mwh / capacity_mw; signed; MWh MW-1 yr-1",
            "equal_generation_capacity_ratio": "H0_reference / H0_target; common normal-generation target is reference G0 within each model and climate",
            "offset_ratio": "-expansion_layout_TWh / expansion_scale_TWh; defined only when scale contribution > 1e-12 TWh",
            "scale_layout": "Symmetric exact two-factor decomposition at fixed climate; capacity and loss refer to common support",
            "expansion": "Higher-capacity minus lower-capacity deployment; not a temporal growth trajectory"},
        "summary": "Compute all ratios and contrasts per model, then use unweighted four-model mean and min-max",
        "ranking_tolerance": {"rtol": TIE_RTOL, "atol": TIE_ATOL},
        "robust_best": "Best, including numerical ties, in all 12 model-by-climate groups with all three deployments available",
        "uncertainty": "Model range and sign agreement are not confidence intervals or statistical significance",
        "equal_generation_limitation": "Normal baseline generation target; proportional capacity scaling assumes fixed spatial shares and omits land, grid and cost constraints",
        "minimum_coverage_pct": float(metrics.coverage_pct.min()),
        "maximum_coverage_pct": float(metrics.coverage_pct.max()),
        "incomplete_metrics_rows": missing.to_dict("records"),
        "robustness_incomplete_rows": int(robustness.status.ne("complete").sum()),
        "fixed_capacity_max_difference_mw": cap_error, "max_absolute_residuals": residuals,
        "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths.values()},
        "script_sha256": digest(__file__), "outputs": {name: {"rows": len(frame), "sha256": digest(source / name)} for name, frame in frames.items()},
    }
    write_json(out / "data_audit.json", audit)
    print(json.dumps({"status": audit["status"], "countries": audit["countries"],
                      "metrics_rows": len(metrics), "contrast_rows": len(values),
                      "coverage_min_pct": audit["minimum_coverage_pct"],
                      "max_absolute_residuals": residuals, "output": str(out)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
