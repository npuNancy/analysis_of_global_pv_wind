#!/usr/bin/env python3
"""图 7：国家—事件尺度的暴露时长与损失率关系。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import (
    EVENT_COLOR, EVENT_LABEL, TECH_LABEL, TECHS, add_common_args,
    configure_style, output_dir, panel_tag, save_figure, write_source,
)
from prepare_station_summaries import prepare


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    _, country_path = prepare(args.model, out)
    data = pd.read_csv(country_path)
    data = data[(data["event"] != "all") & np.isfinite(data["loss_rate_pct"])].copy()
    write_source(data, out, "fig07_exposure_loss_conversion.csv")

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.75))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.28, top=0.8, wspace=0.26)
    handles = {}
    for index, tech in enumerate(TECHS):
        ax = axes[index]
        subset = data[data["tech"] == tech]
        for event, event_data in subset.groupby("event"):
            size = 5 + 18 * np.sqrt(event_data["normal_all_mwh"] / subset["normal_all_mwh"].max())
            artist = ax.scatter(
                event_data["exposure_days_per_year"], event_data["loss_rate_pct"],
                s=size, color=EVENT_COLOR.get(event, "0.6"), alpha=0.5,
                edgecolors="white", linewidths=0.25, label=EVENT_LABEL.get(event, event),
            )
            handles[event] = artist
        low = subset[subset["event"] == "low_resource"]
        rho, _ = spearmanr(low["exposure_days_per_year"], low["loss_rate_pct"], nan_policy="omit")
        ax.set_xscale("symlog", linthresh=0.1)
        ax.set_xlabel("容量加权暴露天数（天/年）")
        ax.set_ylabel("事件净损失率（%）")
        ax.set_title(f"{TECH_LABEL[tech]}（低资源 Spearman ρ={rho:.2f}）")
        ax.grid(lw=0.35, alpha=0.35)
        panel_tag(ax, chr(ord("a") + index))
    ordered = [event for event in ["low_resource", "high_temp", "high_wind", "hot_humid", "icing", "rainstorm", "cold_highwind", "freezing_rain", "high_humidity"] if event in handles]
    fig.legend(
        [handles[event] for event in ordered], [EVENT_LABEL[event] for event in ordered],
        loc="lower center", ncol=5, bbox_to_anchor=(0.5, 0.045), fontsize=5.8,
    )
    fig.suptitle(f"暴露时长如何转化为净出力损失（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.008,
        "每点为国家—SSP—年代—事件；点大小表示全年应发电量。低资源事件由 CF 定义，其相关性包含机械关系，不作独立因果解释。",
        ha="center", fontsize=6.0, color="0.4",
    )
    save_figure(fig, out, "fig07_exposure_loss_conversion")


if __name__ == "__main__":
    main()
