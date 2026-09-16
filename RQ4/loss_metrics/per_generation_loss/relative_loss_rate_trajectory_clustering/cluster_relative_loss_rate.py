#!/usr/bin/env python3
"""仅按三种 SSP 下相对损失率轨迹聚类国家，并分解类内极端事件。"""

from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.lines import Line2D
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import pdist, squareform

from common import (
    CLUSTER_COLORS,
    COMPARE_SSPS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REGION_CSV,
    EVENT_COLOR,
    EVENT_LABEL,
    METRIC_BY_KEY,
    METRICS,
    SNAPSHOT_LABEL,
    SNAPSHOTS,
    SSP_LABEL,
    TECH_LABEL,
    TECHS,
    configure_style,
    load_country_event_losses,
    aggregate_rates,
    coverage_table,
    load_source,
    FEATURE_NAMES,
    SSP_COLOR,
    resolve_path,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--region-input-csv", type=Path, default=None, help="国家年度损失长表。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。")
    parser.add_argument("--techs", nargs="+", choices=TECHS, default=list(TECHS))
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=[metric.key for metric in METRICS],
        default=[metric.key for metric in METRICS],
    )
    parser.add_argument("--k-min", type=int, default=2, help="候选最小类别数。")
    parser.add_argument("--k-max", type=int, default=5, help="候选最大类别数。")
    parser.add_argument("--min-cluster-size", type=int, default=2, help="每类最少国家数。")
    parser.add_argument("--bootstrap", type=int, default=200, help="扰动重采样次数。")
    parser.add_argument("--noise-scale", type=float, default=0.05, help="稳定性分析噪声相对尺度。")
    parser.add_argument("--seed", type=int, default=20260909, help="随机种子。")
    parser.add_argument("--silhouette-tolerance", type=float, default=0.05)
    parser.add_argument("--event-snapshot", type=int, choices=SNAPSHOTS, default=2050)
    return parser.parse_args()


def build_feature_matrix(
    metrics: pd.DataFrame,
    *,
    tech: str,
    metric: str,
) -> tuple[list[str], np.ndarray, pd.DataFrame]:
    """构造九维相对损失率轨迹，并按列进行跨国家 z-score 标准化。"""
    subset = metrics[(metrics["tech"] == tech) & (metrics["metric"] == metric)].copy()
    wide = subset.pivot(
        index="region",
        columns=["scenario", "snapshot_year"],
        values="value",
    )
    expected = pd.MultiIndex.from_product([COMPARE_SSPS, SNAPSHOTS])
    wide = wide.reindex(columns=expected)
    eligible = np.isfinite(wide.to_numpy(dtype=float)).all(axis=1)
    complete = wide.loc[eligible].sort_index()
    if len(complete) < 4:
        raise ValueError(f"{tech}/{metric} 只有 {len(complete)} 个完整国家，无法聚类。")
    raw_features = complete.to_numpy(dtype=float)
    column_mean = raw_features.mean(axis=0)
    column_std = raw_features.std(axis=0, ddof=1)
    column_std = np.where(column_std > 0, column_std, 1.0)
    features = (raw_features - column_mean) / column_std
    return complete.index.astype(str).tolist(), features, complete


def silhouette_score(features: np.ndarray, labels: np.ndarray) -> float:
    """不依赖 scikit-learn 的平均轮廓系数。"""
    distance = squareform(pdist(features, metric="euclidean"))
    scores = np.zeros(len(features), dtype=float)
    for index, label in enumerate(labels):
        same = np.flatnonzero(labels == label)
        same = same[same != index]
        if len(same) == 0:
            scores[index] = 0.0
            continue
        a = float(distance[index, same].mean())
        other_means = [
            float(distance[index, labels == other].mean())
            for other in np.unique(labels)
            if other != label
        ]
        b = min(other_means)
        scores[index] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(scores.mean())


