"""
对比 era5land 两种海陆判定下，哪些场站落在「海上区域」。

2×2 四个子图（默认 2050 年 ssp126 全部场站），均基于 era5land 数据，用两种方式判定海陆：
    ┌───────────────────────┬───────────────────────┐
    │ 风电 — era5land lsm   │ 光伏 — era5land lsm   │  ← 上排：data/era5land/lsm_0.1x0.1.nc，lsm<0.5=海
    ├───────────────────────┼───────────────────────┤
    │ 风电 — era5land u10   │ 光伏 — era5land u10   │  ← 下排：data/era5land/u10_2020_01.nc，u10=NaN=海
    └───────────────────────┴───────────────────────┘
    左列=风电，右列=光伏；上=era5land lsm 阈值判定，下=era5land u10 缺测（NaN）判定。

每个子图中：
    - 落在海上区域的场站 → 红色
    - 不在海上区域（陆地）的场站 → 灰色

只画 2050 年的场站（CSV 的 year=2050 即累积到 2050 的全部场站，不区分建设年份）。

两种判定说明：
    - lsm：era5land 连续值 0~1（0=海 1=陆，海岸带为中间值），用 lsm<阈值 判海。
    - u10：era5land 是陆地再分析，海洋网格为 NaN，故 np.isnan(u10) 即天然海陆掩码
      （无阈值，对应 era5land 官方陆地覆盖）。仅取第一个时刻。

用法:
    python plot_stations_S0E1_sea_mask.py [--ssp ssp126] [--stations <场站.csv>]

经度坐标说明（两套坐标系，绘图时各自归一化）：
    - 场站 CSV            : lon ∈ [-180, 180]
    - era5land lsm / u10  : lon ∈ [0, 360]   （查表前 lon % 360）
"""

import os
import csv
import argparse
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "plot_stations", os.path.splitext(os.path.basename(__file__))[0])

# era5land 海陆掩码（0.1°，经度 0~360，纬度 90→-90，lsm: 0=海 1=陆）
ERA5LAND_LSM_NC = os.path.join(PROJECT_ROOT, "data", "era5land", "lsm_0.1x0.1.nc")
# era5land 10m 纬向风（0.1°，经度 0~360；era5land 陆地再分析，海洋网格为 NaN）
ERA5LAND_U10_NC = os.path.join(PROJECT_ROOT, "data", "era5land", "u10_2020_01.nc")

# 场站选址结果根目录
STATIONS_DIR = os.path.join(PROJECT_ROOT, "data", "stations")
# ssp 代号 → 场站 CSV 文件名
SSP_STATION_FILE = {
    "ssp126": "stations_SSP1-2.6.csv",
    "ssp245": "stations_SSP2-4.5.csv",
    "ssp585": "stations_SSP5-6.0.csv",
}

YEAR = 2050  # 只画 2050 年（即累积到 2050 的全部场站）

# era5land lsm 的「海洋」判定阈值：lsm < 阈值 视为海上（lsm 0~1 连续值，海岸带为中间值）
LSM_OCEAN_THRESHOLD = 0.5

PC = ccrs.PlateCarree()

# 配色：海上=红，陆地=灰
COLOR_SEA = "#d62728"  # 红
COLOR_LAND = "#9aa0a6"  # 灰

# ══════════════════════════════════════════════════════════════════════
# 字体
# ══════════════════════════════════════════════════════════════════════

font_path = os.path.join(PROJECT_ROOT, "data", "SourceHanSansSC-Normal.otf")
if os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    font_name = fm.FontProperties(fname=font_path).get_name()
    plt.rcParams["font.family"] = [font_name]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"figure.dpi": 120, "font.size": 10})


# ══════════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════════


