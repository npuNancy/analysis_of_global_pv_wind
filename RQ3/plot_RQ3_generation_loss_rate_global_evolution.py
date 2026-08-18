#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ3 图 2：极端天气造成的全球风光出力损失率演化（年代均值折线图）。

损失率定义：损失/发电量之比，即

    损失率 = sum(net_generation_loss_mwh) / sum(normal_all_generation_mwh)

其中 net_generation_loss_mwh 为极端事件（event = all 并集）暴露期间
"应发电量 - 实际出力"的净差，normal_all_generation_mwh 为全年应发电量
（CF-normal × 容量 × 全年时间步）。

聚合口径（与 plot_RQ3_generation_loss_global_evolution.py 一致）：
先在 region 级逐年累计分子分母、再相除得到逐年全球损失率，最后按
center-k（K=2）年代窗口取均值：

    2030s -> mean(2033-2037)，2040s -> mean(2043-2047)，2050s -> mean(2053-2057)；
    误差条 = 窗口内年际最小-最大值。

该口径剔除装机规模与国家覆盖差异，是情景间公平比较的主要指标；
注意不能先算各 region 的比例再对比例求平均。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_RQ3_generation_loss_global_evolution import (
    configure_style,
    panel_tag,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = (
    ROOT
    / "ref_code/calculate_wind_solar_generation_loss/outputs/generation_loss"
    / "{model}"
    / "aggregate/generation_loss_region.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "RQ3/outputs"

DEFAULT_MODEL = "CANESM5"
DEFAULT_SSPS = ["ssp126", "ssp245", "ssp585"]
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
DECADE_ORDER = [2030, 2040, 2050]
DECADE_LABEL = {2030: "2030s", 2040: "2040s", 2050: "2050s"}
DECADE_WINDOWS = {2030: "2033-2037", 2040: "2043-2047", 2050: "2053-2057"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制全球风光出力损失率年代均值演化折线图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--techs",
        nargs="+",
        default=["wind", "solar"],
        help="需要绘制的技术。wind 在左，solar 在右。",
    )
    parser.add_argument(
        "--event",
        default="all",
        help="极端事件口径，all 为全部支持事件的并集；也可选单一事件如 low_resource。",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help="generation_loss aggregate 的 region 级年度长表 CSV。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认：RQ3/outputs/{MODEL}。",
    )
    return parser.parse_args()


def load_loss_rate_summary(args: argparse.Namespace) -> pd.DataFrame:
    """逐年累计分子分母后相除，再按年代窗口聚合。"""
    csv_path = args.input_csv or Path(str(DEFAULT_INPUT_CSV).format(model=args.model))
    if not csv_path.exists():
        raise SystemExit(f"未找到输入 CSV：{csv_path}")
    df = pd.read_csv(csv_path)
    d = df[
        (df["model"] == args.model)
        & (df["event"] == args.event)
        & (df["scenario"].isin(args.ssps))
        & (df["tech"].isin(args.techs))
    ].copy()
    if d.empty:
        raise SystemExit(f"输入 CSV 中没有匹配 model={args.model}、event={args.event} 的行。")

    annual = (
        d.groupby(["scenario", "tech", "snapshot_year", "analysis_year"], as_index=False)
        .agg(
            loss_mwh=("net_generation_loss_mwh", "sum"),
            normal_mwh=("normal_all_generation_mwh", "sum"),
            n_regions=("region", "nunique"),
        )
    )
    annual["loss_rate_pct"] = np.where(
        annual["normal_mwh"] > 0,
        annual["loss_mwh"] / annual["normal_mwh"] * 100.0,
        np.nan,
    )

    decade = (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            loss_rate_pct_mean=("loss_rate_pct", "mean"),
            loss_rate_pct_min=("loss_rate_pct", "min"),
            loss_rate_pct_max=("loss_rate_pct", "max"),
            n_years=("analysis_year", "nunique"),
            n_regions_mean=("n_regions", "mean"),
        )
    )
    decade["decade"] = decade["snapshot_year"].map(DECADE_LABEL)
    return decade


def plot_loss_rate(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    techs = [t for t in ["wind", "solar"] if t in args.techs]
    fig, axes = plt.subplots(1, len(techs), figsize=(7.4, 3.2))
    if len(techs) == 1:
        axes = [axes]
    fig.subplots_adjust(left=0.09, right=0.98, top=0.82, bottom=0.24, wspace=0.28)

    x = np.arange(len(DECADE_ORDER))
    for ax, tech, tag in zip(axes, techs, ["a", "b"]):
        dtech = summary[summary["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["scenario"] == ssp].set_index("snapshot_year")
            if sub.empty:
                continue
            sub = sub.reindex(DECADE_ORDER)
            mean = sub["loss_rate_pct_mean"].to_numpy(dtype=float)
            lo = sub["loss_rate_pct_min"].to_numpy(dtype=float)
            hi = sub["loss_rate_pct_max"].to_numpy(dtype=float)
            color = SSP_C.get(ssp, "0.3")
            ax.errorbar(
                x,
                mean,
                yerr=[mean - lo, hi - mean],
                fmt="-o",
                color=color,
                lw=1.8,
                ms=4,
                capsize=2.5,
                elinewidth=0.8,
                markeredgecolor=color,
                markerfacecolor="white",
                markeredgewidth=1.0,
                label=SSP_L.get(ssp, ssp),
            )
        ax.set_xticks(x)
        ax.set_xticklabels([DECADE_LABEL[d] for d in DECADE_ORDER])
        ax.set_title(f"{TECH_LABEL[tech]}：净出力损失率", fontsize=9)
        ax.set_xlabel("年代")
        ax.set_ylabel("损失率（%）")
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        ax.margins(x=0.12)
        panel_tag(ax, tag)

    handles = [
        Line2D([0], [0], color=SSP_C.get(s, "0.3"), lw=1.8, marker="o", ms=4,
               markerfacecolor="white", label=SSP_L.get(s, s))
        for s in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(f"全球极端天气风光出力损失率演化（{args.model}）", fontsize=11, fontweight="bold", y=1.02)
    windows = "、".join(f"{DECADE_LABEL[d]}:{DECADE_WINDOWS[d]}" for d in DECADE_ORDER)
    note_lines = [
        "损失率 = 净出力损失 / 全年应发电量（region 级逐年累计分子分母后相除）；"
        f"每个年代点为 center-k（K=2）窗口年均值（{windows}），误差条为窗口内年际最小-最大值。",
        "该指标剔除装机规模与国家覆盖差异；比例不可跨 region 直接平均，详见汇总 CSV。",
    ]
    for i, line in enumerate(note_lines):
        fig.text(0.5, 0.055 - 0.045 * i, line, ha="center", fontsize=6.2, color="0.4")

    out_base = out_dir / "fig_RQ3_generation_loss_rate_global_evolution"
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    summary = load_loss_rate_summary(args)
    csv_path = out_dir / "csv/RQ3_generation_loss_rate_global_evolution.csv"
    summary.to_csv(csv_path, index=False)

    path = plot_loss_rate(summary, args, out_dir)
    print(f"已保存：{path}")
    print(f"已保存汇总表：{csv_path}")


if __name__ == "__main__":
    main()
