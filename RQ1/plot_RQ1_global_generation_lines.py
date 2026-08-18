#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：全球风/光发电量折线图（双子图合并版）。

每个子图即 plot_RQ1_generation.py 的图 a（全球发电量轨迹），
左图为光伏、右图为风电，各含三个 SSP 在三个目标年份的年发电量。

数据：data/real/RQ1_generation/{MODEL}/（由 prepare_RQ1_data.py 生成，按气候模式分目录）
输出：RQ1/outputs/real/{MODEL}/fig_GEN_global_lines.png
"""

import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
MODEL = "NESM3"  # 气候模式名；切换模式只需改此处，数据/输出走对应子目录
DATA = f"data/real/RQ1_generation/{MODEL}"
OUT = f"RQ1/outputs/real/{MODEL}"
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------- #
# 字体 & 样式（与 plot_RQ1_generation.py 一致）
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
TECHS = ["solar", "wind"]
TECH_CN = {"solar": "光伏", "wind": "风电"}


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
country = pd.read_csv(f"{DATA}/country_annual_generation.csv")


def gen_trajectory(tech):
    """自洽情景下全球年发电量（TWh）。"""
    d = country[country.technology == tech]
    g = (
        d.groupby(["climate_ssp", "target_year"])
        .agg(gen=("annual_generation_mwh", "sum"), cap=("capacity_mw", "sum"))
        .reset_index()
    )
    g["gen_twh"] = g.gen / 1e6
    return g


# =========================================================================== #
# 主绘图函数
# =========================================================================== #
def figure_global_lines():
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.1))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.86, bottom=0.16, wspace=0.28)

    for k, (ax, tech) in enumerate(zip(axes, TECHS)):
        g = gen_trajectory(tech)
        for s in SSPS:
            sub = g[g.climate_ssp == s].sort_values("target_year")
            if sub.empty:
                continue
            ax.plot(sub.target_year, sub.gen_twh, "-o", color=SSP_C[s], lw=1.8, ms=4, label=SSP_L[s])
        ax.set_xticks(YEARS)
        ax.set_xlim(YEARS[0] - 0.6, YEARS[-1] + 0.6)
        ax.set_xlabel("目标年份")
        ax.set_ylabel("年发电量 (TWh)")
        ax.set_title(f"全球{TECH_CN[tech]}发电量轨迹", fontsize=8.5)
        ax.grid(axis="y", lw=0.4, alpha=0.5)
        panel_tag(ax, chr(ord("a") + k))

    axes[0].legend(loc="best")

    fig.suptitle(f"未来气候对全球风/光发电量的影响（{MODEL}）", fontsize=11, fontweight="bold", y=0.97)
    fig.text(
        0.5,
        0.012,
        f"自洽情景（部署=气候）；{MODEL} 模型；发电量为全部场站年发电量之和。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    p = f"{OUT}/fig_GEN_global_lines.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="RQ1 全球风/光发电量折线图（双子图）")
    ap.add_argument("--model", default=MODEL, help="气候模式名；数据/输出/标题走对应子目录")
    args = ap.parse_args()
    if args.model != MODEL:  # --model 覆盖模块级 MODEL，并按新 DATA 重读
        MODEL = args.model
        DATA = f"data/real/RQ1_generation/{MODEL}"
        OUT = f"RQ1/outputs/real/{MODEL}"
        os.makedirs(OUT, exist_ok=True)
        country = pd.read_csv(f"{DATA}/country_annual_generation.csv")
    print("已保存:", figure_global_lines())
