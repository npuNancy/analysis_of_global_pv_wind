#!/usr/bin/env python3
"""基于纬度带单位装机损失的进一步分析。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from common import (
    BAND_COLOR,
    BAND_EDGES,
    BAND_LABEL,
    BAND_MARKER,
    FURTHER_USE_COLUMNS,
    LAT_BANDS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STATION_CSV,
    EVENT_COLOR,
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

MID_OF_DECADE = {2030: 2035, 2040: 2045, 2050: 2055}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--station-input-csv", type=Path, default=None, help="场站十年损失长表。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。")
    return parser.parse_args()


def load_full(station_csv: Path, model: str) -> pd.DataFrame:
    raw = pd.read_csv(station_csv, usecols=FURTHER_USE_COLUMNS)
    data = raw[
        raw["model"].eq(model) & raw["scenario"].isin(COMPARE_SSPS)
        & raw["tech"].isin(TECHS) & raw["snapshot_year"].isin(SNAPSHOTS)
        & raw["analysis_scheme"].eq("center-k") & raw["analysis_k"].eq(5)
    ].copy()
    # 与 common.load_source 相同的临时风电修正（上游修复后移除）。
    wind = data["tech"].eq("wind")
    for col in ("net_generation_loss_mwh", "normal_all_generation_mwh"):
        data.loc[wind, col] *= 0.1
    hemisphere = np.where(data["lat"].ge(0), "N", "S")
    magnitude = data["lat"].abs()
    data["lat_band"] = pd.Series(hemisphere, index=data.index) + "-" + np.select(
        [magnitude < BAND_EDGES[0], magnitude < BAND_EDGES[1]],
        ["low", "mid"], default="high",
    )
    return data


# ---------------------------------------------------------------- 角度1：纬度梯度

def latitude_gradient(metrics: pd.DataFrame) -> pd.DataFrame:
    """以带中心纬度回归单位装机损失，输出斜率（MWh MW^-1 yr^-1 per degree）。"""
    center = {"N-high": 65.0, "N-mid": 40.0, "N-low": 15.0,
              "S-low": -15.0, "S-mid": -40.0, "S-high": -65.0}
    rows = []
    for keys, group in metrics.groupby(["tech", "scenario", "snapshot_year"]):
        valid = group[group["unit_capacity_loss"].notna()]
        if len(valid) < 3:
            continue
        x = valid["lat_band"].map(center).to_numpy(dtype=float)
        y = valid["unit_capacity_loss"].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        r = float(np.corrcoef(x, y)[0, 1])
        rows.append(dict(
            tech=keys[0], scenario=keys[1], snapshot_year=keys[2],
            slope_unit_capacity_loss_per_deg=float(slope), intercept_unit_capacity_loss=float(intercept),
            pearson_r=r, n_bands=len(valid),
        ))
    return pd.DataFrame(rows)


# ------------------------------------------------------- 角度2：半球对称性差异

def hemisphere_asymmetry(metrics: pd.DataFrame) -> pd.DataFrame:
    """同纬度绝对值带之间 N-S 差：正=北半球单位装机损失更高。"""
    pivot = metrics.pivot_table(
        index=["tech", "scenario", "snapshot_year"], columns="lat_band",
        values="unit_capacity_loss",
    )
    rows = []
    for band in ("low", "mid", "high"):
        north, south = f"N-{band}", f"S-{band}"
        if north in pivot.columns and south in pivot.columns:
            diff = pivot[north] - pivot[south]
            for (tech, scenario, snapshot), value in diff.dropna().items():
                rows.append(dict(
                    tech=tech, scenario=scenario, snapshot_year=snapshot,
                    band=band, north_unit_capacity_loss=pivot.loc[(tech, scenario, snapshot), north],
                    south_unit_capacity_loss=pivot.loc[(tech, scenario, snapshot), south],
                    north_minus_south_unit_capacity_loss=float(value),
                ))
    return pd.DataFrame(rows)


# --------------------------------------------------------- 角度3：SSP 敏感度

def ssp_sensitivity(metrics: pd.DataFrame) -> pd.DataFrame:
    """每带单位装机损失的情景跨度及其占 SSP1-2.6 水平的比例。"""
    pivot = metrics.pivot_table(
        index=["tech", "lat_band", "snapshot_year"], columns="scenario",
        values="unit_capacity_loss",
    )
    pivot["ssp585_minus_126_unit_capacity_loss"] = pivot["ssp585"] - pivot["ssp126"]
    pivot["ssp585_minus_245_unit_capacity_loss"] = pivot["ssp585"] - pivot["ssp245"]
    pivot["span_ratio_vs_126"] = pivot["ssp585_minus_126_unit_capacity_loss"] / pivot["ssp126"] * 100
    return pivot.reset_index()


# ------------------------------------------------------------- 角度4：时间趋势

def time_trend(metrics: pd.DataFrame) -> pd.DataFrame:
    """带内 2030s→2050s 单位装机损失变化，按情景。"""
    pivot = metrics.pivot_table(
        index=["tech", "lat_band", "scenario"], columns="snapshot_year",
        values="unit_capacity_loss",
    )
    pivot["change_2030s_to_2050s_unit_capacity_loss"] = pivot[2050] - pivot[2030]
    pivot["relative_change_pct"] = pivot["change_2030s_to_2050s_unit_capacity_loss"] / pivot[2030] * 100
    return pivot.reset_index()


# --------------------------------------------- 角度5：事件构成（带×事件占比）

def event_composition(events: pd.DataFrame) -> pd.DataFrame:
    """每带各事件损失加权占比（含剔除 low_resource 的残差口径），2050s 快照。"""
    return events[events["snapshot_year"].eq(2050)]


# ------------------------------------- 角度6：纬度带对全球总损失的贡献占比

def global_contribution(metrics: pd.DataFrame) -> pd.DataFrame:
    """每带净损失占全部带总和的比例，及其装机占比和单位装机损失对照。"""
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


# ------------------------------- 角度7：频次 × 强度分解（事件时长与单位时长损失）

def frequency_intensity(data: pd.DataFrame) -> pd.DataFrame:
    """按带分解事件净损失 = 事件小时数 × 单位小时净损失（event 行，十年累计）。"""
    selected = data[data["event"].ne("all")]
    summary = selected.groupby(
        ["lat_band", "scenario", "tech", "snapshot_year", "event"], as_index=False
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
    summary["lat_band"] = pd.Categorical(summary["lat_band"], categories=LAT_BANDS, ordered=True)
    return summary.sort_values(["tech", "lat_band", "scenario", "snapshot_year", "event"]).reset_index(drop=True)


# ------------------------------------------- 角度8：带内国家构成（混杂因素检查）

def band_country_mix(data: pd.DataFrame) -> pd.DataFrame:
    """每带的国家构成（场站数与容量份额），识别由单一国家主导的带。"""
    selected = data[data["event"].eq("all")].drop_duplicates(["scenario", "tech", "station_id"])
    by_station = selected.groupby(
        ["lat_band", "scenario", "tech", "region"], as_index=False
    ).agg(
        n_stations=("station_id", "size"),
        capacity_mw=("capacity_mw", "first"),
    )
    by_station["capacity_gw"] = by_station["capacity_mw"] * by_station["n_stations"] / 1000
    total = by_station.groupby(["lat_band", "scenario", "tech"], as_index=False).agg(
        total_gw=("capacity_gw", "sum"), total_stations=("n_stations", "sum"),
    )
    merged = by_station.merge(total, on=["lat_band", "scenario", "tech"], how="left")
    merged["capacity_share_pct"] = merged["capacity_gw"] / merged["total_gw"] * 100
    merged["station_share_pct"] = merged["n_stations"] / merged["total_stations"] * 100
    merged["lat_band"] = pd.Categorical(merged["lat_band"], categories=LAT_BANDS, ordered=True)
    return merged.sort_values(["tech", "lat_band", "scenario", "region"]).reset_index(drop=True)


# --------------------------------------------------------------------- 绘图

def plot_gradient_heatmap(gradients: pd.DataFrame, output_dir: Path) -> Path:
    """单位装机损失斜率随情景与年代的演变。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=True)
    for ax, tech in zip(axes, TECHS):
        sub = gradients[gradients["tech"].eq(tech)].pivot(
            index="scenario", columns="snapshot_year", values="slope_unit_capacity_loss_per_deg",
        ).reindex(COMPARE_SSPS)
        vmin = float(np.nanmin(np.abs(sub.to_numpy())))
        vmax = float(np.nanmax(np.abs(sub.to_numpy())))
        im = ax.imshow(sub.to_numpy(), cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(SNAPSHOTS)), [f"{y}s" for y in SNAPSHOTS])
        ax.set_yticks(range(len(COMPARE_SSPS)), [SSP_LABEL[s] for s in COMPARE_SSPS])
        for i in range(sub.shape[0]):
            for j in range(sub.shape[1]):
                value = sub.to_numpy()[i, j]
                if np.isfinite(value):
                    ax.text(j, i, f"{value:.3f}", ha="center", va="center", fontsize=6,
                            color="white" if abs(value) > vmax * 0.55 else "black")
        ax.set_title(TECH_LABEL[tech])
        fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03,
                     label="MWh MW$^{-1}$ yr$^{-1}$ per ° latitude")
    fig.suptitle("Latitude gradient of unit capacity loss (linear fit, 6 bands)",
                 fontsize=9, fontweight="bold")
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_gradient_heatmap")


