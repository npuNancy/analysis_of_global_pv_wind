#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制全球极端事件频次与事件条件损失强度的年代演化。

图为 4×2 定量网格，两列分别为风电和光伏，四行依次为：

1. 单位装机事件频次：episode 总数 / 全球装机容量 / 窗口年数；
2. 场站级事件频次：episode 总数 / 全球场站数 / 窗口年数；
3. 容量加权条件损失：净损失 / (装机容量 × 事件持续小时)；
4. 场站级条件损失：净损失 / (场站数 × 事件持续小时)。

episode 从场站级二值信号识别：先对该技术支持的事件取并集，再将每个场站
由 False 变为 True 的时刻记为一次独立事件。默认不绘制误差条；传入
``--error-bar`` 可显示窗口内年度最小-最大值。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import warnings

import h5py
import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_RQ3_generation_loss_global_evolution import (
    apply_temp_wind_energy_correction,
    configure_style,
    panel_tag,
)
from plot_RQ3_generation_loss_global_per_capacity_evolution import (
    ANALYSIS_K,
    DECADE_LABEL,
    DECADE_ORDER,
    DECADE_WINDOWS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SSPS,
    SSP_C,
    SSP_L,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIGNAL_INPUT_ROOT = ROOT / "data/extreme_event_outputs/station_signals_pipelineB"
FALLBACK_SIGNAL_INPUT_ROOT = (
    ROOT.parent / "extreme_event_definitions/outputs/station_signals"
)
DEFAULT_STATION_INPUT_CSV = (
    ROOT
    / "data/generation_loss_outputs/generation_loss"
    / "{model}"
    / "aggregate/generation_loss_station.csv"
)
TECHS = ["wind", "solar"]
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
TECH_EVENTS = {
    "wind": [
        "signal_high_temp",
        "signal_high_wind",
        "signal_icing",
        "signal_hot_humid",
        "signal_low_resource",
    ],
    "solar": [
        "signal_freezing_rain",
        "signal_rainstorm",
        "signal_cold_highwind",
        "signal_high_humidity",
        "signal_icing",
        "signal_low_resource",
    ],
}
DEFAULT_SOURCE = "regional_bcsd"
OUT_STEM = "fig_RQ3_extreme_event_frequency_intensity_global_evolution"
CSV_NAME = "RQ3_extreme_event_frequency_intensity_global_evolution.csv"
EPISODE_CACHE_NAME = "RQ3_extreme_event_episode_annual_cache.csv"
INTENSITY_CACHE_NAME = "RQ3_extreme_event_intensity_annual_cache.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制全球极端事件频次与事件条件损失强度年代演化图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="场站信号数据源层。")
    parser.add_argument(
        "--event",
        default="all",
        choices=["all"],
        help="事件口径；当前仅支持该技术全部事件的并集。",
    )
    parser.add_argument(
        "--signal-input-root",
        type=Path,
        default=None,
        help="场站级二值极端事件信号根目录。",
    )
    parser.add_argument(
        "--station-input-csv",
        type=Path,
        default=None,
        help="generation_loss aggregate 的 station 级年度长表 CSV。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认：RQ3/outputs/{MODEL}。",
    )
    parser.add_argument(
        "--error-bar",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="是否绘制窗口内年度最小-最大值误差条。",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="忽略年度 episode 与损失强度缓存并重新计算。",
    )
    parser.add_argument(
        "--station-chunksize",
        type=int,
        default=500_000,
        help="分块读取 station 级损失 CSV 的行数。",
    )
    return parser.parse_args()


def resolve_signal_input_root(args: argparse.Namespace) -> Path:
    candidates = (
        [args.signal_input_root]
        if args.signal_input_root is not None
        else [DEFAULT_SIGNAL_INPUT_ROOT, FALLBACK_SIGNAL_INPUT_ROOT]
    )
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    searched = "、".join(str(path) for path in candidates if path is not None)
    raise SystemExit(f"未找到场站级极端事件信号目录，已检查：{searched}")


def find_signal_file(
    input_root: Path,
    source: str,
    model: str,
    region: str,
    ssp: str,
    tech: str,
) -> Path | None:
    base = input_root / source / model / region / ssp
    exact = base / f"station_signals_{tech}_{model}_{region}_{ssp}_2015-2060.nc"
    if exact.exists():
        return exact
    matches = sorted(base.glob(f"station_signals_{tech}_*_{ssp}_*.nc"))
    return matches[0] if matches else None


def _decode_attr(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def read_time_years(f: h5py.File) -> np.ndarray:
    """读取时间对应年份，并正确处理当前信号文件使用的 noleap 日历。"""
    time = f["time"][:].astype(float)
    attrs = f["time"].attrs
    units = _decode_attr(attrs.get("units", ""))
    calendar = _decode_attr(attrs.get("calendar", "standard")).lower()
    match = re.search(r"since\s+(\d{4})-", units)
    if match is None:
        raise ValueError(f"无法从 time units 解析起始年份：{units}")
    origin_year = int(match.group(1))
    if units.lower().startswith("hours") and calendar in {"noleap", "365_day"}:
        return origin_year + np.floor(time / (365.0 * 24.0)).astype(int)
    if units.lower().startswith("hours"):
        origin = pd.Timestamp(f"{origin_year}-01-01")
        return (origin + pd.to_timedelta(time, unit="h")).year.to_numpy(dtype=int)
    raise ValueError(f"当前不支持的 time units：{units}")


def count_episode_starts_by_snapshot(
    f: h5py.File,
    *,
    tech: str,
) -> dict[int, tuple[dict[int, int], int, float]]:
    """一次读取 2030–2059，统计三个固定 snapshot cohort 的 episode 起点。"""
    years = read_time_years(f)
    all_target_years = list(range(DECADE_ORDER[0], DECADE_ORDER[-1] + 2 * ANALYSIS_K))
    time_indices = np.flatnonzero(np.isin(years, all_target_years))
    if time_indices.size == 0:
        return {
            snapshot: ({year: 0 for year in range(snapshot, snapshot + 2 * ANALYSIS_K)}, 0, 0.0)
            for snapshot in DECADE_ORDER
        }
    if not np.all(np.diff(time_indices) == 1):
        raise ValueError("目标 2030–2059 窗口在 time 轴上不是连续区间。")

    activation = f["activation_year"][:].astype(int)
    active_indices = np.flatnonzero(activation <= DECADE_ORDER[-1])
    active_activation = activation[active_indices]
    capacity_gw = f["capacity_gw"][:].astype(float)
    active_capacity_gw = capacity_gw[active_indices]
    event_vars = [name for name in TECH_EVENTS[tech] if name in f]
    if not event_vars:
        return {
            snapshot: (
                {year: 0 for year in range(snapshot, snapshot + 2 * ANALYSIS_K)},
                int((active_activation <= snapshot).sum()),
                float(active_capacity_gw[active_activation <= snapshot].sum() * 1e3),
            )
            for snapshot in DECADE_ORDER
        }

    start = int(time_indices[0])
    stop = int(time_indices[-1]) + 1
    read_start = max(0, start - 1)
    years_window = years[start:stop]

    # 多数上游变量以“完整时间轴 × 全部场站”单块压缩；每个变量一次性读取
    # 2030–2059 与 2050 cohort，避免按场站或年代切片反复解压同一压缩块。
    union = np.zeros((stop - read_start, len(active_indices)), dtype=bool)
    for event_var in event_vars:
        union |= f[event_var][read_start:stop, active_indices].astype(bool)
    if read_start < start:
        previous = union[:-1].copy()
        union[1:] &= ~previous
        del previous
        starts = union[1:]
    else:
        previous = union[:-1].copy()
        union[1:] &= ~previous
        del previous
        starts = union

    episode_count_by_year_station = {
        year: starts[years_window == year].sum(axis=0) for year in all_target_years
    }
    results = {}
    for snapshot in DECADE_ORDER:
        cohort = active_activation <= snapshot
        target_years = range(snapshot, snapshot + 2 * ANALYSIS_K)
        counts = {
            year: int(episode_count_by_year_station[year][cohort].sum())
            for year in target_years
        }
        results[snapshot] = (
            counts,
            int(cohort.sum()),
            float(active_capacity_gw[cohort].sum() * 1e3),
        )
    return results


def build_episode_annual(args: argparse.Namespace, signal_root: Path) -> pd.DataFrame:
    model_root = signal_root / args.source / args.model
    if not model_root.exists():
        raise SystemExit(f"未找到模式对应的场站信号目录：{model_root}")
    regions = sorted(path.name for path in model_root.iterdir() if path.is_dir())
    rows: list[dict] = []
    missing: list[dict] = []
    for region in regions:
        for ssp in args.ssps:
            for tech in TECHS:
                path = find_signal_file(signal_root, args.source, args.model, region, ssp, tech)
                if path is None:
                    missing.append({"region": region, "scenario": ssp, "tech": tech})
                    continue
                with h5py.File(path, "r") as f:
                    by_snapshot = count_episode_starts_by_snapshot(f, tech=tech)
                    for snapshot_year, (counts, station_count, capacity_mw) in by_snapshot.items():
                        for analysis_year, episode_count in counts.items():
                            rows.append(
                                {
                                    "model": args.model,
                                    "source": args.source,
                                    "scenario": ssp,
                                    "region": region,
                                    "tech": tech,
                                    "snapshot_year": snapshot_year,
                                    "analysis_year": analysis_year,
                                    "episode_count": episode_count,
                                    "station_count": station_count,
                                    "capacity_mw": capacity_mw,
                                }
                            )
    if not rows:
        raise SystemExit("没有从场站级极端事件信号中识别到可统计的数据。")
    if missing:
        warnings.warn(
            f"{len(missing)} 个区域-情景-技术组合缺少场站信号文件，已跳过。",
            RuntimeWarning,
        )
    return pd.DataFrame(rows)


def load_or_build_episode_annual(
    args: argparse.Namespace,
    signal_root: Path,
    cache_path: Path,
) -> pd.DataFrame:
    if cache_path.exists() and not args.refresh_cache:
        cached = pd.read_csv(cache_path)
        selected = cached[
            (cached["model"] == args.model)
            & (cached["source"] == args.source)
            & (cached["scenario"].isin(args.ssps))
        ].copy()
        if set(args.ssps).issubset(selected["scenario"].unique()):
            print(f"已读取 episode 缓存：{cache_path}")
            return selected
    annual = build_episode_annual(args, signal_root)
    annual.to_csv(cache_path, index=False)
    print(f"已保存 episode 缓存：{cache_path}")
    return annual


def summarize_frequency(annual_raw: pd.DataFrame) -> pd.DataFrame:
    annual_raw = annual_raw.copy()
    annual_raw["active_region"] = annual_raw["station_count"] > 0
    annual = (
        annual_raw.groupby(
            ["scenario", "tech", "snapshot_year", "analysis_year"],
            as_index=False,
        )
        .agg(
            episode_count=("episode_count", "sum"),
            station_count=("station_count", "sum"),
            capacity_mw=("capacity_mw", "sum"),
            n_regions=("active_region", "sum"),
        )
    )
    annual["episode_frequency_per_mw_year"] = np.where(
        annual["capacity_mw"] > 0,
        annual["episode_count"] / annual["capacity_mw"],
        np.nan,
    )
    annual["episode_frequency_per_station_year"] = np.where(
        annual["station_count"] > 0,
        annual["episode_count"] / annual["station_count"],
        np.nan,
    )
    decade = (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            episode_count_total=("episode_count", "sum"),
            capacity_mw_mean=("capacity_mw", "mean"),
            station_count_mean=("station_count", "mean"),
            episode_frequency_per_mw_year_min=("episode_frequency_per_mw_year", "min"),
            episode_frequency_per_mw_year_max=("episode_frequency_per_mw_year", "max"),
            episode_frequency_per_station_year_min=("episode_frequency_per_station_year", "min"),
            episode_frequency_per_station_year_max=("episode_frequency_per_station_year", "max"),
            n_years=("analysis_year", "nunique"),
            n_regions_mean=("n_regions", "mean"),
        )
    )
    decade["episode_frequency_per_mw_year"] = (
        decade["episode_count_total"] / decade["capacity_mw_mean"] / decade["n_years"]
    )
    decade["episode_frequency_per_station_year"] = (
        decade["episode_count_total"] / decade["station_count_mean"] / decade["n_years"]
    )
    return decade


def build_intensity_annual(args: argparse.Namespace, station_csv: Path) -> pd.DataFrame:
    usecols = [
        "model",
        "scenario",
        "region",
        "tech",
        "snapshot_year",
        "analysis_scheme",
        "analysis_k",
        "analysis_year",
        "event",
        "station_id",
        "capacity_mw",
        "event_duration_hours",
        "net_generation_loss_mwh",
    ]
    parts = []
    for chunk in pd.read_csv(station_csv, usecols=usecols, chunksize=args.station_chunksize):
        selected = chunk[
            (chunk["model"] == args.model)
            & (chunk["analysis_scheme"] == "center-k")
            & (chunk["analysis_k"] == ANALYSIS_K)
            & (chunk["event"] == args.event)
            & (chunk["scenario"].isin(args.ssps))
            & (chunk["tech"].isin(TECHS))
        ].copy()
        if selected.empty:
            continue
        apply_temp_wind_energy_correction(selected, context="事件条件损失强度图")
        selected["capacity_event_hours"] = (
            selected["capacity_mw"] * selected["event_duration_hours"]
        )
        selected["station_event_hours"] = selected["event_duration_hours"]
        parts.append(
            selected.groupby(
                ["scenario", "tech", "snapshot_year", "analysis_year"],
                as_index=False,
            ).agg(
                net_loss_mwh=("net_generation_loss_mwh", "sum"),
                capacity_event_hours=("capacity_event_hours", "sum"),
                station_event_hours=("station_event_hours", "sum"),
                station_count=("station_id", "count"),
            )
        )
    if not parts:
        raise SystemExit("station 级损失 CSV 中没有匹配当前参数的数据。")
    annual = (
        pd.concat(parts, ignore_index=True)
        .groupby(["scenario", "tech", "snapshot_year", "analysis_year"], as_index=False)
        .agg(
            net_loss_mwh=("net_loss_mwh", "sum"),
            capacity_event_hours=("capacity_event_hours", "sum"),
            station_event_hours=("station_event_hours", "sum"),
            station_count=("station_count", "sum"),
        )
    )
    annual["loss_per_capacity_event_hour"] = np.where(
        annual["capacity_event_hours"] > 0,
        annual["net_loss_mwh"] / annual["capacity_event_hours"],
        np.nan,
    )
    annual["loss_per_station_event_hour"] = np.where(
        annual["station_event_hours"] > 0,
        annual["net_loss_mwh"] / annual["station_event_hours"],
        np.nan,
    )
    return annual


def load_or_build_intensity_annual(
    args: argparse.Namespace,
    station_csv: Path,
    cache_path: Path,
) -> pd.DataFrame:
    if cache_path.exists() and not args.refresh_cache:
        cached = pd.read_csv(cache_path)
        selected = cached[
            (cached["model"] == args.model)
            & (cached["scenario"].isin(args.ssps))
        ].copy()
        if set(args.ssps).issubset(selected["scenario"].unique()):
            print(f"已读取损失强度缓存：{cache_path}")
            return selected
    annual = build_intensity_annual(args, station_csv)
    annual.insert(0, "model", args.model)
    annual.to_csv(cache_path, index=False)
    print(f"已保存损失强度缓存：{cache_path}")
    return annual


def summarize_intensity(annual: pd.DataFrame) -> pd.DataFrame:
    decade = (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            net_loss_mwh=("net_loss_mwh", "sum"),
            capacity_event_hours=("capacity_event_hours", "sum"),
            station_event_hours=("station_event_hours", "sum"),
            loss_per_capacity_event_hour_min=("loss_per_capacity_event_hour", "min"),
            loss_per_capacity_event_hour_max=("loss_per_capacity_event_hour", "max"),
            loss_per_station_event_hour_min=("loss_per_station_event_hour", "min"),
            loss_per_station_event_hour_max=("loss_per_station_event_hour", "max"),
            intensity_n_years=("analysis_year", "nunique"),
        )
    )
    decade["loss_per_capacity_event_hour"] = np.where(
        decade["capacity_event_hours"] > 0,
        decade["net_loss_mwh"] / decade["capacity_event_hours"],
        np.nan,
    )
    decade["loss_per_station_event_hour"] = np.where(
        decade["station_event_hours"] > 0,
        decade["net_loss_mwh"] / decade["station_event_hours"],
        np.nan,
    )
    return decade


