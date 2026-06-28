"""
绘制哪些场站所在位置的风光气象 / 风光容量因子(CF) 为 0 或 nan。

2×2 四子图（默认 NESM3 / ssp126 / 2050 年）：
    ┌ 气象·风电 │ 气象·光伏 ┐   上排：data/bcsd_outputs（仅 26 国，china/NAM-12 无气象）
    ├ CF·风电   │ CF·光伏   ┤   下排：data/cfs（26 国 + china + NAM-12）
    └───────────┴──────────┘
    左列=风电，右列=光伏；上排=气象，下排=容量因子。

着色（每子图独立，两态；无数据场站不绘制、不参与统计）：
    - 0 或 nan（2050 年均值）→ 红色   （数据源覆盖、但该位置值为 0 或缺失）
    - 正常（年均值 > 0 且非 nan）→ 灰色
异常占比 = 0/nan ÷ (0/nan + 正常)，仅计有数据覆盖的场站。

聚合方式：对每个场站位置取 2050 年的年均值，再判断 ==0 或 nan。
    - CF：年均 CF（time-mean）。
    - 风电气象：年均 RMS 风速 = sqrt(mean(uas²)+mean(vas²))（用 uas/vas 两文件合成）。
    - 光伏气象：年均辐射 rsds（time-mean）。

数据源与路径：
    - 气象 bcsd_outputs/{MODEL}/{Country}/{MODEL}/{var}_3h_bcsd_on_0p1deg_{Country}_{MODEL}_{ssp}_*.nc
        仅 26 国（不含 china/NAM-12）；风电用 uas+vas，光伏用 rsds。
    - CF 26 国：cfs/CFs_of_{tech}/{MODEL}/{Country}/{tech}_CF_{Country}_{MODEL}_{ssp}_*_allmonths.nc
    - CF china：cfs/CFs_of_{tech}_china/{MODEL}/{tech}_CF_china_{MODEL}_{ssp}_*_allmonths.nc
    - CF NAM-12：cfs/CFs_of_{tech}_NAM-12/CanESM5/r1i1p2f1/{ssp}/yearly/
                 {tech}_CF_NAM-12_CanESM5_r1i1p2f1_CRCM5_{ssp}_2050_allmonths.nc
        NAM-12 模式固定 CanESM5（rotated grid，2D lat/lon，按年分文件，2050 年即整文件）。

区域归属：场站先用 AREA_DICT 经纬框分配到 26 国 / China；剩余场站用 NAM-12 CF 网格的
2D lat/lon 建最近邻树，距离 < 阈值者归 NAM-12；其余为「区域外(无数据)」。

用法:
    python plot_stations_S0E2_zero_or_nan.py [--model NESM3] [--ssp ssp126] [--stations <场站.csv>]
"""

import os
import csv
import glob
import argparse
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.spatial import cKDTree

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "plot_stations", os.path.splitext(os.path.basename(__file__))[0])

BCSD_DIR = os.path.join(PROJECT_ROOT, "data", "bcsd_outputs")          # 气象（仅 26 国）
CFS_DIR = os.path.join(PROJECT_ROOT, "data", "cfs")                     # 容量因子

MODEL = "NESM3"          # 26 国 / china 使用的 CMIP6 模式
NAM_MODEL = "CanESM5"    # NAM-12 固定模式
SSP = "ssp126"
YEAR = 2050              # 取该年的年均值判定 0/nan

STATIONS_DIR = os.path.join(PROJECT_ROOT, "data", "stations")
SSP_STATION_FILE = {
    "ssp126": "stations_SSP1-2.6.csv",
    "ssp245": "stations_SSP2-4.5.csv",
    "ssp585": "stations_SSP5-6.0.csv",
}

