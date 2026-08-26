#!/usr/bin/env python3
"""国家—年代—SSP 粒度的风光总装机容量与绝对净损失散点图。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from plot_trade_off_common import (
    REGION_CSV,
    SCENARIOS,
    SSP_C,
    SSP_L,
    add_common_args,
    apply_temp_wind_energy_correction,
    configure_trade_off_style,
    get_output_dir,
    save_figure,
    write_source,
)


def build_country_data(model: str) -> pd.DataFrame:
    """先构造国家逐年风光总账，再对每个年代的五个分析年度取均值。"""
    path = Path(str(REGION_CSV).format(model=model))
    if not path.exists():
        raise SystemExit(f"未找到 RQ3 region 汇总：{path}")
    data = pd.read_csv(path)
    data = data[
        data["model"].eq(model)
        & data["scenario"].isin(SCENARIOS)
        & data["tech"].isin(["wind", "solar"])
        & data["event"].eq("all")
    ].copy()
    if data.empty:
        raise SystemExit(f"输入数据中没有 model={model}、event=all 的风光记录。")

    # 临时修正：风电发电量与损失能量字段统一 ×0.1；装机容量不缩放。
    apply_temp_wind_energy_correction(data, context="国家装机—绝对损失散点图")

    annual = (
        data.groupby(
            ["scenario", "region", "snapshot_year", "analysis_year"],
            as_index=False,
        )
        .agg(
            total_capacity_mw=("capacity_mw", "sum"),
            absolute_net_loss_mwh=("net_generation_loss_mwh", "sum"),
            n_techs=("tech", "nunique"),
        )
    )
    decade = (
        annual.groupby(["scenario", "region", "snapshot_year"], as_index=False)
        .agg(
            total_capacity_mw=("total_capacity_mw", "mean"),
            absolute_net_loss_mwh_per_year=("absolute_net_loss_mwh", "mean"),
            n_years=("analysis_year", "nunique"),
            n_techs=("n_techs", "min"),
        )
    )
    decade["total_capacity_gw"] = decade["total_capacity_mw"] / 1e3
    decade["absolute_net_loss_twh_per_year"] = (
        decade["absolute_net_loss_mwh_per_year"] / 1e6
    )
    decade["technology_coverage"] = decade["n_techs"].map({1: "one_available", 2: "wind_and_solar"})
    return decade.sort_values(["scenario", "region", "snapshot_year"]).reset_index(drop=True)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = get_output_dir(args.model, args.output_dir)
    configure_trade_off_style()
    data = build_country_data(args.model)
    write_source(data, out, "trade_off_country_capacity_loss.csv")

    fig, ax = plt.subplots(figsize=(7.4, 4.7))
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.20, top=0.84)
    for scenario in SCENARIOS:
        sub = data[data["scenario"].eq(scenario)]
        ax.scatter(
            sub["total_capacity_gw"],
            sub["absolute_net_loss_twh_per_year"],
            s=30,
            color=SSP_C[scenario],
            alpha=0.62,
            edgecolor="white",
            linewidth=0.45,
            label=SSP_L[scenario],
        )

    # 国家规模跨多个数量级，y 轴使用 symlog 以保留净损失为 0 的三个点。
    ax.set_xscale("log")
    ax.set_yscale("symlog", linthresh=0.01, linscale=0.8)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("风光总装机容量（GW，对数坐标）")
    ax.set_ylabel("绝对净出力损失（TWh/年，对称对数坐标）")
    ax.set_title("国家尺度风光装机容量与绝对净损失")
    ax.grid(which="major", lw=0.4, alpha=0.42)
    ax.grid(which="minor", lw=0.25, alpha=0.18)
    ax.legend(loc="upper left", ncol=3)

    n_zero = int(data["absolute_net_loss_twh_per_year"].eq(0).sum())
    fig.suptitle(
        f"国家风光装机规模与极端天气绝对损失（{args.model}）",
        fontsize=11,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.035,
        f"每个点为国家×SSP×年代的五年窗口均值（n={len(data)}）；颜色仅区分 SSP，国家和年代不编码。"
        f"按实际存在的风光技术加总；{n_zero} 个零净损失点由 symlog 轴保留。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )
    save_figure(fig, out, "fig_trade_off_country_capacity_loss")


if __name__ == "__main__":
    main()
