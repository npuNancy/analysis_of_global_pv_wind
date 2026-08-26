#!/usr/bin/env python3
"""图 1：净损失增长的 LMDI 诊断分解。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    SSP_LABEL, SSPS, TECH_LABEL, TECHS, add_common_args, configure_style,
    global_annual, load_region, output_dir, panel_tag, save_figure, write_source,
)


def log_mean(x1: float, x0: float) -> float:
    if np.isclose(x1, x0):
        return float(x0)
    return float((x1 - x0) / (np.log(x1) - np.log(x0)))


def build_decomposition(model: str) -> pd.DataFrame:
    annual = global_annual(load_region(model))
    annual = annual[annual["event"] == "all"].copy()
    period = (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            loss_mwh=("net_loss_mwh", "mean"),
            normal_all_mwh=("normal_all_mwh", "mean"),
            capacity_mw=("capacity_mw", "mean"),
        )
    )
    period["normal_full_load_hours"] = period["normal_all_mwh"] / period["capacity_mw"]
    period["loss_rate"] = period["loss_mwh"] / period["normal_all_mwh"]
    rows = []
    for (scenario, tech), group in period.groupby(["scenario", "tech"]):
        start = group[group["snapshot_year"] == 2030].iloc[0]
        end = group[group["snapshot_year"] == 2050].iloc[0]
        scale = log_mean(end["loss_mwh"], start["loss_mwh"])
        capacity_effect = scale * np.log(end["capacity_mw"] / start["capacity_mw"])
        resource_effect = scale * np.log(
            end["normal_full_load_hours"] / start["normal_full_load_hours"]
        )
        risk_effect = scale * np.log(end["loss_rate"] / start["loss_rate"])
        rows.append(
            {
                "scenario": scenario,
                "tech": tech,
                "capacity_effect_twh": capacity_effect / 1e6,
                "normal_resource_effect_twh": resource_effect / 1e6,
                "extreme_risk_effect_twh": risk_effect / 1e6,
                "total_change_twh": (end["loss_mwh"] - start["loss_mwh"]) / 1e6,
                "loss_growth_factor": end["loss_mwh"] / start["loss_mwh"],
                "capacity_growth_factor": end["capacity_mw"] / start["capacity_mw"],
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    data = build_decomposition(args.model)
    write_source(data, out, "fig01_loss_growth_decomposition.csv")

    fig, axes = plt.subplots(2, 3, figsize=(7.4, 5.45))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.2, top=0.87, hspace=0.52, wspace=0.32)
    colors = ["#4c78a8", "#72b7b2", "#e45756", "#777777"]
    labels = ["装机规模", "正常满发小时", "极端损失率", "总变化"]
    for row, tech in enumerate(TECHS):
        for col, scenario in enumerate(SSPS):
            ax = axes[row, col]
            item = data[(data["tech"] == tech) & (data["scenario"] == scenario)].iloc[0]
            values = [
                item["capacity_effect_twh"], item["normal_resource_effect_twh"],
                item["extreme_risk_effect_twh"], item["total_change_twh"],
            ]
            bars = ax.bar(range(4), values, color=colors, width=0.72)
            ax.axhline(0, color="0.25", lw=0.7)
            ax.set_xticks(range(4), labels, rotation=28, ha="right")
            ax.set_title(f"{TECH_LABEL[tech]} · {SSP_LABEL[scenario]}")
            ax.set_ylabel("2030s→2050s 贡献（TWh/年）")
            ax.grid(axis="y", lw=0.35, alpha=0.4)
            for bar, value in zip(bars, values):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    value,
                    f"{value:.1f}",
                    ha="center",
                    va="bottom" if value >= 0 else "top",
                    fontsize=5.8,
                )
            panel_tag(ax, chr(ord("a") + row * 3 + col))
    fig.suptitle(
        f"净出力损失增长的 LMDI 诊断分解（{args.model}）",
        fontsize=10.5, fontweight="bold",
    )
    fig.text(
        0.5, 0.025,
        "L = 装机容量 × 正常满发小时 × 极端损失率；该图是恒等式分解，正常资源和损失率仍包含场站构成效应，不能单独视为纯气候因果效应。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig01_loss_growth_decomposition")


if __name__ == "__main__":
    main()
