#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2.1 图（绝对值版）：2030 cohort 高风险区转变的【绝对容量 (GW)】堆叠柱图。

与 plot_RQ2_1_cohort_transition.py 完全一致，唯一区别：
    纵坐标由 "容量占比 (%)" 改为 "绝对容量 (GW)"。
分组、颜色、cohort 年份、高风险阈值口径、数据来源均与百分比版相同。

说明：
    - 数据直接复用百分比版 transition_summary() 输出的 capacity_gw 列，
      因此本脚本不再重复落盘 CSV（内容与 RQ2_1_cohort_transition.csv 完全一致）。
    - 风电 / 光伏 cohort 总容量量级不同，百分比版因统一 0–100% 可共享 y 轴；
      改为绝对值后取消 sharey，两个面板各自自适应 y 轴，避免光伏被风电量级压扁。
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
    configure_style,
    load_or_build_station_year_risk,
    normalize_args,
    panel_tag,
    save_figure,
)
from plot_RQ2_1_cohort_transition import transition_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2.1：2030 cohort 转入高风险区的【绝对容量 (GW)】堆叠柱图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    return add_common_args(parser).parse_args()


def plot_transition_absolute(summary: pd.DataFrame, args: argparse.Namespace):
    """绘制 2030 cohort 的高风险转变堆叠柱图（纵坐标 = 容量 GW）。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.45), sharey=False)
    fig.subplots_adjust(left=0.10, right=0.98, top=0.77, bottom=0.24, wspace=0.22)
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
                    vals.append(float(sub["capacity_gw"].iloc[0]) if not sub.empty else 0.0)
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
        ax.set_ylim(0, None)
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    axes[0].set_ylabel("容量（GW）")
    handles = [Patch(fc=TRANSITION_COLOR[t], ec="none", label=TRANSITION_LABEL[t]) for t in transitions]
    fig.legend(handles=handles, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 0.96))
    fig.suptitle("RQ2.1：2030 cohort 转入高风险区的容量（GW）", fontsize=11, fontweight="bold", y=1.02)
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
    args = normalize_args(parse_args())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.csv_dir.mkdir(parents=True, exist_ok=True)

    risk, missing = load_or_build_station_year_risk(args)
    summary, thresholds = transition_summary(risk, args)

    fig = plot_transition_absolute(summary, args)
    paths = save_figure(fig, args.output_dir / "fig_RQ2_1_cohort_transition_absolute", save_vector=args.save_vector)
    print(f"复用汇总表：{args.csv_dir / 'RQ2_1_cohort_transition.csv'}")
    for path in paths:
        print(f"saved figure: {path}")


if __name__ == "__main__":
    main()
