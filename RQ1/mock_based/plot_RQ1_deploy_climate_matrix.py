#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 候选图 ② —— 部署 × 气候 3×3 矩阵（解耦两个 SSP 维度）。

用满 deploy_ssp × climate_ssp 的 9 组交叉（2050 年）：
  左图：全球年发电量（TWh）—— 主要沿“行（部署）”变化 → 出力由装机主导
  右图：全球容量加权 CF（%）—— 主要沿“列（气候）”变化 → 资源质量由气候主导
颜色 = 相对各自矩阵均值的偏差（%），用以凸显“沿行还是沿列变化”；格内标注原值。
对角线（部署=气候）为自洽情景，用方框标出。

风电、光伏各一张。
输出：outputs/RQ1_future_generation/tmp/fig_matrix_{solar,wind}.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Rectangle
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
    "figure.dpi": 120, "savefig.dpi": 350, "pdf.fonttype": 42,
})

SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
SSPS = ["ssp126", "ssp245", "ssp585"]
TECH_CN = {"solar": "光伏", "wind": "风电"}

country = pd.read_csv(f"{DATA}/country_annual_generation.csv")


def matrix_gen(tech):
    """2050 全球年发电量矩阵（TWh），行=deploy，列=climate。"""
    d = country[(country.technology == tech) & (country.target_year == 2050)]
    m = d.groupby(["deploy_ssp", "climate_ssp"]).annual_generation_mwh.sum().unstack()
    return (m / 1e6).reindex(index=SSPS, columns=SSPS)


def matrix_cf(tech):
    """2050 全球容量加权 CF 矩阵（%），行=deploy，列=climate。"""
    d = country[(country.technology == tech) & (country.target_year == 2050)].copy()
    d["wcf"] = d.capacity_mw * d.capacity_weighted_cf
    g = d.groupby(["deploy_ssp", "climate_ssp"]).agg(
        wcf=("wcf", "sum"), cap=("capacity_mw", "sum"))
    g["cf"] = g.wcf / g.cap * 100
    return g["cf"].unstack().reindex(index=SSPS, columns=SSPS)


def draw_matrix(ax, M, title, fmt, unit):
    dev = (M.values - M.values.mean()) / M.values.mean() * 100   # 相对均值偏差(%)
    vmax = max(np.abs(dev).max(), 1e-6)
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    im = ax.imshow(dev, cmap="RdBu_r", norm=norm, aspect="equal")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, format(M.values[i, j], fmt), ha="center", va="center",
                    fontsize=8, color="0.1")
            if i == j:                                           # 自洽情景描框
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                       ec="k", lw=1.6))
    ax.set_xticks(range(3)); ax.set_xticklabels([SSP_L[s] for s in SSPS],
                                                rotation=18, fontsize=7)
    ax.set_yticks(range(3)); ax.set_yticklabels([SSP_L[s] for s in SSPS],
                                                fontsize=7)
    ax.set_xlabel("气候情景 climate_ssp")
    ax.set_ylabel("部署情景 deploy_ssp")
    ax.set_title(title, fontsize=8.5)
    cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("相对均值偏差 (%)", fontsize=6.5); cb.ax.tick_params(labelsize=6)
    ax.text(1, -0.9, unit, ha="center", fontsize=6.5, color="0.45")


def make(tech):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 3.7))
    fig.subplots_adjust(left=0.1, right=0.97, bottom=0.16, top=0.8, wspace=0.55)
    draw_matrix(ax1, matrix_gen(tech), "年发电量（沿行/部署变化大）", ".0f", "单位：TWh")
    draw_matrix(ax2, matrix_cf(tech), "容量因子（沿列/气候变化大）", ".1f", "单位：%")
    for ax, tag in zip((ax1, ax2), "ab"):
        ax.text(-0.18, 1.06, tag, transform=ax.transAxes, fontsize=11,
                fontweight="bold", va="top", ha="right")
    fig.suptitle(f"{TECH_CN[tech]}：部署×气候解耦（2050，黑框=自洽情景）",
                 fontsize=10.5, fontweight="bold", y=0.96)
    p = f"{OUT}/fig_matrix_{tech}.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", make(tech))
