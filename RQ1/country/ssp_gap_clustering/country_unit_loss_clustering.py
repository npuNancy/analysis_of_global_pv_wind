"""Hierarchical clustering of countries by SSP585-minus-SSP126 unit-loss gap curves.

Reads the same annual station NetCDF files as RQ1/global, maps each station to a
country through utils/country_patch_mapping (lon/lat join per snapshot year),
aggregates per-country unit-capacity loss (net annual loss / installed capacity)
for ssp126 and ssp585, and Ward-clusters the 30-year gap trajectories. Each
model and the equal-weight model mean produce three figures per technology:
cluster trajectories with member ranges, the country gap heatmap with cluster
separators, and cluster event-composition stacked bars. Figures are PNG only;
importing this module does not read inputs or draw figures.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import multiprocessing as mp
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import xarray as xr
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import pdist, squareform

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "utils") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "utils"))

OUTPUT_DIR = PACKAGE_DIR / "outputs"
LOSS_ROOT = PROJECT_ROOT / "data/loss_outputs"
MAPPING_DIR = PROJECT_ROOT / "utils/country_patch_mapping/generated"
MODELS = ("CANESM5", "MPI-ESM1-2-HR", "MRI-ESM2-0", "BCC-CSM2-MR")
COMPARE_SSPS = ("ssp126", "ssp585")
TECHS = ("wind", "solar")
SNAPSHOTS = (2030, 2040, 2050)
SNAPSHOT_YEARS = 10
ANALYSIS_YEARS = {snapshot: tuple(range(snapshot, snapshot + SNAPSHOT_YEARS))
                  for snapshot in SNAPSHOTS}
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp585": "SSP5-8.5"}
SSP_BAR_LABEL = {"ssp126": "1-2.6", "ssp585": "5-8.5"}
TECH_LABEL = {"wind": "Wind", "solar": "Solar"}
EVENT_LABEL = {
    "low_resource": "Low resource", "high_temp": "High temperature",
    "high_wind": "High wind", "hot_humid": "Hot-humid", "icing": "Icing",
    "rainstorm": "Rainstorm", "cold_highwind": "Cold-high wind",
    "freezing_rain": "Freezing rain", "high_humidity": "High humidity",
}
EVENT_COLOR = dict(zip(EVENT_LABEL, [
    "#3b6fb6", "#d95f02", "#b2182b", "#e78ac3", "#67a9cf",
    "#1b9e77", "#7570b3", "#80cdc1", "#66a61e",
]))
TECH_EVENTS = {
    "wind": ("low_resource", "high_temp", "high_wind", "hot_humid", "icing"),
    "solar": ("low_resource", "icing", "rainstorm", "cold_highwind",
              "freezing_rain", "high_humidity"),
}
COVERAGE_COLUMN = "normal_all_generation_mwh_all"
UNIT_COLUMN = "unit_capacity_loss_mwh_per_mw_year"
GAP_COLUMN = "gap_ssp585_minus_ssp126"
UNIT_LABEL = "Unit-capacity loss (MWh MW$^{-1}$ yr$^{-1}$)"
GAP_LABEL = "SSP5-8.5 minus SSP1-2.6 gap (MWh MW$^{-1}$ yr$^{-1}$)"
CLUSTER_COLORS = ("#1d3b6f", "#b64342", "#42949e", "#9a4d8e",
                  "#d08b32", "#5f7f4f")
EVENT_SNAPSHOT = 2050
LOGGER = logging.getLogger("rq1.country_unit_loss_clustering")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def configure_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "legend.frameon": False,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })


def normalize_scenario(value: str) -> str:
    value = str(value).lower()
    return "ssp585" if value == "ssp560" else value


def read_patch_manifest(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    patches = sorted(payload["patches"])
    if payload.get("active_patch_count") != 47 or len(patches) != 47:
        raise ValueError(f"Expected 47 active patches: {path}")
    return patches


def scenario_directory(root: Path, model: str, scenario: str) -> Path:
    candidates = [root / model / scenario]
    if scenario == "ssp585":
        candidates.append(root / model / "ssp560")
    found = [path for path in candidates if path.is_dir()]
    if len(found) != 1:
        raise ValueError(f"Expected exactly one scenario directory: {candidates}")
    return found[0]


def task_manifest_path(task_dir: Path) -> Path:
    normal = task_dir / "manifest.json"
    if normal.is_file():
        return normal
    markers = sorted(task_dir.glob("manifest.json.*"))
    if len(markers) != 1:
        raise FileNotFoundError(
            f"Expected manifest.json or one manifest marker in {task_dir}; found {markers}"
        )
    return markers[0]


def task_snapshots(manifest: dict, manifest_path: Path) -> list[dict]:
    if manifest.get("status") == "SKIPPED_NO_STATIONS":
        if manifest.get("station_count", 0) != 0:
            raise ValueError(f"Skipped task has non-zero station_count: {manifest_path}")
        return [{"snapshot_year": snapshot, "status": "SKIPPED_NO_STATIONS",
                 "station_count": 0} for snapshot in SNAPSHOTS]
    snapshots = manifest.get("snapshots")
    if snapshots is None:
        snapshots = [{"snapshot_year": snapshot, "status": "COMPLETED"}
                     for snapshot in manifest.get("snapshot_years", SNAPSHOTS)]
    return snapshots


def load_country_lookup(mapping_dir: Path, scenario: str, tech: str,
                        year: int) -> pd.Series:
    """Country lookup keyed by (lon converted to [-180,180), lat), rounded to 3 dp."""
    table = pd.read_csv(mapping_dir / f"stations_{scenario}.csv",
                        usecols=["year", "type", "lon", "lat", "country"])
    subset = table[table["year"].eq(year) & table["type"].eq(tech)]
    if subset.empty:
        raise ValueError(f"Empty station mapping: {scenario}/{tech}/{year}")
    lon180 = ((subset["lon"].to_numpy(dtype=float) + 180.0) % 360.0) - 180.0
    key = pd.MultiIndex.from_arrays(
        [np.round(lon180, 3), np.round(subset["lat"].to_numpy(dtype=float), 3)])
    lookup = pd.Series(subset["country"].to_numpy(), index=key)
    return lookup[~lookup.index.duplicated(keep="first")]


def map_countries(ds: xr.Dataset, lookup: pd.Series, path: Path) -> np.ndarray:
    lon = ds.lon.to_numpy().astype(float)
    lat = ds.lat.to_numpy().astype(float)
    key = pd.MultiIndex.from_arrays([np.round(lon, 3), np.round(lat, 3)])
    countries = lookup.reindex(key).to_numpy()
    unmatched = int(pd.isna(countries).sum())
    if unmatched:
        raise ValueError(f"{unmatched} stations unmatched to countries: {path}")
    return countries.astype(str)


def load_model_unit(
    model: str, scenario: str, tech: str, loss_root: Path, patches: list[str],
    mapping_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-country annual aggregates (all-event and per-event) for one unit."""
    records, event_records = [], []
    status_root = scenario_directory(loss_root / "task_status", model, scenario)
    result_root = scenario_directory(loss_root / "generation_loss", model, scenario)
    lookups: dict[int, pd.Series] = {}
    for patch in patches:
        manifest_path = task_manifest_path(status_root / patch / tech)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {"model": model, "patch": patch, "tech": tech}
        if any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError(f"Unexpected task metadata: {manifest_path}")
        if normalize_scenario(manifest["scenario"]) != scenario:
            raise ValueError(f"Scenario mismatch: {manifest_path}")
        snapshots = task_snapshots(manifest, manifest_path)
        if sorted(item["snapshot_year"] for item in snapshots) != list(SNAPSHOTS):
            raise ValueError(f"Incomplete snapshot coverage: {manifest_path}")
        for item in snapshots:
            if item["status"] == "SKIPPED_NO_STATIONS":
                continue
            if item["status"] != "COMPLETED":
                raise ValueError(f"Incomplete snapshot: {manifest_path}")
            snapshot = item["snapshot_year"]
            folder = result_root / patch / str(snapshot) / tech
            for year in ANALYSIS_YEARS[snapshot]:
                path = folder / f"{tech}_generation_loss_station_{year}.nc"
                required = [
                    "station_id", "capacity_mw", "lon", "lat", COVERAGE_COLUMN,
                    *[name for event in ("all", *TECH_EVENTS[tech])
                      for name in (f"net_generation_loss_mwh_{event}",)],
                ]
                with xr.open_dataset(path, cache=False) as source:
                    attrs = dict(source.attrs)
                    ds = source[required].load()
                expected_attrs = {
                    "model": model, "tech": tech, "patch_id": patch,
                    "snapshot_year": snapshot, "analysis_year": year,
                    "analysis_scheme": "center-k", "analysis_k": 5,
                    "source": "global_bcsd_patch",
                }
                if any(attrs.get(k) != v for k, v in expected_attrs.items()):
                    raise ValueError(f"Unexpected result metadata: {path}")
                if normalize_scenario(attrs["scenario"]) != scenario:
                    raise ValueError(f"Scenario mismatch: {path}")
                if set(json.loads(attrs["supported_events"])) != set(TECH_EVENTS[tech]):
                    raise ValueError(f"Unexpected event categories: {path}")
                capacity = ds.capacity_mw.to_numpy().astype(float)
                covered = finite_vector(ds, COVERAGE_COLUMN, path) > 0
                if snapshot not in lookups:
                    lookups[snapshot] = load_country_lookup(
                        mapping_dir, scenario, tech, snapshot)
                countries = map_countries(ds, lookups[snapshot], path)
                countries = countries[covered]
                capacity = capacity[covered]
                loss = finite_vector(ds, "net_generation_loss_mwh_all", path)[covered]
                frame = pd.DataFrame({
                    "country": countries, "net_loss_mwh": loss,
                    "capacity_mw": capacity,
                })
                country = frame.groupby("country", as_index=False).sum(
                    numeric_only=True)
                country["scenario"] = scenario
                country["tech"] = tech
                country["snapshot_year"] = snapshot
                country["analysis_year"] = year
                country["n_stations"] = (
                    pd.Series(countries).value_counts().reindex(
                        country["country"]).to_numpy())
                records.append(country)
                for event in TECH_EVENTS[tech]:
                    event_loss = finite_vector(
                        ds, f"net_generation_loss_mwh_{event}", path)[covered]
                    event_frame = pd.DataFrame({
                        "country": countries, "net_loss_mwh": event_loss})
                    event_country = event_frame.groupby(
                        "country", as_index=False).sum(numeric_only=True)
                    event_country["scenario"] = scenario
                    event_country["tech"] = tech
                    event_country["snapshot_year"] = snapshot
                    event_country["analysis_year"] = year
                    event_country["event"] = event
                    event_records.append(event_country)
                del ds
                gc.collect()
    LOGGER.info("Read %s / %s / %s", model, scenario, tech)
    return (pd.concat(records, ignore_index=True) if records else pd.DataFrame(),
            pd.concat(event_records, ignore_index=True) if event_records else pd.DataFrame())


