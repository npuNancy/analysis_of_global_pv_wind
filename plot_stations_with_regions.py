"""
用 cartopy 画出
1. 本项目所用各区域的范围：
  1.1 AREA_DICT 里的各个国家，画其经纬度边界框
  2.2 NAM-12 区域 —— rotated-pole 网格，画其真实的弯曲域边界

2. 所有风光场站的站点位置：
    - 区分风电和光伏
    - 区分不同年份

3. 统计有多少场站落在上述区域内：
    - 区分风光、区分不同年份
    - 打印绝对值和比例

用法:
    python plot_regions_stations.py --stations <场站选址结果.csv> [--ssp ssp126]

场站选址结果 CSV 列：year,type,lon,lat,capacity_gw
其中 year 为场站建设时间（2030 即 2030；2030+2040 记为 2040；2030+2040+2050 记为 2050），
lon ∈ [-180, 180]，lat ∈ [-90, 90]。
"""

import os
import re
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
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "plot_regions_stations")
NAM_GRID_NC = os.path.join(BASE_DIR, "data", "NAM-12_grid.nc")

# NAM-12 rotated-pole 网格参数（硬编码，取自 data/NAM-12_grid.nc 的 crs）
NAM_POLE_LON = 83.0
NAM_POLE_LAT = 42.5

YEARS = [2050, 2040, 2030]  # 由远及近绘制，使早期年份叠在上层
YEAR_COLORS = {2030: "#c501ff", 2040: "#00ffc5", 2050: "#d48a8b"}

# Key: [北纬N, lonW, 南纬S, lonE]；经度统一使用 [0,360)（可用 lonW>lonE 表示跨 0° 经线）
AREA_DICT: dict[str, list[float]] = {
    # "global": [90, 0, -90, 360],
    # "Canada": [83.1, 219.0, 41.7, 307.4],
    # "Tibetan Plateau": [30, 119, 28, 120],
    "China": [54.95, 70.05, 15.05, 139.95],
    "Japan": [45.5, 122.9, 24.2, 145.8],
    "South Korea": [38.6, 124.6, 33.2, 130.9],
    "India": [37, 68, 6, 98],
    "Turkey": [42.1, 25.7, 35.8, 44.8],
    "Vietnam": [23.4, 102.1, 8.6, 109.5],
    "Germany": [55, 5, 47, 15],
    "Italy": [48, 6, 36, 19],
    "Spain": [44, 350, 35, 5],
    "France": [51.1, 354.9, 41.3, 9.6],
    "United Kingdom": [60.9, 351.4, 50.0, 1.8],
    "Poland": [54.8, 14.1, 49.0, 24.2],
    "Greece": [41.8, 19.4, 34.8, 28.2],
    "Sweden": [69.1, 11.1, 55.3, 24.2],
    "Denmark": [57.8, 8.1, 54.6, 15.2],
    "Portugal": [42.2, 328.7, 37.0, 353.8],
    "Netherlands": [53.6, 3.4, 50.8, 7.2],
    "Ireland": [55.4, 349.5, 51.4, 354.0],
    "Romania": [48.3, 20.3, 43.7, 29.7],
    "Ukraine": [52.4, 22.2, 44.4, 40.2],
    "Austria": [49.0, 9.5, 46.4, 17.2],
    "México": [32.7, 241.6, 14.5, 273.3],
    "Brazil": [5.3, 286.0, -33.8, 325.3],
    "Chile": [-17.5, 283.5, -55.9, 293.6],  # 实际上 BCSD 的智利经度是 250.5-293.6
    "South Africa": [-22.1, 16.3, -28.3, 32.9],
    "Egypt": [31.7, 24.7, 22.0, 36.9],
    "Australia": [-9.1, 112.9, -43.6, 153.6],
}

# ══════════════════════════════════════════════════════════════════════
# 字体
# ══════════════════════════════════════════════════════════════════════

font_path = "/data4/yanxiaokai/SourceHanSansSC-Normal.otf"
if os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    font_name = fm.FontProperties(fname=font_path).get_name()
    plt.rcParams["font.family"] = [font_name]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"figure.dpi": 120, "font.size": 10})


# ══════════════════════════════════════════════════════════════════════
# 区域几何
# ══════════════════════════════════════════════════════════════════════

NAM_CRS = ccrs.RotatedPole(pole_longitude=NAM_POLE_LON, pole_latitude=NAM_POLE_LAT)
PC = ccrs.PlateCarree()


def to180(lon):
    """经度归一化到 [-180, 180)。"""
    return ((np.asarray(lon, dtype=float) + 180.0) % 360.0) - 180.0


def bbox_edges_180(north, lon_w, south, lon_e, n=50):
    """返回边界框四条边的折线坐标 (lons, lats)，经度转为连续的 [-180,180]。

    AREA_DICT 中跨 0° 经线（lon_w>lon_e）的框，归一化后 w<=e 仍连续，可直接绘制。
    """
    w, e = float(to180(lon_w)), float(to180(lon_e))
    if w > e:  # 真正跨 180° 经线（AREA_DICT 实际不出现）——退化为连续直绘
        e += 360.0
    lons = np.concatenate([
        np.linspace(w, e, n), np.full(n, e),
        np.linspace(e, w, n), np.full(n, w),
    ])
    lats = np.concatenate([
        np.full(n, north), np.linspace(north, south, n),
        np.full(n, south), np.linspace(south, north, n),
    ])
    return lons, lats


