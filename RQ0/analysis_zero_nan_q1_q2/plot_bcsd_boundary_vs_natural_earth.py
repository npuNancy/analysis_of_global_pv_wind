#!/usr/bin/env python3
"""逐国家对比 BCSD 有效值边界与 Natural Earth 国界。

每个国家输出一张 PNG，包含：
  1. Natural Earth admin-0 国界；
  2. BCSD 文件的完整 lat/lon 网格外框；
  3. 指定变量在指定 time index 上的有效值边界（非 NaN 且非 0）。

默认只读取 time=0 的一个时间片。这里关注空间有效域，避免为画边界读取完整
2015-2060 时间序列。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import xarray as xr

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle

import cartopy.crs as ccrs
import cartopy.feature as cfeature


THIS_DIR = Path(__file__).resolve().parent
RQ0_DIR = THIS_DIR.parent
PROJECT_ROOT = RQ0_DIR.parent
sys.path.insert(0, str(RQ0_DIR))

import plot_stations_S0E2_zero_or_nan as P  # noqa: E402
from natural_earth_regions import DEFAULT_NE_SHP, load_target_country_shapes  # noqa: E402


PC = ccrs.PlateCarree()


def parse_args():
    parser = argparse.ArgumentParser(description="逐国家绘制 BCSD 有效边界 vs Natural Earth 国界")
    parser.add_argument("--model", default=P.MODEL, help=f"CMIP6 模式，默认 {P.MODEL}")
    parser.add_argument("--ssp", default=P.SSP, choices=list(P.SSP_STATION_FILE), help=f"情景，默认 {P.SSP}")
    parser.add_argument("--year", type=int, default=P.YEAR, help=f"年份，仅用于选文件，默认 {P.YEAR}")
    parser.add_argument("--variable", default="rsds", choices=["uas", "vas", "tas", "rsds", "pr"], help="用于画有效值边界的 BCSD 变量")
    parser.add_argument("--time-index", type=int, default=0, help="读取的 time index，默认 0")
    parser.add_argument("--countries", nargs="*", default=None, help="可选，只画指定国家；默认画 26 国")
    parser.add_argument(
        "--out-dir",
        default=str(THIS_DIR / "outputs" / "bcsd_boundary_vs_natural_earth"),
        help="输出目录",
    )
    return parser.parse_args()


def lon_to_180(lon):
    return ((np.asarray(lon, dtype=float) + 180.0) % 360.0) - 180.0


def country_to_safe_name(country):
    return P.area_to_dir(country).replace("México", "Mexico")


def setup_font():
    font_path = PROJECT_ROOT / "data" / "SourceHanSansSC-Normal.otf"
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = [fm.FontProperties(fname=str(font_path)).get_name()]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams.update({"figure.dpi": 120, "font.size": 10})


def read_bcsd_slice(country, variable, model, ssp, year, time_index):
    path = P.met_path(country, variable, model, ssp, year)
    if not path or not os.path.isfile(path):
        return None

    data_var = f"{variable}_bcsd"
    with xr.open_dataset(path) as ds:
        if data_var not in ds:
            return None
        da = ds[data_var].isel(time=time_index)
        grid = np.asarray(da.values)
        lat = np.asarray(da["lat"].values)
        lon = np.asarray(da["lon"].values)

    lon180 = lon_to_180(lon)
    order = np.argsort(lon180)
    return {
        "path": path,
        "grid": grid[:, order],
        "lat": lat,
        "lon": lon180[order],
    }


def geom_bounds(geom):
    minx, miny, maxx, maxy = geom.bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def draw_bcsd_grid_bbox(ax, lon, lat, **kwargs):
    x0, x1 = float(np.nanmin(lon)), float(np.nanmax(lon))
    y0, y1 = float(np.nanmin(lat)), float(np.nanmax(lat))
    rect = Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, transform=PC, **kwargs)
    ax.add_patch(rect)
    return x0, y0, x1, y1


def plot_one(country, geom, bcsd, variable, model, ssp, out_path):
    fig = plt.figure(figsize=(8, 8))
    ax = plt.axes(projection=PC)
    ax.add_feature(cfeature.LAND, color="#f5f5f0", zorder=0)
    ax.add_feature(cfeature.OCEAN, color="#d1e8f0", zorder=0)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, color="#888", zorder=1)
    ax.add_feature(cfeature.BORDERS, linewidth=0.25, color="#aaa", zorder=1)
    ax.gridlines(linewidth=0.25, color="gray", alpha=0.4)

    ax.add_geometries([geom], crs=PC, facecolor="none", edgecolor="#1b7837", linewidth=1.8, zorder=5)

    lon = bcsd["lon"]
    lat = bcsd["lat"]
    grid = bcsd["grid"]
    x0, y0, x1, y1 = draw_bcsd_grid_bbox(ax, lon, lat, edgecolor="#2166ac", linewidth=1.2, linestyle="--", zorder=4)

    valid = np.isfinite(grid) & (grid != 0)
    n_valid = int(valid.sum())
    n_total = int(valid.size)
    valid_ratio = n_valid / n_total if n_total else 0.0
    if valid.any() and (~valid).any():
        ax.contour(lon, lat, valid.astype(np.uint8), levels=[0.5], colors=["#d73027"], linewidths=1.4, transform=PC, zorder=6)
    elif valid.any():
        draw_bcsd_grid_bbox(ax, lon, lat, edgecolor="#d73027", linewidth=1.4, linestyle="-", zorder=6)

    gx0, gy0, gx1, gy1 = geom_bounds(geom)
    xmin = min(gx0, x0) - 1.0
    xmax = max(gx1, x1) + 1.0
    ymin = min(gy0, y0) - 1.0
    ymax = max(gy1, y1) + 1.0
    ax.set_extent([xmin, xmax, ymin, ymax], crs=PC)

    ax.plot([], [], color="#1b7837", lw=1.8, label="Natural Earth 国界")
    ax.plot([], [], color="#2166ac", lw=1.2, ls="--", label="BCSD lat/lon 网格外框")
    ax.plot([], [], color="#d73027", lw=1.4, label=f"BCSD {variable} 有效值边界")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.9)

    ax.set_title(
        f"{country} · {model} {ssp} · BCSD {variable} 有效边界 vs Natural Earth\n"
        f"valid grid cells: {n_valid:,}/{n_total:,} ({valid_ratio:.1%})",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    setup_font()

    countries = args.countries or P.COUNTRIES_26
    out_dir = Path(args.out_dir) / args.model / args.ssp / args.variable
    out_dir.mkdir(parents=True, exist_ok=True)

    records = load_target_country_shapes(DEFAULT_NE_SHP, tuple(countries))
    geoms = {rec["name"]: rec["geom"] for rec in records}

    print(f"输出目录: {out_dir}")
    for country in countries:
        geom = geoms.get(country)
        if geom is None:
            print(f"[SKIP] Natural Earth 未匹配: {country}")
            continue
        bcsd = read_bcsd_slice(country, args.variable, args.model, args.ssp, args.year, args.time_index)
        if bcsd is None:
            print(f"[SKIP] BCSD 文件缺失或变量不存在: {country}")
            continue
        out_path = out_dir / f"{country_to_safe_name(country)}__{args.model}__{args.ssp}__{args.variable}.png"
        plot_one(country, geom, bcsd, args.variable, args.model, args.ssp, out_path)
        print(f"-> {out_path}")


if __name__ == "__main__":
    main()
