#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：容量因子与发电量的综合对比（风电 vs 光伏）。

把两个分析维度放到一起：左图为气候对 CF 的影响（资源质量信号），
右图为发电量的增长（实际出力规模），直观对比风、光在不同 SSP 下的差异。

说明：mock 数据没有气候模型维度，按要求整体当作 NESM3 情形处理。

输出：保存到 ./figures/RQ1_future_generation/
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "outputs/mock/RQ1_future_generation"
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
SSPS = ["ssp126", "ssp245", "ssp585"]


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    """在子图左上角标注面板字母（a/b）。"""
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
country = pd.read_csv(f"{DATA}/country_annual_generation.csv")


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def global_cf(tech, deploy="ssp245"):
    """固定机队下，按（climate_ssp, 年份）计算全球容量加权 CF。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == deploy)].copy()
    d["wcf"] = d.capacity_mw * d.capacity_weighted_cf
    g = d.groupby(["climate_ssp", "target_year"]).agg(
        cf=("wcf", "sum"), cap=("capacity_mw", "sum")).reset_index()
    g["cf"] = g.cf / g.cap
    return g


def gen_trajectory(tech):
    """自洽情景（deploy==climate）下，按 ssp、年份汇总全球发电量（TWh）。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == country.climate_ssp)]
    g = d.groupby(["climate_ssp", "target_year"]).agg(
        gen=("annual_generation_mwh", "sum"),
        cap=("capacity_mw", "sum")).reset_index()
    g["gen_twh"] = g.gen / 1e6
    return g


# =========================================================================== #
# 综合对比图：风电 vs 光伏
# =========================================================================== #
def figure_synthesis():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.3))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.18, top=0.84, wspace=0.32)

    width = 0.25
    x = np.arange(2)  # 0=光伏, 1=风电

    # (a) 各 SSP 下全球 CF 变化率（2050 vs 2030），按技术分组 -----------------
    for j, s in enumerate(SSPS):
        vals = []
        for tech in ["solar", "wind"]:
            g = global_cf(tech)
            v30 = g[(g.climate_ssp == s) & (g.target_year == 2030)].cf.values[0]
            v50 = g[(g.climate_ssp == s) & (g.target_year == 2050)].cf.values[0]
            vals.append((v50 - v30) / v30 * 100)
        ax1.bar(x + (j - 1) * width, vals, width, color=SSP_C[s], label=SSP_L[s])
    ax1.axhline(0, color="0.3", lw=0.7)
    ax1.set_xticks(x); ax1.set_xticklabels(["光伏", "风电"])
    ax1.set_ylabel("全球 CF 变化\n2050 vs 2030 (%)")
    ax1.set_title("容量因子中的气候信号", fontsize=8.5)
    ax1.legend(loc="best")
    panel_tag(ax1, "a")

    # (b) 各技术、各情景的发电量增长 2030→2050 -------------------------------
    for j, s in enumerate(SSPS):
        vals = []
        for tech in ["solar", "wind"]:
            g = gen_trajectory(tech)
            v30 = g[(g.climate_ssp == s) & (g.target_year == 2030)].gen_twh.values[0]
            v50 = g[(g.climate_ssp == s) & (g.target_year == 2050)].gen_twh.values[0]
            vals.append(v50 - v30)
        ax2.bar(x + (j - 1) * width, vals, width, color=SSP_C[s], label=SSP_L[s])
    ax2.set_xticks(x); ax2.set_xticklabels(["光伏", "风电"])
    ax2.set_ylabel("发电量增量 2030→2050 (TWh)")
    ax2.set_title("发电量总增长", fontsize=8.5)
    panel_tag(ax2, "b")

    fig.suptitle("综合对比：未来气候下的风电 vs 光伏",
                 fontsize=11, fontweight="bold", y=0.98)
    p = f"{OUT}/fig_synthesis_wind_vs_solar.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("已保存:", figure_synthesis())
