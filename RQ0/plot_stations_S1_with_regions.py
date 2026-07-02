"""
项目区域范围 / 风光场站 / CF=0-or-nan 场站 的可视化与统计（cartopy）。

对单个 SSP 的场站选址结果（--stations CSV），写入 outputs/plot_stations/plot_stations_S1_with_regions/，
产出如下文件：

【图】
1. regions_{ssp}.png
   项目所用区域范围 = 20 大区（UN M49）边界 + AREA_DICT 各国经纬度矩形框 + NAM-12 弯曲域。
   均为"项目自有的边界定义"（矩形 bbox / rotated 矩形），并非真实国界。

2. stations_{ssp}.png
   全部风光场站位置（上=光伏 / 下=风电），按建设年份 2030/2040/2050 着色，叠加 1 的区域边界。

3. zero_cf_stations_{ssp}.png
   零出力（CF=0）场站图，来自场站出力 NC（data/wind_solar_output）：以 2050 年出力算年 CF，
   CF==0 的场站合并所有年份单色绘制，图例标注占 2050 全部场站的比例。
   注：此图只识别 CF==0，不识别 CF==nan（出力 NC 中 CF=nan 的场站年化后仍为 nan，被判 !=0）。

4. cf_zero_nan_ne_border_{ssp}.png   ★ natural-earth 精确国界口径（新增）
   以 natural-earth 矢量国界（ne_110m_admin_0_countries）为口径，绘制：
     - 各国精确国界（绿色描边）
     - 气象数据边界：AREA_DICT 矩形框（红）+ NAM-12 弯曲域（蓝），与精确国界同框对照
     - CF=0 或 nan 的场站（红点） vs 正常场站（灰点）
   CF=0/nan 判定取自容量因子数据 data/cfs（2050 年均），与 plot_stations_S0E2_zero_or_nan.py 同口径。
   图例标注：精确国界内 CF=0/nan 场站数 / 精确国界内全部场站数（比例）。

【CSV 统计】
- stats_in_regions_{ssp}.csv：场站数 / 装机量 落在 AREA_DICT+NAM 区域内的数量与比例（按年份、风光）
- stats_by_macro_region_{ssp}.csv：20 大区维度的场站数 / 装机量 与项目区域覆盖比例
- stats_cf_zero_nan_by_country_{ssp}.csv：★ 各 natural-earth 精确国界内 CF=0/nan 场站数与比例（按风光）

边界口径说明（重要）：
- AREA_DICT（矩形 bbox）：项目气象数据 BCSD 的国家矩形定义，粗糙（含邻国领土 / 领海）。
- natural-earth（精确国界）：真实国界，与出力计算 / 极端天气识别的国家归属口径一致。
- 本脚本把两种口径同框呈现，便于直观对比 bbox 与真实国界的偏差。

用法:
    python plot_stations_S1_with_regions.py --stations <场站选址结果.csv> [--ssp ssp126]
        [--draw-macro-regions] [--nc-output-dir <出力NC根目录>]

场站选址结果 CSV 列：year,type,lon,lat,capacity_gw
其中 year 为场站建设时间（2030；2030+2040 记为 2040；2030+2040+2050 记为 2050），
lon ∈ [-180, 180]，lat ∈ [-90, 90]。
"""

import os
import re
import csv
import sys
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
NAM_GRID_NC = os.path.join(PROJECT_ROOT, "data", "grid_of_regions", "NAM-12_grid.nc")

# 场站出力 NC 文件默认根目录（用于零出力场站图）
DEFAULT_NC_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "wind_solar_output", "outputs_0p1deg_2030_2040_2050")

# 全球 20 大区划分（UN M49）：0.1° 栅格 + 编号→名称映射
GRID_DIV_TIF = os.path.join(PROJECT_ROOT, "data", "grid_division", "Global_Grid_Division.tif")
GRID_DIV_NAMES = os.path.join(PROJECT_ROOT, "data", "grid_division", "region_id_to_name.json")

# NAM-12 rotated-pole 网格参数（硬编码，取自 data/tracked/NAM-12_grid.nc 的 crs）
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
# natural-earth 精确国界（用于 CF=0/nan 精确口径图；与出力计算/极端天气同口径）
# ══════════════════════════════════════════════════════════════════════
NE_SHP = os.path.join(PROJECT_ROOT, "data", "maps", "natural_earth", "ne_110m_admin_0_countries.shp")
# AREA_DICT 国家名 → natural-earth shapefile 的 NAME 字段（其余已验证同名）
NE_NAME_MAP = {"México": "Mexico"}
# 精确国界图覆盖的国家：AREA_DICT 全部（含 México→Mexico）+ NAM-12 另两国（Canada / USA）
NE_TARGET_COUNTRIES = list(AREA_DICT.keys()) + ["Canada", "United States of America"]