def finite_vector(ds: xr.Dataset, name: str, path: Path) -> np.ndarray:
    variable = ds[name]
    values = variable.to_numpy().astype(float)
    if variable.dims != ("station",) or not np.isfinite(values).all():
        raise ValueError(f"Invalid station vector {name}: {path}")
    return values


def load_model_unit_worker(task: tuple) -> tuple[str, str, str, pd.DataFrame, pd.DataFrame]:
    configure_logging()
    model, scenario, tech, loss_root, patches, mapping_dir = task
    annual, events = load_model_unit(model, scenario, tech, loss_root, patches, mapping_dir)
    return model, scenario, tech, annual, events


def country_unit_loss(annual: pd.DataFrame) -> pd.DataFrame:
    """Decade-mean per-country unit-capacity loss for the two compare SSPs.

    Countries spanning several patches arrive as one row per patch-year; merge
    patches first so each country-year is a single record before the window check.
    """
    per_year = annual.groupby(
        ["country", "scenario", "tech", "snapshot_year", "analysis_year"],
        as_index=False).agg(
        net_loss_mwh=("net_loss_mwh", "sum"),
        capacity_mw=("capacity_mw", "sum"),
        n_stations=("n_stations", "sum"))
    per_year[UNIT_COLUMN] = np.where(
        per_year["capacity_mw"] > 0,
        per_year["net_loss_mwh"] / per_year["capacity_mw"], np.nan)
    keys = ["country", "scenario", "tech", "snapshot_year"]
    grouped = per_year.groupby(keys, as_index=False).agg(
        unit_loss=(UNIT_COLUMN, "mean"), n_years=(UNIT_COLUMN, "count"),
        capacity_mw=("capacity_mw", "mean"))
    incomplete = grouped[grouped["n_years"] != SNAPSHOT_YEARS]
    if not incomplete.empty:
        raise ValueError("Incomplete decade windows in country aggregation")
    return grouped


