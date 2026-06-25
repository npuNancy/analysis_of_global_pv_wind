#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1: 各国多年平均容量因子柱状图
  上图：光伏（ERA5Land 2015–2025 均值 vs NESM3 SSP 2015–2025 均值）
  下图：风电（ERA5Land 2015–2020 均值 vs NESM3 SSP 2015–2020 均值）
输出：RQ1/outputs/real/{MODEL}/fig_CF_country_bar.png（按气候模式分目录）
"""

import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
MODEL        = "NESM3"  # 气候模式名；切换模式只需改此处，源目录/输出走对应子目录
ERA5LAND_DIR = "data/cfs/annual_mean_cf_ERA5Land"
NESM3_DIR    = f"data/cfs/annual_mean_cf/{MODEL}"
OUT          = f"RQ1/outputs/real/{MODEL}"
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------- #
# 字体 & 样式
# --------------------------------------------------------------------------- #
from matplotlib import font_manager as fm

FONT_PATH = "data/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(FONT_PATH)
FONT_NAME = fm.FontProperties(fname=FONT_PATH).get_name()

mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [FONT_NAME, "Arial", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "legend.fontsize": 7.5,
        "legend.frameon": False,
        "figure.dpi": 120,
        "savefig.dpi": 350,
        "pdf.fonttype": 42,
    }
)

SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
ERA_C = "#555555"
SSPS  = ["ssp126", "ssp245", "ssp585"]

SOLAR_YEARS = (2015, 2025)
WIND_YEARS  = (2015, 2020)

EXCLUDE_REGIONS = {"NAM-12"}


def panel_tag(ax, tag, dx=-0.04, dy=1.06):
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold",
            va="top", ha="right")


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def load_era5land(tech):
    f = os.path.join(ERA5LAND_DIR, tech, "per_country_annual_cf_ERA5Land.csv")
    if not os.path.exists(f):
        raise SystemExit(f"找不到文件：{f}")
    return pd.read_csv(f, skipinitialspace=True)


def load_nesm3():
    f = os.path.join(NESM3_DIR, f"per_country_annual_cf_{MODEL}.csv")
    if not os.path.exists(f):
        raise SystemExit(f"找不到文件：{f}")
    return pd.read_csv(f, skipinitialspace=True)


def compute_means(df_era, df_nesm3, tech, year_range):
    """计算 ERA5Land 和各 SSP 的各国多年平均 CF（%）。

    返回：(countries_sorted, era_mean, ssp_mean_dict)
      countries_sorted: 按 ERA5Land CF 降序排列的国家列表
      era_mean:         pd.Series, index=region, values=CF(%)
      ssp_mean_dict:    {ssp: pd.Series}
    """
    y0, y1 = year_range

    # ERA5Land
    e = df_era[
        (df_era.energy == tech)
        & df_era.year.between(y0, y1)
        & ~df_era.region.isin(EXCLUDE_REGIONS)
    ]
    era_mean = e.groupby("region")["mean_cf"].mean() * 100

    # NESM3
    n = df_nesm3[
        (df_nesm3.energy == tech)
        & df_nesm3.year.between(y0, y1)
    ]
    ssp_mean = {}
    for s in SSPS:
        sub = n[n.scenario == s]
        ssp_mean[s] = sub.groupby("region")["mean_cf"].mean() * 100

    # 取共同国家，按 ERA5Land CF 降序排列
    common = era_mean.index.intersection(ssp_mean["ssp126"].index)
    countries = sorted(common, key=lambda c: -era_mean[c])
    return countries, era_mean, ssp_mean


# --------------------------------------------------------------------------- #
# 绘图
# --------------------------------------------------------------------------- #
def draw_bars(ax, countries, era_mean, ssp_mean, title, panel):
    n   = len(countries)
    x   = np.arange(n)
    w   = 0.17                                   # 单柱宽度
    off = np.array([-1.5, -0.5, 0.5, 1.5]) * w  # ERA + 3 SSPs

    # ERA5Land
    ax.bar(
        x + off[0],
        [era_mean.get(c, np.nan) for c in countries],
        width=w, color=ERA_C, label="ERA5-Land",
    )
    # SSPs
    for i, s in enumerate(SSPS):
        ax.bar(
            x + off[i + 1],
            [ssp_mean[s].get(c, np.nan) for c in countries],
            width=w, color=SSP_C[s], label=SSP_L[s],
        )

    ax.set_xticks(x)
    ax.set_xticklabels(countries, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("容量因子 CF (%)")
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_title(title, fontsize=8.5)
    ax.grid(axis="y", lw=0.4, alpha=0.5)
    panel_tag(ax, panel)


def main():
    df_era_solar = load_era5land("solar")
    df_era_wind  = load_era5land("wind")
    df_nesm3     = load_nesm3()

    countries_s, era_s, ssp_s = compute_means(df_era_solar, df_nesm3, "solar", SOLAR_YEARS)
    countries_w, era_w, ssp_w = compute_means(df_era_wind,  df_nesm3, "wind",  WIND_YEARS)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.91, bottom=0.14, hspace=0.55)

    draw_bars(
        ax1, countries_s, era_s, ssp_s,
        f"光伏各国多年平均 CF（{SOLAR_YEARS[0]}–{SOLAR_YEARS[1]}，按 ERA5-Land 降序）",
        "a",
    )
    draw_bars(
        ax2, countries_w, era_w, ssp_w,
        f"风电各国多年平均 CF（{WIND_YEARS[0]}–{WIND_YEARS[1]}，按 ERA5-Land 降序）",
        "b",
    )

    # 统一图例放顶部
    handles = [Patch(fc=ERA_C, label="ERA5-Land")] + [
        Patch(fc=SSP_C[s], label=SSP_L[s]) for s in SSPS
    ]
    fig.legend(
        handles=handles,
        loc="upper center", bbox_to_anchor=(0.5, 0.985),
        ncol=4, fontsize=8, frameon=False,
    )

    fig.suptitle(
        "各国多年平均容量因子（NESM3 vs ERA5-Land）",
        fontsize=11, fontweight="bold", y=1.00,
    )

    out_path = f"{OUT}/fig_CF_country_bar.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print("已保存:", out_path)


if __name__ == "__main__":
    main()
