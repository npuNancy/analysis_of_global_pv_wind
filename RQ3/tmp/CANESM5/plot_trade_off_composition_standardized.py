#!/usr/bin/env python3
"""候选方案 3：固定风光技术权重后的 trade-off 构成效应诊断。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_trade_off_common import (
    DECADE_LABEL,
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
    panel_tag,
    save_figure,
    write_source,
)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = get_output_dir(args.model, args.output_dir)
    configure_trade_off_style()
    data = build_trade_off_decade(load_trade_off_annual(args.model))
    data["tech_mix_effect_pp"] = (
        data["observed_rate_pct_mean"] - data["fixed_tech_mix_rate_pct_mean"]
    )
    write_source(data, out, "trade_off_composition_standardized.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.75), sharey=True)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.23, top=0.78, wspace=0.23)
    for index, (ax, snapshot_year) in enumerate(zip(axes, SNAPSHOTS)):
        sub = data[data["snapshot_year"].eq(snapshot_year)].set_index("scenario").reindex(SCENARIOS)
        for scenario, row in sub.iterrows():
            x = float(row["total_loss_twh_mean"])
            observed = float(row["observed_rate_pct_mean"])
            fixed = float(row["fixed_tech_mix_rate_pct_mean"])
            color = SSP_C[scenario]
            ax.plot([x, x], [observed, fixed], color=color, lw=1.4, alpha=0.8, zorder=1)
            ax.errorbar(
                x, observed,
                xerr=asymmetric_error(x, row["total_loss_twh_min"], row["total_loss_twh_max"]),
                yerr=asymmetric_error(observed, row["observed_rate_pct_min"], row["observed_rate_pct_max"]),
                fmt="o", color=color, markerfacecolor="white", ms=5.5,
                markeredgewidth=1.2, capsize=2, elinewidth=0.6, zorder=2,
            )
            ax.scatter(x, fixed, marker="D", s=28, color=color, zorder=3)
            ax.annotate(
                SSP_L[scenario], (x, max(observed, fixed)), xytext=(0, 5),
                textcoords="offset points", ha="center", va="bottom", fontsize=5.8, color=color,
            )
        ax.set_title(DECADE_LABEL[snapshot_year])
        ax.set_xlabel("风光净损失总量（TWh/年）")
        ax.grid(lw=0.4, alpha=0.4)
        panel_tag(ax, chr(ord("a") + index))
        if index == 0:
            ax.set_ylabel("风光综合净损失率（%）")

    handles = [
        Line2D([0], [0], marker="o", color="0.25", markerfacecolor="white", lw=0,
               label="观测技术结构"),
        Line2D([0], [0], marker="D", color="0.25", lw=0, label="固定共同风光权重"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 0.90))
    fig.suptitle(f"技术结构对风险 trade-off 的影响（{args.model}）", fontsize=11, fontweight="bold")
    fig.text(
        0.5, 0.045,
        "圆点为观测风光结构；菱形以同一年度三情景的平均风电正常发电占比作为共同权重。竖线表示技术构成对综合损失率的贡献。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig_trade_off_composition_standardized")


if __name__ == "__main__":
    main()

