"""Meeting diagnostics: annual weather trends and four-model agreement."""
from pathlib import Path
import json
import itertools
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from paper_figures.config import ROOT, MODELS, SSPS
from paper_figures.common.io import digest, write_json

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/meeting_grid"
SOURCE = OUT / "source_data"
COLORS = dict(zip(SSPS, ["#1d3b6f", "#b77c19", "#9e1b1b"]))
PANELS = [
 ("Wind-event union", [("wind", "all")]),
 ("PV-event union", [("solar", "all")]),
 ("High temperature", [("wind", "high_temp")]),
 ("High wind", [("wind", "high_wind")]),
 ("Hot and humid", [("wind", "hot_humid")]),
 ("Icing: two product time axes", [("wind", "icing"), ("solar", "icing")]),
 ("Low wind resource", [("wind", "low_resource")]),
 ("Cold + high wind", [("solar", "cold_highwind")]),
 ("Freezing-rain proxy", [("solar", "freezing_rain")]),
 ("High humidity", [("solar", "high_humidity")]),
 ("Low irradiance resource", [("solar", "low_resource")]),
 ("Rainstorm", [("solar", "rainstorm")]),
]
WEATHER_PANELS = [
 ("High temperature", [("wind", "high_temp")]),
 ("High wind", [("wind", "high_wind")]),
 ("Hot and humid", [("wind", "hot_humid")]),
 ("Icing", [("wind", "icing")]),
 ("Low wind resource", [("wind", "low_resource")]),
 ("Cold + high wind", [("solar", "cold_highwind")]),
 ("Freezing-rain proxy", [("solar", "freezing_rain")]),
 ("High humidity", [("solar", "high_humidity")]),
 ("Low irradiance resource", [("solar", "low_resource")]),
 ("Rainstorm", [("solar", "rainstorm")]),
]
BANDS = ["60S-30S", "30S-0", "0-30N", "30N-60N", "60N-90N"]
BAND_LABELS = ["60–30°S", "30–0°S", "0–30°N", "30–60°N", "60–90°N"]
REGIONAL = [("High humidity", "solar", "high_humidity"),
            ("Icing: wind time axis", "wind", "icing"),
            ("Icing: PV time axis", "solar", "icing"),
            ("Low irradiance resource", "solar", "low_resource")]

def require(value, msg):
    if not value:
        raise ValueError(msg)

def summarize(frame, keys, value):
    return frame.groupby(keys, as_index=False).agg(
        mean=(value, "mean"), minimum=(value, "min"), maximum=(value, "max"),
        n_models=(value, "size"),
        positive_models=(value, lambda x: int((x > 1e-6).sum())),
        negative_models=(value, lambda x: int((x < -1e-6).sum())))

def plot_panel(ax, number, annual, panels=PANELS):
    title, series = panels[number]
    for j, (tech, event) in enumerate(series):
        sub = annual[annual.tech.eq(tech) & annual.event.eq(event)]
        for ssp in SSPS:
            a = sub[sub.climate_ssp.eq(ssp)].sort_values("year")
            ax.plot(a.year, a["mean"], color=COLORS[ssp], lw=1.0,
                    ls="-" if j == 0 else ":", label=ssp.upper())
            if len(series) == 1:
                ax.fill_between(a.year, a.minimum, a.maximum, color=COLORS[ssp],
                                alpha=.10, linewidth=0)
    ax.set_title(title, loc="left", fontsize=7.5, pad=5)
    ax.text(-.15, 1.05, chr(97 + number), transform=ax.transAxes, fontweight="bold", fontsize=9)
    ax.set_xlim(2015, 2060)
    ax.set_xticks([2020, 2040, 2060])
    ax.set_xlabel("Year")
    ax.set_ylabel("Exposure (day yr⁻¹)")
    ax.grid(axis="y", lw=.4, color="#e2e6ea")
    ax.tick_params(length=2, width=.5, labelsize=6.5)
    if len(series) == 2:
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi + .30 * (hi - lo))
        ax.text(.02, .96, "Solid: wind time axis\nDotted: PV time axis",
                transform=ax.transAxes, va="top", fontsize=5.7)

