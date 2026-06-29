"""
Q2 分析：气象(bcsd)数据「边界 nan」的产生机制。

背景
----
plot_stations_S0E2_zero_or_nan.py 发现场站气象/CF 为 0 或 nan 有两类：
  第一类：海陆分界线（海岸带）—— 已由 plot_stations_S0E1_sea_mask 分析。
  第二类：每个气象数据块（每国 bcsd 输出）的边界处 —— 机制不明，本脚本专攻。

核心思路
--------
bcsd 气象在每个国家是一个矩形经纬度网格（AREA_DICT bbox），其中 nan 格点有两类来源：
  (a) 海洋格点：ERA5-Land 本身在海洋缺测（=第一类海岸线 nan）；
  (b) 数据边界：网格边缘一圈格点，落在陆地上却无数据（=第二类边界 nan）。

用全球海陆掩码 data/era5land/lsm_0.1x0.1.nc（lsm>=0.5=陆，<0.5=海）逐格点判定，
即可把 bcsd 的 nan 拆成「陆地 nan(第二类)」与「海洋 nan(第一类)」，
并测量网格四边 nan 带宽度、统计落在陆地边界 nan 上的场站数。

结论（详见 REPORT.md）：第二类边界 nan 的本质是 bcsd Step6 末尾用
`mask_src = obs_hi.isel(time=0).notnull()` 做覆盖掩码（part.where(mask_src)），
而 obs_hi(ERA5-Land 区域观测) 的有效覆盖受 GCM 粗网格双线性插值边缘外推失败 +
区域裁剪限制，导致每国网格边缘一圈（宽度 ~ GCM 分辨率，不对称）在掩码中为 False → nan。
这些格点经 lsm 验证绝大多数是陆地（如 Germany 南缘 lat=47 行 lsm≈1.0 却全 nan）。

用法: python q2_boundary_nan.py
"""
import os
import sys
import csv
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 复用 plot_stations_S0E2 的路径/区域归属/查值逻辑，保证与原图统计口径一致
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plot_stations_S0E2_zero_or_nan as P  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
LSM_NC = os.path.join(P.PROJECT_ROOT, "data", "era5land", "lsm_0.1x0.1.nc")
YEAR = P.YEAR

# 字体
font_path = os.path.join(P.PROJECT_ROOT, "data", "SourceHanSansSC-Normal.otf")
if os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    plt.rcParams["font.family"] = [fm.FontProperties(fname=font_path).get_name()]
plt.rcParams["axes.unicode_minus"] = False

LSM_LAND = 0.5  # lsm >= 0.5 视为陆地


# ─────────────────────────────────────────────────────────────
# 全球 lsm 查值
# ─────────────────────────────────────────────────────────────
_LSM_CACHE = None


def load_lsm_grid():
    """全球 lsm：行=latitude(90→-90)，列=longitude(0→360)。"""
    global _LSM_CACHE
    if _LSM_CACHE is not None:
        return _LSM_CACHE
    ds = xr.open_dataset(LSM_NC)
    arr = ds["lsm"].isel(time=0).values
    lat = ds["latitude"].values   # 90 -> -90
    lon = ds["longitude"].values  # 0 -> 360
    ds.close()
    _LSM_CACHE = (arr, lat, lon)
    return _LSM_CACHE


def lsm_at(la2d, lo2d):
    """对 (nlat,nlon) 经纬度网格，最近邻查全球 lsm（0.1° 对齐）。lon 自动 %360。"""
    arr, lat, lon = load_lsm_grid()
    ilat = np.argmin(np.abs(lat[:, None] - la2d.ravel()[None, :]), axis=0)
    ilon = np.argmin(np.abs(lon[:, None] - (lo2d.ravel() % 360.0)[None, :]), axis=0)
    return arr[ilat, ilon].reshape(la2d.shape)


# ─────────────────────────────────────────────────────────────
# 单国 bcsd 变量年均 nan 掩码
# ─────────────────────────────────────────────────────────────


def met_nan_mask(country, var):
    """读某国某变量(var in uas/vas/rsds) 2050 年均的 nan 掩码 + lat1d/lon1d。无数据返回 None。"""
    d = P.area_to_dir(country)
    pat = os.path.join(P.BCSD_DIR, P.MODEL, d, P.MODEL, f"{var}_3h_bcsd_on_0p1deg_{d}_{P.MODEL}_{P.SSP}_*.nc")
    p = P._pick_year_file(pat, YEAR)
    if not (p and os.path.isfile(p)):
        return None
    ds = xr.open_dataset(p)
    idx = np.where(ds["time"].dt.year == YEAR)[0]
    if len(idx) == 0:
        ds.close()
        return None
    da = ds[f"{var}_bcsd"].isel(time=idx).mean("time")
    g = np.asarray(da.values)
    la, lo = np.asarray(da["lat"].values), np.asarray(da["lon"].values)
    ds.close()
    return np.isnan(g), la, lo