def choose_partition(features: np.ndarray, *, k_min: int, k_max: int,
                     min_cluster_size: int, tolerance: float = 0.05
                     ) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    tree = linkage(features, method="ward", metric="euclidean", optimal_ordering=True)
    rows, partitions = [], {}
    for k in range(k_min, min(k_max, len(features) - 1) + 1):
        labels = fcluster(tree, k, criterion="maxclust")
        counts = pd.Series(labels).value_counts()
        actual = len(counts)
        score = silhouette_score(features, labels) if 1 < actual < len(features) else np.nan
        eligible = actual == k and counts.min() >= min_cluster_size
        rows.append(dict(requested_k=k, actual_k=actual, minimum_cluster_size=counts.min(),
                         silhouette_score=score, eligible=eligible))
        partitions[k] = labels
    scores = pd.DataFrame(rows)
    candidates = scores[scores["eligible"] & scores["silhouette_score"].notna()]
    relaxed = candidates.empty
    if relaxed:
        candidates = scores[scores["actual_k"].eq(scores["requested_k"]) & scores["silhouette_score"].notna()]
    if candidates.empty:
        raise ValueError("没有可分割的国家轨迹，不能强制分成多个类别")
    best = candidates["silhouette_score"].max()
    chosen = int(candidates.loc[candidates["silhouette_score"] >= best - tolerance,
                                 "requested_k"].min())
    scores["selected"] = scores["requested_k"].eq(chosen)
    scores["relaxed_min_cluster_size"] = relaxed
    return partitions[chosen], tree, scores


