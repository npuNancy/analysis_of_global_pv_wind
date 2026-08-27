#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制全球总量指标及场站级极端事件损失分解。

两张图均采用 2×3 布局：第一行为风电，第二行为光伏。第一张图展示
绝对损失量、极端事件总次数和场站级极端事件强度；第二张图展示
场站级绝对损失量、场站级极端事件次数和场站级极端事件强度。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_RQ3_generation_loss_global_evolution import configure_style, panel_tag
from plot_RQ3_generation_loss_global_per_capacity_evolution import (
    DECADE_LABEL,
    DECADE_ORDER,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SSPS,
    SSP_C,
    SSP_L,
)


TECHS = ["wind", "solar"]
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
DEFAULT_INPUT_CSV = (
    DEFAULT_OUTPUT_DIR
    / "{model}"
    / "csv/RQ3_extreme_event_frequency_intensity_global_evolution.csv"
)
GLOBAL_OUT_STEM = "fig_RQ3_tradeoff_station_level_metrics_global_evolution"
STATION_OUT_STEM = "fig_RQ3_tradeoff_station_level_decomposition_global_evolution"
CSV_NAME = "RQ3_tradeoff_station_level_metrics_global_evolution.csv"
GLOBAL_METRICS = [
    ("total_event_count_per_year", "极端事件总次数", "次/年"),
    ("loss_per_station_episode_mwh", "场站级极端事件强度", "MWh/场站事件"),
    ("absolute_loss_twh_per_year", "绝对损失量", "TWh/年"),
]
STATION_METRICS = [
    ("event_frequency_per_station_year", "场站级极端事件次数", "次/(场站·年)"),
    ("loss_per_station_episode_mwh", "场站级极端事件强度", "MWh/场站事件"),
    ("mean_loss_per_station_year_mwh", "场站级绝对损失量", "MWh/(场站·年)"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制全球总量指标及场站级损失分解的 2×3 演化图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help="全球 episode 与损失强度汇总 CSV。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认：RQ3/outputs/{MODEL}。",
    )
    return parser.parse_args()


def load_summary(args: argparse.Namespace) -> pd.DataFrame:
    input_csv = args.input_csv or Path(str(DEFAULT_INPUT_CSV).format(model=args.model))
    if not input_csv.exists():
        raise SystemExit(
            f"未找到输入汇总表：{input_csv}；请先运行 "
            "plot_RQ3_extreme_event_frequency_intensity_global_evolution.py。"
        )
    required = {
        "scenario",
        "tech",
        "snapshot_year",
        "episode_count_total",
        "station_count_mean",
        "n_years",
        "net_loss_mwh",
    }
    data = pd.read_csv(input_csv)
    missing = sorted(required.difference(data.columns))
    if missing:
        raise KeyError(f"输入汇总表缺少字段：{', '.join(missing)}")
    data = data[
        data["scenario"].isin(args.ssps) & data["tech"].isin(TECHS)
    ].copy()
    if data.empty:
        raise SystemExit("输入汇总表中没有匹配当前 SSP 和技术的数据。")

    valid_years = data["n_years"] > 0
    valid_episodes = data["episode_count_total"] > 0
    valid_stations = data["station_count_mean"] > 0
    data["absolute_loss_twh_per_year"] = np.where(
        valid_years,
        data["net_loss_mwh"] / data["n_years"] / 1e6,
        np.nan,
    )
    data["total_event_count_per_year"] = np.where(
        valid_years,
        data["episode_count_total"] / data["n_years"],
        np.nan,
    )
    data["event_frequency_per_station_year"] = np.where(
        valid_years & valid_stations,
        data["episode_count_total"] / data["station_count_mean"] / data["n_years"],
        np.nan,
    )
    data["mean_loss_per_station_year_mwh"] = np.where(
        valid_years & valid_stations,
        data["net_loss_mwh"] / data["station_count_mean"] / data["n_years"],
        np.nan,
    )
    data["loss_per_station_episode_mwh"] = np.where(
        valid_episodes,
        data["net_loss_mwh"] / data["episode_count_total"],
        np.nan,
    )
    data["decade"] = data["snapshot_year"].map(DECADE_LABEL)
    return data


def plot_metric(ax, data: pd.DataFrame, args: argparse.Namespace, value_column: str) -> None:
    x = np.arange(len(DECADE_ORDER))
    for ssp in args.ssps:
        sub = data[data["scenario"] == ssp].set_index("snapshot_year").reindex(DECADE_ORDER)
        ax.plot(
            x,
            sub[value_column].to_numpy(dtype=float),
            "-o",
            color=SSP_C.get(ssp, "0.3"),
            lw=1.8,
            ms=4,
            markeredgecolor=SSP_C.get(ssp, "0.3"),
            markerfacecolor="white",
            markeredgewidth=1.0,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([DECADE_LABEL[year] for year in DECADE_ORDER])
    ax.grid(axis="y", lw=0.4, alpha=0.45)
    ax.margins(x=0.12)


def plot_summary(
    summary: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
    metrics: list[tuple[str, str, str]],
    out_stem: str,
    title: str,
    note: str,
) -> Path:
    configure_style()
    fig, axes = plt.subplots(2, 3, figsize=(10.8, 5.8), sharex=True)
    fig.subplots_adjust(left=0.085, right=0.99, top=0.84, bottom=0.16, wspace=0.34, hspace=0.36)

    for row, tech in enumerate(TECHS):
        tech_data = summary[summary["tech"] == tech]
        for column, (value_column, column_title, unit) in enumerate(metrics):
            ax = axes[row, column]
            plot_metric(ax, tech_data, args, value_column)
            ax.set_ylabel(unit)
            if row == 0:
                ax.set_title(column_title, fontsize=9, fontweight="bold")
            else:
                ax.set_xlabel("年代")
            panel_tag(ax, chr(ord("a") + row * len(metrics) + column), dx=-0.13, dy=1.08)

    fig.text(0.015, 0.62, TECH_LABEL["wind"], rotation=90, ha="center", va="center", fontsize=10, fontweight="bold")
    fig.text(0.015, 0.29, TECH_LABEL["solar"], rotation=90, ha="center", va="center", fontsize=10, fontweight="bold")

    handles = [
        Line2D(
            [0],
            [0],
            color=SSP_C.get(ssp, "0.3"),
            lw=2.3,
            marker="o",
            ms=5,
            markerfacecolor="white",
            label=SSP_L.get(ssp, ssp),
        )
        for ssp in args.ssps
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        ncol=len(handles),
        bbox_to_anchor=(0.5, 0.955),
        fontsize=9,
        handlelength=2.4,
        handletextpad=0.6,
        columnspacing=1.6,
    )
    fig.suptitle(
        f"{title}（{args.model}）",
        fontsize=11,
        fontweight="bold",
        y=0.995,
    )
    fig.text(
        0.5,
        0.045,
        note,
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    out_path = out_dir / f"{out_stem}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    csv_dir = out_dir / "csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    summary = load_summary(args)
    csv_path = csv_dir / CSV_NAME
    summary.to_csv(csv_path, index=False)
    global_figure_path = plot_summary(
        summary,
        args,
        out_dir,
        GLOBAL_METRICS,
        GLOBAL_OUT_STEM,
        "全球风光极端事件损失总量与场站级强度演化",
        "绝对损失为十年窗口年均值；episode 为各技术事件并集的 False→True 起点；场站级强度 = 净出力损失/episode。",
    )
    station_figure_path = plot_summary(
        summary,
        args,
        out_dir,
        STATION_METRICS,
        STATION_OUT_STEM,
        "全球风光场站级极端事件损失分解",
        "场站级绝对损失 = 场站级极端事件次数 × 场站级极端事件强度。",
    )
    print(f"已保存：{global_figure_path}")
    print(f"已保存：{station_figure_path}")
    print(f"已保存汇总表：{csv_path}")


if __name__ == "__main__":
    main()
