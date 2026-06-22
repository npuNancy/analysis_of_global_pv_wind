"""
将 GRW 实测风光场站聚合到粗粒度网格（1° 和 0.1°），统计各网格的场站占用情况与
装机容量，并绘制与 plot_stations_S1_grw_coverage.py 相同类型的全球地图和大区统计图。

网格聚合规则（风光分别处理）：
  - 只要一格内存在场站 → 该格置 1（presence=1），装机容量 = 格内场站之和（GW）
  - 1°  网格: 360×180 格
  - 0.1° 网格: 3600×1800 格
  两网格文件像元值 0=海洋，1–20=大区 ID，同时作为聚合网格和大区归属栅格。

场站数据 = global-renewables-watch (Microsoft, 2024Q2)，装机密度公式与
plot_stations_S1_grw_coverage.py 完全相同。

用法：
    python plot_stations_S1_grw_grid.py               # 出所有统计 + 地图 + 柱状图
    python plot_stations_S1_grw_grid.py --no-map      # 不画地图（柱状图仍出）
    python plot_stations_S1_grw_grid.py --threshold 30  # 占用率阈值（默认 30%）

输出（outputs/plot_stations/plot_stations_S1_grw_grid/）：
  grw_grid_global.csv                  全球统计（占用率 / 格数覆盖率 / 装机覆盖率）
  grw_grid_by_macro_region_1deg.csv    20 大区逐区统计（1°）
  grw_grid_by_macro_region_01deg.csv   20 大区逐区统计（0.1°）
  grw_grid_map_1deg.png                1° 网格装机容量分布图（上=光伏，下=风电）
  grw_grid_map_01deg.png               0.1° 网格装机容量分布图
  grw_grid_macro_bar_1deg.png          20 大区格占用率柱状图（1°）
  grw_grid_macro_bar_01deg.png         20 大区格占用率柱状图（0.1°）
  grw_grid_capacity_by_macro_region.csv  20 大区装机覆盖率统计（场站级，被项目区域覆盖/区内总装机）
  grw_grid_capacity_bar.png              20 大区装机覆盖率柱状图（与 coverage 脚本同口径，只画一张）
"""

import os
import csv
import json
import argparse
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import rasterio

# 复用字体注册和基础地图函数
import RQ0.plot_stations_S1_with_regions as prs
from RQ0.plot_stations_S1_with_regions import PC, setup_basemap, in_any_region, load_nam_domain

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "plot_stations", os.path.splitext(os.path.basename(__file__))[0])
GRW_DIR = os.path.join(BASE_DIR, "data", "ignored", "global-renewables-watch", "data")
SOLAR_GPKG = os.path.join(GRW_DIR, "solar_all_2024q2_v1.gpkg")
WIND_GPKG = os.path.join(GRW_DIR, "wind_all_2024q2_v1.gpkg")
GRID_DIV_NAMES = os.path.join(BASE_DIR, "data", "tracked", "grid_division", "region_id_to_name.json")

GRID_FILES = {
    "1deg": (
        "/data4/yanxiaokai/project_energy_climate"
        "/globally_interconnected_10km/GlobalPotential_10km"
        "/inputs/Global_Grid_Division.tif"
    ),
    "01deg": (
        "/data4/yanxiaokai/project_energy_climate"
        "/globally_interconnected_10km/GlobalPotential_10km"
        "/outputs/Global_Grid_Division.tif"
    ),
}
RES_LABEL = {"1deg": "1°", "01deg": "0.1°"}

# 装机密度参数（与 plot_stations_S1_grw_coverage.py / compute_regional_capacity.py 完全一致）
WIND_DENSITY = 3.68  # MW/km²（陆上风电）
ROTOR_D_M = 100.0  # 叶轮直径 (m)
SPACING_D = 8.0  # 8D × 8D 间距
TURBINE_FOOTPRINT_KM2 = (SPACING_D * ROTOR_D_M / 1000.0) ** 2  # 0.64 km²
WIND_CAP_GW_EACH = TURBINE_FOOTPRINT_KM2 * WIND_DENSITY / 1000.0  # GW/台
PV_PEAK = 161.9  # MW/km²（STC 组件功率密度）
PV_FR = 0.15  # 地面填充率

TECHS = ("solar", "wind")
TECH_LABEL = {"solar": "光伏", "wind": "风电"}

