#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_RQ1_data.py — 将场站出力与格点 CF 聚合为 RQ1 绘图所需的 CSV

输入 1（场站出力）：
  data/wind_solar_output/outputs_0p1deg_2030_2040_2050/
    {pv_out,wind_out}/NESM3/{region}/{tech}_stations_out_{region}_NESM3_{ssp}_allmonths.nc

输入 2（格点容量因子）：
  data/cfs/CFs_of_{solar,wind}/NESM3/{region}/{tech}_CF_{region}_NESM3_{ssp}_2015-2060_allmonths.nc
  data/cfs/CFs_of_{solar,wind}_china/NESM3/{tech}_CF_china_NESM3_{ssp}_2015-2060_allmonths.nc

输出：data/real/RQ1_generation/
  station_annual_generation.csv   — 场站级年度统计（CF、发电量）
  station_monthly_generation.csv  — 场站级月度统计
  country_annual_generation.csv   — 国家级年度汇总（装机、发电量、场站平均 CF）
  country_grid_cf.csv             — 国家级格点年均 CF（用于图 a/c/d 全球/国家轨迹）

约定：
  - 仅使用 NESM3 气候模型；全部为自洽情景（deploy_ssp == climate_ssp）
  - power 单位 GW，3h 时步；NaN 表示场站未激活（activation_year > 当前年）
  - 站点级 CF：CF = ΣP / (n_steps × capacity_gw)，含夜间零值
  - 格点级 CF：直接读取 CF NC 文件，各目标年时步内 nanmean，再空间 nanmean
  - 年发电量 MWh = ΣP_GW × 3h × 1000 MW/GW

