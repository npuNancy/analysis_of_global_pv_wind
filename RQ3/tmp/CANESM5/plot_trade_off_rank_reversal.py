#!/usr/bin/env python3
"""候选方案 2：总损失与综合损失率的情景排序反转图。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from plot_trade_off_common import (
    DECADE_LABEL,
    SCENARIOS,
    SNAPSHOTS,
    SSP_C,
    SSP_L,
    add_common_args,
    build_trade_off_decade,
    configure_trade_off_style,
    get_output_dir,
    load_trade_off_annual,
    panel_tag,
    save_figure,
    write_source,
)


def minmax(values):
    low = float(values.min())
    high = float(values.max())
    if np.isclose(high, low):
        return values * 0.0
    return (values - low) / (high - low)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = get_output_dir(args.model, args.output_dir)
    configure_trade_off_style()
    data = build_trade_off_decade(load_trade_off_annual(args.model))
    data["total_loss_risk_score"] = data.groupby("snapshot_year")["total_loss_twh_mean"].transform(minmax)
    data["loss_rate_risk_score"] = data.groupby("snapshot_year")["observed_rate_pct_mean"].transform(minmax)
    write_source(data, out, "trade_off_rank_reversal.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.55), sharey=True)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.22, top=0.78, wspace=0.22)
    for index, (ax, snapshot_year) in enumerate(zip(axes, SNAPSHOTS)):
        sub = data[data["snapshot_year"].eq(snapshot_year)].set_index("scenario").reindex(SCENARIOS)
        for scenario, row in sub.iterrows():
            ys = [row["total_loss_risk_score"], row["loss_rate_risk_score"]]
            ax.plot([0, 1], ys, "-o", color=SSP_C[scenario], lw=1.8, ms=5.2)
            ax.text(
                -0.06, ys[0], f"{row['total_loss_twh_mean']:.1f}",
                ha="right", va="center", fontsize=6.2, color=SSP_C[scenario],
            )
            ax.text(
                1.06, ys[1], f"{row['observed_rate_pct_mean']:.2f}%",
                ha="left", va="center", fontsize=6.2, color=SSP_C[scenario],
            )
        ax.set_xlim(-0.30, 1.30)
        ax.set_ylim(-0.10, 1.10)
        ax.set_xticks([0, 1], ["总损失\n(TWh/年)", "综合损失率\n(%)"])
        ax.set_title(DECADE_LABEL[snapshot_year])
        ax.grid(axis="y", lw=0.4, alpha=0.4)
        panel_tag(ax, chr(ord("a") + index))
        if index == 0:
            ax.set_ylabel("年代内归一化风险（0=最低，1=最高）")
    handles = [
        Line2D([0], [0], color=SSP_C[scenario], lw=2.2, marker="o", ms=4.5,
               label=SSP_L[scenario])
        for scenario in SCENARIOS
    ]
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 0.88))
    fig.suptitle(f"两个风险指标下的 SSP 排序反转（{args.model}）", fontsize=11, fontweight="bold")
    fig.text(
        0.5, 0.045,
        "每个年代分别做 min–max 归一化；左、右端数字保留实际值。向下倾斜表示总损失较高但综合损失率较低，向上倾斜则相反。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig_trade_off_rank_reversal")


if __name__ == "__main__":
    main()