def point_in_bbox(lon, lat, bbox):
    """点是否落在 AREA_DICT 边界框内。lon/lat 为数组，bbox=[N,lonW,S,lonE]（0-360）。"""
    north, lon_w, south, lon_e = bbox
    lon360 = np.asarray(lon, dtype=float) % 360.0
    in_lat = (lat <= north) & (lat >= south)
    if lon_w <= lon_e:
        in_lon = (lon360 >= lon_w) & (lon360 <= lon_e)
    else:  # 跨 0° 经线
        in_lon = (lon360 >= lon_w) | (lon360 <= lon_e)
    return in_lat & in_lon


def load_nam_domain():
    """读取 NAM-12 网格，返回 (rlon_min, rlon_max, rlat_min, rlat_max)。"""
    import xarray as xr

    ds = xr.open_dataset(NAM_GRID_NC)
    rlon, rlat = ds["rlon"].values, ds["rlat"].values
    return float(rlon.min()), float(rlon.max()), float(rlat.min()), float(rlat.max())


def nam_boundary_rotated(domain, n=200):
    """沿 NAM-12 域（rlon×rlat 矩形）周界采样，返回 rotated-pole 坐标 (rlons, rlats)。

    以 transform=NAM_CRS 绘制时，cartopy 自动渲染为真实的弯曲域边界并正确处理跨经线。
    """
    rlon0, rlon1, rlat0, rlat1 = domain
    rlons = np.concatenate([
        np.linspace(rlon0, rlon1, n), np.full(n, rlon1),
        np.linspace(rlon1, rlon0, n), np.full(n, rlon0),
    ])
    rlats = np.concatenate([
        np.full(n, rlat0), np.linspace(rlat0, rlat1, n),
        np.full(n, rlat1), np.linspace(rlat1, rlat0, n),
    ])
    return rlons, rlats


def point_in_nam(lon, lat, domain):
    """点是否落在 NAM-12 弯曲域内：转到 rotated-pole 坐标后判断矩形范围。"""
    rlon0, rlon1, rlat0, rlat1 = domain
    pts = NAM_CRS.transform_points(PC, np.asarray(lon, float), np.asarray(lat, float))
    rlon, rlat = pts[:, 0], pts[:, 1]
    return (rlon >= rlon0) & (rlon <= rlon1) & (rlat >= rlat0) & (rlat <= rlat1)


# ══════════════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════════════


def load_stations(csv_path):
    """读取场站选址结果 CSV，返回 {year: {'solar': (lon,lat), 'wind': (lon,lat)}}。"""
    data = {y: {"solar": [[], []], "wind": [[], []]} for y in YEARS}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            year = int(row["year"])
            typ = row["type"]
            if year not in data or typ not in data[year]:
                continue
            data[year][typ][0].append(float(row["lon"]))
            data[year][typ][1].append(float(row["lat"]))
    return {
        y: {t: (np.array(v[0]), np.array(v[1])) for t, v in d.items()}
        for y, d in data.items()
    }


def in_any_region(lon, lat, domain):
    """点是否落在任一 AREA_DICT 框或 NAM-12 域内。"""
    if len(lon) == 0:
        return np.zeros(0, dtype=bool)
    mask = point_in_nam(lon, lat, domain)
    for bbox in AREA_DICT.values():
        mask = mask | point_in_bbox(lon, lat, bbox)
    return mask


# ══════════════════════════════════════════════════════════════════════
# 绘图
# ══════════════════════════════════════════════════════════════════════


def setup_basemap(ax):
    ax.set_global()
    ax.add_feature(cfeature.LAND, color="#f5f5f0", zorder=0)
    ax.add_feature(cfeature.OCEAN, color="#d1e8f0", zorder=0)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, color="#888", zorder=1)
    ax.add_feature(cfeature.BORDERS, linewidth=0.25, color="#aaa", zorder=1)
    ax.gridlines(linewidth=0.3, color="gray", alpha=0.4)


def draw_regions(ax, domain, label=False):
    """在 ax 上绘制所有 AREA_DICT 边界框与 NAM-12 弯曲域。"""
    for name, bbox in AREA_DICT.items():
        north, lon_w, south, lon_e = bbox
        lons, lats = bbox_edges_180(north, lon_w, south, lon_e)
        ax.plot(lons, lats, transform=PC, color="#d62728", lw=1.0, zorder=4)
        if label:
            e = lon_e if lon_e >= lon_w else lon_e + 360
            cx = float(to180((lon_w + e) / 2.0))
            ax.text(cx, (north + south) / 2.0, name, transform=PC, fontsize=6,
                    ha="center", va="center", color="#7a0000", zorder=5)

    rlons, rlats = nam_boundary_rotated(domain)
    ax.plot(rlons, rlats, transform=NAM_CRS, color="#1f77b4", lw=1.6, zorder=4)
    if label:
        rlon0, rlon1, rlat0, rlat1 = domain
        ax.text((rlon0 + rlon1) / 2, (rlat0 + rlat1) / 2, "NAM-12", transform=NAM_CRS,
                fontsize=8, ha="center", va="center", color="#0b3d61", zorder=5)


