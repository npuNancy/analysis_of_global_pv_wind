#!/usr/bin/env python3
"""图 9：共同国家口径下的部署—气候强度交叉反事实与 Shapley 分解。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D

from common import (
    SSP_LABEL,
    SSPS,
    TECH_LABEL,
    TECHS,
    add_common_args,
    configure_style,
    load_region,
    output_dir,
    panel_tag,
    save_figure,
    write_source,
)


YEARS = [2030, 2050]


def build_counterfactual(model: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """构造 L(D, C)=sum_r K_r(D) q_r(C)，并计算二因素 Shapley 贡献。"""
    region = load_region(model)
    selected = region[
        region["event"].eq("all") & region["snapshot_year"].isin(YEARS)
    ].copy()

    capacity_check = (
        selected.groupby(["scenario", "tech", "snapshot_year", "region"])["capacity_mw"]
        .agg(["min", "max"])
    )
    if not np.allclose(capacity_check["min"], capacity_check["max"]):
        raise ValueError("同一国家—情景—技术—年代内的年度装机容量不一致。")

    period = (
        selected.groupby(["scenario", "tech", "snapshot_year", "region"], as_index=False)
        .agg(
            annual_loss_mwh=("net_generation_loss_mwh", "mean"),
            capacity_mw=("capacity_mw", "first"),
            n_years=("analysis_year", "nunique"),
        )
    )
    period["loss_intensity_mwh_per_mw_year"] = (
        period["annual_loss_mwh"] / period["capacity_mw"]
    )

    matrix_rows: list[dict[str, float | int | str]] = []
    shapley_rows: list[dict[str, float | int | str]] = []
    for (scenario, tech), group in period.groupby(["scenario", "tech"], sort=False):
        by_year = {
            year: group[group["snapshot_year"].eq(year)].set_index("region").sort_index()
            for year in YEARS
        }
        common_regions = by_year[2030].index.intersection(by_year[2050].index)
        if common_regions.empty:
            raise ValueError(f"{scenario}/{tech} 在 2030s 与 2050s 间没有共同国家。")

        values: dict[tuple[int, int], float] = {}
        for deployment_year in YEARS:
            deployment = by_year[deployment_year]
            capacity = deployment.loc[common_regions, "capacity_mw"]
            capacity_coverage = capacity.sum() / deployment["capacity_mw"].sum() * 100.0
            for climate_year in YEARS:
                climate = by_year[climate_year]
                intensity = climate.loc[common_regions, "loss_intensity_mwh_per_mw_year"]
                loss_twh = float((capacity * intensity).sum() / 1e6)
                values[(deployment_year, climate_year)] = loss_twh
                climate_loss_coverage = (
                    climate.loc[common_regions, "annual_loss_mwh"].sum()
                    / climate["annual_loss_mwh"].sum()
                    * 100.0
                )
                matrix_rows.append(
                    {
                        "scenario": scenario,
                        "tech": tech,
                        "deployment_year": deployment_year,
                        "climate_year": climate_year,
                        "counterfactual_loss_twh": loss_twh,
                        "n_common_regions": len(common_regions),
                        "deployment_capacity_coverage_pct": capacity_coverage,
                        "climate_observed_loss_coverage_pct": climate_loss_coverage,
                    }
                )

        l00 = values[(2030, 2030)]
        l10 = values[(2050, 2030)]
        l01 = values[(2030, 2050)]
        l11 = values[(2050, 2050)]
        deployment_effect = 0.5 * ((l10 - l00) + (l11 - l01))
        climate_effect = 0.5 * ((l01 - l00) + (l11 - l10))
        total_change = l11 - l00
        if not np.isclose(deployment_effect + climate_effect, total_change):
            raise AssertionError(f"{scenario}/{tech} 的 Shapley 分解未闭合。")
        shapley_rows.append(
            {
                "scenario": scenario,
                "tech": tech,
                "baseline_loss_twh": l00,
                "final_loss_twh": l11,
                "deployment_effect_twh": deployment_effect,
                "climate_intensity_effect_twh": climate_effect,
                "total_change_twh": total_change,
                "n_common_regions": len(common_regions),
                "capacity_coverage_2030_pct": (
                    by_year[2030].loc[common_regions, "capacity_mw"].sum()
                    / by_year[2030]["capacity_mw"].sum()
                    * 100.0
                ),
                "capacity_coverage_2050_pct": (
                    by_year[2050].loc[common_regions, "capacity_mw"].sum()
                    / by_year[2050]["capacity_mw"].sum()
                    * 100.0
                ),
            }
        )
    return pd.DataFrame(matrix_rows), pd.DataFrame(shapley_rows)


def plot_counterfactual(
    matrix: pd.DataFrame,
    shapley: pd.DataFrame,
    model: str,
    out_dir,
) -> None:
    positive = matrix.loc[matrix["counterfactual_loss_twh"] > 0, "counterfactual_loss_twh"]
    norm = LogNorm(vmin=float(positive.min()), vmax=float(positive.max()))
    fig = plt.figure(figsize=(7.4, 7.0))
    grid = fig.add_gridspec(
        3, 3, height_ratios=[1.0, 1.0, 1.15],
        left=0.10, right=0.94, bottom=0.13, top=0.90, hspace=0.42, wspace=0.32,
    )
    image = None
    tag_index = 0
    for row, tech in enumerate(TECHS):
        for col, scenario in enumerate(SSPS):
            ax = fig.add_subplot(grid[row, col])
            sub = matrix[
                matrix["tech"].eq(tech) & matrix["scenario"].eq(scenario)
            ]
            table = (
                sub.pivot(index="deployment_year", columns="climate_year", values="counterfactual_loss_twh")
                .reindex(index=YEARS, columns=YEARS)
            )
            image = ax.imshow(table.to_numpy(), cmap="Blues", norm=norm, aspect="auto")
            for y_index, deployment_year in enumerate(YEARS):
                for x_index, climate_year in enumerate(YEARS):
                    value = float(table.loc[deployment_year, climate_year])
                    text_color = "white" if norm(value) > 0.57 else "#17233a"
                    ax.text(
                        x_index, y_index, f"{value:.1f}", ha="center", va="center",
                        fontsize=7.2, fontweight="bold", color=text_color,
                    )
            ax.set_xticks([0, 1], ["C2030s", "C2050s"])
            ax.set_yticks([0, 1], ["D2030s", "D2050s"])
            ax.set_xlabel("气候损失强度 C")
            if col == 0:
                ax.set_ylabel("部署容量 D")
            ax.set_title(f"{TECH_LABEL[tech]} · {SSP_LABEL[scenario]}")
            panel_tag(ax, chr(ord("a") + tag_index))
            tag_index += 1

    if image is not None:
        colorbar_ax = fig.add_axes([0.955, 0.405, 0.012, 0.45])
        colorbar = fig.colorbar(image, cax=colorbar_ax)
        colorbar.set_label("反事实净损失（TWh/年，对数色阶）", fontsize=6.5)
        colorbar.ax.tick_params(labelsize=5.8)

    ax = fig.add_subplot(grid[2, :])
    ordered = pd.concat(
        [
            shapley[shapley["tech"].eq(tech)].set_index("scenario").reindex(SSPS).reset_index()
            for tech in TECHS
        ],
        ignore_index=True,
    )
    x = np.arange(len(ordered), dtype=float)
    x[3:] += 0.35
    width = 0.32
    deployment = ordered["deployment_effect_twh"].to_numpy()
    climate = ordered["climate_intensity_effect_twh"].to_numpy()
    total = ordered["total_change_twh"].to_numpy()
    ax.bar(x - width / 2, deployment, width, color="#4c78a8", label="部署效应")
    ax.bar(x + width / 2, climate, width, color="#e45756", label="气候损失强度效应")
    ax.scatter(x, total, marker="D", s=19, color="#222222", zorder=3, label="总变化")
    for xpos, value in zip(x, climate):
        ax.text(
            xpos + width / 2, value, f"{value:+.1f}", ha="center",
            va="bottom" if value >= 0 else "top", fontsize=5.7,
        )
    ax.axhline(0, color="0.25", lw=0.7)
    ax.set_xticks(
        x,
        [
            f"{TECH_LABEL[row.tech]}\n{SSP_LABEL[row.scenario]}"
            for row in ordered.itertuples(index=False)
        ],
    )
    ax.set_ylabel("2030s→2050s Shapley 贡献（TWh/年）")
    ax.set_title("g  二因素 Shapley 分解", loc="left", fontweight="bold")
    ax.grid(axis="y", lw=0.35, alpha=0.4)
    handles = [
        Line2D([0], [0], color="#4c78a8", lw=5, label="部署效应"),
        Line2D([0], [0], color="#e45756", lw=5, label="气候损失强度效应"),
        Line2D([0], [0], color="#222222", marker="D", lw=0, ms=4, label="总变化"),
    ]
    ax.legend(handles=handles, ncol=3, loc="upper right")

    coverage_min = float(shapley["capacity_coverage_2050_pct"].min())
    fig.suptitle(
        f"部署—气候损失强度交叉反事实与 Shapley 分解（{model}）",
        fontsize=10.5, fontweight="bold",
    )
    fig.text(
        0.5, 0.035,
        "L(D,C)=Σ国家 容量(D)×单位容量净损失强度(C)；仅使用 2030s/2050s 共同国家，"
        f"2050s 容量覆盖率至少 {coverage_min:.1f}%。风电发电量与损失能量项采用临时 0.1 修正。",
        ha="center", fontsize=6.1, color="0.4",
    )
    save_figure(fig, out_dir, "fig09_deployment_climate_counterfactual")


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    matrix, shapley = build_counterfactual(args.model)
    write_source(matrix, out, "fig09_counterfactual_matrix.csv")
    write_source(shapley, out, "fig09_shapley_decomposition.csv")
    plot_counterfactual(matrix, shapley, args.model, out)


if __name__ == "__main__":
    main()