def plot_region(ax, number, contrasts):
    title, tech, event = REGIONAL[number]
    a = contrasts[contrasts.tech.eq(tech) & contrasts.event.eq(event) &
                  contrasts.scope.eq("latitude") & contrasts.region.isin(BANDS)]
    stats = summarize(a, ["region"], "difference").set_index("region")
    for i, band in enumerate(BANDS):
        r = stats.loc[band]
        ax.hlines(i, r.minimum, r.maximum, color="#7b8a9c", lw=1)
        vals = a[a.region.eq(band)].set_index("model").loc[list(MODELS)].difference
        for mi, v in enumerate(vals):
            ax.scatter(v, i + (mi - 1.5) * .075, s=14,
                       marker=["o", "s", "^", "v"][mi], color="#8b9dae", linewidths=0)
        ax.scatter(r["mean"], i, marker="D", color="#183c66", s=16, zorder=4)
        agreement = max(r.positive_models, r.negative_models)
        ax.annotate(f"{int(agreement)}/4", (r.maximum, i), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=6)
    ax.axvline(0, color="#4d5660", lw=.6)
    ax.set_yticks(range(5), BAND_LABELS)
    ax.invert_yaxis()
    ax.set_xlabel("SSP585 − SSP126 (day yr⁻¹)")
    ax.set_title(title, loc="left", fontsize=8)
    ax.text(-.18, 1.05, chr(97 + number), transform=ax.transAxes, fontsize=10, fontweight="bold")
    ax.margins(x=.30)
    if event == "icing":
        ax.set_xlim(-3.5, 3.5)
    ax.grid(axis="x", color="#e2e6ea", lw=.4)
    ax.tick_params(length=2, width=.5)

def save(fig, name):
    fig.savefig(OUT / (name + ".png"), dpi=600, facecolor="white", bbox_inches="tight")
    plt.close(fig)