# AREA_DICT: [北纬N, lonW, 南纬S, lonE]，经度 [0,360)（lonW>lonE 表示跨 0° 经线）
AREA_DICT: dict[str, list[float]] = {
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
    "Chile": [-17.5, 283.5, -55.9, 293.6],
    "South Africa": [-22.1, 16.3, -28.3, 32.9],
    "Egypt": [31.7, 24.7, 22.0, 36.9],
    "Australia": [-9.1, 112.9, -43.6, 153.6],
}
COUNTRIES_26 = [k for k in AREA_DICT if k != "China"]  # 有气象+CF 的 26 国

# AREA_DICT 国家名 → bcsd/cfs 目录名（空格 vs 连字符差异）
_AREA_DIR_FIX = {"South Korea": "South-Korea", "United Kingdom": "United-Kingdom", "South Africa": "South-Africa"}


def area_to_dir(name):
    return _AREA_DIR_FIX.get(name, name)


NAM_NEAR_THRESH = 0.3  # 场站到 NAM-12 网格最近邻距离(°)小于此值才归 NAM-12

PC = ccrs.PlateCarree()

# 三态配色：0/nan=红，正常=灰，无数据=蓝
COLOR_BAD = "#d62728"     # 红：0 或 nan
COLOR_OK = "#9aa0a6"      # 灰：正常
COLOR_NODATA = "#1f77b4"  # 蓝：无数据

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
    """读取场站 CSV，仅保留 YEAR=2050。返回 {'solar':(lon,lat),'wind':(lon,lat)}。"""
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
# 文件定位
# ══════════════════════════════════════════════════════════════════════


def _pick_year_file(pattern, year):
    """从 glob 匹配中选 time 覆盖 year 的文件；无则返回首个/None。"""
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    y0, y1 = np.datetime64(f"{year}-01-01"), np.datetime64(f"{year}-12-31")
    for m in matches:
        try:
            with xr.open_dataset(m) as ds:
                if "time" in ds:
                    t = ds["time"].values
                    if len(t) and t[0] <= y1 and t[-1] >= y0:
                        return m
        except Exception:
            continue
    return matches[0]


def cf_path_26(country, tech, model, ssp, year):
    """26 国 CF 文件路径（Country 用目录名）。"""
    d = area_to_dir(country)
    pat = os.path.join(CFS_DIR, f"CFs_of_{tech}", model, d, f"{tech}_CF_{d}_{model}_{ssp}_*_allmonths.nc")
    return _pick_year_file(pat, year)


def cf_path_china(tech, model, ssp, year):
    pat = os.path.join(CFS_DIR, f"CFs_of_{tech}_china", model, f"{tech}_CF_china_{model}_{ssp}_*_allmonths.nc")
    return _pick_year_file(pat, year)


def cf_path_nam(tech, ssp, year):
    """NAM-12 CF 文件路径（模式固定 CanESM5，按年分文件）。"""
    fname = f"{tech}_CF_NAM-12_{NAM_MODEL}_r1i1p2f1_CRCM5_{ssp}_{year}_allmonths.nc"
    return os.path.join(CFS_DIR, f"CFs_of_{tech}_NAM-12", NAM_MODEL, "r1i1p2f1", ssp, "yearly", fname)


def met_path(country, var, model, ssp, year):
    """气象文件路径（仅 26 国）。"""
    d = area_to_dir(country)
    pat = os.path.join(BCSD_DIR, model, d, model, f"{var}_3h_bcsd_on_0p1deg_{d}_{model}_{ssp}_*.nc")
    return _pick_year_file(pat, year)


# ══════════════════════════════════════════════════════════════════════
# 年均网格加载（2050 年）
# ══════════════════════════════════════════════════════════════════════

_CACHE: dict = {}


def _annual_mean_1d(path, var, year):
    """读 1D lat/lon 网格文件，取 year 年 time-mean，返回 (grid2d, lat1d, lon1d)。

    若文件不含 year 年数据（部分文件时间不完整，如 Poland solar 实际仅 2015-2016）返回 None。
    """
    ds = xr.open_dataset(path)
    idx = np.where(ds["time"].dt.year == year)[0]
    if len(idx) == 0:
        ds.close()
        return None
    da = ds[var].isel(time=idx).mean("time")
    g, la, lo = np.asarray(da.values), np.asarray(da["lat"].values), np.asarray(da["lon"].values)
    ds.close()
    return g, la, lo


