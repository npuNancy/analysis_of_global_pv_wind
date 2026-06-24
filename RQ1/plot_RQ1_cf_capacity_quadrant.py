#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 补充图 —— 各场站的容量因子 vs 装机容量（四象限）。NESM3 真实数据版。

回答的问题：风/光装机是否布局在资源好的地方？三种 SSP 路径下格局如何变化？

设计
----
  三个面板各对应一个自洽情景（deploy_ssp == climate_ssp），目标年份 2050。
  x：年容量因子（%）            → 资源质量
  y：装机容量（MW，对数轴）      → 部署规模
  颜色：年发电量（GWh，对数）    → 实际出力

  参考线（四象限分界）固定为 SSP2-4.5 面板的中位 CF 和中位装机，
  便于比较 SSP1-2.6 / SSP5-8.5 相对于"中间路径"的偏移。

数据：data/real/RQ1_generation/（由 prepare_RQ1_data.py 生成）
输出：outputs/real/RQ1_generation/fig_CFvsCAP_quadrant_{solar,wind}.png
"""

import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
DATA = "data/real/RQ1_generation"
OUT = "outputs/real/RQ1_generation"
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
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 7.5,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "axes.linewidth": 0.8,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "legend.frameon": False,
        "figure.dpi": 120,
        "savefig.dpi": 350,
    }
)

SSPS = ["ssp126", "ssp245", "ssp585"]
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
YEAR = 2050
CMAP = "viridis"

st = pd.read_csv(f"{DATA}/station_annual_generation.csv")

# --------------------------------------------------------------------------- #
# 象限图
# --------------------------------------------------------------------------- #
QUAD_META = {  # (x 轴比例, y 轴比例, ha, va, 象限名称)
    "tr": (0.97, 0.97, "right", "top", "旗舰"),
    "br": (0.97, 0.03, "right", "bottom", "待开发"),
    "tl": (0.03, 0.97, "left", "top", "低效"),
    "bl": (0.03, 0.03, "left", "bottom", "边缘"),
}


def figure_quadrant(tech):
    # 取目标年份的全部自洽情景场站
    d = st[(st.technology == tech) & (st.target_year == YEAR) & (st.deploy_ssp == st.climate_ssp)].copy()
    d["cf"] = d.annual_capacity_factor * 100.0
    d["gen_gwh"] = d.annual_generation_mwh / 1e3

    # 过滤零值（CF=0 或 gen=0 的场站不纳入可视化）
    d = d[(d.cf > 0) & (d.gen_gwh > 0)].copy()

    if d.empty:
        print(f"  [{tech}] 无有效数据，跳过四象限图")
        return None

    # 参考线：取 SSP2-4.5 面板的中位数作为全局四象限分界
    ref = d[d.climate_ssp == "ssp245"]
    cf_line = ref.cf.median() if not ref.empty else d.cf.median()
    cap_line = ref.capacity_mw.median() if not ref.empty else d.capacity_mw.median()

    # 各面板共用坐标范围与颜色映射
    gmin = d.gen_gwh.min()
    gmax = d.gen_gwh.max()
    norm = LogNorm(vmin=max(gmin, 1e-3), vmax=gmax)
    cf_lim = (d.cf.min() * 0.92, d.cf.max() * 1.05)
    cap_lim = (d.capacity_mw.min() * 0.8, d.capacity_mw.max() * 1.25)

    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.05), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.075, right=0.88, bottom=0.16, top=0.82, wspace=0.08)

    for ax, s in zip(axes, SSPS):
        sub = d[d.climate_ssp == s]
        if sub.empty:
            ax.text(0.5, 0.5, "数据缺失", transform=ax.transAxes, ha="center", va="center", fontsize=8)
            ax.set_title(SSP_L[s], fontsize=8.5)
            continue

        sc = ax.scatter(
            sub.cf,
            sub.capacity_mw,
            c=sub.gen_gwh,
            cmap=CMAP,
            norm=norm,
            s=14,
            alpha=0.75,
            linewidths=0.2,
            edgecolors="white",
        )
        ax.set_yscale("log")
        ax.set_xlim(*cf_lim)
        ax.set_ylim(*cap_lim)
        ax.axvline(cf_line, color="0.25", lw=0.9, ls="--", zorder=0)
        ax.axhline(cap_line, color="0.25", lw=0.9, ls="--", zorder=0)
        ax.set_xlabel("容量因子 (%)")

        # 各象限注释（站数 + 发电占比）
        tot = sub.gen_gwh.sum()
        masks = {
            "tr": (sub.cf >= cf_line) & (sub.capacity_mw >= cap_line),
            "br": (sub.cf >= cf_line) & (sub.capacity_mw < cap_line),
            "tl": (sub.cf < cf_line) & (sub.capacity_mw >= cap_line),
            "bl": (sub.cf < cf_line) & (sub.capacity_mw < cap_line),
        }
        first = ax is axes[0]
        for q, m in masks.items():
            xf, yf, ha, va, role = QUAD_META[q]
            n = int(m.sum())
            share = sub.gen_gwh[m].sum() / tot * 100 if tot > 0 else 0
            head = f"{role}\n" if first else ""
            ax.text(
                xf,
                yf,
                f"{head}n={n} · 发电{share:.0f}%",
                transform=ax.transAxes,
                ha=ha,
                va=va,
                fontsize=5.8,
                color="0.15",
                linespacing=1.25,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="0.7", lw=0.4, alpha=0.82),
            )

        n_sta = len(sub)
        cf_avg = sub.cf.mean()
        ax.set_title(f"{SSP_L[s]}   n={n_sta}, 均值 CF {cf_avg:.1f}%", fontsize=8.5)

    axes[0].set_ylabel("装机容量 (MW，对数)")

    # 共享色带
    cax = fig.add_axes([0.90, 0.16, 0.018, 0.66])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=CMAP), cax=cax)
    cb.set_label("年发电量 (GWh)", fontsize=8)
    cb.ax.tick_params(labelsize=6.5)

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(
        f"{tech_cn}：资源质量 vs 部署规模（NESM3，{YEAR} 年）", fontsize=10.5, fontweight="bold", x=0.48, y=0.975
    )
    fig.text(
        0.48,
        0.005,
        f"自洽情景（部署=气候）；虚线为 SSP2-4.5 中位 CF（{cf_line:.1f}%）"
        f"与装机（{cap_line:.0f} MW），三面板共用；已过滤零出力场站。",
        ha="center",
        fontsize=6.2,
        color="0.45",
    )

    p = f"{OUT}/fig_CFvsCAP_quadrant_{tech}.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        result = figure_quadrant(tech)
        if result:
            print("已保存:", result)
