#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_RQ1_data.py — 将场站出力 NetCDF 聚合为 RQ1 绘图所需的 CSV

输入：
  data/wind_solar_output/outputs_0p1deg_2030_2040_2050/
    {pv_out,wind_out}/NESM3/{region}/{tech}_stations_out_{region}_NESM3_{ssp}_allmonths.nc

输出：data/real/RQ1_generation/
  station_annual_generation.csv   — 场站级年度统计（CF、发电量）
  station_monthly_generation.csv  — 场站级月度统计
  country_annual_generation.csv   — 国家级年度汇总（容量加权 CF）

约定：
  - 仅使用 NESM3 气候模型
  - 全部为自洽情景（deploy_ssp == climate_ssp）
  - power 单位 GW，时间步 3h；NaN 表示场站尚未激活（activation_year > 当前年）
  - CF = ΣP / (n_steps × capacity_gw)，含夜间零值（对光伏来说正确）
  - 年发电量 MWh = ΣP_GW × 3h × 1000 MW/GW
"""

import sys
from pathlib import Path

import netCDF4 as nc_lib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 路径与参数
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent          # 项目根目录
STATION_OUT = ROOT / "data/wind_solar_output/outputs_0p1deg_2030_2040_2050"
OUT_DIR = ROOT / "data/real/RQ1_generation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "NESM3"
SSPS = ["ssp126", "ssp245", "ssp585"]
TARGET_YEARS = [2030, 2040, 2050]
DT_H = 3  # 时间步长（小时）

# tech_dir → technology 名称
TECH_MAP = {"pv_out": "solar", "wind_out": "wind"}

# region 目录名 → 国家显示名
REGION_NAME_MAP = {
    "South-Africa":   "South Africa",
    "South-Korea":    "South Korea",
    "United-Kingdom": "United Kingdom",
    "México":         "Mexico",
    "china":          "China",
}


def region_to_country(region_dir: str) -> str:
    return REGION_NAME_MAP.get(region_dir, region_dir)


def nc_filepath(tech_dir: str, ssp: str, region: str) -> Path:
    prefix = "pv" if tech_dir == "pv_out" else "wind"
    return (
        STATION_OUT / tech_dir / MODEL / region
        / f"{prefix}_stations_out_{region}_{MODEL}_{ssp}_allmonths.nc"
    )


# ---------------------------------------------------------------------------
# 单文件处理（向量化）
# ---------------------------------------------------------------------------

def process_file(path: Path, tech: str, country: str, ssp: str):
    """
    读取一个场站出力 NC 文件，返回 (df_annual, df_monthly)。

    power (time, id) 单位 GW，已乘以场站装机容量（= CF × capacity_gw）。
    NaN 表示 activation_year > 当前年；0 是有效零出力（如夜间）。
    """
    region_dir = path.parent.name

    ds = nc_lib.Dataset(path, "r")

    power_ma = ds.variables["power"][:]           # MaskedArray (time, id)
    power = (power_ma.filled(np.nan)
             if hasattr(power_ma, "filled")
             else np.asarray(power_ma)).astype(np.float32)  # (T, N)

    cap_gw = np.asarray(ds.variables["capacity_gw"][:], dtype=np.float64)   # (N,)
    act_year = np.asarray(ds.variables["activation_year"][:], dtype=np.int32)  # (N,)

    raw_times = ds.variables["time"][:]
    time_units = ds.variables["time"].units
    cftime_objs = nc_lib.num2date(raw_times, time_units)
    years_arr  = np.array([t.year  for t in cftime_objs], dtype=np.int32)
    months_arr = np.array([t.month for t in cftime_objs], dtype=np.int32)
    ds.close()

    ann_dfs = []
    mon_dfs = []

    for yr in TARGET_YEARS:
        yr_mask = years_arr == yr
        if not yr_mask.any():
            continue

        yr_power  = power[yr_mask, :]      # (T_yr, N)
        yr_months = months_arr[yr_mask]    # (T_yr,)
        n_yr_steps = int(yr_mask.sum())

        # 活跃站掩码 + 数据完整性检查 + 有效装机（>0 避免除零）
        active   = act_year <= yr                              # (N,)
        has_data = ~np.all(np.isnan(yr_power), axis=0)        # (N,)
        valid_cap = cap_gw > 0                                 # (N,)
        include  = active & has_data & valid_cap
        idx = np.where(include)[0]
        if len(idx) == 0:
            continue

        # ---------- 年度聚合（向量化） ----------
        pwr_sum = np.nansum(yr_power[:, idx], axis=0)          # (M,)
        cap_mw  = cap_gw[idx] * 1000.0                         # (M,) MW
        ann_cf  = pwr_sum / (n_yr_steps * cap_gw[idx])         # (M,)
        ann_gen = pwr_sum * DT_H * 1000.0                      # (M,) MWh

        sta_ids = [f"{tech[0].upper()}{ssp[-3:]}_{region_dir}_{i:05d}" for i in idx]

        df_yr = pd.DataFrame({
            "station_id":              sta_ids,
            "country":                 country,
            "technology":              tech,
            "deploy_ssp":              ssp,
            "climate_ssp":             ssp,
            "target_year":             yr,
            "capacity_mw":             cap_mw.round(4),
            "annual_capacity_factor":  ann_cf.round(6),
            "annual_generation_mwh":   ann_gen.round(3),
        })
        ann_dfs.append(df_yr)

        # ---------- 月度聚合（向量化） ----------
        for m in range(1, 13):
            m_mask = yr_months == m
            if not m_mask.any():
                continue
            m_power  = yr_power[np.ix_(m_mask, idx)]           # (T_m, M)
            n_m      = int(m_mask.sum())
            m_sum    = np.nansum(m_power, axis=0)               # (M,)
            m_cf     = m_sum / (n_m * cap_gw[idx])             # (M,)
            m_gen    = m_sum * DT_H * 1000.0                   # (M,) MWh

            df_m = pd.DataFrame({
                "station_id":               sta_ids,
                "country":                  country,
                "technology":               tech,
                "deploy_ssp":               ssp,
                "climate_ssp":              ssp,
                "target_year":              yr,
                "month":                    m,
                "capacity_mw":              cap_mw.round(4),
                "monthly_capacity_factor":  m_cf.round(6),
                "monthly_generation_mwh":   m_gen.round(3),
            })
            mon_dfs.append(df_m)

    df_ann = pd.concat(ann_dfs, ignore_index=True) if ann_dfs else pd.DataFrame()
    df_mon = pd.concat(mon_dfs, ignore_index=True) if mon_dfs else pd.DataFrame()
    return df_ann, df_mon


# ---------------------------------------------------------------------------
# 国家级聚合
# ---------------------------------------------------------------------------

def aggregate_country(df_ann: pd.DataFrame) -> pd.DataFrame:
    """场站年度 → 国家年度：求和装机 / 发电量，CF 取各站算术平均。"""
    grp = ["country", "technology", "deploy_ssp", "climate_ssp", "target_year"]
    agg = df_ann.groupby(grp, sort=False).agg(
        capacity_mw=("capacity_mw", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
        mean_cf=("annual_capacity_factor", "mean"),
    ).reset_index()
    return agg


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    all_ann = []
    all_mon = []
    n_ok = n_miss = 0

    for tech_dir, tech in TECH_MAP.items():
        base = STATION_OUT / tech_dir / MODEL
        if not base.exists():
            print(f"[WARN] 目录不存在，跳过: {base}")
            continue

        regions = sorted(base.iterdir())

        for region_path in regions:
            region = region_path.name
            country = region_to_country(region)

            for ssp in SSPS:
                path = nc_filepath(tech_dir, ssp, region)
                if not path.exists():
                    print(f"  [MISS] {tech}/{region}/{ssp}")
                    n_miss += 1
                    continue

                print(f"  [OK]   {tech}/{region}/{ssp} ...", end="", flush=True)
                try:
                    df_ann, df_mon = process_file(path, tech, country, ssp)
                    if df_ann.empty:
                        print(" (无有效数据)")
                        continue
                    all_ann.append(df_ann)
                    all_mon.append(df_mon)
                    print(f" {len(df_ann)} 站×年记录")
                    n_ok += 1
                except Exception as e:
                    print(f" [ERR] {e}")

    print(f"\n处理完成：{n_ok} 个文件成功，{n_miss} 个文件缺失")

    # 合并
    df_ann_all = pd.concat(all_ann, ignore_index=True)
    df_mon_all = pd.concat(all_mon, ignore_index=True)
    df_cty_all = aggregate_country(df_ann_all)

    # 保存
    p_ann = OUT_DIR / "station_annual_generation.csv"
    p_mon = OUT_DIR / "station_monthly_generation.csv"
    p_cty = OUT_DIR / "country_annual_generation.csv"

    df_ann_all.to_csv(p_ann, index=False)
    df_mon_all.to_csv(p_mon, index=False)
    df_cty_all.to_csv(p_cty, index=False)

    print(f"\n已保存:")
    print(f"  {p_ann}  ({len(df_ann_all):,} 行)")
    print(f"  {p_mon}  ({len(df_mon_all):,} 行)")
    print(f"  {p_cty}  ({len(df_cty_all):,} 行)")

    # 简要统计
    print("\n=== 国家级快速检验 ===")
    chk = df_cty_all.groupby(["technology", "deploy_ssp", "target_year"]).agg(
        n_countries=("country", "count"),
        total_cap_gw=("capacity_mw", lambda x: x.sum() / 1000),
        total_gen_twh=("annual_generation_mwh", lambda x: x.sum() / 1e6),
        mean_cf=("mean_cf", "mean"),
    )
    print(chk.to_string())


if __name__ == "__main__":
    main()
