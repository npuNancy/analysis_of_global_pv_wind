#!/usr/bin/env python3
"""Trade-off 候选图的共享数据、样式与输出工具。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
RQ3_DIR = ROOT / "RQ3"
if str(RQ3_DIR) not in sys.path:
    sys.path.insert(0, str(RQ3_DIR))

from plot_RQ3_generation_loss_global_evolution import (  # noqa: E402
    SSP_C,
    SSP_L,
    apply_temp_wind_energy_correction,
    configure_style,
)


DEFAULT_MODEL = Path(__file__).resolve().parent.name
REGION_CSV = (
    ROOT
    / "ref_code/calculate_wind_solar_generation_loss/outputs/generation_loss"
    / "{model}/aggregate/generation_loss_region.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "RQ3/outputs/tmp"

SCENARIOS = ["ssp126", "ssp245", "ssp585"]
SNAPSHOTS = [2030, 2040, 2050]
DECADE_LABEL = {2030: "2030s", 2040: "2040s", 2050: "2050s"}
DECADE_MARKER = {2030: "o", 2040: "s", 2050: "^"}


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--output-dir", type=Path, default=None, help="可选输出目录。")
    return parser


def get_output_dir(model: str, custom: Path | None = None) -> Path:
    path = custom or (DEFAULT_OUTPUT_DIR / model)
    path.mkdir(parents=True, exist_ok=True)
    (path / "csv").mkdir(parents=True, exist_ok=True)
    return path


def configure_trade_off_style() -> None:
    configure_style()
    mpl.rcParams.update(
        {
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8.5,
            "legend.fontsize": 7,
            "figure.dpi": 120,
            "savefig.dpi": 350,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def load_trade_off_annual(model: str) -> pd.DataFrame:
    """读取 region 年度表，统一应用风电 0.1 修正并构造系统 trade-off 指标。"""
    path = Path(str(REGION_CSV).format(model=model))
    if not path.exists():
        raise SystemExit(f"未找到 RQ3 region 汇总：{path}")
    data = pd.read_csv(path)
    data = data[
        data["model"].eq(model)
        & data["scenario"].isin(SCENARIOS)
        & data["tech"].isin(["wind", "solar"])
        & data["event"].eq("all")
    ].copy()
    if data.empty:
        raise SystemExit(f"输入数据中没有 model={model}、event=all 的风光记录。")

    # 临时修正：所有 trade-off 图与 RQ3 主图使用同一风电能量字段 ×0.1 口径。
    apply_temp_wind_energy_correction(data, context="trade-off 候选图")

    by_tech = (
        data.groupby(
            ["scenario", "snapshot_year", "analysis_year", "tech"],
            as_index=False,
        )
        .agg(
            loss_mwh=("net_generation_loss_mwh", "sum"),
            normal_mwh=("normal_all_generation_mwh", "sum"),
            capacity_mw=("capacity_mw", "sum"),
            n_regions=("region", "nunique"),
        )
    )
    by_tech["loss_rate_pct"] = by_tech["loss_mwh"] / by_tech["normal_mwh"] * 100.0

    wide = by_tech.pivot(
        index=["scenario", "snapshot_year", "analysis_year"],
        columns="tech",
        values=["loss_mwh", "normal_mwh", "capacity_mw", "loss_rate_pct", "n_regions"],
    ).reset_index()
    wide.columns = ["_".join(part for part in column if part).rstrip("_") for column in wide.columns]
    required = [
        "loss_mwh_wind", "loss_mwh_solar", "normal_mwh_wind", "normal_mwh_solar",
        "capacity_mw_wind", "capacity_mw_solar", "loss_rate_pct_wind", "loss_rate_pct_solar",
    ]
    wide = wide.dropna(subset=required).copy()

    wide["total_loss_twh"] = (wide["loss_mwh_wind"] + wide["loss_mwh_solar"]) / 1e6
    wide["normal_generation_twh"] = (
        wide["normal_mwh_wind"] + wide["normal_mwh_solar"]
    ) / 1e6
    wide["total_capacity_gw"] = (
        wide["capacity_mw_wind"] + wide["capacity_mw_solar"]
    ) / 1e3
    wide["observed_rate_pct"] = (
        (wide["loss_mwh_wind"] + wide["loss_mwh_solar"])
        / (wide["normal_mwh_wind"] + wide["normal_mwh_solar"])
        * 100.0
    )
    wide["wind_generation_share"] = (
        wide["normal_mwh_wind"]
        / (wide["normal_mwh_wind"] + wide["normal_mwh_solar"])
    )

    common_weight = (
        wide.groupby(["snapshot_year", "analysis_year"], as_index=False)
        .agg(common_wind_generation_share=("wind_generation_share", "mean"))
    )
    wide = wide.merge(
        common_weight,
        on=["snapshot_year", "analysis_year"],
        how="left",
        validate="many_to_one",
    )
    wide["fixed_tech_mix_rate_pct"] = (
        wide["common_wind_generation_share"] * wide["loss_rate_pct_wind"]
        + (1.0 - wide["common_wind_generation_share"]) * wide["loss_rate_pct_solar"]
    )
    return wide.sort_values(["scenario", "snapshot_year", "analysis_year"]).reset_index(drop=True)


def build_trade_off_decade(annual: pd.DataFrame) -> pd.DataFrame:
    """把五个分析年度聚合为年代均值和年际最小—最大值。"""
    decade = (
        annual.groupby(["scenario", "snapshot_year"], as_index=False)
        .agg(
            total_loss_twh_mean=("total_loss_twh", "mean"),
            total_loss_twh_min=("total_loss_twh", "min"),
            total_loss_twh_max=("total_loss_twh", "max"),
            observed_rate_pct_mean=("observed_rate_pct", "mean"),
            observed_rate_pct_min=("observed_rate_pct", "min"),
            observed_rate_pct_max=("observed_rate_pct", "max"),
            fixed_tech_mix_rate_pct_mean=("fixed_tech_mix_rate_pct", "mean"),
            fixed_tech_mix_rate_pct_min=("fixed_tech_mix_rate_pct", "min"),
            fixed_tech_mix_rate_pct_max=("fixed_tech_mix_rate_pct", "max"),
            wind_generation_share_mean=("wind_generation_share", "mean"),
            common_wind_generation_share_mean=("common_wind_generation_share", "mean"),
            normal_generation_twh_mean=("normal_generation_twh", "mean"),
            total_capacity_gw_mean=("total_capacity_gw", "mean"),
            wind_rate_pct_mean=("loss_rate_pct_wind", "mean"),
            solar_rate_pct_mean=("loss_rate_pct_solar", "mean"),
            n_years=("analysis_year", "nunique"),
        )
    )
    decade["decade"] = decade["snapshot_year"].map(DECADE_LABEL)
    return decade.sort_values(["scenario", "snapshot_year"]).reset_index(drop=True)


def panel_tag(ax: plt.Axes, tag: str) -> None:
    ax.text(-0.10, 1.04, tag, transform=ax.transAxes, fontsize=10, fontweight="bold", va="top")


def write_source(data: pd.DataFrame, out_dir: Path, filename: str) -> Path:
    path = out_dir / "csv" / filename
    data.to_csv(path, index=False)
    print(f"已保存 source-data：{path}")
    return path


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> tuple[Path, Path]:
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    fig.savefig(png, dpi=350, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"已保存：{png}")
    print(f"已保存：{pdf}")
    return png, pdf


def asymmetric_error(mean: float, low: float, high: float) -> np.ndarray:
    return np.asarray([[mean - low], [high - mean]], dtype=float)