def load_stations_2050(csv_path):
    """读取场站 CSV，仅保留 YEAR=2050 的行（即累积到 2050 的全部场站）。

    返回 {'solar': (lon, lat), 'wind': (lon, lat)}，经度为 CSV 原始 [-180,180]。
    """
    data = {"solar": [[], []], "wind": [[], []]}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if int(row["year"]) != YEAR:
                continue
            typ = row["type"]
            if typ not in data:
                continue
            data[typ][0].append(float(row["lon"]))
            data[typ][1].append(float(row["lat"]))
    return {t: (np.array(v[0]), np.array(v[1])) for t, v in data.items()}


# ══════════════════════════════════════════════════════════════════════
# 海陆掩码判定（era5land 0.1° 网格）
# ══════════════════════════════════════════════════════════════════════


def load_era5land_grid(nc_path, var, time_dim="time"):
    """读取 era5land 变量的第一个时刻，返回 2D 数组。

    行=纬度(降序 90→-90)，列=经度(升序 0→359.9)。
    era5land 的 lsm 文件时间维名为 'time'，u10 文件为 'valid_time'，按需传入。
    """
    import xarray as xr

    ds = xr.open_dataset(nc_path)
    if time_dim in ds[var].dims:
        grid = ds[var].isel({time_dim: 0}).values
    else:
        grid = ds[var].values
    ds.close()
    return np.asarray(grid)


def era5land_lookup(lon, lat, grid):
    """era5land 0.1° 网格向量化查表，返回每个 (lon,lat) 的网格值。

    lon 输入为 [-180,180]，grid 行=纬度(降序 90→-90)、列=经度(升序 0→360)。
    纬度按 (90-lat)/0.1 取行索引；经度先 lon%360 再按 lon/0.1 取列索引。
    """
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    nlat, nlon = grid.shape

    lon360 = lon % 360.0  # [-180,180] → [0,360)
    ilat = np.clip(np.rint((90.0 - lat) / 0.1).astype(int), 0, nlat - 1)
    ilon = np.clip(np.rint(lon360 / 0.1).astype(int), 0, nlon - 1)
    return grid[ilat, ilon]


def is_ocean_lsm(lon, lat, lsm, threshold=LSM_OCEAN_THRESHOLD):
    """era5land lsm 阈值判定：lsm < 阈值 → 海上（True）。"""
    return era5land_lookup(lon, lat, lsm) < threshold


def is_ocean_u10(lon, lat, u10):
    """era5land u10 缺测判定：u10 为 NaN（海洋无数据）→ 海上（True）。"""
    return np.isnan(era5land_lookup(lon, lat, u10))


# ══════════════════════════════════════════════════════════════════════
# 绘图
# ══════════════════════════════════════════════════════════════════════


def setup_basemap(ax):
    ax.set_global()
    ax.add_feature(cfeature.LAND, color="#f5f5f0", zorder=0)
    ax.add_feature(cfeature.OCEAN, color="#d1e8f0", zorder=0)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, color="#888", zorder=1)
    ax.gridlines(linewidth=0.3, color="gray", alpha=0.4)


def plot_sea_mask(ax, lon, lat, is_sea, tech_label, mask_label):
    """在单个子图上绘制场站：海上=红，陆地=灰。返回 (n_sea, n_total)。"""
    setup_basemap(ax)

    n_total = len(lon)
    n_sea = int(np.sum(is_sea))
    sea_pct = (n_sea / n_total * 100) if n_total else 0.0
    n_land = n_total - n_sea
    land_pct = 100.0 - sea_pct

    # 陆地（灰）先画在下层，海上（红）画在上层使其突出
    if n_land:
        ax.scatter(
            lon[~is_sea],
            lat[~is_sea],
            s=1.5,
            c=COLOR_LAND,
            transform=PC,
            rasterized=True,
            zorder=3,
            label=f"陆地 {n_land:,} ({land_pct:.2f}%)",
        )
    if n_sea:
        ax.scatter(
            lon[is_sea],
            lat[is_sea],
            s=6,
            c=COLOR_SEA,
            transform=PC,
            rasterized=True,
            zorder=4,
            label=f"海上 {n_sea:,} ({sea_pct:.2f}%)",
        )

    ax.legend(loc="lower left", fontsize=9, markerscale=4, framealpha=0.9, edgecolor="#888")
    ax.set_title(f"{tech_label} — {mask_label}", fontsize=12, pad=6)
    return n_sea, n_total


