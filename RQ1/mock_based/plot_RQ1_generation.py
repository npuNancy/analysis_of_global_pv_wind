#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：未来气候如何改变风/光的场站发电量（出力）。

思路：发电量 = 装机容量 × 容量因子，同时受部署（装机）与气候（CF）影响。
全部采用自洽情景（deploy_ssp == climate_ssp）。风电、光伏分别成图。

说明：mock 数据没有气候模型维度，按要求整体当作 NESM3 情形处理。

输出：Nature 风格多面板图，保存到 ./outputs/RQ1_future_generation/
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
DATA = "data_mock/mock_RQ_data/RQ1_future_generation"
OUT  = "RQ1/outputs/mock"
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------- #
# Nature 风格设置
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 中文字体（思源黑体）
# --------------------------------------------------------------------------- #
from matplotlib import font_manager as fm
FONT_PATH = "data/SourceHanSansSC-Normal.otf"
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

# 分时段标签（柱子的堆叠层）。每个 SSP 用一个色系，系内由深到浅对应三个时段
SEG_LABELS = ["2030", "2030→2040", "2040→2050"]
SSP_SHADES = {
    "ssp126": ["#10254a", "#3a6ea5", "#9cc0e0"],   # 蓝系（深 → 浅）
    "ssp245": ["#b9742a", "#e7a13b", "#f6d28a"],   # 橙系
    "ssp585": ["#6e0f0f", "#c0392b", "#e8a39c"],   # 红系
}
YEAR_ALPHA = {2030: 0.85, 2040: 0.55, 2050: 0.30}


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
    """在子图左上角标注面板字母（a/b/c/d）。"""
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top", ha="right")


# --------------------------------------------------------------------------- #
# 读取数据
# --------------------------------------------------------------------------- #
country = pd.read_csv(f"{DATA}/country_annual_generation.csv")
st_mon  = pd.read_csv(f"{DATA}/station_monthly_generation.csv")
st_ann  = pd.read_csv(f"{DATA}/station_annual_generation.csv")


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


def gen_array_coherent(tech, ssp, year):
    """自洽情景（deploy==climate）下，场站年发电量（GWh）。"""
    d = st_ann[(st_ann.technology == tech) & (st_ann.deploy_ssp == ssp)
               & (st_ann.climate_ssp == ssp) & (st_ann.target_year == year)]
    return d.annual_generation_mwh.values / 1e3


def gen_log_limits(tech):
    """该技术全部 (情景×年份) 发电量的 log10 范围，用于统一对数网格与坐标。"""
    vals = np.concatenate([gen_array_coherent(tech, s, y) for s in SSPS for y in YEARS])
    lo, hi = np.log10(vals.min()), np.log10(vals.max())
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def country_segments(tech, ntop=8):
    """Top 国家在 3 个自洽情景下的分时段发电量 (TWh)。

    返回 (countries, seg)：
      countries —— 国家列表，按 SSP2-4.5 下 2050 发电量升序（最大者在最上）；
      seg       —— dict[ssp] -> DataFrame(index=country, cols=base/inc40/inc50/total)。
    """
    d = country[(country.technology == tech) & (country.deploy_ssp == country.climate_ssp)]
    # 取 SSP2-4.5 下 2050 发电量最高的 ntop 国，升序排列便于横向柱图自下而上
    ref = d[d.climate_ssp == "ssp245"].pivot_table(
        index="country", columns="target_year", values="annual_generation_mwh")
    order = (ref[2050] / 1e6).sort_values(ascending=False).head(ntop).index.tolist()[::-1]
    seg = {}
    for s in SSPS:
        p = d[d.climate_ssp == s].pivot_table(
            index="country", columns="target_year",
            values="annual_generation_mwh").reindex(order) / 1e6
        t = pd.DataFrame(index=order)
        t["base"]  = p[2030].values                              # 2030 基底
        t["inc40"] = (p[2040] - p[2030]).clip(lower=0).values    # 2030→2040 增量
        t["inc50"] = (p[2050] - p[2040]).clip(lower=0).values    # 2040→2050 增量
        t["total"] = t[["base", "inc40", "inc50"]].sum(axis=1)   # = 2050 总量
        seg[s] = t
    return order, seg


