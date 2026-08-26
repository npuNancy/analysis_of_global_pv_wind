#!/usr/bin/env python3
"""图 10：SSP1-2.6 与 SSP5-8.5 净损失总量差距的二因素 Shapley 分解。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from common import (
    SSP_COLOR,
    SSP_LABEL,
    TECH_LABEL,
    TECHS,
    add_common_args,
    configure_style,
    global_annual,
    load_region,
    output_dir,
    panel_tag,
    save_figure,
    write_source,
)


COMPARE_SSPS = ["ssp126", "ssp585"]
SNAPSHOTS = [2030, 2040, 2050]


def build_data(model: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """以全球容量与单位容量损失强度构造跨情景反事实并做 Shapley 分解。"""
    annual = global_annual(load_region(model))
    annual = annual[
        annual["event"].eq("all") & annual["scenario"].isin(COMPARE_SSPS)
    ].copy()
    period = (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            loss_mwh_mean=("net_loss_mwh", "mean"),
            loss_mwh_min=("net_loss_mwh", "min"),
            loss_mwh_max=("net_loss_mwh", "max"),
            capacity_mw=("capacity_mw", "mean"),
            n_years=("analysis_year", "nunique"),
        )
    )
    period["loss_twh_mean"] = period["loss_mwh_mean"] / 1e6
    period["loss_twh_min"] = period["loss_mwh_min"] / 1e6
    period["loss_twh_max"] = period["loss_mwh_max"] / 1e6
    period["loss_intensity_mwh_per_mw_year"] = (
        period["loss_mwh_mean"] / period["capacity_mw"]
    )

    rows: list[dict[str, float | int | str]] = []
    for tech in TECHS:
        for snapshot_year in SNAPSHOTS:
            group = period[
                period["tech"].eq(tech) & period["snapshot_year"].eq(snapshot_year)
            ].set_index("scenario")
            low = group.loc["ssp126"]
            high = group.loc["ssp585"]
            capacity_low = float(low["capacity_mw"])
            capacity_high = float(high["capacity_mw"])
            intensity_low = float(low["loss_intensity_mwh_per_mw_year"])
            intensity_high = float(high["loss_intensity_mwh_per_mw_year"])

            # L(D, C)：D 取某情景的全球装机规模，C 取某情景的全球单位容量损失强度。
            l_high_high = capacity_high * intensity_high / 1e6
            l_low_high = capacity_low * intensity_high / 1e6
            l_high_low = capacity_high * intensity_low / 1e6
            l_low_low = capacity_low * intensity_low / 1e6
            deployment_effect = 0.5 * (
                (l_low_high - l_high_high) + (l_low_low - l_high_low)
            )
            intensity_effect = 0.5 * (
                (l_high_low - l_high_high) + (l_low_low - l_low_high)
            )
            total_gap = l_low_low - l_high_high
            if not np.isclose(deployment_effect + intensity_effect, total_gap):
                raise AssertionError(f"{tech}/{snapshot_year} 的跨情景 Shapley 分解未闭合。")
            rows.append(
                {
                    "tech": tech,
                    "snapshot_year": snapshot_year,
                    "ssp126_loss_twh": l_low_low,
                    "ssp585_loss_twh": l_high_high,
                    "ssp126_minus_ssp585_twh": total_gap,
                    "deployment_effect_twh": deployment_effect,
                    "loss_intensity_effect_twh": intensity_effect,
                    "capacity_ratio_ssp126_to_ssp585": capacity_low / capacity_high,
                    "loss_intensity_ratio_ssp126_to_ssp585": intensity_low / intensity_high,
                    "counterfactual_D126_C585_twh": l_low_high,
                    "counterfactual_D585_C126_twh": l_high_low,
                }
            )
    return period, pd.DataFrame(rows)


def plot_data(observed: pd.DataFrame, shapley: pd.DataFrame, model: str, out_dir) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(7.4, 5.5), sharex="row")
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.13, top=0.89, hspace=0.42, wspace=0.28)
    x = np.arange(len(SNAPSHOTS), dtype=float)

    for col, tech in enumerate(TECHS):
        ax = axes[0, col]
        for scenario in COMPARE_SSPS:
            sub = observed[
                observed["tech"].eq(tech) & observed["scenario"].eq(scenario)
            ].set_index("snapshot_year").reindex(SNAPSHOTS)
            mean = sub["loss_twh_mean"].to_numpy(dtype=float)
            low = sub["loss_twh_min"].to_numpy(dtype=float)
            high = sub["loss_twh_max"].to_numpy(dtype=float)
            ax.errorbar(
                x, mean, yerr=[mean - low, high - mean], fmt="-o",
                color=SSP_COLOR[scenario], lw=1.7, ms=4, capsize=2.5,
                elinewidth=0.8, label=SSP_LABEL[scenario],
            )
        gap_data = (
            shapley[shapley["tech"].eq(tech)]
            .set_index("snapshot_year")
            .reindex(SNAPSHOTS)
        )
        midpoints = (
            gap_data["ssp126_loss_twh"].to_numpy(dtype=float)
            + gap_data["ssp585_loss_twh"].to_numpy(dtype=float)
        ) / 2.0
        for xpos, gap, ypos in zip(x, gap_data["ssp126_minus_ssp585_twh"], midpoints):
            ax.text(
                xpos, ypos, f"差距 {gap:.1f}", ha="center", va="center",
                fontsize=5.7, color="0.35",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 0.8},
            )
        ax.set_title(f"{TECH_LABEL[tech]}：全球净损失总量")
        ax.set_ylabel("净出力损失（TWh/年）")
        ax.set_xticks(x, ["2030s", "2040s", "2050s"])
        ax.grid(axis="y", lw=0.35, alpha=0.4)
        panel_tag(ax, chr(ord("a") + col))
        if col == 0:
            ax.legend(loc="upper left")

        ax = axes[1, col]
        sub = shapley[shapley["tech"].eq(tech)].set_index("snapshot_year").reindex(SNAPSHOTS)
        width = 0.32
        deployment = sub["deployment_effect_twh"].to_numpy(dtype=float)
        intensity = sub["loss_intensity_effect_twh"].to_numpy(dtype=float)
        total = sub["ssp126_minus_ssp585_twh"].to_numpy(dtype=float)
        ax.bar(x - width / 2, deployment, width, color="#4c78a8", label="装机规模效应")
        ax.bar(x + width / 2, intensity, width, color="#e45756", label="单位容量损失强度效应")
        ax.scatter(x, total, marker="D", s=20, color="#222222", zorder=3, label="总差距")
        for xpos, value in zip(x, intensity):
            ax.text(
                xpos + width / 2, value, f"{value:+.1f}", ha="center",
                va="bottom" if value >= 0 else "top", fontsize=5.7,
            )
        ax.axhline(0, color="0.25", lw=0.7)
        ax.set_xticks(x, ["2030s", "2040s", "2050s"])
        ax.set_ylabel("SSP1-2.6 − SSP5-8.5（TWh/年）")
        ax.set_title(f"{TECH_LABEL[tech]}：情景差距 Shapley 分解")
        ax.grid(axis="y", lw=0.35, alpha=0.4)
        panel_tag(ax, chr(ord("c") + col))
        if col == 0:
            handles = [
                Line2D([0], [0], color="#4c78a8", lw=5, label="装机规模效应"),
                Line2D([0], [0], color="#e45756", lw=5, label="单位容量损失强度效应"),
                Line2D([0], [0], color="#222222", marker="D", lw=0, ms=4, label="总差距"),
            ]
            ax.legend(handles=handles, loc="upper left", fontsize=5.8)

    fig.suptitle(
        f"SSP1-2.6 为何比 SSP5-8.5 损失总量更高（{model}）",
        fontsize=10.5, fontweight="bold",
    )
    fig.text(
        0.5, 0.035,
        "跨情景恒等式：L = 全球装机容量 × 全球单位容量净损失强度；"
        "Shapley 将 SSP1-2.6−SSP5-8.5 的差距分为两项。风电发电量与损失能量项采用临时 0.1 修正。",
        ha="center", fontsize=6.1, color="0.4",
    )
    save_figure(fig, out_dir, "fig10_ssp126_ssp585_gap_decomposition")


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    observed, shapley = build_data(args.model)
    write_source(observed, out, "fig10_observed_loss_and_intensity.csv")
    write_source(shapley, out, "fig10_scenario_gap_shapley.csv")
    plot_data(observed, shapley, args.model, out)


if __name__ == "__main__":
    main()
