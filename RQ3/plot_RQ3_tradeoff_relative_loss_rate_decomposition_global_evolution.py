#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制全球风光相对损失率的两因素与三因素分解。

两因素分解：

    相对损失率 = episode 数 / 总发电量 × 净出力损失 / episode 数

三因素分解：

    相对损失率
    = episode 数 / (装机容量 × 年数)
    × 净出力损失 / episode 数
    ÷ 总发电量 / (装机容量 × 年数)

两种分解均输出年代版本和可选线性趋势的逐年采样版本。
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

from plot_RQ3_extreme_event_frequency_intensity_global_evolution import (
    DEFAULT_OUTPUT_DIR,
)
from plot_RQ3_generation_loss_global_evolution import (
    apply_temp_wind_energy_correction,
    configure_style,
    panel_tag,
)
from plot_RQ3_generation_loss_global_rate_evolution import (
    ANALYSIS_K,
    DECADE_LABEL,
    DECADE_ORDER,
    DEFAULT_INPUT_CSV,
    DEFAULT_MODEL,
    DEFAULT_SSPS,
    SSP_C,
    SSP_L,
)
from plot_RQ3_tradeoff_station_level_metrics_global_evolution import (
    load_annual_components,
    plot_annual_metric,
)


TECHS = ["wind", "solar"]
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
DEFAULT_EVENT_CSV = (
    DEFAULT_OUTPUT_DIR
    / "{model}"
    / "csv/RQ3_extreme_event_frequency_intensity_global_evolution.csv"
)
TWO_FACTOR_OUT_STEM = "fig_RQ3_tradeoff_relative_loss_rate_two_factor_decomposition_global_evolution"
THREE_FACTOR_OUT_STEM = "fig_RQ3_tradeoff_relative_loss_rate_three_factor_decomposition_global_evolution"
CSV_NAME = "RQ3_relative_loss_rate_decomposition_global_evolution.csv"
ANNUAL_CSV_NAME = "RQ3_tradeoff_relative_loss_rate_decomposition_global_annual_evolution.csv"
TWO_FACTOR_METRICS = [
    ("event_frequency_per_generation_mwh", "单位发电量事件频次", "次/MWh"),
    ("loss_per_episode_mwh", "单次事件净损失", "MWh/episode"),
    ("relative_loss_rate_pct", "相对损失率", "%"),
]
THREE_FACTOR_METRICS = [
    ("event_frequency_per_mw_year", "单位装机事件频次", "次/(MW·年)"),
    ("loss_per_episode_mwh", "单次事件净损失", "MWh/episode"),
    ("generation_per_mw_year_mwh", "单位装机平均发电量", "MWh/(MW·年)"),
    ("relative_loss_rate_pct", "相对损失率", "%"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制相对损失率的两因素与三因素分解图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--event-csv",
        type=Path,
        default=None,
        help="全球 episode 与净损失汇总 CSV。",
    )
    parser.add_argument(
        "--generation-loss-csv",
        type=Path,
        default=None,
        help="generation_loss aggregate 的 region 级年度长表 CSV。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出根目录；图像保存到其 tradeoff/ 子目录。默认：RQ3/outputs/{MODEL}。",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=2,
        help="逐年图相邻采样点之间跳过的年份数；0 表示每年、1 表示每两年。",
    )
    parser.add_argument(
        "--trend-line",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="是否在逐年图中绘制各 SSP 的线性趋势虚线。",
    )
    return parser.parse_args()


def load_summary(args: argparse.Namespace) -> pd.DataFrame:
    event_csv = args.event_csv or Path(str(DEFAULT_EVENT_CSV).format(model=args.model))
    loss_csv = args.generation_loss_csv or Path(str(DEFAULT_INPUT_CSV).format(model=args.model))
    if not event_csv.exists():
        raise SystemExit(f"未找到事件汇总表：{event_csv}")
    if not loss_csv.exists():
        raise SystemExit(f"未找到发电损失表：{loss_csv}")

    required_event = {
        "scenario",
        "tech",
        "snapshot_year",
        "episode_count_total",
        "capacity_mw_mean",
        "n_years",
        "net_loss_mwh",
    }
    events = pd.read_csv(event_csv)
    missing = sorted(required_event.difference(events.columns))
    if missing:
        raise KeyError(f"事件汇总表缺少字段：{', '.join(missing)}")
    events = events[
        events["scenario"].isin(args.ssps) & events["tech"].isin(TECHS)
    ].copy()

    loss = pd.read_csv(loss_csv)
    loss = loss[
        (loss["model"] == args.model)
        & (loss["analysis_scheme"] == "center-k")
        & (loss["analysis_k"] == ANALYSIS_K)
        & (loss["event"] == "all")
        & (loss["scenario"].isin(args.ssps))
        & (loss["tech"].isin(TECHS))
    ].copy()
    if events.empty or loss.empty:
        raise SystemExit("输入数据中没有匹配当前模式、SSP 和技术的数据。")

    # 临时修正：风电发电量与损失能量字段统一乘以 0.1；装机容量不缩放。
    apply_temp_wind_energy_correction(loss, context="相对损失率分解图")
    generation = (
        loss.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            generation_mwh=("normal_all_generation_mwh", "sum"),
            raw_net_loss_mwh=("net_generation_loss_mwh", "sum"),
            generation_n_years=("analysis_year", "nunique"),
        )
    )
    data = events.merge(
        generation,
        on=["scenario", "tech", "snapshot_year"],
        how="inner",
        validate="one_to_one",
    )
    if len(data) != len(events):
        raise ValueError("事件汇总表与发电量汇总表未能逐项匹配。")
    if not np.allclose(data["net_loss_mwh"], data["raw_net_loss_mwh"], rtol=1e-10):
        raise ValueError("事件汇总表与发电损失表的净损失量不一致。")
    if not (data["n_years"] == data["generation_n_years"]).all():
        raise ValueError("事件汇总与发电量汇总的窗口年数不一致。")

    valid = (
        (data["episode_count_total"] > 0)
        & (data["capacity_mw_mean"] > 0)
        & (data["n_years"] > 0)
        & (data["generation_mwh"] > 0)
    )
    data["event_frequency_per_generation_mwh"] = np.where(
        valid,
        data["episode_count_total"] / data["generation_mwh"],
        np.nan,
    )
    data["loss_per_episode_mwh"] = np.where(
        valid,
        data["net_loss_mwh"] / data["episode_count_total"],
        np.nan,
    )
    data["event_frequency_per_mw_year"] = np.where(
        valid,
        data["episode_count_total"] / data["capacity_mw_mean"] / data["n_years"],
        np.nan,
    )
    data["generation_per_mw_year_mwh"] = np.where(
        valid,
        data["generation_mwh"] / data["capacity_mw_mean"] / data["n_years"],
        np.nan,
    )
    data["relative_loss_rate_pct"] = np.where(
        valid,
        data["net_loss_mwh"] / data["generation_mwh"] * 100.0,
        np.nan,
    )
    data["two_factor_rate_pct"] = (
        data["event_frequency_per_generation_mwh"]
        * data["loss_per_episode_mwh"]
        * 100.0
    )
    data["three_factor_rate_pct"] = (
        data["event_frequency_per_mw_year"]
        * data["loss_per_episode_mwh"]
        / data["generation_per_mw_year_mwh"]
        * 100.0
    )
    data["two_factor_abs_error_pct_point"] = (
        data["relative_loss_rate_pct"] - data["two_factor_rate_pct"]
    ).abs()
    data["three_factor_abs_error_pct_point"] = (
        data["relative_loss_rate_pct"] - data["three_factor_rate_pct"]
    ).abs()
    data["decade"] = data["snapshot_year"].map(DECADE_LABEL)
    return data


