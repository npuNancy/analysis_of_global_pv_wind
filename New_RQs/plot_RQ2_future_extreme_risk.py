#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制 RQ2：当前风光优化布局是否暴露于未来极端风险（Fig. 2a–f）。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import unicodedata

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import cartopy.crs as ccrs
from cartopy.io import shapereader
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D

from plot_RQ1_extreme_weather_loss import (
    DEFAULT_MAP,
    ROOT,
    SSP_COLORS,
    SSP_LABELS,
    SSPS,
    TECH_LABELS,
    configure_style,
    panel_label,
    require_columns,
)


DEFAULT_MODEL = "CANESM5"
DEFAULT_OUTPUT = ROOT / "New_RQs/outputs/fig_RQ2_future_extreme_risk.png"
TECH_COLORS = {"wind": "#356A8A", "solar": "#D69C3D"}
TECH_MARKERS = {"wind": "^", "solar": "o"}
RISK_CMAP = LinearSegmentedColormap.from_list(
    "future_extreme_risk", ["#F4F2EE", "#E7C6BC", "#C77B72", "#8F3745"]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="绘制 RQ2 六面板未来极端风险图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="使用的气候模式。")
    parser.add_argument("--risk-csv", type=Path, default=None, help="场站-年份风险明细 CSV。")
    parser.add_argument("--transition-csv", type=Path, default=None, help="2030 cohort 风险转移 CSV。")
    parser.add_argument("--generation-csv", type=Path, default=None, help="国家级发电量与 CF CSV。")
    parser.add_argument("--region-loss-dir", type=Path, default=None, help="逐国单位装机损失目录。")
    parser.add_argument(
        "--map-shapefile", type=Path, default=DEFAULT_MAP, help="Natural Earth 国家边界 shp 文件。"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 PNG 路径。")
    parser.add_argument("--dpi", type=int, default=400, help="PNG 输出分辨率。")
    return parser.parse_args()


def input_paths(args: argparse.Namespace) -> dict[str, Path]:
    csv_dir = ROOT / "RQ2/outputs" / args.model / "csv"
    return {
        "risk": args.risk_csv
        or csv_dir
        / f"RQ2_1_station_year_risk_{args.model}_regional_bcsd_ssp126-ssp245-ssp585_2030-2040-2050.csv",
        "transition": args.transition_csv or csv_dir / "RQ2_1_cohort_transition.csv",
        "generation": args.generation_csv
        or ROOT / "data/real/RQ1_generation" / args.model / "country_annual_generation.csv",
        "region_loss": args.region_loss_dir
        or ROOT / "RQ3/outputs" / args.model / "region_generation_loss",
    }


def load_station_risk(source: Path) -> pd.DataFrame:
    if not source.exists():
        raise FileNotFoundError(f"未找到场站风险数据：{source}")
    columns = [
        "region",
        "ssp",
        "tech",
        "year",
        "activation_year",
        "capacity_gw",
        "risk_days",
        "station_lon",
        "station_lat",
    ]
    data = pd.read_csv(source, usecols=columns)
    require_columns(data, set(columns), source)
    data = data[
        data["ssp"].isin(["ssp126", "ssp585"])
        & data["tech"].isin(TECH_LABELS)
        & data["year"].eq(2050)
        & data["activation_year"].le(2050)
    ].copy()
    finite = np.isfinite(data[["risk_days", "capacity_gw", "station_lon", "station_lat"]]).all(axis=1)
    data = data[finite & data["capacity_gw"].gt(0)].copy()
    if data.empty:
        raise ValueError("场站风险数据中没有符合 2050 年地图条件的记录。")
    return data


def load_transition(source: Path) -> pd.DataFrame:
    if not source.exists():
        raise FileNotFoundError(f"未找到风险转移数据：{source}")
    data = pd.read_csv(source)
    required = {
        "ssp",
        "tech",
        "target_year",
        "transition",
        "station_count",
        "station_share_pct",
    }
    require_columns(data, required, source)
    selected = data[
        data["ssp"].isin(SSPS)
        & data["tech"].isin(TECH_LABELS)
        & data["target_year"].eq(2050)
        & data["transition"].eq("new_high")
    ].copy()
    counts = selected.groupby(["ssp", "tech"]).size()
    if len(counts) != 6 or not counts.eq(1).all():
        raise ValueError("2030 cohort 到 2050 年的 new_high 转移数据不完整。")
    return selected


def load_country_resource_risk(generation_source: Path, region_loss_dir: Path) -> pd.DataFrame:
    if not generation_source.exists():
        raise FileNotFoundError(f"未找到国家级 CF 数据：{generation_source}")
    generation = pd.read_csv(generation_source)
    require_columns(
        generation,
        {"country", "technology", "deploy_ssp", "climate_ssp", "target_year", "mean_cf"},
        generation_source,
    )
    generation = generation[
        generation["technology"].isin(TECH_LABELS)
        & generation["deploy_ssp"].eq("ssp126")
        & generation["climate_ssp"].eq("ssp126")
        & generation["target_year"].eq(2050)
    ][["country", "technology", "mean_cf"]].rename(columns={"technology": "tech"})

    loss_files = sorted(region_loss_dir.glob("*/*generation_loss_per_capacity_region_evolution.csv"))
    if not loss_files:
        raise FileNotFoundError(f"未找到逐国单位装机损失 CSV：{region_loss_dir}")
    loss_parts = []
    for source in loss_files:
        part = pd.read_csv(source)
        require_columns(
            part,
            {
                "region",
                "scenario",
                "tech",
                "snapshot_year",
                "loss_twh_per_tw_mean",
                "capacity_tw_mean",
            },
            source,
        )
        loss_parts.append(part)
    loss = pd.concat(loss_parts, ignore_index=True)
    loss = loss[
        loss["scenario"].eq("ssp126")
        & loss["snapshot_year"].eq(2050)
        & loss["tech"].isin(TECH_LABELS)
    ][["region", "tech", "loss_twh_per_tw_mean", "capacity_tw_mean"]].rename(
        columns={"region": "country"}
    )
    if loss.duplicated(["country", "tech"]).any():
        raise ValueError("逐国单位装机损失数据包含重复的 country-tech 记录。")

    data = generation.merge(loss, on=["country", "tech"], how="inner", validate="one_to_one")
    data["cf_pct"] = data["mean_cf"] * 100.0
    data["capacity_gw"] = data["capacity_tw_mean"] * 1e3
    data = data[
        np.isfinite(data[["cf_pct", "loss_twh_per_tw_mean", "capacity_gw"]]).all(axis=1)
        & data["capacity_gw"].gt(0)
    ].copy()
    if data.groupby("tech")["country"].nunique().lt(10).any():
        raise ValueError("国家资源-风险散点图的有效国家不足。")
    return data


def normalized_country_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(normalized.lower().replace("-", " ").split())


def country_risk(stations: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (ssp, region), subset in stations.groupby(["ssp", "region"], sort=False):
        weights = subset["capacity_gw"].to_numpy(dtype=float)
        values = subset["risk_days"].to_numpy(dtype=float)
        rows.append(
            {
                "ssp": ssp,
                "region": region,
                "risk_days": float(np.average(values, weights=weights)),
            }
        )
    return pd.DataFrame(rows)


def draw_risk_map(
    fig: mpl.figure.Figure,
    ax: mpl.axes.Axes,
    map_records: list,
    stations: pd.DataFrame,
    risks: pd.DataFrame,
    ssp: str,
    norm: Normalize,
    label: str,
) -> None:
    scenario_risk = risks[risks["ssp"].eq(ssp)].copy()
    risk_lookup = {
        normalized_country_name(row.region): float(row.risk_days)
        for row in scenario_risk.itertuples(index=False)
    }
    matched: set[str] = set()

    ax.set_global()
    ax.set_facecolor("#F7FAFC")
    for record in map_records:
        attrs = record.attributes
        if attrs.get("ADMIN") == "Antarctica":
            continue
        key = normalized_country_name(str(attrs.get("ADMIN", "")))
        risk = risk_lookup.get(key)
        if risk is None:
            facecolor = "#E6EAED"
        else:
            facecolor = RISK_CMAP(norm(risk))
            matched.add(key)
        ax.add_geometries(
            [record.geometry],
            crs=ccrs.PlateCarree(),
            facecolor=facecolor,
            edgecolor="#FFFFFF",
            linewidth=0.28,
            zorder=1,
        )
    missing = set(risk_lookup).difference(matched)
    if missing:
        raise ValueError(f"地图中未匹配国家：{', '.join(sorted(missing))}")

    scenario_stations = stations[stations["ssp"].eq(ssp)]
    station_handles = []
    for tech in ["wind", "solar"]:
        subset = scenario_stations[scenario_stations["tech"].eq(tech)]
        ax.scatter(
            subset["station_lon"],
            subset["station_lat"],
            s=2.5,
            marker=TECH_MARKERS[tech],
            transform=ccrs.PlateCarree(),
            facecolor=TECH_COLORS[tech],
            edgecolor="none",
            alpha=0.38,
            rasterized=True,
            zorder=3,
        )
        station_handles.append(
            Line2D(
                [0],
                [0],
                marker=TECH_MARKERS[tech],
                linestyle="none",
                markerfacecolor=TECH_COLORS[tech],
                markeredgecolor="none",
                markersize=5,
                label=f"{TECH_LABELS[tech]}场站（n={len(subset):,}）",
            )
        )

    gridlines = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=False,
        linewidth=0.35,
        color="#93A1AA",
        alpha=0.28,
        linestyle=":",
        zorder=0,
    )
    gridlines.xlocator = mpl.ticker.FixedLocator(np.arange(-120, 181, 60))
    gridlines.ylocator = mpl.ticker.FixedLocator(np.arange(-60, 61, 30))
    ax.set_title(f"2050 年场站分布与极端风险 · {SSP_LABELS[ssp]}", pad=6)
    panel_label(ax, label, x=-0.02, y=1.04)
    ax.legend(
        handles=station_handles,
        loc="lower left",
        bbox_to_anchor=(0.01, 0.025),
        borderaxespad=0,
        handletextpad=0.5,
        labelspacing=0.5,
    )

    colorbar = fig.colorbar(
        mpl.cm.ScalarMappable(norm=norm, cmap=RISK_CMAP),
        ax=ax,
        orientation="horizontal",
        fraction=0.04,
        pad=0.035,
        shrink=0.58,
        aspect=30,
    )
    colorbar.set_label("国家容量加权极端暴露时间（天/年）", labelpad=2)
    colorbar.ax.tick_params(labelsize=6, length=2)
    colorbar.outline.set_linewidth(0.5)


def draw_transition_bars(
    ax: mpl.axes.Axes, transition: pd.DataFrame, tech: str, label: str
) -> None:
    subset = transition[transition["tech"].eq(tech)].set_index("ssp").reindex(SSPS)
    values = subset["station_share_pct"].to_numpy(dtype=float)
    counts = subset["station_count"].to_numpy(dtype=int)
    x = np.arange(len(SSPS))
    bars = ax.bar(
        x,
        values,
        width=0.68,
        color=[SSP_COLORS[ssp] for ssp in SSPS],
        edgecolor="white",
        linewidth=0.6,
    )
    padding = max(float(np.nanmax(values)) * 0.04, 0.25)
    for bar, value, count in zip(bars, values, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + padding,
            f"{value:.1f}%\nn={count}",
            ha="center",
            va="bottom",
            fontsize=6.2,
            linespacing=1.05,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([SSP_LABELS[ssp] for ssp in SSPS], rotation=25, ha="right")
    ax.set_ylim(0, max(12.0, float(np.nanmax(values)) * 1.35))
    ax.set_ylabel("转为高风险的场站比例（%）")
    ax.set_title(f"{TECH_LABELS[tech]}：2030 cohort 低风险→高风险")
    ax.grid(axis="y", color="#D5D9DC", linewidth=0.5, alpha=0.8)
    panel_label(ax, label, x=-0.13, y=1.08)


def capacity_size(value: float, scale_value: float) -> float:
    return 14.0 + 120.0 * min(value / scale_value, 1.0)


def draw_resource_risk_scatter(
    ax: mpl.axes.Axes, country_data: pd.DataFrame, tech: str, label: str
) -> None:
    subset = country_data[country_data["tech"].eq(tech)].copy()
    scale_value = float(subset["capacity_gw"].quantile(0.95))
    sizes = [capacity_size(value, scale_value) for value in subset["capacity_gw"]]
    ax.scatter(
        subset["cf_pct"],
        subset["loss_twh_per_tw_mean"],
        s=sizes,
        facecolor=TECH_COLORS[tech],
        edgecolor="white",
        linewidth=0.6,
        alpha=0.72,
        zorder=3,
    )

    label_countries = set(subset.nlargest(3, "capacity_gw")["country"])
    label_countries.add(str(subset.loc[subset["loss_twh_per_tw_mean"].idxmax(), "country"]))
    offsets = [(4, 4), (4, -8), (-4, 4), (-4, -8)]
    for offset, row in zip(offsets, subset[subset["country"].isin(label_countries)].itertuples()):
        ax.annotate(
            row.country,
            (row.cf_pct, row.loss_twh_per_tw_mean),
            xytext=offset,
            textcoords="offset points",
            fontsize=5.3,
            ha="left" if offset[0] > 0 else "right",
            va="bottom" if offset[1] > 0 else "top",
            color="#3E3E3E",
        )

    legend_values = subset["capacity_gw"].quantile([0.50, 0.75, 0.95]).to_numpy(dtype=float)
    handles = [
        ax.scatter(
            [],
            [],
            s=capacity_size(value, scale_value),
            facecolor=TECH_COLORS[tech],
            edgecolor="white",
            linewidth=0.6,
            alpha=0.72,
            label=f"{value:,.0f}",
        )
        for value in legend_values
    ]
    legend = ax.legend(
        handles=handles,
        title="装机容量（GW）",
        loc="upper left",
        labelspacing=0.6,
        handletextpad=0.6,
        borderaxespad=0.3,
    )
    legend.get_title().set_fontsize(6.5)

    ax.set_xlabel(f"{TECH_LABELS[tech]}容量因子（%）")
    ax.set_ylabel("单位发电损失（TWh/TW·年）")
    ax.set_title(f"{TECH_LABELS[tech]}资源—风险 · SSP1-2.6, 2050s")
    ax.grid(color="#D5D9DC", linewidth=0.5, alpha=0.8)
    ax.margins(x=0.08, y=0.12)
    panel_label(ax, label, x=-0.13, y=1.08)


def make_figure(args: argparse.Namespace) -> Path:
    configure_style()
    paths = input_paths(args)
    stations = load_station_risk(paths["risk"])
    transitions = load_transition(paths["transition"])
    country_data = load_country_resource_risk(paths["generation"], paths["region_loss"])
    risks = country_risk(stations)

    if not args.map_shapefile.exists():
        raise FileNotFoundError(f"未找到国家边界文件：{args.map_shapefile}")
    map_records = list(shapereader.Reader(args.map_shapefile).records())
    risk_vmax = float(risks["risk_days"].quantile(0.98))
    risk_norm = Normalize(vmin=0.0, vmax=risk_vmax)

    fig = plt.figure(figsize=(15.2, 8.7))
    grid = fig.add_gridspec(
        4,
        4,
        left=0.055,
        right=0.955,
        bottom=0.105,
        top=0.885,
        hspace=0.95,
        wspace=0.60,
        height_ratios=[0.65, 0.65, 0.65, 1.15],
    )
    ax_a = fig.add_subplot(grid[:3, :2], projection=ccrs.Robinson())
    ax_b = fig.add_subplot(grid[:3, 2:], projection=ccrs.Robinson())
    ax_c = fig.add_subplot(grid[3, 0])
    ax_d = fig.add_subplot(grid[3, 1])
    ax_e = fig.add_subplot(grid[3, 2])
    ax_f = fig.add_subplot(grid[3, 3])

    draw_risk_map(fig, ax_a, map_records, stations, risks, "ssp126", risk_norm, "a")
    draw_risk_map(fig, ax_b, map_records, stations, risks, "ssp585", risk_norm, "b")
    draw_transition_bars(ax_c, transitions, "wind", "c")
    draw_transition_bars(ax_d, transitions, "solar", "d")
    draw_resource_risk_scatter(ax_e, country_data, "wind", "e")
    draw_resource_risk_scatter(ax_f, country_data, "solar", "f")

    scenario_handles = [
        Line2D([0], [0], color=SSP_COLORS[ssp], linewidth=2.2, label=SSP_LABELS[ssp])
        for ssp in SSPS
    ]
    scenario_legend = fig.legend(
        handles=scenario_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.938),
        ncol=3,
        columnspacing=2.0,
        handlelength=2.5,
        title="气候路径",
    )
    scenario_legend.get_title().set_fontsize(7)

    fig.suptitle(
        "RQ2｜当前风光优化布局是否暴露于未来极端风险？",
        fontsize=13,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.5,
        0.025,
        (
            "a–b，国家填色为全部在运场站的容量加权极端暴露，符号为截至 2050 年投运的场站；"
            "c–d，高风险阈值为各 SSP–技术 2030 cohort 基准风险的容量加权 P80，比例分母为全部 2030 cohort 场站；"
            "e–f，每点为一个国家，单位发电损失=净出力损失/装机容量。"
        ),
        ha="center",
        fontsize=6.3,
        color="#555555",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)
    return args.output


def main() -> None:
    args = parse_args()
    output = make_figure(args)
    print(f"已保存：{output}")


if __name__ == "__main__":
    main()