def edge_band_widths(nanmask):
    """测量网格四边连续全-nan 的带宽度(格点数)。
    返回 (top, bottom, left, right) —— 纬度轴高索引端/低索引端、经度轴高/低索引端
    从外向内连续全 nan 的行/列数（即有效数据实际覆盖比标称网格内缩的格数）。"""
    nr, nc = nanmask.shape
    has_val_row = (~nanmask).any(axis=1)   # 该行是否至少有1个有效值
    has_val_col = (~nanmask).any(axis=0)
    if not has_val_row.any() or not has_val_col.any():
        return nr, nr, nc, nc  # 全 nan
    bottom = int(np.argmax(has_val_row))                 # 低索引端连续 nan 行数
    top = int(np.argmax(has_val_row[::-1]))              # 高索引端连续 nan 行数
    left = int(np.argmax(has_val_col))                   # 低索引端连续 nan 列数
    right = int(np.argmax(has_val_col[::-1]))            # 高索引端连续 nan 列数
    return top, bottom, left, right


# ─────────────────────────────────────────────────────────────
# 主分析
# ─────────────────────────────────────────────────────────────


def analyze_grids():
    """逐国逐变量：nan 拆成 陆地nan/海洋nan，并测边界带宽度。"""
    rows = []
    for country in P.COUNTRIES_26:
        for var, tech in (("uas", "wind"), ("rsds", "solar")):
            res = met_nan_mask(country, var)
            if res is None:
                rows.append([country, tech, "NO_DATA", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
                continue
            nanmask, la, lo = res
            LA, LO = np.meshgrid(la, lo, indexing="ij")
            lsm = lsm_at(LA, LO)
            n_total = nanmask.size
            n_nan = int(nanmask.sum())
            n_nan_land = int((nanmask & (lsm >= LSM_LAND)).sum())   # 第二类：陆地边界 nan
            n_nan_sea = int((nanmask & (lsm < LSM_LAND)).sum())     # 第一类：海洋海岸 nan
            top, bottom, left, right = edge_band_widths(nanmask)
            dlat = abs(float(la[1] - la[0]))
            dlon = abs(float(lo[1] - lo[0]))
            rows.append([
                country, tech, "OK",
                n_total, n_nan, n_nan_land, n_nan_sea,
                f"{n_nan / n_total:.4f}",
                f"{n_nan_land / max(n_nan, 1):.4f}",   # 陆地nan占nan比例
                f"{top * dlat:.2f}", f"{bottom * dlat:.2f}",   # 上/下边界带宽度(°)
                f"{left * dlon:.2f}", f"{right * dlon:.2f}",   # 左/右边界带宽度(°)
            ])
    header = ["country", "tech", "status", "n_grid", "n_nan", "n_nan_land", "n_nan_sea",
              "nan_ratio", "land_nan_frac_of_nan", "band_top_deg", "band_bot_deg",
              "band_left_deg", "band_right_deg"]
    out = os.path.join(OUT_DIR, "q2_grid_nan_landsea_by_country.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  -> {out}")
    return rows, header


def analyze_stations():
    """场站层面：26 国场站落在 bcsd nan 上的，区分陆地 nan(第二类) / 海洋 nan(第一类)。"""
    csv_path = os.path.join(P.STATIONS_DIR, P.SSP_STATION_FILE[P.SSP])
    stations = P.load_stations_2050(csv_path)
    out_rows = []
    for tech, var in (("wind", "uas"), ("solar", "rsds")):
        lon, lat = stations[tech]
        labels = P.assign_regions(lon, lat)
        m26 = np.isin(labels, P.COUNTRIES_26)
        # 逐国查气象值 + lsm
        is_nan = np.zeros(len(lon), bool)
        is_land = np.zeros(len(lon), bool)  # 该场站所在格点 lsm 是否陆地
        for country in P.COUNTRIES_26:
            mc = m26 & (labels == country)
            if not mc.any():
                continue
            res = met_nan_mask(country, var)
            if res is None:
                continue
            nanmask, la, lo = res
            vals = P.lookup_1d(lon[mc], lat[mc], (~nanmask).astype(float), la, lo)  # 1=有效 0=nan
            LA, LO = np.meshgrid(la, lo, indexing="ij")
            lsm_grid = lsm_at(LA, LO)
            lsm_vals = P.lookup_1d(lon[mc], lat[mc], lsm_grid, la, lo)
            is_nan[mc] = vals == 0
            is_land[mc] = lsm_vals >= LSM_LAND
        cov = m26
        n_cov = int(cov.sum())
        n_nan = int((cov & is_nan).sum())
        n_nan_land = int((cov & is_nan & is_land).sum())   # 第二类
        n_nan_sea = int((cov & is_nan & ~is_land).sum())    # 第一类
        out_rows.append([tech, n_cov, n_nan, n_nan_land, n_nan_sea,
                         f"{n_nan / max(n_cov, 1):.4f}",
                         f"{n_nan_land / max(n_nan, 1):.4f}"])
    header = ["tech", "n_covered(26国)", "n_nan", "n_nan_land(type2)", "n_nan_sea(type1)",
              "nan_ratio", "land_nan_frac_of_nan"]
    out = os.path.join(OUT_DIR, "q2_stations_nan_landsea.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(out_rows)
    print(f"  -> {out}")
    return out_rows, header


def plot_landsea_nan(rows, header):
    """各国 wind/solar 的 nan 中陆地(第二类)占比条形图。"""
    hi = {h: i for i, h in enumerate(header)}
    data = {}
    for r in rows:
        if r[hi["status"]] != "OK":
            continue
        country, tech = r[0], r[1]
        land_frac = float(r[hi["land_nan_frac_of_nan"]])
        data.setdefault(tech, {})[country] = land_frac
    countries = sorted({r[0] for r in rows if r[hi["status"]] == "OK"})
    fig, ax = plt.subplots(figsize=(max(10, len(countries) * 0.45), 6))
    x = np.arange(len(countries))
    w = 0.38
    for i, tech in enumerate(("wind", "solar")):
        vals = [data.get(tech, {}).get(c, np.nan) for c in countries]
        ax.bar(x + (i - 0.5) * w, vals, w, label={"wind": "风电(uas)", "solar": "光伏(rsds)"}[tech])
    ax.set_xticks(x)
    ax.set_xticklabels(countries, rotation=60, ha="right", fontsize=9)
    ax.set_ylabel("陆地 nan 占全部 nan 的比例\n(越高 → 第二类「数据边界」nan 越主导)")
    ax.set_title(f"Q2：各国 bcsd 气象 nan 中「陆地 nan(第二类·数据边界)」占比（{P.MODEL}/{P.SSP}/{YEAR}）\n"
                 f"比例≈1 → nan 几乎全是陆地边界效应(非海洋)；比例≈0 → nan 主要是海岸线海洋缺测")
    ax.axhline(0.5, color="gray", ls="--", lw=0.8)
    ax.set_ylim(0, 1.05)
    ax.legend()
    plt.tight_layout()
    out = os.path.join(OUT_DIR, "q2_land_nan_fraction_by_country.png")
    plt.savefig(out, dpi=160)
    plt.close()
    print(f"  -> {out}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"{'='*60}\n  Q2 分析：bcsd 气象边界 nan 机制（{P.MODEL}/{P.SSP}/{YEAR}）\n{'='*60}")
    print("\n[1/3] 预加载 lsm 与 NAM 网格 ...")
    load_lsm_grid()
    P.get_nam_tree()
    print("\n[2/3] 逐国网格 nan 陆/海拆分 ...")
    rows, header = analyze_grids()
    # 汇总（列: country0 tech1 status2 n_grid3 n_nan4 n_nan_land5 n_nan_sea6 ...）
    ok = [r for r in rows if r[2] != "NO_DATA"]
    tot_nan = sum(int(r[4]) for r in ok)
    tot_land = sum(int(r[5]) for r in ok)
    tot_sea = sum(int(r[6]) for r in ok)
    print(f"\n  汇总(全部国家全部变量): nan格点 {tot_nan:,} = 陆地(第二类) {tot_land:,} "
          f"({tot_land/max(tot_nan,1)*100:.1f}%) + 海洋(第一类) {tot_sea:,} ({tot_sea/max(tot_nan,1)*100:.1f}%)")
    print("\n[3/3] 场站层面 nan 陆/海拆分 + 绘图 ...")
    analyze_stations()
    plot_landsea_nan(rows, header)
    print("\n  Q2 完成。")


if __name__ == "__main__":
    main()
