#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2.1 图：2030 cohort 的高风险区转变比例。

图形问题：
    2030 年建设的场站，在 2040/2050 年有多少容量从非高风险区
    转入高风险区？有多少容量持续处于高风险区？

高风险阈值：
    默认使用各 SSP-技术在 2030 年、2030 cohort 风险分布的容量加权 P80。
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from plot_RQ2_1_common import (
    SSP_LABEL,
    TECH_LABEL_CN,
    TRANSITION_COLOR,
    TRANSITION_LABEL,
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
        description="RQ2.1：2030 cohort 从非高风险转入高风险的容量比例。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    return add_common_args(parser).parse_args()


def transition_summary(risk: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算 2030 cohort 从基准风险等级到目标年份风险等级的容量占比。"""
    thresholds = high_risk_thresholds(risk, args.baseline_year, args.cohort_year, args.high_risk_quantile)
    tagged = attach_high_risk(risk, thresholds)
    cohort = tagged[tagged["activation_year"] == args.cohort_year].copy()

    base = cohort[cohort["year"] == args.baseline_year][
        ["station_key", "region", "ssp", "tech", "capacity_gw", "is_high_risk"]
    ].rename(columns={"is_high_risk": "baseline_high_risk"})

    rows = []
    for target_year in [y for y in sorted(args.years) if y != args.baseline_year]:
        target = cohort[cohort["year"] == target_year][["station_key", "risk_days", "is_high_risk"]].rename(
            columns={"is_high_risk": "target_high_risk", "risk_days": "target_risk_days"}
        )
        merged = base.merge(target, on="station_key", how="inner")
        if merged.empty:
            continue
        merged["transition"] = np.select(
            [
                (~merged["baseline_high_risk"]) & (~merged["target_high_risk"]),
                (~merged["baseline_high_risk"]) & (merged["target_high_risk"]),
                (merged["baseline_high_risk"]) & (merged["target_high_risk"]),
                (merged["baseline_high_risk"]) & (~merged["target_high_risk"]),
            ],
            ["remain_non_high", "new_high", "remain_high", "deescalate"],
            default="remain_non_high",
        )
        for (ssp, tech, transition), sub in merged.groupby(["ssp", "tech", "transition"], sort=False):
            denom_cap = merged[(merged["ssp"] == ssp) & (merged["tech"] == tech)]["capacity_gw"].sum()
            denom_n = len(merged[(merged["ssp"] == ssp) & (merged["tech"] == tech)])
            rows.append(
                {
                    "ssp": ssp,
                    "tech": tech,
                    "target_year": int(target_year),
                    "transition": transition,
                    "capacity_gw": float(sub["capacity_gw"].sum()),
                    "capacity_share_pct": float(sub["capacity_gw"].sum() / denom_cap * 100.0) if denom_cap > 0 else np.nan,
                    "station_count": int(len(sub)),
                    "station_share_pct": float(len(sub) / denom_n * 100.0) if denom_n > 0 else np.nan,
                }
            )
    return pd.DataFrame(rows), thresholds


def plot_transition(summary: pd.DataFrame, args: argparse.Namespace):
    """绘制 2030 cohort 的高风险转变堆叠柱图。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.45), sharey=True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.77, bottom=0.24, wspace=0.16)
    transitions = ["remain_non_high", "new_high", "remain_high", "deescalate"]

    for ax, tech, tag in zip(axes, ["wind", "solar"], ["a", "b"]):
        labels = []
        x = []
        cursor = 0
        for ssp in args.ssps:
            for year in [y for y in sorted(args.years) if y != args.baseline_year]:
                labels.append(f"{SSP_LABEL.get(ssp, ssp)}\n{year}")
                x.append(cursor)
                cursor += 1
            cursor += 0.5
        x = np.asarray(x)
        bottom = np.zeros(len(x), dtype=float)

        for transition in transitions:
            vals = []
            for ssp in args.ssps:
                for year in [y for y in sorted(args.years) if y != args.baseline_year]:
                    sub = summary[
                        (summary["tech"] == tech)
                        & (summary["ssp"] == ssp)
                        & (summary["target_year"] == year)
                        & (summary["transition"] == transition)
                    ]
                    vals.append(float(sub["capacity_share_pct"].iloc[0]) if not sub.empty else 0.0)
            vals = np.asarray(vals)
            ax.bar(
                x,
                vals,
                bottom=bottom,
                width=0.72,
                color=TRANSITION_COLOR[transition],
                edgecolor="white",
                linewidth=0.45,
            )
            bottom += vals

        ax.set_title(f"{TECH_LABEL_CN[tech]}：{args.cohort_year} cohort 风险等级变化")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=35, ha="right")
        ax.set_ylim(0, 100)
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    axes[0].set_ylabel("容量占比（%）")
    handles = [Patch(fc=TRANSITION_COLOR[t], ec="none", label=TRANSITION_LABEL[t]) for t in transitions]
    fig.legend(handles=handles, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 0.96))
    fig.suptitle("RQ2.1：2030 cohort 转入高风险区的容量比例", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.055,
        f"高风险阈值为各 SSP-技术在 {args.baseline_year} 年 {args.cohort_year} cohort 风险分布的容量加权 P{int(args.high_risk_quantile * 100)}。",
        ha="center",
        fontsize=6.3,
        color="0.4",
    )
    return fig


def main() -> None:
    args = parse_args()
    risk, missing = load_or_build_station_year_risk(args)
    summary, thresholds = transition_summary(risk, args)

    out_csv = args.csv_dir / "RQ2_1_cohort_transition.csv"
    threshold_csv = args.csv_dir / "RQ2_1_high_risk_thresholds.csv"
    summary.to_csv(out_csv, index=False)
    thresholds.to_csv(threshold_csv, index=False)
    if not missing.empty:
        missing.to_csv(args.csv_dir / "RQ2_1_missing_inputs.csv", index=False)

    fig = plot_transition(summary, args)
    paths = save_figure(fig, args.output_dir / "fig_RQ2_1_cohort_transition", save_vector=args.save_vector)
    print(f"saved csv: {out_csv}")
    print(f"saved thresholds: {threshold_csv}")
    for path in paths:
        print(f"saved figure: {path}")


if __name__ == "__main__":
    main()