def plot_2x2(stations, out_path, ssp):
    """2×2 子图：行=掩码(lsm/u10)，列=技术(风电/光伏)，均来自 era5land。"""
    lsm = load_era5land_grid(ERA5LAND_LSM_NC, "lsm", time_dim="time")
    u10 = load_era5land_grid(ERA5LAND_U10_NC, "u10", time_dim="valid_time")

    fig, axes = plt.subplots(2, 2, figsize=(20, 14), subplot_kw={"projection": PC})

    wlon, wlat = stations["wind"]
    slon, slat = stations["solar"]
    panels = [
        # (行, 列, 技术, 掩码标签, is_ocean 数组)
        (0, 0, "风电", "era5land lsm（阈值判定）", is_ocean_lsm(wlon, wlat, lsm)),
        (0, 1, "光伏", "era5land lsm（阈值判定）", is_ocean_lsm(slon, slat, lsm)),
        (1, 0, "风电", "era5land u10（缺测判定）", is_ocean_u10(wlon, wlat, u10)),
        (1, 1, "光伏", "era5land u10（缺测判定）", is_ocean_u10(slon, slat, u10)),
    ]

    stats = []
    for r, c, tech, mask, is_sea in panels:
        lon = wlon if tech == "风电" else slon
        lat = wlat if tech == "风电" else slat
        n_sea, n_total = plot_sea_mask(axes[r, c], lon, lat, is_sea, tech, mask)
        stats.append((mask, tech, n_sea, n_total))

    fig.text(
        0.5,
        0.965,
        f"{ssp} · {YEAR} 年场站 era5land 两种海陆判定对比（红=海上，灰=陆地）",
        ha="center",
        fontsize=15,
        weight="bold",
    )

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")
    return stats


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


def report_stats(stats, ssp, out_path):
    """打印并保存两种判定下海上场站数量与占比。"""
    print(f"\n  {YEAR} 年场站落在海上区域的比例（{ssp}）")
    print(f"  {'判定方式':<28}{'技术':<6}{'海上':>9}{'总数':>10}{'占比':>9}")
    print("  " + "-" * 62)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mask", "tech", "n_sea", "n_total", "sea_ratio"])
        for mask, tech, n_sea, n_total in stats:
            ratio = (n_sea / n_total) if n_total else 0.0
            print(f"  {mask:<26}{tech:<6}{n_sea:>9,}{n_total:>10,}{ratio:>8.2%}")
            writer.writerow([mask, tech, n_sea, n_total, f"{ratio:.4f}"])
    print(f"  -> {out_path}")


# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="对比 era5land lsm 与 u10 两种海陆判定下海上场站分布")
    parser.add_argument("--ssp", default="ssp126", choices=list(SSP_STATION_FILE), help="情景（默认 ssp126）")
    parser.add_argument("--stations", default=None, help="场站 CSV 路径（默认按 --ssp 取 data/stations/）")
    args = parser.parse_args()

    ssp = args.ssp
    csv_path = args.stations or os.path.join(STATIONS_DIR, SSP_STATION_FILE[ssp])
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"场站 CSV 不存在：{csv_path}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"{'=' * 60}\n  era5land 海陆判定海上场站对比：{ssp}\n  stations: {csv_path}\n{'=' * 60}")

    stations = load_stations_2050(csv_path)
    for t in ("wind", "solar"):
        print(f"  {YEAR} 年 {t}: {len(stations[t][0]):,} 个场站")

    stats = plot_2x2(stations, os.path.join(OUTPUT_DIR, f"stations_sea_mask_{ssp}_{YEAR}.png"), ssp)
    report_stats(stats, ssp, os.path.join(OUTPUT_DIR, f"stats_sea_mask_{ssp}_{YEAR}.csv"))


if __name__ == "__main__":
    main()