def load_cf_grid(country, tech, model, ssp, year):
    """CF 年均网格。26 国用 cf_path_26，返回 (grid2d, lat1d, lon1d) 或 None。"""
    key = ("cf26", country, tech, model, ssp, year)
    if key in _CACHE:
        return _CACHE[key]
    p = cf_path_26(country, tech, model, ssp, year)
    res = None
    if p and os.path.isfile(p):
        try:
            res = _annual_mean_1d(p, f"{tech}_cf", year)
        except Exception as e:
            print(f"    [警告] 读取 CF 失败 {country}/{tech}: {e}")
    _CACHE[key] = res
    return res


def load_cf_grid_china(tech, model, ssp, year):
    key = ("cfchina", tech, model, ssp, year)
    if key in _CACHE:
        return _CACHE[key]
    p = cf_path_china(tech, model, ssp, year)
    res = None
    if p and os.path.isfile(p):
        try:
            res = _annual_mean_1d(p, f"{tech}_cf", year)
        except Exception as e:
            print(f"    [警告] 读取 China CF 失败 {tech}: {e}")
    _CACHE[key] = res
    return res


def load_cf_grid_nam(tech, ssp, year):
    """NAM-12 CF 年均网格：rotated grid，2D lat/lon，整文件即 year 年。返回 (grid2d, lat2d, lon2d) 或 None。"""
    key = ("cfnam", tech, ssp, year)
    if key in _CACHE:
        return _CACHE[key]
    p = cf_path_nam(tech, ssp, year)
    res = None
    if p and os.path.isfile(p):
        try:
            ds = xr.open_dataset(p)
            da = ds[f"{tech}_cf"].mean("time")
            res = (da.values, ds["lat"].values, ds["lon"].values)
            ds.close()
        except Exception as e:
            print(f"    [警告] 读取 NAM-12 CF 失败 {tech}: {e}")
    _CACHE[key] = res
    return res


def load_met_grid(country, tech, model, ssp, year):
    """气象年均网格（仅 26 国）。风电=uas+vas 合成 RMS 风速，光伏=rsds。返回 (grid2d, lat1d, lon1d) 或 None。"""
    key = ("met", country, tech, model, ssp, year)
    if key in _CACHE:
        return _CACHE[key]
    res = None
    try:
        if tech == "wind":
            pu, pv = met_path(country, "uas", model, ssp, year), met_path(country, "vas", model, ssp, year)
            if pu and pv and os.path.isfile(pu) and os.path.isfile(pv):
                du = xr.open_dataset(pu)
                dv = xr.open_dataset(pv)
                idx = np.where(du["time"].dt.year == year)[0]
                if len(idx) > 0:
                    g = np.sqrt((du["uas_bcsd"].isel(time=idx) ** 2).mean("time").values
                                + (dv["vas_bcsd"].isel(time=idx) ** 2).mean("time").values)
                    la, lo = du["lat"].values, du["lon"].values
                    res = (g, la, lo)
                du.close(); dv.close()
        else:  # solar
            pr = met_path(country, "rsds", model, ssp, year)
            if pr and os.path.isfile(pr):
                res = _annual_mean_1d(pr, "rsds_bcsd", year)
    except Exception as e:
        print(f"    [警告] 读取气象失败 {country}/{tech}: {e}")
    _CACHE[key] = res
    return res


# ══════════════════════════════════════════════════════════════════════
# 区域归属 & 网格查值
# ══════════════════════════════════════════════════════════════════════


