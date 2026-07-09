#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ2 补充图：不同事件的容量加权极端暴露时间。

图形为 2×3 填充面积折线图：行表示技术（风电、光伏），列表示 SSP。
每个子图按事件类型拆分容量加权极端暴露时间（天/GW年）。

注意：若同一时间步同时触发多个事件，不同事件会分别计入各自面积；
因此堆叠总高度表示“事件类型暴露时间之和”，不强制等于“任一事件”暴露时间。
"""

from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from plot_RQ2_extreme_exposure_change_stacked import (
    DEFAULT_INPUT_ROOT,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCES,
    DEFAULT_SSPS,
    EVENT_C,
    EVENT_LABEL,
    EXCLUDE_GRID_REGIONS,
    RESERVED_REGIONS,
    TECH_EVENTS,
    TECH_LABEL,
    SSP_L,
    annual_event_file,
    configure_style,
    find_signal_file,
    parse_years,
    panel_tag,
)


ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2：绘制不同事件的容量加权极端暴露时间填充面积图。",
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
        "--event-summary-csv",
        type=Path,
        default=None,
        help="事件年度容量加权汇总 CSV。默认优先读取输出目录中的 RQ2_extreme_exposure_event_area_capacity_weighted.csv。",
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


def regional_countries() -> list[str]:
    grid_dir = ROOT / "data/grid_of_regions"
    countries = []
    for p in sorted(grid_dir.glob("*_grid.nc")):
        name = p.name.removesuffix("_grid.nc")
        if name not in EXCLUDE_GRID_REGIONS:
            countries.append(name)
    return countries


def requested_keys(args: argparse.Namespace, years: list[int]) -> set[tuple[str, str, str, int]]:
    return {
        (ssp, tech, event, year)
        for ssp in args.ssps
        for tech in ("wind", "solar")
        for event in TECH_EVENTS[tech]
        for year in years
    }


def existing_keys(summary: pd.DataFrame) -> set[tuple[str, str, str, int]]:
    return set(
        summary[["ssp", "tech", "event", "year"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )


def summary_covers_request(summary: pd.DataFrame, args: argparse.Namespace, years: list[int]) -> bool:
    needed = requested_keys(args, years)
    have = set(
        summary[["ssp", "tech", "event", "year"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    return needed.issubset(have)


def load_or_build_event_summary(args: argparse.Namespace, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    years = parse_years(args.years)
    event_csv = args.event_summary_csv or (out_dir / "csv/RQ2_extreme_exposure_event_area_capacity_weighted.csv")
    fallback_event_csv = out_dir / "csv/RQ2_extreme_exposure_event_annual_capacity_weighted.csv"
    existing = pd.DataFrame()
    years_to_build = years
    if event_csv.exists():
        existing = pd.read_csv(event_csv)
    elif fallback_event_csv.exists():
        existing = pd.read_csv(fallback_event_csv)

    if not existing.empty:
        if summary_covers_request(existing, args, years):
            annual = existing[existing["year"].isin(years)].copy()
            missing_csv = out_dir / "csv/RQ2_missing_change_inputs.csv"
            missing = pd.read_csv(missing_csv) if missing_csv.exists() else pd.DataFrame()
            return annual, missing
        missing_keys = requested_keys(args, years) - existing_keys(existing)
        years_to_build = sorted({key[3] for key in missing_keys})

    regions = args.regions if args.regions else regional_countries()
    if args.include_reserved_regions:
        regions = list(dict.fromkeys([*regions, *RESERVED_REGIONS]))

    rows = []
    missing = []
    for source in args.sources:
        for region in regions:
            for ssp in args.ssps:
                for tech in ("wind", "solar"):
                    path = find_signal_file(args.input_root, source, args.model, region, ssp, tech)
                    if path is None:
                        missing.append({"source": source, "region": region, "ssp": ssp, "tech": tech})
                        continue
                    file_rows = annual_event_file(path, source, tech, years_to_build, args.dt_hours)
                    for row in file_rows:
                        row.update({"region": region, "ssp": ssp})
                    rows.extend(file_rows)

    raw = pd.DataFrame(rows)
    if raw.empty and existing.empty:
        raise SystemExit("未找到指定模式/数据源/区域/SSP 对应的场站信号 NetCDF 文件。")

    if raw.empty:
        built = pd.DataFrame()
    else:
        built = (
            raw.groupby(["ssp", "tech", "event", "year"], as_index=False)
            .agg(signal_gw_days=("signal_gw_days", "sum"), active_capacity_gw=("active_capacity_gw", "sum"))
        )
        built["exposed_days_per_gw_year"] = np.where(
            built["active_capacity_gw"] > 0,
            built["signal_gw_days"] / built["active_capacity_gw"],
            0.0,
        )

    if existing.empty:
        annual = built
    elif built.empty:
        annual = existing
    else:
        annual = pd.concat([existing, built], ignore_index=True)
        annual = annual.drop_duplicates(subset=["ssp", "tech", "event", "year"], keep="last")
    annual = annual[
        annual["year"].isin(years)
        & annual["ssp"].isin(args.ssps)
        & annual["tech"].isin(["wind", "solar"])
    ].copy()

    missing_df = pd.DataFrame(missing)
    if not args.quiet_missing and not missing_df.empty:
        warnings.warn(
            f"{len(missing_df)} 个 数据源/区域/SSP/技术 组合缺少场站信号文件；"
            "在 26 国统计框架中按零贡献保留。",
            RuntimeWarning,
        )
    return annual, missing_df


def plot_event_area(annual: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    fig, axes = plt.subplots(2, 3, figsize=(8.4, 5.0), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.78, bottom=0.15, wspace=0.28, hspace=0.34)

    panel_tags = iter(["a", "b", "c", "d", "e", "f"])
    for row, tech in enumerate(["wind", "solar"]):
        events = TECH_EVENTS[tech]
        for col, ssp in enumerate(args.ssps):
            ax = axes[row, col]
            sub = annual[(annual["tech"] == tech) & (annual["ssp"] == ssp)]
            pivot = (
                sub.pivot_table(
                    index="year",
                    columns="event",
                    values="exposed_days_per_gw_year",
                    aggfunc="sum",
                    fill_value=0.0,
                )
                .reindex(columns=events, fill_value=0.0)
                .sort_index()
            )
            years = pivot.index.to_numpy(dtype=float)
            values = [pivot[event].to_numpy(dtype=float) for event in events]
            colors = [EVENT_C[event] for event in events]
            labels = [EVENT_LABEL[event] for event in events]
            if len(years):
                ax.stackplot(years, values, colors=colors, alpha=0.58, linewidth=0.0, labels=labels)
                total = np.sum(np.vstack(values), axis=0) if values else np.zeros_like(years)
                ax.plot(years, total, color="0.25", lw=0.8)
            ax.set_title(f"{TECH_LABEL[tech]} · {SSP_L.get(ssp, ssp)}", fontsize=8.5)
            ax.grid(axis="y", lw=0.35, alpha=0.4)
            ax.set_xlabel("年份" if row == 1 else "")
            if col == 0:
                ax.set_ylabel("极端暴露（天/GW年）")
            panel_tag(ax, next(panel_tags), dx=-0.12, dy=1.08)

    wind_handles = [
        Patch(fc=EVENT_C[event], ec="none", alpha=0.58, label=EVENT_LABEL[event])
        for event in TECH_EVENTS["wind"]
    ]
    solar_handles = [
        Patch(fc=EVENT_C[event], ec="none", alpha=0.58, label=EVENT_LABEL[event])
        for event in TECH_EVENTS["solar"]
    ]
    fig.legend(
        handles=wind_handles,
        title="风电极端事件",
        loc="upper center",
        ncol=len(wind_handles),
        bbox_to_anchor=(0.28, 0.965),
    )
    fig.legend(
        handles=solar_handles,
        title="光伏极端事件",
        loc="upper center",
        ncol=len(solar_handles),
        bbox_to_anchor=(0.72, 0.965),
    )
    fig.suptitle(f"不同事件的容量加权极端暴露时间（{args.model}）", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.04,
        "面积表示各事件类型的容量加权暴露时间；同一时间步多事件并发时，各事件分别计入。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    out_base = out_dir / "fig_RQ2_extreme_exposure_event_area_capacity_weighted"
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    annual, missing = load_or_build_event_summary(args, out_dir)
    annual.to_csv(out_dir / "csv/RQ2_extreme_exposure_event_area_capacity_weighted.csv", index=False)
    if not missing.empty:
        missing.to_csv(out_dir / "csv/RQ2_missing_event_area_inputs.csv", index=False)

    path = plot_event_area(annual, args, out_dir)
    print(f"已保存：{path}")
    print(f"已保存汇总表：{out_dir / 'csv/RQ2_extreme_exposure_event_area_capacity_weighted.csv'}")
    if not missing.empty:
        print(f"缺失组合记录：{out_dir / 'csv/RQ2_missing_event_area_inputs.csv'}")


if __name__ == "__main__":
    main()
