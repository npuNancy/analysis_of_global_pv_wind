"""
统计「项目高分辨率气象区域」对全球**实测**风光场站的覆盖比例。

区域口径（注意区分）：
  - 二十多个高分辨率区域 = AREA_DICT 国家经纬度框 + NAM-12 rotated-pole 弯曲域
    （即 plot_stations_S1_with_regions.py 里画的那些未来气候情景数据范围）。
  - 20 个大区 = UN M49 区域电网划分（data/tracked/grid_division/Global_Grid_Division.tif）。
    本脚本逐大区统计「区内总量」中被「项目区域」覆盖的份额。

场站数据 = global-renewables-watch (Microsoft, 2024Q2) 识别到的现状风光设施：
  - solar_all_2024q2_v1.gpkg   86,345 个光伏多边形（Polygon，自带 area=真实占地 m²）
  - wind_all_2024q2_v1.gpkg    375,197 台风机（Point，每点 1 台）
  二者均为 EPSG:3857。

两种统计口径（回答「多少比例场站？多少比例发电量？」）：
  - 场站数量：光伏多边形数 + 风机台数
  - 装机容量(GW)：与 data/ignored/global-renewables-watch/compute_regional_capacity.py 完全同款密度公式
      · 光伏：cap = 占地面积(km²) × [161.9 × Ω(lat) × 0.15]  MW（Ω=GCR，纬度依赖）
      · 风电：cap = 台数 × 0.64 km² × 3.68 MW/km² ≈ 2.355 MW/台
    GRW 不含实际发电量，装机容量在此作为「发电/产能」的代理口径；按技术分别给出，
    故「发电量比例」= 该技术装机容量的覆盖比例（同一技术内 CF 为常数时二者相等）。

覆盖判定：场站质心落在 任一 AREA_DICT 框 或 NAM-12 弯曲域内 → 被项目区域覆盖。
区域几何/栅格查表逻辑直接复用 plot_stations_S1_with_regions.py，确保与既有图口径一致。

用法：
    python plot_stations_S1_grw_coverage.py                    # 出统计 + 分布图 + 大区柱状图
    python plot_stations_S1_grw_coverage.py --no-map           # 不画分布图（柱状图仍出）
    python plot_stations_S1_grw_coverage.py --threshold 60     # 覆盖率阈值（默认 60，红线 + 标签标红）
    python plot_stations_S1_grw_coverage.py --draw-macro-regions # 分布图叠加 20 大区边界

输出（outputs/plot_stations/plot_stations_S1_grw_coverage/）：
    grw_coverage_global.csv          全球总量 + 覆盖比例（按技术 + 合计）
    grw_coverage_by_macro_region.csv 20 大区逐区覆盖比例
    grw_coverage_map.png             覆盖/未覆盖场站分布图
    grw_coverage_macro_bar.png       20 大区装机容量覆盖率柱状图（每区 1 柱）
"""

import os
import sys
import csv
import argparse
import warnings

# 确保项目根目录在 sys.path 中，使 `import RQ0.xxx` 可从任意位置运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

warnings.filterwarnings("ignore")

import numpy as np
import matplotlib.pyplot as plt
from scipy import ndimage

# 复用 plot_stations_S1_with_regions.py 的区域几何与栅格逻辑，避免重复实现
# （该模块在 import 时已完成中文字体注册，柱状图/地图均可直接用中文）
import RQ0.plot_stations_S1_with_regions as prs
from RQ0.plot_stations_S1_with_regions import (
    PC,
    AREA_DICT,
    in_any_region,
    load_nam_domain,
    load_grid_division,
    macro_region_geometries,
    setup_basemap,
    draw_regions,
    draw_macro_regions,
)

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 约定：plot_stations_*.py 的图都存到 outputs/plot_stations/<本脚本文件名>/
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "plot_stations", os.path.splitext(os.path.basename(__file__))[0])
GRW_DIR = os.path.join(BASE_DIR, "data", "ignored", "global-renewables-watch", "data")
SOLAR_GPKG = os.path.join(GRW_DIR, "solar_all_2024q2_v1.gpkg")
WIND_GPKG = os.path.join(GRW_DIR, "wind_all_2024q2_v1.gpkg")

