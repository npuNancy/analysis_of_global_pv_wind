#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：未来气候如何改变风/光的容量因子（CF）。NESM3 真实数据版。

数据：data/real/RQ1_generation/（由 prepare_RQ1_data.py 生成）
输出：outputs/real/RQ1_generation/fig_CF_{solar,wind}.png
"""

import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
DATA = "data/real/RQ1_generation"
OUT = "outputs/real/RQ1_generation"
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
        "legend.fontsize": 7,
        "legend.frameon": False,
        "figure.dpi": 120,
        "savefig.dpi": 350,
        "pdf.fonttype": 42,
    }
)

SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
YEARS = [2030, 2040, 2050]
SSPS = ["ssp126", "ssp245", "ssp585"]
DIVMAP = "RdBu_r"
YEAR_ALPHA = {2030: 0.85, 2040: 0.55, 2050: 0.30}


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
country = pd.read_csv(f"{DATA}/country_annual_generation.csv")
st_ann  = pd.read_csv(f"{DATA}/station_annual_generation.csv")
grid_cf = pd.read_csv(f"{DATA}/country_grid_cf.csv")


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def global_cf(tech):
    """各国格点年均 CF 的全球均值（各国等权）。用于图 a 折线图。"""
    d = grid_cf[grid_cf.technology == tech]
    g = (
        d.groupby(["climate_ssp", "target_year"])["mean_grid_cf"]
        .mean()
        .reset_index()
        .rename(columns={"mean_grid_cf": "cf"})
    )
    return g


def country_cf_change(tech):
    """各国格点 CF 变化率（2050 vs 2030，%）。用于图 c 热图、图 d 柱图。
    缺失国家/SSP 组合以 NaN 填充。"""
    d = grid_cf[grid_cf.technology == tech]
    p = d.pivot_table(index=["country", "climate_ssp"], columns="target_year",
                      values="mean_grid_cf")
    if 2030 not in p.columns:
        return pd.DataFrame()
    p["pct"] = (p[2050] - p[2030]) / p[2030].replace(0, np.nan) * 100.0
    return p.reset_index().pivot(index="country", columns="climate_ssp", values="pct")


def cf_array(tech, climate, year):
    """自洽情景下场站年 CF（%），排除零值（用于 KDE）。"""
    d = st_ann[
        (st_ann.technology == tech)
        & (st_ann.deploy_ssp == climate)
        & (st_ann.climate_ssp == climate)
        & (st_ann.target_year == year)
    ]
    vals = d.annual_capacity_factor.values * 100.0
    return vals[vals > 0]


def cf_limits(tech):
    """统一 KDE y 范围（排除零值）。"""
    parts = [cf_array(tech, s, y) for s in SSPS for y in YEARS]
    parts = [v for v in parts if len(v) > 1]
    if not parts:
        return 0, 50
    vals = np.concatenate(parts)
    lo, hi = vals.min(), vals.max()
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


# =========================================================================== #
# 主绘图函数
# =========================================================================== #
def figure_cf(tech):
    g = global_cf(tech)

    fig, (axa, axb) = plt.subplots(1, 2, figsize=(7.2, 3.4))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.86, bottom=0.14, wspace=0.34)

    # (a) 全球 CF 时间轨迹 -------------------------------------------------------
    for s in SSPS:
        sub = g[g.climate_ssp == s].sort_values("target_year")
        if sub.empty:
            continue
        axa.plot(sub.target_year, sub.cf * 100, "-o", color=SSP_C[s], lw=1.8, ms=4, label=SSP_L[s])
    axa.set_xticks(YEARS)
    axa.set_xlabel("目标年份")
    axa.set_ylabel("容量因子 CF (%)")
    axa.set_title("全球容量因子轨迹", fontsize=8.5)
    axa.legend(loc="best")
    axa.grid(axis="y", lw=0.4, alpha=0.5)
    panel_tag(axa, "a")

    # (b) 场站 CF 分布：嵌套小提琴 -----------------------------------------------
    lo, hi = cf_limits(tech)
    grid = np.linspace(lo, hi, 300)
    base_w = 0.42
    for j, s in enumerate(SSPS):
        arrs = {y: cf_array(tech, s, y) for y in YEARS}
        if any(len(v) < 3 for v in arrs.values()):
            continue
        dens = {y: gaussian_kde(arrs[y])(grid) * len(arrs[y]) for y in YEARS}
        scale = base_w / max(d.max() for d in dens.values())
        for y in [2050, 2040, 2030]:
            d = dens[y] * scale
            axb.fill_betweenx(
                grid, j - d, j + d,
                color=SSP_C[s], alpha=YEAR_ALPHA[y],
                lw=0.4, edgecolor="white", zorder=2 + YEARS.index(y),
            )
            axb.plot(j, np.median(arrs[y]), "o", ms=3, mfc="white", mec="k", mew=0.8, zorder=10)
    axb.set_xticks(range(len(SSPS)))
    axb.set_xticklabels([SSP_L[s] for s in SSPS], rotation=12)
    axb.set_ylabel("场站容量因子 (%)")
    axb.set_ylim(lo, hi)
    axb.set_title("场站 CF 分布（嵌套：宽度∝场站数）", fontsize=8.5)
    handles = [Patch(fc="0.4", alpha=YEAR_ALPHA[y], label=str(y)) for y in YEARS]
    handles.append(Line2D([], [], marker="o", ls="", mfc="white", mec="k", mew=0.8, ms=4, label="中位数"))
    axb.legend(handles=handles, loc="upper right", fontsize=6)
    panel_tag(axb, "b")

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"未来气候对{tech_cn}容量因子的影响（NESM3）", fontsize=11, fontweight="bold")
    fig.text(
        0.5, 0.01,
        "自洽情景（部署=气候）；NESM3 模型；图 a：格点 CF 各国等权均值；图 b：站点级 CF（排除零值站）。",
        ha="center", fontsize=6.2, color="0.4",
    )

    p = f"{OUT}/fig_CF_{tech}.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_cf(tech))