# 复用 S0E2 的 CF 查值（assign_regions/query_cf），保证 CF=0/nan 判定与其完全同口径
sys.path.insert(0, BASE_DIR)
import plot_stations_S0E2_zero_or_nan as P0  # noqa: E402

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
    lons = np.concatenate(
        [
            np.linspace(w, e, n),
            np.full(n, e),
            np.linspace(e, w, n),
            np.full(n, w),
        ]
    )
    lats = np.concatenate(
        [
            np.full(n, north),
            np.linspace(north, south, n),
            np.full(n, south),
            np.linspace(south, north, n),
        ]
    )
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
    rlons = np.concatenate(
        [
            np.linspace(rlon0, rlon1, n),
            np.full(n, rlon1),
            np.linspace(rlon1, rlon0, n),
            np.full(n, rlon0),
        ]
    )
    rlats = np.concatenate(
        [
            np.full(n, rlat0),
            np.linspace(rlat0, rlat1, n),
            np.full(n, rlat1),
            np.linspace(rlat1, rlat0, n),
        ]
    )
    return rlons, rlats


def point_in_nam(lon, lat, domain):
    """点是否落在 NAM-12 弯曲域内：转到 rotated-pole 坐标后判断矩形范围。"""
    rlon0, rlon1, rlat0, rlat1 = domain
    pts = NAM_CRS.transform_points(PC, np.asarray(lon, float), np.asarray(lat, float))
    rlon, rlat = pts[:, 0], pts[:, 1]
    return (rlon >= rlon0) & (rlon <= rlon1) & (rlat >= rlat0) & (rlat <= rlat1)


# ── 全球 20 大区（UN M49 区域电网划分）────────────────────────────────


def load_grid_division():
    """读取 20 大区栅格，返回 (grid[H,W] int, affine_transform, {id:name})。

    grid 取值 0=背景，1..20=大区编号；transform 为 rasterio 仿射变换。
    若文件缺失则返回 (None, None, {})，绘图/统计自动跳过大区相关功能。
    """
    if not (os.path.exists(GRID_DIV_TIF) and os.path.exists(GRID_DIV_NAMES)):
        print(f"  [警告] 未找到 20 大区数据，跳过大区功能：{GRID_DIV_TIF}")
        return None, None, {}
    import json
    import rasterio

    with rasterio.open(GRID_DIV_TIF) as src:
        grid = src.read(1)
        transform = src.transform
    with open(GRID_DIV_NAMES, encoding="utf-8") as f:
        names = {int(k): v for k, v in json.load(f).items()}
    return grid, transform, names


def region_of_points(lon, lat, grid, transform):
    """按经纬度在 20 大区栅格中查表，返回每个点的大区编号（0=背景）。"""
    if grid is None or len(lon) == 0:
        return np.zeros(len(lon), dtype=int)
    # transform: col = (lon - c)/a，row = (lat - f)/e（e<0）
    a, _, c, _, e, f = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
    col = np.floor((np.asarray(lon, float) - c) / a).astype(int)
    row = np.floor((np.asarray(lat, float) - f) / e).astype(int)
    h, w = grid.shape
    col = np.clip(col, 0, w - 1)
    row = np.clip(row, 0, h - 1)
    return grid[row, col].astype(int)


def macro_region_geometries(grid, transform):
    """把 20 大区栅格矢量化为每个大区的合并多边形，返回 {id: shapely geometry}。"""
    if grid is None:
        return {}
    from collections import defaultdict
    from rasterio.features import shapes
    from shapely.geometry import shape
    from shapely.ops import unary_union

    polys = defaultdict(list)
    for geom, val in shapes(grid.astype(np.int32), mask=grid > 0, transform=transform):
        polys[int(val)].append(shape(geom))
    return {rid: unary_union(gs) for rid, gs in polys.items()}


# ══════════════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════════════


def load_stations(csv_path):
    """读取场站选址结果 CSV，返回 {year: {'solar': (lon,lat,cap), 'wind': (lon,lat,cap)}}。

    cap 为各场站装机容量（GW），取自 CSV 的 capacity_gw 列；该列缺失时记为 0。
    """
    data = {y: {"solar": [[], [], []], "wind": [[], [], []]} for y in YEARS}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            year = int(row["year"])
            typ = row["type"]
            if year not in data or typ not in data[year]:
                continue
            data[year][typ][0].append(float(row["lon"]))
            data[year][typ][1].append(float(row["lat"]))
            data[year][typ][2].append(float(row.get("capacity_gw") or 0.0))
    return {y: {t: (np.array(v[0]), np.array(v[1]), np.array(v[2])) for t, v in d.items()} for y, d in data.items()}


def _ssp_code(ssp):
    """将各种 SSP 表达形式统一为 'ssp126' / 'ssp245' / 'ssp585'。"""
    s = ssp.lower()
    if re.search(r"1.?2.?6", s):
        return "ssp126"
    if re.search(r"2.?4.?5", s):
        return "ssp245"
    if re.search(r"5.?8.?5", s) or re.search(r"5.?6.?0", s):
        return "ssp585"
    m = re.search(r"ssp(\d{3})", s)
    if m:
        return f"ssp{m.group(1)}"
    return ssp