# 装机密度参数（与 compute_regional_capacity.py 一致）──────────────────
WIND_DENSITY = 3.68  # MW/km²（陆上风电）
ROTOR_D_M = 100.0  # 叶轮直径 (m)
SPACING_D = 8.0  # 8D × 8D 间距
TURBINE_FOOTPRINT_KM2 = (SPACING_D * ROTOR_D_M / 1000.0) ** 2  # 0.64 km²
WIND_CAP_GW_EACH = TURBINE_FOOTPRINT_KM2 * WIND_DENSITY / 1000.0  # GW/台
PV_PEAK = 161.9  # MW/km²（STC 组件功率密度）
PV_FR = 0.15  # 地面填充率

TECHS = ("solar", "wind")
TECH_LABEL = {"solar": "光伏", "wind": "风电"}

# 20 大区中文简写（编号与 region_id_to_name.json 一致；与 macro 柱状图脚本对齐）
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


def pv_density(lat):
    """光伏装机密度 (MW/km²)，纬度依赖。与 compute_pv_density.m / GRW 脚本一致。"""
    lat = np.asarray(lat, dtype=float)
    beta = 0.35396 * np.abs(lat) + 16.84775
    alpha_min = np.maximum(90.0 - np.abs(lat) - 23.45, 0.1)
    beta_r = np.deg2rad(beta)
    alpha_r = np.deg2rad(alpha_min)
    omega = np.cos(beta_r) / (np.cos(beta_r) + np.sin(beta_r) / np.tan(alpha_r))
    return PV_PEAK * omega * PV_FR


# ══════════════════════════════════════════════════════════════════════
# GRW 场站读取
# ══════════════════════════════════════════════════════════════════════


def _sanitize(lon, lat, cap):
    """无效质心（NaN 经纬度，如退化多边形）容量计 0，避免污染全局求和；返回剔除数。"""
    bad = ~(np.isfinite(lon) & np.isfinite(lat))
    cap = np.where(bad, 0.0, cap)
    return lon, lat, cap, int(bad.sum())


def load_grw():
    """读取 GRW 光伏/风电设施，返回 {tech: (lon, lat, cap_gw)}（经纬度为质心，WGS84）。"""
    import geopandas as gpd

    out = {}

    print("  读取光伏多边形 ...")
    solar = gpd.read_file(SOLAR_GPKG)
    cen = solar.geometry.centroid.to_crs("EPSG:4326")  # 3857 平面质心→经纬度
    s_lon, s_lat = cen.x.values, cen.y.values
    s_cap_gw = (solar["area"].values / 1e6) * pv_density(s_lat) / 1000.0  # km²×MW/km²→GW
    s_lon, s_lat, s_cap_gw, n_bad = _sanitize(s_lon, s_lat, s_cap_gw)
    out["solar"] = (s_lon, s_lat, s_cap_gw)
    bad = f"（含 {n_bad} 个无效质心，容量计 0）" if n_bad else ""
    print(f"    光伏: {len(s_lon):,} 个多边形, 合计 {s_cap_gw.sum():,.0f} GW{bad}")

    print("  读取风机点位 ...")
    wind = gpd.read_file(WIND_GPKG)
    w = wind.geometry.to_crs("EPSG:4326")
    w_lon, w_lat = w.x.values, w.y.values
    w_cap_gw = np.full(len(w_lon), WIND_CAP_GW_EACH)
    out["wind"] = (w_lon, w_lat, w_cap_gw)
    print(f"    风电: {len(w_lon):,} 台风机, 合计 {w_cap_gw.sum():,.0f} GW")

    return out


# ══════════════════════════════════════════════════════════════════════
# 20 大区查表（最近邻填充，使近海场站也归入相邻大区；与 GRW 脚本一致）
# ══════════════════════════════════════════════════════════════════════


