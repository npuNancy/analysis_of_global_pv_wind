#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 候选图 ⑤ —— 季节循环中的 SSP 分歧。

固定机队（deploy=ssp245）、2050 年，逐月容量加权 CF：
  (a) 12 个月的 3 条 SSP 曲线（+ 2030 基准灰线），看季节形态
  (b) 逐月 (SSP5-8.5 − SSP1-2.6) 差值条形，定位差异最大的月份/季节

风电、光伏各一张。
输出：outputs/RQ1_future_generation/tmp/fig_seasondiv_{solar,wind}.png
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
MONLAB = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]

mon = pd.read_csv(f"{DATA}/station_monthly_generation.csv")


def monthly_cf(tech, climate, year=2050, deploy="ssp245"):
    """逐月容量加权平均 CF（%）。"""
    d = mon[(mon.technology == tech) & (mon.deploy_ssp == deploy)
            & (mon.climate_ssp == climate) & (mon.target_year == year)].copy()
    d["wcf"] = d.capacity_mw * d.monthly_capacity_factor
    g = d.groupby("month").agg(wcf=("wcf", "sum"), cap=("capacity_mw", "sum"))
    return (g.wcf / g.cap * 100).reindex(range(1, 13)).values


def make(tech):
    months = np.arange(1, 13)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 3.4))
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.16, top=0.8, wspace=0.28)

    # (a) 季节曲线
    ax1.plot(months, monthly_cf(tech, "ssp126", 2030), "-", color="0.6", lw=1.3,
             label="2030 基准", zorder=1)
    for s in SSPS:
        ax1.plot(months, monthly_cf(tech, s, 2050), "-o", color=SSP_C[s], lw=1.7,
                 ms=3, label=f"2050 {SSP_L[s]}")
    ax1.set_xticks(months); ax1.set_xticklabels(MONLAB, fontsize=6.5)
    ax1.set_xlabel("月份"); ax1.set_ylabel("容量加权 CF (%)")
    ax1.set_title("季节循环（2050 三情景 + 2030 基准）", fontsize=8.5)
    ax1.legend(loc="best", fontsize=6)

    # (b) 逐月 SSP585 − SSP126 差值
    diff = monthly_cf(tech, "ssp585", 2050) - monthly_cf(tech, "ssp126", 2050)
    colors = [SSP_C["ssp585"] if v < 0 else SSP_C["ssp126"] for v in diff]
    ax2.bar(months, diff, color=colors, edgecolor="white", lw=0.4)
    ax2.axhline(0, color="0.3", lw=0.7)
    ax2.set_xticks(months); ax2.set_xticklabels(MONLAB, fontsize=6.5)
    ax2.set_xlabel("月份")
    ax2.set_ylabel("ΔCF：SSP5-8.5 − SSP1-2.6 (个百分点)")
    ax2.set_title("逐月气候分歧（红=SSP5-8.5 更低）", fontsize=8.5)

    for ax, tag in zip((ax1, ax2), "ab"):
        ax.text(-0.12, 1.05, tag, transform=ax.transAxes, fontsize=11,
                fontweight="bold", va="top", ha="right")
    fig.suptitle(f"{TECH_CN[tech]}：季节循环中的 SSP 分歧（2050）",
                 fontsize=10.5, fontweight="bold", y=0.97)
    p = f"{OUT}/fig_seasondiv_{tech}.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", make(tech))