REGION_SHORT_CN = {
    1: "北美",
    2: "中美",
    3: "加勒比",
    4: "南美",
    5: "北欧",
    6: "西欧",
    7: "南欧",
    8: "东欧",
    9: "中亚",
    10: "东亚",
    11: "西亚",
    12: "南亚",
    13: "东南亚",
    14: "美拉",
    15: "澳新",
    16: "北非",
    17: "西非",
    18: "中非",
    19: "东非",
    20: "南非",
}
N_REGIONS = 20


# ══════════════════════════════════════════════════════════════════════
# 装机密度（与 GRW 脚本一致）
# ══════════════════════════════════════════════════════════════════════


def pv_density(lat):
    """光伏装机密度 (MW/km²)，纬度依赖。"""
    lat = np.asarray(lat, dtype=float)
    beta = 0.35396 * np.abs(lat) + 16.84775
    alpha_min = np.maximum(90.0 - np.abs(lat) - 23.45, 0.1)
    beta_r = np.deg2rad(beta)
    alpha_r = np.deg2rad(alpha_min)
    omega = np.cos(beta_r) / (np.cos(beta_r) + np.sin(beta_r) / np.tan(alpha_r))
    return PV_PEAK * omega * PV_FR


# ══════════════════════════════════════════════════════════════════════
# GRW 场站读取（与 plot_stations_S1_grw_coverage.py 完全相同）
# ══════════════════════════════════════════════════════════════════════


def load_grw():
    """读取 GRW 光伏/风电设施，返回 {tech: (lon, lat, cap_gw)}（WGS84 经纬度，质心）。"""
    import geopandas as gpd

    out = {}

    print("  读取光伏多边形 ...")
    solar = gpd.read_file(SOLAR_GPKG)
    cen = solar.geometry.centroid.to_crs("EPSG:4326")
    s_lon, s_lat = cen.x.values, cen.y.values
    s_cap_gw = (solar["area"].values / 1e6) * pv_density(s_lat) / 1000.0
    bad = ~(np.isfinite(s_lon) & np.isfinite(s_lat))
    s_cap_gw = np.where(bad, 0.0, s_cap_gw)
    out["solar"] = (s_lon, s_lat, s_cap_gw)
    print(f"    光伏: {len(s_lon):,} 个多边形, 合计 {s_cap_gw.sum():,.0f} GW")

    print("  读取风机点位 ...")
    wind = gpd.read_file(WIND_GPKG)
    w = wind.geometry.to_crs("EPSG:4326")
    w_lon, w_lat = w.x.values, w.y.values
    w_cap_gw = np.full(len(w_lon), WIND_CAP_GW_EACH)
    out["wind"] = (w_lon, w_lat, w_cap_gw)
    print(f"    风电: {len(w_lon):,} 台风机, 合计 {w_cap_gw.sum():,.0f} GW")

    return out


# ══════════════════════════════════════════════════════════════════════
# 网格聚合
# ══════════════════════════════════════════════════════════════════════


def load_macro_grid(res_key):
    """读取 Grid_Division TIF，返回 (macro_grid[H,W], transform)。
    像元值 0=海洋，1–20=大区 ID。
    """
    path = GRID_FILES[res_key]
    with rasterio.open(path) as src:
        macro_grid = src.read(1).astype(np.int16)
        transform = src.transform
    return macro_grid, transform


def aggregate_to_grid(lon, lat, cap, macro_grid, transform):
    """将场站（lon/lat/cap）聚合到网格。

    返回 (presence[H,W], cap_grid[H,W])：
      presence = 1 表示该格内至少有一个场站；cap_grid = 格内所有场站装机容量之和（GW）。
    """
    H, W = macro_grid.shape
    a, c = transform.a, transform.c  # col direction: a=res, c=lon_min
    e, f = transform.e, transform.f  # row direction: e=-res, f=lat_max

    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    cap = np.asarray(cap, dtype=float)

    col = np.floor((lon - c) / a).astype(np.int32)
    row = np.floor((lat - f) / e).astype(np.int32)

    valid = np.isfinite(lon) & np.isfinite(lat) & (col >= 0) & (col < W) & (row >= 0) & (row < H)
    col, row, cap_v = col[valid], row[valid], cap[valid]

    count = np.zeros((H, W), dtype=np.int32)
    cap_grid = np.zeros((H, W), dtype=np.float64)
    np.add.at(count, (row, col), 1)
    np.add.at(cap_grid, (row, col), cap_v)

    presence = (count > 0).astype(np.int8)
    return presence, cap_grid


