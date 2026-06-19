#!/usr/bin/env python3
"""
未来风光场站选址可视化

参考 plot_stations.ipynb，对不同 SSP 情景下 2030/2040/2050 年
光伏和风电场站选址结果进行可视化（上: 光伏，下: 风电）。

用法:
    python plot_stations.py
"""

import os
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import scipy.io
import csv
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCENARIOS = {
    "Baseline": "Optimization/results",
    "SSP1-2.6": "Optimization_ssp126/results",
    "SSP2-4.5": "Optimization_ssp245/results",
    "SSP5-6.0": "Optimization_ssp560/results",
}

YEAR_COLORS = {2030: "#c501ff", 2040: "#00ffc5", 2050: "#d48a8b"}

# .mat 选择文件名模式（同一年有多种命名时按优先级尝试）
MAT_PATTERNS = {
    2050: ["Opt_SG_2050_Sel.mat", "Opt_SC_2050_Sel.mat"],
    2040: ["Opt_SC_2040_Sel.mat"],
    2030: ["Opt_SA_2030_Sel.mat"],
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
plt.rcParams.update(
    {
        "figure.dpi": 120,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
    }
)


# ══════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════


def setup_basemap(ax):
    ax.set_global()
    ax.add_feature(cfeature.LAND, color="#f5f5f0", zorder=0)
    ax.add_feature(cfeature.OCEAN, color="#d1e8f0", zorder=0)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.5, color="#888", zorder=1)
    ax.add_feature(cfeature.BORDERS, linewidth=0.3, color="#aaa", zorder=1)
    ax.gridlines(linewidth=0.3, color="gray", alpha=0.4)


def _find_file(data_dir, patterns):
    for p in patterns:
        path = os.path.join(data_dir, p)
        if os.path.exists(path):
            return path
    return None


def _grid_to_coords(grid):
    """将 180x360 二值栅格转为 (lon, lat) 坐标数组。"""
    nrows = grid.shape[0]
    flat = np.nonzero(grid.ravel(order="F"))[0]
    rows, cols = flat % nrows, flat // nrows
    return -179.5 + cols, 89.5 - rows


def extract_stations_from_mat(mat_path):
    """从 .mat 选择文件提取光伏和风电场站经纬度。

    Returns: (slon, slat, ns, wlon, wlat, nw)
    """
    mat = scipy.io.loadmat(mat_path)
    opt_solar = mat["opt_solar"]
    opt_wind = mat["opt_wind"]
    slon, slat = _grid_to_coords(opt_solar)
    wlon, wlat = _grid_to_coords(opt_wind)
    return slon, slat, len(slon), wlon, wlat, len(wlon)


def get_stations(data_dir, year):
    """获取指定年份的光伏+风电场站坐标。

    Returns: (slon, slat, ns, wlon, wlat, nw)
    Raises: FileNotFoundError — .mat 选择文件不存在
    """
    mat_path = _find_file(data_dir, MAT_PATTERNS[year])
    if mat_path is None:
        raise FileNotFoundError(f"{year} 年选择文件未找到，期望：{MAT_PATTERNS[year]}（目录：{data_dir}）")
    return extract_stations_from_mat(mat_path)


# ══════════════════════════════════════════════════════════════════════
# 装机容量 & CSV 导出
# ══════════════════════════════════════════════════════════════════════


def _build_capacity_grids(opt_dir):
    """构建 180×360 光伏/风电装机容量栅格（GW）。

    容量 = 安装密度(MW/km²) × 可用面积比例 × 格网面积(km²) / 1000
    """
    solar_luccs = scipy.io.loadmat(os.path.join(opt_dir, "Global_Solar_Net_Area_Add_Egrid.mat"))["data"] / 100.0
    solar_area = scipy.io.loadmat(os.path.join(opt_dir, "Global_Solar_Fishnet_Area.mat"))["data"].astype(float)
    solar_cap = 74 * solar_luccs * solar_area / 1000

    wind_luccs = scipy.io.loadmat(os.path.join(opt_dir, "Global_Wind_Net_Area_Add_Egrid.mat"))["data"] / 100.0
    wind_area = scipy.io.loadmat(os.path.join(opt_dir, "Global_Wind_Fishnet_Area.mat"))["data"]
    landmask = scipy.io.loadmat(os.path.join(opt_dir, "Global_LandMask.mat"))["data"]
    density = np.where(landmask > 100, 4.6, 2.7)
    wind_cap = density * wind_luccs * wind_area / 1000

    return solar_cap, wind_cap