def build_filled_region(grid):
    """把 20 大区栅格的 0（背景/海洋）像元用最近的有效大区填充，返回 int 数组。"""
    region = grid.astype(np.int32)
    valid = region > 0
    if not valid.all():
        _, (ri, ci) = ndimage.distance_transform_edt(~valid, return_indices=True)
        region = region[ri, ci]
    return region


def assign_region(lon, lat, region, transform):
    """按经纬度采样大区栅格，返回每点大区 ID (1-20)；非有限坐标记 0。"""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    finite = np.isfinite(lon) & np.isfinite(lat)
    inv = ~transform
    col, row = inv * (np.where(finite, lon, 0.0), np.where(finite, lat, 0.0))
    col = np.clip(np.asarray(col, int), 0, region.shape[1] - 1)
    row = np.clip(np.asarray(row, int), 0, region.shape[0] - 1)
    out = region[row, col]
    out[~finite] = 0
    return out


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


def compute_coverage(stations, domain):
    """逐技术计算覆盖掩码，返回 {tech: dict(lon,lat,cap,covered)}。"""
    res = {}
    for tech in TECHS:
        lon, lat, cap = stations[tech]
        covered = in_any_region(lon, lat, domain)
        res[tech] = {"lon": lon, "lat": lat, "cap": cap, "covered": covered}
    return res


