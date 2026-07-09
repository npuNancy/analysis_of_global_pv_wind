#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2.1 图：新增场站一投产即处于高风险区的容量比例。

图形问题：
    相比 2030 cohort，2040/2050 年新增场站在投产当年有多少容量
    已经落入高风险区？

本图只绘制容量加权比例，不绘制场站数量比例。
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
    attach_high_risk,
    configure_style,
    high_risk_thresholds,
    load_or_build_station_year_risk,
    panel_tag,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2.1：2040/2050 新增场站落入高风险区的容量比例。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    return add_common_args(parser).parse_args()


def newbuild_summary(risk: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算各建设 cohort 在投产当年处于高风险区的容量比例。"""
    thresholds = high_risk_thresholds(risk, args.baseline_year, args.cohort_year, args.high_risk_quantile)
    tagged = attach_high_risk(risk, thresholds)

    rows = []
    for cohort_year in sorted(args.years):
        sub = tagged[(tagged["activation_year"] == cohort_year) & (tagged["year"] == cohort_year)].copy()
        for (ssp, tech), d in sub.groupby(["ssp", "tech"], sort=False):
            denom_cap = float(d["capacity_gw"].sum())
            high = d[d["is_high_risk"]]
            rows.append(
                {
                    "ssp": ssp,
                    "tech": tech,
                    "cohort_year": int(cohort_year),
                    "eval_year": int(cohort_year),
                    "high_risk_capacity_gw": float(high["capacity_gw"].sum()),
                    "total_capacity_gw": denom_cap,
                    "high_risk_capacity_share_pct": float(high["capacity_gw"].sum() / denom_cap * 100.0) if denom_cap > 0 else np.nan,
                    "high_risk_station_count": int(len(high)),
                    "station_count": int(len(d)),
                    "high_risk_station_share_pct": float(len(high) / len(d) * 100.0) if len(d) else np.nan,
                }
            )
    return pd.DataFrame(rows).sort_values(["tech", "ssp", "cohort_year"]), thresholds


def plot_newbuild(summary: pd.DataFrame, args: argparse.Namespace):
    """绘制新增场站的高风险容量占比。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.35), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.78, bottom=0.2, wspace=0.16)

    for ax, tech, tag in zip(axes, ["wind", "solar"], ["a", "b"]):
        dtech = summary[summary["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["ssp"] == ssp].sort_values("cohort_year")
            if sub.empty:
                continue
            color = SSP_COLOR.get(ssp, "0.3")
            ax.plot(
                sub["cohort_year"],
                sub["high_risk_capacity_share_pct"],
                marker="o",
                ms=4,
                lw=1.8,
                color=color,
                label=SSP_LABEL.get(ssp, ssp),
            )
        ax.set_title(f"{TECH_LABEL_CN[tech]}：新增场站高风险比例")
        ax.set_xlabel("建设 cohort / 投产年份")
        ax.set_xticks(sorted(summary["cohort_year"].unique()))
        ax.set_ylim(0, 100)
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    axes[0].set_ylabel("高风险占比（%）")
    color_handles = [
        Line2D([0], [0], color=SSP_COLOR.get(ssp, "0.3"), lw=1.8, marker="o", label=SSP_LABEL.get(ssp, ssp))
        for ssp in args.ssps
    ]
    fig.legend(handles=color_handles, loc="upper center", ncol=len(color_handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle("RQ2.1：新增场站一投产即处于高风险区的比例", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.04,
        f"高风险阈值固定为 {args.baseline_year} 年 {args.cohort_year} cohort 的容量加权 P{int(args.high_risk_quantile * 100)}；新增场站按投产当年风险评估。",
        ha="center",
        fontsize=6.3,
        color="0.4",
    )
    return fig


def main() -> None:
    args = parse_args()
    risk, missing = load_or_build_station_year_risk(args)
    summary, thresholds = newbuild_summary(risk, args)

    out_csv = args.csv_dir / "RQ2_1_newbuild_highrisk_share.csv"
    threshold_csv = args.csv_dir / "RQ2_1_high_risk_thresholds.csv"
    summary.to_csv(out_csv, index=False)
    thresholds.to_csv(threshold_csv, index=False)
    if not missing.empty:
        missing.to_csv(args.csv_dir / "RQ2_1_missing_inputs.csv", index=False)

    fig = plot_newbuild(summary, args)
    paths = save_figure(fig, args.output_dir / "fig_RQ2_1_newbuild_highrisk_share", save_vector=args.save_vector)
    print(f"saved csv: {out_csv}")
    print(f"saved thresholds: {threshold_csv}")
    for path in paths:
        print(f"saved figure: {path}")


if __name__ == "__main__":
    main()