def build_summary(
    args: argparse.Namespace,
    *,
    signal_root: Path,
    station_csv: Path,
    csv_dir: Path,
) -> pd.DataFrame:
    episode_annual = load_or_build_episode_annual(
        args,
        signal_root,
        csv_dir / EPISODE_CACHE_NAME,
    )
    intensity_annual = load_or_build_intensity_annual(
        args,
        station_csv,
        csv_dir / INTENSITY_CACHE_NAME,
    )
    frequency = summarize_frequency(episode_annual)
    intensity = summarize_intensity(intensity_annual)
    summary = frequency.merge(
        intensity,
        on=["scenario", "tech", "snapshot_year"],
        how="outer",
        validate="one_to_one",
    )
    summary["decade"] = summary["snapshot_year"].map(DECADE_LABEL)
    expected_years = 2 * ANALYSIS_K
    incomplete = summary[
        (summary["n_years"] != expected_years)
        | (summary["intensity_n_years"] != expected_years)
    ]
    if not incomplete.empty:
        warnings.warn(
            f"{len(incomplete)} 个情景-技术-年代组合不含完整的 {expected_years} 年窗口。",
            RuntimeWarning,
        )
    return summary


def _plot_series(
    ax,
    data: pd.DataFrame,
    args: argparse.Namespace,
    *,
    value_column: str,
    min_column: str,
    max_column: str,
) -> None:
    x = np.arange(len(DECADE_ORDER))
    for ssp in args.ssps:
        sub = data[data["scenario"] == ssp].set_index("snapshot_year").reindex(DECADE_ORDER)
        mean = sub[value_column].to_numpy(dtype=float)
        lo = sub[min_column].to_numpy(dtype=float)
        hi = sub[max_column].to_numpy(dtype=float)
        color = SSP_C.get(ssp, "0.3")
        ax.errorbar(
            x,
            mean,
            yerr=[np.clip(mean - lo, 0, None), np.clip(hi - mean, 0, None)]
            if args.error_bar
            else None,
            fmt="-o",
            color=color,
            lw=1.8,
            ms=4,
            capsize=2.5,
            elinewidth=0.8,
            markeredgecolor=color,
            markerfacecolor="white",
            markeredgewidth=1.0,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([DECADE_LABEL[year] for year in DECADE_ORDER])
    ax.grid(axis="y", lw=0.4, alpha=0.45)
    ax.margins(x=0.12)


def plot_summary(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    fig, axes = plt.subplots(4, 2, figsize=(7.4, 9.4), sharex=True)
    fig.subplots_adjust(left=0.13, right=0.98, top=0.91, bottom=0.1, wspace=0.25, hspace=0.34)

    metrics = [
        (
            "episode_frequency_per_mw_year",
            "episode_frequency_per_mw_year_min",
            "episode_frequency_per_mw_year_max",
        ),
        (
            "episode_frequency_per_station_year",
            "episode_frequency_per_station_year_min",
            "episode_frequency_per_station_year_max",
        ),
        (
            "loss_per_capacity_event_hour",
            "loss_per_capacity_event_hour_min",
            "loss_per_capacity_event_hour_max",
        ),
        (
            "loss_per_station_event_hour",
            "loss_per_station_event_hour_min",
            "loss_per_station_event_hour_max",
        ),
    ]
    for column, tech in enumerate(TECHS):
        tech_data = summary[summary["tech"] == tech]
        for row, (value, minimum, maximum) in enumerate(metrics):
            _plot_series(
                axes[row, column],
                tech_data,
                args,
                value_column=value,
                min_column=minimum,
                max_column=maximum,
            )
        axes[0, column].set_title(TECH_LABEL[tech], fontsize=10, fontweight="bold")
        axes[-1, column].set_xlabel("年代")

    ylabels = [
        "单位装机事件频次\n（次/MW/年）",
        "场站级事件频次\n（次/场站/年）",
        "容量加权条件损失\n（MWh/(MW·h)）",
        "场站级条件损失\n（MWh/(场站·h)）",
    ]
    for row, ylabel in enumerate(ylabels):
        axes[row, 0].set_ylabel(ylabel)
    for index, ax in enumerate(axes.flat):
        panel_tag(ax, chr(ord("a") + index), dx=-0.12, dy=1.06)

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
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.963))
    fig.suptitle(
        f"全球极端事件频次与事件条件损失强度（{args.model}）",
        fontsize=11,
        fontweight="bold",
        y=0.995,
    )
    windows = "、".join(f"{DECADE_LABEL[d]}:{DECADE_WINDOWS[d]}" for d in DECADE_ORDER)
    note = (
        "episode 为各技术支持事件并集的 False→True 起点；条件损失分母分别为容量-事件小时与场站-事件小时；"
        f"窗口：{windows}。"
    )
    if args.error_bar:
        note += "误差条为窗口内年度最小-最大值。"
    fig.text(0.5, 0.025, note, ha="center", fontsize=6.2, color="0.4")

    out_path = out_dir / f"{OUT_STEM}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> None:
    args = parse_args()
    if args.station_chunksize <= 0:
        raise SystemExit("分块大小必须大于 0。")
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    csv_dir = out_dir / "csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    signal_root = resolve_signal_input_root(args)
    station_csv = args.station_input_csv or Path(
        str(DEFAULT_STATION_INPUT_CSV).format(model=args.model)
    )
    if not station_csv.exists():
        raise SystemExit(f"未找到 station 级损失 CSV：{station_csv}")

    summary = build_summary(
        args,
        signal_root=signal_root,
        station_csv=station_csv,
        csv_dir=csv_dir,
    )
    csv_path = csv_dir / CSV_NAME
    summary.to_csv(csv_path, index=False)
    figure_path = plot_summary(summary, args, out_dir)
    print(f"已保存：{figure_path}")
    print(f"已保存汇总表：{csv_path}")


if __name__ == "__main__":
    main()
