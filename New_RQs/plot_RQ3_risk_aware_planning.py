#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制 RQ3：传统规划与风险修正规划的单位发电损失对比（模拟数据）。"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch

from plot_RQ1_extreme_weather_loss import (
    ROOT,
    SSP_LABELS,
    SSPS,
    configure_style,
    panel_label,
)


DEFAULT_OUTPUT = ROOT / "New_RQs/outputs/fig_RQ3_risk_aware_planning.png"
N_SIMULATIONS = 60
PLANS = ["traditional", "risk_aware"]
PLAN_LABELS = {"traditional": "传统规划", "risk_aware": "风险修正规划"}
METRICS = ["total", "wind", "solar"]
METRIC_LABELS = {
    "total": "总相对损失率",
    "wind": "风电单位损失",
    "solar": "光伏单位损失",
}
METRIC_COLORS = {
    "total": "#68727A",
    "wind": "#356A8A",
    "solar": "#D69C3D",
}
BASE_LOSS = {
    "ssp126": {"wind": 8.2, "solar": 5.4},
    "ssp245": {"wind": 10.4, "solar": 6.8},
    "ssp585": {"wind": 14.0, "solar": 9.1},
}
RISK_REDUCTION = {
    "ssp126": {"wind": 0.18, "solar": 0.22},
    "ssp245": {"wind": 0.25, "solar": 0.28},
    "ssp585": {"wind": 0.34, "solar": 0.38},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="绘制 RQ3 三面板风险修正规划箱线图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mock-seed", type=int, default=20260907, help="模拟数据随机种子。")
    parser.add_argument("--n-simulations", type=int, default=N_SIMULATIONS, help="每种规划的模拟组合数。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 PNG 路径。")
    parser.add_argument("--dpi", type=int, default=400, help="PNG 输出分辨率。")
    return parser.parse_args()


def simulate_planning_losses(seed: int, n_simulations: int) -> dict[str, dict[str, dict[str, np.ndarray]]]:
    if n_simulations < 10:
        raise ValueError("每种规划至少需要 10 个模拟组合。")
    rng = np.random.default_rng(seed)
    result: dict[str, dict[str, dict[str, np.ndarray]]] = {}

    for ssp in SSPS:
        shared_exposure = rng.lognormal(mean=-0.5 * 0.13**2, sigma=0.13, size=n_simulations)
        wind_share = np.clip(rng.normal(0.58, 0.07, size=n_simulations), 0.38, 0.78)
        wind_traditional = np.clip(
            BASE_LOSS[ssp]["wind"] * shared_exposure * rng.normal(1.0, 0.08, n_simulations),
            0.2,
            None,
        )
        solar_traditional = np.clip(
            BASE_LOSS[ssp]["solar"] * shared_exposure * rng.normal(1.0, 0.09, n_simulations),
            0.2,
            None,
        )
        total_traditional = wind_share * wind_traditional + (1.0 - wind_share) * solar_traditional

        wind_risk_aware = np.clip(
            wind_traditional
            * (1.0 - RISK_REDUCTION[ssp]["wind"] + rng.normal(0.0, 0.035, n_simulations)),
            0.1,
            None,
        )
        solar_risk_aware = np.clip(
            solar_traditional
            * (1.0 - RISK_REDUCTION[ssp]["solar"] + rng.normal(0.0, 0.035, n_simulations)),
            0.1,
            None,
        )
        total_risk_aware = wind_share * wind_risk_aware + (1.0 - wind_share) * solar_risk_aware

        result[ssp] = {
            "traditional": {
                "total": total_traditional,
                "wind": wind_traditional,
                "solar": solar_traditional,
            },
            "risk_aware": {
                "total": total_risk_aware,
                "wind": wind_risk_aware,
                "solar": solar_risk_aware,
            },
        }
    return result


def validate_mock_data(data: dict[str, dict[str, dict[str, np.ndarray]]], n_simulations: int) -> None:
    for ssp in SSPS:
        for plan in PLANS:
            for metric in METRICS:
                values = data[ssp][plan][metric]
                if len(values) != n_simulations or not np.isfinite(values).all() or np.any(values <= 0):
                    raise ValueError(f"{ssp}/{plan}/{metric} 的模拟数据无效。")
        traditional = np.median(data[ssp]["traditional"]["total"])
        risk_aware = np.median(data[ssp]["risk_aware"]["total"])
        if risk_aware >= traditional:
            raise ValueError(f"{ssp} 的风险修正规划未降低总相对损失率。")


