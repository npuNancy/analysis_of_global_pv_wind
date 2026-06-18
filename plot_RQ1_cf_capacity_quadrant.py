#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 补充图 —— 各场站的容量因子 vs 装机容量。

回答的问题：风/光装机是否布局在资源好的地方？未来气候（SSP）又如何重新洗牌？

设计
----
  x：年容量因子（%）              -> 资源质量（气候驱动）
  y：装机容量（MW，对数轴）        -> 部署规模
  颜色：年发电量（GWh，对数）      -> 实际出力
  固定参考线把每个面板分成 4 个象限：
      右上  旗舰     （高 CF、高装机）
      右下  待开发   （高 CF、低装机）
      左上  低效     （低 CF、高装机）  <- 搁浅资产风险
      左下  边缘     （低 CF、低装机）

部署机队固定（deploy = SSP2-4.5），三个面板只变化气候情景，因此装机（y）逐面板
完全相同，点云的左移即纯气候信号。年份 = 2050。风电、光伏各一张。
（mock 数据无气候模型维度，按要求当作 NESM3 情形。）
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
FONT_PATH = "/data4/yanxiaokai/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(FONT_PATH)
FONT_NAME = fm.FontProperties(fname=FONT_PATH).get_name()

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [FONT_NAME, "Arial", "DejaVu Sans"],
    "axes.unicode_minus": False,    # 中文环境下用 ASCII 连字符，避免缺字
    "svg.fonttype": "none",     # SVG 中文字可编辑（仅在导出 SVG 时生效）
    "pdf.fonttype": 42,         # PDF 中文字可编辑（仅在导出 PDF 时生效）
    "font.size": 7.5,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "axes.linewidth": 0.8,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "xtick.major.size": 3, "ytick.major.size": 3,
    "legend.frameon": False,
    "figure.dpi": 120, "savefig.dpi": 350,
})

SSPS = ["ssp126", "ssp245", "ssp585"]
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
DEPLOY = "ssp245"     # 固定的部署机队
YEAR = 2050
CMAP = "viridis"

st = pd.read_csv(f"{DATA}/station_annual_generation.csv")


def save_fig(fig, name, vector=False):
    """默认只保存 PNG；vector=True 时额外导出可编辑的 PDF/SVG。"""
    fig.savefig(f"{OUT}/{name}.png", bbox_inches="tight")
    if vector:
        fig.savefig(f"{OUT}/{name}.pdf", bbox_inches="tight")
        fig.savefig(f"{OUT}/{name}.svg", bbox_inches="tight")


def figure_quadrant(tech):
    d = st[(st.technology == tech) & (st.deploy_ssp == DEPLOY)
           & (st.target_year == YEAR)].copy()
    d["cf"] = d.annual_capacity_factor * 100.0
    d["gen_gwh"] = d.annual_generation_mwh / 1e3              # MWh → GWh

    # 固定阈值 = 三个气候情景汇总后的中位数（各面板一致，便于对比）
    cf_line = d.cf.median()
    cap_line = d.capacity_mw.median()
    # 各面板共享的颜色范围与坐标范围
    gmin, gmax = d.gen_gwh.min(), d.gen_gwh.max()
    norm = LogNorm(vmin=gmin, vmax=gmax)
    cf_lim = (d.cf.min() * 0.92, d.cf.max() * 1.05)
    cap_lim = (d.capacity_mw.min() * 0.8, d.capacity_mw.max() * 1.25)

    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.05), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.075, right=0.88, bottom=0.16, top=0.82, wspace=0.08)

    quad_labels = {  # (x 比例, y 比例, ha, va, 象限名称)
        "tr": (0.97, 0.97, "right", "top",    "旗舰"),
        "br": (0.97, 0.03, "right", "bottom", "待开发"),
        "tl": (0.03, 0.97, "left",  "top",    "低效"),
        "bl": (0.03, 0.03, "left",  "bottom", "边缘"),
    }

    for ax, s in zip(axes, SSPS):
        sub = d[d.climate_ssp == s]
        ax.scatter(sub.cf, sub.capacity_mw, c=sub.gen_gwh, cmap=CMAP,
                   norm=norm, s=16, alpha=0.78, linewidths=0.25,
                   edgecolors="white")
        ax.set_yscale("log")
        ax.set_xlim(*cf_lim); ax.set_ylim(*cap_lim)
        ax.axvline(cf_line, color="0.25", lw=0.9, ls="--", zorder=0)
        ax.axhline(cap_line, color="0.25", lw=0.9, ls="--", zorder=0)
        ax.set_xlabel("容量因子 (%)")

        # 各象限的场站数 + 占本面板发电量的比例
        tot = sub.gen_gwh.sum()
        masks = {
            "tr": (sub.cf >= cf_line) & (sub.capacity_mw >= cap_line),
            "br": (sub.cf >= cf_line) & (sub.capacity_mw < cap_line),
            "tl": (sub.cf < cf_line) & (sub.capacity_mw >= cap_line),
            "bl": (sub.cf < cf_line) & (sub.capacity_mw < cap_line),
        }
        first = ax is axes[0]
        for q, m in masks.items():
            xf, yf, ha, va, role = quad_labels[q]
            n = int(m.sum()); share = sub.gen_gwh[m].sum() / tot * 100
            head = f"{role}\n" if first else ""        # 象限名称只在第一个面板标注
            ax.text(xf, yf, f"{head}n={n} · 发电{share:.0f}%",
                    transform=ax.transAxes, ha=ha, va=va, fontsize=6,
                    color="0.15", linespacing=1.25,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="0.7", lw=0.4, alpha=0.82))
        ax.set_title(f"{SSP_L[s]}   (平均 CF {sub.cf.mean():.1f}%)", fontsize=8.5)

    axes[0].set_ylabel("装机容量 (MW，对数)")

    # 共享色带
    cax = fig.add_axes([0.90, 0.16, 0.018, 0.66])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=CMAP), cax=cax)
    cb.set_label("年发电量 (GWh)", fontsize=8)
    cb.ax.tick_params(labelsize=6.5)

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"{tech_cn}：资源质量 vs 部署，及其气候位移",
                 fontsize=10.5, fontweight="bold", x=0.48, y=0.975)
    fig.text(0.48, 0.005,
             f"固定机队（deploy = SSP2-4.5），{YEAR} 年；虚线为机队中位数 CF "
             f"（{cf_line:.1f}%）与装机（{cap_line:.0f} MW），各面板一致。",
             ha="center", fontsize=6.2, color="0.45")

    save_fig(fig, f"fig_CFvsCAP_quadrant_{tech}")     # 默认仅 PNG
    plt.close(fig)
    return f"{OUT}/fig_CFvsCAP_quadrant_{tech}.png"


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_quadrant(tech))
