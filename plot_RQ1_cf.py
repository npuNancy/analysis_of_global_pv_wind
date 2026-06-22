#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：未来气候如何改变风/光的容量因子（CF）。

思路：CF 是纯气候驱动的资源质量指标。全部采用自洽情景
（deploy_ssp == climate_ssp）。风电、光伏分别成图。

说明：mock 数据没有气候模型维度，按要求整体当作 NESM3 情形处理。

输出：Nature 风格多面板图，保存到 ./figures/RQ1_future_generation/
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "outputs/RQ1_future_generation"
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------- #
# Nature 风格设置
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 中文字体（思源黑体）
# --------------------------------------------------------------------------- #
from matplotlib import font_manager as fm
FONT_PATH = "data/tracked/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(FONT_PATH)
FONT_NAME = fm.FontProperties(fname=FONT_PATH).get_name()

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [FONT_NAME, "Arial", "DejaVu Sans"],
    "axes.unicode_minus": False,    # 中文环境下用 ASCII 连字符，避免缺字
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
})

# IPCC 风格的 SSP 配色
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
YEARS = [2030, 2040, 2050]
SSPS = ["ssp126", "ssp245", "ssp585"]
DIVMAP = "RdBu_r"   # 发散型色带，用于变化量热图
YEAR_ALPHA = {2030: 0.85, 2040: 0.55, 2050: 0.30}   # 年份越早越实、叠在最前


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    """在子图左上角标注面板字母（a/b/c/d）。"""
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
country = pd.read_csv(f"{DATA}/country_annual_generation.csv")
st_ann  = pd.read_csv(f"{DATA}/station_annual_generation.csv")


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def global_cf(tech):
    """自洽情景（deploy==climate）下，按（climate_ssp, 年份）计算全球容量加权 CF。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == country.climate_ssp)].copy()
    d["wcf"] = d.capacity_mw * d.capacity_weighted_cf          # 容量 × CF
    g = d.groupby(["climate_ssp", "target_year"]).agg(
        cf=("wcf", "sum"), cap=("capacity_mw", "sum")).reset_index()
    g["cf"] = g.cf / g.cap                                     # 容量加权平均
    return g


def country_cf_change(tech):
    """自洽情景（deploy==climate）下各国 × climate_ssp 的容量加权 CF 变化率（2050 相对 2030，%）。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == country.climate_ssp)]
    p = d.pivot_table(index=["country", "climate_ssp"], columns="target_year",
                      values="capacity_weighted_cf")
    p["pct"] = (p[2050] - p[2030]) / p[2030] * 100.0
    return p.reset_index().pivot(index="country", columns="climate_ssp", values="pct")


def cf_array(tech, climate, year):
    """自洽情景（deploy==climate）下，场站年 CF（%）。"""
    d = st_ann[(st_ann.technology == tech) & (st_ann.deploy_ssp == climate)
               & (st_ann.climate_ssp == climate) & (st_ann.target_year == year)]
    return d.annual_capacity_factor.values * 100.0


def cf_limits(tech):
    """该技术全部 (情景×年份) 的 CF 取值范围，用于统一 KDE 网格与坐标。"""
    vals = np.concatenate([cf_array(tech, s, y) for s in SSPS for y in YEARS])
    lo, hi = vals.min(), vals.max()
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


