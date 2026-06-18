#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：未来气候如何改变风/光的场站发电量（出力）。

思路：发电量 = 装机容量 × 容量因子，同时受部署（装机）与气候（CF）影响。
用自洽情景（deploy_ssp == climate_ssp）画真实发电量轨迹，并额外做一个
“装机增长 vs 气候(ΔCF)”分解，把两类驱动力拆开。风电、光伏分别成图。

说明：mock 数据没有气候模型维度，按要求整体当作 NESM3 情形处理。

输出：Nature 风格多面板图，保存到 ./figures/RQ1_future_generation/
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
YEARS = [2030, 2040, 2050]
SSPS = ["ssp126", "ssp245", "ssp585"]


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    """在子图左上角标注面板字母（a/b/c/d）。"""
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
country = pd.read_csv(f"{DATA}/country_annual_generation.csv")
st_mon  = pd.read_csv(f"{DATA}/station_monthly_generation.csv")


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def gen_trajectory(tech):
    """自洽情景（deploy==climate）下，按 ssp、年份汇总全球发电量（TWh）。"""
    d = country[(country.technology == tech) & (country.deploy_ssp == country.climate_ssp)]
    g = d.groupby(["climate_ssp", "target_year"]).agg(
        gen=("annual_generation_mwh", "sum"),
        cap=("capacity_mw", "sum")).reset_index()
    g["gen_twh"] = g.gen / 1e6                                 # MWh → TWh
    return g


def monthly_cycle(tech, climate, year, deploy="ssp245"):
    """固定机队下，全部场站的逐月容量加权平均 CF（用于季节循环）。"""
    d = st_mon[(st_mon.technology == tech) & (st_mon.deploy_ssp == deploy)
               & (st_mon.climate_ssp == climate) & (st_mon.target_year == year)].copy()
    d["wcf"] = d.capacity_mw * d.monthly_capacity_factor
    g = d.groupby("month").apply(
        lambda x: x.wcf.sum() / x.capacity_mw.sum(), include_groups=False)
    return g.reindex(range(1, 13)).values