def get_stations_with_cap(data_dir, year, solar_cap, wind_cap):
    """获取指定年份的光伏+风电场站坐标及装机容量。

    Returns: (slon, slat, scap, ns, wlon, wlat, wcap, nw)
    Raises: FileNotFoundError — .mat 选择文件不存在
    """
    mat_path = _find_file(data_dir, MAT_PATTERNS[year])
    if mat_path is None:
        raise FileNotFoundError(f"{year} 年选择文件未找到，期望：{MAT_PATTERNS[year]}（目录：{data_dir}）")

    mat = scipy.io.loadmat(mat_path)
    opt_solar, opt_wind = mat["opt_solar"], mat["opt_wind"]
    nrows = opt_solar.shape[0]

    sflat = np.nonzero(opt_solar.ravel(order="F"))[0]
    srows, scols = sflat % nrows, sflat // nrows
    slon, slat = -179.5 + scols, 89.5 - srows
    scap = solar_cap[srows, scols]

    wflat = np.nonzero(opt_wind.ravel(order="F"))[0]
    wrows, wcols = wflat % nrows, wflat // nrows
    wlon, wlat = -179.5 + wcols, 89.5 - wrows
    wcap = wind_cap[wrows, wcols]

    return slon, slat, scap, len(slon), wlon, wlat, wcap, len(wlon)


def save_stations_csv(data_dir, scenario_name, cap_results):
    """保存场站选址结果为 CSV：year,type,lon,lat,capacity_gw。"""
    csv_path = os.path.join(data_dir, f"stations_{scenario_name}.csv")
    n_rows = 0
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "type", "lon", "lat", "capacity_gw"])
        for year in [2050, 2040, 2030]:
            if year not in cap_results:
                continue
            slon, slat, scap, ns, wlon, wlat, wcap, nw = cap_results[year]
            for i in range(ns):
                writer.writerow([year, "solar", f"{slon[i]:.1f}", f"{slat[i]:.1f}", f"{scap[i]:.4f}"])
            for i in range(nw):
                writer.writerow([year, "wind", f"{wlon[i]:.1f}", f"{wlat[i]:.1f}", f"{wcap[i]:.4f}"])
            n_rows += ns + nw
    print(f"  -> {csv_path} ({n_rows} stations)")


# ══════════════════════════════════════════════════════════════════════
# 可视化
# ══════════════════════════════════════════════════════════════════════


def plot_scenario(scenario_name, data_dir, results):
    """单情景：上子图=光伏，下子图=风电，3 个年份叠加。"""
    fig, (ax_s, ax_w) = plt.subplots(2, 1, figsize=(16, 14), subplot_kw={"projection": ccrs.Robinson()})
    setup_basemap(ax_s)
    setup_basemap(ax_w)

    for year in [2050, 2040, 2030]:
        if year not in results:
            continue
        slon, slat, ns, wlon, wlat, nw = results[year]

        ax_s.scatter(
            slon,
            slat,
            s=3,
            c=YEAR_COLORS[year],
            transform=ccrs.PlateCarree(),
            label=f"{year} ({ns:,})",
            rasterized=True,
        )
        ax_w.scatter(
            wlon,
            wlat,
            s=3,
            c=YEAR_COLORS[year],
            transform=ccrs.PlateCarree(),
            label=f"{year} ({nw:,})",
            rasterized=True,
        )

    for ax, title in [
        (ax_s, f"{scenario_name} — Solar Farm Station Selection"),
        (ax_w, f"{scenario_name} — Wind Farm Station Selection"),
    ]:
        ax.legend(loc="lower left", fontsize=11, markerscale=5, framealpha=0.9, edgecolor="#888")
        ax.set_title(title, fontsize=14, pad=10)

    out = os.path.join(data_dir, "solar_wind_farm_stations.png")
    plt.tight_layout()
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  -> {out}")


# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════


def run_single_scenario(scenario_name, opt_dir, res_dir, output_dir):
    """单场景模式：指定 opt_dir（基础数据）、res_dir（结果文件）、output_dir（输出目录）。"""
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  {scenario_name}")
    print(f"  opt_dir:   {opt_dir}")
    print(f"  res_dir:   {res_dir}")
    print(f"  output_dir:{output_dir}")
    print(f"{'=' * 60}")

    results = {}
    for year in [2050, 2040, 2030]:
        try:
            data = get_stations(res_dir, year)
            slon, slat, ns, wlon, wlat, nw = data
            results[year] = data
            print(f"  {year}: solar={ns:,}  wind={nw:,}")
        except FileNotFoundError as e:
            print(f"  {year}: {e}")

    if results:
        plot_scenario(scenario_name, output_dir, results)

    # CSV 导出
    cap_files = ["Global_Solar_Net_Area_Add_Egrid.mat", "Global_LandMask.mat"]
    if all(os.path.exists(os.path.join(opt_dir, f)) for f in cap_files):
        solar_cap, wind_cap = _build_capacity_grids(opt_dir)
        cap_results = {}
        for year in [2050, 2040, 2030]:
            try:
                data = get_stations_with_cap(res_dir, year, solar_cap, wind_cap)
                cap_results[year] = data
            except FileNotFoundError:
                pass
        if cap_results:
            save_stations_csv(output_dir, scenario_name, cap_results)

    return results


def run_all_scenarios():
    """原始多场景模式：遍历 SCENARIOS 字典。"""
    all_results = {}

    for scenario_name, rel_path in SCENARIOS.items():
        data_dir = os.path.join(BASE_DIR, rel_path)
        if not os.path.isdir(data_dir):
            print(f"[skip] {data_dir}")
            continue

        # 查找最新的 results_<timestamp> 子目录
        subdirs = sorted(
            [
                os.path.join(data_dir, d)
                for d in os.listdir(data_dir)
                if d.startswith("results_") and os.path.isdir(os.path.join(data_dir, d))
            ]
        )
        if subdirs:
            data_dir = subdirs[-1]

        opt_dir = os.path.dirname(data_dir)
        if os.path.basename(opt_dir) == "results":
            opt_dir = os.path.dirname(opt_dir)

        results = run_single_scenario(scenario_name, opt_dir, data_dir, data_dir)
        if results:
            all_results[scenario_name] = results

    # 汇总
    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    header = f"  {'Scenario':<12}" + "".join(f"  {y} solar/wind    " for y in [2050, 2040, 2030])
    print(header)
    print("  " + "-" * 78)
    for name, results in all_results.items():
        row = f"  {name:<12}"
        for year in [2050, 2040, 2030]:
            if year in results:
                ns, nw = results[year][2], results[year][5]
                row += f"  {ns:>5,}/{nw:<5,}     "
            else:
                row += f"  {'--/--':>12}   "
        print(row)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="未来风光场站选址可视化")
    parser.add_argument("--opt-dir", type=str, default=None, help="基础数据目录（含 Global_Solar_*.mat 等）")
    parser.add_argument("--res-dir", type=str, default=None, help="结果文件目录（含 Opt_*_Sel.mat）")
    parser.add_argument("--output-dir", type=str, default=None, help="输出目录（图片和 CSV 保存位置）")
    parser.add_argument("--scenario-name", type=str, default=None, help="场景名称（如 SSP1-2.6）")
    args = parser.parse_args()

    if args.opt_dir and args.res_dir and args.output_dir:
        name = args.scenario_name or os.path.basename(args.res_dir)
        run_single_scenario(name, args.opt_dir, args.res_dir, args.output_dir)
    else:
        run_all_scenarios()


if __name__ == "__main__":
    main()