def report_global(cov, out_path):
    """全球总量：逐技术 + 合计，给出 场站数 / 装机容量(GW) 的覆盖比例。"""
    print(f"\n  ── 全球总量：项目区域对 GRW 实测场站的覆盖 ──")
    print(f"  {'tech':<8}{'n_tot':>10}{'n_in':>10}{'n_cov':>8}   " f"{'cap_tot':>11}{'cap_in':>11}{'cap_cov':>9}")
    print("  " + "-" * 72)

    rows = []
    tot = dict(n_tot=0, n_in=0, c_tot=0.0, c_in=0.0)
    for tech in TECHS:
        d = cov[tech]
        n_tot = len(d["lon"])
        n_in = int(d["covered"].sum())
        c_tot = float(d["cap"].sum())
        c_in = float(d["cap"][d["covered"]].sum())
        nr = n_in / n_tot if n_tot else 0.0
        cr = c_in / c_tot if c_tot else 0.0
        print(f"  {TECH_LABEL[tech]:<7}{n_tot:>10,}{n_in:>10,}{nr:>7.1%}   " f"{c_tot:>11,.0f}{c_in:>11,.0f}{cr:>8.1%}")
        rows.append((tech, n_tot, n_in, nr, c_tot, c_in, cr))
        tot["n_tot"] += n_tot
        tot["n_in"] += n_in
        tot["c_tot"] += c_tot
        tot["c_in"] += c_in

    nr = tot["n_in"] / tot["n_tot"] if tot["n_tot"] else 0.0
    cr = tot["c_in"] / tot["c_tot"] if tot["c_tot"] else 0.0
    print("  " + "-" * 72)
    print(
        f"  {'合计':<7}{tot['n_tot']:>10,}{tot['n_in']:>10,}{nr:>7.1%}   "
        f"{tot['c_tot']:>11,.0f}{tot['c_in']:>11,.0f}{cr:>8.1%}"
    )
    rows.append(("all", tot["n_tot"], tot["n_in"], nr, tot["c_tot"], tot["c_in"], cr))

    with open(out_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(
            ["tech", "n_total", "n_inside", "n_cover_ratio", "cap_total_gw", "cap_inside_gw", "cap_cover_ratio"]
        )
        for tech, n_tot, n_in, nr, c_tot, c_in, cr in rows:
            wr.writerow([tech, n_tot, n_in, f"{nr:.4f}", f"{c_tot:.4f}", f"{c_in:.4f}", f"{cr:.4f}"])
    print(f"  -> {out_path}")


def report_by_macro_region(cov, region, transform, names, out_path):
    """20 大区逐区：区内总量中被项目区域覆盖的 场站数 / 装机容量 及比例（光伏+风电合计）。

    返回 region_rows 列表 (rid, name, n_tot, n_in, n_ratio, c_tot, c_in, c_ratio)，供柱状图使用。
    """
    n_ids = max(names) if names else 20
    n_tot = np.zeros(n_ids + 1)
    n_in = np.zeros(n_ids + 1)
    c_tot = np.zeros(n_ids + 1)
    c_in = np.zeros(n_ids + 1)

    for tech in TECHS:
        d = cov[tech]
        rid = assign_region(d["lon"], d["lat"], region, transform)
        cap = d["cap"]
        covered = d["covered"]
        valid = rid > 0
        np.add.at(n_tot, rid[valid], 1)
        np.add.at(c_tot, rid[valid], cap[valid])
        ins = valid & covered
        np.add.at(n_in, rid[ins], 1)
        np.add.at(c_in, rid[ins], cap[ins])

    print(f"\n  ── 20 大区（UN M49）逐区覆盖 ──")
    print(
        f"  {'id':<3}{'region':<24}"
        f"{'n_tot':>9}{'n_in':>9}{'n_cov':>7}   "
        f"{'cap_tot':>10}{'cap_in':>10}{'cap_cov':>8}"
    )
    print("  " + "-" * 86)
    region_rows = []
    with open(out_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(
            [
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
        for rid in range(1, n_ids + 1):
            nt, ni = int(n_tot[rid]), int(n_in[rid])
            ct, ci = float(c_tot[rid]), float(c_in[rid])
            nr = ni / nt if nt else 0.0
            cr = ci / ct if ct else 0.0
            name = names.get(rid, f"region {rid}")
            print(f"  {rid:<3}{name:<24}" f"{nt:>9,}{ni:>9,}{nr:>6.1%}   " f"{ct:>10,.1f}{ci:>10,.1f}{cr:>7.1%}")
            wr.writerow([rid, name, nt, ni, f"{nr:.4f}", f"{ct:.4f}", f"{ci:.4f}", f"{cr:.4f}"])
            region_rows.append((rid, name, nt, ni, nr, ct, ci, cr))
        # 合计
        NT, NI = int(n_tot.sum()), int(n_in.sum())
        CT, CI = float(c_tot.sum()), float(c_in.sum())
        nr = NI / NT if NT else 0.0
        cr = CI / CT if CT else 0.0
        print("  " + "-" * 86)
        print(f"  {'':3}{'20 区合计':<24}" f"{NT:>9,}{NI:>9,}{nr:>6.1%}   " f"{CT:>10,.1f}{CI:>10,.1f}{cr:>7.1%}")
        wr.writerow(["ALL", "20 区合计", NT, NI, f"{nr:.4f}", f"{CT:.4f}", f"{CI:.4f}", f"{cr:.4f}"])
    print(f"  -> {out_path}")
    return region_rows


# ══════════════════════════════════════════════════════════════════════
# 绘图
# ══════════════════════════════════════════════════════════════════════


def plot_coverage_map(cov, domain, region_geoms, names, out_path):
    """两面板（上=光伏，下=风电）：区分被覆盖 / 未覆盖的 GRW 场站，叠加项目区域边界。

    region_geoms 为空（默认）时不画 20 大区边界。
    """
    fig, axes = plt.subplots(2, 1, figsize=(16, 16), subplot_kw={"projection": PC})
    for ax, tech in zip(axes, TECHS):
        setup_basemap(ax)
        draw_macro_regions(ax, region_geoms, names, label=False)  # 空则自动跳过
        draw_regions(ax, domain, label=False)
        d = cov[tech]
        lon, lat, m = d["lon"], d["lat"], d["covered"]
        ax.scatter(
            lon[~m],
            lat[~m],
            s=1.2,
            c="#d62728",
            transform=PC,
            label=f"未覆盖 ({int((~m).sum()):,})",
            rasterized=True,
            zorder=3,
        )
        ax.scatter(
            lon[m],
            lat[m],
            s=1.2,
            c="#00ff04",
            transform=PC,
            label=f"被项目区域覆盖 ({int(m.sum()):,})",
            rasterized=True,
            zorder=4,
        )
        cr = float(d["cap"][m].sum()) / float(d["cap"].sum()) if d["cap"].sum() else 0.0
        ax.plot([], [], color="#1f77b4", lw=1.6, label="NAM-12 / AREA_DICT 边界")
        if region_geoms:
            ax.plot([], [], color="#2f7d32", lw=0.8, label="20 大区边界")
        ax.legend(loc="lower left", fontsize=10, markerscale=6, framealpha=0.9, edgecolor="#888")
        ax.set_title(
            f"GRW {TECH_LABEL[tech]}场站覆盖：" f"场站 {int(m.sum()/len(lon)*100):d}% / 装机 {cr:.0%}",
            fontsize=14,
            pad=10,
        )
    plt.tight_layout()
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()
    print(f"  -> {out_path}")


def plot_macro_bar(region_rows, out_path, threshold=60.0):
    """20 大区装机容量覆盖率柱状图：每区 1 根柱（不堆叠），按覆盖率降序排列。

    柱高 = 该大区被项目区域覆盖的装机容量比例；颜色按覆盖率由低(红)到高(绿)着色，
    以凸显未被覆盖的大区。柱顶标注覆盖率 %，x 轴标签下方附区内总装机(GW)。
    在 threshold（默认 60%）处画红色横线；覆盖率低于该阈值的大区，横坐标名称标红。
    """
    rows = sorted(region_rows, key=lambda r: r[7], reverse=True)  # 按 cap 覆盖率降序
    labels = [f"{REGION_SHORT_CN.get(r[0], str(r[0]))}\n{r[5]:,.0f}GW" for r in rows]
    cap_ratio = np.array([r[7] for r in rows]) * 100.0
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

    # 阈值红线（默认 60%）
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
    # 低于阈值的大区：横坐标名称标红
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
        "全球 20 大区：GRW 现状装机容量被项目区域覆盖的比例" "（x 轴下方为区内总装机 GW）", fontsize=10.5, pad=8
    )

    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out_path}")


# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════


def main():
    ap = argparse.ArgumentParser(description="项目区域对 GRW 实测风光场站的覆盖统计")
    ap.add_argument("--no-map", action="store_true", help="不画场站分布图（柱状图仍输出）")
    ap.add_argument(
        "--threshold",
        type=float,
        default=60.0,
        help="覆盖率阈值（%%，默认 60）：柱状图在此处画红线，低于该值的大区名称标红",
    )
    ap.add_argument(
        "--draw-macro-regions", action="store_true", help="分布图叠加 20 大区边界（默认不画；大区统计/柱状图始终输出）"
    )
    args = ap.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"{'=' * 64}\n  GRW 实测场站覆盖统计\n{'=' * 64}")

    domain = load_nam_domain()
    grid, transform, names = load_grid_division()
    region = build_filled_region(grid) if grid is not None else None

    stations = load_grw()
    cov = compute_coverage(stations, domain)

    report_global(cov, os.path.join(OUTPUT_DIR, "grw_coverage_global.csv"))

    region_rows = []
    if region is not None:
        region_rows = report_by_macro_region(
            cov, region, transform, names, os.path.join(OUTPUT_DIR, "grw_coverage_by_macro_region.csv")
        )
        plot_macro_bar(region_rows, os.path.join(OUTPUT_DIR, "grw_coverage_macro_bar.png"), threshold=args.threshold)

    if not args.no_map:
        # 默认不画 20 大区边界；仅 --draw-macro-regions 时才矢量化（较耗时）
        region_geoms = (
            macro_region_geometries(grid, transform) if (args.draw_macro_regions and grid is not None) else {}
        )
        plot_coverage_map(cov, domain, region_geoms, names, os.path.join(OUTPUT_DIR, "grw_coverage_map.png"))


if __name__ == "__main__":
    main()
