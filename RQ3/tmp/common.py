#!/usr/bin/env python3
"""RQ3 临时机制分析图的共享配置与数据工具。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"
REGION_CSV = (
    ROOT
    / "ref_code/calculate_wind_solar_generation_loss/outputs/generation_loss"
    / "{model}/aggregate/generation_loss_region.csv"
)
DECADE_STATION_CSV = (
    ROOT
    / "ref_code/calculate_wind_solar_generation_loss/outputs/generation_loss"
    / "{model}/aggregate/generation_loss_decade_station.csv"
)
RQ2_EXPOSURE_CSV = ROOT / "RQ2/outputs/{model}/csv/RQ2_extreme_exposure_rate_capacity_weighted.csv"

SSPS = ["ssp126", "ssp245", "ssp585"]
TECHS = ["wind", "solar"]
SNAPSHOTS = [2030, 2040, 2050]
# 临时修正：上游风电发电量及其损失被错误放大 10 倍；上游数据修复后应删除此常量、字段列表和缩放函数。
TEMP_WIND_ENERGY_SCALE_FACTOR = 0.1
TEMP_WIND_ENERGY_COLUMNS = (
    "generation_loss_mwh",
    "net_generation_loss_mwh",
    "normal_generation_mwh",
    "normal_all_generation_mwh",
    "actual_generation_mwh",
    "generation_fluctuation_mwh",
)
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
DECADE_LABEL = {2030: "2030s", 2040: "2040s", 2050: "2050s"}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
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
    "all": "全部事件并集",
}
EVENT_COLOR = {
    "all": "#222222",
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


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--model", default="CANESM5", help="CMIP6 模式名称。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。")
    return parser


def output_dir(model: str, custom: Path | None = None) -> Path:
    path = custom or (ROOT / "RQ3/outputs/tmp" / model)
    path.mkdir(parents=True, exist_ok=True)
    (path / "csv").mkdir(parents=True, exist_ok=True)
    return path


def configure_style() -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    from matplotlib import font_manager as fm

    sans = ["Arial", "DejaVu Sans"]
    if FONT_PATH.exists():
        fm.fontManager.addfont(str(FONT_PATH))
        sans.insert(0, fm.FontProperties(fname=str(FONT_PATH)).get_name())
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans,
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 7.5,
            "axes.titlesize": 8.5,
            "axes.labelsize": 8,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "legend.fontsize": 6.5,
            "figure.dpi": 120,
            "savefig.dpi": 350,
        }
    )


def load_region(model: str) -> pd.DataFrame:
    path = Path(str(REGION_CSV).format(model=model))
    if not path.exists():
        raise SystemExit(f"未找到 RQ3 region 汇总：{path}")
    data = pd.read_csv(path)
    data = data[(data["model"] == model) & data["scenario"].isin(SSPS)].copy()
    apply_temp_wind_energy_correction(data, context="region 汇总")
    return data


def apply_temp_wind_energy_correction(
    data: pd.DataFrame,
    *,
    context: str,
    emit_log: bool = True,
) -> int:
    """临时将风电发电量和损失能量项乘以 0.1；返回受影响的风电行数。"""
    if "tech" not in data.columns:
        raise KeyError("临时风电修正要求输入数据包含 tech 列。")
    columns = [column for column in TEMP_WIND_ENERGY_COLUMNS if column in data.columns]
    if not columns:
        raise KeyError(f"临时风电修正未找到能量字段：{TEMP_WIND_ENERGY_COLUMNS}")
    wind_mask = data["tech"] == "wind"
    data.loc[wind_mask, columns] *= TEMP_WIND_ENERGY_SCALE_FACTOR
    affected = int(wind_mask.sum())
    if emit_log:
        print(
            f"[临时修正] {context}：已将风电 {', '.join(columns)} × "
            f"{TEMP_WIND_ENERGY_SCALE_FACTOR:g}（影响 {affected} 行）；"
            "上游数据修复后请移除此修正。"
        )
    return affected


def global_annual(region: pd.DataFrame) -> pd.DataFrame:
    keys = ["scenario", "tech", "snapshot_year", "analysis_year", "event"]
    return (
        region.groupby(keys, as_index=False)
        .agg(
            net_loss_mwh=("net_generation_loss_mwh", "sum"),
            gross_loss_mwh=("generation_loss_mwh", "sum"),
            normal_event_mwh=("normal_generation_mwh", "sum"),
            normal_all_mwh=("normal_all_generation_mwh", "sum"),
            capacity_mw=("capacity_mw", "sum"),
            n_regions=("region", "nunique"),
        )
    )


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> Path:
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    fig.savefig(png, dpi=350, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"已保存：{png}")
    print(f"已保存：{pdf}")
    return png


def panel_tag(ax: plt.Axes, tag: str) -> None:
    ax.text(-0.095, 1.035, tag, transform=ax.transAxes, fontsize=10, fontweight="bold", va="top")


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values = values[mask]
    weights = weights[mask]
    if not len(values):
        return np.nan
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cdf = (np.cumsum(weights) - 0.5 * weights) / weights.sum()
    return float(np.interp(q, cdf, values))


def write_source(data: pd.DataFrame, out_dir: Path, name: str) -> Path:
    path = out_dir / "csv" / name
    data.to_csv(path, index=False)
    print(f"已保存 source-data：{path}")
    return path