def point_in_bbox(lon, lat, bbox):
    """点是否落在 AREA_DICT 边界框内。bbox=[N,lonW,S,lonE]（0-360）。"""
    north, lon_w, south, lon_e = bbox
    lon360 = np.asarray(lon, dtype=float) % 360.0
    in_lat = (lat <= north) & (lat >= south)
    if lon_w <= lon_e:
        in_lon = (lon360 >= lon_w) & (lon360 <= lon_e)
    else:
        in_lon = (lon360 >= lon_w) | (lon360 <= lon_e)
    return in_lat & in_lon


def get_nam_tree():
    """NAM-12 CF 网格 2D lat/lon 的最近邻树（用 solar 网格；solar/wind 同域）。"""
    if "nam_tree" in _CACHE:
        return _CACHE["nam_tree"]
    grid = load_cf_grid_nam("solar", SSP, YEAR)
    if grid is None:
        _CACHE["nam_tree"] = None
        return None
    _, lat2d, lon2d = grid
    pts = np.column_stack([lat2d.ravel(), lon2d.ravel() % 360.0])
    _CACHE["nam_tree"] = cKDTree(pts)
    return _CACHE["nam_tree"]


def assign_regions(lon, lat):
    """返回每个场站的区域标签：26国名/'China'/'NAM-12'/'outside'。"""
    labels = np.array(["outside"] * len(lon), dtype=object)
    for name, bbox in AREA_DICT.items():  # 含 China
        m = point_in_bbox(lon, lat, bbox) & (labels == "outside")
        labels[m] = name
    # NAM-12：剩余 outside 中距 NAM 网格最近邻 < 阈值者
    tree = get_nam_tree()
    if tree is not None:
        out = labels == "outside"
        if out.any():
            q = np.column_stack([lat[out], lon[out] % 360.0])
            dist, _ = tree.query(q)
            nam_hit = np.zeros(len(lon), dtype=bool)
            nam_hit[out] = dist < NAM_NEAR_THRESH
            labels[nam_hit] = "NAM-12"
    return labels


def lookup_1d(lon, lat, grid, lat1d, lon1d):
    """1D lat/lon 网格 nearest 查值（lon 用周期距离处理 0/360 边界）。"""
    lat1d = np.asarray(lat1d, float); lon1d = np.asarray(lon1d, float)
    ilat = np.argmin(np.abs(lat1d[None, :] - np.asarray(lat, float)[:, None]), axis=1)
    d = np.abs((lon1d % 360.0)[None, :] - (np.asarray(lon, float) % 360.0)[:, None])
    d = np.minimum(d, 360.0 - d)
    ilon = np.argmin(d, axis=1)
    return grid[ilat, ilon]


def lookup_2d(lon, lat, grid, lat2d, lon2d):
    """2D lat/lon 网格（rotated）nearest 查值（cKDTree）。"""
    pts = np.column_stack([lat2d.ravel(), lon2d.ravel() % 360.0])
    tree = cKDTree(pts)
    q = np.column_stack([np.asarray(lat, float), np.asarray(lon, float) % 360.0])
    _, idx = tree.query(q)
    return grid.ravel()[idx]


def query_cf(lon, lat, labels, tech):
    """各场站 2050 年均 CF。区域外/文件缺失 → nan（判为无数据）。"""
    vals = np.full(len(lon), np.nan)
    for name in COUNTRIES_26:
        m = labels == name
        if not m.any():
            continue
        grid = load_cf_grid(name, tech, MODEL, SSP, YEAR)
        if grid is None:
            continue
        vals[m] = lookup_1d(lon[m], lat[m], *grid)
    m = labels == "China"
    if m.any():
        grid = load_cf_grid_china(tech, MODEL, SSP, YEAR)
        if grid is not None:
            vals[m] = lookup_1d(lon[m], lat[m], *grid)
    m = labels == "NAM-12"
    if m.any():
        grid = load_cf_grid_nam(tech, SSP, YEAR)
        if grid is not None:
            vals[m] = lookup_2d(lon[m], lat[m], *grid)
    return vals


