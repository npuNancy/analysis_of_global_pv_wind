#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_RQ1_data.py — 将场站出力聚合为 RQ1 绘图所需的 CSV

使用示例：
  # 默认配置：NESM3，ssp126/245/585，2030/2040/2050，Natural Earth 国界
  python RQ1/prepare_RQ1_data.py

  # 切换气候模式，输出到 data/real/RQ1_generation/MIROC-ES2H/
  python RQ1/prepare_RQ1_data.py --model MIROC-ES2H

  # 只处理一个情景和一个年份
  python RQ1/prepare_RQ1_data.py --ssps ssp245 --target-years 2050

  # 显式指定输入、国界和输出目录
  python RQ1/prepare_RQ1_data.py \
    --station-out data/wind_solar_output/outputs_0p1deg_2030_2040_2050 \
    --country-shp data/maps/natural_earth/ne_110m_admin_0_countries.shp \
    --out-dir data/real/RQ1_generation/NESM3

输入（场站出力）：
  data/wind_solar_output/outputs_0p1deg_2030_2040_2050/
    {pv_out,wind_out}/{MODEL}/{region}/{tech}_stations_out_{region}_{MODEL}_{ssp}_allmonths.nc

输出：data/real/RQ1_generation/{MODEL}/   （按气候模式分目录，如 NESM3）
  station_annual_generation.csv   — 场站级年度统计（CF、发电量）
  station_monthly_generation.csv  — 场站级月度统计
  country_annual_generation.csv   — 国家级年度汇总（装机、发电量、场站平均 CF）

约定：
  - 全部为自洽情景（deploy_ssp == climate_ssp）
  - 场站国家归属由 station_lon/station_lat 对 Natural Earth 国界做点在多边形判定
  - power 单位 GW，3h 时步；NaN 表示场站未激活（activation_year > 当前年）
  - 站点级 CF：CF = ΣP / (n_steps × capacity_gw)，含夜间零值
  - 年发电量 MWh = ΣP_GW × 3h × 1000 MW/GW