def build_annual_summary(args: argparse.Namespace) -> pd.DataFrame:
    annual = load_annual_components(args)
    loss_csv = args.generation_loss_csv or Path(
        str(DEFAULT_INPUT_CSV).format(model=args.model)
    )
    loss = pd.read_csv(loss_csv)
    loss = loss[
        (loss["model"] == args.model)
        & (loss["analysis_scheme"] == "center-k")
        & (loss["analysis_k"] == ANALYSIS_K)
        & (loss["event"] == "all")
        & loss["scenario"].isin(args.ssps)
        & loss["tech"].isin(TECHS)
    ].copy()
    if loss.empty:
        raise SystemExit("发电损失表中没有匹配当前模式、SSP 和技术的逐年数据。")
    apply_temp_wind_energy_correction(loss, context="相对损失率逐年分解图")
    generation = (
        loss.groupby(
            ["scenario", "tech", "snapshot_year", "analysis_year"],
            as_index=False,
        )
        .agg(
            generation_mwh=("normal_all_generation_mwh", "sum"),
            raw_net_loss_mwh=("net_generation_loss_mwh", "sum"),
        )
    )
    data = annual.merge(
        generation,
        on=["scenario", "tech", "snapshot_year", "analysis_year"],
        how="inner",
        validate="one_to_one",
    )
    if len(data) != len(annual):
        raise ValueError("逐年事件数据与发电量数据未能逐项匹配。")
    if not np.allclose(data["net_loss_mwh"], data["raw_net_loss_mwh"], rtol=1e-10):
        raise ValueError("逐年事件缓存与发电损失表的净损失量不一致。")

    valid = (
        (data["episode_count"] > 0)
        & (data["capacity_mw"] > 0)
        & (data["generation_mwh"] > 0)
    )
    data["event_frequency_per_generation_mwh"] = np.where(
        valid,
        data["episode_count"] / data["generation_mwh"],
        np.nan,
    )
    data["loss_per_episode_mwh"] = np.where(
        valid,
        data["net_loss_mwh"] / data["episode_count"],
        np.nan,
    )
    data["event_frequency_per_mw_year"] = np.where(
        valid,
        data["episode_count"] / data["capacity_mw"],
        np.nan,
    )
    data["generation_per_mw_year_mwh"] = np.where(
        valid,
        data["generation_mwh"] / data["capacity_mw"],
        np.nan,
    )
    data["relative_loss_rate_pct"] = np.where(
        valid,
        data["net_loss_mwh"] / data["generation_mwh"] * 100.0,
        np.nan,
    )
    data["two_factor_rate_pct"] = (
        data["event_frequency_per_generation_mwh"]
        * data["loss_per_episode_mwh"]
        * 100.0
    )
    data["three_factor_rate_pct"] = (
        data["event_frequency_per_mw_year"]
        * data["loss_per_episode_mwh"]
        / data["generation_per_mw_year_mwh"]
        * 100.0
    )
    data["two_factor_abs_error_pct_point"] = (
        data["relative_loss_rate_pct"] - data["two_factor_rate_pct"]
    ).abs()
    data["three_factor_abs_error_pct_point"] = (
        data["relative_loss_rate_pct"] - data["three_factor_rate_pct"]
    ).abs()
    return data.sort_values(["tech", "scenario", "analysis_year"]).reset_index(drop=True)


