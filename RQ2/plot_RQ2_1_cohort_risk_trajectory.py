#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2.1 图：2030 cohort 的未来极端天气风险轨迹。

图形问题：
    同一批 2030 年投产/建设的场站，在 2030、2040、2050 年的
    容量加权极端天气风险时长如何随 SSP 路径变化？

指标：
    capacity-weighted risk days = sum(risk_days * capacity_gw) / sum(capacity_gw)
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_RQ2_1_common import (
    SSP_COLOR,
    SSP_LABEL,
    TECH_LABEL_CN,
    add_common_args,
    capacity_weighted_mean,
    configure_style,
    load_or_build_station_year_risk,
    panel_tag,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2.1：2030 cohort 在 2030/2040/2050 的容量加权风险时长。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    return add_common_args(parser).parse_args()


def summarize_trajectory(risk: pd.DataFrame, cohort_year: int) -> pd.DataFrame:
    """汇总指定建设 cohort 在各年份的容量加权风险时长。"""
    cohort = risk[risk["activation_year"] == cohort_year].copy()
    rows = []
    for (ssp, tech, year), sub in cohort.groupby(["ssp", "tech", "year"], sort=False):
        rows.append(
            {
                "ssp": ssp,
                "tech": tech,
                "year": int(year),
                "cohort_year": cohort_year,
                "capacity_weighted_risk_days": capacity_weighted_mean(sub),
                "station_count": int(len(sub)),
                "capacity_gw": float(sub["capacity_gw"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["tech", "ssp", "year"])


def plot_trajectory(summary: pd.DataFrame, args: argparse.Namespace):
    """绘制 2030 cohort 的容量加权风险轨迹。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.25), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.78, bottom=0.2, wspace=0.28)

    for ax, tech, tag in zip(axes, ["wind", "solar"], ["a", "b"]):
        dtech = summary[summary["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["ssp"] == ssp].sort_values("year")
            if sub.empty:
                continue
            ax.plot(
                sub["year"],
                sub["capacity_weighted_risk_days"],
                marker="o",
                ms=4,
                lw=1.8,
                color=SSP_COLOR.get(ssp, "0.3"),
                label=SSP_LABEL.get(ssp, ssp),
            )
        ax.set_title(f"{TECH_LABEL_CN[tech]}：{args.cohort_year} 年建设场站")
        ax.set_xlabel("评估年份")
        ax.set_xticks(sorted(summary["year"].unique()))
        ymax = np.nanmax(dtech["capacity_weighted_risk_days"].to_numpy()) if not dtech.empty else 0
        ax.set_ylim(bottom=0, top=max(ymax * 1.18, 0.01))
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    axes[0].set_ylabel("容量加权风险时长（天/GW年）")

    handles = [
        Line2D([0], [0], color=SSP_COLOR.get(ssp, "0.3"), marker="o", lw=1.8, label=SSP_LABEL.get(ssp, ssp))
        for ssp in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle("RQ2.1：2030 cohort 的未来极端天气风险轨迹", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.04,
        "风险时长为任一支持极端事件发生的时间步折算天数；每个场站按装机容量加权。",
        ha="center",
        fontsize=6.3,
        color="0.4",
    )
    return fig


def main() -> None:
    args = parse_args()
    risk, missing = load_or_build_station_year_risk(args)
    summary = summarize_trajectory(risk, args.cohort_year)

    out_csv = args.csv_dir / "RQ2_1_cohort_risk_trajectory.csv"
    summary.to_csv(out_csv, index=False)
    if not missing.empty:
        missing.to_csv(args.csv_dir / "RQ2_1_missing_inputs.csv", index=False)

    fig = plot_trajectory(summary, args)
    paths = save_figure(fig, args.output_dir / "fig_RQ2_1_cohort_risk_trajectory", save_vector=args.save_vector)
    print(f"saved csv: {out_csv}")
    for path in paths:
        print(f"saved figure: {path}")


if __name__ == "__main__":
    main()
