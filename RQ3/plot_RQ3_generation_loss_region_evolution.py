#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ3：逐国绘制风光净出力绝对损失量的年代演化。"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_RQ3_generation_loss_global_evolution import (
    COMBINED_TECH,
    apply_temp_wind_energy_correction,
    configure_style,
    panel_tag,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = (
    ROOT
    / "data/generation_loss_outputs/generation_loss"
    / "{model}"
    / "aggregate/generation_loss_region.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "RQ3/outputs"

DEFAULT_MODEL = "CANESM5"
DEFAULT_SSPS = ["ssp126", "ssp245", "ssp585"]
ANALYSIS_K = 5
TEMP_WIND_CAPACITY_SCALE_FACTOR = 0.1
TECH_LABEL = {"wind": "风电", "solar": "光伏", COMBINED_TECH: "风光总量"}
SSP_C = {"ssp126": "#1d3b6f", "ssp245": "#e7a13b", "ssp585": "#9e1b1b"}
SSP_L = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
DECADE_ORDER = [2030, 2040, 2050]
DECADE_LABEL = {2030: "2030s", 2040: "2040s", 2050: "2050s"}
DECADE_WINDOWS = {2030: "2030-2039", 2040: "2040-2049", 2050: "2050-2059"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：逐国绘制风光净出力绝对损失量年代演化图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--techs",
        nargs="+",
        default=["wind", "solar"],
        help="需要绘制的技术；固定按 wind、solar 排列。",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        default=None,
        help="需要绘制的国家名称；默认绘制全部国家。",
    )
    parser.add_argument(
        "--event",
        default="all",
        help="极端事件口径，all 为全部支持事件的并集。",
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
        help="国家子目录的统一根目录。默认：RQ3/outputs/{MODEL}/region_generation_loss。",
    )
    parser.add_argument(
        "--error-bar",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否绘制表示窗口内年际最小-最大值的误差条。",
    )
    return parser.parse_args()


def safe_region_name(region: str) -> str:
    """生成可安全用于文件名、同时尽量保留原国家名的字符串。"""
    safe = re.sub(r"[^\w.-]+", "_", region, flags=re.UNICODE).strip("._")
    return safe or "unnamed_region"


def apply_temp_wind_energy_and_capacity_correction(
    data: pd.DataFrame,
    *,
    context: str,
) -> int:
    """临时将风电能量字段和装机容量统一乘以 0.1。"""
    affected = apply_temp_wind_energy_correction(data, context=context)
    if "capacity_mw" not in data.columns:
        raise KeyError("临时风电装机修正要求输入数据包含 capacity_mw 列。")
    wind_mask = data["tech"].eq("wind")
    data.loc[wind_mask, "capacity_mw"] *= TEMP_WIND_CAPACITY_SCALE_FACTOR
    capacity_affected = int(wind_mask.sum())
    print(
        f"[临时修正] {context}：已将风电 capacity_mw 乘以 "
        f"{TEMP_WIND_CAPACITY_SCALE_FACTOR:g}（影响 {capacity_affected} 行）；"
        "上游数据修复后请移除此修正。"
    )
    return affected


def load_region_summary(args: argparse.Namespace) -> pd.DataFrame:
    """按国家和技术构造逐年损失总账，再聚合为年代窗口统计。"""
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
    if args.regions:
        available = set(d["region"].unique())
        missing = sorted(set(args.regions) - available)
        if missing:
            raise SystemExit(f"输入数据中不存在指定国家：{', '.join(missing)}")
        d = d[d["region"].isin(args.regions)].copy()
    if d.empty:
        raise SystemExit(f"输入 CSV 中没有匹配 model={args.model}、event={args.event} 的行。")

    # 临时修正：风电能量字段和装机容量统一乘以 0.1；上游修复后删除此调用。
    apply_temp_wind_energy_and_capacity_correction(d, context="国家净出力绝对损失图")

    annual_by_tech = (
        d.groupby(
            ["region", "scenario", "tech", "snapshot_year", "analysis_year"],
            as_index=False,
        )
        .agg(net_generation_loss_twh=("net_generation_loss_mwh", "sum"))
    )
    annual_by_tech["net_generation_loss_twh"] /= 1e6
    annual_parts = [annual_by_tech]

    if {"wind", "solar"}.issubset(args.techs):
        annual_total = (
            d.groupby(
                ["region", "scenario", "snapshot_year", "analysis_year"],
                as_index=False,
            )
            .agg(
                net_generation_loss_twh=("net_generation_loss_mwh", "sum"),
                n_techs=("tech", "nunique"),
            )
        )
        annual_total = annual_total[annual_total["n_techs"] == 2].drop(columns="n_techs")
        annual_total["net_generation_loss_twh"] /= 1e6
        annual_total["tech"] = COMBINED_TECH
        annual_parts.append(annual_total)

    annual = pd.concat(annual_parts, ignore_index=True)
    decade = (
        annual.groupby(["region", "scenario", "tech", "snapshot_year"], as_index=False)
        .agg(
            net_generation_loss_twh_mean=("net_generation_loss_twh", "mean"),
            net_generation_loss_twh_min=("net_generation_loss_twh", "min"),
            net_generation_loss_twh_max=("net_generation_loss_twh", "max"),
            n_years=("analysis_year", "nunique"),
        )
    )
    decade["decade"] = decade["snapshot_year"].map(DECADE_LABEL)
    return decade


def plot_region(
    summary: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
    region: str,
    *,
    include_combined: bool,
) -> Path:
    """为单个国家绘制双面板或含风光总量的三面板图。"""
    configure_style()
    techs = [COMBINED_TECH, "wind", "solar"] if include_combined else ["wind", "solar"]
    figsize = (10.8, 3.2) if include_combined else (7.4, 3.2)
    left = 0.06 if include_combined else 0.09
    fig, axes = plt.subplots(1, len(techs), figsize=figsize)
    fig.subplots_adjust(left=left, right=0.98, top=0.82, bottom=0.2, wspace=0.28)

    region_summary = summary[summary["region"] == region]
    x = np.arange(len(DECADE_ORDER))
    for index, (ax, tech) in enumerate(zip(axes, techs)):
        dtech = region_summary[region_summary["tech"] == tech]
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
                yerr=[mean - lo, hi - mean] if args.error_bar else None,
                fmt="-o",
                color=color,
                lw=1.8,
                ms=4,
                capsize=2.5,
                elinewidth=0.8,
                markeredgecolor=color,
                markerfacecolor="white",
                markeredgewidth=1.0,
            )
        if dtech.empty:
            ax.text(0.5, 0.5, "无数据", transform=ax.transAxes, ha="center", va="center", color="0.5")
            ax.set_yticks([])
        ax.set_xticks(x)
        ax.set_xticklabels([DECADE_LABEL[d] for d in DECADE_ORDER])
        ax.set_title(f"{TECH_LABEL[tech]}：净出力损失总量", fontsize=9)
        ax.set_xlabel("年代")
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        ax.margins(x=0.12)
        panel_tag(ax, chr(ord("a") + index))

    axes[0].set_ylabel("净出力损失（TWh/年）")
    handles = [
        Line2D(
            [0], [0], color=SSP_C.get(s, "0.3"), lw=1.8, marker="o", ms=4,
            markerfacecolor="white", label=SSP_L.get(s, s),
        )
        for s in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(
        f"{region}：极端天气风光净出力损失演化（{args.model}）",
        fontsize=11,
        fontweight="bold",
        y=1.02,
    )
    windows = "、".join(f"{DECADE_LABEL[d]}:{DECADE_WINDOWS[d]}" for d in DECADE_ORDER)
    fig.text(
        0.5,
        0.045,
        "净出力损失为极端事件暴露期间应发电量与实际出力之差；每个年代点为 "
        f"center-k（K={ANALYSIS_K}）窗口年均值（{windows}）"
        + ("，误差条为窗口内年际最小-最大值。" if args.error_bar else "。"),
        ha="center",
        fontsize=6.2,
        color="0.4",
    )

    suffix = "_combined" if include_combined else ""
    out_path = out_dir / f"fig_RQ3_{safe_region_name(region)}_generation_loss_region_evolution{suffix}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> None:
    args = parse_args()
    output_root = args.output_dir or (
        DEFAULT_OUTPUT_DIR / args.model / "region_generation_loss"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    summary = load_region_summary(args)
    regions = args.regions or sorted(summary["region"].unique())
    for region in regions:
        safe_region = safe_region_name(region)
        region_dir = output_root / safe_region
        region_dir.mkdir(parents=True, exist_ok=True)
        csv_path = region_dir / f"RQ3_{safe_region}_generation_loss_region_evolution.csv"
        summary[summary["region"] == region].to_csv(csv_path, index=False)
        path = plot_region(summary, args, region_dir, region, include_combined=False)
        combined_path = plot_region(summary, args, region_dir, region, include_combined=True)
        print(f"已保存：{path}")
        print(f"已保存：{combined_path}")
        print(f"已保存汇总表：{csv_path}")
    print(f"共生成 {len(regions) * 2} 张国家图。")


if __name__ == "__main__":
    main()
