#!/usr/bin/env python3
"""经度带单位装机损失分析的数据入口与绘图工具。"""

from __future__ import annotations

from pathlib import Path
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STATION_CSV = ROOT / "data/generation_loss_outputs/generation_loss/{model}/aggregate/generation_loss_decade_station.csv"
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "outputs"
DEFAULT_MODEL = "CANESM5"
COMPARE_SSPS = ("ssp126", "ssp245", "ssp585")
TECHS = ("wind", "solar")
SNAPSHOTS = (2030, 2040, 2050)
METRIC_KEY = "unit_capacity_loss"
YEARS_PER_SNAPSHOT = 10.0
# 经度带分界：lon 转入 [0,360) 后每 60° 一带，自 0°E 起自西向东排列。
BAND_WIDTH = 60.0
# 自西向东排列，用于输出与图表排序。
LON_BANDS = ("000-060E", "060-120E", "120-180E", "180-120W", "120-060W", "060-000W")
BAND_LABEL = {
    "000-060E": "0–60°E", "060-120E": "60–120°E", "120-180E": "120–180°E",
    "180-120W": "120°W–180°", "120-060W": "60–120°W", "060-000W": "0–60°W",
}
# 色环顺序：自西向东渐进。
BAND_COLOR = {
    "000-060E": "#08306b", "060-120E": "#2171b5", "120-180E": "#6baed6",
    "180-120W": "#fdbb84", "120-060W": "#e34a33", "060-000W": "#a50f15",
}
BAND_MARKER = {
    "000-060E": "o", "060-120E": "s", "120-180E": "^",
    "180-120W": "v", "120-060W": "D", "060-000W": "P",
}
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp245": "#b77c19", "ssp585": "#9e1b1b"}
TECH_LABEL = {"wind": "Wind", "solar": "Solar"}
EVENT_LABEL = {
    "low_resource": "Low resource", "high_temp": "High temperature",
    "high_wind": "High wind", "hot_humid": "Hot-humid", "icing": "Icing",
    "rainstorm": "Rainstorm", "cold_highwind": "Cold-high wind",
    "freezing_rain": "Freezing rain", "high_humidity": "High humidity",
}
EVENT_COLOR = dict(zip(EVENT_LABEL, [
    "#3b6fb6", "#d95f02", "#b2182b", "#e78ac3", "#67a9cf",
    "#1b9e77", "#7570b3", "#80cdc1", "#66a61e",
]))
STATION_USE_COLUMNS = [
    "model", "scenario", "source", "region", "tech", "snapshot_year",
    "analysis_scheme", "analysis_k", "station_id", "lon", "capacity_mw",
    "event", "net_generation_loss_mwh", "normal_all_generation_mwh",
]
# 进一步分析（further_analysis.py）额外需要的列。
FURTHER_USE_COLUMNS = STATION_USE_COLUMNS + ["event_duration_hours"]

def load_source_full(station_csv: Path, model: str) -> pd.DataFrame:
    """与 load_source 相同的过滤与修正，但读取含 event_duration_hours 的扩展列。"""
    raw = pd.read_csv(station_csv, usecols=FURTHER_USE_COLUMNS)
    data = raw[
        raw["model"].eq(model) & raw["scenario"].isin(COMPARE_SSPS)
        & raw["tech"].isin(TECHS) & raw["snapshot_year"].isin(SNAPSHOTS)
        & raw["analysis_scheme"].eq("center-k") & raw["analysis_k"].eq(5)
    ].copy()
    if data.empty:
        raise ValueError("没有匹配模式和分析窗口的数据")
    if "source" in data and data["source"].nunique() != 1:
        raise ValueError("输入包含多个数据源，不能混合聚合")
    wind = data["tech"].eq("wind")
    for col in ("net_generation_loss_mwh", "normal_all_generation_mwh"):
        data.loc[wind, col] *= 0.1
    return add_lon_band(data)

def configure_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"],
        "font.size": 7, "axes.titlesize": 8, "axes.spines.top": False,
        "axes.spines.right": False, "legend.frameon": False,
        "legend.fontsize": 6, "savefig.dpi": 350,
    })

