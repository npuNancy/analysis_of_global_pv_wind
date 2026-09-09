#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制 RQ1：不同气候路径下极端天气造成的风光损失（Fig. 1a–f）。

面板 a、b 使用可复现的国家级模拟数据；面板 c–f 读取项目已有的
容量加权暴露、全球净出力损失和损失率年度汇总数据。
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import cartopy.crs as ccrs
from cartopy.io import shapereader
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "CANESM5"
DEFAULT_OUTPUT = ROOT / "New_RQs/outputs/fig_RQ1_extreme_weather_loss.png"
DEFAULT_MAP = ROOT / "data/maps/natural_earth/ne_110m_admin_0_countries.shp"

SSPS = ["ssp126", "ssp245", "ssp585"]
SSP_COLORS = {
    "ssp126": "#356A8A",
    "ssp245": "#D69C3D",
    "ssp585": "#A65353",
}
SSP_LABELS = {
    "ssp126": "SSP1-2.6",
    "ssp245": "SSP2-4.5",
    "ssp585": "SSP5-8.5",
}
TECH_LABELS = {"wind": "风电", "solar": "光伏"}
DECADES = [2030, 2040, 2050]
DECADE_LABELS = {2030: "2030s", 2040: "2040s", 2050: "2050s"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="绘制 RQ1 六面板风光极端天气损失图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="使用的气候模式。")
    parser.add_argument(
        "--map-shapefile",
        type=Path,
        default=DEFAULT_MAP,
        help="Natural Earth 国家边界 shp 文件。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出 PNG 路径。",
    )
    parser.add_argument("--mock-seed", type=int, default=20260907, help="地图模拟数据随机种子。")
    parser.add_argument("--dpi", type=int, default=400, help="PNG 输出分辨率。")
    return parser.parse_args()


def configure_style() -> None:
    font_path = ROOT / "data/SourceHanSansSC-Normal.otf"
    sans_fonts = ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"]
    if font_path.exists():
        fontManager.addfont(font_path)
        sans_fonts.insert(0, FontProperties(fname=font_path).get_name())

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans_fonts,
            "axes.unicode_minus": False,
            "font.size": 7,
            "axes.titlesize": 8.5,
            "axes.labelsize": 7.5,
            "axes.linewidth": 0.75,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 6.5,
            "ytick.labelsize": 6.5,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
            "legend.fontsize": 6.5,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.dpi": 400,
        }
    )


def require_columns(data: pd.DataFrame, columns: set[str], source: Path) -> None:
    missing = columns.difference(data.columns)
    if missing:
        raise ValueError(f"{source} 缺少字段：{', '.join(sorted(missing))}")


def load_exposure(model: str) -> pd.DataFrame:
    source = (
        ROOT
        / "RQ2/outputs"
        / model
        / "csv/RQ2_extreme_exposure_timeseries_capacity_weighted.csv"
    )
    if not source.exists():
        raise FileNotFoundError(f"未找到容量加权暴露数据：{source}")
    data = pd.read_csv(source)
    require_columns(data, {"ssp", "tech", "year", "exposed_days_per_gw_year"}, source)
    data = data[
        data["ssp"].isin(SSPS)
        & data["tech"].isin(TECH_LABELS)
        & data["year"].between(2030, 2059)
    ].copy()
    data["decade"] = data["year"].floordiv(10).mul(10).astype(int)
    return data


