#!/usr/bin/env python3
"""RQ4 国家损失曲线聚类的共享数据与绘图工具。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# common.py 位于 RQ4/ssp126_ssp585_loss_gap_clustering/，项目根目录需要上溯两级。
ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"
DEFAULT_REGION_CSV = (
    ROOT
    / "data/generation_loss_outputs/generation_loss"
    / "{model}/aggregate/generation_loss_region.csv"
)
DEFAULT_STATION_SUMMARY_CSV = (
    ROOT / "RQ3/outputs/tmp/{model}/csv/source_station_decade_all.csv"
)
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "outputs"

DEFAULT_MODEL = "CANESM5"
COMPARE_SSPS = ("ssp126", "ssp585")
TECHS = ("wind", "solar")
SNAPSHOTS = (2030, 2040, 2050)
ANALYSIS_K = 5
EXPECTED_WINDOW_YEARS = 2 * ANALYSIS_K

SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp585": "SSP5-8.5"}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp585": "#9e1b1b"}
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
SNAPSHOT_LABEL = {year: f"{year}s" for year in SNAPSHOTS}

EVENT_LABEL = {
    "low_resource": "低资源",
    "high_temp": "高温",
    "high_wind": "大风",
    "hot_humid": "高温高湿",
    "icing": "覆冰",
    "rainstorm": "暴雨",
    "cold_highwind": "低温大风",
    "freezing_rain": "冻雨",
    "high_humidity": "高湿",
}
EVENT_COLOR = {
    "low_resource": "#3b6fb6",
    "high_temp": "#d95f02",
    "high_wind": "#b2182b",
    "hot_humid": "#e78ac3",
    "icing": "#67a9cf",
    "rainstorm": "#1b9e77",
    "cold_highwind": "#7570b3",
    "freezing_rain": "#80cdc1",
    "high_humidity": "#66a61e",
}
CLUSTER_COLORS = (
    "#1d3b6f",
    "#b64342",
    "#42949e",
    "#9a4d8e",
    "#d08b32",
    "#5f7f4f",
)


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str


METRICS = (
    MetricSpec("absolute_loss", "绝对损失", "TWh/年"),
    MetricSpec("relative_loss_rate", "相对损失率", "%"),
    MetricSpec("loss_per_capacity", "单位装机损失", "MWh/(MW·年)"),
    MetricSpec("loss_per_station", "单位场站损失", "MWh/(场站·年)"),
)
METRIC_BY_KEY = {metric.key: metric for metric in METRICS}


def configure_style() -> None:
    """配置紧凑的 PNG 出图风格。"""
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    from matplotlib import font_manager as fm

    sans = ["Arial", "DejaVu Sans", "Liberation Sans"]
    if FONT_PATH.exists():
        fm.fontManager.addfont(str(FONT_PATH))
        sans.insert(0, fm.FontProperties(fname=str(FONT_PATH)).get_name())
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans,
            "axes.unicode_minus": False,
            "font.size": 7,
            "axes.titlesize": 8,
            "axes.labelsize": 7.5,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "legend.fontsize": 6.5,
            "figure.dpi": 120,
            "savefig.dpi": 350,
        }
    )


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> Path:
    """保存审阅用 PNG 图。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.png"
    fig.savefig(path, dpi=350, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def apply_temp_wind_energy_correction(data: pd.DataFrame) -> int:
    """临时将上游错误放大十倍的风电能量字段乘以 0.1。"""
    columns = [
        column
        for column in (
            "generation_loss_mwh",
            "net_generation_loss_mwh",
            "normal_generation_mwh",
            "normal_all_generation_mwh",
            "actual_generation_mwh",
        )
        if column in data.columns
    ]
    wind = data["tech"].eq("wind")
    data.loc[wind, columns] *= 0.1
    return int(wind.sum())


def resolve_path(template: Path, model: str) -> Path:
    return Path(str(template).format(model=model))


def load_country_metrics(
    *,
    model: str,
    region_csv: Path,
    station_summary_csv: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回国家年代指标长表和完整的逐年国家总账。"""
    required_region = {
        "model",
        "scenario",
        "region",
        "tech",
        "snapshot_year",
        "analysis_scheme",
        "analysis_k",
        "analysis_year",
        "event",
        "capacity_mw",
        "net_generation_loss_mwh",
        "normal_all_generation_mwh",
    }
    raw = pd.read_csv(region_csv)
    missing = sorted(required_region.difference(raw.columns))
    if missing:
        raise KeyError(f"国家年度输入缺少字段：{', '.join(missing)}")
    data = raw[
        raw["model"].eq(model)
        & raw["scenario"].isin(COMPARE_SSPS)
        & raw["tech"].isin(TECHS)
        & raw["snapshot_year"].isin(SNAPSHOTS)
        & raw["analysis_scheme"].eq("center-k")
        & raw["analysis_k"].eq(ANALYSIS_K)
        & raw["event"].eq("all")
    ].copy()
    if data.empty:
        raise ValueError("国家年度输入中没有匹配 RQ4 口径的数据。")
    corrected_rows = apply_temp_wind_energy_correction(data)
    print(f"[临时修正] RQ4 国家指标：风电能量字段 × 0.1（影响 {corrected_rows} 行）。")

    annual = (
        data.groupby(
            ["region", "scenario", "tech", "snapshot_year", "analysis_year"],
            as_index=False,
        )
        .agg(
            net_loss_mwh=("net_generation_loss_mwh", "sum"),
            normal_all_mwh=("normal_all_generation_mwh", "sum"),
            capacity_mw=("capacity_mw", "sum"),
        )
    )

    station = pd.read_csv(
        station_summary_csv,
        usecols=["scenario", "region", "tech", "snapshot_year", "station_id"],
    )
    station = station[
        station["scenario"].isin(COMPARE_SSPS)
        & station["tech"].isin(TECHS)
        & station["snapshot_year"].isin(SNAPSHOTS)
    ]
    station_count = (
        station.groupby(
            ["region", "scenario", "tech", "snapshot_year"], as_index=False
        )
        .agg(station_count=("station_id", "nunique"))
    )
    annual = annual.merge(
        station_count,
        on=["region", "scenario", "tech", "snapshot_year"],
        how="left",
        validate="many_to_one",
    )
    if annual["station_count"].isna().any():
        bad = annual.loc[annual["station_count"].isna(), ["region", "scenario", "tech", "snapshot_year"]]
        raise ValueError(f"以下国家年代缺少场站数量：\n{bad.drop_duplicates().to_string(index=False)}")

    annual["absolute_loss"] = annual["net_loss_mwh"] / 1e6
    annual["relative_loss_rate"] = np.where(
        annual["normal_all_mwh"] > 0,
        annual["net_loss_mwh"] / annual["normal_all_mwh"] * 100.0,
        np.nan,
    )
    annual["loss_per_capacity"] = np.where(
        annual["capacity_mw"] > 0,
        annual["net_loss_mwh"] / annual["capacity_mw"],
        np.nan,
    )
    annual["loss_per_station"] = np.where(
        annual["station_count"] > 0,
        annual["net_loss_mwh"] / annual["station_count"],
        np.nan,
    )

    keys = ["region", "scenario", "tech", "snapshot_year"]
    year_counts = annual.groupby(keys)["analysis_year"].nunique()
    incomplete = year_counts[year_counts != EXPECTED_WINDOW_YEARS]
    if not incomplete.empty:
        raise ValueError(
            f"发现 {len(incomplete)} 个国家—情景—技术—年代窗口不是 "
            f"{EXPECTED_WINDOW_YEARS} 年。"
        )

    metrics = annual.melt(
        id_vars=keys,
        value_vars=[metric.key for metric in METRICS],
        var_name="metric",
        value_name="value",
    )
    metrics = (
        metrics.groupby(keys + ["metric"], as_index=False)
        .agg(value=("value", "mean"), n_years=("value", "count"))
    )
    return metrics, annual


def load_country_event_losses(*, model: str, region_csv: Path) -> pd.DataFrame:
    """读取国家—事件年代年均净损失；保留负值并另给正损失用于构成分析。"""
    raw = pd.read_csv(region_csv)
    data = raw[
        raw["model"].eq(model)
        & raw["scenario"].isin(COMPARE_SSPS)
        & raw["tech"].isin(TECHS)
        & raw["snapshot_year"].isin(SNAPSHOTS)
        & raw["analysis_scheme"].eq("center-k")
        & raw["analysis_k"].eq(ANALYSIS_K)
        & raw["event"].ne("all")
    ].copy()
    if data.empty:
        raise ValueError("国家年度输入中没有事件分解数据。")
    apply_temp_wind_energy_correction(data)
    annual = (
        data.groupby(
            ["region", "scenario", "tech", "snapshot_year", "analysis_year", "event"],
            as_index=False,
        )
        .agg(net_loss_mwh=("net_generation_loss_mwh", "sum"))
    )
    decade = (
        annual.groupby(
            ["region", "scenario", "tech", "snapshot_year", "event"],
            as_index=False,
        )
        .agg(net_loss_mwh_per_year=("net_loss_mwh", "mean"), n_years=("analysis_year", "nunique"))
    )
    decade["positive_net_loss_mwh_per_year"] = decade["net_loss_mwh_per_year"].clip(lower=0.0)
    return decade