def reorder_labels(features: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """按平均标准化损失率从高到低稳定编号。"""
    means = {
        label: float(features[labels == label].mean()) for label in np.unique(labels)
    }
    mapping = {
        old: new
        for new, old in enumerate(
            sorted(means, key=lambda label: means[label], reverse=True), start=1
        )
    }
    return np.asarray([mapping[label] for label in labels], dtype=int)


def align_labels(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    refs, candidates = np.unique(reference), np.unique(candidate)
    counts = np.array([[np.sum((reference == a) & (candidate == b))
                        for b in candidates] for a in refs])
    rows, columns = linear_sum_assignment(-counts)
    mapping = {candidates[j]: refs[i] for i, j in zip(rows, columns)}
    return np.array([mapping.get(label, -1) for label in candidate])


def estimate_stability(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    n_bootstrap: int,
    noise_scale: float,
    seed: int,
) -> np.ndarray:
    if n_bootstrap <= 0:
        return np.full(len(features), np.nan)
    rng = np.random.default_rng(seed)
    scale = np.std(features, axis=0, ddof=1)
    matches = np.zeros(len(features), dtype=int)
    n_clusters = len(np.unique(labels))
    for _ in range(n_bootstrap):
        perturbed = features + rng.normal(0.0, noise_scale * scale, size=features.shape)
        candidate = fcluster(linkage(perturbed, method="ward"), n_clusters, criterion="maxclust")
        candidate = align_labels(labels, candidate)
        matches += candidate == labels
    return matches / n_bootstrap


def describe_pattern(values: np.ndarray, threshold: float = 0.10) -> str:
    """根据原始损失率起止变化（百分点）描述中心轨迹。"""
    trajectories = np.asarray(values).reshape(3, 3)
    change = trajectories[:, -1] - trajectories[:, 0]
    if np.max(np.abs(change)) <= threshold:
        return "Stable"
    if np.all(change > threshold):
        return "Increasing"
    if np.all(change < -threshold):
        return "Decreasing"
    if np.max(change) > threshold and np.min(change) < -threshold:
        return "Divergent trends"
    return "Mixed trends"


def build_assignments(
    regions: list[str],
    features: np.ndarray,
    labels: np.ndarray,
    stability: np.ndarray,
    wide: pd.DataFrame,
    *,
    model: str,
    tech: str,
    metric: str,
) -> pd.DataFrame:
    centroids = {
        label: wide.to_numpy()[labels == label].mean(axis=0) for label in np.unique(labels)
    }
    patterns = {label: describe_pattern(values) for label, values in centroids.items()}
    rows = []
    for index, region in enumerate(regions):
        row = {
            "model": model,
            "region": region,
            "tech": tech,
            "metric": metric,
            "cluster": int(labels[index]),
            "cluster_label": f"C{labels[index]}",
            "pattern": patterns[labels[index]],
            "assignment_stability": stability[index],
            "singleton": bool(np.sum(labels == labels[index]) == 1),
        }
        feature_index = 0
        for scenario in COMPARE_SSPS:
            for snapshot in SNAPSHOTS:
                row[f"z_{scenario}_{snapshot}"] = features[index, feature_index]
                row[f"{scenario}_{snapshot}"] = float(wide.loc[region, (scenario, snapshot)])
                feature_index += 1
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_clusters(assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cluster, group in assignments.groupby("cluster", sort=True):
        row = {
            "model": group["model"].iloc[0],
            "tech": group["tech"].iloc[0],
            "metric": group["metric"].iloc[0],
            "cluster": int(cluster),
            "cluster_label": f"C{cluster}",
            "pattern": group["pattern"].iloc[0],
            "n_countries": len(group),
            "countries": ";".join(sorted(group["region"])),
            "mean_assignment_stability": group["assignment_stability"].mean(),
        }
        for scenario in COMPARE_SSPS:
            for snapshot in SNAPSHOTS:
                key = f"z_{scenario}_{snapshot}"
                row[f"{key}_mean"] = group[key].mean()
                row[f"{key}_min"] = group[key].min()
                row[f"{key}_max"] = group[key].max()
                raw_key = f"{scenario}_{snapshot}"
                row[f"{raw_key}_mean"] = group[raw_key].mean()
                row[f"{raw_key}_min"] = group[raw_key].min()
                row[f"{raw_key}_max"] = group[raw_key].max()
        rows.append(row)
    return pd.DataFrame(rows)


def plot_clusters(assignments, scores, tree, *, tech, metric, output_dir) -> Path:
    configure_style()
    clusters = sorted(assignments["cluster"].unique())
    fig, axes = plt.subplots(1, len(COMPARE_SSPS), figsize=(7.8, 2.9),
                             squeeze=False, sharex=True, sharey=False)
    for col, scenario in enumerate(COMPARE_SSPS):
        ax = axes[0, col]
        for cluster in clusters:
            group = assignments[assignments["cluster"].eq(cluster)]
            color = CLUSTER_COLORS[(int(cluster) - 1) % len(CLUSTER_COLORS)]
            values = group[[f"{scenario}_{year}" for year in SNAPSHOTS]].to_numpy()
            for values_row in values:
                ax.plot(SNAPSHOTS, values_row, color=color, alpha=0.25, lw=0.65)
            ax.plot(SNAPSHOTS, values.mean(axis=0), "-o", color=color, lw=1.8, ms=3,
                    label=f"C{cluster} (n={len(group)})")
        ax.set_title(SSP_LABEL[scenario])
        ax.set_xticks(SNAPSHOTS, [str(y) for y in SNAPSHOTS])
        ax.grid(axis="y", alpha=0.2)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.tick_params(axis="y", labelleft=True)
        if col == 0:
            ax.set_ylabel("Relative loss rate (%)")
    handles = [Line2D([0], [0], color=CLUSTER_COLORS[(int(c)-1) % len(CLUSTER_COLORS)],
                      lw=1.8, marker="o", ms=3,
                      label=f"C{c} (n={len(assignments[assignments.cluster.eq(c)])})")
               for c in clusters]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles),
               bbox_to_anchor=(0.5, 1.03))
    fig.suptitle(f"{TECH_LABEL[tech]}: relative loss-rate trajectories by cluster", fontsize=10, y=1.10)
    fig.subplots_adjust(left=0.08, right=0.99, bottom=0.18, top=0.78, wspace=0.16)
    save_figure(fig, output_dir, f"trajectories_{tech}")

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 5.5), width_ratios=[3, 1.2])
    order = assignments.iloc[leaves_list(tree)].sort_values("cluster", kind="stable")
    values = order[[f"z_{name}" for name in FEATURE_NAMES]].to_numpy()
    limit = max(0.1, float(np.abs(values).max()))
    im = axes[0].imshow(values, aspect="auto", cmap="RdBu_r", vmin=-limit, vmax=limit)
    axes[0].set_yticks(range(len(order)), [f"C{r.cluster} {r.region}" for r in order.itertuples()], fontsize=6)
    axes[0].set_xticks(range(9), FEATURE_NAMES, rotation=90, fontsize=6)
    axes[0].set_title("a  Standardized input features")
    fig.colorbar(im, ax=axes[0], fraction=0.04, pad=0.03, label="z-score")
    for boundary in (2.5, 5.5):
        axes[0].axvline(boundary, color="white", lw=1)
    axes[1].plot(scores["requested_k"], scores["silhouette_score"], "-o", color="#484878")
    selected = scores[scores["selected"]]
    axes[1].scatter(selected["requested_k"], selected["silhouette_score"], s=65,
                    facecolors="none", edgecolors="black", label="Selected")
    invalid = scores[~scores["eligible"]]
    axes[1].scatter(invalid["requested_k"], invalid["silhouette_score"],
                    marker="x", color="#b64342", label="Size < minimum")
    axes[1].set_xticks(scores["requested_k"])
    axes[1].set_xlabel("Number of clusters")
    axes[1].set_ylabel("Mean silhouette")
    axes[1].set_title("b  Selection")
    axes[1].legend(fontsize=5, loc="best")
    fig.tight_layout()
    return save_figure(fig, output_dir, f"diagnostics_{tech}")


