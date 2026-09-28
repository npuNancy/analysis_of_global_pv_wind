"""Country grid exposure heatmaps and trajectories from annual grid caches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

GLOBAL_DIR = Path(__file__).resolve().parents[2] / "global/grid"
sys.path.insert(0, str(GLOBAL_DIR))
from grid_common import (
    SHAPEFILE, SSP_COLOR, SSP_LABEL, LOGGER, aggregate_rows, cache_dataset,
    configure_logging, configure_style, country_geometries, digest_json,
    ensemble_table, model_title, period_ensemble, period_label, period_table,
    save_figure, write_json,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
PRIORITY_COUNTRIES = (
    "China", "United States of America", "India", "Germany",
    "South Africa", "Australia", "Russia", "Brazil",
)


def rasterize_countries(lat, lon, domain, geometries):
    """Cell-centre assignment; stable first-country ownership on shared borders."""
    xx, yy = np.meshgrid((np.asarray(lon) + 180) % 360 - 180, lat)
    result = np.full(domain.shape, -1, dtype=np.int32)
    for i, geom in enumerate(geometries):
        west, south, east, north = geom.bounds
        eligible = domain & (result < 0) & (xx >= west) & (xx <= east) & (yy >= south) & (yy <= north)
        y, x = np.where(eligible)
        if len(y):
            inside = shapely.intersects_xy(geom, xx[y, x], yy[y, x])
            result[y[inside], x[inside]] = i
    return result


def country_mask(ds, record, geometries, boundary_hash, output):
    lat, lon = ds["lat"][:], ds["lon"][:]
    domain = ds["domain_mask"][:] == 1
    digest = hashlib.sha256(lat.tobytes() + lon.tobytes() + domain.tobytes() + boundary_hash.encode()).hexdigest()
    target = output / "masks" / (record["patch"] + "_" + digest[:16] + ".npz")
    if target.exists():
        with np.load(target) as cache:
            if str(cache["fingerprint"]) != digest:
                raise ValueError("Country mask fingerprint mismatch")
            return cache["country_id"]
    target.parent.mkdir(parents=True, exist_ok=True)
    ids = rasterize_countries(lat, lon, domain, geometries)
    np.savez_compressed(target, country_id=ids, fingerprint=digest)
    return ids


def reduce_countries(record, metadata, geometries, boundary_hash, output):
    rows = []
    with cache_dataset(record) as ds:
        ids = country_mask(ds, record, geometries, boundary_hash, output)
        domain = ds["domain_mask"][:] == 1
        area = ds["cell_area_km2"][:]
        # Bin zero records unassigned domain cells explicitly.
        bins = ids[domain] + 1
        weights = area[domain]
        n = len(metadata) + 1
        reference = np.bincount(bins, weights=weights, minlength=n)
        cells = np.bincount(bins, minlength=n)
        labels = [{"country": "UNASSIGNED", "country_iso3": "UNK"}, *metadata]
        events = list(ds["event"][:])
        for i, year in enumerate(ds["year"][:]):
            temporal = ds["valid_hours"][i][domain] / ds["nominal_hours"][i]
            time_area = np.bincount(bins, weights=weights * temporal, minlength=n)
            for j, event in enumerate(events):
                values = ds["event_days"][i, j][domain]
                valid = np.isfinite(values)
                numerator = np.bincount(bins[valid], weights=weights[valid] * values[valid], minlength=n)
                valid_area = np.bincount(bins[valid], weights=weights[valid], minlength=n)
                valid_cells = np.bincount(bins[valid], minlength=n)
                for k in np.flatnonzero(reference > 0):
                    rows.append({**labels[k], **{a: record[a] for a in ("model", "scenario", "tech")},
                                 "year": int(year), "event": event, "weighted_days_km2": numerator[k],
                                 "valid_area_km2": valid_area[k], "reference_area_km2": reference[k],
                                 "valid_cells": valid_cells[k], "domain_cells": cells[k],
                                 "time_area_km2": time_area[k]})
    return rows


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-output-dir", type=Path, default=GLOBAL_DIR / "outputs")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--shapefile", type=Path, default=SHAPEFILE)
    parser.add_argument("--countries-per-page", type=int, default=35)
    parser.add_argument("--top-countries", type=int, default=6,
                        help="Union the highest-ranked countries with the eight mandatory priority countries")
    args = parser.parse_args()
    if args.countries_per_page < 1 or args.top_countries < 1:
        parser.error("Country counts must be positive")
    return args


def plot_heatmaps(periods, model, tech, config, output, per_page):
    data = periods[(periods.model == model) & (periods.tech == tech) &
                   (periods.event == "any") & (periods.country != "UNASSIGNED")]
    change = data.pivot(index="country", columns="scenario", values="change_days").reindex(columns=config["ssps"])
    coverage = data.pivot(index="country", columns="scenario", values="future_coverage_pct").reindex(columns=config["ssps"])
    change = change.loc[change.notna().any(axis=1)]
    if change.empty:
        LOGGER.warning("No finite country changes: %s/%s", model, tech)
        return
    order = change.mean(axis=1).sort_values(ascending=False).index
    change, coverage = change.reindex(order), coverage.reindex(order)
    limit = float(np.nanmax(np.abs(change))) or 1
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad("#eeeeee")
    covmap = plt.get_cmap("Greys").copy()
    covmap.set_bad("#eeeeee")
    for start in range(0, len(change), per_page):
        part = change.iloc[start:start + per_page]
        cov = coverage.reindex(part.index)
        fig, axes = plt.subplots(1, 2, figsize=(9, max(4, len(part) * 0.24 + 2.3)),
                                 gridspec_kw={"width_ratios": [1.25, 1]}, sharey=True, squeeze=False)
        left, right = axes.flat
        im = left.imshow(part.to_numpy(), cmap=cmap, vmin=-limit, vmax=limit, aspect="auto")
        cm = right.imshow(cov.to_numpy(), cmap=covmap, vmin=0, vmax=100, aspect="auto")
        left.set_yticks(np.arange(len(part)), part.index, fontsize=7.5)
        left.set_title("Exposure change (days/year)")
        right.set_title("Future valid domain area (%)")
        for ax in (left, right):
            ax.set_xticks(np.arange(len(config["ssps"])), [SSP_LABEL[s] for s in config["ssps"]], rotation=25, ha="right")
            ax.tick_params(axis="both", length=0)
        short_page = len(part) < 10
        fig.subplots_adjust(left=0.29, right=0.98, top=0.80 if short_page else 0.90,
                            bottom=0.27 if short_page else 0.14, wspace=0.22)
        for artist, ax in ((im, left), (cm, right)):
            position = ax.get_position()
            cax = fig.add_axes([position.x0, 0.08 if short_page else 0.05, position.width, 0.018])
            fig.colorbar(artist, cax=cax, orientation="horizontal")
        fig.suptitle(f"{tech.capitalize()} · {model}\n{period_label(config['future_years'])} minus {period_label(config['baseline_years'])}", fontsize=11)
        save_figure(fig, output / model / "figures" / f"country_change_heatmap_{tech}_{start // per_page + 1:02d}.png")


def select_trajectory_countries(periods, tech, count):
    selection = periods[(periods.model == "ensemble_mean") & (periods.tech == tech) &
                        (periods.event == "any") & (periods.country != "UNASSIGNED")]
    ranking = selection.groupby("country")["change_days"].apply(lambda s: s.abs().max()).dropna().sort_values(ascending=False)
    return list(dict.fromkeys([*PRIORITY_COUNTRIES, *ranking.head(count).index]))


def plot_trajectories(annual, countries, model, tech, config, output):
    if not countries:
        return
    cols = min(3, len(countries))
    rows = (len(countries) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4.1*cols, 3*rows), squeeze=False)
    for ax, country in zip(axes.flat, countries):
        has_data = False
        for scenario in config["ssps"]:
            data = annual[(annual.model == model) & (annual.tech == tech) & (annual.scenario == scenario) &
                          (annual.country == country) & (annual.event == "any")].sort_values("year")
            has_data = has_data or bool(np.isfinite(data.exposure_days).any())
            ax.plot(data.year, data.exposure_days, color=SSP_COLOR[scenario], label=SSP_LABEL[scenario], lw=1.5)
            if model == "ensemble_mean":
                ax.fill_between(data.year, data.model_min, data.model_max, color=SSP_COLOR[scenario], alpha=0.15)
        if not has_data:
            ax.text(0.5, 0.5, "No valid data in selected scope", transform=ax.transAxes,
                    ha="center", va="center", fontsize=8, color="0.4")
        ax.set(title=country, xlabel="Year", ylabel="Exposure (days/year)")
        ax.grid(axis="y", alpha=0.15)
    for ax in list(axes.flat)[len(countries):]:
        ax.set_visible(False)
    axes.flat[0].legend(fontsize=7)
    fig.suptitle(f"{tech.capitalize()} · {model_title(model, config['models'])}\nPriority countries and largest absolute SSP changes")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    save_figure(fig, output / model / "figures" / f"country_trajectories_{tech}.png")


def main():
    configure_logging()
    args = parse_args()
    manifest_path = args.grid_output_dir / "cache_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    scope = manifest["scope"]
    records = manifest["records"]
    expected = {(m, s, t, p) for m in scope["models"] for s in scope["ssps"]
                for t in scope["techs"] for p in scope["patches"]}
    actual = [(r["model"], r["scenario"], r["tech"], r["patch"]) for r in records]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Incomplete or duplicate global cache manifest")
    config = {**scope, "baseline_years": manifest["baseline_years"], "future_years": manifest["future_years"]}
    boundary_hash = hashlib.sha256(b"".join(args.shapefile.with_suffix(s).read_bytes() for s in (".shp", ".shx", ".dbf"))).hexdigest()
    metadata, geometries = country_geometries(args.shapefile)
    # Aggregate each patch before concatenation to bound memory for the full inventory.
    partials = []
    for i, record in enumerate(records, 1):
        patch_rows = reduce_countries(record, metadata, geometries, boundary_hash, args.output_dir)
        if patch_rows:
            partials.append(aggregate_rows(
                patch_rows, ["country", "country_iso3", "model", "scenario", "tech", "year", "event"]))
        if i % 25 == 0 or i == len(records):
            LOGGER.info("Country summaries %d/%d", i, len(records))
    if not partials:
        raise ValueError("Selected caches contain no domain grid cells")
    annual = aggregate_rows(pd.concat(partials, ignore_index=True),
                            ["country", "country_iso3", "model", "scenario", "tech", "year", "event"])
    means = ensemble_table(annual, ["country", "country_iso3", "scenario", "tech", "year", "event"], scope["models"])
    periods = period_table(annual, config["baseline_years"], config["future_years"], country=True)
    periods = pd.concat([periods, period_ensemble(periods, scope["models"], country=True)], ignore_index=True)
    annual = pd.concat([annual, means], ignore_index=True)
    configure_style()
    trajectory_countries = {tech: select_trajectory_countries(periods, tech, args.top_countries) for tech in scope["techs"]}
    for model in (*scope["models"], "ensemble_mean"):
        folder = args.output_dir / model / "csv"
        folder.mkdir(parents=True, exist_ok=True)
        data = annual[annual.model == model]
        data[data.country != "UNASSIGNED"].to_csv(folder / "country_annual_exposure.csv", index=False)
        data[data.country == "UNASSIGNED"].to_csv(folder / "unassigned_domain.csv", index=False)
        period = periods[(periods.model == model) & (periods.country != "UNASSIGNED")]
        period.to_csv(folder / "country_period_changes.csv", index=False)
        for tech in scope["techs"]:
            plot_heatmaps(periods, model, tech, config, args.output_dir, args.countries_per_page)
            plot_trajectories(annual, trajectory_countries[tech], model, tech, config, args.output_dir)
    write_json(args.output_dir / "run_config.json", {
        **config, "grid_manifest": str(manifest_path.resolve()),
        "grid_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "shapefile": str(args.shapefile.resolve()), "boundary_sha256": boundary_hash,
        "country_assignment": "cell centre intersects polygon; first sorted country on shared boundaries",
        "coverage_denominator": "country-assigned domain area within selected patches",
        "priority_countries": list(PRIORITY_COUNTRIES),
        "top_countries": args.top_countries,
        "trajectory_countries": trajectory_countries, "figure_format": "png", "dpi": 300,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    })
    LOGGER.info("Saved country grid analysis to %s", args.output_dir)


if __name__ == "__main__":
    main()
