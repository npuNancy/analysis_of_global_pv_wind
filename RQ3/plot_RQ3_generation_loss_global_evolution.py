#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ3 图 1：极端天气造成的全球风光净出力损失演化（年代均值折线图）。

除原有风电、光伏双面板图外，另输出风光总量、风电、光伏三面板图；
风光总量在逐年层面将风电与光伏净损失相加后再按年代聚合。

基于 generation_loss aggregate 的 region 级年度长表
（event = all，即任一极端事件暴露期间的净损失），汇总为
26 个 regional-BCSD 国家的全球年总账，再按年代聚合：

    净出力损失 = sum(net_generation_loss_mwh)，MWh -> TWh；
    每个年代点 = center-k（K=5）窗口内各年的均值，
        2030s -> mean(2030-2039)，2040s -> mean(2040-2049)，
        2050s -> mean(2050-2059)；
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
    / "data/generation_loss_outputs/generation_loss"
    / "{model}"
    / "aggregate/generation_loss_region.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "RQ3/outputs"
FONT_PATH = ROOT / "data/SourceHanSansSC-Normal.otf"

DEFAULT_MODEL = "CANESM5"
DEFAULT_SSPS = ["ssp126", "ssp245", "ssp585"]
ANALYSIS_K = 5
# 临时修正：上游风电发电量及损失被错误放大 10 倍；上游数据修复后应删除此常量、字段列表及缩放函数。
TEMP_WIND_ENERGY_SCALE_FACTOR = 0.1
TEMP_WIND_ENERGY_COLUMNS = (
    "generation_loss_mwh",
    "net_generation_loss_mwh",
    "normal_generation_mwh",
    "normal_all_generation_mwh",
    "actual_generation_mwh",
    "generation_fluctuation_mwh",
)
COMBINED_TECH = "wind_solar"
TECH_LABEL = {"wind": "风电", "solar": "光伏", COMBINED_TECH: "风光总量"}
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
# 年代（快照年）标签；每个年代点为 center-k 窗口内各年的均值。
DECADE_ORDER = [2030, 2040, 2050]
DECADE_LABEL = {2030: "2030s", 2040: "2040s", 2050: "2050s"}
DECADE_WINDOWS = {
    2030: "2030-2039",
    2040: "2040-2049",
    2050: "2050-2059",
}


def apply_temp_wind_energy_correction(
    data: pd.DataFrame,
    *,
    context: str,
) -> int:
    """临时将风电发电量和损失能量项乘以 0.1；返回受影响的风电行数。"""
    if "tech" not in data.columns:
        raise KeyError("临时风电修正要求输入数据包含 tech 列。")
    columns = [column for column in TEMP_WIND_ENERGY_COLUMNS if column in data.columns]
    if not columns:
        raise KeyError(f"临时风电修正未找到能量字段：{TEMP_WIND_ENERGY_COLUMNS}")
    wind_mask = data["tech"].eq("wind")
    data.loc[wind_mask, columns] *= TEMP_WIND_ENERGY_SCALE_FACTOR
    affected = int(wind_mask.sum())
    print(
        f"[临时修正] {context}：已将风电 {', '.join(columns)} 乘以 "
        f"{TEMP_WIND_ENERGY_SCALE_FACTOR:g}（影响 {affected} 行）；"
        "上游数据修复后请移除此修正。"
    )
    return affected


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
            "默认：data/generation_loss_outputs/"
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
        & (df["analysis_scheme"] == "center-k")
        & (df["analysis_k"] == ANALYSIS_K)
        & (df["event"] == args.event)
        & (df["scenario"].isin(args.ssps))
        & (df["tech"].isin(args.techs))
    ].copy()
    if d.empty:
        raise SystemExit(f"输入 CSV 中没有匹配 model={args.model}、event={args.event} 的行。")

    # 临时修正：统一缩放风电发电量与损失能量项；上游数据修复后应删除此调用。
    apply_temp_wind_energy_correction(d, context="全球净出力损失图")

    annual_by_tech = (
        d.groupby(["scenario", "tech", "snapshot_year", "analysis_year"], as_index=False)
        .agg(
            net_generation_loss_twh=("net_generation_loss_mwh", "sum"),
            n_regions=("region", "nunique"),
        )
    )
    annual_by_tech["net_generation_loss_twh"] /= 1e6

    annual_parts = [annual_by_tech]
    if {"wind", "solar"}.issubset(args.techs):
        annual_total = (
            d.groupby(["scenario", "snapshot_year", "analysis_year"], as_index=False)
            .agg(
                net_generation_loss_twh=("net_generation_loss_mwh", "sum"),
                n_regions=("region", "nunique"),
                n_techs=("tech", "nunique"),
            )
        )
        annual_total = annual_total[annual_total["n_techs"] == 2].drop(columns="n_techs")
        annual_total["net_generation_loss_twh"] /= 1e6
        annual_total["tech"] = COMBINED_TECH
        annual_parts.append(annual_total)

    annual = pd.concat(annual_parts, ignore_index=True)

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


