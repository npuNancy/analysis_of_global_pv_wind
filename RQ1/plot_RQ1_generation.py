#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1：未来气候如何改变风/光的场站发电量（出力）。NESM3 真实数据版。

数据：data/real/RQ1_generation/（由 prepare_RQ1_data.py 生成）
输出：outputs/real/RQ1_generation/fig_GEN_{solar,wind}.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
DATA = "data/real/RQ1_generation"
OUT  = "outputs/real/RQ1_generation"
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------- #
# 字体 & 样式
# --------------------------------------------------------------------------- #
from matplotlib import font_manager as fm
FONT_PATH = "data/tracked/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(FONT_PATH)
FONT_NAME = fm.FontProperties(fname=FONT_PATH).get_name()

mpl.rcParams.update({
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
})

SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
YEARS = [2030, 2040, 2050]
SSPS  = ["ssp126", "ssp245", "ssp585"]

SEG_LABELS = ["2030", "2030→2040", "2040→2050"]
SSP_SHADES = {
    "ssp126": ["#10254a", "#3a6ea5", "#9cc0e0"],
    "ssp245": ["#b9742a", "#e7a13b", "#f6d28a"],
    "ssp585": ["#6e0f0f", "#c0392b", "#e8a39c"],
}
YEAR_ALPHA = {2030: 0.85, 2040: 0.55, 2050: 0.30}


def panel_tag(ax, tag, dx=-0.08, dy=1.04):
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
    """自洽情景下全球年发电量（TWh）。"""
    d = country[country.technology == tech]
    g = d.groupby(["climate_ssp", "target_year"]).agg(
        gen=("annual_generation_mwh", "sum"),
        cap=("capacity_mw", "sum")).reset_index()
    g["gen_twh"] = g.gen / 1e6
    return g


def monthly_cycle(tech, climate, year):
    """自洽情景下全部场站的逐月容量加权平均 CF。"""
    d = st_mon[(st_mon.technology == tech)
               & (st_mon.deploy_ssp == climate)
               & (st_mon.climate_ssp == climate)
               & (st_mon.target_year == year)].copy()
    if d.empty:
        return np.full(12, np.nan)
    d["wcf"] = d.capacity_mw * d.monthly_capacity_factor
    g = d.groupby("month").apply(
        lambda x: x.wcf.sum() / x.capacity_mw.sum(), include_groups=False)
    return g.reindex(range(1, 13)).values


def gen_array_coherent(tech, ssp, year):
    """自洽情景下场站年发电量（GWh），排除零值（用于 KDE）。"""
    d = st_ann[(st_ann.technology == tech) & (st_ann.deploy_ssp == ssp)
               & (st_ann.climate_ssp == ssp) & (st_ann.target_year == year)]
    vals = d.annual_generation_mwh.values / 1e3
    return vals[vals > 0]


def gen_log_limits(tech):
    """统一 KDE 对数坐标范围（排除零值）。"""
    parts = [gen_array_coherent(tech, s, y) for s in SSPS for y in YEARS]
    parts = [v for v in parts if len(v) > 1]
    if not parts:
        return -1, 4
    vals = np.concatenate(parts)
    lo, hi = np.log10(vals.min()), np.log10(vals.max())
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def country_segments(tech, ntop=8):
    """Top 国家的分时段发电量（TWh），缺失 SSP 以 0 填充。"""
    d = country[country.technology == tech]
    ref = d[d.climate_ssp == "ssp245"].pivot_table(
        index="country", columns="target_year", values="annual_generation_mwh")
    if 2050 not in ref.columns:
        return [], {}
    order = (ref[2050] / 1e6).sort_values(ascending=False).head(ntop).index.tolist()[::-1]
    seg = {}
    for s in SSPS:
        sub = d[d.climate_ssp == s]
        if sub.empty:
            p = pd.DataFrame(index=order, columns=YEARS, dtype=float).fillna(0)
        else:
            p = sub.pivot_table(index="country", columns="target_year",
                                values="annual_generation_mwh").reindex(order) / 1e6
            for yr in YEARS:
                if yr not in p.columns:
                    p[yr] = 0.0
            p = p[YEARS].fillna(0)
        t = pd.DataFrame(index=order)
        t["base"]  = p[2030].values
        t["inc40"] = (p[2040] - p[2030]).clip(lower=0).values
        t["inc50"] = (p[2050] - p[2040]).clip(lower=0).values
        t["total"] = t[["base", "inc40", "inc50"]].sum(axis=1)
        seg[s] = t
    return order, seg