def load_zero_cf_stations(nc_output_dir, ssp_code):
    """从场站出力 NC 文件提取 2050 年 CF=0 的场站，按激活年份分组。

    扫描 nc_output_dir 下的 pv_out 和 wind_out 子目录（仅 NESM3 模型），
    对每个区域读取 NC 文件，以 2050 年出力计算年 CF，将 CF=0 的场站按
    其 activation_year 归入 YEARS 对应的年份桶（2030/2040/2050）。

    返回与 load_stations() 相同的结构：
        {year: {'solar': (lon, lat, cap), 'wind': (lon, lat, cap)}}
    """
    import netCDF4 as nc_lib

    ssp = _ssp_code(ssp_code)
    result = {y: {"solar": [[], [], []], "wind": [[], [], []]} for y in YEARS}

    for tech, tech_dir, prefix in [
        ("solar", "pv_out", "pv"),
        ("wind", "wind_out", "wind"),
    ]:
        base = os.path.join(nc_output_dir, tech_dir, "NESM3")
        if not os.path.isdir(base):
            print(f"  [零出力] 目录不存在，跳过 {tech}: {base}")
            continue

        for region in sorted(os.listdir(base)):
            nc_path = os.path.join(
                base,
                region,
                f"{prefix}_stations_out_{region}_NESM3_{ssp}_allmonths.nc",
            )
            if not os.path.isfile(nc_path):
                continue

            try:
                ds = nc_lib.Dataset(nc_path, "r")
                power = ds.variables["power"][:]
                if hasattr(power, "filled"):
                    power = power.filled(np.nan)

                t_var = ds.variables["time"]
                times = nc_lib.num2date(t_var[:], t_var.units)
                years_arr = np.array([t.year for t in times], dtype=np.int32)

                cap_gw = np.asarray(ds.variables["capacity_gw"][:], dtype=np.float64)
                act_year = np.asarray(ds.variables["activation_year"][:], dtype=np.int32)
                sta_lons = np.asarray(ds.variables["station_lon"][:], dtype=np.float64)
                sta_lats = np.asarray(ds.variables["station_lat"][:], dtype=np.float64)
                ds.close()
            except Exception as e:
                print(f"  [零出力] 读取失败 {nc_path}: {e}")
                continue

            mask_2050 = years_arr == 2050
            if not mask_2050.any():
                continue

            pwr_2050 = power[mask_2050, :]
            n_steps = int(mask_2050.sum())

            active = act_year <= 2050
            has_data = ~np.all(np.isnan(pwr_2050), axis=0)
            valid = active & has_data & (cap_gw > 0)

            pwr_sum = np.nansum(pwr_2050, axis=0)
            with np.errstate(invalid="ignore", divide="ignore"):
                ann_cf = np.where(valid, pwr_sum / (n_steps * cap_gw), np.nan)

            zero_idx = np.where(valid & (ann_cf == 0))[0]
            for i in zero_idx:
                ay = int(act_year[i])
                yr_key = 2030 if ay <= 2030 else (2040 if ay <= 2040 else 2050)
                result[yr_key][tech][0].append(float(sta_lons[i]))
                result[yr_key][tech][1].append(float(sta_lats[i]))
                result[yr_key][tech][2].append(float(cap_gw[i]))

    return {y: {t: (np.array(v[0]), np.array(v[1]), np.array(v[2])) for t, v in d.items()} for y, d in result.items()}


def in_any_region(lon, lat, domain):
    """点是否落在任一 AREA_DICT 框或 NAM-12 域内。"""
    if len(lon) == 0:
        return np.zeros(0, dtype=bool)
    mask = point_in_nam(lon, lat, domain)
    for bbox in AREA_DICT.values():
        mask = mask | point_in_bbox(lon, lat, bbox)
    return mask


# ── natural-earth 精确国界（point-in-polygon）─────────────────────────


def load_ne_country_shapes(shp_path=NE_SHP):
    """读取 natural-earth admin-0 shapefile，返回 {AREA_DICT国家名: shapely geometry}。

    仅保留 NE_TARGET_COUNTRIES 涉及国家（经 NE_NAME_MAP 把 AREA_DICT 名映射到 NE 的 NAME 字段）。
    返回普通几何（未 prep）；批量 point-in-polygon 在 assign_country_ne 内临时 prep。
    """
    import fiona
    from shapely.geometry import shape

    # {NE_NAME: AREA_DICT国家名}
    target = {NE_NAME_MAP.get(c, c): c for c in NE_TARGET_COUNTRIES}
    shapes = {}
    with fiona.open(shp_path) as src:
        for rec in src:
            ne_name = rec["properties"].get("NAME")
            if ne_name in target:
                geom = shape(rec["geometry"])
                if not geom.is_valid:
                    geom = geom.buffer(0)
                shapes[target[ne_name]] = geom
    missing = set(NE_TARGET_COUNTRIES) - set(shapes.keys())
    if missing:
        print(f"  [警告] natural-earth 未匹配国家: {sorted(missing)}")
    return shapes