def build_feature_matrix(decade: pd.DataFrame, tech: str) -> tuple[list[str], np.ndarray, pd.DataFrame]:
    """Gap trajectories for countries complete in both SSPs and all snapshots."""
    subset = decade[decade["tech"].eq(tech)]
    wide = subset.pivot_table(index="country", columns=["scenario", "snapshot_year"],
                              values="unit_loss", aggfunc="first")
    expected = pd.MultiIndex.from_product([COMPARE_SSPS, SNAPSHOTS])
    wide = wide.reindex(columns=expected)
    eligible = wide.notna().all(axis=1)
    complete = wide.loc[eligible].sort_index()
    if len(complete) < 4:
        raise ValueError(f"{tech}: only {len(complete)} complete countries; need >= 4")
    features = (complete["ssp585"].to_numpy(dtype=float)
                - complete["ssp126"].to_numpy(dtype=float))
    return complete.index.astype(str).tolist(), features, complete


def silhouette_score(features: np.ndarray, labels: np.ndarray) -> float:
    distance = squareform(pdist(features, metric="euclidean"))
    scores = np.zeros(len(features), dtype=float)
    for index, label in enumerate(labels):
        same = np.flatnonzero(labels == label)
        same = same[same != index]
        if len(same) == 0:
            scores[index] = 0.0
            continue
        a = float(distance[index, same].mean())
        other_means = [float(distance[index, labels == other].mean())
                       for other in np.unique(labels) if other != label]
        b = min(other_means)
        scores[index] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(scores.mean())


