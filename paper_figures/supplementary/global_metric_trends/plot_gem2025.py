"""Render GEM history and LCOE-2025 inventories in the global metric trend style."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from paper_figures.common.plotting import configure, export_panel_png, independent_y_ticks
from paper_figures.config import SSP_COLORS
from paper_figures.supplementary.gem_lcoe_history.plot import (
    ROOT, HERE as ORIGINAL, METRICS, FIXED_METRICS, PAIRS, TECHS,
    digest, read, select, select_fixed, fixed_capacity_models,
)

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DATA = OUT / "source_data"
ENGLISH = {
    "total_loss": "Total net generation loss",
    "unit_loss": "Net loss per unit capacity",
    "loss_fraction": "Loss / annual normal generation",
    "total_generation": "Total generation",
    "unit_generation": "Generation per unit capacity",
    "capacity": "Installed capacity",
    "exposure_total": "Capacity-weighted exposure",
    "exposure_mean": "Mean exposure duration",
    "cf": "Capacity factor",
}


def draw_panel(ax, display, tech, label, letter, metric):
    _, field, scale, ylabel, _ = metric
    history = display[display.tech.eq(tech) & display.pathway.eq("historical")].sort_values("year")
    yy = history[field].to_numpy() * scale
    ax.plot(history.year, yy, color="#111111", lw=1.3, marker="o", ms=1.8)
    fixed = metric[0].startswith("station_fixed_")
    for (_, climate), marker in zip(PAIRS, ["o", "s", "^"]):
        future = display[display.tech.eq(tech) & display.pathway.eq(climate)].sort_values("year")
        if not fixed and future.year.tolist() != [2030, 2040, 2050]:
            raise ValueError("LCOE display requires three future periods")
        style = {} if fixed else dict(marker=marker, ms=3.5, markevery=[1, 2, 3])
        ax.plot(np.r_[2025, future.year], np.r_[yy[-1], future[field].to_numpy() * scale],
                color=SSP_COLORS[climate], lw=1.15, **style)
    axes = independent_y_ticks(ax, intervals=5)
    if axes["lower"] < 0 <= axes["data_minimum"]:
        needed = axes["data_maximum"] * 1.06 / 5
        power = 10. ** np.floor(np.log10(needed))
        step = next(f * power for f in (1., 1.25, 1.5, 2., 2.5, 3., 4., 5., 6., 8., 10.)
                    if f * power >= needed)
        ticks = np.arange(6) * step
        ax.set_yticks(ticks)
        ax.set_ylim(0, ticks[-1])
        axes.update(lower=0., upper=float(ticks[-1]), step=float(step), ticks=ticks.tolist())
    ax.axvline(2025, color=".72", lw=.55, ls=":", zorder=0)
    ax.set_title(label, fontsize=9, pad=8)
    ax.text(-.11, 1.12, letter, transform=ax.transAxes, fontsize=9, fontweight="bold")
    if fixed:
        ax.set_xticks([2015, 2025, 2035, 2045, 2055])
        ax.set_xlim(2014, 2060)
        ax.set_xlabel("Year")
    else:
        capacity = metric[0] == "station_capacity"
        labels = ["2015", "2025"] + (["2030", "2040", "2050"] if capacity
                                             else ["2030s", "2040s", "2050s"])
        ax.set_xticks([2015, 2025, 2030, 2040, 2050], labels, rotation=30, ha="right")
        ax.set_xlim(2014, 2052)
        ax.set_xlabel("Year" if capacity else "Year / decade")
    ax.grid(axis="y", color=".9", lw=.45)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 5), useMathText=True)
    ax.tick_params(length=3, width=.7)
    return axes


def decorate(fig, metric, fixed, solo=False):
    name = metric[0].replace("station_fixed_", "").replace("station_", "")
    scope = "Fixed 2025 capacity" if fixed else "LCOE-2025 global stations"
    fig.suptitle(scope + ("\n" if solo else " | ") + ENGLISH[name], fontsize=9 if solo else 10, y=.97)
    fig.text(.54 if not solo else .56, .875 if not solo else .835,
             "Independent y-axis ranges; 5 intervals per panel" if not solo else "5 equal y-axis intervals",
             ha="center", fontsize=7 if not solo else 6.5, color=".4")
    capacity = name == "capacity"
    historical_label = "Historical GEM" if capacity else "ERA5-Land"
    scenario_labels = ["SSP1-2.6", "SSP2-4.5", "SSP5-6.0" if capacity else "SSP5-8.5"]
    handles = [Line2D([], [], color="#111111", lw=1.3, label=historical_label)]
    handles += [Line2D([], [], color=SSP_COLORS[c], lw=1.5, label=label,
                        marker=None if fixed else marker, ms=3.5)
                for (_, c), label, marker in zip(PAIRS, scenario_labels, ["o", "s", "^"])]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.53, .075),
               ncol=2 if solo else 4, fontsize=7 if solo else 8)
    if capacity:
        footer = ("2015–2025: annual GEM stock;", "2030 / 2040 / 2050: LCOE snapshots.")
    elif fixed:
        footer = ("2015–2025: ERA5-Land;", "2026–2059: four-GCM mean.")
    else:
        footer = ("2015–2025: annual ERA5-Land;", "Future: decadal four-GCM means.")
    fig.text(.53, .025, ("\n" if solo else " ").join(footer),
             ha="center", fontsize=6.7, color=".35")


def render(display, metrics, fixed):
    records = []
    for metric in metrics:
        name = "gem2025_" + metric[0]
        fig, axes = plt.subplots(1, 3, figsize=(240/25.4, 85/25.4))
        fig.subplots_adjust(left=.10, right=.985, bottom=.28 if fixed else .34, top=.78, wspace=.40)
        limits = []
        for ax, (tech, label), letter in zip(axes, TECHS, "abc"):
            limits.append(dict(tech=tech, **draw_panel(ax, display, tech, label, letter, metric)))
        axes[0].set_ylabel(metric[3], labelpad=7)
        decorate(fig, metric, fixed)
        complete = export_panel_png(fig, OUT/(name + ".png"))
        panels = []
        for (tech, label), letter in zip(TECHS, "abc"):
            fig, ax = plt.subplots(figsize=(105/25.4, 100/25.4))
            fig.subplots_adjust(left=.23, right=.97, bottom=.30 if fixed else .35, top=.73)
            draw_panel(ax, display, tech, label, letter, metric)
            ax.set_ylabel(metric[3], labelpad=7)
            decorate(fig, metric, fixed, solo=True)
            panels.append(export_panel_png(fig, OUT/(name + "_" + letter + ".png")))
        records.append(dict(name=name, metric=metric[0], title=metric[4],
                            family="fixed2025" if fixed else "lcoe2025",
                            field=metric[1], scale=metric[2], complete=complete,
                            panels=panels, axes=limits))
        print("Rendered", name, flush=True)
    return records


def period_tables(models, annual_display):
    """Keep historical years and average each future decade within each model."""
    numeric = [c for c in models.select_dtypes(include="number").columns if c != "year"]
    future = models[models.phase.eq("future")].copy()
    future["decade"] = future.year // 10 * 10
    keys = ["phase", "station_ssp", "climate_ssp", "model", "tech", "calendar", "pathway", "decade"]
    grouped = future.groupby(keys, sort=True)
    for key, group in grouped:
        decade = key[-1]
        if decade not in (2030, 2040, 2050) or group.year.sort_values().tolist() != list(range(decade, decade+10)):
            raise ValueError("Incomplete model decade: " + str(key))
        if group.catalogue_capacity_mw.nunique() != 1:
            raise ValueError("Catalogue capacity changes within a snapshot")
    aggregation = {c: "first" if c == "catalogue_capacity_mw" else "mean" for c in numeric}
    decadal = grouped.agg(aggregation).reset_index().rename(columns={"decade": "year"})
    decadal["period_start"] = decadal.year
    decadal["period_end"] = decadal.year + 9
    decadal["n_years"] = 10
    history = models[models.phase.eq("historical")].copy()
    history["period_start"] = history.year
    history["period_end"] = history.year
    history["n_years"] = 1
    periods = pd.concat([history, decadal], ignore_index=True)
    if len(history) != 33 or len(decadal) != 108:
        raise ValueError("Historical/model-decade matrix")
    keys = ["phase", "station_ssp", "climate_ssp", "tech", "pathway", "year",
            "period_start", "period_end", "n_years"]
    grouped = periods.groupby(keys, sort=True)
    display = grouped[numeric].agg(["mean", "min", "max"])
    display.columns = ["_".join(c) for c in display.columns]
    display = display.reset_index()
    display["n_models"] = grouped.size().to_numpy()
    if len(display) != 60 or not display.n_models.eq(np.where(display.phase.eq("historical"), 1, 4)).all():
        raise ValueError("Period ensemble matrix")
    fields = [m[1] for m in METRICS]
    if not np.isfinite(display[fields].to_numpy()).all():
        raise ValueError("Nonfinite plotted period value")
    actual = display[display.phase.eq("historical")].sort_values(["tech", "year"])[fields]
    expected = annual_display[annual_display.phase.eq("historical")].sort_values(["tech", "year"])[fields]
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True),
                                  check_dtype=False, rtol=1e-12, atol=1e-7)
    if not np.allclose(display.catalogue_capacity_mw_min, display.catalogue_capacity_mw_max):
        raise ValueError("Capacity must be a deterministic catalogue snapshot")
    return periods, display


def refresh_lcoe():
    """Render only LCOE-2025 from its accepted annual summary CSVs."""
    manifest_path = OUT/"gem2025_figure_manifest.json"
    manifest = read(manifest_path)
    frames = {}
    for name in ("gem2025_models.csv", "gem2025_display.csv"):
        path = DATA/name
        if digest(path) != manifest["sources"][name]["sha256"]:
            raise ValueError("Annual plotting source changed: " + name)
        frames[name] = pd.read_csv(path)
    models, display = period_tables(frames["gem2025_models.csv"], frames["gem2025_display.csv"])
    for name, frame in (("gem2025_period_models.csv", models), ("gem2025_period_display.csv", display)):
        frame.to_csv(DATA/name, index=False)
        manifest["sources"][name] = dict(path=str(DATA/name), rows=len(frame), sha256=digest(DATA/name))
    fixed = [image for record in manifest["figures"] if record["family"] == "fixed2025"
             for image in [record["complete"]] + record["panels"]]
    configure()
    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8})
    updated = {record["name"]: record for record in render(display, METRICS, False)}
    manifest["figures"] = [updated.get(record["name"], record) for record in manifest["figures"]]
    for image in fixed:
        if digest(OUT/image["path"]) != image["sha256"]:
            raise ValueError("Fixed-capacity PNG changed")
    manifest.update(status="NUMERIC_AND_EXPORT_PASSED", visual_review="PENDING",
                    decadal_aggregation=dict(status="PASSED", historical_years=[2015, 2025],
                        future_decades=[2030, 2040, 2050], model_rows=len(models), display_rows=len(display),
                        method="Ten-year mean within each model, then equal four-model mean; catalogue capacity uses snapshots.",
                        fixed_pngs_unchanged=len(fixed)))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print("Updated nine LCOE-2025 triptychs and 27 panels; fixed-capacity PNGs unchanged.", flush=True)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    index_path = ROOT/"runtime/authoritative_index.json"
    done = read(ROOT/"runtime/completion.json")
    if done["status"] != "COMPLETED" or digest(index_path) != done["index_sha256"]:
        raise ValueError("Unaccepted GEM climate index")
    index = read(index_path)
    summaries = {}
    for name in ("global_annual_models.csv", "global_annual_ensemble.csv"):
        record = index["summaries"][name]
        path = Path(record["path"])
        if path.stat().st_size != record["size_bytes"] or digest(path) != record["sha256"]:
            raise ValueError("Changed accepted summary " + name)
        summaries[name] = pd.read_csv(path)
    display = select(summaries["global_annual_ensemble.csv"])
    fixed_models, fixed_ensemble, checks = fixed_capacity_models(index, summaries["global_annual_models.csv"])
    fixed_display = select_fixed(display, fixed_ensemble)
    original_sources = ORIGINAL/"outputs/source_data"
    for expected, path, keys in [
        (display, original_sources/"plot_series.csv", ["pathway", "tech", "year"]),
        (fixed_models, original_sources/"fixed_capacity_models.csv", ["pathway", "model", "tech", "year"]),
        (fixed_ensemble, original_sources/"fixed_capacity_ensemble.csv", ["pathway", "tech", "year"]),
    ]:
        old = pd.read_csv(path)
        pd.testing.assert_frame_equal(expected.sort_values(keys).reset_index(drop=True),
                                      old.sort_values(keys).reset_index(drop=True),
                                      check_dtype=False, rtol=1e-10, atol=1e-7)
    model_rows = []
    published = summaries["global_annual_models.csv"]
    for pathway in ("historical", "ssp126", "ssp245", "ssp585"):
        if pathway == "historical":
            part = published[published.phase.eq("historical")].copy()
        else:
            station = dict((c, s) for s, c in PAIRS)[pathway]
            part = published[published.climate_ssp.eq(pathway) &
                (published.phase.eq("transition") |
                 (published.phase.eq("future") & published.station_ssp.eq(station)))].copy()
        part["pathway"] = pathway
        model_rows.append(part)
    tables = {
        "gem2025_models.csv": pd.concat(model_rows, ignore_index=True),
        "gem2025_display.csv": display,
        "gem2025_fixed_models.csv": fixed_models,
        "gem2025_fixed_ensemble.csv": fixed_ensemble,
        "gem2025_fixed_display.csv": fixed_display,
    }
    period_models, period_display = period_tables(tables["gem2025_models.csv"], display)
    tables["gem2025_period_models.csv"] = period_models
    tables["gem2025_period_display.csv"] = period_display
    for name, frame in tables.items():
        frame.to_csv(DATA/name, index=False)
    configure()
    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8})
    figures = render(period_display, METRICS, False) + render(fixed_display, FIXED_METRICS, True)
    manifest = dict(status="NUMERIC_AND_EXPORT_PASSED", visual_review="PENDING",
        source_index=str(index_path), index_sha256=digest(index_path),
        source_summaries=index["summaries"], original_series_comparison="PASSED",
        fixed_transition_crosscheck_rows=checks,
        sources={name: dict(path=str(DATA/name), rows=len(frame), sha256=digest(DATA/name))
                 for name, frame in tables.items()},
        figures=figures, full_figures=len(figures), independent_panels=3*len(figures))
    (OUT/"gem2025_figure_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print("Completed", len(figures), "triptychs and", 3*len(figures), "panels", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lcoe-only", action="store_true", help="Update LCOE-2025 using the accepted annual CSVs.")
    args = parser.parse_args()
    refresh_lcoe() if args.lcoe_only else main()
