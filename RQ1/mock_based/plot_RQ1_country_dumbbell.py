#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 候选图 ③ —— 各国哑铃图：CF 对气候路径的敏感度（SSP1-2.6 ↔ SSP5-8.5，2050）。

每个国家一条哑铃：左端=该国 2050 年 SSP1-2.6 下的容量加权 CF，右端=SSP5-8.5 下的
CF；连线长度=气候路径造成的差距。按差距大小排序，最敏感的国家在上。风、光并列两栏。
固定机队（deploy=ssp245），仅变化 climate_ssp。

输出：outputs/RQ1_future_generation/tmp/fig_dumbbell.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib import font_manager as fm

DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "outputs/RQ1_future_generation/tmp"
os.makedirs(OUT, exist_ok=True)

FONT_PATH = "data/tracked/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(FONT_PATH)
FONT_NAME = fm.FontProperties(fname=FONT_PATH).get_name()
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [FONT_NAME, "Arial", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
    "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "legend.fontsize": 7, "legend.frameon": False,
    "figure.dpi": 120, "savefig.dpi": 350, "pdf.fonttype": 42,
})

SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
TECH_CN = {"solar": "光伏", "wind": "风电"}
SORT_BY = "ssp585"   # 排序依据：按该情景的 CF 升序排列国家（可改为 "ssp126"）

country = pd.read_csv(f"{DATA}/country_annual_generation.csv")


def cf_country(tech, deploy="ssp245", year=2050):
    """各国 2050 年在 3 个气候情景下的容量加权 CF（%）。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == deploy)
                & (country.target_year == year)]
    return d.pivot_table(index="country", columns="climate_ssp",
                         values="capacity_weighted_cf") * 100


def draw_dumbbell(ax, tech):
    p = cf_country(tech)
    p["gap"] = p["ssp585"] - p["ssp126"]
    p = p.sort_values(SORT_BY)                     # 按指定情景的 CF 升序排列
    yp = np.arange(len(p))
    # 连线（颜色按方向：CF 下降=红，上升=蓝）
    for k, (_, r) in enumerate(p.iterrows()):
        c = SSP_C["ssp585"] if r["gap"] < 0 else SSP_C["ssp126"]
        ax.plot([r["ssp126"], r["ssp585"]], [k, k], color=c, lw=1.4, alpha=0.6,
                zorder=1)
    ax.scatter(p["ssp126"], yp, s=22, color=SSP_C["ssp126"], zorder=3,
               edgecolor="white", lw=0.4)
    ax.scatter(p["ssp585"], yp, s=22, color=SSP_C["ssp585"], zorder=3,
               edgecolor="white", lw=0.4)
    ax.set_yticks(yp); ax.set_yticklabels(p.index, fontsize=5.8)
    ax.set_ylim(-0.6, len(p) - 0.4)
    ax.set_xlabel("容量加权 CF (%)")
    ax.set_title(f"{TECH_CN[tech]}", fontsize=9)
    ax.grid(axis="x", lw=0.3, alpha=0.5)


fig, axes = plt.subplots(1, 2, figsize=(7.4, 6.6))
fig.subplots_adjust(left=0.1, right=0.97, bottom=0.1, top=0.86, wspace=0.42)
for ax, tech, tag in zip(axes, ["solar", "wind"], "ab"):
    draw_dumbbell(ax, tech)
    ax.text(-0.12, 1.02, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")
handles = [Line2D([], [], marker="o", ls="", mfc=SSP_C["ssp126"], mec="white",
                  ms=6, label=SSP_L["ssp126"]),
           Line2D([], [], marker="o", ls="", mfc=SSP_C["ssp585"], mec="white",
                  ms=6, label=SSP_L["ssp585"])]
fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.52, 0.93))
fig.suptitle(f"各国 CF 对气候路径的敏感度（2050，按 {SSP_L[SORT_BY]} 的 CF 升序）",
             fontsize=10.5, fontweight="bold", y=0.97)
p = f"{OUT}/fig_dumbbell.png"
fig.savefig(p, bbox_inches="tight"); plt.close(fig)
print("已保存:", p)