def summarize_cluster_events(
    events: pd.DataFrame,
    assignments: pd.DataFrame,
) -> pd.DataFrame:
    selected = events[events["tech"].eq(assignments["tech"].iloc[0])].merge(
        assignments[["region", "cluster", "cluster_label", "pattern"]],
        on="region",
        how="inner",
        validate="many_to_one",
    )
    country_total = selected.groupby(
        ["region", "scenario", "snapshot_year"], as_index=False
    )["positive_net_loss_mwh_per_year"].sum().rename(
        columns={"positive_net_loss_mwh_per_year": "country_positive_event_loss_mwh_per_year"}
    )
    selected = selected.merge(country_total, on=["region", "scenario", "snapshot_year"], how="left")
    selected["country_event_share"] = np.where(
        selected["country_positive_event_loss_mwh_per_year"] > 0,
        selected["positive_net_loss_mwh_per_year"] / selected["country_positive_event_loss_mwh_per_year"],
        np.nan,
    )
    residual_total = selected[selected["event"].ne("low_resource")].groupby(
        ["region", "scenario", "snapshot_year"], as_index=False
    )["positive_net_loss_mwh_per_year"].sum().rename(
        columns={"positive_net_loss_mwh_per_year": "country_residual_event_loss_mwh_per_year"}
    )
    selected = selected.merge(residual_total, on=["region", "scenario", "snapshot_year"], how="left")
    selected["country_residual_share"] = np.where(
        selected["event"].ne("low_resource") & (selected["country_residual_event_loss_mwh_per_year"] > 0),
        selected["positive_net_loss_mwh_per_year"] / selected["country_residual_event_loss_mwh_per_year"],
        np.nan,
    )

    keys = ["scenario", "snapshot_year", "cluster", "cluster_label", "pattern", "event"]
    summary = selected.groupby(keys, as_index=False).agg(
        positive_net_loss_mwh_per_year=("positive_net_loss_mwh_per_year", "sum"),
        country_equal_share=("country_event_share", "mean"),
        country_equal_residual_share=("country_residual_share", "mean"),
        n_countries=("region", "nunique"),
        n_negative_country_event_values=("net_loss_mwh_per_year", lambda values: int((values < 0).sum())),
    )
    total = summary.groupby(["scenario", "snapshot_year", "cluster"])[
        "positive_net_loss_mwh_per_year"
    ].transform("sum")
    summary["loss_weighted_share"] = np.where(
        total > 0, summary["positive_net_loss_mwh_per_year"] / total, np.nan
    )
    residual = summary[summary["event"].ne("low_resource")].groupby(
        ["scenario", "snapshot_year", "cluster"]
    )["positive_net_loss_mwh_per_year"].transform("sum")
    summary["loss_weighted_residual_share"] = np.nan
    mask = summary["event"].ne("low_resource")
    summary.loc[mask, "loss_weighted_residual_share"] = np.where(
        residual > 0,
        summary.loc[mask, "positive_net_loss_mwh_per_year"] / residual,
        np.nan,
    )
    summary["tech"] = assignments["tech"].iloc[0]
    summary["metric"] = assignments["metric"].iloc[0]
    return summary