# =========================================================================== #
# 发电量图（风/光各一张）
# =========================================================================== #
def figure_gen(tech):
    g = gen_trajectory(tech)
    fig = plt.figure(figsize=(7.2, 6.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.15],
                          hspace=0.42, wspace=0.34,
                          left=0.1, right=0.97, top=0.9, bottom=0.1)

    # (a) 全球发电量时间轨迹 --------------------------------------------------
    axa = fig.add_subplot(gs[0, 0])
    for s in SSPS:
        sub = g[g.climate_ssp == s].sort_values("target_year")
        axa.plot(sub.target_year, sub.gen_twh, "-o", color=SSP_C[s], lw=1.8,
                 ms=4, label=SSP_L[s])
    axa.set_xticks(YEARS)
    axa.set_xlabel("目标年份")
    axa.set_ylabel("年发电量 (TWh)")
    axa.set_title("全球发电量轨迹", fontsize=8.5)
    axa.legend(loc="best")
    axa.grid(axis="y", lw=0.4, alpha=0.5)
    panel_tag(axa, "a")

    # (b) 季节循环位移：2030 vs 2050 ----------------------------------------
    axb = fig.add_subplot(gs[0, 1])
    months = np.arange(1, 13)
    axb.plot(months, monthly_cycle(tech, "ssp585", 2030) * 100, "-",
             color="0.55", lw=1.4, label="2030 基准")
    axb.plot(months, monthly_cycle(tech, "ssp126", 2050) * 100, "--o",
             color=SSP_C["ssp126"], lw=1.5, ms=3, label="2050 SSP1-2.6")
    axb.plot(months, monthly_cycle(tech, "ssp585", 2050) * 100, "-o",
             color=SSP_C["ssp585"], lw=1.8, ms=3.5, label="2050 SSP5-8.5")
    axb.set_xticks(months)
    axb.set_xticklabels(["1","2","3","4","5","6","7","8","9","10","11","12"],
                        fontsize=6.5)
    axb.set_xlabel("月份")
    axb.set_ylabel("容量加权 CF (%)")
    axb.set_title("季节循环：2030 vs 2050", fontsize=8.5)
    axb.legend(loc="best")
    panel_tag(axb, "b")

    # (c) Top 国家：按时段堆叠的发电量增长 2030 / 2040 / 2050 -----------------
    axc = fig.add_subplot(gs[1, 0])
    d = country[(country.technology == tech) & (country.deploy_ssp == "ssp245")
                & (country.climate_ssp == "ssp245")]
    p = d.pivot_table(index="country", columns="target_year",
                      values="annual_generation_mwh") / 1e6
    p = p.sort_values(2050, ascending=True).tail(14)           # 取 2050 最高的 14 国
    yp = np.arange(len(p))
    # 堆叠累积轨迹：2030 基底 + 各时段增量，使柱高等于 2050 总量
    base = p[2030].values
    inc40 = (p[2040] - p[2030]).clip(lower=0).values
    inc50 = (p[2050] - p[2040]).clip(lower=0).values
    shades = {"solar": ["#c77b06", "#f6b339", "#fdd98a"],
              "wind":  ["#1f5f8b", "#5fa3cf", "#bcd9ec"]}[tech]
    axc.barh(yp, base, color=shades[0], edgecolor="white", lw=0.4, label="2030")
    axc.barh(yp, inc40, left=base, color=shades[1], edgecolor="white", lw=0.4,
             label="2030→2040")
    axc.barh(yp, inc50, left=base + inc40, color=shades[2], edgecolor="white",
             lw=0.4, label="2040→2050")
    axc.set_yticks(yp); axc.set_yticklabels(p.index, fontsize=6)
    axc.set_xlabel("年发电量 (TWh)")
    axc.set_title("Top 国家：分时段增长（SSP2-4.5）", fontsize=8.5)
    axc.legend(loc="lower right", fontsize=6)
    panel_tag(axc, "c")

    # (d) 装机 vs 气候 的发电量增量分解 2030→2050 ----------------------------
    axd = fig.add_subplot(gs[1, 1])
    rows = []
    for s in SSPS:
        d = country[(country.technology == tech) & (country.deploy_ssp == s)
                    & (country.climate_ssp == s)]
        a = d.groupby("target_year").apply(
            lambda x: pd.Series({
                "cap": x.capacity_mw.sum(),
                "cf": (x.capacity_mw * x.capacity_weighted_cf).sum() / x.capacity_mw.sum()
            }), include_groups=False)
        c30, c50 = a.loc[2030, "cap"], a.loc[2050, "cap"]
        f30, f50 = a.loc[2030, "cf"], a.loc[2050, "cf"]
        H = 8760                                               # 年小时数
        cap_eff = (c50 - c30) * f30 * H / 1e6                  # 装机增长贡献
        cli_eff = c30 * (f50 - f30) * H / 1e6                  # 气候(ΔCF)贡献
        inter   = (c50 - c30) * (f50 - f30) * H / 1e6          # 交互项
        rows.append((s, cap_eff, cli_eff, inter))
    dec = pd.DataFrame(rows, columns=["ssp", "cap", "cli", "int"]).set_index("ssp")
    x = np.arange(len(SSPS))
    axd.bar(x, dec["cap"], color="#7a7a7a", label="装机增长")
    axd.bar(x, dec["cli"], bottom=dec["cap"], color=SSP_C["ssp585"],
            label="气候 (ΔCF)")
    axd.bar(x, dec["int"], bottom=dec["cap"] + dec["cli"], color="#cfa3a3",
            label="交互项")
    # 显式标注（较小的）气候驱动项
    for xi, s in zip(x, SSPS):
        tot = dec.loc[s, ["cap", "cli", "int"]].sum()
        axd.annotate(f"气候 {dec.loc[s,'cli']:+.1f}", (xi, tot),
                     textcoords="offset points", xytext=(0, 3),
                     ha="center", fontsize=5.8, color=SSP_C["ssp585"])
    axd.axhline(0, color="0.3", lw=0.7)
    axd.set_xticks(x); axd.set_xticklabels([SSP_L[s] for s in SSPS],
                                           rotation=12, fontsize=7)
    axd.set_ylabel("发电量增量 2030→2050 (TWh)")
    axd.set_title("装机 vs 气候 的增量分解", fontsize=8.5)
    axd.legend(loc="upper right")
    panel_tag(axd, "d")

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"未来气候对{tech_cn}发电量的影响",
                 fontsize=11, fontweight="bold", y=0.975)
    fig.text(0.5, 0.005,
             "自洽情景（部署 = 气候）；子图 d 将装机增长与气候驱动的 CF 变化分离。",
             ha="center", fontsize=6.2, color="0.4")
    p = f"{OUT}/fig_GEN_{tech}.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_gen(tech))
