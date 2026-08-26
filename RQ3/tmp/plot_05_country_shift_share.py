#!/usr/bin/env python3
"""图 5：全球损失率变化的国家内部与构成效应。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    SSP_LABEL, SSPS, TECH_LABEL, TECHS, add_common_args, configure_style,
    load_region, output_dir, panel_tag, save_figure, write_source,
)


def build_data(model: str) -> pd.DataFrame:
    region = load_region(model)
    data = region[region["event"] == "all"].copy()
    country = (
        data.groupby(["scenario", "tech", "snapshot_year", "analysis_year", "region"], as_index=False)
        .agg(loss_mwh=("net_generation_loss_mwh", "sum"), normal_mwh=("normal_all_generation_mwh", "sum"))
        .groupby(["scenario", "tech", "snapshot_year", "region"], as_index=False)[["loss_mwh", "normal_mwh"]]
        .mean()
    )
    rows = []
    for (scenario, tech), group in country.groupby(["scenario", "tech"]):
        for start_year, end_year in [(2030, 2040), (2040, 2050)]:
            start = group[group["snapshot_year"] == start_year].set_index("region")
            end = group[group["snapshot_year"] == end_year].set_index("region")
            common = start.index.intersection(end.index)
            a = start.loc[common]
            b = end.loc[common]
            r0 = a["loss_mwh"] / a["normal_mwh"] * 100.0
            r1 = b["loss_mwh"] / b["normal_mwh"] * 100.0
            w0 = a["normal_mwh"] / a["normal_mwh"].sum()
            w1 = b["normal_mwh"] / b["normal_mwh"].sum()
            within = float((0.5 * (w0 + w1) * (r1 - r0)).sum())
            composition = float((0.5 * (r0 + r1) * (w1 - w0)).sum())
            full0 = start["loss_mwh"].sum() / start["normal_mwh"].sum() * 100.0
            full1 = end["loss_mwh"].sum() / end["normal_mwh"].sum() * 100.0
            total = float(full1 - full0)
            coverage = total - within - composition
            rows.append(
                {
                    "scenario": scenario, "tech": tech,
                    "transition": f"{start_year}s→{end_year}s",
                    "within_country_pp": within,
                    "weight_composition_pp": composition,
                    "coverage_entry_exit_pp": coverage,
                    "total_change_pp": total,
                    "n_common_countries": len(common),
                }
            )
    return pd.DataFrame(rows)


def signed_stack(ax, x: np.ndarray, parts: list[np.ndarray], colors: list[str], labels: list[str]) -> None:
    positive = np.zeros(len(x))
    negative = np.zeros(len(x))
    for values, color, label in zip(parts, colors, labels):
        bottoms = np.where(values >= 0, positive, negative)
        ax.bar(x, values, bottom=bottoms, color=color, width=0.62, label=label)
        positive += np.where(values >= 0, values, 0)
        negative += np.where(values < 0, values, 0)


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    data = build_data(args.model)
    write_source(data, out, "fig05_country_shift_share.csv")

    fig, axes = plt.subplots(2, 3, figsize=(7.4, 4.9), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.16, top=0.85, hspace=0.42, wspace=0.25)
    transitions = ["2030s→2040s", "2040s→2050s"]
    colors = ["#4c78a8", "#f2a541", "#9c9c9c"]
    labels = ["国家内部", "发电权重", "覆盖进出"]
    for row, tech in enumerate(TECHS):
        for col, scenario in enumerate(SSPS):
            ax = axes[row, col]
            sub = data[(data["tech"] == tech) & (data["scenario"] == scenario)].set_index("transition").reindex(transitions)
            x = np.arange(2)
            parts = [
                sub["within_country_pp"].to_numpy(),
                sub["weight_composition_pp"].to_numpy(),
                sub["coverage_entry_exit_pp"].to_numpy(),
            ]
            signed_stack(ax, x, parts, colors, labels)
            ax.plot(x, sub["total_change_pp"], "D", color="#222222", ms=4, label="总变化")
            ax.axhline(0, color="0.25", lw=0.7)
            ax.set_xticks(x, ["30→40", "40→50"])
            ax.set_title(f"{TECH_LABEL[tech]} · {SSP_LABEL[scenario]}")
            ax.set_ylabel("损失率变化贡献（百分点）")
            ax.grid(axis="y", lw=0.35, alpha=0.4)
            panel_tag(ax, chr(ord("a") + row * 3 + col))
    handles, legend_labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower center", ncol=4, bbox_to_anchor=(0.5, 0.025))
    fig.suptitle(f"全球损失率变化的国家内部与构成效应（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.005,
        "Kitagawa 分解在共同国家内区分风险变化与应发电量权重变化；覆盖进出项为完整样本总变化与共同国家分解之差。",
        ha="center", fontsize=6.1, color="0.4",
    )
    save_figure(fig, out, "fig05_country_shift_share")


if __name__ == "__main__":
    main()