def plot_asymmetry(asym: pd.DataFrame, output_dir: Path) -> Path:
    """N-S 单位装机损失差：分带、情景、年代。"""
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9), sharey=True)
    width = 0.26
    for ax, tech in zip(axes, TECHS):
        sub = asym[asym["tech"].eq(tech)]
        bands = [b for b in ("low", "mid", "high") if (sub["band"] == b).any()]
        for k, scenario in enumerate(COMPARE_SSPS):
            xs, ys = [], []
            for i, band in enumerate(bands):
                for year in SNAPSHOTS:
                    match = sub[
                        sub["band"].eq(band) & sub["scenario"].eq(scenario)
                        & sub["snapshot_year"].eq(year)
                    ]
                    if len(match):
                        xs.append(i + (k - 1) * width + (year - 2040) * width / 3.4)
                        ys.append(float(match["north_minus_south_unit_capacity_loss"].iloc[0]))
            ax.bar(xs, ys, width=width * 0.9, color=SSP_COLOR[scenario], label=SSP_LABEL[scenario])
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(range(len(bands)), [f"{b} lat" for b in bands])
        ax.set_title(TECH_LABEL[tech])
        ax.grid(axis="y", alpha=0.2)
        ax.legend(fontsize=6)
        if ax is axes[0]:
            ax.set_ylabel("N minus S (MWh MW$^{-1}$ yr$^{-1}$)")
    fig.suptitle("Hemispheric asymmetry of unit capacity loss by band (bar = decade)",
                 fontsize=9, fontweight="bold")
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_asymmetry")