def _plot_summary_panels(
    summary: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
    *,
    techs: list[str],
    figsize: tuple[float, float],
    left: float,
    out_stem: str,
) -> Path:
    configure_style()
    fig, axes = plt.subplots(1, len(techs), figsize=figsize)
    if len(techs) == 1:
        axes = [axes]
    fig.subplots_adjust(left=left, right=0.98, top=0.82, bottom=0.2, wspace=0.28)

    x = np.arange(len(DECADE_ORDER))
    for index, (ax, tech) in enumerate(zip(axes, techs)):
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
        panel_tag(ax, chr(ord("a") + index))

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
        f"center-k（K={ANALYSIS_K}）窗口年均值（{windows}），误差条为窗口内年际最小-最大值。"
    ]
    if not n_wind.empty and not n_solar.empty:
        note_lines.append(
            f"覆盖国家数随情景与年代变化：风电 {n_wind.min():.0f}-{n_wind.max():.0f} 国、"
            f"光伏 {n_solar.min():.0f}-{n_solar.max():.0f} 国"
            "（SSP5-8.5 使用 SSP5-6.0 部署表，部分国家无场站），详见汇总 CSV。"
        )
    for i, line in enumerate(note_lines):
        fig.text(0.5, 0.055 - 0.045 * i, line, ha="center", fontsize=6.2, color="0.4")

    out_base = out_dir / out_stem
    fig.savefig(out_base.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)
    return out_base.with_suffix(".png")


def plot_summary(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    techs = [t for t in ["wind", "solar"] if t in args.techs]
    return _plot_summary_panels(
        summary,
        args,
        out_dir,
        techs=techs,
        figsize=(7.4, 3.2),
        left=0.09,
        out_stem="fig_RQ3_generation_loss_global_evolution",
    )


def plot_combined_summary(summary: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> Path:
    return _plot_summary_panels(
        summary,
        args,
        out_dir,
        techs=[COMBINED_TECH, "wind", "solar"],
        figsize=(10.8, 3.2),
        left=0.06,
        out_stem="fig_RQ3_generation_loss_global_evolution_combined",
    )


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)

    summary = load_decade_summary(args)
    csv_path = out_dir / "csv/RQ3_generation_loss_global_evolution.csv"
    summary[summary["tech"].isin(args.techs)].to_csv(csv_path, index=False)

    path = plot_summary(summary, args, out_dir)
    print(f"已保存：{path}")
    if COMBINED_TECH in summary["tech"].values:
        combined_csv_path = out_dir / "csv/RQ3_generation_loss_global_evolution_combined.csv"
        summary.to_csv(combined_csv_path, index=False)
        combined_path = plot_combined_summary(summary, args, out_dir)
        print(f"已保存：{combined_path}")
        print(f"已保存汇总表：{combined_csv_path}")
    print(f"已保存汇总表：{csv_path}")


if __name__ == "__main__":
    main()
