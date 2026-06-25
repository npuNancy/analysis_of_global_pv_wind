#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 候选图 ① —— SSP 发散扇形图。

核心：不同 SSP 路径下，CF 相对 2030 的异常值随时间张开为“扇形”，扇口大小即
SSP 间差异。固定机队（deploy=ssp245）、仅变化 climate_ssp，隔离纯气候信号。

- 实线 = 全球容量加权 CF 异常（相对 2030，%）
- 阴影带 = 28 国异常值的 25–75% 分布
- 2050 处标注 SSP1-2.6 与 SSP5-8.5 的差距

输出：outputs/RQ1_future_generation/tmp/fig_sspfan.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "RQ1/outputs/mock/tmp"
os.makedirs(OUT, exist_ok=True)

FONT_PATH = "data/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(FONT_PATH)
FONT_NAME = fm.FontProperties(fname=FONT_PATH).get_name()
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [FONT_NAME, "Arial", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
    "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "xtick.major.size": 3, "ytick.major.size": 3,
    "legend.fontsize": 7, "legend.frameon": False,
    "figure.dpi": 120, "savefig.dpi": 350, "pdf.fonttype": 42,
})

SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
SSPS = ["ssp126", "ssp245", "ssp585"]
YEARS = [2030, 2040, 2050]
TECH_CN = {"solar": "光伏", "wind": "风电"}

country = pd.read_csv(f"{DATA}/country_annual_generation.csv")


def cf_anomaly(tech, deploy="ssp245"):
    """返回 (全球异常 dict[ssp][year], 各国异常 DataFrame)。异常 = 相对 2030 的 %。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == deploy)].copy()
    d["wcf"] = d.capacity_mw * d.capacity_weighted_cf
    # 全球容量加权 CF
    g = d.groupby(["climate_ssp", "target_year"]).agg(
        wcf=("wcf", "sum"), cap=("capacity_mw", "sum")).reset_index()
    g["cf"] = g.wcf / g.cap
    glob = {}
    for s in SSPS:
        v = g[g.climate_ssp == s].set_index("target_year")["cf"]
        glob[s] = {y: (v[y] - v[2030]) / v[2030] * 100 for y in YEARS}
    # 各国异常（用于分布带）
    p = d.pivot_table(index=["country", "climate_ssp"], columns="target_year",
                      values="capacity_weighted_cf")
    for y in YEARS:
        p[f"a{y}"] = (p[y] - p[2030]) / p[2030] * 100
    return glob, p.reset_index()


def draw_fan(ax, tech):
    glob, cc = cf_anomaly(tech)
    for s in SSPS:
        yvals = [glob[s][y] for y in YEARS]
        sub = cc[cc.climate_ssp == s]
        q25 = [sub[f"a{y}"].quantile(0.25) for y in YEARS]
        q75 = [sub[f"a{y}"].quantile(0.75) for y in YEARS]
        ax.fill_between(YEARS, q25, q75, color=SSP_C[s], alpha=0.16, lw=0)
        ax.plot(YEARS, yvals, "-o", color=SSP_C[s], lw=2, ms=4, zorder=5)
        ax.annotate(SSP_L[s], (YEARS[-1], yvals[-1]), color=SSP_C[s],
                    fontsize=7.5, fontweight="bold", va="center",
                    xytext=(6, 0), textcoords="offset points")
    # 2050 处 SSP126 与 SSP585 的差距括号
    y126, y585 = glob["ssp126"][2050], glob["ssp585"][2050]
    xb = 2050.5
    ax.annotate("", xy=(xb, y126), xytext=(xb, y585),
                arrowprops=dict(arrowstyle="<->", color="0.3", lw=1.0))
    ax.text(xb + 0.4, (y126 + y585) / 2, f"差距 {abs(y126 - y585):.1f} 个百分点",
            fontsize=6.5, color="0.3", rotation=90, va="center", ha="left")
    ax.axhline(0, color="0.6", lw=0.7, ls="--")
    ax.set_xticks(YEARS)
    ax.set_xlim(2028, 2054)
    ax.set_xlabel("目标年份")
    ax.set_ylabel("CF 异常（相对 2030，%）")
    ax.set_title(f"{TECH_CN[tech]}", fontsize=9)


fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.5), sharey=False)
fig.subplots_adjust(left=0.09, right=0.95, bottom=0.16, top=0.82, wspace=0.28)
for ax, tech, tag in zip(axes, ["solar", "wind"], "ab"):
    draw_fan(ax, tech)
    ax.text(-0.1, 1.05, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")
fig.suptitle("SSP 路径下容量因子的发散（实线=全球；带=各国 25–75%）",
             fontsize=10.5, fontweight="bold", y=0.97)
fig.text(0.52, 0.005, "固定部署机队（deploy = SSP2-4.5），仅变化气候情景。",
         ha="center", fontsize=6.2, color="0.45")
p = f"{OUT}/fig_sspfan.png"
fig.savefig(p, bbox_inches="tight"); plt.close(fig)
print("已保存:", p)
