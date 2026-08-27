#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制装机容量级极端事件频次与单次事件净损失的年代演化。

单位装机年损失被拆分为：

    单位装机年损失
    = episode 总数 / (装机容量 × 年数)
    × 净出力损失 / episode 总数

图采用 2×2 布局：上排为单位装机事件频次，下排为单次事件损失；左列为
风电，右列为光伏。episode 及净损失沿用全球频次—条件强度图的汇总结果。
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
OUT_STEM = "fig_RQ3_extreme_event_capacity_frequency_intensity_global_evolution"
TOTAL_OUT_STEM = "fig_RQ3_extreme_event_capacity_total_frequency_intensity_global_evolution"
CSV_NAME = "RQ3_extreme_event_capacity_frequency_intensity_global_evolution.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制装机容量级极端事件频次与单次事件净损失年代演化图。",
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
        "capacity_mw_mean",
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

    valid = (
        (data["episode_count_total"] > 0)
        & (data["capacity_mw_mean"] > 0)
        & (data["n_years"] > 0)
    )
    data["event_frequency_per_mw_year"] = np.where(
        valid,
        data["episode_count_total"] / data["capacity_mw_mean"] / data["n_years"],
        np.nan,
    )
    data["total_event_count_per_year"] = np.where(
        data["n_years"] > 0,
        data["episode_count_total"] / data["n_years"],
        np.nan,
    )
    data["loss_per_episode_mwh"] = np.where(
        data["episode_count_total"] > 0,
        data["net_loss_mwh"] / data["episode_count_total"],
        np.nan,
    )
    data["mean_loss_per_mw_year_mwh"] = np.where(
        valid,
        data["net_loss_mwh"] / data["capacity_mw_mean"] / data["n_years"],
        np.nan,
    )
    data["factorized_mean_loss_per_mw_year_mwh"] = (
        data["event_frequency_per_mw_year"] * data["loss_per_episode_mwh"]
    )
    data["factorization_abs_error_mwh"] = (
        data["mean_loss_per_mw_year_mwh"]
        - data["factorized_mean_loss_per_mw_year_mwh"]
    ).abs()
    data["decade"] = data["snapshot_year"].map(DECADE_LABEL)
    return data


def plot_metric(
    ax,
    data: pd.DataFrame,
    args: argparse.Namespace,
    *,
    value_column: str,
) -> None:
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
    *,
    total_count: bool = False,
) -> Path:
    configure_style()
    fig, axes = plt.subplots(2, 2, figsize=(7.4, 5.8), sharex=True)
    fig.subplots_adjust(left=0.12, right=0.98, top=0.86, bottom=0.15, wspace=0.25, hspace=0.36)

    for column, tech in enumerate(TECHS):
        tech_data = summary[summary["tech"] == tech]
        plot_metric(
            axes[0, column],
            tech_data,
            args,
            value_column=(
                "total_event_count_per_year"
                if total_count
                else "event_frequency_per_mw_year"
            ),
        )
        plot_metric(
            axes[1, column],
            tech_data,
            args,
            value_column="loss_per_episode_mwh",
        )
        axes[0, column].set_title(TECH_LABEL[tech], fontsize=10, fontweight="bold")
        axes[1, column].set_xlabel("年代")

    axes[0, 0].set_ylabel(
        "极端事件总次数\n（次/年）"
        if total_count
        else "单位装机事件频次\n（次/(MW·年)）"
    )
    axes[1, 0].set_ylabel("单次事件净损失\n（MWh/episode）")
    for index, ax in enumerate(axes.flat):
        panel_tag(ax, chr(ord("a") + index), dx=-0.11, dy=1.08)

    handles = [
        Line2D(
            [0],
            [0],
            color=SSP_C.get(ssp, "0.3"),
            lw=1.8,
            marker="o",
            ms=4,
            markerfacecolor="white",
            label=SSP_L.get(ssp, ssp),
        )
        for ssp in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.965))
    fig.suptitle(
        (
            f"极端事件总次数与单次事件净损失（装机容量级分解，{args.model}）"
            if total_count
            else f"装机容量级极端事件频次与单次事件净损失（{args.model}）"
        ),
        fontsize=11,
        fontweight="bold",
        y=1.0,
    )
    fig.text(
        0.5,
        0.045,
        (
            "总次数 = episode 数/窗口年数；下排保持为净出力损失/episode；episode 为事件并集的 False→True 起点。"
            if total_count
            else "单位装机年损失 = episode 数/(MW×年) × 净出力损失/episode；episode 为事件并集的 False→True 起点。"
        ),
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    out_path = out_dir / f"{TOTAL_OUT_STEM if total_count else OUT_STEM}.png"
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
    figure_path = plot_summary(summary, args, out_dir)
    total_figure_path = plot_summary(summary, args, out_dir, total_count=True)
    print(f"已保存：{figure_path}")
    print(f"已保存：{total_figure_path}")
    print(f"已保存汇总表：{csv_path}")
    print(f"分解最大绝对误差：{summary['factorization_abs_error_mwh'].max():.3e} MWh/(MW·年)")


if __name__ == "__main__":
    main()
