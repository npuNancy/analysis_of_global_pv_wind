#!/usr/bin/env python3
"""按 SSP126–SSP585 损失差曲线聚类国家，并分解类内极端事件。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
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
    DEFAULT_STATION_SUMMARY_CSV,
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
    load_country_metrics,
    resolve_path,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--region-input-csv", type=Path, default=None, help="国家年度损失长表。")
    parser.add_argument("--station-summary-csv", type=Path, default=None, help="场站年代轻量汇总。")
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
    parser.add_argument("--event-snapshot", type=int, choices=SNAPSHOTS, default=2050)
    return parser.parse_args()


def symmetric_relative_gap(ssp126: np.ndarray, ssp585: np.ndarray) -> np.ndarray:
    """计算有界情景差；正值表示 SSP126 损失更高。"""
    first = np.asarray(ssp126, dtype=float)
    second = np.asarray(ssp585, dtype=float)
    denominator = np.abs(first) + np.abs(second)
    scale = np.nanmedian(denominator[denominator > 0]) if np.any(denominator > 0) else 1.0
    epsilon = max(float(scale) * 1e-12, np.finfo(float).eps)
    return 2.0 * (first - second) / (denominator + epsilon)


def build_feature_matrix(
    metrics: pd.DataFrame,
    *,
    tech: str,
    metric: str,
) -> tuple[list[str], np.ndarray, pd.DataFrame]:
    """仅保留两个情景、三个年代均完整的国家。"""
    subset = metrics[(metrics["tech"] == tech) & (metrics["metric"] == metric)].copy()
    wide = subset.pivot_table(
        index="region",
        columns=["scenario", "snapshot_year"],
        values="value",
        aggfunc="first",
    )
    expected = pd.MultiIndex.from_product([COMPARE_SSPS, SNAPSHOTS])
    wide = wide.reindex(columns=expected)
    eligible = wide.notna().all(axis=1)
    complete = wide.loc[eligible].sort_index()
    if len(complete) < 4:
        raise ValueError(f"{tech}/{metric} 只有 {len(complete)} 个完整国家，无法聚类。")
    features = symmetric_relative_gap(
        complete["ssp126"].to_numpy(dtype=float),
        complete["ssp585"].to_numpy(dtype=float),
    )
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


def choose_partition(
    features: np.ndarray,
    *,
    k_min: int,
    k_max: int,
    min_cluster_size: int,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    tree = linkage(features, method="ward", metric="euclidean", optimal_ordering=True)
    rows = []
    partitions: dict[int, np.ndarray] = {}
    upper = min(k_max, len(features) - 1)
    for requested_k in range(k_min, upper + 1):
        labels = fcluster(tree, requested_k, criterion="maxclust")
        counts = pd.Series(labels).value_counts()
        actual_k = int(counts.size)
        valid = actual_k == requested_k and int(counts.min()) >= min_cluster_size
        score = silhouette_score(features, labels) if valid else np.nan
        rows.append(
            {
                "requested_k": requested_k,
                "actual_k": actual_k,
                "minimum_cluster_size": int(counts.min()),
                "silhouette_score": score,
                "eligible": valid,
            }
        )
        if valid:
            partitions[requested_k] = labels
    scores = pd.DataFrame(rows)
    valid_scores = scores.dropna(subset=["silhouette_score"])
    if valid_scores.empty:
        # 某些指标存在一个稳定的曲线离群国家；强行禁止 singleton 会使整个
        # 指标无法分析。因此在没有满足约束的候选时保留 singleton，并在诊断表
        # 中显式标记 relaxed_min_cluster_size，避免把它误读为常规类别。
        relaxed_rows = []
        for requested_k in range(k_min, upper + 1):
            labels = fcluster(tree, requested_k, criterion="maxclust")
            counts = pd.Series(labels).value_counts()
            actual_k = int(counts.size)
            if actual_k != requested_k:
                continue
            score = silhouette_score(features, labels)
            relaxed_rows.append((requested_k, score, labels))
        if not relaxed_rows:
            raise ValueError("无法构造有效的层次聚类候选。")
        best_k, _, best_labels = max(relaxed_rows, key=lambda item: (item[1], -item[0]))
        scores["relaxed_min_cluster_size"] = True
        scores.loc[scores["requested_k"].eq(best_k), "eligible"] = True
        partitions[best_k] = best_labels
        return partitions[best_k], tree, scores
    scores["relaxed_min_cluster_size"] = False
    best_k = int(
        valid_scores.sort_values(
            ["silhouette_score", "requested_k"], ascending=[False, True]
        ).iloc[0]["requested_k"]
    )
    return partitions[best_k], tree, scores


def reorder_labels(features: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """按平均情景差从高到低稳定编号。"""
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
    labels = sorted(np.unique(reference))
    matrix = np.zeros((len(labels), len(labels)), dtype=int)
    for i, ref_label in enumerate(labels):
        for j, candidate_label in enumerate(labels):
            matrix[i, j] = int(np.sum((reference == ref_label) & (candidate == candidate_label)))
    rows, columns = linear_sum_assignment(-matrix)
    mapping = {labels[column]: labels[row] for row, column in zip(rows, columns)}
    return np.asarray([mapping[label] for label in candidate], dtype=int)


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
    positive = scale[scale > 0]
    fallback = float(np.median(positive)) if len(positive) else 1.0
    scale = np.where(scale > 0, scale, fallback)
    matches = np.zeros(len(features), dtype=int)
    n_clusters = len(np.unique(labels))
    for _ in range(n_bootstrap):
        perturbed = features + rng.normal(0.0, noise_scale * scale, size=features.shape)
        candidate = fcluster(linkage(perturbed, method="ward"), n_clusters, criterion="maxclust")
        candidate = align_labels(labels, candidate)
        matches += candidate == labels
    return matches / n_bootstrap


def describe_pattern(values: np.ndarray, threshold: float = 0.10) -> str:
    """将聚类中心转换为可解释的 trade-off 模式。"""
    values = np.asarray(values, dtype=float)
    if np.max(np.abs(values)) < threshold:
        return "情景近似一致"
    signs = np.where(values > threshold, 1, np.where(values < -threshold, -1, 0))
    nonzero = signs[signs != 0]
    if len(nonzero) and np.all(nonzero > 0):
        return "SSP126持续较高"
    if len(nonzero) and np.all(nonzero < 0):
        return "SSP585持续较高"
    if len(nonzero) >= 2 and nonzero[0] > 0 and nonzero[-1] < 0:
        return "SSP126→SSP585交叉"
    if len(nonzero) >= 2 and nonzero[0] < 0 and nonzero[-1] > 0:
        return "SSP585→SSP126交叉"
    if abs(values[-1]) < abs(values[0]):
        return "情景收敛"
    if abs(values[-1]) > abs(values[0]):
        return "情景发散"
    return "波动型"


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
        label: features[labels == label].mean(axis=0) for label in np.unique(labels)
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
        for snapshot in SNAPSHOTS:
            row[f"gap_{snapshot}_mean"] = group[f"gap_{snapshot}"].mean()
            row[f"gap_{snapshot}_min"] = group[f"gap_{snapshot}"].min()
            row[f"gap_{snapshot}_max"] = group[f"gap_{snapshot}"].max()
        rows.append(row)
    return pd.DataFrame(rows)


def plot_clusters(
    assignments: pd.DataFrame,
    scores: pd.DataFrame,
    tree: np.ndarray,
    *,
    tech: str,
    metric: str,
    output_dir: Path,
) -> list[Path]:
    configure_style()
    fig = plt.figure(figsize=(7.2, 6.2))
    grid = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.45], width_ratios=[2.15, 1.0], hspace=0.38, wspace=0.34)
    ax_curve = fig.add_subplot(grid[0, 0])
    ax_score = fig.add_subplot(grid[0, 1])
    ax_heat = fig.add_subplot(grid[1, :])

    for cluster, group in assignments.groupby("cluster", sort=True):
        color = CLUSTER_COLORS[(int(cluster) - 1) % len(CLUSTER_COLORS)]
        matrix = group[[f"gap_{year}" for year in SNAPSHOTS]].to_numpy(dtype=float) * 100.0
        for row in matrix:
            ax_curve.plot(SNAPSHOTS, row, color=color, lw=0.7, alpha=0.22)
        center = matrix.mean(axis=0)
        ax_curve.plot(
            SNAPSHOTS,
            center,
            "-o",
            color=color,
            lw=2.0,
            ms=4,
            label=f"C{cluster} {group['pattern'].iloc[0]} (n={len(group)})",
        )
    ax_curve.axhline(0, color="0.45", lw=0.8, ls="--")
    ax_curve.set_xticks(SNAPSHOTS, [SNAPSHOT_LABEL[year] for year in SNAPSHOTS])
    ax_curve.set_ylabel("SSP126–SSP585 对称相对差（%）")
    ax_curve.set_title("a  聚类中心与国家曲线", loc="left", fontweight="bold")
    ax_curve.legend(loc="best", fontsize=5.7)
    ax_curve.grid(axis="y", lw=0.35, alpha=0.4)

    valid_scores = scores[scores["eligible"]]
    invalid_scores = scores[~scores["eligible"]]
    ax_score.plot(
        valid_scores["requested_k"], valid_scores["silhouette_score"], "-o", color="#484878", lw=1.5, ms=4
    )
    if not invalid_scores.empty:
        ax_score.scatter(invalid_scores["requested_k"], np.zeros(len(invalid_scores)), marker="x", color="0.6", s=18)
    ax_score.set_xticks(scores["requested_k"].astype(int))
    ax_score.set_xlabel("类别数 k")
    ax_score.set_ylabel("轮廓系数")
    ax_score.set_title("b  类别数选择", loc="left", fontweight="bold")
    ax_score.grid(axis="y", lw=0.35, alpha=0.4)

    leaf_regions = [assignments.iloc[index]["region"] for index in leaves_list(tree)]
    order = (
        assignments.assign(_leaf=assignments["region"].map({region: i for i, region in enumerate(leaf_regions)}))
        .sort_values(["cluster", "_leaf"])
    )
    heat = order[[f"gap_{year}" for year in SNAPSHOTS]].to_numpy(dtype=float) * 100.0
    limit = max(20.0, float(np.nanmax(np.abs(heat))))
    image = ax_heat.imshow(
        heat,
        cmap="RdBu",
        norm=TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit),
        aspect="auto",
        interpolation="nearest",
    )
    ax_heat.set_xticks(np.arange(len(SNAPSHOTS)), [SNAPSHOT_LABEL[year] for year in SNAPSHOTS])
    labels = [f"C{row.cluster}  {row.region}" for row in order.itertuples()]
    ax_heat.set_yticks(np.arange(len(order)), labels)
    ax_heat.tick_params(axis="y", length=0, labelsize=6.2)
    for tick, cluster in zip(ax_heat.get_yticklabels(), order["cluster"]):
        tick.set_color(CLUSTER_COLORS[(int(cluster) - 1) % len(CLUSTER_COLORS)])
    ax_heat.set_title("c  国家情景差热图", loc="left", fontweight="bold")
    colorbar = fig.colorbar(image, ax=ax_heat, fraction=0.028, pad=0.025)
    colorbar.set_label("正值：SSP126 更高；负值：SSP585 更高（%）")

    metric_spec = METRIC_BY_KEY[metric]
    fig.suptitle(
        f"{TECH_LABEL[tech]}国家 {metric_spec.label} trade-off 聚类",
        fontsize=10,
        fontweight="bold",
        y=0.995,
    )
    stem = f"fig_RQ4_country_tradeoff_clusters_{tech}_{metric}"
    return save_figure(fig, output_dir, stem)


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
) -> list[Path]:
    configure_style()
    data = summary[summary["snapshot_year"].eq(snapshot)].copy()
    clusters = sorted(data["cluster"].unique())
    events = [event for event in EVENT_LABEL if event in set(data["event"])]
    residual_events = [event for event in events if event != "low_resource"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6), sharey=False)

    for ax, event_order, column, title in [
        (axes[0], events, "loss_weighted_share", "a  全部事件构成"),
        (axes[1], residual_events, "loss_weighted_residual_share", "b  非低资源事件构成"),
    ]:
        positions = []
        labels = []
        bottoms = []
        for cluster_index, cluster in enumerate(clusters):
            for scenario_index, scenario in enumerate(COMPARE_SSPS):
                positions.append(cluster_index * 2.6 + scenario_index)
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
            center = cluster_index * 2.6 + 0.5
            ax.text(center, -0.18, f"C{cluster}", transform=ax.get_xaxis_transform(), ha="center", va="top", fontweight="bold")
        ax.set_ylim(0, 100)
        ax.set_ylabel("正净损失事件池占比（%）")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.grid(axis="y", lw=0.35, alpha=0.35)
    handles = [Patch(facecolor=EVENT_COLOR[event], label=EVENT_LABEL[event]) for event in events]
    fig.legend(handles=handles, loc="upper center", ncol=min(5, len(handles)), bbox_to_anchor=(0.5, 0.965))
    metric_spec = METRIC_BY_KEY[metric]
    fig.suptitle(
        f"{TECH_LABEL[tech]}国家 {metric_spec.label} 聚类的极端事件构成（{snapshot}s）",
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
    station_csv = args.station_summary_csv or resolve_path(DEFAULT_STATION_SUMMARY_CSV, args.model)
    for path in (region_csv, station_csv):
        if not path.exists():
            raise SystemExit(f"未找到输入文件：{path}")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    csv_dir = output_dir / "csv"
    figure_dir = output_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    metrics, annual = load_country_metrics(
        model=args.model,
        region_csv=region_csv,
        station_summary_csv=station_csv,
    )
    events = load_country_event_losses(model=args.model, region_csv=region_csv)
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
            raw_labels, tree, scores = choose_partition(
                features,
                k_min=args.k_min,
                k_max=args.k_max,
                min_cluster_size=args.min_cluster_size,
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
