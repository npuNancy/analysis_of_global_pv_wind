#!/usr/bin/env python3
"""图 2：损失率的暴露—时段—强度机制分解。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    RQ2_EXPOSURE_CSV, SSP_COLOR, SSP_LABEL, SSPS, TECH_LABEL, TECHS,
    add_common_args, configure_style, global_annual, load_region, output_dir,
    panel_tag, save_figure, write_source,
)


def build_data(model: str) -> pd.DataFrame:
    annual = global_annual(load_region(model))
    annual = annual[annual["event"] == "all"].copy()
    annual["loss_rate_pct"] = annual["net_loss_mwh"] / annual["normal_all_mwh"] * 100.0
    annual["opportunity_pct"] = annual["normal_event_mwh"] / annual["normal_all_mwh"] * 100.0
    annual["severity_pct"] = annual["net_loss_mwh"] / annual["normal_event_mwh"] * 100.0

    exposure_path = Path(str(RQ2_EXPOSURE_CSV).format(model=model))
    if not exposure_path.exists():
        raise SystemExit(f"未找到 RQ2 暴露率表：{exposure_path}")
    exposure = pd.read_csv(exposure_path).rename(columns={"ssp": "scenario", "year": "analysis_year"})
    exposure = exposure[
        ["scenario", "tech", "analysis_year", "capacity_weighted_exposure_rate_pct"]
    ]
    annual = annual.merge(exposure, on=["scenario", "tech", "analysis_year"], how="left", validate="many_to_one")
    annual["timing_factor"] = np.where(
        annual["capacity_weighted_exposure_rate_pct"] > 0,
        annual["opportunity_pct"] / annual["capacity_weighted_exposure_rate_pct"],
        np.nan,
    )
    return (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            exposure_pct=("capacity_weighted_exposure_rate_pct", "mean"),
            timing_factor=("timing_factor", "mean"),
            severity_pct=("severity_pct", "mean"),
            loss_rate_pct=("loss_rate_pct", "mean"),
            n_years=("analysis_year", "nunique"),
        )
    )


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    data = build_data(args.model)
    write_source(data, out, "fig02_loss_rate_mechanism.csv")

    metrics = [
        ("exposure_pct", "容量加权暴露率（%）", "暴露时长 E"),
        ("timing_factor", "时段因子（倍）", "事件时段 T"),
        ("severity_pct", "条件损失强度（%）", "条件强度 S"),
        ("loss_rate_pct", "净出力损失率（%）", "最终损失率 R"),
    ]
    fig, axes = plt.subplots(4, 2, figsize=(7.4, 8.1), sharex=True)
    fig.subplots_adjust(left=0.1, right=0.98, bottom=0.09, top=0.91, hspace=0.36, wspace=0.28)
    for row, (metric, ylabel, title) in enumerate(metrics):
        for col, tech in enumerate(TECHS):
            ax = axes[row, col]
            for scenario in SSPS:
                sub = data[(data["tech"] == tech) & (data["scenario"] == scenario)].sort_values("snapshot_year")
                ax.plot(
                    sub["snapshot_year"], sub[metric], "-o", color=SSP_COLOR[scenario],
                    lw=1.6, ms=3.5, label=SSP_LABEL[scenario],
                )
            ax.set_ylabel(ylabel)
            ax.set_title(f"{TECH_LABEL[tech]} · {title}")
            ax.grid(axis="y", lw=0.35, alpha=0.4)
            ax.set_xticks([2030, 2040, 2050], ["2030s", "2040s", "2050s"])
            panel_tag(ax, chr(ord("a") + row * 2 + col))
    axes[0, 0].legend(loc="best")
    fig.suptitle(f"净出力损失率的暴露—时段—强度机制（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.02,
        "年度尺度上 R = E × T × S；图中为各年代五个年度分解量的均值。E 来自 RQ2，T 衡量极端事件是否集中在正常高出力时段。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig02_loss_rate_mechanism")


if __name__ == "__main__":
    main()