def query_met(lon, lat, labels, tech):
    """各场站 2050 年均气象（仅 26 国覆盖）。china/NAM/区域外 → nan（无数据）。"""
    vals = np.full(len(lon), np.nan)
    for name in COUNTRIES_26:
        m = labels == name
        if not m.any():
            continue
        grid = load_met_grid(name, tech, MODEL, SSP, YEAR)
        if grid is None:
            continue
        vals[m] = lookup_1d(lon[m], lat[m], *grid)
    return vals


# ══════════════════════════════════════════════════════════════════════
# 三态分类
# ══════════════════════════════════════════════════════════════════════


def classify(vals, has_data):
    """vals: 年均值(nan=缺失); has_data: 该数据源是否覆盖此场站(bool)。

    返回状态数组：'bad'(0/nan) / 'ok'(正常) / 'nodata'(数据源不覆盖)。
    """
    status = np.array(["ok"] * len(vals), dtype=object)
    status[~has_data] = "nodata"
    covered = has_data & np.isnan(vals)
    status[covered] = "bad"
    zero = has_data & (~np.isnan(vals)) & (vals == 0)
    status[zero] = "bad"
    return status


# ══════════════════════════════════════════════════════════════════════
# 绘图
# ══════════════════════════════════════════════════════════════════════


def setup_basemap(ax):
    ax.set_global()
    ax.add_feature(cfeature.LAND, color="#f5f5f0", zorder=0)
    ax.add_feature(cfeature.OCEAN, color="#d1e8f0", zorder=0)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, color="#888", zorder=1)
    ax.gridlines(linewidth=0.3, color="gray", alpha=0.4)


def plot_panel(ax, lon, lat, status, title):
    """单子图：bad=红(0/nan), ok=灰(正常)。无数据场站不绘制。返回 (n_bad, n_ok)。"""
    setup_basemap(ax)
    n_bad = int(np.sum(status == "bad"))
    n_ok = int(np.sum(status == "ok"))
    n_cov = n_bad + n_ok  # 有数据覆盖的场站数（比例分母）
    pct_bad = (n_bad / n_cov * 100) if n_cov else 0.0
    pct_ok = (n_ok / n_cov * 100) if n_cov else 0.0

    m_ok = status == "ok"
    if n_ok:
        ax.scatter(lon[m_ok], lat[m_ok], s=1.5, c=COLOR_OK, transform=PC, rasterized=True,
                   label=f"正常 {n_ok:,} ({pct_ok:.1f}%)", zorder=3)
    m_bad = status == "bad"
    if n_bad:
        ax.scatter(lon[m_bad], lat[m_bad], s=5, c=COLOR_BAD, transform=PC, rasterized=True,
                   label=f"0/nan {n_bad:,} ({pct_bad:.2f}%)", zorder=4)
    ax.legend(loc="lower left", fontsize=8, markerscale=3, framealpha=0.9, edgecolor="#888")
    ax.set_title(title, fontsize=11, pad=5)
    return n_bad, n_ok