def compute_grids(stations, macro_grid, transform):
    """逐技术聚合场站到网格，返回 {tech: (presence[H,W], cap_grid[H,W])}。"""
    res = {}
    for tech in TECHS:
        lon, lat, cap = stations[tech]
        presence, cap_grid = aggregate_to_grid(lon, lat, cap, macro_grid, transform)
        n_occ = int(presence.sum())
        print(f"    {TECH_LABEL[tech]}: {n_occ:,} 格占用，装机 {cap_grid.sum():,.0f} GW")
        res[tech] = (presence, cap_grid)
    return res


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


def region_stats(presence, cap_grid, macro_grid):
    """按大区（1–20）统计占用格数和装机容量。

    返回 (n_land[21], n_occ[21], cap[21])，索引 0 未用，1–20 对应大区。
    """
    n_land = np.zeros(N_REGIONS + 1, dtype=np.int64)
    n_occ = np.zeros(N_REGIONS + 1, dtype=np.int64)
    cap_sum = np.zeros(N_REGIONS + 1, dtype=np.float64)
    for rid in range(1, N_REGIONS + 1):
        mask_land = macro_grid == rid
        mask_occ = mask_land & (presence > 0)
        n_land[rid] = int(mask_land.sum())
        n_occ[rid] = int(mask_occ.sum())
        cap_sum[rid] = float(cap_grid[mask_occ].sum())
    return n_land, n_occ, cap_sum