def weather_types_trends():
    """Render one source series per weather type from accepted annual summaries."""
    annual_path = SOURCE / "annual_models.csv"
    summary_path = SOURCE / "annual_summary.csv"
    annual = pd.read_csv(annual_path)
    summary = pd.read_csv(summary_path)
    definitions = pd.read_csv(SOURCE / "event_definitions.csv")
    mapping = pd.DataFrame([
        dict(panel=chr(97 + i), weather_type=title, tech=series[0][0], event=series[0][1],
             reference_variable="uas" if series[0][0] == "wind" else "rsds",
             source_selection="native temperature/humidity time axis" if series[0][1] == "icing"
                              else "published event definition")
        for i, (title, series) in enumerate(WEATHER_PANELS)])
    require(len(mapping) == 10 and not mapping.duplicated(["tech", "event"]).any(),
            "Ten unique physical weather types required")
    mapping = mapping.merge(definitions, on=["tech", "event"], validate="one_to_one")
    selected = mapping.merge(annual, on=["tech", "event"], validate="one_to_many")
    selected_summary = mapping.merge(summary, on=["tech", "event"], validate="one_to_many")
    require(len(selected) == 10 * 4 * 3 * 46, "Weather-type annual matrix incomplete")
    require(len(selected_summary) == 10 * 3 * 46, "Weather-type summary matrix incomplete")
    require(selected_summary.n_models.eq(4).all(), "Four models per weather-type curve")
    require(selected[selected.event.eq("icing")].tech.eq("wind").all(),
            "Icing must use only the native temperature/humidity time axis")
    mapping_path = SOURCE / "weather_type_source_mapping.csv"
    mapping.to_csv(mapping_path, index=False)
    selected.to_csv(SOURCE / "weather_type_annual_models.csv", index=False)
    selected_summary.to_csv(SOURCE / "weather_type_annual_summary.csv", index=False)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": .6, "legend.frameon": False})
    handles = [plt.Line2D([], [], color=COLORS[s], label=s.upper()) for s in SSPS]
    fig, axes = plt.subplots(5, 2, figsize=(183/25.4, 246/25.4))
    for i, ax in enumerate(axes.flat):
        plot_panel(ax, i, selected_summary, panels=WEATHER_PANELS)
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(.54, 1.0))
    fig.subplots_adjust(left=.10, right=.99, top=.962, bottom=.055, hspace=.72, wspace=.36)
    save(fig, "meeting_weather_types_trends")
    for i in range(10):
        fig, ax = plt.subplots(figsize=(88/25.4, 72/25.4))
        plot_panel(ax, i, selected_summary, panels=WEATHER_PANELS)
        fig.legend(handles=handles, loc="upper center", ncol=3,
                   bbox_to_anchor=(.52, 1.04), fontsize=6)
        fig.subplots_adjust(left=.20, right=.98, top=.82, bottom=.20)
        save(fig, "meeting_weather_types_trends_" + chr(97 + i))
    (OUT / "meeting_weather_types_caption.txt").write_text(
        "Annual global exposure to ten physical weather types, 2015–2060. "
        "Each type has one curve per SSP: equal-weight mean across four climate models, "
        "with minimum–maximum model ranges. Exposure is area-weighted over 1,526,295 "
        "supported native land cells; one exposure day is 24 cumulative hours. "
        "Icing uses only the native temperature/humidity (uas reference) timestamps. "
        "The alternative rsds-reference icing product remains in the product-comparison figure. "
        "Other event definitions retain their published reference timestamps, recorded in "
        "weather_type_source_mapping.csv. Low wind and low irradiance use their own "
        "model- and SSP-specific 2015–2024 anomaly baselines. A unified cross-technology "
        "HIW union has not been computed; category durations cannot be summed to obtain it. "
        "The shaded ranges are not confidence intervals.\n", encoding="utf-8")
    metadata_path = OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    figures = sorted(OUT.glob("meeting_weather_types_trends*.png"))
    new_paths = {str(p) for p in figures}
    metadata["figures"] = [x for x in metadata.get("figures", []) if x["path"] not in new_paths]
    metadata["figures"] += [dict(path=str(p), sha256=digest(p)) for p in figures]
    metadata["code_sha256"] = digest(Path(__file__))
    metadata["weather_types"] = dict(
        status="PASSED", n_types=10, n_model_rows=len(selected), n_summary_rows=len(selected_summary),
        years=[2015, 2060], models=MODELS, scenarios=SSPS, dpi=600,
        icing_reference="native temperature/humidity timestamps, wind/uas product",
        unified_hiw_union_computed=False, original_product_comparison_preserved=True,
        source_mapping=dict(path=str(mapping_path), sha256=digest(mapping_path)),
        inputs=[dict(path=str(p), sha256=digest(p)) for p in [annual_path, summary_path]])
    write_json(metadata_path, metadata)
    print("PASSED weather types", len(figures), "PNGs", len(selected), "model rows", flush=True)