def choose_partition(features: np.ndarray, *, k_min: int, k_max: int,
                     min_cluster_size: int) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    tree = linkage(features, method="ward", metric="euclidean", optimal_ordering=True)
    rows, partitions = [], {}
    upper = min(k_max, len(features) - 1)
    for requested_k in range(k_min, upper + 1):
        labels = fcluster(tree, requested_k, criterion="maxclust")
        counts = pd.Series(labels).value_counts()
        actual_k = int(counts.size)
        valid = actual_k == requested_k and int(counts.min()) >= min_cluster_size
        score = silhouette_score(features, labels) if valid else np.nan
        rows.append({"requested_k": requested_k, "actual_k": actual_k,
                     "minimum_cluster_size": int(counts.min()),
                     "silhouette_score": score, "eligible": valid})
        if valid:
            partitions[requested_k] = labels
    scores = pd.DataFrame(rows)
    valid_scores = scores.dropna(subset=["silhouette_score"])
    if valid_scores.empty:
        relaxed = []
        for requested_k in range(k_min, upper + 1):
            labels = fcluster(tree, requested_k, criterion="maxclust")
            if int(pd.Series(labels).value_counts().size) != requested_k:
                continue
            relaxed.append((requested_k, silhouette_score(features, labels), labels))
        if not relaxed:
            raise ValueError("No valid hierarchical partition candidates")
        best_k, _, best_labels = max(relaxed, key=lambda item: (item[1], -item[0]))
        scores["relaxed_min_cluster_size"] = True
        scores.loc[scores["requested_k"].eq(best_k), "eligible"] = True
        partitions[best_k] = best_labels
        return partitions[best_k], tree, scores
    scores["relaxed_min_cluster_size"] = False
    best_k = int(valid_scores.sort_values(
        ["silhouette_score", "requested_k"], ascending=[False, True]
    ).iloc[0]["requested_k"])
    return partitions[best_k], tree, scores


