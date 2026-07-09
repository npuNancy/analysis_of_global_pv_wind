#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ2 图 3：未来期相对基准期的容量加权极端暴露变化。

脚本按技术和 SSP 计算各事件类型的暴露变化：

    Δ exposed days per GW-year =
        mean(2050-2060 annual exposure) - mean(2030-2040 annual exposure)

输出包含风电和光伏两个面板。每个面板按 SSP 绘制堆叠柱，
每个堆叠段代表一种事件类型。

China CMFD-BCSD 和 CORDEX NAM-12 通过 --sources 与
--include-reserved-regions 预留；在其场站级 Pipeline B 文件生成前，
默认不纳入统计。
"""

from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import h5py

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_ROOT = ROOT / "data/extreme_event_outputs/station_signals_pipelineB"
DEFAULT_OUTPUT_DIR = ROOT / "RQ2/outputs"
FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"

DEFAULT_MODEL = "NESM3"
DEFAULT_SSPS = ["ssp126", "ssp245", "ssp585"]
DEFAULT_SOURCES = ["regional_bcsd"]
RESERVED_SOURCES = ["china_cmfd_bcsd", "cordex_nam12"]
RESERVED_REGIONS = ["china", "NAM-12"]
EXCLUDE_GRID_REGIONS = {"china", "NAM-12"}

TECH_EVENTS = {
    "wind": ["signal_high_temp", "signal_high_wind"],
    "solar": ["signal_freezing_rain", "signal_rainstorm", "signal_cold_highwind"],
}
EVENT_LABEL = {
    "signal_high_temp": "高温",
    "signal_high_wind": "强风",
    "signal_freezing_rain": "冻雨",
    "signal_rainstorm": "暴雨",
    "signal_cold_highwind": "低温强风",
}
EVENT_C = {
    "signal_high_temp": "#c0392b",
    "signal_high_wind": "#3a6ea5",
    "signal_freezing_rain": "#9ecae9",
    "signal_rainstorm": "#54a24b",
    "signal_cold_highwind": "#6b5b95",
}
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}


def configure_style() -> None:
    from matplotlib import font_manager as fm

    if FONT_PATH.exists():
        fm.fontManager.addfont(str(FONT_PATH))
        font_name = fm.FontProperties(fname=str(FONT_PATH)).get_name()
        sans_serif = [font_name, "Arial", "DejaVu Sans"]
    else:
        sans_serif = ["Arial", "DejaVu Sans"]

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans_serif,
            "axes.unicode_minus": False,
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "legend.fontsize": 7,
            "legend.frameon": False,
            "figure.dpi": 120,
            "savefig.dpi": 350,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ2：绘制未来极端暴露变化的事件类型堆叠贡献。",
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
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None, help="默认：RQ2/outputs/{MODEL}。")
    parser.add_argument(
        "--regions",
        nargs="+",
        default=None,
        help="纳入统计的区域。默认使用 data/grid_of_regions 中的 26 个 regional-BCSD 国家。",
    )
    parser.add_argument(
        "--include-reserved-regions",
        action="store_true",
        help="若文件存在，同时纳入预留的 china 与 NAM-12 区域。",
    )
    parser.add_argument("--baseline-years", default="2030-2040", help="基准期窗口，格式为 YYYY-YYYY。")
    parser.add_argument("--future-years", default="2050-2060", help="未来期窗口，格式为 YYYY-YYYY。")
    parser.add_argument("--dt-hours", type=float, default=None, help="手动指定时间步长（小时）。")
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


def parse_years(years: str) -> list[int]:
    if "-" in years:
        lo, hi = (int(x) for x in years.split("-", 1))
        return list(range(lo, hi + 1))
    return [int(years)]


def find_signal_file(input_root: Path, source: str, model: str, region: str, ssp: str, tech: str) -> Path | None:
    base = input_root / source / model / region / ssp
    exact = base / f"station_signals_{tech}_{model}_{region}_{ssp}_2015-2060.nc"
    if exact.exists():
        return exact
    matches = sorted(base.glob(f"station_signals_{tech}_*_{ssp}_*.nc"))
    return matches[0] if matches else None


def _decode_attr(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def read_time_years_h5(f: h5py.File) -> tuple[np.ndarray, float | None]:
    time = f["time"][:]
    attrs = f["time"].attrs
    units = _decode_attr(attrs.get("units", ""))
    if " since " not in units:
        return np.full(time.shape, -9999, dtype=int), None

    unit, origin = units.split(" since ", 1)
    unit = unit.strip().lower()
    pandas_unit = {
        "hour": "h",
        "hours": "h",
        "day": "D",
        "days": "D",
        "minute": "m",
        "minutes": "m",
        "second": "s",
        "seconds": "s",
    }.get(unit)
    if pandas_unit is None:
        return np.full(time.shape, -9999, dtype=int), None

    dates = pd.to_datetime(origin.strip()) + pd.to_timedelta(time, unit=pandas_unit)
    dt_hours = None
    if len(time) >= 2:
        scale = {"h": 1.0, "D": 24.0, "m": 1.0 / 60.0, "s": 1.0 / 3600.0}[pandas_unit]
        dt_hours = float((time[1] - time[0]) * scale)
    return dates.year.to_numpy(dtype=int), dt_hours


def infer_dt_hours(f: h5py.File, source: str, override: float | None, time_dt_hours: float | None) -> float:
    if override is not None:
        return float(override)
    if time_dt_hours is not None and np.isfinite(time_dt_hours) and time_dt_hours > 0:
        return float(time_dt_hours)
    if "cordex" in source.lower() or "nam12" in source.lower():
        return 1.0
    return 3.0


def annual_event_file(path: Path, source: str, tech: str, target_years: list[int], dt_hours_arg: float | None):
    rows = []
    with h5py.File(path, "r") as f:
        years_by_step, time_dt_hours = read_time_years_h5(f)
        dt_hours = infer_dt_hours(f, source, dt_hours_arg, time_dt_hours)
        n_station = int(f["station"].shape[0])
        active_year = f["activation_year"][:].astype(int) if "activation_year" in f else np.full(n_station, -9999)
        capacity = f["capacity_gw"][:].astype(float) if "capacity_gw" in f else np.ones(n_station, dtype=float)
        event_arrays = {event: f[event][:].astype(bool) for event in TECH_EVENTS[tech] if event in f}

        for year in target_years:
            year_mask = years_by_step == year
            active = active_year <= year
            active_capacity = np.where(active, capacity, 0.0)
            denom = float(np.nansum(active_capacity))

            for event in TECH_EVENTS[tech]:
                if denom <= 0 or not year_mask.any() or event not in event_arrays:
                    signal_gw_days = 0.0
                else:
                    signal_gw_days = float(event_arrays[event][year_mask].dot(active_capacity).sum()) * dt_hours / 24.0
                rows.append(
                    {
                        "source": source,
                        "tech": tech,
                        "event": event,
                        "year": year,
                        "signal_gw_days": signal_gw_days,
                        "active_capacity_gw": denom,
                        "dt_hours": dt_hours,
                        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                    }
                )
    return rows


def build_summary(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline_years = parse_years(args.baseline_years)
    future_years = parse_years(args.future_years)
    years = sorted(set(baseline_years + future_years))
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
                    file_rows = annual_event_file(path, source, tech, years, args.dt_hours)
                    for row in file_rows:
                        row.update({"region": region, "ssp": ssp})
                    rows.extend(file_rows)

    raw = pd.DataFrame(rows)
    if raw.empty:
        raise SystemExit("未找到指定模式/数据源/区域/SSP 对应的场站信号 NetCDF 文件。")

    annual = (
        raw.groupby(["ssp", "tech", "event", "year"], as_index=False)
        .agg(signal_gw_days=("signal_gw_days", "sum"), active_capacity_gw=("active_capacity_gw", "sum"))
    )
    annual["exposed_days_per_gw_year"] = np.where(
        annual["active_capacity_gw"] > 0,
        annual["signal_gw_days"] / annual["active_capacity_gw"],
        0.0,
    )

    baseline = (
        annual[annual["year"].isin(baseline_years)]
        .groupby(["ssp", "tech", "event"], as_index=False)["exposed_days_per_gw_year"]
        .mean()
        .rename(columns={"exposed_days_per_gw_year": "baseline_exposed_days_per_gw_year"})
    )
    future = (
        annual[annual["year"].isin(future_years)]
        .groupby(["ssp", "tech", "event"], as_index=False)["exposed_days_per_gw_year"]
        .mean()
        .rename(columns={"exposed_days_per_gw_year": "future_exposed_days_per_gw_year"})
    )
    change = baseline.merge(future, on=["ssp", "tech", "event"], how="outer").fillna(0.0)
    change["delta_exposed_days_per_gw_year"] = (
        change["future_exposed_days_per_gw_year"] - change["baseline_exposed_days_per_gw_year"]
    )

    missing_df = pd.DataFrame(missing)
    if not args.quiet_missing and not missing_df.empty:
        warnings.warn(
            f"{len(missing_df)} 个 数据源/区域/SSP/技术 组合缺少场站信号文件；"
            "在 26 国统计框架中按零贡献保留。",
            RuntimeWarning,
        )
    return annual, change, missing_df


def panel_tag(ax, tag: str, dx: float = -0.08, dy: float = 1.04) -> None:
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", ha="right")


def plot_change(change: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), sharey=False)
    fig.subplots_adjust(left=0.1, right=0.98, top=0.8, bottom=0.22, wspace=0.34)

    for ax, tech, tag in zip(axes, ["wind", "solar"], ["a", "b"]):
        x = np.arange(len(args.ssps))
        pos_bottom = np.zeros(len(args.ssps), dtype=float)
        neg_bottom = np.zeros(len(args.ssps), dtype=float)
        for event in TECH_EVENTS[tech]:
            vals = []
            for ssp in args.ssps:
                sub = change[(change["tech"] == tech) & (change["ssp"] == ssp) & (change["event"] == event)]
                vals.append(float(sub["delta_exposed_days_per_gw_year"].iloc[0]) if not sub.empty else 0.0)
            vals_arr = np.asarray(vals)
            pos = np.clip(vals_arr, 0, None)
            neg = np.clip(vals_arr, None, 0)
            ax.bar(
                x,
                pos,
                bottom=pos_bottom,
                width=0.58,
                color=EVENT_C[event],
                edgecolor="white",
                lw=0.5,
                label=EVENT_LABEL[event],
            )
            ax.bar(
                x,
                neg,
                bottom=neg_bottom,
                width=0.58,
                color=EVENT_C[event],
                edgecolor="white",
                lw=0.5,
            )
            pos_bottom += pos
            neg_bottom += neg

        ax.axhline(0, color="0.35", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([SSP_L.get(s, s) for s in args.ssps], rotation=12)
        ax.set_title(f"{TECH_LABEL[tech]}：事件类型贡献", fontsize=9)
        ax.set_ylabel("Δ 极端暴露（天/GW年）")
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    handles = [Patch(fc=EVENT_C[e], ec="none", label=EVENT_LABEL[e]) for e in TECH_EVENTS["wind"] + TECH_EVENTS["solar"]]
    # 若未来事件集合出现重复标签，保留首次出现的图例项。
    uniq = {}
    for h in handles:
        uniq[h.get_label()] = h
    fig.legend(list(uniq.values()), list(uniq.keys()), loc="upper center", ncol=5, bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(f"未来期相对基准期的容量加权极端暴露变化（{args.model}）", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.04,
        f"Δ = {args.future_years} 年均暴露 − {args.baseline_years} 年均暴露；按当年已投产容量加权；缺失国家-情景-技术文件按零贡献保留。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    out_base = out_dir / "fig_RQ2_extreme_exposure_change_stacked"
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    annual, change, missing = build_summary(args)
    annual.to_csv(out_dir / "csv/RQ2_extreme_exposure_event_annual_capacity_weighted.csv", index=False)
    change.to_csv(out_dir / "csv/RQ2_extreme_exposure_change_stacked.csv", index=False)
    if not missing.empty:
        missing.to_csv(out_dir / "csv/RQ2_missing_change_inputs.csv", index=False)

    path = plot_change(change, args, out_dir)
    print(f"已保存：{path}")
    print(f"已保存年度汇总表：{out_dir / 'csv/RQ2_extreme_exposure_event_annual_capacity_weighted.csv'}")
    print(f"已保存变化汇总表：{out_dir / 'csv/RQ2_extreme_exposure_change_stacked.csv'}")
    if not missing.empty:
        print(f"缺失组合记录：{out_dir / 'csv/RQ2_missing_change_inputs.csv'}")


if __name__ == "__main__":
    main()