日志：RQ1/logs/prepare_RQ1_data.log（每次运行覆写）
"""

import logging
import sys
from pathlib import Path

import netCDF4 as nc_lib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "prepare_RQ1_data.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径与参数
# ---------------------------------------------------------------------------
ROOT        = Path(__file__).resolve().parent.parent
STATION_OUT = ROOT / "data/wind_solar_output/outputs_0p1deg_2030_2040_2050"
CF_BASE     = ROOT / "data/cfs"
OUT_DIR     = ROOT / "data/real/RQ1_generation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL        = "NESM3"
SSPS         = ["ssp126", "ssp245", "ssp585"]
TARGET_YEARS = [2030, 2040, 2050]
DT_H         = 3  # 时间步长（小时）

TECH_MAP = {"pv_out": "solar", "wind_out": "wind"}

REGION_NAME_MAP = {
    "South-Africa":   "South Africa",
    "South-Korea":    "South Korea",
    "United-Kingdom": "United Kingdom",
    "México":         "Mexico",
    "china":          "China",
}


def region_to_country(region_dir: str) -> str:
    return REGION_NAME_MAP.get(region_dir, region_dir)


# ---------------------------------------------------------------------------
# 文件路径工具
# ---------------------------------------------------------------------------

def nc_filepath(tech_dir: str, ssp: str, region: str) -> Path:
    """场站出力 NC 文件路径。"""
    prefix = "pv" if tech_dir == "pv_out" else "wind"
    return (
        STATION_OUT / tech_dir / MODEL / region
        / f"{prefix}_stations_out_{region}_{MODEL}_{ssp}_allmonths.nc"
    )


def cf_filepath(tech_dir: str, ssp: str, region: str) -> Path:
    """格点 CF NC 文件路径（中国单独目录）。"""
    prefix = "solar" if tech_dir == "pv_out" else "wind"
    if region == "china":
        return (
            CF_BASE / f"CFs_of_{prefix}_china" / MODEL
            / f"{prefix}_CF_{region}_{MODEL}_{ssp}_2015-2060_allmonths.nc"
        )
    return (
        CF_BASE / f"CFs_of_{prefix}" / MODEL / region
        / f"{prefix}_CF_{region}_{MODEL}_{ssp}_2015-2060_allmonths.nc"
    )


# ---------------------------------------------------------------------------
# 场站出力处理（向量化）
# ---------------------------------------------------------------------------

def process_file(path: Path, tech: str, country: str, ssp: str):
    """读取场站出力 NC，返回 (df_annual, df_monthly)。"""
    region_dir = path.parent.name

    ds = nc_lib.Dataset(path, "r")
    power_ma = ds.variables["power"][:]
    power = (
        power_ma.filled(np.nan) if hasattr(power_ma, "filled") else np.asarray(power_ma)
    ).astype(np.float32)

    cap_gw   = np.asarray(ds.variables["capacity_gw"][:],    dtype=np.float64)
    act_year = np.asarray(ds.variables["activation_year"][:], dtype=np.int32)

    t_var     = ds.variables["time"]
    cft       = nc_lib.num2date(t_var[:], t_var.units)
    years_arr  = np.array([t.year  for t in cft], dtype=np.int32)
    months_arr = np.array([t.month for t in cft], dtype=np.int32)
    ds.close()

    ann_dfs, mon_dfs = [], []

    for yr in TARGET_YEARS:
        yr_mask    = years_arr == yr
        if not yr_mask.any():
            continue
        yr_power   = power[yr_mask, :]
        yr_months  = months_arr[yr_mask]
        n_yr_steps = int(yr_mask.sum())

        active    = act_year <= yr
        has_data  = ~np.all(np.isnan(yr_power), axis=0)
        valid_cap = cap_gw > 0
        include   = active & has_data & valid_cap
        idx       = np.where(include)[0]
        if len(idx) == 0:
            continue

        pwr_sum = np.nansum(yr_power[:, idx], axis=0)
        cap_mw  = cap_gw[idx] * 1000.0
        ann_cf  = pwr_sum / (n_yr_steps * cap_gw[idx])
        ann_gen = pwr_sum * DT_H * 1000.0

        sta_ids = [f"{tech[0].upper()}{ssp[-3:]}_{region_dir}_{i:05d}" for i in idx]

        ann_dfs.append(pd.DataFrame({
            "station_id":             sta_ids,
            "country":                country,
            "technology":             tech,
            "deploy_ssp":             ssp,
            "climate_ssp":            ssp,
            "target_year":            yr,
            "capacity_mw":            cap_mw.round(4),
            "annual_capacity_factor": ann_cf.round(6),
            "annual_generation_mwh":  ann_gen.round(3),
        }))

        for m in range(1, 13):
            m_mask = yr_months == m
            if not m_mask.any():
                continue
            m_power = yr_power[np.ix_(m_mask, idx)]
            n_m     = int(m_mask.sum())
            m_sum   = np.nansum(m_power, axis=0)
            m_cf    = m_sum / (n_m * cap_gw[idx])
            m_gen   = m_sum * DT_H * 1000.0

            mon_dfs.append(pd.DataFrame({
                "station_id":              sta_ids,
                "country":                 country,
                "technology":              tech,
                "deploy_ssp":              ssp,
                "climate_ssp":             ssp,
                "target_year":             yr,
                "month":                   m,
                "capacity_mw":             cap_mw.round(4),
                "monthly_capacity_factor": m_cf.round(6),
                "monthly_generation_mwh":  m_gen.round(3),
            }))

    df_ann = pd.concat(ann_dfs, ignore_index=True) if ann_dfs else pd.DataFrame()
    df_mon = pd.concat(mon_dfs, ignore_index=True) if mon_dfs else pd.DataFrame()
    return df_ann, df_mon


# ---------------------------------------------------------------------------
# 格点 CF 处理
# ---------------------------------------------------------------------------

def process_cf_file(path: Path, tech: str, country: str, ssp: str) -> pd.DataFrame:
    """读取格点 CF NC 文件，返回各目标年的国家级空间均值 DataFrame。

    流程：时间切片 → 时间轴 nanmean → 空间轴 nanmean（排除 NaN 格点）。
    """
    var_name = "solar_cf" if tech == "solar" else "wind_cf"

    ds      = nc_lib.Dataset(path, "r")
    t_var   = ds.variables["time"]
    cft     = nc_lib.num2date(t_var[:], t_var.units)
    years_arr = np.array([c.year for c in cft], dtype=np.int32)

    rows = []
    for yr in TARGET_YEARS:
        yr_idx = np.where(years_arr == yr)[0]
        if len(yr_idx) == 0:
            continue

        i0, i1 = int(yr_idx[0]), int(yr_idx[-1]) + 1
        cf_yr = ds.variables[var_name][i0:i1, :, :]        # (T_yr, lat, lon)
        if hasattr(cf_yr, "filled"):
            cf_yr = cf_yr.filled(np.nan).astype(np.float32)
        else:
            cf_yr = np.asarray(cf_yr, dtype=np.float32)

        cf_ann = np.nanmean(cf_yr, axis=0)                  # (lat, lon)
        valid  = ~np.isnan(cf_ann)
        if not valid.any():
            logger.warning("  [WARN] 格点CF无有效值: %s/%s/%s/%d", tech, country, ssp, yr)
            continue

        rows.append({
            "country":      country,
            "technology":   tech,
            "deploy_ssp":   ssp,
            "climate_ssp":  ssp,
            "target_year":  yr,
            "mean_grid_cf": round(float(cf_ann[valid].mean()), 6),
            "n_grid":       int(valid.sum()),
        })

    ds.close()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 国家级聚合（站点）
# ---------------------------------------------------------------------------

def aggregate_country(df_ann: pd.DataFrame) -> pd.DataFrame:
    """场站年度 → 国家年度：求和装机/发电量，CF 取各站算术平均。"""
    grp = ["country", "technology", "deploy_ssp", "climate_ssp", "target_year"]
    return (
        df_ann.groupby(grp, sort=False)
        .agg(
            capacity_mw=("capacity_mw", "sum"),
            annual_generation_mwh=("annual_generation_mwh", "sum"),
            mean_cf=("annual_capacity_factor", "mean"),
        )
        .reset_index()
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    all_ann, all_mon, all_cf = [], [], []
    n_sta_ok = n_sta_miss = n_cf_ok = n_cf_miss = 0

    for tech_dir, tech in TECH_MAP.items():
        base = STATION_OUT / tech_dir / MODEL
        if not base.exists():
            logger.warning("[WARN] 目录不存在，跳过: %s", base)
            continue

        regions = sorted(base.iterdir())
        logger.info("=== %s  (%d 个地区) ===", tech, len(regions))

        for region_path in regions:
            region  = region_path.name
            country = region_to_country(region)

            for ssp in SSPS:
                # ---- 场站出力 ----
                sta_path = nc_filepath(tech_dir, ssp, region)
                if not sta_path.exists():
                    logger.info("  [MISS-STA] %s/%s/%s", tech, region, ssp)
                    n_sta_miss += 1
                else:
                    logger.info("  [STA]  %s/%s/%s ...", tech, region, ssp)
                    try:
                        df_ann, df_mon = process_file(sta_path, tech, country, ssp)
                        if df_ann.empty:
                            logger.info("    → 无有效场站数据")
                        else:
                            all_ann.append(df_ann)
                            all_mon.append(df_mon)
                            logger.info("    → %d 站×年记录", len(df_ann))
                            n_sta_ok += 1
                    except Exception as e:
                        logger.error("    [ERR] %s", e, exc_info=True)

                # ---- 格点 CF ----
                cf_path = cf_filepath(tech_dir, ssp, region)
                if not cf_path.exists():
                    logger.info("  [MISS-CF]  %s/%s/%s", tech, region, ssp)
                    n_cf_miss += 1
                else:
                    try:
                        df_cf = process_cf_file(cf_path, tech, country, ssp)
                        if df_cf.empty:
                            logger.info("    → 格点CF无有效数据")
                        else:
                            all_cf.append(df_cf)
                            n_cf_ok += 1
                    except Exception as e:
                        logger.error("    [CF-ERR] %s", e, exc_info=True)

    logger.info(
        "\n处理完成：站点 %d 成功 / %d 缺失；格点CF %d 成功 / %d 缺失",
        n_sta_ok, n_sta_miss, n_cf_ok, n_cf_miss,
    )

    # 合并与保存
    df_ann_all = pd.concat(all_ann, ignore_index=True)
    df_mon_all = pd.concat(all_mon, ignore_index=True)
    df_cty_all = aggregate_country(df_ann_all)
    df_cf_all  = pd.concat(all_cf,  ignore_index=True) if all_cf else pd.DataFrame()

    p_ann = OUT_DIR / "station_annual_generation.csv"
    p_mon = OUT_DIR / "station_monthly_generation.csv"
    p_cty = OUT_DIR / "country_annual_generation.csv"
    p_cf  = OUT_DIR / "country_grid_cf.csv"

    df_ann_all.to_csv(p_ann, index=False)
    df_mon_all.to_csv(p_mon, index=False)
    df_cty_all.to_csv(p_cty, index=False)
    if not df_cf_all.empty:
        df_cf_all.to_csv(p_cf, index=False)

    logger.info("\n已保存:")
    logger.info("  %s  (%d 行)", p_ann, len(df_ann_all))
    logger.info("  %s  (%d 行)", p_mon, len(df_mon_all))
    logger.info("  %s  (%d 行)", p_cty, len(df_cty_all))
    if not df_cf_all.empty:
        logger.info("  %s  (%d 行)", p_cf,  len(df_cf_all))

    # 快速检验
    logger.info("\n=== 国家级场站统计 ===")
    chk = df_cty_all.groupby(["technology", "deploy_ssp", "target_year"]).agg(
        n_countries=("country", "count"),
        total_cap_gw=("capacity_mw", lambda x: x.sum() / 1000),
        total_gen_twh=("annual_generation_mwh", lambda x: x.sum() / 1e6),
        mean_station_cf=("mean_cf", "mean"),
    )
    logger.info("\n%s", chk.to_string())

    if not df_cf_all.empty:
        logger.info("\n=== 格点 CF 统计 ===")
        chk2 = df_cf_all.groupby(["technology", "deploy_ssp", "target_year"]).agg(
            n_countries=("country", "count"),
            mean_grid_cf=("mean_grid_cf", "mean"),
        )
        logger.info("\n%s", chk2.to_string())


if __name__ == "__main__":
    main()
