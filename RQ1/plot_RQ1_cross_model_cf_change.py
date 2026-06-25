#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 不同 CMIP6 气候模式下，国家级容量因子（CF）的长期变化（小提琴图）。

科学问题
--------
在多个 CMIP6 气候模式下，世纪末（t1=2055-2060）相对近期（t2=2015-2020）的
国家级 CF 变化 ΔCF = mean_CF(t1) - mean_CF(t2)：分布、方向、跨模式一致性，
以及随 SSP 情景（ssp126/245/585）的变化。

数据
----
data/cfs/annual_mean_cf/<MODEL>/per_country_annual_cf_*.csv
  列：energy, model, scenario, region, year, mean_cf, ...
  「模式」由 annual_mean_cf/ 下的真实子目录名决定（软链目录被忽略）。
  当前默认绘制：NESM3、MIROC-ES2H。

输出
----
RQ1/outputs/real/cross_cmip6_model/
  violin_dCF_solar.png / violin_dCF_wind.png
  —— x=气候模式，每个模式内按 SSP 分组的标准小提琴图；
     小提琴体=各国 ΔCF 的核密度，内部粗线=四分位距(IQR)，细线=全距，白点=中位数。

用法
----
python RQ1/plot_RQ1_cross_model_cf_change.py
"""

import glob
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from scipy.stats import gaussian_kde

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
CF_BASE = ROOT / "data/cfs/annual_mean_cf"
OUT = ROOT / "RQ1/outputs/real/cross_cmip6_model"
OUT.mkdir(parents=True, exist_ok=True)

# 排除非 CMIP6-模式 的目录（如 ERA5Land 再分析参考）
EXCLUDE_DIRS = {"ERA5Land", "ERA5", "ERA5-Land"}

# 模式排序：列在此处的优先靠前，其余按字母序
MODEL_ORDER = ["NESM3", "MIROC-ES2H"]

# --------------------------------------------------------------------------- #
# 分析窗口与情景
# --------------------------------------------------------------------------- #
WIN_T2 = (2015, 2020)  # 近期基准
WIN_T1 = (2055, 2060)  # 世纪末

SSPS = ["ssp126", "ssp245", "ssp585"]
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
TECH_CN = {"solar": "光伏", "wind": "风电"}

# --------------------------------------------------------------------------- #
# 字体 & 样式（沿用项目既有出版级配置）
# --------------------------------------------------------------------------- #
from matplotlib import font_manager as fm

FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"
fm.fontManager.addfont(str(FONT_PATH))
FONT_NAME = fm.FontProperties(fname=str(FONT_PATH)).get_name()

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

ZERO_KW = dict(color="0.35", lw=0.8, ls="--", zorder=1)


def ssp_legend(ax, **kw):
    handles = [Patch(fc=SSP_C[s], ec="none", alpha=0.6, label=SSP_L[s]) for s in SSPS]
    ax.legend(handles=handles, **kw)


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def discover_models():
    """返回 annual_mean_cf/ 下的真实模式目录名（忽略软链占位与再分析目录）。"""
    models = []
    for p in sorted(CF_BASE.iterdir()):
        if p.is_symlink() or not p.is_dir() or p.name in EXCLUDE_DIRS:
            continue
        if not glob.glob(str(p / "per_country_annual_cf_*.csv")):
            continue
        models.append(p.name)
    rank = {m: i for i, m in enumerate(MODEL_ORDER)}
    return sorted(models, key=lambda m: (rank.get(m, len(rank)), m))


def load_one_model(model_dir):
    """读取单个模式目录下的逐年逐国家 CF；模式标签 = 目录名。"""
    files = sorted(glob.glob(str(CF_BASE / model_dir / "per_country_annual_cf_*.csv")))
    df = pd.read_csv(files[0], skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    for c in ("energy", "scenario", "region"):
        df[c] = df[c].astype(str).str.strip()
    df["year"] = df["year"].astype(int)
    df["mean_cf"] = df["mean_cf"].astype(float)
    df["model"] = model_dir
    return df[["model", "energy", "scenario", "region", "year", "mean_cf"]]


def window_mean(df, lo, hi):
    """各 (model,energy,scenario,region) 在 [lo,hi] 年窗口内的 CF 均值。"""
    m = (df["year"] >= lo) & (df["year"] <= hi)
    return (
        df[m]
        .groupby(["model", "energy", "scenario", "region"], sort=False)["mean_cf"]
        .mean()
        .rename("cf")
        .reset_index()
    )


def build_delta(df):
    """构造 ΔCF 表（百分点 p.p.）：delta = CF(t1) - CF(t2)。"""
    t2 = window_mean(df, *WIN_T2).rename(columns={"cf": "cf_t2"})
    t1 = window_mean(df, *WIN_T1).rename(columns={"cf": "cf_t1"})
    key = ["model", "energy", "scenario", "region"]
    d = t2.merge(t1, on=key, how="inner")
    d["delta_pp"] = (d["cf_t1"] - d["cf_t2"]) * 100.0  # 百分点
    return d


def footnote(fig):
    base = (
        f"ΔCF = CF({WIN_T1[0]}–{WIN_T1[1]}) − CF({WIN_T2[0]}–{WIN_T2[1]})，"
        f"各国年均 CF 之差（百分点）；小提琴内粗线=四分位距，细线=全距，白点=中位数。"
    )
    fig.text(0.5, 0.005, base, ha="center", va="bottom", fontsize=6.0, color="0.4")


# --------------------------------------------------------------------------- #
# 小提琴图（x=模式，按 SSP 分组）
# --------------------------------------------------------------------------- #
def fig_violin(delta, models):
    """自绘小提琴（gaussian_kde + fill_betweenx），在固定 grid 上作图，
    Y 轴范围 = grid 范围，从根本上杜绝小提琴尾部被裁切。"""
    paths = []
    n_ssp = len(SSPS)
    group_w = 0.82
    half_w = group_w / n_ssp * 0.9 / 2  # 单侧最大宽度

    for energy in ("solar", "wind"):
        sub = delta[delta["energy"] == energy]

        # 先以本能源全部 ΔCF 的范围（+8% 留白）确定 grid，再在其上估计密度
        vall = sub["delta_pp"].to_numpy()
        vall = vall[np.isfinite(vall)]
        lo, hi = vall.min(), vall.max()
        pad = (hi - lo) * 0.08
        grid = np.linspace(lo - pad, hi + pad, 300)

        fig, ax = plt.subplots(figsize=(1.8 + 1.7 * len(models), 3.8))

        for mi, model in enumerate(models):
            for si, ssp in enumerate(SSPS):
                vals = sub[(sub["model"] == model) & (sub["scenario"] == ssp)]["delta_pp"].to_numpy()
                vals = vals[np.isfinite(vals)]
                if vals.size < 2:
                    continue
                pos = mi + (si - (n_ssp - 1) / 2) * (group_w / n_ssp)

                # 小提琴体：在 grid 上估计 KDE，单独归一化到统一最大宽度
                if np.std(vals) > 0:
                    d = gaussian_kde(vals)(grid)
                    d = d / d.max() * half_w
                    ax.fill_betweenx(
                        grid, pos - d, pos + d, color=SSP_C[ssp], alpha=0.55, lw=0.8, edgecolor=SSP_C[ssp], zorder=2
                    )

                # 内部统计标注：IQR 粗线 + 须 + 中位数白点
                q1, med, q3 = np.percentile(vals, [25, 50, 75])
                ax.vlines(pos, q1, q3, color="0.15", lw=4.0, zorder=3)
                ax.vlines(pos, vals.min(), vals.max(), color="0.15", lw=0.9, zorder=3)
                ax.scatter(pos, med, s=14, color="white", edgecolor="0.15", lw=0.6, zorder=4)

        ax.axhline(0, **ZERO_KW)
        ax.set_ylim(grid[0], grid[-1])
        ax.set_xticks(range(len(models)))
        ax.set_xticklabels(models)
        ax.set_ylabel("ΔCF（百分点）")
        ax.set_title(f"{TECH_CN[energy]}：各模式国家级 ΔCF 分布（按 SSP 分组）", fontsize=9)
        ssp_legend(ax, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.13), handlelength=1.0, columnspacing=1.2)
        footnote(fig)
        p = OUT / f"violin_dCF_{energy}.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        paths.append(p)
    return paths


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    models = discover_models()
    if not models:
        raise SystemExit(f"未在 {CF_BASE} 下发现任何真实模式目录。")
    print("绘制模式:", models)

    df = pd.concat([load_one_model(m) for m in models], ignore_index=True)
    delta = build_delta(df)
    print(
        f"ΔCF 记录: {len(delta)} 行（{delta['region'].nunique()} 国 × "
        f"{len(models)} 模式 × {delta['scenario'].nunique()} 情景 × 2 能源）"
    )

    paths = fig_violin(delta, models)
    print("\n已保存 %d 张图至 %s :" % (len(paths), OUT))
    for p in paths:
        print("  ", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