def report_global(grids_by_res, stations, domain, out_path):
    """全球总量：逐分辨率 × 逐技术的格占用率、格数覆盖率、装机覆盖率。

    指标口径：
      - occ_ratio        = 含场站格 / 陆地格（受网格粒度影响）
      - cell_cover_ratio = 含覆盖场站格 / 含场站格（项目区域覆盖的格点占比；受粒度影响）
      - cap_cover_ratio  = 被覆盖装机 / 总装机（场站级，与 coverage 脚本同口径，不受粒度影响）
    「含覆盖场站格」= 格内至少有一个场站落在项目区域（AREA_DICT + NAM-12）内。
    cell_cover_ratio 即「项目区域覆盖的格点 / 含场站的格点」，对应站点级覆盖率（见 coverage
    脚本 grw_coverage_global.csv 的 n_cover_ratio=0.9680）的网格口径版本。
    """
    # 预算每个技术的 covered 掩码、装机覆盖率（所有场站口径）与 covered 子集
    glob_cov = {}
    covered_sub = {}
    for tech in TECHS:
        lon, lat, cap = stations[tech]
        cap = np.where(np.isfinite(cap), cap, 0.0)
        covered = in_any_region(lon, lat, domain)
        ct = float(cap.sum())
        ci = float(cap[covered].sum())
        glob_cov[tech] = (ct, ci, ci / ct if ct else 0.0)
        covered_sub[tech] = (lon[covered], lat[covered], cap[covered])
    ct_all = sum(glob_cov[t][0] for t in TECHS)
    ci_all = sum(glob_cov[t][1] for t in TECHS)
    glob_cov["all"] = (ct_all, ci_all, ci_all / ct_all if ct_all else 0.0)

    print(f"\n  ── 全球装机覆盖率（所有场站，与 coverage 脚本同口径）──")
    print(f"  {'tech':<8}{'装机GW':>11}{'被覆盖GW':>11}{'覆盖率':>8}")
    print("  " + "-" * 38)
    for tech in TECHS:
        ct, ci, cr = glob_cov[tech]
        print(f"  {TECH_LABEL[tech]:<8}{ct:>11,.0f}{ci:>11,.0f}{cr:>7.1%}")
    print(f"  {'合计':<8}{ct_all:>11,.0f}{ci_all:>11,.0f}{glob_cov['all'][2]:>7.1%}")

    print(f"\n  ── 全球格占用率 / 格数覆盖率（各分辨率）──")
    header = [
        "res",
        "tech",
        "n_cells_total",
        "n_cells_occupied",
        "occ_ratio",
        "n_cells_covered",
        "cell_cover_ratio",
        "cap_total_gw",
        "cap_cover_ratio",
    ]
    rows = []
    for res_key in ("1deg", "01deg"):
        macro_grid, transform, grids = grids_by_res[res_key]
        H, W = macro_grid.shape
        n_total_land = int((macro_grid > 0).sum())
        rl = RES_LABEL[res_key]
        print(f"\n  {rl} 网格（{W}×{H} = {H*W:,} 格，陆地 {n_total_land:,} 格）")

        combined_occ = np.zeros((H, W), dtype=np.int8)
        combined_cov = np.zeros((H, W), dtype=np.int8)
        combined_cap = np.zeros((H, W), dtype=np.float64)
        for tech in TECHS:
            presence, cap_grid = grids[tech]
            lon_c, lat_c, cap_c = covered_sub[tech]
            p_cov, _ = aggregate_to_grid(lon_c, lat_c, cap_c, macro_grid, transform)
            n_occ = int(presence.sum())
            n_cov = int(p_cov.sum())
            cap_tot = float(cap_grid.sum())
            occ_r = n_occ / n_total_land if n_total_land else 0.0
            cell_cov_r = n_cov / n_occ if n_occ else 0.0
            cap_cov_r = glob_cov[tech][2]
            print(
                f"    {TECH_LABEL[tech]:<4}: 占用 {n_occ:>7,} 格({occ_r:5.1%})，"
                f"含覆盖 {n_cov:>7,} 格({cell_cov_r:5.1%})，"
                f"装机 {cap_tot:>9,.0f} GW(覆盖 {cap_cov_r:5.1%})"
            )
            rows.append(
                (
                    rl,
                    tech,
                    n_total_land,
                    n_occ,
                    f"{occ_r:.4f}",
                    n_cov,
                    f"{cell_cov_r:.4f}",
                    f"{cap_tot:.4f}",
                    f"{cap_cov_r:.4f}",
                )
            )
            combined_occ = np.maximum(combined_occ, presence)
            combined_cov = np.maximum(combined_cov, p_cov)
            combined_cap += cap_grid
        n_occ_combined = int(combined_occ.sum())
        n_cov_combined = int(combined_cov.sum())
        cap_tot_combined = float(combined_cap[combined_occ > 0].sum())
        occ_r_combined = n_occ_combined / n_total_land if n_total_land else 0.0
        cell_cov_r_combined = n_cov_combined / n_occ_combined if n_occ_combined else 0.0
        cap_cov_r_all = glob_cov["all"][2]
        print(
            f"    {'合计':<4}: 占用 {n_occ_combined:>7,} 格({occ_r_combined:5.1%})，"
            f"含覆盖 {n_cov_combined:>7,} 格({cell_cov_r_combined:5.1%})，"
            f"装机 {cap_tot_combined:>9,.0f} GW(覆盖 {cap_cov_r_all:5.1%})"
        )
        rows.append(
            (
                rl,
                "all",
                n_total_land,
                n_occ_combined,
                f"{occ_r_combined:.4f}",
                n_cov_combined,
                f"{cell_cov_r_combined:.4f}",
                f"{cap_tot_combined:.4f}",
                f"{cap_cov_r_all:.4f}",
            )
        )

    with open(out_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)
    print(f"\n  -> {out_path}")