def reorder_labels(features: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Number clusters by mean gap from high to low."""
    means = {label: float(features[labels == label, :].mean()) for label in np.unique(labels)}
    mapping = {old: new for new, old in enumerate(
        sorted(means, key=lambda label: means[label], reverse=True), start=1)}
    return np.asarray([mapping[label] for label in labels], dtype=int)


def align_labels(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    labels = sorted(np.unique(reference))
    matrix = np.zeros((len(labels), len(labels)), dtype=int)
    for i, ref_label in enumerate(labels):
        for j, cand_label in enumerate(labels):
            matrix[i, j] = int(np.sum((reference == ref_label) & (candidate == cand_label)))
    rows, columns = linear_sum_assignment(-matrix)
    mapping = {labels[column]: labels[row] for row, column in zip(rows, columns)}
    return np.asarray([mapping[label] for label in candidate], dtype=int)


def estimate_stability(features: np.ndarray, labels: np.ndarray, *,
                       n_bootstrap: int, noise_scale: float, seed: int) -> np.ndarray:
    if n_bootstrap <= 0:
        return np.full(len(features), np.nan)
    rng = np.random.default_rng(seed)
    scale = np.std(features, axis=0, ddof=1)
    positive = scale[scale > 0]
    fallback = float(np.median(positive)) if len(positive) else 1.0
    scale = np.where(scale > 0, scale, fallback)
    matches = np.zeros(len(features), dtype=int)
    n_clusters = len(np.unique(labels))
    for _ in range(n_bootstrap):
        perturbed = features + rng.normal(0.0, noise_scale * scale, size=features.shape)
        candidate = fcluster(linkage(perturbed, method="ward"), n_clusters,
                             criterion="maxclust")
        candidate = align_labels(labels, candidate)
        matches += candidate == labels
    return matches / n_bootstrap


def build_assignments(regions: list[str], features: np.ndarray, labels: np.ndarray,
                      stability: np.ndarray, wide: pd.DataFrame, *, model: str,
                      tech: str) -> pd.DataFrame:
    rows = []
    for index, region in enumerate(regions):
        row = {
            "model": model, "country": region, "tech": tech,
            "cluster": int(labels[index]),
            "assignment_stability": stability[index],
        }
        for snapshot_index, snapshot in enumerate(SNAPSHOTS):
            row[f"gap_{snapshot}"] = features[index, snapshot_index]
            for scenario in COMPARE_SSPS:
                row[f"{scenario}_{snapshot}"] = float(wide.loc[region, (scenario, snapshot)])
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_clusters(assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cluster, group in assignments.groupby("cluster", sort=True):
        row = {
            "model": group["model"].iloc[0], "tech": group["tech"].iloc[0],
            "cluster": int(cluster), "cluster_label": f"C{cluster}",
            "n_countries": len(group),
            "countries": ";".join(sorted(group["country"])),
            "mean_assignment_stability": group["assignment_stability"].mean(),
        }
        for snapshot in SNAPSHOTS:
            row[f"gap_{snapshot}_mean"] = group[f"gap_{snapshot}"].mean()
            row[f"gap_{snapshot}_min"] = group[f"gap_{snapshot}"].min()
            row[f"gap_{snapshot}_max"] = group[f"gap_{snapshot}"].max()
        rows.append(row)
    return pd.DataFrame(rows)


def save_figure(fig: plt.Figure, output: Path) -> None:
    fig.savefig(output, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_cluster_trajectories(assignments: pd.DataFrame, output: Path) -> None:
    """Cluster mean gap curves with member range bands."""
    configure_style()
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    handles = []
    for cluster, group in assignments.groupby("cluster", sort=True):
        color = CLUSTER_COLORS[(int(cluster) - 1) % len(CLUSTER_COLORS)]
        matrix = group[[f"gap_{year}" for year in SNAPSHOTS]].to_numpy(dtype=float)
        years = np.asarray(SNAPSHOTS)
        ax.fill_between(years, matrix.min(axis=0), matrix.max(axis=0),
                        color=color, alpha=0.18, linewidth=0, zorder=1)
        for row in matrix:
            ax.plot(years, row, color=color, lw=0.6, alpha=0.25, zorder=2)
        ax.plot(years, matrix.mean(axis=0), "-o", color=color, lw=2.0, ms=4, zorder=4,
                label=f"C{cluster} (n={len(group)})")
        handles.append((int(cluster), len(group)))
    ax.axhline(0, color="0.45", lw=0.8, ls="--", zorder=3)
    ax.set_xticks(SNAPSHOTS, [f"{year}s" for year in SNAPSHOTS])
    ax.set_ylabel(GAP_LABEL)
    ax.set_xlabel("Decade")
    ax.grid(axis="y", alpha=.2)
    ax.legend(loc="best", fontsize=8)
    title = "Cluster means (bold) with member ranges (shading)"
    if "n_models" in assignments:
        title += "; equal-weight mean of 4 models"
    ax.set_title(title, loc="left", fontsize=9)
    save_figure(fig, output)


def plot_country_heatmap(assignments: pd.DataFrame, tree: np.ndarray, output: Path) -> None:
    """Country gap heatmap ordered by cluster then dendrogram leaves."""
    configure_style()
    leaf_regions = [assignments.iloc[index]["country"] for index in leaves_list(tree)]
    order = (assignments.assign(_leaf=assignments["country"].map(
        {region: i for i, region in enumerate(leaf_regions)}))
        .sort_values(["cluster", "_leaf"]))
    heat = order[[f"gap_{year}" for year in SNAPSHOTS]].to_numpy(dtype=float)
    limit = max(1.0, float(np.nanmax(np.abs(heat))))
    fig, ax = plt.subplots(figsize=(4.4, max(6.0, 0.24 * len(order) + 1.6)))
    image = ax.imshow(heat, cmap="RdBu_r", aspect="auto", interpolation="nearest",
                      norm=TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit))
    ax.set_xticks(np.arange(len(SNAPSHOTS)), [f"{year}s" for year in SNAPSHOTS])
    labels = [f"C{row.cluster}  {row.country}" for row in order.itertuples()]
    ax.set_yticks(np.arange(len(order)), labels)
    ax.tick_params(axis="y", length=0, labelsize=7)
    for tick, cluster in zip(ax.get_yticklabels(), order["cluster"]):
        tick.set_color(CLUSTER_COLORS[(int(cluster) - 1) % len(CLUSTER_COLORS)])
    cluster_values = order["cluster"].to_numpy()
    boundaries = np.flatnonzero(cluster_values[1:] != cluster_values[:-1]) + 1.5
    for edge in boundaries:
        ax.axhline(edge, color="black", lw=2.0)
    ax.set_xticks(np.arange(len(SNAPSHOTS)) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(order)) - 0.5, minor=True)
    ax.grid(which="minor", color="white", lw=0.6)
    ax.tick_params(which="minor", length=0)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.03)
    colorbar.set_label(GAP_LABEL, fontsize=7.5)
    ax.set_title("Country SSP585–SSP126 gap by decade", loc="left", fontsize=9)
    save_figure(fig, output)


def event_composition_by_cluster(
    annual_events: pd.DataFrame, assignments: pd.DataFrame,
    *, exclude_low_resource: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """2050s positive event-loss shares per cluster and SSP, plus all-country mean shares.

    Cluster shares are loss-weighted within each cluster × SSP positive pool.
    The all-country reference averages country-internal shares equally.
    With ``exclude_low_resource`` the low-resource event is dropped and the
    pools renormalize over the remaining events.
    """
    tech = assignments["tech"].iloc[0]
    events = annual_events[annual_events["tech"].eq(tech)]
    if exclude_low_resource:
        events = events[~events["event"].eq("low_resource")]
    snapshot_years = ANALYSIS_YEARS[EVENT_SNAPSHOT]
    decade = (events[events["analysis_year"].isin(snapshot_years)]
              .groupby(["country", "scenario", "event"], as_index=False)
              .agg(net_loss_mwh_per_year=("net_loss_mwh", "mean")))
    decade = decade.merge(
        assignments[["country", "cluster"]], on="country", how="inner",
        validate="many_to_one")
    decade["positive_net_loss_mwh_per_year"] = decade["net_loss_mwh_per_year"].clip(lower=0)
    order = [event for event in EVENT_LABEL
             if event in TECH_EVENTS[tech] and event in set(decade["event"])]
    full_index = pd.MultiIndex.from_product(
        [sorted(decade["cluster"].unique()), COMPARE_SSPS],
        names=["cluster", "scenario"])
    full_columns = pd.Index(order, name="event")

    cluster_total = decade.groupby(["cluster", "scenario"])[
        "positive_net_loss_mwh_per_year"].transform("sum")
    decade["cluster_share"] = np.where(
        cluster_total > 0,
        decade["positive_net_loss_mwh_per_year"] / cluster_total, np.nan)
    clusters = (decade.pivot_table(index=["cluster", "scenario"], columns="event",
                                   values="cluster_share", aggfunc="sum")
                .reindex(index=full_index, columns=full_columns).fillna(0.0))
    row_sums = clusters.sum(axis=1)
    if not np.allclose(row_sums[np.isfinite(row_sums) & (row_sums > 0)], 1.0,
                       atol=1e-9):
        raise AssertionError("Cluster event shares must sum to one per cluster x SSP")

    country_total = decade.groupby(["country", "scenario"])[
        "positive_net_loss_mwh_per_year"].transform("sum")
    decade["country_share"] = np.where(
        country_total > 0,
        decade["positive_net_loss_mwh_per_year"] / country_total, np.nan)
    all_mean = (decade.pivot_table(index=["country", "scenario"], columns="event",
                                   values="country_share", aggfunc="first")
                .reindex(columns=full_columns).fillna(0.0).groupby(level="scenario").mean())
    if not np.allclose(all_mean.sum(axis=1), 1.0, atol=1e-9):
        raise AssertionError("All-country mean shares must sum to one per SSP")
    return clusters, all_mean, order


def plot_event_composition(clusters: pd.DataFrame, all_mean: pd.DataFrame,
                           events: list[str], tech: str, output: Path,
                           *, exclude_low_resource: bool = False) -> None:
    """Left: all-country mean (two bars, ssp126/ssp585). Right: per cluster (two bars each)."""
    configure_style()
    suffix = " (excl. low resource)" if exclude_low_resource else ""
    cluster_ids = sorted({index[0] for index in clusters.index})
    fig, axes = plt.subplots(
        1, 2, figsize=(3.2 + 1.6 * len(cluster_ids) + 1.2, 4.6),
        gridspec_kw={"width_ratios": [1.0, len(cluster_ids)]})
    right_positions = []
    right_labels = []
    for cluster_index, cluster in enumerate(cluster_ids):
        for scenario_index, scenario in enumerate(COMPARE_SSPS):
            right_positions.append(cluster_index * 2.6 + scenario_index)
            right_labels.append(SSP_BAR_LABEL[scenario])
    left_positions = np.arange(len(COMPARE_SSPS))
    for ax, positions, labels, table, group_label in (
        (axes[0], left_positions, [SSP_BAR_LABEL[s] for s in COMPARE_SSPS],
         all_mean, "All countries"),
        (axes[1], np.asarray(right_positions), right_labels,
         clusters, None),
    ):
        bottoms = np.zeros(len(positions))
        for event in events:
            values = []
            if group_label is not None:
                for scenario in COMPARE_SSPS:
                    values.append(float(table.loc[scenario, event])
                                  if event in table.columns else 0.0)
            else:
                for cluster in cluster_ids:
                    for scenario in COMPARE_SSPS:
                        try:
                            values.append(float(table.loc[(cluster, scenario), event]))
                        except KeyError:
                            values.append(0.0)
            values_array = np.nan_to_num(np.asarray(values), nan=0.0)
            ax.bar(positions, values_array * 100.0, bottom=bottoms * 100.0, width=0.82,
                   color=EVENT_COLOR[event], edgecolor="white", linewidth=0.3,
                   label=EVENT_LABEL[event])
            bottoms += values_array
        ax.set_xticks(positions, labels)
        if group_label is not None:
            ax.set_title(f"{group_label} mean{suffix}", loc="left", fontsize=9,
                         fontweight="bold")
        else:
            for cluster_index, cluster in enumerate(cluster_ids):
                center = cluster_index * 2.6 + 0.5
                ax.text(center, -0.16, f"C{cluster}", transform=ax.get_xaxis_transform(),
                        ha="center", va="top", fontweight="bold", fontsize=9)
            ax.set_title(f"By cluster{suffix}", loc="left", fontsize=9, fontweight="bold")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Positive event-loss pool share (%)")
        ax.grid(axis="y", alpha=.25)
        ax.set_axisbelow(True)
    handles = [Patch(facecolor=EVENT_COLOR[event], label=EVENT_LABEL[event])
               for event in events]
    axes[1].legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.02),
                   fontsize=7.5, ncol=min(3, len(handles)))
    save_figure(fig, output)


def resolve_worker_count(requested: int | None, task_count: int) -> int:
    if requested is not None:
        if requested < 1:
            raise ValueError("--workers must be at least 1")
        return min(requested, task_count)
    slurm_cpus = os.environ.get("SLURM_CPUS_PER_TASK", "")
    if slurm_cpus.isdigit() and int(slurm_cpus) > 0:
        available = int(slurm_cpus)
    else:
        available = min(os.cpu_count() or 1, 4)
    return max(1, min(available, task_count))


def load_model(model: str, loss_root: Path, patches: list[str],
               mapping_dir: Path, workers: int | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read all compare-SSP units for one model, optionally in parallel."""
    tasks = [(model, scenario, tech, loss_root, patches, mapping_dir)
             for scenario in COMPARE_SSPS for tech in TECHS]
    max_workers = resolve_worker_count(workers, len(tasks))
    LOGGER.info("Loading %s with %d workers for %d tasks", model, max_workers, len(tasks))
    context = mp.get_context("fork")
    annual_parts, event_parts = [], []
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=context) as pool:
        futures = {pool.submit(load_model_unit_worker, task): task for task in tasks}
        for future in as_completed(futures):
            _, _, _, annual, events = future.result()
            annual_parts.append(annual)
            event_parts.append(events)
    return (pd.concat(annual_parts, ignore_index=True),
            pd.concat(event_parts, ignore_index=True))