def plot_contribution(contrib: pd.DataFrame, output_dir: Path) -> Path:
    """2050s：每带损失占比 vs 装机占比（成对柱），暴露“装机多但损失率低”错位。"""
    configure_style()
    data = contrib[contrib["snapshot_year"].eq(2050)]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    width = 0.38
    for ax, tech in zip(axes, TECHS):
        sub = data[data["tech"].eq(tech)]
        bands = [b for b in LAT_BANDS if (sub["lat_band"] == b).any()]
        for k, scenario in enumerate(COMPARE_SSPS):
            s = sub[sub["scenario"].eq(scenario)].set_index("lat_band").reindex(bands)
            xs = np.arange(len(bands)) + (k - 1) * width
            ax.bar(xs - width / 2.05, s["capacity_share_pct"], width=width * 0.92,
                   color=SSP_COLOR[scenario], alpha=0.45, edgecolor="white", linewidth=0.3)
            ax.bar(xs + width / 2.05, s["loss_share_pct"], width=width * 0.92,
                   color=SSP_COLOR[scenario], edgecolor="white", linewidth=0.3)
        ax.set_xticks(range(len(bands)), [BAND_LABEL[b].split(" (")[0] for b in bands], rotation=45)
        ax.set_title(TECH_LABEL[tech])
        ax.grid(axis="y", alpha=0.2)
        if ax is axes[0]:
            ax.set_ylabel("Share (%)")
    handles = [
        Patch(facecolor="#888888", alpha=0.45, label="Capacity share"),
        Patch(facecolor="#888888", label="Loss share"),
    ] + [Patch(facecolor=SSP_COLOR[s], label=SSP_LABEL[s]) for s in COMPARE_SSPS]
    fig.legend(handles=handles, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 1.06))
    fig.suptitle("Latitude-band shares of capacity vs total loss (2050s; faded = capacity)",
                 fontsize=9, fontweight="bold", y=1.16)
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_contribution_2050")