# =========================================================================== #
# 发电量图（风/光各一张）
# =========================================================================== #
def figure_gen(tech):
    g = gen_trajectory(tech)
    countries, seg = country_segments(tech, ntop=8)

    fig = plt.figure(figsize=(7.4, 9.2))
    gs = fig.add_gridspec(3, 2, height_ratios=[0.95, 1.65, 0.85],
                          hspace=0.5, wspace=0.3,
                          left=0.1, right=0.96, top=0.92, bottom=0.07)

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
    axb.plot(months, monthly_cycle(tech, "ssp585", 2030, deploy="ssp585") * 100, "-",
             color="0.55", lw=1.4, label="2030 基准")
    axb.plot(months, monthly_cycle(tech, "ssp126", 2050, deploy="ssp126") * 100, "--o",
             color=SSP_C["ssp126"], lw=1.5, ms=3, label="2050 SSP1-2.6")
    axb.plot(months, monthly_cycle(tech, "ssp585", 2050, deploy="ssp585") * 100, "-o",
             color=SSP_C["ssp585"], lw=1.8, ms=3.5, label="2050 SSP5-8.5")
    axb.set_xticks(months)
    axb.set_xticklabels(["1","2","3","4","5","6","7","8","9","10","11","12"],
                        fontsize=6.5)
    axb.set_xlabel("月份")
    axb.set_ylabel("容量加权 CF (%)")
    axb.set_title("季节循环：2030 vs 2050", fontsize=8.5)
    axb.legend(loc="best")
    panel_tag(axb, "b")

    # (c) Top 国家：分情景 × 分时段发电量（绝对值，每国 3 柱）-----------------
    axc = fig.add_subplot(gs[1, 0])
    w, bar_h = 0.27, 0.24                                      # 组内 SSP 偏移 / 柱高
    for ci, c_ in enumerate(countries):
        for si, s in enumerate(SSPS):
            y = ci + (si - 1) * w                              # 三柱：ssp126/245/585
            r = seg[s].loc[c_]
            cols = SSP_SHADES[s]                               # 该情景的色系（深→浅）
            axc.barh(y, r.base, height=bar_h, color=cols[0], edgecolor="white", lw=0.4)
            axc.barh(y, r.inc40, height=bar_h, left=r.base, color=cols[1],
                     edgecolor="white", lw=0.4)
            axc.barh(y, r.inc50, height=bar_h, left=r.base + r.inc40, color=cols[2],
                     edgecolor="white", lw=0.4)
    axc.set_yticks(range(len(countries)))
    axc.set_yticklabels(countries, fontsize=6)
    axc.set_ylim(-0.6, len(countries) - 0.4)
    axc.set_xlabel("年发电量 (TWh)")
    axc.set_title("分情景 · 分时段发电量（绝对值）", fontsize=8.5)
    panel_tag(axc, "c")

    # (d) 相对值：每国 SSP1-2.6 固定为 100%，柱顶标注 2050 发电量 --------------
    axd = fig.add_subplot(gs[1, 1])
    for ci, c_ in enumerate(countries):
        t126 = seg["ssp126"].loc[c_, "total"]
        if t126 <= 0:
            continue
        sc = 100.0 / t126                                      # 归一到 SSP1-2.6 = 100%
        for si, s in enumerate(SSPS):
            y = ci + (si - 1) * w
            r = seg[s].loc[c_]
            cols = SSP_SHADES[s]                               # 该情景的色系（深→浅）
            b, i40, i50 = r.base * sc, r.inc40 * sc, r.inc50 * sc
            axd.barh(y, b, height=bar_h, color=cols[0], edgecolor="white", lw=0.4)
            axd.barh(y, i40, height=bar_h, left=b, color=cols[1], edgecolor="white", lw=0.4)
            axd.barh(y, i50, height=bar_h, left=b + i40, color=cols[2],
                     edgecolor="white", lw=0.4)
            axd.text(b + i40 + i50, y, f" {r.total:.0f}", va="center", ha="left",
                     fontsize=4.6, color="0.2")                # 柱顶标 2050 TWh
    axd.axvline(100, color="0.45", lw=0.8, ls="--", zorder=0)
    axd.set_yticks(range(len(countries)))
    axd.set_yticklabels([])
    axd.set_ylim(-0.6, len(countries) - 0.4)
    axd.set_xlabel("相对 SSP1-2.6 (%)")
    axd.set_title("相对值（柱顶标 2050 TWh）", fontsize=8.5)
    axd.set_xlim(0, axd.get_xlim()[1] * 1.18)                  # 右侧留白给数值
    panel_tag(axd, "d")

    # (e) 场站发电量分布：嵌套小提琴（2030/2040/2050，对数轴）-----------------
    axe = fig.add_subplot(gs[2, 0])
    axe.set_yscale("log")
    loglo, loghi = gen_log_limits(tech)
    grid_log = np.linspace(loglo, loghi, 240)
    ygrid = 10 ** grid_log
    base_w = 0.42
    for j, s in enumerate(SSPS):
        arrs = {y: gen_array_coherent(tech, s, y) for y in YEARS}
        dens = {y: gaussian_kde(np.log10(arrs[y]))(grid_log) * len(arrs[y])
                for y in YEARS}
        scale = base_w / max(d.max() for d in dens.values())
        for y in [2050, 2040, 2030]:
            d = dens[y] * scale
            axe.fill_betweenx(ygrid, j - d, j + d, color=SSP_C[s],
                              alpha=YEAR_ALPHA[y], lw=0.4, edgecolor="white",
                              zorder=2 + YEARS.index(y))
            axe.plot(j, np.median(arrs[y]), "o", ms=3, mfc="white", mec="k",
                     mew=0.8, zorder=10)
    axe.set_xticks(range(len(SSPS)))
    axe.set_xticklabels([SSP_L[s] for s in SSPS], rotation=12, fontsize=7)
    axe.set_ylabel("场站年发电量 (GWh，对数)")
    axe.set_ylim(10 ** loglo, 10 ** loghi)
    axe.set_title("场站发电量分布（宽度∝场站数）", fontsize=8.5)
    handles_vio = [Patch(fc="0.4", alpha=YEAR_ALPHA[y], label=str(y)) for y in YEARS]
    handles_vio.append(Line2D([], [], marker="o", ls="", mfc="white", mec="k",
                              mew=0.8, ms=4, label="中位数"))
    axe.legend(handles=handles_vio, loc="upper right", fontsize=6)
    panel_tag(axe, "e")

    # 共享图例（子图 c / d）：3×3 色块矩阵 —— 行=情景色系，列=发电量时段 -------
    from matplotlib.patches import Rectangle
    axl = fig.add_subplot(gs[2, 1]); axl.axis("off")
    axl.set_xlim(0, 1); axl.set_ylim(0, 1)
    axl.text(0.04, 0.95, "子图 c / d 图例", fontsize=7.5, fontweight="bold",
             va="top")
    x0, y_top = 0.42, 0.74                                     # 矩阵左上角
    cw, ch = 0.16, 0.17                                        # 单元格宽 / 高
    # 列标题：发电量时段
    for j, lab in enumerate(SEG_LABELS):
        axl.text(x0 + (j + 0.5) * cw, y_top + 0.04, lab, ha="center", va="bottom",
                 fontsize=5.6, rotation=22)
    # 行标题（情景）+ 3×3 色块
    for i, s in enumerate(SSPS):
        yc = y_top - (i + 1) * ch
        axl.text(x0 - 0.03, yc + ch * 0.5, SSP_L[s], ha="right", va="center",
                 fontsize=6.8)
        for j in range(3):
            axl.add_patch(Rectangle((x0 + j * cw, yc), cw, ch,
                                    facecolor=SSP_SHADES[s][j], edgecolor="white",
                                    lw=0.6))
    axl.text(0.04, y_top - 3 * ch - 0.04,
             "色系区分情景，系内由深到浅对应时段",
             fontsize=5.8, color="0.4", va="top")

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"未来气候对{tech_cn}发电量的影响",
                 fontsize=11, fontweight="bold", y=0.975)
    fig.text(0.5, 0.012,
             "自洽情景（部署 = 气候）；子图 c/d 每国按 SSP 分三柱、按时段堆叠，"
             "d 为相对 SSP1-2.6 的占比；子图 e 为场站发电量分布（对数轴，宽度∝场站数）。",
             ha="center", fontsize=6.2, color="0.4")
    p = f"{OUT}/fig_GEN_{tech}.png"
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_gen(tech))