def plot_2x2(data, out_path, model, ssp, year):
    """data = {(dtype, tech): status_array}。dtype∈{met,cf}, tech∈{wind,solar}。"""
    fig, axes = plt.subplots(2, 2, figsize=(20, 14), subplot_kw={"projection": PC})
    panels = [
        (0, 0, "met", "wind", f"气象·风电（bcsd {model}，仅 26 国）"),
        (0, 1, "met", "solar", f"气象·光伏（bcsd {model}，仅 26 国）"),
        (1, 0, "cf", "wind", f"容量因子·风电（cfs {model} + NAM-12 {NAM_MODEL}）"),
        (1, 1, "cf", "solar", f"容量因子·光伏（cfs {model} + NAM-12 {NAM_MODEL}）"),
    ]
    stats = []
    for r, c, dtype, tech, title in panels:
        lon, lat = data["lonlat"][tech]
        n_bad, n_ok = plot_panel(axes[r, c], lon, lat, data[(dtype, tech)], title)
        stats.append((dtype, tech, n_bad, n_ok))

    fig.text(0.5, 0.965,
             f"{ssp} · {year} 年 场站位置 气象/容量因子 为 0 或 nan（红=0/nan，灰=正常；仅画有数据覆盖的场站）",
             ha="center", fontsize=14, weight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")
    return stats


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


def report_stats(stats, out_path, model, ssp, year):
    print(f"\n  场站位置 气象/CF 为 0 或 nan 统计（{model} / {ssp} / {year}，仅计有数据覆盖的场站）")
    print(f"  {'数据':<6}{'技术':<6}{'0/nan':>9}{'正常':>10}{'覆盖':>9}{'异常占比':>9}")
    print("  " + "-" * 50)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dtype", "tech", "n_bad", "n_ok", "n_covered", "bad_ratio"])
        for dtype, tech, bad, ok in stats:
            covered = bad + ok
            ratio = (bad / covered) if covered else 0.0
            print(f"  {dtype:<6}{tech:<6}{bad:>9,}{ok:>10,}{covered:>9,}{ratio:>8.2%}")
            w.writerow([dtype, tech, bad, ok, covered, f"{ratio:.4f}"])
    print(f"  -> {out_path}")


# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════


def main():
    global MODEL, SSP
    parser = argparse.ArgumentParser(description="绘制场站位置气象/容量因子为 0 或 nan 的分布")
    parser.add_argument("--model", default=MODEL, help=f"26国/china CMIP6 模式（默认 {MODEL}；NAM-12 固定 {NAM_MODEL}）")
    parser.add_argument("--ssp", default=SSP, choices=list(SSP_STATION_FILE), help=f"情景（默认 {SSP}）")
    parser.add_argument("--stations", default=None, help="场站 CSV 路径（默认按 --ssp 取 data/stations/）")
    args = parser.parse_args()

    MODEL, SSP = args.model, args.ssp
    csv_path = args.stations or os.path.join(STATIONS_DIR, SSP_STATION_FILE[SSP])
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"场站 CSV 不存在：{csv_path}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"{'=' * 60}\n  气象/CF 为 0 或 nan 场站图：{MODEL} / {SSP} / {YEAR}\n  stations: {csv_path}\n{'=' * 60}")

    stations = load_stations_2050(csv_path)
    for t in ("wind", "solar"):
        print(f"  {YEAR} 年 {t}: {len(stations[t][0]):,} 个场站")

    # 预加载 NAM-12 solar 网格（用于区域归属判断）
    print("  预加载 NAM-12 网格用于区域归属判断 ...")
    get_nam_tree()

    data = {"lonlat": stations}
    for tech in ("wind", "solar"):
        lon, lat = stations[tech]
        print(f"\n  处理 {tech} ...")
        labels = assign_regions(lon, lat)
        # 区域分布
        uniq, counts = np.unique(labels, return_counts=True)
        dist = ", ".join(f"{u}:{c:,}" for u, c in zip(uniq, counts) if u != "outside")
        n_out = int(np.sum(labels == "outside"))
        print(f"    区域归属: {dist}, outside:{n_out:,}")

        cf_vals = query_cf(lon, lat, labels, tech)
        met_vals = query_met(lon, lat, labels, tech)

        cf_has = labels != "outside"           # CF 覆盖 26国+china+NAM
        met_has = np.isin(labels, COUNTRIES_26)  # 气象仅覆盖 26 国
        data[("cf", tech)] = classify(cf_vals, cf_has)
        data[("met", tech)] = classify(met_vals, met_has)

    stats = plot_2x2(data, os.path.join(OUTPUT_DIR, f"zero_or_nan_{MODEL}_{SSP}_{YEAR}.png"), MODEL, SSP, YEAR)
    report_stats(stats, os.path.join(OUTPUT_DIR, f"stats_zero_or_nan_{MODEL}_{SSP}_{YEAR}.csv"), MODEL, SSP, YEAR)


if __name__ == "__main__":
    main()
