#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ3 图 1：极端天气造成的全球风光净出力损失演化（年代均值折线图）。

基于 generation_loss aggregate 的 region 级年度长表
（event = all，即任一极端事件暴露期间的净损失），汇总为
26 个 regional-BCSD 国家的全球年总账，再按年代聚合：

    净出力损失 = sum(net_generation_loss_mwh)，MWh -> TWh；
    每个年代点 = center-k（K=2）窗口内各年的均值，
        2030s -> mean(2033-2037)，2040s -> mean(2043-2047)，
        2050s -> mean(2053-2057)；
    误差条 = 窗口内年际最小-最大值。

覆盖口径说明：部分国家在部分情景下无 SSP 场站（pipeline 以
SKIPPED_NO_STATIONS 正常跳过，SSP5-8.5 气象强迫使用 SSP5-6.0
部署表），绝对量按各情景-年实际覆盖国家加总，覆盖国家数
写入汇总 CSV。
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


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = (
    ROOT
    / "ref_code/calculate_wind_solar_generation_loss/outputs/generation_loss"
    / "{model}"
    / "aggregate/generation_loss_region.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "RQ3/outputs"
FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"

DEFAULT_MODEL = "CANESM5"
DEFAULT_SSPS = ["ssp126", "ssp245", "ssp585"]
TECH_LABEL = {"wind": "风电", "solar": "光伏"}
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
# 年代（快照年）标签；每个年代点为 center-k 窗口内各年的均值。
DECADE_ORDER = [2030, 2040, 2050]
DECADE_LABEL = {2030: "2030s", 2040: "2040s", 2050: "2050s"}
DECADE_WINDOWS = {
    2030: "2033-2037",
    2040: "2043-2047",
    2050: "2053-2057",
}


def configure_style() -> None:
    from matplotlib import font_manager as fm

    if FONT_PATH.exists():
        fm.fontManager.addfont(str(FONT_PATH))
        font_name = fm.FontProperties(fname=str(FONT_PATH)).get_name()
        sans_serif = [font_name, "Arial", "DejaVu Sans"]
    else:
        sans_serif = ["Arial", "DejaVu Sans"]

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans_serif,
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
            "svg.fonttype": "none",
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制全球风光净出力损失年代均值演化折线图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--techs",
        nargs="+",
        default=["wind", "solar"],
        help="需要绘制的技术。wind 在左列，solar 在右列。",
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
        help=(
            "generation_loss aggregate 的 region 级年度长表 CSV。"
            "默认：ref_code/calculate_wind_solar_generation_loss/outputs/"
            "generation_loss/{model}/aggregate/generation_loss_region.csv。"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认：RQ3/outputs/{MODEL}。",
    )
    return parser.parse_args()


def load_decade_summary(args: argparse.Namespace) -> pd.DataFrame:
    """读取年度长表，先汇总为全球逐年总账，再按年代取窗口均值。"""
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
            net_generation_loss_twh=("net_generation_loss_mwh", "sum"),
            n_regions=("region", "nunique"),
        )
    )
    annual["net_generation_loss_twh"] /= 1e6

    decade = (
        annual.groupby(["scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            net_generation_loss_twh_mean=("net_generation_loss_twh", "mean"),
            net_generation_loss_twh_min=("net_generation_loss_twh", "min"),
            net_generation_loss_twh_max=("net_generation_loss_twh", "max"),
            n_years=("analysis_year", "nunique"),
            n_regions_mean=("n_regions", "mean"),
        )
    )
    decade["decade"] = decade["snapshot_year"].map(DECADE_LABEL)
    return decade


def panel_tag(ax, tag: str, dx: float = -0.08, dy: float = 1.04) -> None:
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", ha="right")


def plot_summary(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    configure_style()
    techs = [t for t in ["wind", "solar"] if t in args.techs]
    fig, axes = plt.subplots(1, len(techs), figsize=(7.4, 3.2))
    if len(techs) == 1:
        axes = [axes]
    fig.subplots_adjust(left=0.09, right=0.98, top=0.82, bottom=0.2, wspace=0.28)

    x = np.arange(len(DECADE_ORDER))
    for ax, tech, tag in zip(axes, techs, ["a", "b"]):
        dtech = summary[summary["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["scenario"] == ssp].set_index("snapshot_year")
            if sub.empty:
                continue
            sub = sub.reindex(DECADE_ORDER)
            mean = sub["net_generation_loss_twh_mean"].to_numpy(dtype=float)
            lo = sub["net_generation_loss_twh_min"].to_numpy(dtype=float)
            hi = sub["net_generation_loss_twh_max"].to_numpy(dtype=float)
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
        ax.set_title(f"{TECH_LABEL[tech]}：净出力损失总量", fontsize=9)
        ax.set_xlabel("年代")
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        ax.margins(x=0.12)
        panel_tag(ax, tag)

    axes[0].set_ylabel("净出力损失（TWh/年）")
    handles = [
        Line2D([0], [0], color=SSP_C.get(s, "0.3"), lw=1.8, marker="o", ms=4,
               markerfacecolor="white", label=SSP_L.get(s, s))
        for s in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(f"全球极端天气风光净出力损失演化（{args.model}）", fontsize=11, fontweight="bold", y=1.02)
    windows = "、".join(f"{DECADE_LABEL[d]}:{DECADE_WINDOWS[d]}" for d in DECADE_ORDER)
    n_wind = summary[summary["tech"] == "wind"]["n_regions_mean"]
    n_solar = summary[summary["tech"] == "solar"]["n_regions_mean"]
    note_lines = [
        "净出力损失为极端事件（并集）暴露期间应发电量与实际出力之差；每个年代点为 "
        f"center-k（K=2）窗口年均值（{windows}），误差条为窗口内年际最小-最大值。"
    ]
    if not n_wind.empty and not n_solar.empty:
        note_lines.append(
            f"覆盖国家数随情景与年代变化：风电 {n_wind.min():.0f}-{n_wind.max():.0f} 国、"
            f"光伏 {n_solar.min():.0f}-{n_solar.max():.0f} 国"
            "（SSP5-8.5 使用 SSP5-6.0 部署表，部分国家无场站），详见汇总 CSV。"
        )
    for i, line in enumerate(note_lines):
        fig.text(0.5, 0.055 - 0.045 * i, line, ha="center", fontsize=6.2, color="0.4")

    out_base = out_dir / "fig_RQ3_generation_loss_global_evolution"
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    summary = load_decade_summary(args)
    csv_path = out_dir / "csv/RQ3_generation_loss_global_evolution.csv"
    summary.to_csv(csv_path, index=False)

    path = plot_summary(summary, args, out_dir)
    print(f"已保存：{path}")
    print(f"已保存汇总表：{csv_path}")


if __name__ == "__main__":
    main()