def plot_cluster_events(
    summary: pd.DataFrame,
    *,
    tech: str,
    metric: str,
    snapshot: int,
    output_dir: Path,
) -> Path:
    configure_style()
    data = summary[summary["snapshot_year"].eq(snapshot)].copy()
    clusters = sorted(data["cluster"].unique())
    events = [event for event in EVENT_LABEL if event in set(data["event"])]
    residual_events = [event for event in events if event != "low_resource"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6), sharey=False)

    for ax, event_order, column, title in [
        (axes[0], events, "loss_weighted_share", "a  All event types"),
        (axes[1], residual_events, "loss_weighted_residual_share", "b  Other event types"),
    ]:
        positions = []
        labels = []
        bottoms = []
        for cluster_index, cluster in enumerate(clusters):
            for scenario_index, scenario in enumerate(COMPARE_SSPS):
                positions.append(cluster_index * (len(COMPARE_SSPS) + 0.6) + scenario_index)
                labels.append(SSP_LABEL[scenario].replace("SSP", ""))
                bottoms.append(0.0)
        bottoms = np.asarray(bottoms)
        for event in event_order:
            values = []
            for cluster in clusters:
                for scenario in COMPARE_SSPS:
                    match = data[
                        data["cluster"].eq(cluster)
                        & data["scenario"].eq(scenario)
                        & data["event"].eq(event)
                    ]
                    values.append(float(match[column].iloc[0]) if len(match) else 0.0)
            values_array = np.nan_to_num(np.asarray(values), nan=0.0)
            ax.bar(
                positions,
                values_array * 100.0,
                bottom=bottoms * 100.0,
                width=0.82,
                color=EVENT_COLOR.get(event, "0.65"),
                edgecolor="white",
                linewidth=0.25,
                label=EVENT_LABEL.get(event, event),
            )
            bottoms += values_array
        ax.set_xticks(positions, labels, rotation=0)
        for cluster_index, cluster in enumerate(clusters):
            center = cluster_index * (len(COMPARE_SSPS) + 0.6) + (len(COMPARE_SSPS) - 1) / 2
            ax.text(center, -0.18, f"C{cluster}", transform=ax.get_xaxis_transform(), ha="center", va="top", fontweight="bold")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Positive event-loss pool (%)")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.grid(axis="y", lw=0.35, alpha=0.35)
    handles = [Patch(facecolor=EVENT_COLOR[event], label=EVENT_LABEL[event]) for event in events]
    fig.legend(handles=handles, loc="upper center", ncol=min(5, len(handles)), bbox_to_anchor=(0.5, 0.965))
    metric_spec = METRIC_BY_KEY[metric]
    fig.suptitle(
        f"{TECH_LABEL[tech]}: event-loss composition ({snapshot}s)",
        fontsize=9.5,
        fontweight="bold",
        y=1.04,
    )
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.19, top=0.80, wspace=0.28)
    stem = f"fig_RQ4_cluster_event_composition_{tech}_{metric}_{snapshot}"
    return save_figure(fig, output_dir, stem)


