"""Sign-based reversal classification of country SSP585-minus-SSP126 unit-loss gaps.

Splits countries into four fixed classes by the sign of the decadal-mean gap in
the early (2030s) and late (2050s) snapshots: ++, +-, -+, --. No clustering
algorithm is used; the classes are the four sign combinations. Reading,
per-country aggregation, event composition and plotting reuse the
ssp_gap_clustering module, and each model plus the equal-weight model mean
produce cluster trajectories, event-composition bars and (via
map_country_clusters) world maps. Figures are PNG only; importing this module
does not read inputs or draw figures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PACKAGE_PARENT = Path(__file__).resolve().parents[1]
for candidate in (PACKAGE_PARENT, PACKAGE_PARENT / "ssp_gap_clustering"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import country_unit_loss_clustering as base  # noqa: E402
from country_unit_loss_clustering import (  # noqa: E402
    ANALYSIS_YEARS, COMPARE_SSPS, EVENT_SNAPSHOT, LOSS_ROOT, MAPPING_DIR, MODELS,
    SNAPSHOTS, TECHS, build_feature_matrix, configure_logging, event_composition_by_cluster,
    load_model, plot_cluster_trajectories, plot_event_composition, read_patch_manifest,
)
import map_country_clusters  # noqa: E402
from map_country_clusters import paint_map  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
EARLY_SNAPSHOT, LATE_SNAPSHOT = SNAPSHOTS[0], SNAPSHOTS[-1]
GAP_LABEL = "SSP5-8.5 minus SSP1-2.6 gap (MWh MW$^{-1}$ yr$^{-1}$)"
LOGGER = logging.getLogger("rq1.country_ssp_gap_reversal")

# Fixed class order: ++, +-, -+, -- ; sign is (early, late).
SIGN_CLASSES = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def classify_reversal(features: np.ndarray) -> np.ndarray:
    """Class index in 1..4 from the signs of the early and late gap means.

    A gap of exactly zero counts as positive, so every country maps to exactly
    one of the four (early, late) sign classes.
    """
    early = features[:, SNAPSHOTS.index(EARLY_SNAPSHOT)]
    late = features[:, SNAPSHOTS.index(LATE_SNAPSHOT)]
    early_positive = early >= 0
    late_positive = late >= 0
    labels = np.empty(len(features), dtype=int)
    for index, (early_sign, late_sign) in enumerate(SIGN_CLASSES, start=1):
        match = (early_positive == (early_sign > 0)) & (late_positive == (late_sign > 0))
        labels[match] = index
    if (labels == 0).any():
        raise ValueError("Every country must match exactly one sign class")
    return labels


def class_pattern(label: int) -> str:
    early_sign, late_sign = SIGN_CLASSES[label - 1]
    early = "+" if early_sign > 0 else "-"
    late = "+" if late_sign > 0 else "-"
    return f"{early}{late}"


def build_assignments(regions: list[str], features: np.ndarray, labels: np.ndarray,
                      wide: pd.DataFrame, *, model: str, tech: str) -> pd.DataFrame:
    rows = []
    for index, region in enumerate(regions):
        row = {
            "model": model, "country": region, "tech": tech,
            "cluster": int(labels[index]),
            "pattern": class_pattern(int(labels[index])),
        }
        for snapshot_index, snapshot in enumerate(SNAPSHOTS):
            row[f"gap_{snapshot}"] = features[index, snapshot_index]
            for scenario in COMPARE_SSPS:
                row[f"{scenario}_{snapshot}"] = float(wide.loc[region, (scenario, snapshot)])
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_clusters(assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in range(1, len(SIGN_CLASSES) + 1):
        group = assignments[assignments["cluster"].eq(label)]
        row = {
            "model": assignments["model"].iloc[0], "tech": assignments["tech"].iloc[0],
            "cluster": label, "cluster_label": f"C{label}",
            "pattern": class_pattern(label), "n_countries": len(group),
            "countries": ";".join(sorted(group["country"])),
        }
        for snapshot in SNAPSHOTS:
            values = group[f"gap_{snapshot}"]
            row[f"gap_{snapshot}_mean"] = float(values.mean()) if len(group) else np.nan
            row[f"gap_{snapshot}_min"] = float(values.min()) if len(group) else np.nan
            row[f"gap_{snapshot}_max"] = float(values.max()) if len(group) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_model(decade: pd.DataFrame, model: str, output: Path) -> dict[str, pd.DataFrame]:
    (output / "csv").mkdir(parents=True, exist_ok=True)
    (output / "figures").mkdir(parents=True, exist_ok=True)
    assignments_all, clusters_all = [], []
    for tech in TECHS:
        regions, features, wide = build_feature_matrix(decade, tech)
        labels = classify_reversal(features)
        assignments = build_assignments(regions, features, labels, wide,
                                        model=model, tech=tech)
        clusters = summarize_clusters(assignments)
        plot_cluster_trajectories(assignments, output / "figures" /
                                  f"country_cluster_trajectories_{tech}.png")
        assignments_all.append(assignments)
        clusters_all.append(clusters)
        sizes = ", ".join(f"C{i}={int((labels == i).sum())}"
                          for i in range(1, len(SIGN_CLASSES) + 1))
        LOGGER.info("%s / %s: %d countries classified (%s)", model, tech,
                    len(assignments), sizes)
    assignments = pd.concat(assignments_all, ignore_index=True)
    clusters = pd.concat(clusters_all, ignore_index=True)
    decade.to_csv(output / "csv" / "country_unit_loss_decade.csv", index=False)
    assignments.to_csv(output / "csv" / "country_cluster_assignments.csv", index=False)
    clusters.to_csv(output / "csv" / "country_cluster_summary.csv", index=False)
    return {"assignments": assignments}


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loss-root", type=Path, default=LOSS_ROOT)
    parser.add_argument("--mapping-dir", type=Path, default=MAPPING_DIR)
    parser.add_argument("--patch-manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    manifest = args.patch_manifest or args.loss_root.resolve().parents[1] / "inputs/patch_manifest.json"
    patches = read_patch_manifest(manifest)
    config = {
        "models": list(MODELS), "compare_ssps": list(COMPARE_SSPS),
        "technologies": list(TECHS), "snapshots": list(SNAPSHOTS),
        "event_snapshot": EVENT_SNAPSHOT,
        "metric": "per-country annual net loss / per-country installed capacity, decade mean",
        "station_filter": "stations with normal_all_generation_mwh_all > 0 in each annual file",
        "classification": "fixed sign classes of the SSP585-minus-SSP126 gap: "
                          "C1 = 2030s+ 2050s+, C2 = +-, C3 = -+, C4 = --; "
                          "a gap of exactly zero counts as positive",
        "ensemble": "decade-mean unit losses averaged across the four models "
                    "before classification",
        "loss_root": str(args.loss_root.resolve()), "patch_ids": patches,
        "patch_manifest": str(manifest.resolve()),
        "patch_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenario_aliases": {"ssp560": "ssp585"},
        "figure_archetype": "quantitative grid", "figure_format": "png", "dpi": 600,
    }
    decade_tables: dict[str, pd.DataFrame] = {}
    model_events: dict[str, pd.DataFrame] = {}
    for model in MODELS:
        annual, events = load_model(model, args.loss_root, patches,
                                    args.mapping_dir, args.workers)
        model_events[model] = events
        decade = base.country_unit_loss(annual)
        decade_tables[model] = decade
        assignments = analyze_model(decade, model, args.output_dir / model)
        for tech in TECHS:
            tech_assign = assignments["assignments"][assignments["assignments"]["tech"].eq(tech)]
            clusters, all_mean, order = event_composition_by_cluster(events, tech_assign)
            plot_event_composition(clusters, all_mean, order, tech,
                                   args.output_dir / model / "figures" /
                                   f"country_cluster_event_composition_{tech}.png")
            paint_map(tech_assign, model, tech, args.output_dir / model / "figures" /
                      f"cluster_map_{model}_{tech}.png")
    combined = pd.concat([table.assign(model=model)
                          for model, table in decade_tables.items()], ignore_index=True)
    keys = ["country", "scenario", "tech", "snapshot_year"]
    model_counts = combined.groupby(keys)["model"].nunique()
    incomplete = model_counts[model_counts.ne(len(MODELS))]
    if not incomplete.empty:
        dropped = sorted(set(incomplete.index.get_level_values("country")))
        LOGGER.warning("Ensemble keeps only countries complete in all four models; "
                       "dropping %d: %s", len(dropped), ", ".join(dropped))
    complete_keys = model_counts[model_counts.eq(len(MODELS))].index
    mean_decade = (combined.set_index(keys).loc[complete_keys].reset_index()
                   .groupby(keys, as_index=False).agg(unit_loss=("unit_loss", "mean")))
    result = analyze_model(mean_decade, "ensemble_mean", args.output_dir / "ensemble_mean")
    combined_events = pd.concat([table.assign(model=model)
                                 for model, table in model_events.items()],
                                ignore_index=True)
    event_keys = ["country", "scenario", "tech", "event", "analysis_year"]
    event_model_counts = combined_events.groupby(event_keys)["model"].nunique()
    complete_event_keys = event_model_counts[event_model_counts.eq(len(MODELS))].index
    mean_events = (combined_events.set_index(event_keys).loc[complete_event_keys]
                   .reset_index().groupby(event_keys, as_index=False).agg(
        net_loss_mwh=("net_loss_mwh", "mean")))
    for tech in TECHS:
        tech_assign = result["assignments"][result["assignments"]["tech"].eq(tech)]
        clusters, all_mean, order = event_composition_by_cluster(mean_events, tech_assign)
        plot_event_composition(clusters, all_mean, order, tech,
                               args.output_dir / "ensemble_mean" / "figures" /
                               f"country_cluster_event_composition_{tech}.png")
        paint_map(tech_assign, "ensemble_mean", tech,
                  args.output_dir / "ensemble_mean" / "figures" /
                  f"cluster_map_ensemble_mean_{tech}.png")
    map_config = {
        "projection": "PlateCarree",
        "basemap": "Natural Earth 110m admin_0_countries (cartopy cache)",
        "cluster_colors": list(map_country_clusters.CLUSTER_COLORS),
        "not_clustered_color": map_country_clusters.LAND_COLOR,
        "source": "country_cluster_assignments.csv per model output set",
        "script_sha256": hashlib.sha256(
            (Path(__file__).resolve().parent.parent / "ssp_gap_clustering"
             / "map_country_clusters.py").read_bytes()).hexdigest(),
        "figure_format": "png", "dpi": 600,
    }
    for model in (*MODELS, "ensemble_mean"):
        (args.output_dir / model / "run_config.json").write_text(
            json.dumps({**config, "model": model, "cluster_map": map_config},
                       indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("Saved: %s", args.output_dir)


if __name__ == "__main__":
    main()