def load_generation_and_loss_rate(model: str) -> pd.DataFrame:
    csv_dir = ROOT / "RQ3/outputs" / model / "csv"
    loss_source = csv_dir / "RQ3_generation_loss_global_annual_evolution.csv"
    rate_source = csv_dir / "RQ3_generation_loss_rate_global_annual_evolution.csv"
    for source in (loss_source, rate_source):
        if not source.exists():
            raise FileNotFoundError(f"未找到年度损失数据：{source}")

    loss = pd.read_csv(loss_source)
    rate = pd.read_csv(rate_source)
    keys = ["scenario", "tech", "snapshot_year", "analysis_year"]
    require_columns(loss, set(keys + ["net_generation_loss_twh"]), loss_source)
    require_columns(rate, set(keys + ["loss_rate_pct"]), rate_source)

    data = loss[keys + ["net_generation_loss_twh"]].merge(
        rate[keys + ["loss_rate_pct"]],
        on=keys,
        how="inner",
        validate="one_to_one",
    )
    data = data[
        data["scenario"].isin(SSPS)
        & data["tech"].isin(TECH_LABELS)
        & data["analysis_year"].between(2030, 2059)
        & data["loss_rate_pct"].gt(0)
    ].copy()
    data["generation_twh"] = (
        data["net_generation_loss_twh"] / data["loss_rate_pct"] * 100.0
    )
    return data


def stable_rng(seed: int, tech: str, country_id: str) -> np.random.Generator:
    token = f"{seed}:{tech}:{country_id}".encode("utf-8")
    digest = hashlib.sha256(token).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def make_mock_map_data(
    shapefile: Path, tech: str, seed: int
) -> list[dict[str, object]]:
    if not shapefile.exists():
        raise FileNotFoundError(f"未找到国家边界文件：{shapefile}")

    records: list[dict[str, object]] = []
    for record in shapereader.Reader(shapefile).records():
        attrs = record.attributes
        if attrs.get("ADMIN") == "Antarctica":
            continue
        country_id = str(attrs.get("ADM0_A3") or attrs.get("ADMIN"))
        population = max(float(attrs.get("POP_EST") or 0.0), 50_000.0)
        rng = stable_rng(seed, tech, country_id)
        resource_factor = rng.lognormal(mean=0.0, sigma=0.38)
        tech_factor = 1.15 if tech == "solar" else 0.92
        generation = tech_factor * (population / 1e6) ** 0.72 * resource_factor
        loss_fraction = np.clip(rng.normal(0.045 if tech == "wind" else 0.035, 0.013), 0.008, 0.09)
        loss = generation * loss_fraction
        records.append(
            {
                "geometry": record.geometry,
                "generation_twh": float(generation),
                "loss_twh": float(loss),
                "lon": float(attrs.get("LABEL_X") or record.geometry.representative_point().x),
                "lat": float(attrs.get("LABEL_Y") or record.geometry.representative_point().y),
            }
        )
    return records


def panel_label(ax: mpl.axes.Axes, label: str, x: float = -0.06, y: float = 1.05) -> None:
    ax.text(
        x,
        y,
        label,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        fontweight="bold",
    )


def bubble_size(value: float, scale_value: float) -> float:
    return 5.0 + 105.0 * min(value / scale_value, 1.0)