def plot_metric(ax, data: pd.DataFrame, args: argparse.Namespace, value_column: str) -> None:
    x = np.arange(len(DECADE_ORDER))
    for ssp in args.ssps:
        sub = data[data["scenario"] == ssp].set_index("snapshot_year").reindex(DECADE_ORDER)
        color = SSP_C.get(ssp, "0.3")
        ax.plot(
            x,
            sub[value_column].to_numpy(dtype=float),
            "-o",
            color=color,
            lw=1.8,
            ms=4,
            markeredgecolor=color,
            markerfacecolor="white",
            markeredgewidth=1.0,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([DECADE_LABEL[year] for year in DECADE_ORDER])
    ax.grid(axis="y", lw=0.4, alpha=0.45)
    ax.margins(x=0.12)


def plot_decomposition(
    summary: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
    metrics: list[tuple[str, str, str]],
    out_stem: str,
    title: str,
    note: str,
    *,
    annual: bool = False,
) -> Path:
    configure_style()
    n_columns = len(metrics)
    fig_width = 10.8 if n_columns == 3 else 14.2
    fig, axes = plt.subplots(2, n_columns, figsize=(fig_width, 5.8), sharex=True)
    fig.subplots_adjust(
        left=0.085 if n_columns == 3 else 0.065,
        right=0.99,
        top=0.84,
        bottom=0.16,
        wspace=0.34,
        hspace=0.36,
    )

    for row, tech in enumerate(TECHS):
        tech_data = summary[summary["tech"] == tech]
        for column, (value_column, column_title, unit) in enumerate(metrics):
            ax = axes[row, column]
            if annual:
                plot_annual_metric(ax, tech_data, args, value_column)
            else:
                plot_metric(ax, tech_data, args, value_column)
            ax.set_ylabel(unit)
            if row == 0:
                ax.set_title(column_title, fontsize=9, fontweight="bold")
            else:
                ax.set_xlabel("年份" if annual else "年代")
            ax.tick_params(axis="x", which="both", labelbottom=True)
            panel_tag(ax, chr(ord("a") + row * n_columns + column), dx=-0.13, dy=1.08)

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
        f"{title}（{'逐年采样，' if annual else ''}{args.model}）",
        fontsize=11,
        fontweight="bold",
        y=0.995,
    )
    figure_note = (
        f"采样点间隔为 {args.k + 1} 年（k={args.k}）；"
        + (
            "同色虚线为各 SSP 全部有效年份的一阶线性拟合。"
            if args.trend_line
            else ""
        )
        + note
        if annual
        else note
    )
    fig.text(0.5, 0.045, figure_note, ha="center", fontsize=6.2, color="0.4")

    suffix = f"_annual_k{args.k}" if annual else ""
    out_path = out_dir / f"{out_stem}{suffix}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> None:
    args = parse_args()
    if args.k < 0:
        raise SystemExit("k 必须大于或等于 0。")
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    figure_dir = out_dir / "tradeoff"
    csv_dir = out_dir / "csv"
    figure_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    summary = load_summary(args)
    annual = build_annual_summary(args)
    csv_path = csv_dir / CSV_NAME
    annual_csv_path = csv_dir / ANNUAL_CSV_NAME
    summary.to_csv(csv_path, index=False)
    annual.to_csv(annual_csv_path, index=False)
    two_factor_path = plot_decomposition(
        summary,
        args,
        figure_dir,
        TWO_FACTOR_METRICS,
        TWO_FACTOR_OUT_STEM,
        "全球风光相对损失率两因素分解",
        "相对损失率 = 单位发电量事件频次 × 单次事件净损失。",
    )
    three_factor_path = plot_decomposition(
        summary,
        args,
        figure_dir,
        THREE_FACTOR_METRICS,
        THREE_FACTOR_OUT_STEM,
        "全球风光相对损失率三因素分解",
        "相对损失率 = 单位装机事件频次 × 单次事件净损失 ÷ 单位装机平均发电量。",
    )
    two_factor_annual_path = plot_decomposition(
        annual,
        args,
        figure_dir,
        TWO_FACTOR_METRICS,
        TWO_FACTOR_OUT_STEM,
        "全球风光相对损失率两因素分解",
        "相对损失率 = 单位发电量事件频次 × 单次事件净损失。",
        annual=True,
    )
    three_factor_annual_path = plot_decomposition(
        annual,
        args,
        figure_dir,
        THREE_FACTOR_METRICS,
        THREE_FACTOR_OUT_STEM,
        "全球风光相对损失率三因素分解",
        "相对损失率 = 单位装机事件频次 × 单次事件净损失 ÷ 单位装机平均发电量。",
        annual=True,
    )
    print(f"已保存：{two_factor_path}")
    print(f"已保存：{three_factor_path}")
    print(f"已保存：{two_factor_annual_path}")
    print(f"已保存：{three_factor_annual_path}")
    print(f"已保存汇总表：{csv_path}")
    print(f"已保存逐年汇总表：{annual_csv_path}")
    print(
        "两因素分解最大绝对误差："
        f"{summary['two_factor_abs_error_pct_point'].max():.3e} 个百分点"
    )
    print(
        "三因素分解最大绝对误差："
        f"{summary['three_factor_abs_error_pct_point'].max():.3e} 个百分点"
    )


if __name__ == "__main__":
    main()