def plot_frequency_intensity(freq: pd.DataFrame, output_dir: Path) -> Path:
    """2050s：low_resource 的频次（小时）×强度（MWh/h）带级对比，散点大小=正损失量。"""
    configure_style()
    data = freq[
        freq["snapshot_year"].eq(2050) & freq["event"].eq("low_resource")
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharex=False, sharey=False)
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
    fig.suptitle("Frequency × intensity of low-resource loss (2050s, per band; size ∝ positive loss)",
                 fontsize=8.5, fontweight="bold")
    fig.tight_layout()
    return save_figure(fig, output_dir, "further_freq_intensity_low_resource_2050")


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

    # 复用 common 的带级指标与事件聚合，保证与主脚本口径一致。
    metrics = data[data["event"].eq("all")].groupby(
        ["lat_band", "scenario", "tech", "snapshot_year"], as_index=False
    ).agg(
        n_stations=("station_id", "nunique"),
        capacity_mw=("capacity_mw", "sum"),
        net_loss_mwh=("net_generation_loss_mwh", "sum"),
        normal_all_mwh=("normal_all_generation_mwh", "sum"),
    )
    metrics["unit_capacity_loss"] = np.where(
        metrics["capacity_mw"].gt(0),
        metrics["net_loss_mwh"] / metrics["capacity_mw"] / 10.0, np.nan,
    )
    events = band_event_losses(data)

    gradients = latitude_gradient(metrics)
    asym = hemisphere_asymmetry(metrics)
    ssp_sens = ssp_sensitivity(metrics)
    trends = time_trend(metrics)
    contrib = global_contribution(metrics)
    freq = frequency_intensity(data)
    mix = band_country_mix(data)

    gradients.to_csv(csv_dir / "further_latitude_gradient.csv", index=False)
    asym.to_csv(csv_dir / "further_hemisphere_asymmetry.csv", index=False)
    ssp_sens.to_csv(csv_dir / "further_ssp_sensitivity.csv", index=False)
    trends.to_csv(csv_dir / "further_time_trend.csv", index=False)
    contrib.to_csv(csv_dir / "further_global_contribution.csv", index=False)
    freq.to_csv(csv_dir / "further_frequency_intensity.csv", index=False)
    mix.to_csv(csv_dir / "further_band_country_mix.csv", index=False)

    plot_gradient_heatmap(gradients, figure_dir)
    plot_asymmetry(asym, figure_dir)
    plot_contribution(contrib, figure_dir)
    plot_frequency_intensity(freq, figure_dir)

    config = {"model": args.model, "input_csv": str(station_csv.resolve()),
              "input_sha256": hashlib.sha256(station_csv.read_bytes()).hexdigest()}
    (csv_dir / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"已保存进一步分析结果：{csv_dir} 与 {figure_dir}/further_*.png")


if __name__ == "__main__":
    main()