def draw_map_panel(
    fig: mpl.figure.Figure,
    ax: mpl.axes.Axes,
    records: list[dict[str, object]],
    tech: str,
    label: str,
) -> None:
    color_ends = {
        "wind": ("#EFF5F8", "#265F7C"),
        "solar": ("#FFF5D9", "#B86222"),
    }
    cmap = LinearSegmentedColormap.from_list(f"{tech}_generation", color_ends[tech])
    generation = np.array([item["generation_twh"] for item in records], dtype=float)
    loss = np.array([item["loss_twh"] for item in records], dtype=float)
    norm = LogNorm(vmin=max(np.quantile(generation, 0.03), 0.02), vmax=np.quantile(generation, 0.98))
    loss_scale = float(np.quantile(loss, 0.95))

    ax.set_global()
    ax.set_facecolor("#F7FAFC")
    for item in records:
        ax.add_geometries(
            [item["geometry"]],
            crs=ccrs.PlateCarree(),
            facecolor=cmap(norm(float(item["generation_twh"]))),
            edgecolor="#FFFFFF",
            linewidth=0.22,
            zorder=1,
        )
    ax.scatter(
        [item["lon"] for item in records],
        [item["lat"] for item in records],
        s=[bubble_size(float(item["loss_twh"]), loss_scale) for item in records],
        transform=ccrs.PlateCarree(),
        facecolor="#CF4B43",
        edgecolor="#762721",
        linewidth=0.35,
        alpha=0.65,
        zorder=3,
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
    ax.set_title(f"{TECH_LABELS[tech]}发电量与绝对损失 · SSP1-2.6, 2050（模拟数据）", pad=6)
    panel_label(ax, label, x=-0.02, y=1.04)

    sm = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
    cbar = fig.colorbar(
        sm,
        ax=ax,
        orientation="horizontal",
        fraction=0.04,
        pad=0.035,
        shrink=0.58,
        aspect=30,
    )
    cbar.set_label("年发电量（TWh/年，log 色标）", labelpad=2)
    cbar.ax.tick_params(labelsize=6, length=2)
    cbar.outline.set_linewidth(0.5)

    legend_values = np.quantile(loss, [0.50, 0.75, 0.95])
    bubble_handles = [
        ax.scatter(
            [],
            [],
            s=bubble_size(float(value), loss_scale),
            facecolor="#CF4B43",
            edgecolor="#762721",
            linewidth=0.35,
            alpha=0.65,
            label=f"{value:.1f}",
        )
        for value in legend_values
    ]
    legend = ax.legend(
        handles=bubble_handles,
        title="绝对损失（TWh/年）",
        loc="lower left",
        bbox_to_anchor=(0.005, 0.02),
        handletextpad=0.7,
        labelspacing=0.7,
        borderaxespad=0,
    )
    legend.get_title().set_fontsize(6.5)


def draw_exposure_boxplot(
    ax: mpl.axes.Axes, exposure: pd.DataFrame, tech: str, label: str
) -> None:
    data: list[np.ndarray] = []
    positions: list[float] = []
    colors: list[str] = []
    for decade_index, decade in enumerate(DECADES):
        for ssp_index, ssp in enumerate(SSPS):
            values = exposure.loc[
                (exposure["tech"] == tech)
                & (exposure["decade"] == decade)
                & (exposure["ssp"] == ssp),
                "exposed_days_per_gw_year",
            ].dropna()
            if len(values) != 10:
                raise ValueError(
                    f"{tech}/{ssp}/{DECADE_LABELS[decade]} 应有 10 个年度值，实际为 {len(values)}。"
                )
            data.append(values.to_numpy(dtype=float))
            positions.append(decade_index * 4.0 + ssp_index)
            colors.append(SSP_COLORS[ssp])

    result = ax.boxplot(
        data,
        positions=positions,
        widths=0.72,
        patch_artist=True,
        showfliers=True,
        medianprops={"color": "#1A1A1A", "linewidth": 1.1},
        whiskerprops={"color": "#555555", "linewidth": 0.75},
        capprops={"color": "#555555", "linewidth": 0.75},
        boxprops={"edgecolor": "#555555", "linewidth": 0.7},
        flierprops={
            "marker": "o",
            "markersize": 2.1,
            "markerfacecolor": "#555555",
            "markeredgewidth": 0,
            "alpha": 0.65,
        },
    )
    for patch, color in zip(result["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.72)

    ax.set_xticks([1.0, 5.0, 9.0])
    ax.set_xticklabels([DECADE_LABELS[decade] for decade in DECADES])
    ax.set_xlim(-0.8, 10.8)
    ax.set_xlabel("年代")
    ax.set_ylabel("容量加权暴露时间\n（天/(GW·年)）")
    ax.set_title(f"{TECH_LABELS[tech]}极端事件暴露")
    ax.grid(axis="y", color="#D5D9DC", linewidth=0.5, alpha=0.8)
    panel_label(ax, label, x=-0.13, y=1.08)


def draw_trajectory(
    ax: mpl.axes.Axes, data: pd.DataFrame, tech: str, label: str
) -> mpl.axes.Axes:
    right = ax.twinx()
    right.spines["right"].set_visible(True)
    right.spines["right"].set_linewidth(0.75)

    for ssp in SSPS:
        annual = data[(data["tech"] == tech) & (data["scenario"] == ssp)].copy()
        if len(annual) != 30:
            raise ValueError(f"{tech}/{ssp} 应有 30 个年度值，实际为 {len(annual)}。")
        subset = (
            annual.groupby("snapshot_year", as_index=False)
            .agg(
                generation_twh=("generation_twh", "mean"),
                loss_rate_pct=("loss_rate_pct", "mean"),
            )
            .sort_values("snapshot_year")
        )
        if subset["snapshot_year"].tolist() != DECADES:
            raise ValueError(f"{tech}/{ssp} 年代数据不完整：{subset['snapshot_year'].tolist()}")
        ax.plot(
            subset["snapshot_year"],
            subset["generation_twh"],
            color=SSP_COLORS[ssp],
            linewidth=1.5,
            linestyle="-",
            marker="o",
            markersize=3.6,
            zorder=3,
        )
        right.plot(
            subset["snapshot_year"],
            subset["loss_rate_pct"],
            color=SSP_COLORS[ssp],
            linewidth=1.25,
            linestyle=(0, (3.0, 1.8)),
            marker="o",
            markersize=3.2,
            markerfacecolor="white",
            markeredgewidth=0.8,
            zorder=2,
        )

    ax.set_xlim(2028, 2052)
    ax.set_xticks(DECADES)
    ax.set_xticklabels([DECADE_LABELS[decade] for decade in DECADES])
    ax.set_xlabel("年代")
    ax.set_ylabel("总发电量（TWh/年）")
    right.set_ylabel("单位发电损失（%）")
    ax.set_title(f"{TECH_LABELS[tech]}发电与单位损失")
    ax.grid(axis="y", color="#D5D9DC", linewidth=0.5, alpha=0.8)
    ax.tick_params(axis="y", colors="#333333")
    right.tick_params(axis="y", colors="#666666")
    panel_label(ax, label, x=-0.13, y=1.08)
    return right


def make_figure(args: argparse.Namespace) -> Path:
    configure_style()
    exposure = load_exposure(args.model)
    trajectory = load_generation_and_loss_rate(args.model)
    wind_map = make_mock_map_data(args.map_shapefile, "wind", args.mock_seed)
    solar_map = make_mock_map_data(args.map_shapefile, "solar", args.mock_seed)

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

    draw_map_panel(fig, ax_a, wind_map, "wind", "a")
    draw_map_panel(fig, ax_b, solar_map, "solar", "b")
    draw_exposure_boxplot(ax_c, exposure, "wind", "c")
    draw_exposure_boxplot(ax_d, exposure, "solar", "d")
    draw_trajectory(ax_e, trajectory, "wind", "e")
    draw_trajectory(ax_f, trajectory, "solar", "f")

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

    metric_handles = [
        Line2D([0], [0], color="#333333", linewidth=1.5, linestyle="-", label="总发电量"),
        Line2D(
            [0],
            [0],
            color="#333333",
            linewidth=1.25,
            linestyle=(0, (3.0, 1.8)),
            label="单位发电损失",
        ),
    ]
    ax_e.legend(
        handles=metric_handles,
        loc="upper left",
        bbox_to_anchor=(0.0, 1.01),
        handlelength=2.3,
        borderaxespad=0,
    )

    fig.suptitle(
        "RQ1｜不同气候路径下，极端天气会造成多大的风光损失？",
        fontsize=13,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.5,
        0.025,
        (
            "a–b，国家填色表示年发电量、圆面积表示绝对损失（模拟数据）；"
            "c–d，箱体为各年代 10 个年度值（n=10，中位数、四分位距与 1.5×IQR）；"
            "e–f，各点为年代内 10 年均值，单位发电损失=净出力损失/全年应发电量。"
        ),
        ha="center",
        fontsize=6.5,
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
