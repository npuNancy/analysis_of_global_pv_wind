#!/usr/bin/env python3
"""基于经度带单位装机损失的进一步分析。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from common import (
    BAND_COLOR,
    BAND_LABEL,
    LON_BANDS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STATION_CSV,
    EVENT_LABEL,
    COMPARE_SSPS,
    SNAPSHOTS,
    SSP_COLOR,
    SSP_LABEL,
    TECH_LABEL,
    TECHS,
    band_event_losses,
    configure_style,
    load_source,
    resolve_path,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--station-input-csv", type=Path, default=None, help="场站十年损失长表。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。")
    return parser.parse_args()


def load_full(station_csv: Path, model: str) -> pd.DataFrame:
    """读取含 event_duration_hours 的扩展列，过滤与风电×0.1修正同 load_source。"""
    from common import load_source_full
    return load_source_full(station_csv, model)


def band_metrics(data: pd.DataFrame) -> pd.DataFrame:
    """与主脚本一致的带级单位装机损失。"""
    from common import aggregate_band_rates
    return aggregate_band_rates(data)


# ------------------------------------------------- 角度1：带间分异（极差与排序）

def band_disparity(metrics: pd.DataFrame) -> pd.DataFrame:
    """每（技术，情景，年代）内最高/最低带、单位装机损失极差及离散度。"""
    rows = []
    for keys, group in metrics.groupby(["tech", "scenario", "snapshot_year"]):
        valid = group[group["unit_capacity_loss"].notna()]
        if len(valid) < 2:
            continue
        top = valid.loc[valid["unit_capacity_loss"].idxmax()]
        bottom = valid.loc[valid["unit_capacity_loss"].idxmin()]
        mean = valid["unit_capacity_loss"].mean()
        rows.append(dict(
            tech=keys[0], scenario=keys[1], snapshot_year=keys[2],
            max_band=top["lon_band"], max_unit_capacity_loss=top["unit_capacity_loss"],
            min_band=bottom["lon_band"], min_unit_capacity_loss=bottom["unit_capacity_loss"],
            range_unit_capacity_loss=top["unit_capacity_loss"] - bottom["unit_capacity_loss"],
            cv_pct=valid["unit_capacity_loss"].std(ddof=1) / mean * 100,
            n_bands=len(valid),
        ))
    return pd.DataFrame(rows)


# --------------------------------------------------------- 角度2：SSP 敏感度

def ssp_sensitivity(metrics: pd.DataFrame) -> pd.DataFrame:
    """每带单位装机损失的情景跨度及其占 SSP1-2.6 水平的比例。"""
    pivot = metrics.pivot_table(
        index=["tech", "lon_band", "snapshot_year"], columns="scenario",
        values="unit_capacity_loss",
    )
    pivot["ssp585_minus_126_unit_capacity_loss"] = pivot["ssp585"] - pivot["ssp126"]
    pivot["ssp585_minus_245_unit_capacity_loss"] = pivot["ssp585"] - pivot["ssp245"]
    pivot["span_ratio_vs_126"] = pivot["ssp585_minus_126_unit_capacity_loss"] / pivot["ssp126"] * 100
    return pivot.reset_index()


# ------------------------------------------------------------- 角度3：时间趋势

def time_trend(metrics: pd.DataFrame) -> pd.DataFrame:
    """带内 2030s→2050s 单位装机损失变化，按情景。"""
    pivot = metrics.pivot_table(
        index=["tech", "lon_band", "scenario"], columns="snapshot_year",
        values="unit_capacity_loss",
    )
    pivot["change_2030s_to_2050s_unit_capacity_loss"] = pivot[2050] - pivot[2030]
    pivot["relative_change_pct"] = pivot["change_2030s_to_2050s_unit_capacity_loss"] / pivot[2030] * 100
    return pivot.reset_index()


# --------------------------------------------- 角度4：事件构成（带×事件占比）

def event_composition(events: pd.DataFrame) -> pd.DataFrame:
    """每带各事件损失加权占比（含剔除 low_resource 的残差口径），2050s 快照。"""
    return events[events["snapshot_year"].eq(2050)]


# ------------------------------------- 角度5：经度带对全球总损失的贡献占比

def global_contribution(metrics: pd.DataFrame) -> pd.DataFrame:
    """每带净损失占全部带总和的比例，以及装机和单位装机损失对照。"""
    total = metrics.groupby(["tech", "scenario", "snapshot_year"], as_index=False).agg(
        total_net_loss_mwh=("net_loss_mwh", "sum"),
        total_capacity_mw=("capacity_mw", "sum"),
        total_normal_all_mwh=("normal_all_mwh", "sum"),
    )
    merged = metrics.merge(total, on=["tech", "scenario", "snapshot_year"], how="left")
    merged["loss_share_pct"] = merged["net_loss_mwh"] / merged["total_net_loss_mwh"] * 100
    merged["capacity_share_pct"] = merged["capacity_mw"] / merged["total_capacity_mw"] * 100
    total["total_unit_capacity_loss"] = (
        total["total_net_loss_mwh"] / total["total_capacity_mw"] / 10.0
    )
    merged = merged.drop(columns=["total_unit_capacity_loss"], errors="ignore")
    merged = merged.merge(
        total[["tech", "scenario", "snapshot_year", "total_unit_capacity_loss"]],
        on=["tech", "scenario", "snapshot_year"], how="left",
    )
    merged["unit_capacity_loss_ratio_vs_global"] = (
        merged["unit_capacity_loss"]
        / merged["total_unit_capacity_loss"]
    )
    return merged


# ------------------------------- 角度6：频次 × 强度分解（事件时长与单位时长损失）

def frequency_intensity(data: pd.DataFrame) -> pd.DataFrame:
    """按带分解事件净损失 = 事件小时数 × 单位小时净损失（event 行，十年累计）。"""
    selected = data[data["event"].ne("all")]
    summary = selected.groupby(
        ["lon_band", "scenario", "tech", "snapshot_year", "event"], as_index=False
    ).agg(
        net_loss_mwh_decade=("net_generation_loss_mwh", "sum"),
        event_hours_decade=("event_duration_hours", "sum"),
        n_stations=("station_id", "nunique"),
    )
    summary["net_loss_per_event_hour_mwh"] = np.where(
        summary["event_hours_decade"] > 0,
        summary["net_loss_mwh_decade"] / summary["event_hours_decade"],
        np.nan,
    )
    summary["positive_net_loss_mwh_decade"] = summary["net_loss_mwh_decade"].clip(lower=0)
    summary["lon_band"] = pd.Categorical(summary["lon_band"], categories=LON_BANDS, ordered=True)
    return summary.sort_values(["tech", "lon_band", "scenario", "snapshot_year", "event"]).reset_index(drop=True)


# ------------------------------------------- 角度7：带内国家构成（混杂因素检查）

def band_country_mix(data: pd.DataFrame) -> pd.DataFrame:
    """每带的国家构成（场站数与容量份额），识别由单一国家主导的带。"""
    selected = data[data["event"].eq("all")].drop_duplicates(["scenario", "tech", "station_id"])
    by_station = selected.groupby(
        ["lon_band", "scenario", "tech", "region"], as_index=False
    ).agg(
        n_stations=("station_id", "size"),
        capacity_gw=("capacity_mw", "sum"),
    )
    by_station["capacity_gw"] = by_station["capacity_gw"] / 1000
    total = by_station.groupby(["lon_band", "scenario", "tech"], as_index=False).agg(
        total_gw=("capacity_gw", "sum"), total_stations=("n_stations", "sum"),
    )
    merged = by_station.merge(total, on=["lon_band", "scenario", "tech"], how="left")
    merged["capacity_share_pct"] = merged["capacity_gw"] / merged["total_gw"] * 100
    merged["station_share_pct"] = merged["n_stations"] / merged["total_stations"] * 100
    merged["lon_band"] = pd.Categorical(merged["lon_band"], categories=LON_BANDS, ordered=True)
    return merged.sort_values(["tech", "lon_band", "scenario", "region"]).reset_index(drop=True)


# --------------------------------------------------------------------- 绘图

def plot_disparity(disparity: pd.DataFrame, output_dir: Path) -> Path:
    """带间单位装机损失极差随情景×年代的变化。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=False)
    for ax, tech in zip(axes, TECHS):
        sub = disparity[disparity["tech"].eq(tech)]
        for scenario in COMPARE_SSPS:
            s = sub[sub["scenario"].eq(scenario)].sort_values("snapshot_year")
            ax.plot(s["snapshot_year"], s["range_unit_capacity_loss"], "-o", color=SSP_COLOR[scenario],
                    lw=1.6, ms=3, label=SSP_LABEL[scenario])
        ax.set_xticks(SNAPSHOTS, [f"{y}s" for y in SNAPSHOTS])
        ax.set_title(TECH_LABEL[tech])
        ax.grid(axis="y", alpha=0.2)
        ax.legend(fontsize=6)
        if ax is axes[0]:
            ax.set_ylabel("Max–min band range (MWh MW$^{-1}$ yr$^{-1}$)")
    fig.suptitle("Longitude-band disparity of unit capacity loss (max − min)",
                 fontsize=9, fontweight="bold")
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_lon_disparity")


