#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 候选图 ④ —— CF 的纬度 / 资源带剖面（SSP 差异藏在哪）。

把 station_annual 的场站 CF（随气候情景变化）经 station_id 关联到 catalog 的纬度与
resource_index，固定机队（deploy=ssp245）、2050 年：
  (a) CF 随纬度带的变化（3 条 SSP 线 + 25–75% 带）
  (b) CF 随 resource_index 十分位的变化
展示 SSP 间差异在哪些纬度 / 资源等级最显著（不画地图，符合区域受限的约束）。

风电、光伏各一张。
输出：outputs/RQ1_future_generation/tmp/fig_latprofile_{solar,wind}.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "outputs/mock/RQ1_future_generation/tmp"
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
SSPS = ["ssp126", "ssp245", "ssp585"]
TECH_CN = {"solar": "光伏", "wind": "风电"}

ann = pd.read_csv(f"{DATA}/station_annual_generation.csv")
cat = pd.read_csv(f"{DATA}/station_catalog.csv")[
    ["station_id", "lat", "resource_index"]]


def joined(tech, deploy="ssp245", year=2050):
    a = ann[(ann.technology == tech) & (ann.deploy_ssp == deploy)
            & (ann.target_year == year)].merge(cat, on="station_id", how="left")
    a["cf"] = a.annual_capacity_factor * 100
    return a


def profile(ax, a, xcol, bins, xlabel, binlabels=None):
    a = a.dropna(subset=[xcol]).copy()
    a["bin"] = pd.cut(a[xcol], bins=bins)
    centers = [iv.mid for iv in a["bin"].cat.categories]
    for s in SSPS:
        sub = a[a.climate_ssp == s]
        gp = sub.groupby("bin", observed=False)["cf"]
        med = gp.median().values
        q25 = gp.quantile(0.25).values
        q75 = gp.quantile(0.75).values
        ax.fill_between(centers, q25, q75, color=SSP_C[s], alpha=0.14, lw=0)
        ax.plot(centers, med, "-o", color=SSP_C[s], lw=1.6, ms=3,
                label=SSP_L[s])
    ax.set_xlabel(xlabel)
    ax.set_ylabel("场站容量因子 (%)")
    if binlabels is not None:
        ax.set_xticks(centers); ax.set_xticklabels(binlabels, fontsize=6.5)


def make(tech):
    a = joined(tech)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 3.5))
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.16, top=0.8, wspace=0.28)

    # (a) 纬度带
    latbins = np.arange(np.floor(a.lat.min() / 10) * 10,
                        np.ceil(a.lat.max() / 10) * 10 + 1, 10)
    profile(ax1, a, "lat", latbins, "纬度 (°)")
    ax1.legend(loc="best")
    ax1.set_title("沿纬度", fontsize=8.5)

    # (b) resource_index 十分位
    qbins = np.array(a.resource_index.quantile(np.linspace(0, 1, 11)).values,
                     dtype=float)
    qbins[0] -= 1e-9
    profile(ax2, a, "resource_index", qbins, "resource_index 十分位",
            binlabels=[f"D{i}" for i in range(1, 11)])
    ax2.set_title("沿资源等级", fontsize=8.5)

    for ax, tag in zip((ax1, ax2), "ab"):
        ax.text(-0.12, 1.05, tag, transform=ax.transAxes, fontsize=11,
                fontweight="bold", va="top", ha="right")
    fig.suptitle(f"{TECH_CN[tech]} CF 的纬度 / 资源剖面与 SSP 差异（2050）",
                 fontsize=10.5, fontweight="bold", y=0.97)
    fig.text(0.52, 0.005, "实线=各带中位数；带=25–75%。固定机队 deploy=SSP2-4.5。",
             ha="center", fontsize=6.2, color="0.45")
    p = f"{OUT}/fig_latprofile_{tech}.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", make(tech))