def report_by_macro_region(macro_grid, grids, names, out_path, res_label):
    """20 大区逐区统计（格占用数、装机容量），打印并写 CSV，返回 region_rows 供柱状图使用。

    region_rows 每项: (rid, short_name, n_land, n_occ_solar, cap_solar,
                                         n_occ_wind, cap_wind, n_occ_all, cap_all, occ_ratio)
    """
    n_land_s, n_occ_s, cap_s = region_stats(*grids["solar"], macro_grid)
    n_land_w, n_occ_w, cap_w = region_stats(*grids["wind"], macro_grid)

    print(f"\n  ── 20 大区逐区统计（{res_label}）──")
    print(
        f"  {'id':<3}{'region':<10}"
        f"{'n陆格':>8}{'n光占':>8}{'n风占':>8}{'n合占':>8}{'占用率':>7}"
        f"  {'光伏GW':>9}{'风电GW':>9}{'合计GW':>9}"
    )
    print("  " + "-" * 78)

    region_rows = []
    with open(out_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(
            [
                "region_id",
                "region_name",
                "n_land_cells",
                "n_occ_solar",
                "n_occ_wind",
                "n_occ_combined",
                "occ_ratio",
                "cap_solar_gw",
                "cap_wind_gw",
                "cap_total_gw",
            ]
        )
        for rid in range(1, N_REGIONS + 1):
            nl = int(n_land_s[rid])  # n_land same for solar/wind (same grid)
            ns = int(n_occ_s[rid])
            nw = int(n_occ_w[rid])
            cs = float(cap_s[rid])
            cw = float(cap_w[rid])
            # combined: cells occupied by solar OR wind
            mask_s = (grids["solar"][0] > 0) & (macro_grid == rid)
            mask_w = (grids["wind"][0] > 0) & (macro_grid == rid)
            n_all = int((mask_s | mask_w).sum())
            cap_all = cs + cw  # sum, not double-count since cap is per-tech
            occ_r = n_all / nl if nl else 0.0
            name = names.get(rid, f"region {rid}")
            short = REGION_SHORT_CN.get(rid, str(rid))
            print(
                f"  {rid:<3}{short:<10}"
                f"{nl:>8,}{ns:>8,}{nw:>8,}{n_all:>8,}{occ_r:>7.1%}"
                f"  {cs:>9,.1f}{cw:>9,.1f}{cap_all:>9,.1f}"
            )
            wr.writerow([rid, name, nl, ns, nw, n_all, f"{occ_r:.4f}", f"{cs:.4f}", f"{cw:.4f}", f"{cap_all:.4f}"])
            region_rows.append((rid, short, nl, ns, nw, n_all, cs, cw, cap_all, occ_r))

        # 合计行
        nl_tot = sum(r[2] for r in region_rows)
        n_all_tot = sum(r[5] for r in region_rows)
        cap_tot = sum(r[8] for r in region_rows)
        occ_r_tot = n_all_tot / nl_tot if nl_tot else 0.0
        wr.writerow(["ALL", "合计", nl_tot, "", "", n_all_tot, f"{occ_r_tot:.4f}", "", "", f"{cap_tot:.4f}"])
    print("  " + "-" * 78)
    print(
        f"  {'':13}{'合计':<4} {nl_tot:>8,}{'':8}{'':8}{n_all_tot:>8,}{occ_r_tot:>7.1%}"
        f"  {'':9}{'':9}{cap_tot:>9,.1f}"
    )
    print(f"  -> {out_path}")
    return region_rows


# ── 装机容量（场站级，与聚合网格粒度无关）──────────────────────────────


def assign_region(lon, lat, region_grid, transform):
    """按经纬度在 20 大区栅格中查表，返回每个点的大区编号 (1–20)；越界/无效坐标记 0。"""
    a, c = transform.a, transform.c
    e, f = transform.e, transform.f
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    finite = np.isfinite(lon) & np.isfinite(lat)
    col = np.floor((lon - c) / a).astype(int)
    row = np.floor((lat - f) / e).astype(int)
    H, W = region_grid.shape
    col = np.clip(col, 0, W - 1)
    row = np.clip(row, 0, H - 1)
    out = region_grid[row, col].astype(int)
    out[~finite] = 0
    return out


def compute_coverage_by_region(stations, domain, region_grid, transform):
    """场站级：每个大区内，被项目区域覆盖的装机 vs 区内总装机。

    与 plot_stations_S1_grw_coverage.py 完全同口径：covered = 场站质心落在任一 AREA_DICT
    框或 NAM-12 弯曲域内（in_any_region）。大区归属由 region_grid 查表。
    装机按场站求和，与聚合网格粒度无关。

    返回 (cap_tot_by, cap_in_by)，各为 {tech: np.ndarray[21]}（索引 0 未用，1–20 大区）。
    """
    cap_tot_by, cap_in_by = {}, {}
    for tech in TECHS:
        lon, lat, cap = stations[tech]
        cap = np.where(np.isfinite(cap), cap, 0.0)
        covered = in_any_region(lon, lat, domain)
        rid = assign_region(lon, lat, region_grid, transform)
        ct = np.zeros(N_REGIONS + 1, dtype=np.float64)
        ci = np.zeros(N_REGIONS + 1, dtype=np.float64)
        valid = rid > 0
        np.add.at(ct, rid[valid], cap[valid])
        ins = valid & covered
        np.add.at(ci, rid[ins], cap[ins])
        cap_tot_by[tech] = ct
        cap_in_by[tech] = ci
    return cap_tot_by, cap_in_by


def report_coverage_by_region(cap_tot_by, cap_in_by, names, out_path):
    """20 大区装机覆盖率：区内被项目区域覆盖的装机 / 区内总装机。打印并写 CSV。

    返回 region_rows，每项: (rid, short_name, cap_total_gw, cap_inside_gw, cover_ratio)
    """
    print(f"\n  ── 20 大区装机覆盖率（被项目区域覆盖的装机 / 区内总装机；与 coverage 脚本同口径）──")
    print(f"  {'id':<3}{'region':<10}{'区内总装机GW':>13}{'被覆盖GW':>11}{'覆盖率':>8}")
    print("  " + "-" * 45)

    region_rows = []
    CT_tot = CI_tot = 0.0
    with open(out_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["region_id", "region_name", "cap_total_gw", "cap_inside_gw", "cap_cover_ratio"])
        for rid in range(1, N_REGIONS + 1):
            ct = float(cap_tot_by["solar"][rid] + cap_tot_by["wind"][rid])
            ci = float(cap_in_by["solar"][rid] + cap_in_by["wind"][rid])
            cr = ci / ct if ct else 0.0
            short = REGION_SHORT_CN.get(rid, str(rid))
            name = names.get(rid, f"region {rid}")
            print(f"  {rid:<3}{short:<10}{ct:>13,.1f}{ci:>11,.1f}{cr:>7.1%}")
            wr.writerow([rid, name, f"{ct:.4f}", f"{ci:.4f}", f"{cr:.4f}"])
            region_rows.append((rid, short, ct, ci, cr))
            CT_tot += ct
            CI_tot += ci
        cr_tot = CI_tot / CT_tot if CT_tot else 0.0
        wr.writerow(["ALL", "合计", f"{CT_tot:.4f}", f"{CI_tot:.4f}", f"{cr_tot:.4f}"])
    print("  " + "-" * 45)
    print(f"  {'':13}{'合计':<10}{CT_tot:>13,.1f}{CI_tot:>11,.1f}{cr_tot:>7.1%}")
    print(f"  -> {out_path}")
    return region_rows


# ══════════════════════════════════════════════════════════════════════
# 绘图
# ══════════════════════════════════════════════════════════════════════


def _cap_norm(cap_grid):
    """构建用于 imshow 的 LogNorm；最大值兜底避免 vmax=0 报错。"""
    vmax = float(cap_grid.max())
    if vmax <= 0:
        vmax = 1.0
    return mcolors.LogNorm(vmin=1e-4, vmax=vmax)


def plot_grid_map(grids, macro_grid, names, out_path, res_label):
    """两面板（上=光伏，下=风电）：各网格装机容量（GW）的全球分布图。"""
    H, W = macro_grid.shape
    fig, axes = plt.subplots(2, 1, figsize=(16, 16), subplot_kw={"projection": PC})

    for ax, tech in zip(axes, TECHS):
        setup_basemap(ax)
        presence, cap_grid = grids[tech]

        cap_plot = np.where(presence > 0, cap_grid, np.nan)
        norm = _cap_norm(cap_grid[presence > 0])

        cmap = plt.cm.YlOrRd.copy()
        cmap.set_bad(color="white", alpha=0)
        im = ax.imshow(
            cap_plot,
            origin="upper",
            extent=[-180, 180, -90, 90],
            transform=PC,
            cmap=cmap,
            norm=norm,
            interpolation="nearest",
            zorder=3,
        )
        cbar = plt.colorbar(im, ax=ax, shrink=0.55, pad=0.02, orientation="vertical")
        cbar.set_label("装机容量（GW/格）", fontsize=9)
        cbar.ax.tick_params(labelsize=7.5)

        n_occ = int(presence.sum())
        cap_tot = float(cap_grid.sum())
        ax.set_title(
            f"GRW {TECH_LABEL[tech]}（{res_label}网格）：{n_occ:,} 格占用，合计 {cap_tot:,.0f} GW",
            fontsize=13,
            pad=8,
        )

    plt.tight_layout()
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")


def plot_macro_bar(region_rows, out_path, res_label, threshold=30.0):
    """20 大区格占用率柱状图：每区 1 根柱，按占用率降序排列。

    柱高 = 该大区陆地格中有场站的比例（solar OR wind）；颜色按 RdYlGn 着色。
    x 轴下方标注区内合计装机容量（GW）；在 threshold 处画红色阈值线。
    """
    rows = sorted(region_rows, key=lambda r: r[9], reverse=True)  # 按 occ_ratio 降序
    labels = [f"{r[1]}\n{r[8]:,.0f}GW" for r in rows]
    occ_pct = np.array([r[9] * 100.0 for r in rows])
    n = len(rows)
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(10.0, 4.4))
    for i in range(n):
        if i % 2 == 0:
            ax.axvspan(i - 0.5, i + 0.5, color="#f4f4f2", zorder=0)

    colors = plt.cm.RdYlGn(occ_pct / 100.0)
    ax.bar(x, occ_pct, width=0.72, color=colors, edgecolor="#666666", linewidth=0.4, zorder=3)

    for xi, v in zip(x, occ_pct):
        ax.text(xi, v + 0.5, f"{v:.1f}%", ha="center", va="bottom", fontsize=6.5, color="#222222", zorder=4)

    ax.axhline(threshold, color="#d62728", lw=1.3, ls="--", zorder=5)
    ax.text(
        n - 0.45,
        threshold + 0.5,
        f"{threshold:.0f}% 阈值",
        color="#d62728",
        ha="right",
        va="bottom",
        fontsize=7.5,
        zorder=6,
    )

    ax.set_ylim(0, max(occ_pct.max() * 1.18, threshold * 1.3))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_ylabel("陆地格占用率（有场站的格/总陆地格）", fontsize=9)
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    for tick, v in zip(ax.get_xticklabels(), occ_pct):
        if v < threshold:
            tick.set_color("#d62728")
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#dddddd", linewidth=0.6, zorder=1)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_title(
        f"全球 20 大区 GRW 现状风光场站陆地格占用率（{res_label}）" "（x 轴下方为区内合计装机 GW）",
        fontsize=10.5,
        pad=8,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out_path}")


