#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ2 补充图：容量加权极端暴露率时间序列。

该图复用容量加权极端暴露的年度汇总逻辑，将
“极端暴露（天/GW年）”换算为“极端暴露率（%）”：

    暴露率 = 极端暴露天数 / 当年天数 * 100

默认绘制 2030-2060 年，并只保存 PNG。
"""

from __future__ import annotations

import argparse
import calendar
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from plot_RQ2_extreme_exposure_timeseries_capacity_weighted import (
    DEFAULT_INPUT_ROOT,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCES,
    DEFAULT_SSPS,
    SSP_C,
    SSP_L,
    TECH_LABEL,
    build_summary,
    configure_style,
    panel_tag,
    parse_years,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2：绘制容量加权全球极端暴露率时间序列。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=DEFAULT_SOURCES,
        help="场站信号数据源层。预留值：china_cmfd_bcsd、cordex_nam12。",
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT, help="station_signals_pipelineB 输出根目录。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。默认：RQ2/outputs/{MODEL}。")
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=None,
        help="容量加权年度暴露汇总 CSV。默认优先读取输出目录中的 RQ2_extreme_exposure_timeseries_capacity_weighted.csv。",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        default=None,
        help="纳入统计的区域。默认使用 data/grid_of_regions 中的 26 个 regional-BCSD 国家。",
    )
    parser.add_argument("--include-reserved-regions", action="store_true", help="若文件存在，同时纳入预留的 china 与 NAM-12 区域。")
    parser.add_argument("--years", default="2030-2060", help="绘图年份范围，格式为 YYYY-YYYY。")
    parser.add_argument("--dt-hours", type=float, default=None, help="手动指定时间步长（小时）。默认从 time 坐标或数据源推断。")
    parser.add_argument("--quiet-missing", action="store_true", help="不显示缺失文件警告。")
    return parser.parse_args()


def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(int(year)) else 365


def add_exposure_rate(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    out["days_in_year"] = out["year"].map(days_in_year)
    out["capacity_weighted_exposure_rate_pct"] = (
        out["exposed_days_per_gw_year"] / out["days_in_year"] * 100.0
    )
    return out


def load_or_build_summary(args: argparse.Namespace, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_csv = args.summary_csv or (out_dir / "csv/RQ2_extreme_exposure_timeseries_capacity_weighted.csv")
    years = set(parse_years(args.years))
    if summary_csv.exists():
        summary = pd.read_csv(summary_csv)
        summary = summary[summary["year"].isin(years)].copy()
        missing_csv = out_dir / "csv/RQ2_missing_capacity_weighted_inputs.csv"
        missing = pd.read_csv(missing_csv) if missing_csv.exists() else pd.DataFrame()
        return summary, missing
    return build_summary(args)


def add_linear_trend(ax, x, y, color: str) -> None:
    xs = np.asarray(x, dtype=float)
    ys = np.asarray(y, dtype=float)
    ok = np.isfinite(xs) & np.isfinite(ys)
    if ok.sum() < 2 or np.ptp(xs[ok]) == 0:
        return
    coef = np.polyfit(xs[ok], ys[ok], 1)
    ax.plot(xs[ok], np.polyval(coef, xs[ok]), "--", color=color, lw=1.0, alpha=0.9, zorder=1)


def plot_rate(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.2), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.82, bottom=0.2, wspace=0.28)

    for ax, tech, tag in zip(axes, ["wind", "solar"], ["a", "b"]):
        dtech = summary[summary["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["ssp"] == ssp].sort_values("year")
            if sub.empty:
                continue
            ax.plot(
                sub["year"],
                sub["capacity_weighted_exposure_rate_pct"],
                "-",
                color=SSP_C.get(ssp, "0.3"),
                lw=1.8,
                label=SSP_L.get(ssp, ssp),
            )
            add_linear_trend(ax, sub["year"], sub["capacity_weighted_exposure_rate_pct"], SSP_C.get(ssp, "0.3"))
        ax.set_title(f"{TECH_LABEL[tech]}：容量加权极端暴露率", fontsize=9)
        ax.set_xlabel("年份")
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    axes[0].set_ylabel("极端暴露率（%）")
    handles = [
        Line2D([0], [0], color=SSP_C.get(s, "0.3"), lw=1.8, label=SSP_L.get(s, s))
        for s in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(f"全球26国容量加权极端天气暴露率时间序列（{args.model}）", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.04,
        "暴露率 = 容量加权极端暴露天数 / 当年天数；缺失国家-情景-技术文件按零贡献保留。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    out_base = out_dir / "fig_RQ2_extreme_exposure_rate_capacity_weighted"
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    summary, missing = load_or_build_summary(args, out_dir)
    summary = add_exposure_rate(summary)
    summary.to_csv(out_dir / "csv/RQ2_extreme_exposure_rate_capacity_weighted.csv", index=False)
    if not missing.empty:
        missing.to_csv(out_dir / "csv/RQ2_missing_capacity_weighted_rate_inputs.csv", index=False)

    path = plot_rate(summary, args, out_dir)
    print(f"已保存：{path}")
    print(f"已保存汇总表：{out_dir / 'csv/RQ2_extreme_exposure_rate_capacity_weighted.csv'}")
    if not missing.empty:
        print(f"缺失组合记录：{out_dir / 'csv/RQ2_missing_capacity_weighted_rate_inputs.csv'}")


if __name__ == "__main__":
    main()
