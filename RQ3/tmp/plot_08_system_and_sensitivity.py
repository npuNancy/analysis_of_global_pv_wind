#!/usr/bin/env python3
"""图 8：国家风光联合风险与净/单向损失口径敏感性。"""

from __future__ import annotations

import argparse

import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    SSP_COLOR, SSP_LABEL, SSPS, TECH_LABEL, TECHS, add_common_args,
    configure_style, global_annual, load_region, output_dir, panel_tag,
    save_figure, write_source,
)


MARKER = {2030: "o", 2040: "s", 2050: "^"}


def build_joint(region: pd.DataFrame) -> pd.DataFrame:
    data = region[region["event"] == "all"].copy()
    country = (
        data.groupby(["scenario", "tech", "snapshot_year", "analysis_year", "region"], as_index=False)
        .agg(loss_mwh=("net_generation_loss_mwh", "sum"), normal_mwh=("normal_all_generation_mwh", "sum"))
        .groupby(["scenario", "tech", "snapshot_year", "region"], as_index=False)[["loss_mwh", "normal_mwh"]]
        .mean()
    )
    country["loss_rate_pct"] = country["loss_mwh"] / country["normal_mwh"] * 100.0
    wide = country.pivot_table(
        index=["scenario", "snapshot_year", "region"], columns="tech", values=["loss_rate_pct", "normal_mwh"]
    )
    wide.columns = [f"{metric}_{tech}" for metric, tech in wide.columns]
    return wide.reset_index().dropna(subset=["loss_rate_pct_wind", "loss_rate_pct_solar"])


def build_sensitivity(region: pd.DataFrame) -> pd.DataFrame:
    annual = global_annual(region)
    annual = annual[annual["event"] == "all"].copy()
    annual["net_rate_pct"] = annual["net_loss_mwh"] / annual["normal_all_mwh"] * 100.0
    annual["gross_rate_pct"] = annual["gross_loss_mwh"] / annual["normal_all_mwh"] * 100.0
    return (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(net_rate_pct=("net_rate_pct", "mean"), gross_rate_pct=("gross_rate_pct", "mean"))
    )


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    region = load_region(args.model)
    joint = build_joint(region)
    sensitivity = build_sensitivity(region)
    write_source(joint, out, "fig08_joint_wind_solar_risk.csv")
    write_source(sensitivity, out, "fig08_metric_sensitivity.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.25))
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.2, top=0.78, wspace=0.33)
    ax = axes[0]
    for (scenario, snapshot), group in joint.groupby(["scenario", "snapshot_year"]):
        size = 6 + 22 * np.sqrt(
            (group["normal_mwh_wind"] + group["normal_mwh_solar"])
            / (joint["normal_mwh_wind"] + joint["normal_mwh_solar"]).max()
        )
        ax.scatter(
            group["loss_rate_pct_wind"], group["loss_rate_pct_solar"],
            s=size, marker=MARKER[int(snapshot)], color=SSP_COLOR[scenario],
            alpha=0.55, edgecolors="white", linewidths=0.25,
        )
    ax.set_xlabel("风电净损失率（%）")
    ax.set_ylabel("光伏净损失率（%）")
    ax.set_title("国家风光联合风险")
    ax.grid(lw=0.35, alpha=0.35)
    color_handles = [mlines.Line2D([], [], color=SSP_COLOR[s], marker="o", ls="", label=SSP_LABEL[s]) for s in SSPS]
    marker_handles = [mlines.Line2D([], [], color="0.35", marker=MARKER[y], ls="", label=f"{y}s") for y in [2030, 2040, 2050]]
    ax.legend(handles=color_handles + marker_handles, fontsize=5.2, ncol=2, loc="best")

    for index, tech in enumerate(TECHS, start=1):
        ax = axes[index]
        for scenario in SSPS:
            sub = sensitivity[(sensitivity["tech"] == tech) & (sensitivity["scenario"] == scenario)].sort_values("snapshot_year")
            ax.plot(sub["snapshot_year"], sub["net_rate_pct"], "-o", color=SSP_COLOR[scenario], lw=1.5, ms=3)
            ax.plot(sub["snapshot_year"], sub["gross_rate_pct"], "--", color=SSP_COLOR[scenario], lw=1.1)
        ax.set_xticks([2030, 2040, 2050], ["30s", "40s", "50s"])
        ax.set_ylabel("损失率（%）")
        ax.set_title(f"{TECH_LABEL[tech]}：净损失 vs 单向损失")
        ax.grid(axis="y", lw=0.35, alpha=0.4)
    for index, ax in enumerate(axes):
        panel_tag(ax, chr(ord("a") + index))
    metric_handles = [
        mlines.Line2D([], [], color="0.25", ls="-", marker="o", ms=3, label="净损失"),
        mlines.Line2D([], [], color="0.25", ls="--", label="单向损失"),
    ]
    axes[1].legend(handles=metric_handles, loc="best")
    fig.suptitle(f"系统联合风险与指标口径敏感性（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.03,
        "联合风险点为国家—SSP—年代均值；净损失允许事件期增发抵消，单向损失仅累计 CF 低于正常值的时刻。",
        ha="center", fontsize=6.1, color="0.4",
    )
    save_figure(fig, out, "fig08_system_and_sensitivity")


if __name__ == "__main__":
    main()
