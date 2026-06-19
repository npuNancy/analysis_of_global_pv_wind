#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 候选图 ⑥ —— 出力稳定性与风光互补随 SSP 的变化（超越“均值”的维度）。

固定机队（deploy=ssp245）、2050 年，用月度数据：
  (a) 光伏：各场站 12 个月 CF 的变异系数(CV=std/mean) 按 SSP 的分布
  (b) 风电：同上
  (c) 风光互补：各国“月度风发电 vs 月度光发电”的相关系数按 SSP 的分布
      （越接近 -1 互补越好，对电网越友好）
看增暖是否让出力更不稳定、风光互补是否被削弱。

输出：outputs/RQ1_future_generation/tmp/fig_stability.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "outputs/RQ1_future_generation/tmp"
os.makedirs(OUT, exist_ok=True)

FONT_PATH = "/data4/yanxiaokai/SourceHanSansSC-Normal.otf"
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
SSPS = ["ssp126", "ssp245", "ssp585"]

mon = pd.read_csv(f"{DATA}/station_monthly_generation.csv")


def cv_by_station(tech, climate, year=2050, deploy="ssp245"):
    """各场站 12 个月 CF 的变异系数（%）。"""
    d = mon[(mon.technology == tech) & (mon.deploy_ssp == deploy)
            & (mon.climate_ssp == climate) & (mon.target_year == year)]
    g = d.groupby("station_id").monthly_capacity_factor.agg(["mean", "std"])
    return (g["std"] / g["mean"] * 100).dropna().values


def corr_by_country(climate, year=2050, deploy="ssp245"):
    """各国 月度风发电 vs 月度光发电 的相关系数。"""
    d = mon[(mon.deploy_ssp == deploy) & (mon.climate_ssp == climate)
            & (mon.target_year == year)]
    g = d.groupby(["country", "technology", "month"]).monthly_generation_mwh.sum()
    pv = g.unstack("technology")
    out = []
    for c, grp in pv.groupby(level=0):
        if {"solar", "wind"}.issubset(grp.columns):
            sub = grp[["solar", "wind"]].dropna()
            if len(sub) >= 6 and sub["solar"].std() > 0 and sub["wind"].std() > 0:
                out.append(sub["solar"].corr(sub["wind"]))
    return np.array(out)


def violin(ax, datasets, ylabel, title, ylim=None):
    parts = ax.violinplot(datasets, positions=range(len(SSPS)), widths=0.8,
                          showextrema=False)
    for pc, s in zip(parts["bodies"], SSPS):
        pc.set_facecolor(SSP_C[s]); pc.set_alpha(0.55); pc.set_edgecolor("none")
    for i, arr in enumerate(datasets):
        med = np.median(arr)
        ax.plot([i - 0.22, i + 0.22], [med, med], color="k", lw=1.3, zorder=5)
        ax.annotate(f"{med:.2f}" if abs(med) < 5 else f"{med:.1f}", (i, med),
                    textcoords="offset points", xytext=(13, 0), va="center",
                    fontsize=6, color="0.25")
    ax.set_xticks(range(len(SSPS)))
    ax.set_xticklabels([SSP_L[s] for s in SSPS], rotation=12)
    ax.set_ylabel(ylabel); ax.set_title(title, fontsize=8.5)
    if ylim:
        ax.set_ylim(*ylim)


fig, axes = plt.subplots(1, 3, figsize=(7.8, 3.3))
fig.subplots_adjust(left=0.07, right=0.98, bottom=0.16, top=0.8, wspace=0.34)

violin(axes[0], [cv_by_station("solar", s) for s in SSPS],
       "月度 CF 变异系数 (%)", "光伏出力波动性")
violin(axes[1], [cv_by_station("wind", s) for s in SSPS],
       "月度 CF 变异系数 (%)", "风电出力波动性")
ax3data = [corr_by_country(s) for s in SSPS]
violin(axes[2], ax3data, "风–光月度相关系数", "风光互补性（越负越好）")
axes[2].axhline(0, color="0.5", lw=0.7, ls="--")

for ax, tag in zip(axes, "abc"):
    ax.text(-0.16, 1.05, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")
fig.suptitle("出力稳定性与风光互补随 SSP 的变化（2050，固定机队）",
             fontsize=10.5, fontweight="bold", y=0.97)
p = f"{OUT}/fig_stability.png"
fig.savefig(p, bbox_inches="tight"); plt.close(fig)
print("已保存:", p)
