#!/usr/bin/env python3
"""候选方案 1：总损失—综合损失率二维权衡轨迹图。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_trade_off_common import (
    DECADE_LABEL,
    DECADE_MARKER,
    SCENARIOS,
    SNAPSHOTS,
    SSP_C,
    SSP_L,
    add_common_args,
    asymmetric_error,
    build_trade_off_decade,
    configure_trade_off_style,
    get_output_dir,
    load_trade_off_annual,
    save_figure,
    write_source,
)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = get_output_dir(args.model, args.output_dir)
    configure_trade_off_style()
    data = build_trade_off_decade(load_trade_off_annual(args.model))
    write_source(data, out, "trade_off_quadrant.csv")

    fig, ax = plt.subplots(figsize=(7.4, 4.75))
    fig.subplots_adjust(left=0.12, right=0.97, bottom=0.20, top=0.84)

    # 同一年代连接 SSP1-2.6 与 SSP5-8.5，直接展示“总量高但比例低”的横截面权衡。
    for snapshot_year in SNAPSHOTS:
        cross = data[
            data["snapshot_year"].eq(snapshot_year)
            & data["scenario"].isin(["ssp126", "ssp585"])
        ].set_index("scenario")
        ax.plot(
            [cross.loc["ssp126", "observed_rate_pct_mean"], cross.loc["ssp585", "observed_rate_pct_mean"]],
            [cross.loc["ssp126", "total_loss_twh_mean"], cross.loc["ssp585", "total_loss_twh_mean"]],
            color="0.72", lw=0.9, ls="--", zorder=1,
        )

    for scenario in SCENARIOS:
        sub = data[data["scenario"].eq(scenario)].set_index("snapshot_year").reindex(SNAPSHOTS)
        color = SSP_C[scenario]
        ax.plot(
            sub["observed_rate_pct_mean"], sub["total_loss_twh_mean"],
            color=color, lw=1.8, alpha=0.9, zorder=2,
        )
        for snapshot_year, row in sub.iterrows():
            x = float(row["observed_rate_pct_mean"])
            y = float(row["total_loss_twh_mean"])
            ax.errorbar(
                x, y,
                xerr=asymmetric_error(x, row["observed_rate_pct_min"], row["observed_rate_pct_max"]),
                yerr=asymmetric_error(y, row["total_loss_twh_min"], row["total_loss_twh_max"]),
                fmt=DECADE_MARKER[snapshot_year], ms=6.0, color=color,
                markerfacecolor="white", markeredgewidth=1.3,
                capsize=2.2, elinewidth=0.65, alpha=0.95, zorder=3,
            )
            dx = 0.09 if scenario != "ssp585" else -0.10
            ha = "left" if dx > 0 else "right"
            ax.annotate(
                DECADE_LABEL[snapshot_year], (x, y), xytext=(dx, 5),
                textcoords="offset points", ha=ha, va="bottom", fontsize=6.2, color=color,
            )

    ax.text(
        0.02, 0.78, "低单位损失率\n但系统总损失较高",
        transform=ax.transAxes, ha="left", va="top", fontsize=7.2,
        color=SSP_C["ssp126"],
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 1.0},
    )
    ax.text(
        0.98, 0.05, "高单位损失率\n但系统总损失较低",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=7.2,
        color=SSP_C["ssp585"],
    )
    ax.set_xlabel("风光综合净出力损失率（%）")
    ax.set_ylabel("风光净出力损失总量（TWh/年）")
    ax.set_title("总量风险与单位风险的二维权衡")
    ax.grid(lw=0.4, alpha=0.42)

    scenario_handles = [
        Line2D([0], [0], color=SSP_C[s], lw=2, label=SSP_L[s]) for s in SCENARIOS
    ]
    decade_handles = [
        Line2D([0], [0], color="0.25", marker=DECADE_MARKER[y], lw=0,
               markerfacecolor="white", label=DECADE_LABEL[y])
        for y in SNAPSHOTS
    ]
    first = ax.legend(handles=scenario_handles, loc="upper right", ncol=3, bbox_to_anchor=(1.0, 1.13))
    ax.add_artist(first)
    ax.legend(handles=decade_handles, loc="upper right", ncol=3, bbox_to_anchor=(1.0, 1.045))

    fig.suptitle(f"不同 SSP 路径下风光系统的风险 trade-off（{args.model}）", fontsize=11, fontweight="bold")
    fig.text(
        0.5, 0.035,
        "点为五年窗口均值，横纵误差条为年际最小—最大值；彩色实线表示年代演化，灰色虚线连接同年代的 SSP1-2.6 与 SSP5-8.5。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig_trade_off_quadrant")


if __name__ == "__main__":
    main()