日志：RQ1/logs/prepare_RQ1_data.log（每次运行覆写）
"""

import argparse
import logging
import sys
from pathlib import Path

import fiona
import netCDF4 as nc_lib
import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.prepared import prep

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )

# ---------------------------------------------------------------------------
# 默认路径与参数
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATION_OUT = ROOT / "data/wind_solar_output/outputs_0p1deg_2030_2040_2050"
DEFAULT_COUNTRY_SHP = ROOT / "data/maps/natural_earth/ne_110m_admin_0_countries.shp"
DEFAULT_LOG_FILE = Path(__file__).resolve().parent / "logs/prepare_RQ1_data.log"
TECH_MAP = {"pv_out": "solar", "wind_out": "wind"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 RQ1 场站出力 NC 聚合为场站级和国家级 CSV，国家归属使用 Natural Earth 国界。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default="NESM3", help="气候模式名，对应输入目录中的 MODEL 层级。")
    parser.add_argument(
        "--station-out",
        type=Path,
        default=DEFAULT_STATION_OUT,
        help="场站出力输出根目录，下面应包含 {pv_out,wind_out}/{MODEL}/{region}/。",
    )
    parser.add_argument(
        "--country-shp",
        type=Path,
        default=DEFAULT_COUNTRY_SHP,
        help="Natural Earth admin-0 国家边界 shapefile。",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="CSV 输出目录。默认 data/real/RQ1_generation/{MODEL}。",
    )
    parser.add_argument(
        "--ssps",
        nargs="+",
        default=["ssp126", "ssp245", "ssp585"],
        help="要处理的 climate/deploy SSP 情景列表。",
    )
    parser.add_argument(
        "--target-years",
        nargs="+",
        type=int,
        default=[2030, 2040, 2050],
        help="要输出的目标年份列表。",
    )
    parser.add_argument("--dt-hours", type=float, default=3.0, help="power 时间步长，单位小时。")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE, help="日志文件路径。")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 文件路径工具
# ---------------------------------------------------------------------------

def nc_filepath(station_out: Path, model: str, tech_dir: str, ssp: str, region: str) -> Path:
    """场站出力 NC 文件路径。"""
    prefix = "pv" if tech_dir == "pv_out" else "wind"
    return (
        station_out / tech_dir / model / region
        / f"{prefix}_stations_out_{region}_{model}_{ssp}_allmonths.nc"
    )


# ---------------------------------------------------------------------------
# 国家边界匹配
# ---------------------------------------------------------------------------

class CountryMatcher:
    """Natural Earth 国家边界点查询器。"""

    def __init__(self, shp_path: Path):
        if not shp_path.exists():
            raise FileNotFoundError(f"Natural Earth shapefile 不存在: {shp_path}")

        self._countries = []
        with fiona.open(shp_path) as src:
            for feat in src:
                name = feat["properties"].get("NAME")
                if not name or feat["geometry"] is None:
                    continue
                geom = shape(feat["geometry"])
                self._countries.append((name, geom, prep(geom)))

        logger.info("已加载 Natural Earth 国家边界: %s (%d 个国家/地区)", shp_path, len(self._countries))

    def locate(self, lon: float, lat: float) -> str | None:
        point = Point(float(lon), float(lat))
        for name, geom, prepared in self._countries:
            if prepared.contains(point):
                return name

        # 边界点 contains=False；用 covers 兜底，避免正好落在国界线上的站点丢失。
        for name, geom, _ in self._countries:
            if geom.covers(point):
                return name
        return None

    def locate_many(self, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        return np.array([self.locate(lon, lat) for lon, lat in zip(lons, lats)], dtype=object)


# ---------------------------------------------------------------------------
# 场站出力处理（向量化）
# ---------------------------------------------------------------------------

def process_file(
    path: Path,
    tech: str,
    ssp: str,
    country_matcher: CountryMatcher,
    target_years: list[int],
    dt_hours: float,
):
    """读取场站出力 NC，返回 (df_annual, df_monthly)。"""
    region_dir = path.parent.name

    ds = nc_lib.Dataset(path, "r")
    power_ma = ds.variables["power"][:]
    power = (
        power_ma.filled(np.nan) if hasattr(power_ma, "filled") else np.asarray(power_ma)
    ).astype(np.float32)

    cap_gw   = np.asarray(ds.variables["capacity_gw"][:],    dtype=np.float64)
    act_year = np.asarray(ds.variables["activation_year"][:], dtype=np.int32)
    sta_lon  = np.asarray(ds.variables["station_lon"][:],     dtype=np.float64)
    sta_lat  = np.asarray(ds.variables["station_lat"][:],     dtype=np.float64)
    countries = country_matcher.locate_many(sta_lon, sta_lat)
    has_country = pd.notna(countries)
    n_unmatched = int((~has_country).sum())
    if n_unmatched:
        logger.warning("    [WARN] %s 有 %d 个场站未落入 Natural Earth 国家边界，已排除", path.name, n_unmatched)

    t_var     = ds.variables["time"]
    cft       = nc_lib.num2date(t_var[:], t_var.units)
    years_arr  = np.array([t.year  for t in cft], dtype=np.int32)
    months_arr = np.array([t.month for t in cft], dtype=np.int32)
    ds.close()

    ann_dfs, mon_dfs = [], []

    for yr in target_years:
        yr_mask    = years_arr == yr
        if not yr_mask.any():
            continue
        yr_power   = power[yr_mask, :]
        yr_months  = months_arr[yr_mask]
        n_yr_steps = int(yr_mask.sum())

        active    = act_year <= yr
        has_data  = ~np.all(np.isnan(yr_power), axis=0)
        valid_cap = cap_gw > 0
        include   = active & has_data & valid_cap & has_country
        idx       = np.where(include)[0]
        if len(idx) == 0:
            continue

        pwr_sum = np.nansum(yr_power[:, idx], axis=0)
        cap_mw  = cap_gw[idx] * 1000.0
        ann_cf  = pwr_sum / (n_yr_steps * cap_gw[idx])
        ann_gen = pwr_sum * dt_hours * 1000.0

        sta_ids = [f"{tech[0].upper()}{ssp[-3:]}_{region_dir}_{i:05d}" for i in idx]

        ann_dfs.append(pd.DataFrame({
            "station_id":             sta_ids,
            "country":                countries[idx],
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
            m_gen   = m_sum * dt_hours * 1000.0

            mon_dfs.append(pd.DataFrame({
                "station_id":              sta_ids,
                "country":                 countries[idx],
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
    args = parse_args()
    configure_logging(args.log_file)

    out_dir = args.out_dir or (ROOT / "data/real/RQ1_generation" / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("参数:")
    logger.info("  model        = %s", args.model)
    logger.info("  station_out  = %s", args.station_out)
    logger.info("  country_shp  = %s", args.country_shp)
    logger.info("  out_dir      = %s", out_dir)
    logger.info("  ssps         = %s", ", ".join(args.ssps))
    logger.info("  target_years = %s", ", ".join(map(str, args.target_years)))
    logger.info("  dt_hours     = %s", args.dt_hours)

    country_matcher = CountryMatcher(args.country_shp)

    all_ann, all_mon = [], []
    n_sta_ok = n_sta_miss = 0

    for tech_dir, tech in TECH_MAP.items():
        base = args.station_out / tech_dir / args.model
        if not base.exists():
            logger.warning("[WARN] 目录不存在，跳过: %s", base)
            continue

        regions = sorted(base.iterdir())
        logger.info("=== %s  (%d 个地区) ===", tech, len(regions))

        for region_path in regions:
            region  = region_path.name

            for ssp in args.ssps:
                # ---- 场站出力 ----
                sta_path = nc_filepath(args.station_out, args.model, tech_dir, ssp, region)
                if not sta_path.exists():
                    logger.info("  [MISS-STA] %s/%s/%s", tech, region, ssp)
                    n_sta_miss += 1
                else:
                    logger.info("  [STA]  %s/%s/%s ...", tech, region, ssp)
                    try:
                        df_ann, df_mon = process_file(
                            sta_path,
                            tech,
                            ssp,
                            country_matcher,
                            args.target_years,
                            args.dt_hours,
                        )
                        if df_ann.empty:
                            logger.info("    → 无有效场站数据")
                        else:
                            all_ann.append(df_ann)
                            all_mon.append(df_mon)
                            logger.info("    → %d 站×年记录", len(df_ann))
                            n_sta_ok += 1
                    except Exception as e:
                        logger.error("    [ERR] %s", e, exc_info=True)

    logger.info(
        "\n处理完成：站点 %d 成功 / %d 缺失；默认不生成 country_grid_cf.csv",
        n_sta_ok, n_sta_miss,
    )

    # 合并与保存
    df_ann_all = pd.concat(all_ann, ignore_index=True)
    df_mon_all = pd.concat(all_mon, ignore_index=True)
    df_cty_all = aggregate_country(df_ann_all)

    p_ann = out_dir / "station_annual_generation.csv"
    p_mon = out_dir / "station_monthly_generation.csv"
    p_cty = out_dir / "country_annual_generation.csv"

    df_ann_all.to_csv(p_ann, index=False)
    df_mon_all.to_csv(p_mon, index=False)
    df_cty_all.to_csv(p_cty, index=False)

    logger.info("\n已保存:")
    logger.info("  %s  (%d 行)", p_ann, len(df_ann_all))
    logger.info("  %s  (%d 行)", p_mon, len(df_mon_all))
    logger.info("  %s  (%d 行)", p_cty, len(df_cty_all))

    # 快速检验
    logger.info("\n=== 国家级场站统计 ===")
    chk = df_cty_all.groupby(["technology", "deploy_ssp", "target_year"]).agg(
        n_countries=("country", "count"),
        total_cap_gw=("capacity_mw", lambda x: x.sum() / 1000),
        total_gen_twh=("annual_generation_mwh", lambda x: x.sum() / 1e6),
        mean_station_cf=("mean_cf", "mean"),
    )
    logger.info("\n%s", chk.to_string())


if __name__ == "__main__":
    main()
