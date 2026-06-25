#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 补充图：场站级 装机容量 / 容量因子(CF) / 发电量 的嵌套小提琴图。

光伏、风电各出一张图；每张图含 3 个子图（装机容量、CF、发电量），
每个子图为 3 个 SSP × 3 个年份（2030/2040/2050）的嵌套小提琴，
横轴区分 3 个 SSP。三个 SSP 的 2050 年中位数用虚线线性拟合（无 legend）。

- CF 子图风格同 RQ1/plot_RQ1_cf.py 的图 b
- 发电量子图风格同 RQ1/plot_RQ1_generation.py 的图 e

数据：data/real/RQ1_generation/{MODEL}/station_annual_generation.csv
输出：outputs/real/RQ1_generation/{MODEL}/fig_VIOLIN_{solar,wind}.png
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
MODEL = "NESM3"  # 气候模式名；切换模式只需改此处，数据/输出走对应子目录
DATA = f"data/real/RQ1_generation/{MODEL}"
OUT = f"outputs/real/RQ1_generation/{MODEL}"
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
YEAR_ALPHA = {2030: 0.85, 2040: 0.55, 2050: 0.30}
FIT_YEAR = 2050  # 用于中位数虚线拟合的年份


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
st_ann = pd.read_csv(f"{DATA}/station_annual_generation.csv")


# --------------------------------------------------------------------------- #
# 自洽情景（部署=气候）下的场站取值，排除零值（用于 KDE）
# --------------------------------------------------------------------------- #
def _coherent(tech, ssp, year):
    return st_ann[
        (st_ann.technology == tech)
        & (st_ann.deploy_ssp == ssp)
        & (st_ann.climate_ssp == ssp)
        & (st_ann.target_year == year)
    ]


def cap_array(tech, ssp, year):
    """场站装机容量（MW），排除零值。"""
    vals = _coherent(tech, ssp, year).capacity_mw.values
    return vals[vals > 0]


def cf_array(tech, ssp, year):
    """场站年容量因子（%），排除零值。"""
    vals = _coherent(tech, ssp, year).annual_capacity_factor.values * 100.0
    return vals[vals > 0]


def gen_array(tech, ssp, year):
    """场站年发电量（GWh），排除零值。"""
    vals = _coherent(tech, ssp, year).annual_generation_mwh.values / 1e3
    return vals[vals > 0]


# --------------------------------------------------------------------------- #
# 通用嵌套小提琴绘制
# --------------------------------------------------------------------------- #
def _limits(arr_fn, tech, log=False):
    parts = [arr_fn(tech, s, y) for s in SSPS for y in YEARS]
    parts = [v for v in parts if len(v) > 1]
    if not parts:
        return (-1, 4) if log else (0, 1)
    vals = np.concatenate(parts)
    lo, hi = (np.log10(vals.min()), np.log10(vals.max())) if log else (vals.min(), vals.max())
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def violin_panel(ax, arr_fn, tech, ylabel, title, log=False):
    """在 ax 上绘制 3 SSP × 3 年份 的嵌套小提琴；2050 中位数虚线拟合。"""
    lo, hi = _limits(arr_fn, tech, log=log)
    grid = np.linspace(lo, hi, 300)
    ygrid = 10**grid if log else grid
    base_w = 0.42

    fit_x, fit_y = [], []  # 收集各 SSP 的 2050 中位数
    for j, s in enumerate(SSPS):
        arrs = {y: arr_fn(tech, s, y) for y in YEARS}
        if any(len(v) < 3 for v in arrs.values()):
            continue
        if log:
            dens = {y: gaussian_kde(np.log10(arrs[y]))(grid) * len(arrs[y]) for y in YEARS}
        else:
            dens = {y: gaussian_kde(arrs[y])(grid) * len(arrs[y]) for y in YEARS}
        scale = base_w / max(d.max() for d in dens.values())
        for y in [2050, 2040, 2030]:
            d = dens[y] * scale
            ax.fill_betweenx(
                ygrid, j - d, j + d,
                color=SSP_C[s], alpha=YEAR_ALPHA[y],
                lw=0.4, edgecolor="white", zorder=2 + YEARS.index(y),
            )
            med = np.median(arrs[y])
            ax.plot(j, med, "o", ms=3, mfc="white", mec="k", mew=0.8, zorder=10)
            if y == FIT_YEAR:
                fit_x.append(j)
                fit_y.append(med)

    # 三个 SSP 的 2050 中位数线性拟合（虚线，无 legend）
    if len(fit_x) >= 2:
        xs = np.array([min(fit_x), max(fit_x)])
        if log:
            coef = np.polyfit(fit_x, np.log10(fit_y), 1)
            ax.plot(xs, 10 ** np.polyval(coef, xs), "--", color="0.3", lw=1.2, zorder=11)
        else:
            coef = np.polyfit(fit_x, fit_y, 1)
            ax.plot(xs, np.polyval(coef, xs), "--", color="0.3", lw=1.2, zorder=11)

    if log:
        ax.set_yscale("log")
    ax.set_xticks(range(len(SSPS)))
    ax.set_xticklabels([SSP_L[s] for s in SSPS], rotation=12, fontsize=7)
    ax.set_ylabel(ylabel)
    ax.set_ylim(ygrid[0], ygrid[-1])
    ax.set_title(title, fontsize=8.5)


# =========================================================================== #
# 主绘图函数
# =========================================================================== #
def figure_violin(tech):
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(10.5, 3.8))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.84, bottom=0.16, wspace=0.34)

    violin_panel(ax1, cap_array, tech, "场站装机容量 (MW，对数)", "装机容量分布", log=True)
    panel_tag(ax1, "a")

    violin_panel(ax2, cf_array, tech, "场站容量因子 (%)", "容量因子(CF)分布", log=False)
    panel_tag(ax2, "b")

    violin_panel(ax3, gen_array, tech, "场站年发电量 (GWh，对数)", "发电量分布", log=True)
    panel_tag(ax3, "c")

    # 统一图例（放在最右子图）
    handles = [Patch(fc="0.4", alpha=YEAR_ALPHA[y], label=str(y)) for y in YEARS]
    handles.append(Line2D([], [], marker="o", ls="", mfc="white", mec="k", mew=0.8, ms=4, label="中位数"))
    handles.append(Line2D([], [], ls="--", color="0.3", lw=1.2, label=f"{FIT_YEAR} 中位数拟合"))
    ax3.legend(handles=handles, loc="upper right", fontsize=6)

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"未来气候下{tech_cn}场站 装机/CF/发电量 分布（{MODEL}）", fontsize=11, fontweight="bold")
    fig.text(0.5, 0.92, "装机容量 × 容量因子 = 发电量", ha="center", fontsize=8.5, color="0.3")
    fig.text(
        0.5, 0.012,
        "自洽情景（部署=气候）；嵌套小提琴宽度∝场站数，颜色深浅区分年份；均排除零出力站；"
        "虚线为三情景 2050 中位数线性拟合。",
        ha="center", fontsize=6.2, color="0.4",
    )

    p = f"{OUT}/fig_VIOLIN_{tech}.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_violin(tech))
