#!/usr/bin/env python3
"""三情景单位装机损失轨迹的数据入口和 PNG 绘图工具。"""

from __future__ import annotations

from dataclasses import dataclass
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
DEFAULT_REGION_CSV = ROOT / "data/generation_loss_outputs/generation_loss/{model}/aggregate/generation_loss_region.csv"
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "outputs"
DEFAULT_MODEL = "CANESM5"
COMPARE_SSPS = ("ssp126", "ssp245", "ssp585")
TECHS = ("wind", "solar")
SNAPSHOTS = (2030, 2040, 2050)
FEATURE_NAMES = [f"{s}_{y}" for s in COMPARE_SSPS for y in SNAPSHOTS]
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp245": "#b77c19", "ssp585": "#9e1b1b"}
TECH_LABEL = {"wind": "Wind", "solar": "Solar"}
SNAPSHOT_LABEL = {y: f"{y}s" for y in SNAPSHOTS}
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
CLUSTER_COLORS = ("#1d3b6f", "#b64342", "#42949e", "#9a4d8e", "#d08b32")
@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str

METRICS = (MetricSpec("unit_capacity_loss", "unit capacity loss", "MWh MW$^{-1}$ yr$^{-1}$"),)
METRIC_BY_KEY = {m.key: m for m in METRICS}
YEARS_PER_SNAPSHOT = 10.0

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

def load_source(region_csv: Path, model: str) -> pd.DataFrame:
    raw = pd.read_csv(region_csv)
    data = raw[
        raw["model"].eq(model) & raw["scenario"].isin(COMPARE_SSPS)
        & raw["tech"].isin(TECHS) & raw["snapshot_year"].isin(SNAPSHOTS)
        & raw["analysis_scheme"].eq("center-k") & raw["analysis_k"].eq(5)
    ].copy()
    if data.empty:
        raise ValueError("没有匹配模式和分析窗口的数据")
    if "source" in data and data["source"].nunique() != 1:
        raise ValueError("输入包含多个数据源，不能混合聚合")
    keys = ["region", "scenario", "tech", "snapshot_year", "analysis_year", "event"]
    if data.duplicated(keys).any():
        raise ValueError("国家年度输入存在重复键，请先统一数据源和基准口径")
    # 上游风电能量暂被放大10倍；修复上游后移除此缩放并重跑。
    wind = data["tech"].eq("wind")
    for col in ("net_generation_loss_mwh", "normal_all_generation_mwh"):
        data.loc[wind, col] *= 0.1
    return data

def aggregate_rates(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    annual = data[data["event"].eq("all")].copy()
    annual = annual.rename(columns={
        "net_generation_loss_mwh": "net_loss_mwh",
        "normal_all_generation_mwh": "normal_all_mwh",
    })
    valid = (
        np.isfinite(annual["net_loss_mwh"])
        & np.isfinite(annual["capacity_mw"])
        & annual["capacity_mw"].gt(0)
    )
    annual["unit_capacity_loss"] = np.where(
        valid,
        annual["net_loss_mwh"] / annual["capacity_mw"],
        np.nan,
    )
    rows = []
    for keys, group in annual.groupby(["region", "scenario", "tech", "snapshot_year"]):
        region, scenario, tech, snapshot = keys
        reasons = []
        if set(group["analysis_year"]) != set(range(snapshot, snapshot + 10)):
            reasons.append("incomplete_years")
        if not np.isfinite(group[["net_loss_mwh", "capacity_mw"]].to_numpy()).all():
            reasons.append("nonfinite_loss_or_capacity")
        if not group["capacity_mw"].gt(0).all():
            reasons.append("nonpositive_capacity")
        loss = group["net_loss_mwh"].sum()
        capacity_values = group["capacity_mw"].dropna().unique()
        if len(capacity_values) != 1:
            reasons.append("inconsistent_capacity")
        capacity = float(group["capacity_mw"].mean())
        rows.append(dict(
            region=region, scenario=scenario, tech=tech, snapshot_year=snapshot,
            metric="unit_capacity_loss",
            value=loss / capacity / YEARS_PER_SNAPSHOT if not reasons else np.nan,
            n_years=group["analysis_year"].nunique(), net_loss_mwh=loss,
            capacity_mw=capacity,
            normal_all_mwh=group["normal_all_mwh"].sum(),
            reason=";".join(reasons) or "valid",
        ))
    return pd.DataFrame(rows), annual

def load_country_event_losses(data: pd.DataFrame) -> pd.DataFrame:
    selected = data[data["event"].ne("all")]
    keys = ["region", "scenario", "tech", "snapshot_year", "event"]
    result = selected.groupby(keys, as_index=False).agg(
        net_loss_mwh_per_year=("net_generation_loss_mwh", "mean"),
        n_years=("analysis_year", "nunique"),
    )
    if result["n_years"].ne(10).any() or not np.isfinite(result["net_loss_mwh_per_year"]).all():
        raise ValueError("事件数据存在不完整窗口或非有限损失")
    result["positive_net_loss_mwh_per_year"] = result["net_loss_mwh_per_year"].clip(lower=0)
    return result

def coverage_table(metrics: pd.DataFrame, regions: list[str]) -> pd.DataFrame:
    rows = []
    for tech in TECHS:
        for region in regions:
            for scenario in COMPARE_SSPS:
                for year in SNAPSHOTS:
                    match = metrics[
                        metrics["tech"].eq(tech) & metrics["region"].eq(region)
                        & metrics["scenario"].eq(scenario) & metrics["snapshot_year"].eq(year)
                    ]
                    reason = "missing_record" if match.empty else str(match.iloc[0]["reason"])
                    rows.append(dict(tech=tech, region=region, scenario=scenario,
                                     snapshot_year=year, reason=reason, valid=(reason == "valid")))
    return pd.DataFrame(rows)