# =========================================================================== #
# 主绘图函数
# =========================================================================== #
def figure_gen(tech):
    g = gen_trajectory(tech)
    countries, seg = country_segments(tech, ntop=8)

    fig = plt.figure(figsize=(7.4, 9.2))
    gs  = fig.add_gridspec(3, 2, height_ratios=[0.95, 1.65, 0.85],
                           hspace=0.5, wspace=0.3,
                           left=0.1, right=0.96, top=0.92, bottom=0.07)

    # (a) 全球发电量时间轨迹 ---------------------------------------------------
    axa = fig.add_subplot(gs[0, 0])
    for s in SSPS:
        sub = g[g.climate_ssp == s].sort_values("target_year")
        if sub.empty:
            continue
        axa.plot(sub.target_year, sub.gen_twh, "-o", color=SSP_C[s],
                 lw=1.8, ms=4, label=SSP_L[s])
    axa.set_xticks(YEARS)
    axa.set_xlabel("目标年份")
    axa.set_ylabel("年发电量 (TWh)")
    axa.set_title("全球发电量轨迹", fontsize=8.5)
    axa.legend(loc="best")
    axa.grid(axis="y", lw=0.4, alpha=0.5)
    panel_tag(axa, "a")

    # (b) 季节循环：2030 vs 2050 -----------------------------------------------
    # 基准用 SSP2-4.5（覆盖最全），对比 SSP1-2.6 和 SSP5-8.5 的 2050
    axb = fig.add_subplot(gs[0, 1])
    months = np.arange(1, 13)
    base_cycle = monthly_cycle(tech, "ssp245", 2030)
    axb.plot(months, base_cycle * 100, "-", color="0.55",
             lw=1.4, label="2030 基准 (SSP2-4.5)")
    for s, ls, lbl in [("ssp126", "--o", "2050 SSP1-2.6"),
                        ("ssp585", "-o",  "2050 SSP5-8.5")]:
        cy = monthly_cycle(tech, s, 2050)
        if not np.all(np.isnan(cy)):
            axb.plot(months, cy * 100, ls, color=SSP_C[s],
                     lw=1.5 if s == "ssp126" else 1.8,
                     ms=3 if s == "ssp126" else 3.5, label=lbl)
    axb.set_xticks(months)
    axb.set_xticklabels(list("123456789") + ["10", "11", "12"], fontsize=6.5)
    axb.set_xlabel("月份")
    axb.set_ylabel("容量加权 CF (%)")
    axb.set_title("季节循环：2030 vs 2050", fontsize=8.5)
    axb.legend(loc="best", fontsize=6)
    panel_tag(axb, "b")

    # (c) Top 国家分情景分时段发电量（绝对值）-----------------------------------
    axc = fig.add_subplot(gs[1, 0])
    if countries:
        w, bar_h = 0.27, 0.24
        for ci, c_ in enumerate(countries):
            for si, s in enumerate(SSPS):
                y = ci + (si - 1) * w
                r = seg[s].loc[c_]
                cols = SSP_SHADES[s]
                axc.barh(y, r.base,  height=bar_h, color=cols[0],
                         edgecolor="white", lw=0.4)
                axc.barh(y, r.inc40, height=bar_h, left=r.base,
                         color=cols[1], edgecolor="white", lw=0.4)
                axc.barh(y, r.inc50, height=bar_h, left=r.base + r.inc40,
                         color=cols[2], edgecolor="white", lw=0.4)
        axc.set_yticks(range(len(countries)))
        axc.set_yticklabels(countries, fontsize=6)
        axc.set_ylim(-0.6, len(countries) - 0.4)
    axc.set_xlabel("年发电量 (TWh)")
    axc.set_title("分情景 · 分时段发电量（绝对值）", fontsize=8.5)
    panel_tag(axc, "c")

    # (d) 相对值（SSP1-2.6 归一为 100%）-----------------------------------------
    axd = fig.add_subplot(gs[1, 1])
    if countries:
        for ci, c_ in enumerate(countries):
            t126 = seg["ssp126"].loc[c_, "total"]
            if t126 <= 0:
                continue
            sc = 100.0 / t126
            for si, s in enumerate(SSPS):
                y = ci + (si - 1) * w
                r = seg[s].loc[c_]
                cols = SSP_SHADES[s]
                b, i40, i50 = r.base * sc, r.inc40 * sc, r.inc50 * sc
                axd.barh(y, b,   height=bar_h, color=cols[0],
                         edgecolor="white", lw=0.4)
                axd.barh(y, i40, height=bar_h, left=b,
                         color=cols[1], edgecolor="white", lw=0.4)
                axd.barh(y, i50, height=bar_h, left=b + i40,
                         color=cols[2], edgecolor="white", lw=0.4)
                axd.text(b + i40 + i50, y, f" {r.total:.0f}",
                         va="center", ha="left", fontsize=4.6, color="0.2")
        axd.axvline(100, color="0.45", lw=0.8, ls="--", zorder=0)
        axd.set_yticks(range(len(countries)))
        axd.set_yticklabels([])
        axd.set_ylim(-0.6, len(countries) - 0.4)
        axd.set_xlim(0, axd.get_xlim()[1] * 1.18)
    axd.set_xlabel("相对 SSP1-2.6 (%)")
    axd.set_title("相对值（柱顶标 2050 TWh）", fontsize=8.5)
    panel_tag(axd, "d")

    # (e) 场站发电量分布：嵌套小提琴（对数轴）------------------------------------
    axe = fig.add_subplot(gs[2, 0])
    axe.set_yscale("log")
    loglo, loghi = gen_log_limits(tech)
    grid_log = np.linspace(loglo, loghi, 300)
    ygrid    = 10 ** grid_log
    base_w   = 0.42
    for j, s in enumerate(SSPS):
        arrs = {y: gen_array_coherent(tech, s, y) for y in YEARS}
        if any(len(v) < 3 for v in arrs.values()):
            continue
        dens  = {y: gaussian_kde(np.log10(arrs[y]))(grid_log) * len(arrs[y])
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

    # 共享图例（c / d 用）：3×3 色块矩阵 ----------------------------------------
    axl = fig.add_subplot(gs[2, 1])
    axl.axis("off")
    axl.set_xlim(0, 1)
    axl.set_ylim(0, 1)
    axl.text(0.04, 0.95, "子图 c / d 图例", fontsize=7.5,
             fontweight="bold", va="top")
    x0, y_top = 0.42, 0.74
    cw, ch    = 0.16, 0.17
    for j, lab in enumerate(SEG_LABELS):
        axl.text(x0 + (j + 0.5) * cw, y_top + 0.04, lab,
                 ha="center", va="bottom", fontsize=5.6, rotation=22)
    for i, s in enumerate(SSPS):
        yc = y_top - (i + 1) * ch
        axl.text(x0 - 0.03, yc + ch * 0.5, SSP_L[s],
                 ha="right", va="center", fontsize=6.8)
        for j in range(3):
            axl.add_patch(Rectangle((x0 + j * cw, yc), cw, ch,
                                    facecolor=SSP_SHADES[s][j],
                                    edgecolor="white", lw=0.6))
    axl.text(0.04, y_top - 3 * ch - 0.04,
             "色系区分情景，系内由深到浅对应时段",
             fontsize=5.8, color="0.4", va="top")

    tech_cn = {"solar": "光伏", "wind": "风电"}[tech]
    fig.suptitle(f"未来气候对{tech_cn}发电量的影响（NESM3）",
                 fontsize=11, fontweight="bold", y=0.975)
    fig.text(0.5, 0.012,
             "自洽情景（部署=气候）；NESM3 模型；子图 b 基准为 SSP2-4.5 2030；"
             "子图 c/d 每国按 SSP 分三柱、按时段堆叠，d 为相对 SSP1-2.6 占比。",
             ha="center", fontsize=6.2, color="0.4")

    p = f"{OUT}/fig_GEN_{tech}.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


if __name__ == "__main__":
    for tech in ["solar", "wind"]:
        print("已保存:", figure_gen(tech))