def high_latitude_cf_evidence():
    """Audit existing native CF summaries as a resource co-occurrence diagnostic."""
    import hashlib
    import netCDF4

    cf_source = BASE / "outputs/source_data/country_cf_grid_patches.csv.gz"
    cf_audit_path = BASE / "outputs/country_cf_data_audit.json"
    cf_audit = json.loads(cf_audit_path.read_text())
    require(cf_audit["status"] == "PASSED", "Native CF source audit failed")
    source_record = next(x for x in cf_audit["source_data"] if x["path"] == str(cf_source))
    require(digest(cf_source) == source_record["sha256"], "Native CF summary hash differs")
    prepare_path = BASE / "prepare_country_cf.py"
    require(digest(prepare_path) == cf_audit["prepare_code_sha256"], "CF preparation code differs")
    patches = [f"R01C{i:02d}" for i in range(1, 13)]
    checks = [x for x in cf_audit["grid_patch_checks"]
              if x["tech"] == "solar" and x["patch"] in patches]
    require(len(checks) == 12 and all(x["common_cells"] == x["domain_cells"] for x in checks),
            "High-latitude CF common support differs from the published domain")
    n_cells = sum(x["common_cells"] for x in checks)
    require(n_cells == 381790, "Unexpected high-latitude native CF support")
    coordinates = []
    longitude = []
    for patch in patches:
        path = BASE / "outputs/country_cf_cache/solar" / patch / "BCC-CSM2-MR/ssp126/grid.npz"
        with np.load(path) as cache:
            lat, lon = cache["lat"], cache["lon"]
        require(len(lat) == 301 and np.allclose(lat, np.arange(600, 901) / 10),
                "CF patch does not precisely cover 60-90N")
        require(len(lon) == 300 and np.allclose(np.diff(lon), .1), "CF longitude spacing differs")
        longitude.extend(np.mod(lon, 360).tolist())
        checksum = hashlib.sha256(lat.tobytes() + lon.tobytes()).hexdigest()
        coordinates.append(dict(patch=patch, latitude_min=float(lat.min()), latitude_max=float(lat.max()),
                                longitude_min=float(lon.min()), longitude_max=float(lon.max()),
                                n_lat=len(lat), n_lon=len(lon), coordinate_sha256=checksum, cache=str(path)))
    require(np.allclose(np.sort(longitude), np.arange(3600) / 10),
            "High-latitude CF patches overlap or omit longitude cells")
    source_manifest = BASE / "outputs/country_cf_cache/solar/R01C01/BCC-CSM2-MR/ssp126/sources.json"
    record = next(x for x in json.loads(source_manifest.read_text()) if x["dataset"] == "cf_grid")
    with netCDF4.Dataset(record["path"]) as ds:
        variable = ds["solar_cf"]
        require(variable.dimensions == ("time", "lat", "lon") and variable.units == "1",
                "Expected the regular native-grid solar_cf product")
        variable_record = dict(name=variable.name, dimensions=list(variable.dimensions),
                               units=variable.units, long_name=variable.long_name, dtype=str(variable.dtype),
                               source_path=record["path"], dataset_variables=list(ds.variables),
                               source_manifest=str(source_manifest), source_manifest_sha256=digest(source_manifest))
    raw = pd.read_csv(cf_source)
    selected = raw[raw.tech.eq("solar") & raw.patch.isin(patches)].copy()
    require(not selected.duplicated(["model", "climate_ssp", "snapshot", "patch", "country"]).any(),
            "Duplicate CF summary entries")
    keys = ["model", "climate_ssp", "snapshot"]
    models = selected.groupby(keys, as_index=False).agg(
        cf_sum=("cf_sum", "sum"), n_cells=("n_cells", "sum"),
        minimum_annual_coverage=("minimum_annual_coverage", "min"))
    require(len(models) == 24 and models.n_cells.eq(n_cells).all(), "CF matrix or support incomplete")
    require(models.minimum_annual_coverage.eq(1).all(), "CF valid-time coverage is incomplete")
    models["mean_cf"] = models.cf_sum / models.n_cells
    models["window_start"] = models.snapshot
    models["window_end"] = models.snapshot + 9
    models["latitude_min"] = 60.0
    models["latitude_max"] = 90.0
    models["weighting"] = "equal native-grid-cell weights"
    models["unit"] = "1"
    levels_path = BASE / "outputs/ssp_grid/levels_models.csv.gz"
    events = pd.read_csv(levels_path)
    events = events[events.tech.eq("solar") & events.event.eq("low_resource") &
                    events.scope.eq("latitude") & events.region.eq("60N-90N") &
                    events.snapshot.isin([2030, 2050])]
    require(len(events) == 24 and events.n_cells.eq(n_cells).all(), "Event support counts differ")
    summary = models.groupby(["climate_ssp", "snapshot"], as_index=False).agg(
        mean=("mean_cf", "mean"), minimum=("mean_cf", "min"), maximum=("mean_cf", "max"),
        n_models=("model", "size"))
    require(summary.n_models.eq(4).all(), "Four CF models per summary required")
    contrast = models.pivot(index=["model", "snapshot"], columns="climate_ssp", values="mean_cf")
    contrast["difference_585_minus_126"] = contrast.ssp585 - contrast.ssp126
    contrast = contrast.reset_index()
    paths = []
    for name, frame in [("high_latitude_cf_models", models), ("high_latitude_cf_summary", summary),
                        ("high_latitude_cf_contrasts", contrast)]:
        path = SOURCE / (name + ".csv")
        frame.to_csv(path, index=False)
        paths.append(path)
    current = contrast[contrast.snapshot.eq(2050)]
    means = models[models.snapshot.eq(2050)].groupby("climate_ssp").mean_cf.mean()
    audit = dict(
        status="PASSED", product="regular native-grid capacity factor", variable=variable_record,
        loss_cf_normal_counterfactual_baseline_used=False,
        latitude=[60, 90], longitude="[0,360) with 0.1-degree spacing; all twelve R01 patches",
        coordinates=coordinates, support=dict(
            n_cells=n_cells, common_cells_equal_domain_cells=True,
            common_across="four models, three SSPs, both 2030s and 2050s",
            minimum_annual_valid_time_fraction=1.0, all_country_labels_included=True,
            event_latitude_n_cells=n_cells,
            event_support_comparison="Cell counts agree; no additional pointwise cross-product mask audit.",
            patch_checks=checks),
        spatial_weighting="Arithmetic mean over supported native grid-cell centres, without area weighting",
        temporal_weighting="Within-year mean over all valid three-hour CF samples, then equal mean of ten annual means",
        ensemble_weighting="Equal weights across four climate models",
        source=dict(path=str(cf_source), sha256=digest(cf_source), source_rows=len(selected),
                    audit_path=str(cf_audit_path), audit_sha256=digest(cf_audit_path),
                    preparation_path=str(prepare_path), preparation_sha256=digest(prepare_path),
                    event_support_path=str(levels_path), event_support_sha256=digest(levels_path)),
        years=[[2030, 2039], [2050, 2059]],
        result_2050s=dict(ssp_means=means.to_dict(),
                         difference_585_minus_126_mean=float(current.difference_585_minus_126.mean()),
                         difference_min=float(current.difference_585_minus_126.min()),
                         difference_max=float(current.difference_585_minus_126.max()),
                         negative_models=int((current.difference_585_minus_126 < 0).sum())),
        interpretation="Higher low-irradiance-event exposure and lower annual mean regular PV CF coexist under SSP585 versus SSP126. This is not causal attribution.",
        limitations=["CF also responds to temperature and is not rsds",
                     "The CF statistic uses equal grid-cell weights; the event statistic uses cell-area weights",
                     "No monthly or seasonal high-latitude rsds or low-resource-event distribution was found in the inspected small summaries",
                     "Mean, variance, persistence and anomaly-baseline contributions have not been separated"],
        outputs=[dict(path=str(p), sha256=digest(p)) for p in paths],
        code_sha256=digest(Path(__file__)))
    audit_path = OUT / "high_latitude_cf_audit.json"
    write_json(audit_path, audit)
    metadata_path = OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["code_sha256"] = digest(Path(__file__))
    metadata["high_latitude_cf"] = dict(status="PASSED", audit_path=str(audit_path),
                                       audit_sha256=digest(audit_path), n_cells=n_cells,
                                       interpretation="Supporting co-occurrence evidence only",
                                       result_2050s=audit["result_2050s"])
    write_json(metadata_path, metadata)
    report_path = OUT / "analysis.txt"
    if report_path.exists():
        report = report_path.read_text()
        heading = "高纬低光的辅助资源证据"
        paragraph = (
            heading + "\n"
            f"已有常规CF产品的60–90°N全年平均solar_cf：2050s SSP126为{means['ssp126']:.9f}，"
            f"SSP245为{means['ssp245']:.9f}，SSP585为{means['ssp585']:.9f}；"
            f"585−126为{current.difference_585_minus_126.mean():.9f}，4/4下降。\n"
            "12个R01 patch坐标精确覆盖该纬带全部经度，381790个共同有效原生域格点，年度有效时间覆盖100%。"
            "该数值为各格点全年三小时CF均值，再平均十个年份及四模式，空间采用格点等权；"
            "来源变量为常规CF产品solar_cf，不是Loss的cf_normal反事实基线。\n"
            "低光暴露增加与平均光伏CF下降同时存在，仅构成共现证据。CF包含温度影响且不等于rsds；"
            "这里的格点等权与主文事件面积权重不同，尚未分离均值、方差、持续性及异常基线贡献。"
            "详见high_latitude_cf_audit.json及source_data/high_latitude_cf_*.csv。\n\n")
        if heading in report:
            first = report.index(heading)
            last = report.index("\n\n", first) + 2
            report = report[:first] + paragraph + report[last:]
        else:
            report = report.replace("路径差与时间趋势不能混用\n",
                                    paragraph + "路径差与时间趋势不能混用\n", 1)
        report_path.write_text(report)
    print("PASSED high-latitude CF", len(models), "model rows", audit["result_2050s"], flush=True)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    files = [ROOT / f"RQ1_extreme/global/grid/outputs/{m}/csv/annual_exposure.csv" for m in MODELS]
    files += [BASE / "outputs/ssp_grid/levels_models.csv.gz",
              BASE / "outputs/ssp_grid/contrasts_models.csv.gz",
              BASE / "outputs/ssp_grid/event_definitions.json"]
    annual = pd.concat([pd.read_csv(p) for p in files[:4]], ignore_index=True)
    annual = annual.rename(columns={"scenario": "climate_ssp"})
    annual["event"] = annual.event.replace({"any": "all"})
    keys = ["tech", "model", "climate_ssp", "year", "event"]
    require(not annual.duplicated(keys).any(), "Duplicated annual observations")
    require(annual.groupby([k for k in keys if k != "model"]).size().eq(4).all(), "Four models")
    require(annual.coverage_pct.eq(100).all(), "Annual spatial support incomplete")
    require(np.allclose(annual.valid_area_km2, annual.valid_area_km2.iloc[0]), "Area changes")
    require(annual.valid_cells.eq(1526295).all(), "Native cell count changes")
    require(np.isfinite(annual.exposure_days).all(), "Missing exposure")
    levels = pd.read_csv(files[4])
    contrasts = pd.read_csv(files[5])
    period = annual[annual.year.between(2030, 2059)].copy()
    period["snapshot"] = period.year // 10 * 10
    pkeys = ["tech", "model", "climate_ssp", "snapshot", "event"]
    means = period.groupby(pkeys).exposure_days.mean()
    ref = levels[levels.scope.eq("global") & levels.event.ne("overlap_correction")].set_index(pkeys).days_per_year
    error = float((means - ref).abs().max())
    require(len(means) == 468 and error < 1e-5, "Annual/window reproduction")
    summary = summarize(annual, ["tech", "climate_ssp", "year", "event"], "exposure_days")
    # Linear slopes are descriptive; no significance test treats model-years as independent.
    rows = []
    for start, stop in [(2015, 2060), (2030, 2059)]:
        for ident, g in annual[annual.year.between(start, stop)].groupby(
                ["tech", "model", "climate_ssp", "event"]):
            slope = np.polyfit(g.year - start, g.exposure_days, 1)[0] * 10
            rows.append(dict(zip(["tech", "model", "climate_ssp", "event"], ident),
                             start_year=start, end_year=stop, slope_days_per_decade=slope))
    slopes = pd.DataFrame(rows)
    trend_summary = summarize(slopes, ["tech", "climate_ssp", "event", "start_year", "end_year"],
                              "slope_days_per_decade")
    paired = contrasts[contrasts.high.eq("ssp585") & contrasts.low.eq("ssp126") &
                       contrasts.scope.isin(["global", "latitude"]) &
                       contrasts.event.ne("overlap_correction")].copy()
    pair_summary = summarize(paired, ["tech", "scope", "region", "snapshot", "event"], "difference")

    contribution = contrasts[contrasts.high.eq("ssp585") & contrasts.low.eq("ssp126") &
                             contrasts.event.ne("overlap_correction")].copy()
    area_keys = ["tech", "model", "snapshot", "event"]
    global_area = contribution[contribution.scope.eq("global")][area_keys + ["area_km2"]].rename(
                    columns={"area_km2": "global_area_km2"})
    contribution = contribution.merge(global_area, on=area_keys, validate="many_to_one")
    contribution["global_contribution_days"] = contribution.difference * contribution.area_km2 / contribution.global_area_km2
    check = contribution.groupby(area_keys + ["scope"]).global_contribution_days.sum().unstack("scope")
    require(np.allclose(check.country, check["global"]) and np.allclose(check.latitude, check["global"]),
            "Regional contribution conservation")
    contribution.to_csv(SOURCE / "regional_contribution_models.csv", index=False)
    summarize(contribution, ["tech", "scope", "region", "snapshot", "event"], "global_contribution_days").to_csv(
              SOURCE / "regional_contributions.csv", index=False)
    old = levels[levels.scope.isin(["global", "latitude"]) & levels.event.ne("overlap_correction")]
    endpoint = old.pivot(index=["tech", "scope", "region", "model", "climate_ssp", "event"],
                         columns="snapshot", values="days_per_year")
    endpoint["difference"] = endpoint[2050] - endpoint[2030]
    endpoint = endpoint.reset_index()
    endpoint_summary = summarize(endpoint, ["tech", "scope", "region", "climate_ssp", "event"], "difference")
    for name, frame in [("annual_models", annual), ("annual_summary", summary),
                        ("trend_models", slopes), ("trend_summary", trend_summary),
                        ("ssp_contrasts_models", paired), ("ssp_contrasts", pair_summary),
                        ("endpoint_models", endpoint), ("endpoint_summary", endpoint_summary)]:
        frame.to_csv(SOURCE / (name + ".csv"), index=False)
    definitions = json.loads(files[-1].read_text())["records"]
    drows = []
    for tech in ["wind", "solar"]:
        r = next(x for x in definitions if x["tech"] == tech)
        for event, definition in r["event_definitions"].items():
            if event != "dust":
                drows.append(dict(tech=tech, event=event, definition=definition,
                                 baseline="model- and SSP-specific 2015–2024" if event == "low_resource" else "absolute threshold"))
    pd.DataFrame(drows).to_csv(SOURCE / "event_definitions.csv", index=False)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": .6, "legend.frameon": False})
    fig, axes = plt.subplots(4, 3, figsize=(183/25.4, 220/25.4))
    for i, ax in enumerate(axes.flat):
        plot_panel(ax, i, summary)
    handles = [plt.Line2D([], [], color=COLORS[s], label=s.upper()) for s in SSPS]
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(.53, 1.005))
    fig.subplots_adjust(left=.09, right=.99, top=.955, bottom=.055, hspace=.77, wspace=.48)
    save(fig, "meeting_grid_annual_trends")
    for i in range(12):
        fig, ax = plt.subplots(figsize=(88/25.4, 72/25.4))
        plot_panel(ax, i, summary)
        fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(.52, 1.04), fontsize=6)
        fig.subplots_adjust(left=.20, right=.98, top=.82, bottom=.20)
        save(fig, "meeting_grid_annual_trends_" + chr(97 + i))
    model_handles = [plt.Line2D([], [], ls="", marker=["o", "s", "^", "v"][i],
                               color="#8b9dae", markersize=3, label=m)
                     for i, m in enumerate(MODELS)]
    selected = paired[paired.snapshot.eq(2050)]
    fig, axes = plt.subplots(2, 2, figsize=(183/25.4, 126/25.4))
    for i, ax in enumerate(axes.flat):
        plot_region(ax, i, selected)
    fig.legend(handles=model_handles, loc="lower center", ncol=4, fontsize=5.8,
               bbox_to_anchor=(.55, -.02))
    fig.subplots_adjust(left=.12, right=.99, top=.94, bottom=.15, wspace=.42, hspace=.65)
    save(fig, "meeting_grid_latitude_contrasts")
    for i in range(4):
        fig, ax = plt.subplots(figsize=(94/25.4, 70/25.4))
        plot_region(ax, i, selected)
        fig.legend(handles=model_handles, loc="lower center", ncol=2, fontsize=5.4,
                   bbox_to_anchor=(.58, -.02))
        fig.subplots_adjust(left=.22, right=.98, top=.85, bottom=.25)
        save(fig, "meeting_grid_latitude_contrasts_" + chr(97 + i))
    (OUT / "caption.txt").write_text(
        "Global grid annual exposure, 2015–2060. Mean and minimum–maximum across four climate models; "
        "native-cell area weighting over 1,526,295 cells. One exposure day equals 24 cumulative hours, "
        "not one calendar day with an event. Annual summaries reproduce accepted 2030s–2050s values. "
        "Icing is shown on both existing product time axes, with no averaging between technologies. "
        "Wind and PV unions refer to their own applicable event sets; a technology-independent union "
        "cannot be reconstructed from these marginal summaries. Low resource uses each model/SSP's "
        "own 2015–2024 anomaly baseline. Latitudinal contrasts use 2050–2059; diamonds are means, small "
        "symbols are individual models, lines are ranges. Counts indicate direction agreement, not significance. "
        "There is no valid common support south of 60°S. No raw relative-humidity histogram is inferred "
        "from binary events. Slopes are descriptive changes per decade.\n", encoding="utf-8")
    write_json(OUT / "metadata.json", dict(
        status="PASSED", window_reproduction_max_error_days=error,
        models=MODELS, scenarios=SSPS, years=[2015, 2060], n_native_cells=1526295,
        area_km2=float(annual.valid_area_km2.iloc[0]),
        minimum_time_coverage_pct=float(annual.time_coverage_pct.min()),
        inputs=[dict(path=str(p), sha256=digest(p)) for p in files],
        code_sha256=digest(Path(__file__)),
        figures=[dict(path=str(p), sha256=digest(p)) for p in sorted(OUT.glob("meeting_grid_*.png"))],
        limitations=["No unified cross-technology event union", "No humidity field distribution in binary-event summaries",
                     "Icing raw-array reproduction is a small-sample audit; see icing_sampling_audit.json for source and global 2050s coverage evidence"],
        contract=dict(claim="SSP and temporal responses vary by weather type and latitude; model agreement is explicit.",
                      archetype="quantitative grid", backend="python", format="PNG", dpi=600)))
    weather_types_trends()
    high_latitude_cf_evidence()
    print("PASSED", OUT, "annual/window max error", error, flush=True)
    print(pair_summary[(pair_summary.snapshot == 2050) & (pair_summary.scope == "global")].to_string(index=False))
    print(trend_summary[(trend_summary.start_year == 2015) & trend_summary.event.isin(["low_resource","high_humidity","icing"])].to_string(index=False))

if __name__ == "__main__":
    main()