def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.png"
    fig.savefig(path, dpi=350, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path

def resolve_path(template: Path, model: str) -> Path:
    return Path(str(template).format(model=model))

def assign_lon_band(lon: float) -> str:
    """经度先取模到 [0,360)，再按 60° 分带；返回自西向东的带名（如 060-000W）。"""
    sector = int((lon % 360) // BAND_WIDTH) % len(LON_BANDS)
    return LON_BANDS[sector]

def add_lon_band(data: pd.DataFrame) -> pd.DataFrame:
    data["lon_band"] = data["lon"].map(assign_lon_band)
    return data

def load_source(station_csv: Path, model: str) -> pd.DataFrame:
    raw = pd.read_csv(station_csv, usecols=STATION_USE_COLUMNS)
    data = raw[
        raw["model"].eq(model) & raw["scenario"].isin(COMPARE_SSPS)
        & raw["tech"].isin(TECHS) & raw["snapshot_year"].isin(SNAPSHOTS)
        & raw["analysis_scheme"].eq("center-k") & raw["analysis_k"].eq(5)
    ].copy()
    if data.empty:
        raise ValueError("没有匹配模式和分析窗口的数据")
    if "source" in data and data["source"].nunique() != 1:
        raise ValueError("输入包含多个数据源，不能混合聚合")
    keys = ["station_id", "scenario", "tech", "snapshot_year", "event"]
    if data.duplicated(keys).any():
        raise ValueError("场站十年输入存在重复键，请先统一数据源和基准口径")
    # 上游风电能量暂被放大10倍；修复上游后移除此缩放并重跑。
    wind = data["tech"].eq("wind")
    for col in ("net_generation_loss_mwh", "normal_all_generation_mwh"):
        data.loc[wind, col] *= 0.1
    return add_lon_band(data)

def aggregate_band_rates(data: pd.DataFrame) -> pd.DataFrame:
    """按经度带汇总十年损失，并换算为单位装机年损失。"""
    selected = data[data["event"].eq("all")]
    grouped = selected.groupby(
        ["lon_band", "scenario", "tech", "snapshot_year"], as_index=False
    ).agg(
        n_stations=("station_id", "nunique"),
        capacity_mw=("capacity_mw", "sum"),
        net_loss_mwh=("net_generation_loss_mwh", "sum"),
        normal_all_mwh=("normal_all_generation_mwh", "sum"),
    )
    valid = (
        np.isfinite(grouped["net_loss_mwh"])
        & np.isfinite(grouped["capacity_mw"])
        & grouped["capacity_mw"].gt(0)
    )
    grouped["unit_capacity_loss"] = np.where(
        valid,
        grouped["net_loss_mwh"] / grouped["capacity_mw"] / YEARS_PER_SNAPSHOT,
        np.nan,
    )
    grouped["lon_band"] = pd.Categorical(grouped["lon_band"], categories=LON_BANDS, ordered=True)
    grouped = grouped.sort_values(
        ["tech", "lon_band", "scenario", "snapshot_year"]
    ).reset_index(drop=True)
    grouped["lon_band"] = grouped["lon_band"].astype(str)
    return grouped

def band_event_losses(data: pd.DataFrame) -> pd.DataFrame:
    """按（经度带，情景，技术，快照，事件）汇总十年净损失并计算损失加权占比。"""
    selected = data[data["event"].ne("all")]
    summary = selected.groupby(
        ["lon_band", "scenario", "tech", "snapshot_year", "event"], as_index=False
    ).agg(
        net_loss_mwh_decade=("net_generation_loss_mwh", "sum"),
        n_stations=("station_id", "nunique"),
    )
    summary["positive_net_loss_mwh_decade"] = summary["net_loss_mwh_decade"].clip(lower=0)
    total = summary.groupby(["lon_band", "scenario", "tech", "snapshot_year"])[
        "positive_net_loss_mwh_decade"
    ].transform("sum")
    summary["loss_weighted_share"] = np.where(
        total > 0, summary["positive_net_loss_mwh_decade"] / total, np.nan
    )
    residual = summary[summary["event"].ne("low_resource")].groupby(
        ["lon_band", "scenario", "tech", "snapshot_year"]
    )["positive_net_loss_mwh_decade"].transform("sum")
    summary["loss_weighted_residual_share"] = np.nan
    mask = summary["event"].ne("low_resource")
    summary.loc[mask, "loss_weighted_residual_share"] = np.where(
        residual > 0,
        summary.loc[mask, "positive_net_loss_mwh_decade"] / residual,
        np.nan,
    )
    summary["lon_band"] = pd.Categorical(summary["lon_band"], categories=LON_BANDS, ordered=True)
    summary = summary.sort_values(
        ["tech", "lon_band", "scenario", "snapshot_year", "event"]
    ).reset_index(drop=True)
    summary["lon_band"] = summary["lon_band"].astype(str)
    return summary

def band_coverage_table(metrics: pd.DataFrame) -> pd.DataFrame:
    """展开全部经度带×情景×快照组合；无场站的组合记为 0。"""
    rows = []
    for tech in TECHS:
        for band in LON_BANDS:
            for scenario in COMPARE_SSPS:
                for year in SNAPSHOTS:
                    match = metrics[
                        metrics["tech"].eq(tech) & metrics["lon_band"].eq(band)
                        & metrics["scenario"].eq(scenario) & metrics["snapshot_year"].eq(year)
                    ]
                    row = match.iloc[0] if len(match) else None
                    rows.append(dict(
                        tech=tech, lon_band=band, scenario=scenario, snapshot_year=year,
                        n_stations=0 if row is None else int(row["n_stations"]),
                        capacity_mw=0.0 if row is None else float(row["capacity_mw"]),
                        unit_capacity_loss=np.nan if row is None else float(row["unit_capacity_loss"]),
                        present=row is not None,
                    ))
    return pd.DataFrame(rows)