def plot_capacity_bar(region_rows, out_path, threshold=60.0):
    """20 大区装机覆盖率柱状图：每区 1 根柱（不堆叠），按覆盖率降序排列。

    与 plot_stations_S1_grw_coverage.py 的 grw_coverage_macro_bar.png 同口径：
    柱高 = 该大区被项目区域覆盖的装机容量比例（%）；颜色按覆盖率由低(红)到高(绿)着色；
    柱顶标注覆盖率 %，x 轴标签下方附区内总装机(GW)；在 threshold（默认 60%）处画红色横线，
    覆盖率低于该阈值的大区，横坐标名称标红。装机覆盖率为场站级统计，与聚合网格粒度无关，故只画一张。
    """
    rows = sorted(region_rows, key=lambda r: r[4], reverse=True)  # 按 cover_ratio 降序
    labels = [f"{REGION_SHORT_CN.get(r[0], str(r[0]))}\n{r[2]:,.0f}GW" for r in rows]
    cap_ratio = np.array([r[4] for r in rows]) * 100.0
    n = len(rows)
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(10.0, 4.4))
    for i in range(n):  # 交替背景带
        if i % 2 == 0:
            ax.axvspan(i - 0.5, i + 0.5, color="#f4f4f2", zorder=0)

    colors = plt.cm.RdYlGn(cap_ratio / 100.0)
    ax.bar(x, cap_ratio, width=0.72, color=colors, edgecolor="#666666", linewidth=0.4, zorder=3)

    for xi, r in zip(x, cap_ratio):
        ax.text(xi, r + 1.2, f"{r:.0f}%", ha="center", va="bottom", fontsize=6.5, color="#222222", zorder=4)

    # 阈值红线（默认 60%，与 coverage 脚本一致）
    ax.axhline(threshold, color="#d62728", lw=1.3, ls="--", zorder=5)
    ax.text(
        n - 0.45,
        threshold + 0.8,
        f"{threshold:.0f}% 阈值",
        color="#d62728",
        ha="right",
        va="bottom",
        fontsize=7.5,
        zorder=6,
    )

    ax.set_ylim(0, 108)
    ax.set_yticks(range(0, 101, 20))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 20)])
    ax.set_ylabel("装机容量覆盖率（被项目区域覆盖）", fontsize=9)
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    for tick, r in zip(ax.get_xticklabels(), cap_ratio):
        if r < threshold:
            tick.set_color("#d62728")
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#dddddd", linewidth=0.6, zorder=1)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_title(
        "全球 20 大区：GRW 现状装机容量被项目区域覆盖的比例" "（场站级，与网格粒度无关；x 轴下方为区内总装机 GW）",
        fontsize=10.5,
        pad=8,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out_path}")


# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════


def main():
    ap = argparse.ArgumentParser(description="GRW 风光场站网格聚合统计与可视化（1° / 0.1°）")
    ap.add_argument("--no-map", action="store_true", help="不画地图（柱状图和 CSV 仍输出）")
    ap.add_argument(
        "--threshold",
        type=float,
        default=30.0,
        help="占用率阈值（%%，默认 30）：占用率柱状图在此处画红线，低于该值的大区名称标红",
    )
    ap.add_argument(
        "--cap-threshold",
        type=float,
        default=60.0,
        help="装机覆盖率阈值（%%，默认 60）：覆盖率柱状图在此处画红线，低于该值的大区名称标红（与 coverage 脚本一致）",
    )
    args = ap.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"{'=' * 64}\n  GRW 风光场站网格聚合统计（1° / 0.1°）\n{'=' * 64}")

    # 读取场站数据
    print("\n[1/3] 读取 GRW 场站数据")
    stations = load_grw()

    # 读取 20 大区名称
    with open(GRID_DIV_NAMES, encoding="utf-8") as f:
        names = {int(k): v for k, v in json.load(f).items()}

    # 逐分辨率聚合
    grids_by_res = {}
    for res_key in ("1deg", "01deg"):
        rl = RES_LABEL[res_key]
        print(f"\n[2/3] 聚合到 {rl} 网格")
        macro_grid, transform = load_macro_grid(res_key)
        grids = compute_grids(stations, macro_grid, transform)
        grids_by_res[res_key] = (macro_grid, transform, grids)

    # 全球总量 CSV（含全球装机覆盖率）
    print("\n[3/3] 统计输出")
    domain = load_nam_domain()
    report_global(grids_by_res, stations, domain, os.path.join(OUTPUT_DIR, "grw_grid_global.csv"))

    # 逐分辨率：大区统计 + 柱状图 + 地图
    for res_key in ("1deg", "01deg"):
        rl = RES_LABEL[res_key]
        macro_grid, transform, grids = grids_by_res[res_key]

        region_rows = report_by_macro_region(
            macro_grid,
            grids,
            names,
            os.path.join(OUTPUT_DIR, f"grw_grid_by_macro_region_{res_key}.csv"),
            rl,
        )
        plot_macro_bar(
            region_rows,
            os.path.join(OUTPUT_DIR, f"grw_grid_macro_bar_{res_key}.png"),
            rl,
            threshold=args.threshold,
        )

        if not args.no_map:
            plot_grid_map(
                grids,
                macro_grid,
                names,
                os.path.join(OUTPUT_DIR, f"grw_grid_map_{res_key}.png"),
                rl,
            )

    # 装机覆盖率统计（场站级，与 coverage 脚本同口径，不受网格大小影响）
    # 用 0.1° 网格做大区归属查表（边界归属最精细）；1° 与 0.1° 结果一致
    print("\n  装机覆盖率统计（场站级，与 coverage 脚本同口径）")
    cap_grid, cap_transform = grids_by_res["01deg"][0], grids_by_res["01deg"][1]
    cap_tot_by, cap_in_by = compute_coverage_by_region(stations, domain, cap_grid, cap_transform)
    region_rows = report_coverage_by_region(
        cap_tot_by,
        cap_in_by,
        names,
        os.path.join(OUTPUT_DIR, "grw_grid_capacity_by_macro_region.csv"),
    )
    plot_capacity_bar(
        region_rows,
        os.path.join(OUTPUT_DIR, "grw_grid_capacity_bar.png"),
        threshold=args.cap_threshold,
    )

    print(f"\n{'=' * 64}\n  完成！输出目录：{OUTPUT_DIR}\n{'=' * 64}")


if __name__ == "__main__":
    main()