def main() -> None:
    args = parse_args()
    if args.k_min < 2 or args.k_max < args.k_min:
        raise SystemExit("要求 2 <= k-min <= k-max。")
    if args.min_cluster_size < 2:
        raise SystemExit("min-cluster-size 至少为 2，避免单国家类别。")

    region_csv = args.region_input_csv or resolve_path(DEFAULT_REGION_CSV, args.model)
    for path in (region_csv,):
        if not path.exists():
            raise SystemExit(f"未找到输入文件：{path}")
    run_name = args.model if set(args.techs) == set(TECHS) else args.model + "_" + "_".join(args.techs)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / run_name)
    csv_dir = output_dir / "csv"
    figure_dir = output_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    source = load_source(region_csv, args.model)
    metrics, annual = aggregate_rates(source)
    events = load_country_event_losses(source)
    regions = sorted(source["region"].unique())
    coverage = coverage_table(metrics, regions)
    coverage.to_csv(csv_dir / "country_coverage.csv", index=False)
    config = {key: str(value) if isinstance(value, Path) else value
              for key, value in vars(args).items()}
    config["input_csv"] = str(region_csv.resolve())
    config["input_sha256"] = hashlib.sha256(region_csv.read_bytes()).hexdigest()
    config["feature_order"] = FEATURE_NAMES
    config["aggregation"] = "100 * sum(net_loss) / sum(normal_generation)"
    (output_dir / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    metrics.to_csv(csv_dir / "RQ4_country_metric_decade.csv", index=False)
    annual.to_csv(csv_dir / "RQ4_country_metric_annual.csv", index=False)
    events.to_csv(csv_dir / "RQ4_country_event_decade.csv", index=False)

    all_assignments = []
    all_clusters = []
    all_scores = []
    all_event_summaries = []
    for tech in args.techs:
        for metric in args.metrics:
            regions, features, wide = build_feature_matrix(metrics, tech=tech, metric=metric)
            raw_features = wide.to_numpy(dtype=float)
            pd.DataFrame({"feature": FEATURE_NAMES, "mean_pct": raw_features.mean(axis=0),
                          "std_pct": raw_features.std(axis=0, ddof=1)}).to_csv(
                              csv_dir / f"standardization_{tech}.csv", index=False)
            wide.set_axis(FEATURE_NAMES, axis=1).to_csv(csv_dir / f"features_raw_{tech}.csv")
            pd.DataFrame(features, index=regions, columns=FEATURE_NAMES).rename_axis("region").to_csv(
                csv_dir / f"features_standardized_{tech}.csv")
            raw_labels, tree, scores = choose_partition(
                features,
                k_min=args.k_min,
                k_max=args.k_max,
                min_cluster_size=args.min_cluster_size,
                tolerance=args.silhouette_tolerance,
            )
            labels = reorder_labels(features, raw_labels)
            stability = estimate_stability(
                features,
                labels,
                n_bootstrap=args.bootstrap,
                noise_scale=args.noise_scale,
                seed=args.seed,
            )
            assignments = build_assignments(
                regions,
                features,
                labels,
                stability,
                wide,
                model=args.model,
                tech=tech,
                metric=metric,
            )
            clusters = summarize_clusters(assignments)
            scores.insert(0, "metric", metric)
            scores.insert(0, "tech", tech)
            scores.insert(0, "model", args.model)
            event_summary = summarize_cluster_events(events, assignments)

            plot_clusters(assignments, scores, tree, tech=tech, metric=metric, output_dir=figure_dir)
            plot_cluster_events(
                event_summary,
                tech=tech,
                metric=metric,
                snapshot=args.event_snapshot,
                output_dir=figure_dir,
            )
            all_assignments.append(assignments)
            all_clusters.append(clusters)
            all_scores.append(scores)
            all_event_summaries.append(event_summary)
            print(
                f"完成 {tech}/{metric}：{len(assignments)} 个国家，"
                f"{assignments['cluster'].nunique()} 类。"
            )

    assignments = pd.concat(all_assignments, ignore_index=True)
    clusters = pd.concat(all_clusters, ignore_index=True)
    scores = pd.concat(all_scores, ignore_index=True)
    event_summary = pd.concat(all_event_summaries, ignore_index=True)
    assignments.to_csv(csv_dir / "RQ4_country_cluster_assignments.csv", index=False)
    clusters.to_csv(csv_dir / "RQ4_country_cluster_summary.csv", index=False)
    scores.to_csv(csv_dir / "RQ4_cluster_k_diagnostics.csv", index=False)
    event_summary.to_csv(csv_dir / "RQ4_cluster_event_composition.csv", index=False)
    print(f"已保存 RQ4 结果：{output_dir}")


if __name__ == "__main__":
    main()