def draw_panel(
    ax: mpl.axes.Axes,
    scenario_data: dict[str, dict[str, np.ndarray]],
    ssp: str,
    label: str,
    y_max: float,
) -> None:
    group_starts = {"traditional": 0.0, "risk_aware": 4.2}
    metric_offsets = {"total": 0.0, "wind": 0.9, "solar": 1.8}

    for plan in PLANS:
        positions = [group_starts[plan] + metric_offsets[metric] for metric in METRICS]
        values = [scenario_data[plan][metric] for metric in METRICS]
        boxplot = ax.boxplot(
            values,
            positions=positions,
            widths=0.66,
            patch_artist=True,
            showfliers=True,
            medianprops={"color": "#202020", "linewidth": 1.15},
            whiskerprops={"color": "#555555", "linewidth": 0.75},
            capprops={"color": "#555555", "linewidth": 0.75},
            boxprops={"edgecolor": "#555555", "linewidth": 0.7},
            flierprops={
                "marker": "o",
                "markersize": 2.0,
                "markerfacecolor": "#555555",
                "markeredgewidth": 0,
                "alpha": 0.55,
            },
        )
        for patch, metric in zip(boxplot["boxes"], METRICS):
            patch.set_facecolor(METRIC_COLORS[metric])
            patch.set_alpha(0.62 if plan == "traditional" else 0.88)
            if plan == "risk_aware":
                patch.set_hatch("//")

    traditional_median = float(np.median(scenario_data["traditional"]["total"]))
    risk_aware_median = float(np.median(scenario_data["risk_aware"]["total"]))
    reduction = (1.0 - risk_aware_median / traditional_median) * 100.0
    ax.text(
        0.5,
        0.96,
        f"总损失率中位数降低 {reduction:.0f}%",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=7.2,
        color="#7B3540",
        bbox={"facecolor": "white", "edgecolor": "#D8C5C7", "linewidth": 0.6, "pad": 2.0},
    )

    ax.axvline(3.0, color="#C7CDD1", linewidth=0.7, linestyle=(0, (2.5, 2.5)))
    ax.set_xticks([0.9, 5.1])
    ax.set_xticklabels([PLAN_LABELS[plan] for plan in PLANS])
    ax.set_xlim(-0.65, 6.65)
    ax.set_ylim(0, y_max)
    ax.set_title(f"{SSP_LABELS[ssp]}（模拟数据）", pad=7)
    ax.grid(axis="y", color="#D5D9DC", linewidth=0.5, alpha=0.8)
    panel_label(ax, label, x=-0.08, y=1.08)


def add_framework(fig: mpl.figure.Figure) -> None:
    box_style = {"boxstyle": "round,pad=0.35", "facecolor": "#F4F6F7", "edgecolor": "#AAB3B9"}
    fig.text(
        0.31,
        0.865,
        "传统目标：资源潜力 + 建设成本",
        ha="center",
        va="center",
        fontsize=7.5,
        bbox=box_style,
    )
    fig.text(
        0.69,
        0.865,
        "风险修正：资源—成本—极端风险联合优化",
        ha="center",
        va="center",
        fontsize=7.5,
        bbox={**box_style, "facecolor": "#F4E8E8", "edgecolor": "#B78186"},
    )
    arrow = FancyArrowPatch(
        (0.43, 0.865),
        (0.57, 0.865),
        transform=fig.transFigure,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.0,
        color="#7B3540",
    )
    fig.add_artist(arrow)
    fig.text(0.5, 0.88, "+ 极端暴露与损失惩罚", ha="center", va="bottom", fontsize=6.5, color="#7B3540")


def make_figure(args: argparse.Namespace) -> Path:
    configure_style()
    data = simulate_planning_losses(args.mock_seed, args.n_simulations)
    validate_mock_data(data, args.n_simulations)
    y_max = max(
        float(np.max(data[ssp][plan][metric]))
        for ssp in SSPS
        for plan in PLANS
        for metric in METRICS
    ) * 1.14

    fig, axes = plt.subplots(1, 3, figsize=(11.4, 5.1), sharey=True)
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.17, top=0.72, wspace=0.18)
    for ax, ssp, label in zip(axes, SSPS, ["a", "b", "c"]):
        draw_panel(ax, data[ssp], ssp, label, y_max)

    axes[0].set_ylabel("单位发电损失（%）")
    metric_handles = [
        Line2D(
            [0],
            [0],
            marker="s",
            linestyle="none",
            markerfacecolor=METRIC_COLORS[metric],
            markeredgecolor="#555555",
            markeredgewidth=0.5,
            markersize=7,
            label=METRIC_LABELS[metric],
        )
        for metric in METRICS
    ]
    fig.legend(
        handles=metric_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.79),
        ncol=3,
        columnspacing=1.8,
        handletextpad=0.5,
    )

    fig.suptitle(
        "RQ3｜忽略极端天气会导致未来能源规划低估多少风险？",
        fontsize=12.5,
        fontweight="bold",
        y=0.975,
    )
    add_framework(fig)
    fig.text(
        0.5,
        0.045,
        (
            f"模拟数据；每个箱体 n={args.n_simulations} 个候选规划组合；"
            "箱体表示四分位距，中线为中位数，须线为 1.5×IQR；斜线填充表示风险修正规划。"
        ),
        ha="center",
        fontsize=6.5,
        color="#555555",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)
    return args.output


def main() -> None:
    args = parse_args()
    output = make_figure(args)
    print(f"已保存：{output}")


if __name__ == "__main__":
    main()
