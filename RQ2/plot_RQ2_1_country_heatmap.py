#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2.1 图：国家尺度高风险转变和新增高风险容量比例热图。

图形问题：
    哪些国家的 2030 cohort 更容易从非高风险转入高风险区？
    哪些国家的 2050 新增容量在投产当年已经处于高风险区？
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from plot_RQ2_1_common import (
    SSP_LABEL,
    TECH_LABEL_CN,
    add_common_args,
    attach_high_risk,
    configure_style,
    high_risk_thresholds,
    load_or_build_station_year_risk,
    panel_tag,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2.1：国家尺度高风险转变/新增高风险比例热图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser = add_common_args(parser)
    parser.add_argument("--target-year", type=int, default=2050, help="转变目标年份，同时也是新增场站 cohort。")
    parser.add_argument("--top-n", type=int, default=14, help="每个热图显示的国家数量，按最大容量占比排序。")
    return parser.parse_args()


def country_metrics(risk: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """计算国家尺度的 cohort 转变比例和新增容量高风险比例。"""
    thresholds = high_risk_thresholds(risk, args.baseline_year, args.cohort_year, args.high_risk_quantile)
    tagged = attach_high_risk(risk, thresholds)

    cohort = tagged[tagged["activation_year"] == args.cohort_year].copy()
    base = cohort[cohort["year"] == args.baseline_year][
        ["station_key", "region", "ssp", "tech", "capacity_gw", "is_high_risk"]
    ].rename(columns={"is_high_risk": "baseline_high_risk"})
    target = cohort[cohort["year"] == args.target_year][["station_key", "is_high_risk"]].rename(
        columns={"is_high_risk": "target_high_risk"}
    )
    merged = base.merge(target, on="station_key", how="inner")

    transition_rows = []
    for (region, ssp, tech), sub in merged.groupby(["region", "ssp", "tech"], sort=False):
        denom = sub[(~sub["baseline_high_risk"])]["capacity_gw"].sum()
        new_high = sub[(~sub["baseline_high_risk"]) & (sub["target_high_risk"])]["capacity_gw"].sum()
        transition_rows.append(
            {
                "region": region,
                "ssp": ssp,
                "tech": tech,
                "metric": f"{args.cohort_year} cohort newly high by {args.target_year}",
                "capacity_share_pct": float(new_high / denom * 100.0) if denom > 0 else np.nan,
                "denominator_capacity_gw": float(denom),
            }
        )
    transition = pd.DataFrame(transition_rows)

    additions = tagged[(tagged["activation_year"] == args.target_year) & (tagged["year"] == args.target_year)].copy()
    addition_rows = []
    for (region, ssp, tech), sub in additions.groupby(["region", "ssp", "tech"], sort=False):
        denom = sub["capacity_gw"].sum()
        high = sub[sub["is_high_risk"]]["capacity_gw"].sum()
        addition_rows.append(
            {
                "region": region,
                "ssp": ssp,
                "tech": tech,
                "metric": f"{args.target_year} additions high at commissioning",
                "capacity_share_pct": float(high / denom * 100.0) if denom > 0 else np.nan,
                "denominator_capacity_gw": float(denom),
            }
        )
    additions_metric = pd.DataFrame(addition_rows)
    return transition, additions_metric, thresholds


def _pivot_top(metric_df: pd.DataFrame, tech: str, args: argparse.Namespace) -> pd.DataFrame:
    """把长表转成 SSP 列热图表，并保留风险比例最高的国家。"""
    sub = metric_df[metric_df["tech"] == tech].copy()
    if sub.empty:
        return pd.DataFrame(index=[], columns=args.ssps)
    pivot = sub.pivot_table(index="region", columns="ssp", values="capacity_share_pct", aggfunc="mean")
    pivot = pivot.reindex(columns=args.ssps)
    order = pivot.max(axis=1, skipna=True).sort_values(ascending=False).index[: args.top_n]
    return pivot.loc[order]


def _draw_heatmap(ax, table: pd.DataFrame, title: str, show_y: bool) -> None:
    """绘制单个国家-SSP 热图面板。"""
    arr = table.to_numpy(dtype=float)
    masked = np.ma.masked_invalid(arr)
    cmap = plt.cm.Reds.copy()
    cmap.set_bad("#eeeeee")
    im = ax.imshow(masked, aspect="auto", cmap=cmap, vmin=0, vmax=100)
    ax.set_title(title)
    ax.set_xticks(np.arange(len(table.columns)))
    ax.set_xticklabels([SSP_LABEL.get(c, c) for c in table.columns], rotation=35, ha="right")
    ax.set_yticks(np.arange(len(table.index)))
    ax.set_yticklabels(table.index if show_y else [])
    ax.tick_params(length=0)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            val = arr[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=5.5, color="black" if val < 55 else "white")
    return im


def plot_heatmap(transition: pd.DataFrame, additions: pd.DataFrame, args: argparse.Namespace):
    """绘制 2×2 国家尺度热图。"""
    configure_style()
    fig, axes = plt.subplots(2, 2, figsize=(7.8, 7.0))
    fig.subplots_adjust(left=0.18, right=0.89, top=0.88, bottom=0.13, hspace=0.34, wspace=0.22)

    last_im = None
    for row, tech in enumerate(["wind", "solar"]):
        trans_table = _pivot_top(transition, tech, args)
        add_table = _pivot_top(additions, tech, args)
        last_im = _draw_heatmap(
            axes[row, 0],
            trans_table,
            f"{TECH_LABEL_CN[tech]}：2030 cohort 非高风险转高风险",
            show_y=True,
        )
        _draw_heatmap(
            axes[row, 1],
            add_table,
            f"{TECH_LABEL_CN[tech]}：{args.target_year} 新增场站高风险",
            show_y=True,
        )
        panel_tag(axes[row, 0], chr(ord("a") + row * 2), x=-0.08, y=1.04)
        panel_tag(axes[row, 1], chr(ord("a") + row * 2 + 1), x=-0.08, y=1.04)

    cax = fig.add_axes([0.92, 0.22, 0.018, 0.56])
    cbar = fig.colorbar(last_im, cax=cax)
    cbar.set_label("容量占比（%）")
    fig.suptitle("RQ2.1：国家尺度高风险转变与新增高风险容量比例", fontsize=11, fontweight="bold", y=0.98)
    fig.text(
        0.5,
        0.045,
        f"左列分母为 {args.cohort_year} cohort 中基准年非高风险容量；右列分母为 {args.target_year} 新增容量。灰色表示缺失或无分母容量。",
        ha="center",
        fontsize=6.3,
        color="0.4",
    )
    return fig


def main() -> None:
    args = parse_args()
    risk, missing = load_or_build_station_year_risk(args)
    transition, additions, thresholds = country_metrics(risk, args)

    transition_csv = args.csv_dir / "RQ2_1_country_transition_heatmap.csv"
    additions_csv = args.csv_dir / "RQ2_1_country_newbuild_heatmap.csv"
    threshold_csv = args.csv_dir / "RQ2_1_high_risk_thresholds.csv"
    transition.to_csv(transition_csv, index=False)
    additions.to_csv(additions_csv, index=False)
    thresholds.to_csv(threshold_csv, index=False)
    if not missing.empty:
        missing.to_csv(args.csv_dir / "RQ2_1_missing_inputs.csv", index=False)

    fig = plot_heatmap(transition, additions, args)
    paths = save_figure(fig, args.output_dir / "fig_RQ2_1_country_heatmap", save_vector=args.save_vector)
    print(f"saved transition csv: {transition_csv}")
    print(f"saved additions csv: {additions_csv}")
    print(f"saved thresholds: {threshold_csv}")
    for path in paths:
        print(f"saved figure: {path}")


if __name__ == "__main__":
    main()