def assign_country_ne(lon, lat, shapes):
    """逐场站判定属于哪个国家（natural-earth point-in-polygon）。

    返回国家名数组（AREA_DICT 名）；不属于任何目标国家的记为 "outside"。
    lon/lat 为 [-180,180]。按 NE_TARGET_COUNTRIES 顺序判定，首个命中即归属。
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    labels = np.array(["outside"] * len(lon), dtype=object)
    for name in NE_TARGET_COUNTRIES:
        geom = shapes.get(name)
        if geom is None:
            continue
        undecided = labels == "outside"
        if not undecided.any():
            break
        prep_geom = prep(geom)
        sub_lon, sub_lat = lon[undecided], lat[undecided]
        hit = np.fromiter(
            (prep_geom.contains(Point(float(lo), float(la))) for lo, la in zip(sub_lon, sub_lat)),
            dtype=bool,
            count=int(undecided.sum()),
        )
        idx = np.where(undecided)[0][hit]
        labels[idx] = name
    return labels


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
            ax.text(
                cx,
                (north + south) / 2.0,
                name,
                transform=PC,
                fontsize=6,
                ha="center",
                va="center",
                color="#7a0000",
                zorder=5,
            )

    rlons, rlats = nam_boundary_rotated(domain)
    ax.plot(rlons, rlats, transform=NAM_CRS, color="#1f77b4", lw=1.6, zorder=4)
    if label:
        rlon0, rlon1, rlat0, rlat1 = domain
        ax.text(
            (rlon0 + rlon1) / 2,
            (rlat0 + rlat1) / 2,
            "NAM-12",
            transform=NAM_CRS,
            fontsize=8,
            ha="center",
            va="center",
            color="#0b3d61",
            zorder=5,
        )


def draw_macro_regions(ax, region_geoms, names, label=False):
    """在 ax 上绘制 20 个大区的边界（仅描边，不填充）。"""
    if not region_geoms:
        return
    for rid, geom in region_geoms.items():
        ax.add_geometries([geom], crs=PC, facecolor="none", edgecolor="#2f7d32", linewidth=0.6, zorder=2)
        if label:
            try:
                pt = geom.representative_point()
                ax.text(
                    pt.x,
                    pt.y,
                    str(rid),
                    transform=PC,
                    fontsize=7,
                    ha="center",
                    va="center",
                    color="#14521a",
                    zorder=5,
                    bbox=dict(boxstyle="circle,pad=0.1", fc="white", ec="#2f7d32", lw=0.4, alpha=0.7),
                )
            except Exception:
                pass


def plot_regions_map(ssp, domain, region_geoms, names, out_path):
    """图1：项目所用全部区域范围 + 20 大区边界。"""
    fig = plt.figure(figsize=(16, 9))
    ax = plt.axes(projection=PC)
    setup_basemap(ax)
    draw_macro_regions(ax, region_geoms, names, label=True)
    draw_regions(ax, domain, label=True)
    if region_geoms:
        ax.plot([], [], color="#2f7d32", lw=0.8, label="20 大区边界（UN M49）")
    ax.plot([], [], color="#d62728", lw=1.2, label="AREA_DICT 国家边界框")
    ax.plot([], [], color="#1f77b4", lw=1.6, label="NAM-12 弯曲域")
    ax.legend(loc="lower left", fontsize=10, framealpha=0.9, edgecolor="#888")
    ax.set_title(f"项目区域范围（{ssp}）：20 大区 + AREA_DICT 国家 + NAM-12", fontsize=14, pad=10)
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")


def plot_stations_map(ssp, stations, domain, region_geoms, names, out_path,
                      title_suffix="", by_year=True, single_color="#ff7f0e", ratio_denominator=None):
    """图2：场站位置（上=光伏，下=风电），叠加区域边界。

    by_year=True（默认）：按年份着色，每年一个图例项（普通场站图）。
    by_year=False：合并所有年份、用 single_color 单色绘制（用于零出力 CF=0 场站图）；
        此时若提供 ratio_denominator={tech: 总数}，则图例标注 CF=0 场站占比。
    """
    fig, (ax_s, ax_w) = plt.subplots(2, 1, figsize=(16, 16), subplot_kw={"projection": PC})
    for ax, typ, title in [
        (ax_s, "solar", f"{ssp} — 光伏场站选址{title_suffix}"),
        (ax_w, "wind", f"{ssp} — 风电场站选址{title_suffix}"),
    ]:
        setup_basemap(ax)
        draw_macro_regions(ax, region_geoms, names, label=True)
        draw_regions(ax, domain, label=False)

        if by_year:
            for year in YEARS:
                lon, lat, _cap = stations[year][typ]
                ax.scatter(
                    lon,
                    lat,
                    s=3,
                    c=YEAR_COLORS[year],
                    transform=PC,
                    label=f"{year} ({len(lon):,})",
                    rasterized=True,
                    zorder=3,
                )
        else:
            # 合并所有年份，单色绘制
            lons = np.concatenate([stations[y][typ][0] for y in YEARS])
            lats = np.concatenate([stations[y][typ][1] for y in YEARS])
            n = len(lons)
            if ratio_denominator is not None:
                denom = ratio_denominator.get(typ, 0)
                ratio = (n / denom) if denom else 0.0
                label = f"CF=0 场站 {n:,} / {denom:,} ({ratio:.2%})"
            else:
                label = f"场站 {n:,}"
            ax.scatter(
                lons,
                lats,
                s=5,
                c=single_color,
                transform=PC,
                label=label,
                rasterized=True,
                zorder=3,
            )

        if region_geoms:
            ax.plot([], [], color="#2f7d32", lw=0.8, label="20 大区边界")
        ax.plot([], [], color="#d62728", lw=1.0, label="AREA_DICT")
        ax.plot([], [], color="#1f77b4", lw=1.6, label="NAM-12")
        ax.legend(loc="lower left", fontsize=10, markerscale=4, framealpha=0.9, edgecolor="#888")
        ax.set_title(title, fontsize=14, pad=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")


def _plot_ne_borders(ax, ne_shapes, color="#0a5d0a", lw=1.2, zorder=5):
    """用 ax.plot 画各国精确国界（描边）。

    cartopy 的 add_geometries 对散点图的 zorder 不可靠（国界会被点遮盖），
    故遍历 Polygon 的 exterior/interiors 用 ax.plot 绘制，与 draw_regions 的
    红色 bbox 用同一套绘制机制，zorder=5 保证位于场站点（3/4）之上。
    """
    from shapely.geometry import Polygon, MultiPolygon

    for geom in ne_shapes.values():
        polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
        for poly in polys:
            if not isinstance(poly, Polygon):
                continue
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, color=color, lw=lw, zorder=zorder, transform=PC)
            for interior in poly.interiors:
                xi, yi = interior.xy
                ax.plot(xi, yi, color=color, lw=lw, zorder=zorder, transform=PC)


def plot_cf_zero_nan_ne_map(ssp, stations, domain, ne_shapes, out_path):
    """图4：natural-earth 精确国界 + 气象边界(AREA_DICT/NAM) + CF=0/nan 场站。

    上=光伏 / 下=风电。CF=0/nan 由 data/cfs 的 2050 年均判定（复用 S0E2 的 assign_regions/query_cf）。
    比例 = 精确国界内 CF=0/nan 场站数 / 精确国界内全部场站数。
    """
    P0.SSP = _ssp_code(ssp)  # 让 S0E2 的 CF 查值走当前 ssp
    fig, axes = plt.subplots(2, 1, figsize=(16, 16), subplot_kw={"projection": PC})
    for ax, typ, title in [
        (axes[0], "solar", f"{ssp} — 光伏：精确国界内 CF=0/nan 场站（data/cfs，2050 年均）"),
        (axes[1], "wind", f"{ssp} — 风电：精确国界内 CF=0/nan 场站（data/cfs，2050 年均）"),
    ]:
        setup_basemap(ax)
        # 2) 气象边界：AREA_DICT 矩形框(红) + NAM-12 弯曲域(蓝)
        draw_regions(ax, domain, label=False)
        # 3) 2050 场站 + CF 判定
        lon, lat, _cap = stations[2050][typ]
        labels = P0.assign_regions(lon, lat)
        cf_vals = P0.query_cf(lon, lat, labels, typ)
        bad = np.isnan(cf_vals) | (cf_vals == 0)
        in_ne = assign_country_ne(lon, lat, ne_shapes) != "outside"
        n_in = int(in_ne.sum())
        n_bad_in = int((bad & in_ne).sum())
        ratio = n_bad_in / n_in if n_in else 0.0
        # 仅绘制「各国精确国界内 CF=0/nan」的场站（红色），不画正常场站、不画国界外场站
        bad_in_ne = bad & in_ne
        if bad_in_ne.any():
            ax.scatter(lon[bad_in_ne], lat[bad_in_ne], s=6, c="#d62728", transform=PC, rasterized=True,
                       label=f"精确国界内 CF=0/nan {int(bad_in_ne.sum()):,}", zorder=4)
        # 1) NE 精确国界（最后画，ax.plot + zorder=5 置于场站点之上）
        _plot_ne_borders(ax, ne_shapes, color="#0a5d0a", lw=1.2, zorder=5)
        # 边界图例
        ax.plot([], [], color="#2f7d32", lw=0.8, label="精确国界（natural-earth）")
        ax.plot([], [], color="#d62728", lw=1.0, label="AREA_DICT 气象边界框")
        ax.plot([], [], color="#1f77b4", lw=1.6, label="NAM-12 弯曲域")
        # 比例标注框
        ax.text(0.99, 0.02, f"精确国界内 CF=0/nan：{n_bad_in:,} / {n_in:,}（{ratio:.2%}）",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=11,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#888", alpha=0.9))
        ax.legend(loc="lower left", fontsize=9, markerscale=3, framealpha=0.9, edgecolor="#888")
        ax.set_title(title, fontsize=13, pad=8)
    fig.suptitle(f"{ssp} · 2050：natural-earth 精确国界 vs 气象边界（AREA_DICT+NAM-12）· CF=0/nan 场站",
                 fontsize=15, y=0.997)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}（精确国界内 CF=0/nan: 光伏/风电见标题区）")


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


def compute_stats(stations, domain):
    """统计每个 (year,type) 的场站覆盖情况。

    返回的每行包含两种口径：
      - 场站个数：total_n / inside_n / ratio_n
      - 装机容量(GW)：total_cap / inside_cap / ratio_cap
    其中 inside 指落在 AREA_DICT 框或 NAM-12 域内（即「当前区域」能覆盖的部分）。
    """
    rows = []
    for year in sorted(stations):
        for typ in ("solar", "wind"):
            lon, lat, cap = stations[year][typ]
            total_n = len(lon)
            mask = in_any_region(lon, lat, domain) if total_n else np.zeros(0, dtype=bool)
            inside_n = int(mask.sum())
            ratio_n = inside_n / total_n if total_n else 0.0

            total_cap = float(cap.sum()) if total_n else 0.0
            inside_cap = float(cap[mask].sum()) if total_n else 0.0
            ratio_cap = inside_cap / total_cap if total_cap else 0.0

            rows.append((year, typ, total_n, inside_n, ratio_n, total_cap, inside_cap, ratio_cap))
    return rows


def report_stats(ssp, rows, out_path):
    """打印并保存统计结果（场站个数口径 + 装机容量口径）。"""
    print(f"\n  当前区域可覆盖的风光场站 / 装机量统计（{ssp}）")
    print(
        f"  {'year':<6}{'type':<7}"
        f"{'n_tot':>8}{'n_in':>8}{'n_ratio':>9}   "
        f"{'cap_tot':>11}{'cap_in':>11}{'cap_ratio':>11}"
    )
    print("  " + "-" * 80)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "year",
                "type",
                "total",
                "inside_region",
                "ratio",
                "total_cap_gw",
                "inside_cap_gw",
                "cap_ratio",
            ]
        )
        for year, typ, total_n, inside_n, ratio_n, total_cap, inside_cap, ratio_cap in rows:
            print(
                f"  {year:<6}{typ:<7}"
                f"{total_n:>8,}{inside_n:>8,}{ratio_n:>8.1%}   "
                f"{total_cap:>11,.0f}{inside_cap:>11,.0f}{ratio_cap:>10.1%}"
            )
            writer.writerow(
                [
                    year,
                    typ,
                    total_n,
                    inside_n,
                    f"{ratio_n:.4f}",
                    f"{total_cap:.4f}",
                    f"{inside_cap:.4f}",
                    f"{ratio_cap:.4f}",
                ]
            )

        tot_n = sum(r[2] for r in rows)
        ins_n = sum(r[3] for r in rows)
        tot_cap = sum(r[5] for r in rows)
        ins_cap = sum(r[6] for r in rows)
        ratio_n_all = ins_n / tot_n if tot_n else 0.0
        ratio_cap_all = ins_cap / tot_cap if tot_cap else 0.0
        print("  " + "-" * 80)
        print(
            f"  {'ALL':<6}{'':<7}"
            f"{tot_n:>8,}{ins_n:>8,}{ratio_n_all:>8.1%}   "
            f"{tot_cap:>11,.0f}{ins_cap:>11,.0f}{ratio_cap_all:>10.1%}"
        )
        writer.writerow(
            [
                "ALL",
                "",
                tot_n,
                ins_n,
                f"{ratio_n_all:.4f}",
                f"{tot_cap:.4f}",
                f"{ins_cap:.4f}",
                f"{ratio_cap_all:.4f}",
            ]
        )
    print(f"  -> {out_path}")


def _region_accumulate(stations_year, domain, grid, transform, n_ids):
    """对单一年份的所有场站（风+光）按大区累加，返回 4 个长度 n_ids+1 的数组。"""
    n_total = np.zeros(n_ids + 1)
    n_inside = np.zeros(n_ids + 1)
    cap_total = np.zeros(n_ids + 1)
    cap_inside = np.zeros(n_ids + 1)
    for typ in ("solar", "wind"):
        lon, lat, cap = stations_year[typ]
        if len(lon) == 0:
            continue
        rid = region_of_points(lon, lat, grid, transform)
        inside = in_any_region(lon, lat, domain)
        valid = rid > 0
        np.add.at(n_total, rid[valid], 1)
        np.add.at(cap_total, rid[valid], cap[valid])
        ins = valid & inside
        np.add.at(n_inside, rid[ins], 1)
        np.add.at(cap_inside, rid[ins], cap[ins])
    return n_total, n_inside, cap_total, cap_inside


def compute_region_stats(stations, domain, grid, transform, names):
    """逐年份、逐 20 大区统计（每个年份内汇总风+光）。

    各年份独立计算（CSV 年份为累积存量，不能相加）。对某年某大区 R：
      - n_total / cap_total：落在大区 R 内的场站数 / 装机量(GW)
      - n_inside / cap_inside：其中又被「项目区域」（AREA_DICT 框 + NAM-12 域）
        覆盖的场站数 / 装机量
      - cover_ratio：本大区内被项目区域覆盖的比例（inside / total）
    返回 (year, rid, name, n_total, n_inside, n_ratio, cap_total, cap_inside, cap_ratio) 行列表，
    按 (年份, 大区编号) 排序。
    """
    if grid is None:
        return []

    n_ids = max(names) if names else 20
    rows = []
    for year in sorted(stations):
        n_total, n_inside, cap_total, cap_inside = _region_accumulate(stations[year], domain, grid, transform, n_ids)
        for rid in range(1, n_ids + 1):
            nt, ni = int(n_total[rid]), int(n_inside[rid])
            ct, ci = float(cap_total[rid]), float(cap_inside[rid])
            rows.append(
                (
                    year,
                    rid,
                    names.get(rid, f"region {rid}"),
                    nt,
                    ni,
                    (ni / nt if nt else 0.0),
                    ct,
                    ci,
                    (ci / ct if ct else 0.0),
                )
            )
    return rows


def report_region_stats(ssp, rows, out_path):
    """按年份分组打印并保存 20 大区覆盖统计。"""
    if not rows:
        return
    years = sorted({r[0] for r in rows})
    print(f"\n  各大区内被项目区域覆盖的场站 / 装机量统计（{ssp}，分年份）")
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "year",
                "region_id",
                "region_name",
                "n_total",
                "n_inside",
                "n_cover_ratio",
                "cap_total_gw",
                "cap_inside_gw",
                "cap_cover_ratio",
            ]
        )
        for year in years:
            year_rows = [r for r in rows if r[0] == year]
            print(f"\n  ── {year} 年 ──")
            print(
                f"  {'id':<3}{'region':<22}"
                f"{'n_tot':>8}{'n_in':>8}{'n_cov':>8}   "
                f"{'cap_tot':>11}{'cap_in':>11}{'cap_cov':>9}"
            )
            print("  " + "-" * 88)
            for _y, rid, name, nt, ni, nr, ct, ci, cr in year_rows:
                print(f"  {rid:<3}{name:<22}" f"{nt:>8,}{ni:>8,}{nr:>7.1%}   " f"{ct:>11,.0f}{ci:>11,.0f}{cr:>8.1%}")
                writer.writerow(
                    [
                        year,
                        rid,
                        name,
                        nt,
                        ni,
                        f"{nr:.4f}",
                        f"{ct:.4f}",
                        f"{ci:.4f}",
                        f"{cr:.4f}",
                    ]
                )
            tot_n = sum(r[3] for r in year_rows)
            ins_n = sum(r[4] for r in year_rows)
            tot_c = sum(r[6] for r in year_rows)
            ins_c = sum(r[7] for r in year_rows)
            print("  " + "-" * 88)
            print(
                f"  {'':3}{'ALL (20 区合计)':<22}"
                f"{tot_n:>8,}{ins_n:>8,}{(ins_n / tot_n if tot_n else 0):>7.1%}   "
                f"{tot_c:>11,.0f}{ins_c:>11,.0f}{(ins_c / tot_c if tot_c else 0):>8.1%}"
            )
            writer.writerow(
                [
                    year,
                    "ALL",
                    "20 区合计",
                    tot_n,
                    ins_n,
                    f"{(ins_n / tot_n if tot_n else 0):.4f}",
                    f"{tot_c:.4f}",
                    f"{ins_c:.4f}",
                    f"{(ins_c / tot_c if tot_c else 0):.4f}",
                ]
            )
    print(f"\n  -> {out_path}")


def compute_cf_zero_nan_by_country(ssp, stations, ne_shapes):
    """逐国家（natural-earth 精确边界）统计 2050 年 CF=0/nan 场站。

    CF 判定复用 S0E2（data/cfs 2050 年均，isnan | ==0）。
    返回 [(tech, country, n_total_in_border, n_cf_zero_nan, bad_ratio), ...]，
    仅含场站数>0 的国家，并附一行 "outside(精确国界外)"。
    """
    P0.SSP = _ssp_code(ssp)
    rows = []
    for typ in ("solar", "wind"):
        lon, lat, _cap = stations[2050][typ]
        if len(lon) == 0:
            continue
        labels = P0.assign_regions(lon, lat)
        cf_vals = P0.query_cf(lon, lat, labels, typ)
        bad = np.isnan(cf_vals) | (cf_vals == 0)
        countries = assign_country_ne(lon, lat, ne_shapes)
        for name in NE_TARGET_COUNTRIES:
            m = countries == name
            nt = int(m.sum())
            if nt == 0:
                continue
            nb = int((bad & m).sum())
            rows.append((typ, name, nt, nb, nb / nt if nt else 0.0))
        m_out = countries == "outside"
        nt = int(m_out.sum())
        if nt:
            nb = int((bad & m_out).sum())
            rows.append((typ, "outside(精确国界外)", nt, nb, nb / nt if nt else 0.0))
    return rows


def report_cf_zero_nan_by_country(ssp, rows, out_path):
    """打印并保存逐国 CF=0/nan 统计。"""
    print(f"\n  各 natural-earth 精确国界内 CF=0/nan 场站统计（{ssp}，2050）")
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tech", "country", "n_total_in_border", "n_cf_zero_nan", "bad_ratio"])
        last_tech = None
        for tech, country, nt, nb, r in rows:
            if tech != last_tech:
                print(f"\n  ── {tech} ──")
                print(f"  {'country':<26}{'n_total':>9}{'n_bad':>9}{'ratio':>9}")
                print("  " + "-" * 57)
                last_tech = tech
            print(f"  {country:<26}{nt:>9,}{nb:>9,}{r:>8.2%}")
            w.writerow([tech, country, nt, nb, f"{r:.4f}"])
    print(f"\n  -> {out_path}")


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
    parser.add_argument(
        "--draw-macro-regions", action="store_true", help="在图上叠加 20 大区边界（默认关闭；大区统计始终输出）"
    )
    parser.add_argument(
        "--nc-output-dir",
        default=DEFAULT_NC_OUTPUT_DIR,
        help="场站出力 NC 文件根目录，用于生成零出力场站图" f"（默认：{DEFAULT_NC_OUTPUT_DIR}）",
    )
    args = parser.parse_args()

    ssp = derive_ssp(args.stations, args.ssp)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"{'=' * 60}\n  区域 & 场站可视化：{ssp}\n  stations: {args.stations}\n{'=' * 60}")

    domain = load_nam_domain()
    stations = load_stations(args.stations)

    grid, transform, names = load_grid_division()
    # 大区边界默认不绘制；仅在 --draw-macro-regions 时才矢量化（较耗时）
    region_geoms = macro_region_geometries(grid, transform) if args.draw_macro_regions else {}

    plot_regions_map(ssp, domain, region_geoms, names, os.path.join(OUTPUT_DIR, f"regions_{ssp}.png"))
    plot_stations_map(ssp, stations, domain, region_geoms, names, os.path.join(OUTPUT_DIR, f"stations_{ssp}.png"))

    # 零出力场站图
    if os.path.isdir(args.nc_output_dir):
        print(f"\n  生成零出力场站图 (NC 目录: {args.nc_output_dir}) ...")
        zero_stations = load_zero_cf_stations(args.nc_output_dir, ssp)
        n_zero = sum(len(zero_stations[y][t][0]) for y in YEARS for t in ("solar", "wind"))
        print(f"  找到 {n_zero} 个零出力场站（2050 年，各年份合计）")
        # 比例分母：2050 年各类型全部场站数（零出力基于 2050 年 CF 计算）
        ratio_denominator = {
            "solar": len(stations[2050]["solar"][0]),
            "wind": len(stations[2050]["wind"][0]),
        }
        plot_stations_map(
            ssp,
            zero_stations,
            domain,
            region_geoms,
            names,
            os.path.join(OUTPUT_DIR, f"zero_cf_stations_{ssp}.png"),
            title_suffix=" — 零出力场站（CF=0）",
            by_year=False,
            ratio_denominator=ratio_denominator,
        )
    else:
        print(f"\n  [跳过] NC 出力目录不存在，不生成零出力场站图：{args.nc_output_dir}")

    rows = compute_stats(stations, domain)
    report_stats(ssp, rows, os.path.join(OUTPUT_DIR, f"stats_in_regions_{ssp}.csv"))

    region_rows = compute_region_stats(stations, domain, grid, transform, names)
    report_region_stats(ssp, region_rows, os.path.join(OUTPUT_DIR, f"stats_by_macro_region_{ssp}.csv"))

    # ★ natural-earth 精确国界 + CF=0/nan 场站（新增）
    if os.path.isfile(NE_SHP):
        print(f"\n  生成 natural-earth 精确国界 CF=0/nan 场站图 ...")
        P0.SSP = _ssp_code(ssp)
        P0.get_nam_tree()  # P0.assign_regions 需要 NAM-12 网格做区域归属
        ne_shapes = load_ne_country_shapes()
        plot_cf_zero_nan_ne_map(
            ssp, stations, domain, ne_shapes,
            os.path.join(OUTPUT_DIR, f"cf_zero_nan_ne_border_{ssp}.png"),
        )
        cz_rows = compute_cf_zero_nan_by_country(ssp, stations, ne_shapes)
        report_cf_zero_nan_by_country(
            ssp, cz_rows,
            os.path.join(OUTPUT_DIR, f"stats_cf_zero_nan_by_country_{ssp}.csv"),
        )
    else:
        print(f"\n  [跳过] natural-earth shapefile 不存在：{NE_SHP}")


if __name__ == "__main__":
    main()