# =========================================================================== #
# CF 图（风/光各一张）
# =========================================================================== #
def figure_cf(tech):
    g = global_cf(tech)
    cc = country_cf_change(tech)            # 各国 × ssp（%）
    fig = plt.figure(figsize=(7.2, 6.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.25],
                          hspace=0.42, wspace=0.34,
                          left=0.1, right=0.97, top=0.9, bottom=0.09)

    # (a) 全球 CF 时间轨迹 ----------------------------------------------------
    axa = fig.add_subplot(gs[0, 0])
    for s in SSPS:
        sub = g[g.climate_ssp == s].sort_values("target_year")
        axa.plot(sub.target_year, sub.cf * 100, "-o", color=SSP_C[s], lw=1.8,
                 ms=4, label=SSP_L[s])
    axa.set_xticks(YEARS)
    axa.set_xlabel("目标年份")
    axa.set_ylabel("容量加权 CF (%)")
    axa.set_title("全球容量因子轨迹", fontsize=8.5)
    axa.legend(loc="best")
    axa.grid(axis="y", lw=0.4, alpha=0.5)
    panel_tag(axa, "a")

    # (b) 场站级 CF 分布：嵌套小提琴（2030/2040/2050） ----------------------
    # 同一 SSP 位置叠放 3 个年份的小提琴，宽度按场站数缩放；场站数逐年增加，
    # 故 2050 最宽、把 2040/2030 “包”在里面。白点为各年中位数。
    axb = fig.add_subplot(gs[0, 1])
    lo, hi = cf_limits(tech)
    grid = np.linspace(lo, hi, 240)
    base_w = 0.42                                  # 单个 SSP 组的最大半宽
    for j, s in enumerate(SSPS):
        arrs = {y: cf_array(tech, s, y) for y in YEARS}
        # 计数密度（kde × n），组内统一缩放使最大处等于 base_w
        dens = {y: gaussian_kde(arrs[y])(grid) * len(arrs[y]) for y in YEARS}
        scale = base_w / max(d.max() for d in dens.values())
        for y in [2050, 2040, 2030]:               # 由宽到窄、从后往前画
            d = dens[y] * scale
            axb.fill_betweenx(grid, j - d, j + d, color=SSP_C[s],
                              alpha=YEAR_ALPHA[y], lw=0.4, edgecolor="white",
                              zorder=2 + YEARS.index(y))
            axb.plot(j, np.median(arrs[y]), "o", ms=3, mfc="white", mec="k",
                     mew=0.8, zorder=10)
    axb.set_xticks(range(len(SSPS)))
    axb.set_xticklabels([SSP_L[s] for s in SSPS], rotation=12)
    axb.set_ylabel("场站容量因子 (%)")
    axb.set_ylim(lo, hi)
    axb.set_title("场站 CF 分布（嵌套：宽度∝场站数）", fontsize=8.5)
    handles = [Patch(fc="0.4", alpha=YEAR_ALPHA[y], label=str(y)) for y in YEARS]
    handles.append(Line2D([], [], marker="o", ls="", mfc="white", mec="k",
                          mew=0.8, ms=4, label="中位数"))
    axb.legend(handles=handles, loc="upper right", fontsize=6)
    panel_tag(axb, "b")

    # (c) 各国 × ssp 的 CF 变化热图 ------------------------------------------
    axc = fig.add_subplot(gs[1, 0])
    order = cc[SSPS].mean(axis=1).sort_values().index          # 按平均变化排序
    M = cc.loc[order, SSPS].values
    vmax = np.nanmax(np.abs(M))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)       # 以 0 为中心
    im = axc.imshow(M, aspect="auto", cmap=DIVMAP, norm=norm)
    axc.set_xticks(range(len(SSPS)))
    axc.set_xticklabels([SSP_L[s] for s in SSPS], rotation=20, fontsize=7)
    axc.set_yticks(range(len(order)))
    axc.set_yticklabels(order, fontsize=5.6)
    axc.set_title("各国 CF 变化（2050 vs 2030，%）", fontsize=8.5)
    cb = fig.colorbar(im, ax=axc, fraction=0.046, pad=0.03)
    cb.set_label("变化率 (%)", fontsize=7)
    cb.ax.tick_params(labelsize=6)
    panel_tag(axc, "c")

    # (d) SSP5-8.5 下涨跌幅最大的国家排序 ------------------------------------
    axd = fig.add_subplot(gs[1, 1])
    r = cc["ssp585"].sort_values()
    sel = pd.concat([r.head(8), r.tail(8)])                    # 跌幅与涨幅各取 8
    colors = [SSP_C["ssp585"] if v >= 0 else SSP_C["ssp126"] for v in sel.values]
    ypos = range(len(sel))
    axd.barh(ypos, sel.values, color=colors, edgecolor="white", lw=0.4)
    axd.axvline(0, color="0.3", lw=0.7)
    axd.set_yticks(list(ypos))
    axd.set_yticklabels(sel.index, fontsize=6)
    axd.set_xlabel("CF 变化 2050 vs 2030 (%)")
    axd.set_title("涨跌幅最大的国家（SSP5-8.5）", fontsize=8.5)
    panel_tag(axd, "d")

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"未来气候对{tech_cn}容量因子的影响",
                 fontsize=11, fontweight="bold", y=0.975)
    fig.text(0.5, 0.005,
             "自洽情景（部署 = 气候）；28 个区域容量加权。",
             ha="center", fontsize=6.2, color="0.4")
    p = f"{OUT}/fig_CF_{tech}.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_cf(tech))