def analyze_model(decade_all: pd.DataFrame, model: str, output: Path,
                  k_min: int, k_max: int, min_cluster_size: int,
                  bootstrap: int, noise_scale: float, seed: int) -> None:
    """Cluster one model (or the model-mean table) and write its outputs."""
    (output / "csv").mkdir(parents=True, exist_ok=True)
    (output / "figures").mkdir(parents=True, exist_ok=True)
    assignments_all, clusters_all, scores_all = [], [], []
    for tech in TECHS:
        regions, features, wide = build_feature_matrix(decade_all, tech)
        raw_labels, tree, scores = choose_partition(
            features, k_min=k_min, k_max=k_max, min_cluster_size=min_cluster_size)
        labels = reorder_labels(features, raw_labels)
        stability = estimate_stability(features, labels, n_bootstrap=bootstrap,
                                       noise_scale=noise_scale, seed=seed)
        assignments = build_assignments(regions, features, labels, stability, wide,
                                        model=model, tech=tech)
        clusters = summarize_clusters(assignments)
        scores = scores.copy()
        scores.insert(0, "tech", tech)
        scores.insert(0, "model", model)
        plot_cluster_trajectories(assignments, output / "figures" /
                                  f"country_cluster_trajectories_{tech}.png")
        plot_country_heatmap(assignments, tree, output / "figures" /
                             f"country_gap_heatmap_{tech}.png")
        assignments_all.append(assignments)
        clusters_all.append(clusters)
        scores_all.append(scores)
        LOGGER.info("%s / %s: %d countries in %d clusters", model, tech,
                    len(assignments), assignments["cluster"].nunique())
    assignments = pd.concat(assignments_all, ignore_index=True)
    clusters = pd.concat(clusters_all, ignore_index=True)
    scores = pd.concat(scores_all, ignore_index=True)
    decade_all.to_csv(output / "csv" / "country_unit_loss_decade.csv", index=False)
    assignments.to_csv(output / "csv" / "country_cluster_assignments.csv", index=False)
    clusters.to_csv(output / "csv" / "country_cluster_summary.csv", index=False)
    scores.to_csv(output / "csv" / "cluster_k_diagnostics.csv", index=False)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loss-root", type=Path, default=LOSS_ROOT)
    parser.add_argument("--mapping-dir", type=Path, default=MAPPING_DIR)
    parser.add_argument("--patch-manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--k-min", type=int, default=2)
    parser.add_argument("--k-max", type=int, default=5)
    parser.add_argument("--min-cluster-size", type=int, default=2)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--noise-scale", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=20260918)
    args = parser.parse_args()
    manifest = args.patch_manifest or args.loss_root.resolve().parents[1] / "inputs/patch_manifest.json"
    patches = read_patch_manifest(manifest)
    config = {
        "models": list(MODELS), "compare_ssps": list(COMPARE_SSPS),
        "technologies": list(TECHS), "snapshots": list(SNAPSHOTS),
        "years_per_snapshot": SNAPSHOT_YEARS, "event_snapshot": EVENT_SNAPSHOT,
        "metric": "per-country annual net loss / per-country installed capacity, decade mean",
        "station_filter": f"stations with {COVERAGE_COLUMN} > 0 in each annual file",
        "country_mapping": "utils/country_patch_mapping/generated/stations_<ssp>.csv "
                           "joined on (lon in [-180,180), lat) rounded to 3 dp, per snapshot year",
        "clustering": "Ward hierarchical on 30-year SSP585-minus-SSP126 unit-loss gaps; "
                      "k by silhouette with min cluster size; bootstrap stability",
        "k_min": args.k_min, "k_max": args.k_max,
        "min_cluster_size": args.min_cluster_size,
        "bootstrap": args.bootstrap, "noise_scale": args.noise_scale, "seed": args.seed,
        "loss_root": str(args.loss_root.resolve()), "patch_ids": patches,
        "patch_manifest": str(manifest.resolve()),
        "patch_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenario_aliases": {"ssp560": "ssp585"},
        "ensemble": "decade-mean unit losses averaged across the four models "
                    "before clustering",
        "figure_archetype": "quantitative grid", "figure_format": "png", "dpi": 600,
    }
    decade_tables: dict[str, pd.DataFrame] = {}
    model_events: dict[str, pd.DataFrame] = {}
    for model in MODELS:
        annual, events = load_model(model, args.loss_root, patches,
                                    args.mapping_dir, args.workers)
        model_events[model] = events
        decade = country_unit_loss(annual)
        decade_tables[model] = decade
        analyze_model(decade, model, args.output_dir / model,
                      args.k_min, args.k_max, args.min_cluster_size,
                      args.bootstrap, args.noise_scale, args.seed)
        assignments = pd.read_csv(args.output_dir / model / "csv" /
                                  "country_cluster_assignments.csv")
        for tech in TECHS:
            tech_assign = assignments[assignments["tech"].eq(tech)]
            for exclude in (False, True):
                stem = ("country_cluster_event_composition_no_low_resource"
                        if exclude else "country_cluster_event_composition")
                clusters, all_mean, order = event_composition_by_cluster(
                    events, tech_assign, exclude_low_resource=exclude)
                plot_event_composition(clusters, all_mean, order, tech,
                                       args.output_dir / model / "figures" /
                                       f"{stem}_{tech}.png",
                                       exclude_low_resource=exclude)
    combined = pd.concat([table.assign(model=model)
                          for model, table in decade_tables.items()], ignore_index=True)
    keys = ["country", "scenario", "tech", "snapshot_year"]
    model_counts = combined.groupby(keys)["model"].nunique()
    incomplete_keys = model_counts[model_counts.ne(len(MODELS))]
    if not incomplete_keys.empty:
        dropped = sorted(set(incomplete_keys.index.get_level_values("country")))
        LOGGER.warning(
            "Ensemble mean keeps only countries complete in all four models; "
            "dropping %d countries with partial model coverage: %s",
            len(dropped), ", ".join(dropped))
    complete_keys = model_counts[model_counts.eq(len(MODELS))].index
    mean_decade = (combined.set_index(keys).loc[complete_keys].reset_index()
                   .groupby(keys, as_index=False).agg(unit_loss=("unit_loss", "mean")))
    analyze_model(mean_decade, "ensemble_mean", args.output_dir / "ensemble_mean",
                  args.k_min, args.k_max, args.min_cluster_size,
                  args.bootstrap, args.noise_scale, args.seed)
    combined_events = pd.concat([table.assign(model=model)
                                 for model, table in model_events.items()],
                                ignore_index=True)
    event_keys = ["country", "scenario", "tech", "event", "analysis_year"]
    event_model_counts = combined_events.groupby(event_keys)["model"].nunique()
    complete_event_keys = event_model_counts[
        event_model_counts.eq(len(MODELS))].index
    mean_events = (combined_events.set_index(event_keys).loc[complete_event_keys]
                   .reset_index().groupby(event_keys, as_index=False).agg(
        net_loss_mwh=("net_loss_mwh", "mean")))
    ensemble_assignments = pd.read_csv(
        args.output_dir / "ensemble_mean" / "csv" / "country_cluster_assignments.csv")
    for tech in TECHS:
        tech_assign = ensemble_assignments[ensemble_assignments["tech"].eq(tech)]
        for exclude in (False, True):
            stem = ("country_cluster_event_composition_no_low_resource"
                    if exclude else "country_cluster_event_composition")
            clusters, all_mean, order = event_composition_by_cluster(
                mean_events, tech_assign, exclude_low_resource=exclude)
            plot_event_composition(clusters, all_mean, order, tech,
                                   args.output_dir / "ensemble_mean" / "figures" /
                                   f"{stem}_{tech}.png",
                                   exclude_low_resource=exclude)
    (args.output_dir / "run_config.json").parent.mkdir(parents=True, exist_ok=True)
    for model in [*MODELS, "ensemble_mean"]:
        target = args.output_dir / model / "run_config.json"
        target.write_text(json.dumps({**config, "model": model}, indent=2,
                                     ensure_ascii=False), encoding="utf-8")
    LOGGER.info("Saved: %s", args.output_dir)


if __name__ == "__main__":
    main()
