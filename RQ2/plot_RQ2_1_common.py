#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2.1 高风险转变图的共享工具函数。

本文件供所有 ``plot_RQ2_1_*.py`` 脚本复用，统一完成：
1. 读取 Pipeline B 场站级极端事件 NetCDF；
2. 计算每个场站在指定年份的任一极端事件风险时长；
3. 使用 2030 cohort 的容量加权分位数定义高风险阈值；
4. 设置论文图常用的 matplotlib 样式和导出格式。

默认输出结构：
- 图件：``RQ2/outputs/{model}/``，默认只保存 PNG
- CSV 与缓存：``RQ2/outputs/{model}/csv/``
"""

from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib as mpl
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = ROOT / "data/extreme_event_outputs/station_signals_pipelineB"
DEFAULT_OUTPUT_ROOT = ROOT / "RQ2/outputs"
FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"

DEFAULT_MODEL = "NESM3"
DEFAULT_SSPS = ["ssp126", "ssp245", "ssp585"]
DEFAULT_SOURCES = ["regional_bcsd"]
DEFAULT_YEARS = [2030, 2040, 2050]
EXCLUDE_GRID_REGIONS = {"china", "NAM-12"}
RESERVED_REGIONS = ["china", "NAM-12"]

TECH_EVENTS = {
    "wind": [
        "signal_high_temp", "signal_high_wind",
        "signal_icing", "signal_hot_humid", "signal_low_resource",
    ],
    "solar": [
        "signal_freezing_rain", "signal_rainstorm", "signal_cold_highwind",
        "signal_high_humidity", "signal_icing", "signal_low_resource",
    ],
}
TECH_LABEL = {"wind": "Wind", "solar": "Solar PV"}
TECH_LABEL_CN = {"wind": "风电", "solar": "光伏"}
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}

TRANSITION_COLOR = {
    "remain_non_high": "#d8d8d8",
    "new_high": "#b64342",
    "remain_high": "#5b2a86",
    "deescalate": "#6aaed6",
}
TRANSITION_LABEL = {
    "remain_non_high": "Still non-high",
    "new_high": "Newly high risk",
    "remain_high": "Persistently high",
    "deescalate": "Moved out of high",
}


def configure_style() -> None:
    """设置统一绘图风格，并保证 SVG/PDF 中的文字可编辑。"""
    from matplotlib import font_manager as fm

    if FONT_PATH.exists():
        fm.fontManager.addfont(str(FONT_PATH))
        font_name = fm.FontProperties(fname=str(FONT_PATH)).get_name()
        sans_serif = [font_name, "Arial", "DejaVu Sans", "Liberation Sans"]
    else:
        sans_serif = ["Arial", "DejaVu Sans", "Liberation Sans"]

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans_serif,
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
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
            "figure.dpi": 130,
            "savefig.dpi": 350,
        }
    )


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要纳入的 SSP 情景。")
    parser.add_argument("--sources", nargs="+", default=DEFAULT_SOURCES, help="场站信号数据源层。")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT, help="Pipeline B 场站信号根目录。")
    parser.add_argument("--output-dir", type=Path, default=None, help="图件输出目录；默认 RQ2/outputs/{model}。")
    parser.add_argument("--regions", nargs="+", default=None, help="纳入区域；默认使用 26 个 regional-BCSD 国家。")
    parser.add_argument("--include-reserved-regions", action="store_true", help="若文件存在，同时纳入 china 与 NAM-12。")
    parser.add_argument("--years", nargs="+", type=int, default=DEFAULT_YEARS, help="分析年份。")
    parser.add_argument("--baseline-year", type=int, default=2030, help="定义高风险阈值的基准年。")
    parser.add_argument("--cohort-year", type=int, default=2030, help="定义高风险阈值的建设 cohort。")
    parser.add_argument(
        "--high-risk-quantile",
        type=float,
        default=0.8,
        help="容量加权高风险分位数；0.8 表示使用 P80 定义上尾高风险。",
    )
    parser.add_argument("--dt-hours", type=float, default=None, help="手动指定时间步长（小时）。")
    parser.add_argument("--refresh-cache", action="store_true", help="重新构建场站-年份风险缓存。")
    parser.add_argument("--quiet-missing", action="store_true", help="不显示缺失文件警告。")
    parser.add_argument(
        "--save-vector",
        action="store_true",
        help="额外保存 SVG/PDF；默认只保存 PNG。",
    )
    return parser


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    """补齐派生路径，保证所有 RQ2.1 脚本使用同一保存结构。"""
    if args.output_dir is None:
        args.output_dir = DEFAULT_OUTPUT_ROOT / args.model
    args.output_dir = Path(args.output_dir)
    args.csv_dir = args.output_dir / "csv"
    return args


def regional_countries() -> list[str]:
    """返回默认 regional-BCSD 国家清单，排除预留区域。"""
    grid_dir = ROOT / "data/grid_of_regions"
    countries = []
    for path in sorted(grid_dir.glob("*_grid.nc")):
        name = path.name.removesuffix("_grid.nc")
        if name not in EXCLUDE_GRID_REGIONS:
            countries.append(name)
    return countries


def find_signal_file(input_root: Path, source: str, model: str, region: str, ssp: str, tech: str) -> Path | None:
    """查找某个区域、情景、技术类型对应的场站信号文件。"""
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
    """读取时间坐标，返回每个时间步的年份和可推断的时间步长。"""
    time = f["time"][:]
    units = _decode_attr(f["time"].attrs.get("units", ""))
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


def infer_dt_hours(source: str, override: float | None, time_dt_hours: float | None) -> float:
    """推断时间步长；regional-BCSD 默认 3 小时。"""
    if override is not None:
        return float(override)
    if time_dt_hours is not None and np.isfinite(time_dt_hours) and time_dt_hours > 0:
        return float(time_dt_hours)
    if "cordex" in source.lower() or "nam12" in source.lower():
        return 1.0
    return 3.0


def weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    """计算容量加权分位数。"""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not ok.any():
        return float("nan")
    values = values[ok]
    weights = weights[ok]
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cum = np.cumsum(weights)
    cutoff = quantile * cum[-1]
    return float(values[np.searchsorted(cum, cutoff, side="left")])


def panel_tag(ax, tag: str, x: float = 0.01, y: float = 0.98) -> None:
    ax.text(x, y, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", ha="left", va="top")


def save_figure(fig, out_base: Path, *, save_vector: bool = False) -> list[Path]:
    """保存图件。

    默认只保存 PNG，减少 RQ2.1 批量调图时的输出文件数量。
    若命令行传入 ``--save-vector``，则额外保存 SVG/PDF，便于论文后期编辑。
    """
    out_base.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    if save_vector:
        paths.extend([out_base.with_suffix(".svg"), out_base.with_suffix(".pdf")])
    paths.append(out_base.with_suffix(".png"))
    for path in paths:
        fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return paths


def _year_selector(years_by_step: np.ndarray, year: int):
    idx = np.flatnonzero(years_by_step == year)
    if idx.size == 0:
        return None
    if np.all(np.diff(idx) == 1):
        return slice(int(idx[0]), int(idx[-1]) + 1)
    return idx


def station_year_rows_from_file(
    path: Path,
    source: str,
    model: str,
    region: str,
    ssp: str,
    tech: str,
    years: list[int],
    dt_hours_arg: float | None,
) -> list[dict]:
    """将单个场站信号 NetCDF 转为场站-年份风险时长记录。"""
    rows = []
    with h5py.File(path, "r") as f:
        years_by_step, time_dt_hours = read_time_years_h5(f)
        dt_hours = infer_dt_hours(source, dt_hours_arg, time_dt_hours)
        n_station = int(f["station"].shape[0])
        capacity = f["capacity_gw"][:].astype(float) if "capacity_gw" in f else np.ones(n_station, dtype=float)
        activation = f["activation_year"][:].astype(int) if "activation_year" in f else np.full(n_station, -9999)
        lon = f["station_lon"][:].astype(float) if "station_lon" in f else np.full(n_station, np.nan)
        lat = f["station_lat"][:].astype(float) if "station_lat" in f else np.full(n_station, np.nan)
        event_vars = [event for event in TECH_EVENTS[tech] if event in f]

        for year in years:
            selector = _year_selector(years_by_step, int(year))
            if selector is None or not event_vars:
                risk_days = np.zeros(n_station, dtype=float)
            else:
                n_step = len(range(selector.start, selector.stop)) if isinstance(selector, slice) else len(selector)
                any_event = np.zeros((n_step, n_station), dtype=bool)
                for event in event_vars:
                    any_event |= f[event][selector, :].astype(bool)
                risk_days = any_event.sum(axis=0).astype(float) * dt_hours / 24.0

            for i in range(n_station):
                rows.append(
                    {
                        "source": source,
                        "model": model,
                        "region": region,
                        "ssp": ssp,
                        "tech": tech,
                        "year": int(year),
                        "station_index": int(i),
                        "station_key": f"{source}|{model}|{region}|{ssp}|{tech}|{i}",
                        "activation_year": int(activation[i]),
                        "capacity_gw": float(capacity[i]),
                        "risk_days": float(risk_days[i]),
                        "station_lon": float(lon[i]),
                        "station_lat": float(lat[i]),
                    }
                )
    return rows


def build_station_year_risk(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """遍历输入组合，构建场站-年份风险明细表。"""
    regions = args.regions if args.regions else regional_countries()
    if args.include_reserved_regions:
        regions = list(dict.fromkeys([*regions, *RESERVED_REGIONS]))

    rows = []
    missing = []
    years = sorted(set(int(y) for y in args.years))
    for source in args.sources:
        for region in regions:
            for ssp in args.ssps:
                for tech in ("wind", "solar"):
                    path = find_signal_file(args.input_root, source, args.model, region, ssp, tech)
                    if path is None:
                        missing.append({"source": source, "model": args.model, "region": region, "ssp": ssp, "tech": tech})
                        continue
                    rows.extend(station_year_rows_from_file(path, source, args.model, region, ssp, tech, years, args.dt_hours))

    risk = pd.DataFrame(rows)
    if risk.empty:
        raise SystemExit("未找到符合当前 RQ2.1 参数的场站信号 NetCDF 文件。")
    missing_df = pd.DataFrame(missing)
    if not args.quiet_missing and not missing_df.empty:
        warnings.warn(
            f"{len(missing_df)} 个 source/region/SSP/tech 组合缺少场站信号文件，已在统计中跳过。",
            RuntimeWarning,
        )
    return risk, missing_df


def cache_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    out_dir = args.csv_dir
    years = "-".join(str(y) for y in sorted(set(int(y) for y in args.years)))
    ssps = "-".join(args.ssps)
    sources = "-".join(args.sources)
    stem = f"RQ2_1_station_year_risk_{args.model}_{sources}_{ssps}_{years}"
    return out_dir / f"{stem}.csv", out_dir / f"{stem}_missing.csv"


def load_or_build_station_year_risk(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读取或生成场站-年份风险缓存。"""
    args = normalize_args(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.csv_dir.mkdir(parents=True, exist_ok=True)
    risk_csv, missing_csv = cache_paths(args)
    if risk_csv.exists() and not args.refresh_cache:
        risk = pd.read_csv(risk_csv)
        missing = pd.read_csv(missing_csv) if missing_csv.exists() else pd.DataFrame()
        return risk, missing

    risk, missing = build_station_year_risk(args)
    risk.to_csv(risk_csv, index=False)
    if not missing.empty:
        missing.to_csv(missing_csv, index=False)
    return risk, missing


def high_risk_thresholds(
    risk: pd.DataFrame,
    baseline_year: int,
    cohort_year: int,
    quantile: float,
) -> pd.DataFrame:
    """按 SSP 和技术类型计算高风险阈值。"""
    baseline = risk[(risk["year"] == baseline_year) & (risk["activation_year"] == cohort_year)].copy()
    rows = []
    for (ssp, tech), sub in baseline.groupby(["ssp", "tech"], sort=False):
        threshold = weighted_quantile(sub["risk_days"].to_numpy(), sub["capacity_gw"].to_numpy(), quantile)
        rows.append(
            {
                "ssp": ssp,
                "tech": tech,
                "baseline_year": baseline_year,
                "cohort_year": cohort_year,
                "high_risk_quantile": quantile,
                "high_risk_threshold_days": threshold,
                "reference_station_count": int(len(sub)),
                "reference_capacity_gw": float(sub["capacity_gw"].sum()),
            }
        )
    return pd.DataFrame(rows)


def attach_high_risk(risk: pd.DataFrame, thresholds: pd.DataFrame) -> pd.DataFrame:
    """根据高风险阈值添加 ``is_high_risk`` 判定列。"""
    out = risk.merge(thresholds[["ssp", "tech", "high_risk_threshold_days"]], on=["ssp", "tech"], how="left")
    # 使用严格上尾规则，避免基准分位数为 0 时把零暴露场站也判为高风险。
    out["is_high_risk"] = out["risk_days"] > out["high_risk_threshold_days"]
    out.loc[~np.isfinite(out["high_risk_threshold_days"]), "is_high_risk"] = False
    return out


def capacity_weighted_mean(sub: pd.DataFrame) -> float:
    """计算容量加权平均风险时长。"""
    cap = sub["capacity_gw"].to_numpy(dtype=float)
    val = sub["risk_days"].to_numpy(dtype=float)
    denom = np.nansum(cap)
    if denom <= 0:
        return float("nan")
    return float(np.nansum(val * cap) / denom)
