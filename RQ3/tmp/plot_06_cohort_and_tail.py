#!/usr/bin/env python3
"""图 6：固定 2030 场站 cohort 与场站风险长尾。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    SSP_COLOR, SSP_LABEL, SSPS, TECH_LABEL, TECHS, add_common_args,
    configure_style, output_dir, panel_tag, save_figure, weighted_quantile,
    write_source,
)
from prepare_station_summaries import prepare


def build_data(model: str, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    station_path, _ = prepare(model, out_dir)
    station = pd.read_csv(station_path)
    trajectory_rows = []
    tail_rows = []
    for (scenario, tech), group in station.groupby(["scenario", "tech"]):
        base = group[group["snapshot_year"] == 2030][["station_id", "capacity_mw"]].rename(
            columns={"capacity_mw": "base_capacity_mw"}
        )
        base_capacity = base["base_capacity_mw"].sum()
        for snapshot in [2030, 2040, 2050]:
            current = group[group["snapshot_year"] == snapshot].copy()
            actual_rate = current["net_loss_mwh"].sum() / current["normal_all_mwh"].sum() * 100.0
            paired = current.merge(base, on="station_id", how="inner")
            paired["loss_per_mw"] = paired["net_loss_mwh"] / paired["capacity_mw"]
            paired["normal_per_mw"] = paired["normal_all_mwh"] / paired["capacity_mw"]
            fixed_loss = (paired["loss_per_mw"] * paired["base_capacity_mw"]).sum()
            fixed_normal = (paired["normal_per_mw"] * paired["base_capacity_mw"]).sum()
            fixed_rate = fixed_loss / fixed_normal * 100.0
            trajectory_rows.extend(
                [
                    {
                        "scenario": scenario, "tech": tech, "snapshot_year": snapshot,
                        "fleet": "actual", "loss_rate_pct": actual_rate,
                        "paired_capacity_share_pct": 100.0,
                    },
                    {
                        "scenario": scenario, "tech": tech, "snapshot_year": snapshot,
                        "fleet": "fixed_2030", "loss_rate_pct": fixed_rate,
                        "paired_capacity_share_pct": paired["base_capacity_mw"].sum() / base_capacity * 100.0,
                    },
                ]
            )
            values = current["loss_rate_pct"].to_numpy(dtype=float)
            weights = current["capacity_mw"].to_numpy(dtype=float)
            for quantile in [0.5, 0.9, 0.95]:
                tail_rows.append(
                    {
                        "scenario": scenario, "tech": tech, "snapshot_year": snapshot,
                        "quantile": quantile,
                        "loss_rate_pct": weighted_quantile(values, weights, quantile),
                        "n_stations": len(current),
                    }
                )
    return pd.DataFrame(trajectory_rows), pd.DataFrame(tail_rows)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    trajectory, tails = build_data(args.model, out)
    write_source(trajectory, out, "fig06_fixed_cohort.csv")
    write_source(tails, out, "fig06_station_tail.csv")

    fig, axes = plt.subplots(2, 2, figsize=(7.4, 5.5), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.14, top=0.87, hspace=0.38, wspace=0.26)
    for row, tech in enumerate(TECHS):
        ax = axes[row, 0]
        for scenario in SSPS:
            for fleet, linestyle in [("actual", "-"), ("fixed_2030", "--")]:
                sub = trajectory[
                    (trajectory["tech"] == tech) & (trajectory["scenario"] == scenario) & (trajectory["fleet"] == fleet)
                ].sort_values("snapshot_year")
                ax.plot(
                    sub["snapshot_year"], sub["loss_rate_pct"], linestyle,
                    color=SSP_COLOR[scenario], marker="o", ms=3, lw=1.4,
                    label=f"{SSP_LABEL[scenario]} · {'实际' if fleet == 'actual' else '固定2030'}",
                )
        ax.set_title(f"{TECH_LABEL[tech]}：实际部署 vs 固定 2030 cohort")
        ax.set_ylabel("净损失率（%）")
        ax.grid(axis="y", lw=0.35, alpha=0.4)

        ax = axes[row, 1]
        for scenario in SSPS:
            for quantile, linestyle, label in [(0.5, "--", "P50"), (0.95, "-", "P95")]:
                sub = tails[
                    (tails["tech"] == tech) & (tails["scenario"] == scenario) & (tails["quantile"] == quantile)
                ].sort_values("snapshot_year")
                ax.plot(
                    sub["snapshot_year"], sub["loss_rate_pct"], linestyle,
                    color=SSP_COLOR[scenario], marker="o", ms=3, lw=1.4,
                    label=f"{SSP_LABEL[scenario]} · {label}",
                )
        ax.set_title(f"{TECH_LABEL[tech]}：容量加权场站风险长尾")
        ax.set_ylabel("场站净损失率（%）")
        ax.grid(axis="y", lw=0.35, alpha=0.4)
    for ax in axes.ravel():
        ax.set_xticks([2030, 2040, 2050], ["2030s", "2040s", "2050s"])
    axes[0, 0].legend(fontsize=5.4, ncol=2, loc="best")
    axes[0, 1].legend(fontsize=5.4, ncol=2, loc="best")
    for index, ax in enumerate(axes.ravel()):
        panel_tag(ax, chr(ord("a") + index))
    fig.suptitle(f"部署 cohort 与场站级风险长尾（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.025,
        "固定 cohort 保留 2030s 场站及其容量，用后续年代的单位容量损失重新加权；P50/P95 为容量加权分位数。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig06_cohort_and_tail")


if __name__ == "__main__":
    main()
