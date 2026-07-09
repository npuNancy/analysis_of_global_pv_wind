#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ2 图 1：非加权极端天气暴露时间序列。

本图把 Pipeline B 输出的场站级二值极端事件信号汇总为 26 个
regional-BCSD 国家年度全球暴露，每个场站权重相同：

    exposed days per station-year = sum(any_event_signal) * dt_hours / 24 / n_active_stations

China CMFD-BCSD 和 CORDEX NAM-12 通过 --sources 与
--include-reserved-regions 预留；在其场站级 Pipeline B 文件生成前，
默认不纳入统计。

示例
----
python RQ2/plot_RQ2_extreme_exposure_timeseries_unweighted.py
python RQ2/plot_RQ2_extreme_exposure_timeseries_unweighted.py --model NESM3 --ssps ssp126 ssp245
python RQ2/plot_RQ2_extreme_exposure_timeseries_unweighted.py --regions Australia Germany
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
from matplotlib.lines import Line2D


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
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
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
        description="RQ2：绘制非加权全球极端暴露时间序列。",
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
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="station_signals_pipelineB 输出根目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认：RQ2/outputs/{MODEL}。",
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=None,
        help="非加权年度暴露汇总 CSV。默认优先读取输出目录中的 RQ2_extreme_exposure_timeseries_unweighted.csv。",
    )
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
    parser.add_argument(
        "--years",
        default="2030-2060",
        help="绘图年份范围，格式为 YYYY-YYYY。",
    )
    parser.add_argument(
        "--dt-hours",
        type=float,
        default=None,
        help="手动指定时间步长（小时）。默认从 time 坐标或数据源推断。",
    )
    parser.add_argument(
        "--quiet-missing",
        action="store_true",
        help="不显示缺失国家/SSP/技术文件警告。",
    )
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


def annual_unweighted_file(path: Path, source: str, tech: str, target_years: list[int], dt_hours_arg: float | None):
    rows = []
    with h5py.File(path, "r") as f:
        years_by_step, time_dt_hours = read_time_years_h5(f)
        dt_hours = infer_dt_hours(f, source, dt_hours_arg, time_dt_hours)
        n_station = int(f["station"].shape[0])
        active_year = f["activation_year"][:].astype(int) if "activation_year" in f else np.full(n_station, -9999)
        signal_vars = [v for v in TECH_EVENTS[tech] if v in f]
        if signal_vars:
            event_any = np.zeros((len(years_by_step), n_station), dtype=bool)
            for var in signal_vars:
                event_any |= f[var][:].astype(bool)
        else:
            event_any = None

        for year in target_years:
            year_mask = years_by_step == year
            active = active_year <= year
            denom = float(active.sum())

            if denom <= 0 or event_any is None or not year_mask.any():
                signal_days = 0.0
            else:
                signal_days = float(event_any[year_mask][:, active].sum()) * dt_hours / 24.0

            rows.append(
                {
                    "source": source,
                    "tech": tech,
                    "year": year,
                    "signal_station_days": signal_days,
                    "active_stations": denom,
                    "dt_hours": dt_hours,
                    "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                }
            )
    return rows


def build_summary(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    years = parse_years(args.years)
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
                    file_rows = annual_unweighted_file(path, source, tech, years, args.dt_hours)
                    for row in file_rows:
                        row.update({"region": region, "ssp": ssp})
                    rows.extend(file_rows)

    raw = pd.DataFrame(rows)
    if raw.empty:
        raise SystemExit("未找到指定模式/数据源/区域/SSP 对应的场站信号 NetCDF 文件。")

    summary = (
        raw.groupby(["ssp", "tech", "year"], as_index=False)
        .agg(signal_station_days=("signal_station_days", "sum"), active_stations=("active_stations", "sum"))
    )
    summary["exposed_days_per_station_year"] = np.where(
        summary["active_stations"] > 0,
        summary["signal_station_days"] / summary["active_stations"],
        0.0,
    )

    missing_df = pd.DataFrame(missing)
    if not args.quiet_missing and not missing_df.empty:
        warnings.warn(
            f"{len(missing_df)} 个 数据源/区域/SSP/技术 组合缺少场站信号文件；"
            "在 26 国统计框架中按零贡献保留。",
            RuntimeWarning,
        )
    return summary, missing_df


def load_or_build_summary(args: argparse.Namespace, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_csv = args.summary_csv or (out_dir / "csv/RQ2_extreme_exposure_timeseries_unweighted.csv")
    years = set(parse_years(args.years))
    if summary_csv.exists():
        summary = pd.read_csv(summary_csv)
        summary = summary[summary["year"].isin(years)].copy()
        missing_csv = out_dir / "csv/RQ2_missing_unweighted_inputs.csv"
        missing = pd.read_csv(missing_csv) if missing_csv.exists() else pd.DataFrame()
        return summary, missing
    return build_summary(args)


def panel_tag(ax, tag: str, dx: float = -0.08, dy: float = 1.04) -> None:
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", ha="right")


def add_linear_trend(ax, x, y, color: str) -> None:
    xs = np.asarray(x, dtype=float)
    ys = np.asarray(y, dtype=float)
    ok = np.isfinite(xs) & np.isfinite(ys)
    if ok.sum() < 2 or np.ptp(xs[ok]) == 0:
        return
    coef = np.polyfit(xs[ok], ys[ok], 1)
    ax.plot(xs[ok], np.polyval(coef, xs[ok]), "--", color=color, lw=1.0, alpha=0.9, zorder=1)


def plot_summary(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.2), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.82, bottom=0.2, wspace=0.28)

    for ax, tech, tag in zip(axes, ["wind", "solar"], ["a", "b"]):
        dtech = summary[summary["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["ssp"] == ssp].sort_values("year")
            if sub.empty:
                continue
            color = SSP_C.get(ssp, "0.3")
            label = SSP_L.get(ssp, ssp)
            ax.plot(
                sub["year"],
                sub["exposed_days_per_station_year"],
                "-",
                color=color,
                lw=1.8,
                label=label,
            )
            add_linear_trend(ax, sub["year"], sub["exposed_days_per_station_year"], color)
        ax.set_title(f"{TECH_LABEL[tech]}：非加权极端暴露", fontsize=9)
        ax.set_xlabel("年份")
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, tag)

    axes[0].set_ylabel("极端暴露（天/场站年）")
    handles = [
        Line2D([0], [0], color=SSP_C.get(s, "0.3"), lw=1.8, label=SSP_L.get(s, s))
        for s in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(f"全球26国极端天气暴露时间序列（非加权，{args.model}）", fontsize=11, fontweight="bold", y=1.02)
    fig.text(
        0.5,
        0.04,
        "指标为任一支持事件发生的3小时步数折算天数，并除以当年已投产场站数；缺失国家-情景-技术文件按零贡献保留。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    out_base = out_dir / "fig_RQ2_extreme_exposure_timeseries_unweighted"
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    summary, missing = load_or_build_summary(args, out_dir)
    summary.to_csv(out_dir / "csv/RQ2_extreme_exposure_timeseries_unweighted.csv", index=False)
    if not missing.empty:
        missing.to_csv(out_dir / "csv/RQ2_missing_unweighted_inputs.csv", index=False)

    path = plot_summary(summary, args, out_dir)
    print(f"已保存：{path}")
    print(f"已保存汇总表：{out_dir / 'csv/RQ2_extreme_exposure_timeseries_unweighted.csv'}")
    if not missing.empty:
        print(f"缺失组合记录：{out_dir / 'csv/RQ2_missing_unweighted_inputs.csv'}")


if __name__ == "__main__":
    main()