def plot_regions_map(ssp, domain, out_path):
    """图1：项目所用全部区域范围。"""
    fig = plt.figure(figsize=(16, 9))
    ax = plt.axes(projection=PC)
    setup_basemap(ax)
    draw_regions(ax, domain, label=True)
    ax.plot([], [], color="#d62728", lw=1.2, label="AREA_DICT 国家边界框")
    ax.plot([], [], color="#1f77b4", lw=1.6, label="NAM-12 弯曲域")
    ax.legend(loc="lower left", fontsize=10, framealpha=0.9, edgecolor="#888")
    ax.set_title(f"项目区域范围（{ssp}）：AREA_DICT 国家 + NAM-12", fontsize=14, pad=10)
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")


def plot_stations_map(ssp, stations, domain, out_path):
    """图2：场站位置（上=光伏，下=风电），按年份着色，叠加区域边界。"""
    fig, (ax_s, ax_w) = plt.subplots(
        2, 1, figsize=(16, 16), subplot_kw={"projection": PC}
    )
    for ax, typ, title in [
        (ax_s, "solar", f"{ssp} — 光伏场站选址"),
        (ax_w, "wind", f"{ssp} — 风电场站选址"),
    ]:
        setup_basemap(ax)
        draw_regions(ax, domain, label=False)
        for year in YEARS:
            lon, lat = stations[year][typ]
            ax.scatter(lon, lat, s=3, c=YEAR_COLORS[year], transform=PC,
                       label=f"{year} ({len(lon):,})", rasterized=True, zorder=3)
        ax.plot([], [], color="#d62728", lw=1.0, label="AREA_DICT")
        ax.plot([], [], color="#1f77b4", lw=1.6, label="NAM-12")
        ax.legend(loc="lower left", fontsize=10, markerscale=4,
                  framealpha=0.9, edgecolor="#888")
        ax.set_title(title, fontsize=14, pad=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


def compute_stats(stations, domain):
    """统计每个 (year,type) 的场站总数、区域内数量与比例。"""
    rows = []
    for year in sorted(stations):
        for typ in ("solar", "wind"):
            lon, lat = stations[year][typ]
            total = len(lon)
            inside = int(in_any_region(lon, lat, domain).sum()) if total else 0
            ratio = inside / total if total else 0.0
            rows.append((year, typ, total, inside, ratio))
    return rows


def report_stats(ssp, rows, out_path):
    """打印并保存统计结果。"""
    print(f"\n  场站落在项目区域内的统计（{ssp}）")
    print(f"  {'year':<6}{'type':<8}{'total':>8}{'inside':>8}{'ratio':>9}")
    print("  " + "-" * 39)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "type", "total", "inside_region", "ratio"])
        for year, typ, total, inside, ratio in rows:
            print(f"  {year:<6}{typ:<8}{total:>8,}{inside:>8,}{ratio:>8.1%}")
            writer.writerow([year, typ, total, inside, f"{ratio:.4f}"])
        tot = sum(r[2] for r in rows)
        ins = sum(r[3] for r in rows)
        print("  " + "-" * 39)
        print(f"  {'ALL':<6}{'':<8}{tot:>8,}{ins:>8,}{(ins / tot if tot else 0):>8.1%}")
        writer.writerow(["ALL", "", tot, ins, f"{(ins / tot if tot else 0):.4f}"])
    print(f"  -> {out_path}")


# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════


def derive_ssp(stations_path, explicit):
    if explicit:
        return explicit
    m = re.search(r"ssp\d{3}", stations_path, re.IGNORECASE)
    if m:
        return m.group(0).lower()
    return os.path.splitext(os.path.basename(stations_path))[0]


def main():
    parser = argparse.ArgumentParser(description="项目区域范围与风光场站可视化/统计")
    parser.add_argument("--stations", required=True, help="场站选址结果 CSV（year,type,lon,lat,...）")
    parser.add_argument("--ssp", default=None, help="情景标识，用于输出文件名（默认从路径推断，如 ssp126）")
    args = parser.parse_args()

    ssp = derive_ssp(args.stations, args.ssp)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"{'=' * 60}\n  区域 & 场站可视化：{ssp}\n  stations: {args.stations}\n{'=' * 60}")

    domain = load_nam_domain()
    stations = load_stations(args.stations)

    plot_regions_map(ssp, domain, os.path.join(OUTPUT_DIR, f"regions_{ssp}.png"))
    plot_stations_map(ssp, stations, domain, os.path.join(OUTPUT_DIR, f"stations_{ssp}.png"))

    rows = compute_stats(stations, domain)
    report_stats(ssp, rows, os.path.join(OUTPUT_DIR, f"stats_in_regions_{ssp}.csv"))


if __name__ == "__main__":
    main()