def plot_contribution(contrib: pd.DataFrame, output_dir: Path) -> Path:
    """2050s：每带损失占比 vs 装机占比（成对柱）。"""
    configure_style()
    data = contrib[contrib["snapshot_year"].eq(2050)]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    width = 0.38
    for ax, tech in zip(axes, TECHS):
        sub = data[data["tech"].eq(tech)]
        bands = [b for b in LON_BANDS if (sub["lon_band"] == b).any()]
        for k, scenario in enumerate(COMPARE_SSPS):
            s = sub[sub["scenario"].eq(scenario)].set_index("lon_band").reindex(bands)
            xs = np.arange(len(bands)) + (k - 1) * width
            ax.bar(xs - width / 2.05, s["capacity_share_pct"], width=width * 0.92,
                   color=SSP_COLOR[scenario], alpha=0.45, edgecolor="white", linewidth=0.3)
            ax.bar(xs + width / 2.05, s["loss_share_pct"], width=width * 0.92,
                   color=SSP_COLOR[scenario], edgecolor="white", linewidth=0.3)
        ax.set_xticks(range(len(bands)), [BAND_LABEL[b] for b in bands], rotation=45)
        ax.set_title(TECH_LABEL[tech])
        ax.grid(axis="y", alpha=0.2)
        if ax is axes[0]:
            ax.set_ylabel("Share (%)")
    handles = [
        Patch(facecolor="#888888", alpha=0.45, label="Capacity share"),
        Patch(facecolor="#888888", label="Loss share"),
    ] + [Patch(facecolor=SSP_COLOR[s], label=SSP_LABEL[s]) for s in COMPARE_SSPS]
    fig.legend(handles=handles, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 1.06))
    fig.suptitle("Longitude-band shares of capacity vs total loss (2050s; faded = capacity)",
                 fontsize=9, fontweight="bold", y=1.16)
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_lon_contribution_2050")


