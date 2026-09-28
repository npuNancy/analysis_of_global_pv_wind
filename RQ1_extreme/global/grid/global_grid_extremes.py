"""Annual area-weighted grid exposure, spatial changes and event profiles."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import cartopy.crs as ccrs
import netCDF4
import numpy as np
import pandas as pd

from grid_common import (
    INPUT_ROOT, MODELS, SSPS, TECHS, SSP_COLOR, SSP_LABEL, EVENTS, EVENT_LABEL,
    EVENT_COLOR, SHAPEFILE, LOGGER, aggregate_combination, aggregate_rows,
    cache_dataset, configure_logging, configure_style, country_geometries,
    ensemble_table, global_patch_rows, model_title, period_ensemble, period_label,
    period_table, save_figure, select_inventory, write_json,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--ssps", nargs="+", choices=SSPS, default=list(SSPS))
    parser.add_argument("--techs", nargs="+", choices=TECHS, default=list(TECHS))
    parser.add_argument("--patches", nargs="+")
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2015, 2061)))
    parser.add_argument("--baseline-years", nargs="+", type=int, default=list(range(2015, 2025)))
    parser.add_argument("--future-years", nargs="+", type=int, default=list(range(2050, 2060)))
    parser.add_argument("--min-time-coverage", type=float, default=0.99)
    parser.add_argument("--time-chunk", type=int, default=240)
    parser.add_argument("--workers", type=int, default=min(4, int(os.environ.get("SLURM_CPUS_PER_TASK", "1"))))
    parser.add_argument("--phase", choices=("all", "aggregate", "plot"), default="all")
    parser.add_argument("--shapefile", type=Path, default=SHAPEFILE)
    args = parser.parse_args()
    args.years = sorted(set(args.years))
    args.baseline_years = sorted(set(args.baseline_years))
    args.future_years = sorted(set(args.future_years))
    if not set(args.baseline_years + args.future_years) <= set(args.years):
        parser.error("Baseline and future years must be included in --years")
    if any(y < 2015 or y > 2060 for y in args.years):
        parser.error("Source years are 2015 through 2060")
    if not 0 < args.min_time_coverage <= 1 or args.workers < 1 or args.time_chunk < 1:
        parser.error("Invalid coverage, workers or time chunk")
    for values in (args.models, args.ssps, args.techs, args.patches or []):
        if len(values) != len(set(values)):
            parser.error("Selections must not contain duplicates")
    return args


def build_tables(records, models):
    rows = []
    for record in records:
        rows.extend(global_patch_rows(record))
    annual = aggregate_rows(rows, ["model", "scenario", "tech", "year", "event"])
    ensemble = ensemble_table(annual, ["scenario", "tech", "year", "event"], models)
    return pd.concat([annual, ensemble], ignore_index=True), pd.DataFrame(rows)


def save_tables(annual, patches, args):
    periods = period_table(annual[annual.model != "ensemble_mean"], args.baseline_years, args.future_years)
    periods = pd.concat([periods, period_ensemble(periods, args.models)], ignore_index=True)
    for model in (*args.models, "ensemble_mean"):
        folder = args.output_dir / model / "csv"
        folder.mkdir(parents=True, exist_ok=True)
        annual[annual.model == model].to_csv(folder / "annual_exposure.csv", index=False)
        periods[periods.model == model].to_csv(folder / "period_changes.csv", index=False)
        decades = []
        subset = annual[annual.model == model]
        for start in (2030, 2040, 2050):
            if set(range(start, start + 10)) <= set(args.years):
                dec = subset[subset.year.between(start, start + 9)].groupby(
                    ["model", "scenario", "tech", "event"], as_index=False).agg(
                    exposure_days=("exposure_days", lambda x: x.mean() if x.notna().all() else np.nan),
                    coverage_pct=("coverage_pct", "mean"))
                dec["decade"] = start
                decades.append(dec)
        if decades:
            pd.concat(decades, ignore_index=True).to_csv(folder / "decadal_exposure.csv", index=False)
        if model != "ensemble_mean":
            patches[patches.model == model].to_csv(folder / "patch_coverage.csv", index=False)
    return periods


def plot_annual(annual, model, args):
    fig, axes = plt.subplots(1, len(args.techs), figsize=(6 * len(args.techs), 4), squeeze=False)
    for ax, tech in zip(axes.flat, args.techs):
        for ssp in args.ssps:
            data = annual[(annual.model == model) & (annual.tech == tech) &
                          (annual.scenario == ssp) & (annual.event == "any")].sort_values("year")
            ax.plot(data.year, data.exposure_days, color=SSP_COLOR[ssp], label=SSP_LABEL[ssp], lw=1.7)
            if model == "ensemble_mean":
                ax.fill_between(data.year, data.model_min, data.model_max, color=SSP_COLOR[ssp], alpha=0.15)
        ax.set(title=tech.capitalize(), xlabel="Year", ylabel="Area-weighted exposure (days/year)")
        ax.grid(axis="y", alpha=0.18)
    axes.flat[0].legend(fontsize=8)
    fig.suptitle("Any extreme event · " + model_title(model, args.models))
    fig.tight_layout()
    save_figure(fig, args.output_dir / model / "figures/annual_exposure.png")


def plot_events(annual, periods, model, args):
    fig, axes = plt.subplots(len(args.techs), len(args.ssps), figsize=(4.3 * len(args.ssps), 3.6 * len(args.techs)), squeeze=False)
    for i, tech in enumerate(args.techs):
        for j, ssp in enumerate(args.ssps):
            ax = axes[i, j]
            for event, color in zip(EVENTS[tech], EVENT_COLOR):
                data = annual[(annual.model == model) & (annual.tech == tech) &
                              (annual.scenario == ssp) & (annual.event == event)].sort_values("year")
                ax.plot(data.year, data.exposure_days, color=color, label=EVENT_LABEL[event], lw=1.2)
            ax.set(title=f"{tech.capitalize()} · {SSP_LABEL[ssp]}", xlabel="Year", ylabel="Exposure (days/year)")
            ax.grid(axis="y", alpha=0.15)
            if j == len(args.ssps) - 1:
                ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1, 1))
    fig.suptitle(f"Event-specific exposure · {model}\nEvents may overlap")
    fig.tight_layout()
    save_figure(fig, args.output_dir / model / "figures/event_trajectories.png")
    fig, axes = plt.subplots(1, len(args.techs), figsize=(6.5 * len(args.techs), 4.8), squeeze=False)
    for ax, tech in zip(axes.flat, args.techs):
        for j, ssp in enumerate(args.ssps):
            subset = periods[(periods.model == model) & (periods.tech == tech) & (periods.scenario == ssp)].set_index("event")
            values = subset.reindex(EVENTS[tech])
            offset = (j - (len(args.ssps)-1)/2) * 0.2
            ax.scatter(values.change_days, np.arange(len(EVENTS[tech])) + offset, color=SSP_COLOR[ssp], label=SSP_LABEL[ssp], s=24)
            if model == "ensemble_mean":
                ax.hlines(np.arange(len(EVENTS[tech])) + offset, values.model_min, values.model_max,
                          color=SSP_COLOR[ssp], lw=1.1)
        ax.set_yticks(np.arange(len(EVENTS[tech])), [EVENT_LABEL[e] for e in EVENTS[tech]])
        ax.axvline(0, color="0.5", lw=0.7)
        ax.set(title=tech.capitalize(), xlabel="Change in exposure (days/year)")
        ax.grid(axis="x", alpha=0.15)
    axes.flat[0].legend(fontsize=8)
    fig.suptitle(f"{period_label(args.future_years)} minus {period_label(args.baseline_years)} · {model}\nEvent-specific changes; events may overlap")
    fig.tight_layout()
    save_figure(fig, args.output_dir / model / "figures/event_changes.png")


def spatial_change(record, args):
    with cache_dataset(record) as ds:
        years = list(ds["year"][:])
        event = list(ds["event"][:]).index("any")
        before = np.stack([ds["event_days"][years.index(y), event] for y in args.baseline_years])
        after = np.stack([ds["event_days"][years.index(y), event] for y in args.future_years])
        return (ds["lat"][:], ds["lon"][:], after.mean(axis=0) - before.mean(axis=0),
                ds["domain_mask"][:] == 1, ds["cell_area_km2"][:])


def draw_maps(records, args):
    _, boundaries = country_geometries(args.shapefile)
    projection = ccrs.PlateCarree()
    lookup = {(r["model"], r["scenario"], r["tech"], r["patch"]): r for r in records}
    # Retain only two-dimensional changes, not the full time series.
    data = {k: spatial_change(v, args) for k, v in lookup.items()}
    for model in (*args.models, "ensemble_mean"):
        maps, coverage = {}, []
        for ssp in args.ssps:
            for tech in args.techs:
                panels = []
                numerator = denominator = 0.0
                for patch in args.patches:
                    contributors = args.models if model == "ensemble_mean" else [model]
                    parts = [data[(m, ssp, tech, patch)] for m in contributors]
                    lat, lon, _, domain, area = parts[0]
                    if any(not np.array_equal(p[0], lat) or not np.array_equal(p[1], lon) for p in parts[1:]):
                        raise ValueError("Model grids differ for map aggregation")
                    common_domain = np.logical_and.reduce([p[3] for p in parts])
                    delta = np.stack([p[2] for p in parts]).mean(axis=0)
                    delta[~common_domain] = np.nan
                    denominator += float(area[common_domain].sum())
                    numerator += float(area[np.isfinite(delta) & common_domain].sum())
                    order = np.argsort((lon + 180) % 360 - 180)
                    panels.append((lat, ((lon + 180) % 360 - 180)[order], delta[:, order]))
                maps[(ssp, tech)] = panels
                coverage.append({"model": model, "scenario": ssp, "tech": tech,
                                 "complete_period_area_km2": numerator, "reference_area_km2": denominator,
                                 "coverage_pct": 100*numerator/denominator if denominator else np.nan})
        finite_max = [float(np.nanmax(np.abs(p[2]))) for panel in maps.values() for p in panel if np.isfinite(p[2]).any()]
        limit = max(finite_max, default=1) or 1
        norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
        fig, axes = plt.subplots(len(args.techs), len(args.ssps),
                                 figsize=(4.6*len(args.ssps), 2.7*len(args.techs)+0.8),
                                 subplot_kw={"projection": projection}, squeeze=False)
        mesh = None
        for i, tech in enumerate(args.techs):
            for j, ssp in enumerate(args.ssps):
                ax = axes[i, j]
                ax.set_global()
                ax.add_geometries(boundaries, crs=projection, facecolor="#eeeeee", edgecolor="none", zorder=0)
                for lat, lon, delta in maps[(ssp, tech)]:
                    mesh = ax.pcolormesh(lon, lat, delta, transform=projection, shading="nearest",
                                         cmap="RdBu_r", norm=norm, rasterized=True, zorder=1)
                ax.add_geometries(boundaries, crs=projection, facecolor="none", edgecolor="#777777", linewidth=0.25, zorder=2)
                cov = next(v["coverage_pct"] for v in coverage if v["scenario"] == ssp and v["tech"] == tech)
                ax.set_title(f"{tech.capitalize()} · {SSP_LABEL[ssp]}\nValid domain area: {cov:.1f}%", fontsize=9)
        fig.subplots_adjust(left=0.02, right=0.98, top=0.82, bottom=0.18, hspace=0.24, wspace=0.03)
        cax = fig.add_axes([0.28, 0.075, 0.44, 0.025])
        fig.colorbar(mesh, cax=cax, orientation="horizontal", label="Change in any-event exposure (days/year)")
        fig.suptitle(f"{period_label(args.future_years)} minus {period_label(args.baseline_years)} · {model}", fontsize=11)
        save_figure(fig, args.output_dir / model / "figures/exposure_change_map.png")
        pd.DataFrame(coverage).to_csv(args.output_dir / model / "csv/map_coverage.csv", index=False)


def main():
    configure_logging()
    args = parse_args()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records, patches, index_hash = select_inventory(args.input_root, args.models, args.ssps, args.techs, args.patches)
    args.patches = patches
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items() if k != "phase"}
    manifest_path = args.output_dir / "cache_manifest.json"
    # Cache identity excludes concurrency knobs, but records the exact scientific scope.
    scope = {k: config[k] for k in ("models", "ssps", "techs", "patches", "years", "min_time_coverage",
                                      "baseline_years", "future_years")}
    if args.phase != "plot":
        tasks = [(r, args.years, str(args.output_dir), args.min_time_coverage, args.time_chunk) for r in records]
        if args.workers == 1:
            cached = [aggregate_combination(t) for t in tasks]
        else:
            with ProcessPoolExecutor(max_workers=args.workers, mp_context=mp.get_context("spawn")) as pool:
                cached = list(pool.map(aggregate_combination, tasks))
        manifest = {"schema_version": 1, "scope": scope, "input_index_sha256": index_hash, "baseline_years": args.baseline_years,
                    "future_years": args.future_years, "records": cached}
        write_json(manifest_path, manifest)
    else:
        manifest = json.loads(manifest_path.read_text())
        if manifest["scope"] != scope or manifest["input_index_sha256"] != index_hash:
            raise ValueError("Cached selection differs from requested input/scope")
        cached = manifest["records"]
    annual, patch_rows = build_tables(cached, args.models)
    periods = save_tables(annual, patch_rows, args)
    configure_style()
    if args.phase != "aggregate":
        for model in (*args.models, "ensemble_mean"):
            plot_annual(annual, model, args)
            plot_events(annual, periods, model, args)
        draw_maps(cached, args)
    config.update({"input_index_sha256": index_hash, "combinations": len(cached),
                   "model_range": "minimum to maximum, not confidence interval",
                   "figure_format": "png", "dpi": 300,
                   "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "phase": args.phase})
    write_json(args.output_dir / "run_config.json", config)
    LOGGER.info("Saved %d combinations to %s", len(cached), args.output_dir)


if __name__ == "__main__":
    main()