def plot_frequency_intensity(freq: pd.DataFrame, output_dir: Path) -> Path:
    """2050s：low_resource 的频次（小时）×强度（MWh/h）带级对比。"""
    configure_style()
    data = freq[
        freq["snapshot_year"].eq(2050) & freq["event"].eq("low_resource")
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    for ax, tech in zip(axes, TECHS):
        sub = data[data["tech"].eq(tech)]
        for scenario in COMPARE_SSPS:
            s = sub[sub["scenario"].eq(scenario)]
            ax.scatter(
                s["event_hours_decade"] / 1e3, s["net_loss_per_event_hour_mwh"],
                s=18 + s["positive_net_loss_mwh_decade"] / sub["positive_net_loss_mwh_decade"].max() * 90,
                color=SSP_COLOR[scenario], alpha=0.75, edgecolor="white", linewidth=0.4,
                label=SSP_LABEL[scenario],
            )
        ax.set_xlabel("Event hours per decade (×10³, station-sum)")
        if ax is axes[0]:
            ax.set_ylabel("Net loss per event hour (MWh/h, station-sum)")
        ax.set_title(TECH_LABEL[tech])
        ax.grid(alpha=0.2)
        ax.legend(fontsize=6, loc="upper right")
    fig.suptitle("Frequency × intensity of low-resource loss by longitude band (2050s; size ∝ positive loss)",
                 fontsize=8.5, fontweight="bold")
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_lon_freq_intensity_low_resource_2050")


def main() -> None:
    args = parse_args()
    station_csv = args.station_input_csv or resolve_path(DEFAULT_STATION_CSV, args.model)
    if not station_csv.exists():
        raise SystemExit(f"未找到输入文件：{station_csv}")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    csv_dir = output_dir / "csv" / "further"
    figure_dir = output_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)

    data = load_full(station_csv, args.model)
    metrics = band_metrics(data)
    events = band_event_losses(data)

    disparity = band_disparity(metrics)
    ssp_sens = ssp_sensitivity(metrics)
    trends = time_trend(metrics)
    contrib = global_contribution(metrics)
    freq = frequency_intensity(data)
    mix = band_country_mix(data)

    disparity.to_csv(csv_dir / "further_band_disparity.csv", index=False)
    ssp_sens.to_csv(csv_dir / "further_ssp_sensitivity.csv", index=False)
    trends.to_csv(csv_dir / "further_time_trend.csv", index=False)
    contrib.to_csv(csv_dir / "further_global_contribution.csv", index=False)
    freq.to_csv(csv_dir / "further_frequency_intensity.csv", index=False)
    mix.to_csv(csv_dir / "further_band_country_mix.csv", index=False)

    plot_disparity(disparity, figure_dir)
    plot_contribution(contrib, figure_dir)
    plot_frequency_intensity(freq, figure_dir)

    config = {"model": args.model, "input_csv": str(station_csv.resolve()),
              "input_sha256": hashlib.sha256(station_csv.read_bytes()).hexdigest()}
    (csv_dir / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"已保存进一步分析结果：{csv_dir} 与 {figure_dir}/further_lon_*.png")


if __name__ == "__main__":
    main()
