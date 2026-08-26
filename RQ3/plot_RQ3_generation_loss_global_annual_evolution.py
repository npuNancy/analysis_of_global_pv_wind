#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ3：绘制全球风光损失指标的逐年演化及线性趋势。

一次运行输出 6 张图：

    （绝对损失量、相对损失率、单位装机损失）
    ×（不含风光总量、含风光总量）。

实线为 center-k（K=5）三个窗口中的逐年全球值，即 2030-2039、
2040-2049、2050-2059；同色虚线为每个 SSP 在全部有效年份上的
一阶线性拟合，拟合线不进入图例。三个指标的逐年聚合口径与现有
plot_RQ3_generation_loss_global_*.py 保持一致。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plot_RQ3_generation_loss_global_evolution import (
    ANALYSIS_K,
    COMBINED_TECH,
    SSP_C,
    SSP_L,
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
TECH_LABEL = {"wind": "风电", "solar": "光伏", COMBINED_TECH: "风光总量"}
YEAR_WINDOWS = "2030-2039、2040-2049、2050-2059"

METRICS = {
    "absolute": {
        "column": "net_generation_loss_twh",
        "panel_title": "净出力损失总量",
        "ylabel": "净出力损失（TWh/年）",
        "figure_title": "全球极端天气风光净出力损失逐年演化",
        "stem": "generation_loss",
        "note": "绝对损失为各国净出力损失逐年加总；MWh 换算为 TWh。",
    },
    "rate": {
        "column": "loss_rate_pct",
        "panel_title": "净出力损失率",
        "ylabel": "损失率（%）",
        "figure_title": "全球极端天气风光出力损失率逐年演化",
        "stem": "generation_loss_rate",
        "note": "损失率 = 全球净出力损失 / 全球全年应发电量；比例不跨 region 直接平均。",
    },
    "per_capacity": {
        "column": "loss_twh_per_tw",
        "panel_title": "单位装机净出力损失",
        "ylabel": "单位装机损失（TWh / TW）",
        "figure_title": "全球极端天气风光单位装机净出力损失逐年演化",
        "stem": "generation_loss_per_capacity",
        "note": "单位装机损失 = 全球净出力损失 / 全球装机容量；MWh/MW 与 TWh/TW 数值相同。",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制全球风光损失指标逐年折线及线性趋势。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--techs",
        nargs="+",
        default=["wind", "solar"],
        help="需要绘制的技术；combined 仅在 wind 和 solar 均被选择时生成。",
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
        help="输出目录。默认：RQ3/outputs/{MODEL}。",
    )
    return parser.parse_args()


def load_annual_summary(args: argparse.Namespace) -> pd.DataFrame:
    """读取 region 年度长表并计算全球逐年三个损失指标。"""
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
        raise SystemExit(
            f"输入 CSV 中没有匹配 model={args.model}、center-k K={ANALYSIS_K}、"
            f"event={args.event} 的行。"
        )

    # 临时修正：上游风电发电量和损失能量被错误放大 10 倍；上游修复后移除此调用。
    apply_temp_wind_energy_correction(d, context="全球逐年风光损失图")

    group_columns = ["scenario", "tech", "snapshot_year", "analysis_year"]
    annual_by_tech = (
        d.groupby(group_columns, as_index=False)
        .agg(
            loss_mwh=("net_generation_loss_mwh", "sum"),
            normal_mwh=("normal_all_generation_mwh", "sum"),
            capacity_mw=("capacity_mw", "sum"),
            n_regions=("region", "nunique"),
        )
    )

    annual_parts = [annual_by_tech]
    if {"wind", "solar"}.issubset(args.techs):
        annual_total = (
            d.groupby(["scenario", "snapshot_year", "analysis_year"], as_index=False)
            .agg(
                loss_mwh=("net_generation_loss_mwh", "sum"),
                normal_mwh=("normal_all_generation_mwh", "sum"),
                capacity_mw=("capacity_mw", "sum"),
                n_regions=("region", "nunique"),
                n_techs=("tech", "nunique"),
            )
        )
        annual_total = annual_total[annual_total["n_techs"] == 2].drop(columns="n_techs")
        annual_total["tech"] = COMBINED_TECH
        annual_parts.append(annual_total)

    annual = pd.concat(annual_parts, ignore_index=True)
    annual["net_generation_loss_twh"] = annual["loss_mwh"] / 1e6
    annual["loss_rate_pct"] = np.where(
        annual["normal_mwh"] > 0,
        annual["loss_mwh"] / annual["normal_mwh"] * 100.0,
        np.nan,
    )
    annual["loss_twh_per_tw"] = np.where(
        annual["capacity_mw"] > 0,
        annual["loss_mwh"] / annual["capacity_mw"],
        np.nan,
    )
    annual["capacity_tw"] = annual["capacity_mw"] / 1e6
    return annual.sort_values(["tech", "scenario", "analysis_year"]).reset_index(drop=True)


def add_linear_trend(ax, years: pd.Series, values: pd.Series, color: str) -> None:
    """叠加同色一阶线性拟合虚线，不创建 legend 条目。"""
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 2 or np.ptp(x[valid]) == 0:
        return
    fit_x = np.sort(x[valid])
    coefficients = np.polyfit(x[valid], y[valid], 1)
    ax.plot(
        fit_x,
        np.polyval(coefficients, fit_x),
        "--",
        color=color,
        lw=1.0,
        alpha=0.9,
        zorder=1,
        label="_nolegend_",
    )


def plot_metric(
    annual: pd.DataFrame,
    args: argparse.Namespace,
    out_dir: Path,
    *,
    metric_key: str,
    techs: list[str],
    combined: bool,
) -> Path:
    """绘制一个指标的 w/ combined 或 w/o combined 逐年图。"""
    spec = METRICS[metric_key]
    configure_style()
    figsize = (10.8, 3.2) if combined else (7.4, 3.2)
    left = 0.06 if combined else 0.09
    fig, axes = plt.subplots(1, len(techs), figsize=figsize, sharex=True)
    if len(techs) == 1:
        axes = [axes]
    fig.subplots_adjust(left=left, right=0.98, top=0.82, bottom=0.24, wspace=0.28)

    year_min = int(annual["analysis_year"].min())
    year_max = int(annual["analysis_year"].max())
    xticks = np.arange((year_min // 5) * 5, year_max + 1, 5)

    for index, (ax, tech) in enumerate(zip(axes, techs)):
        dtech = annual[annual["tech"] == tech]
        for ssp in args.ssps:
            sub = dtech[dtech["scenario"] == ssp].sort_values("analysis_year")
            if sub.empty:
                continue
            color = SSP_C.get(ssp, "0.3")
            ax.plot(
                sub["analysis_year"],
                sub[spec["column"]],
                "-",
                color=color,
                lw=1.6,
                label=SSP_L.get(ssp, ssp),
                zorder=2,
            )
            add_linear_trend(ax, sub["analysis_year"], sub[spec["column"]], color)

        ax.set_xlim(year_min, year_max)
        ax.set_xticks(xticks)
        ax.set_title(f"{TECH_LABEL[tech]}：{spec['panel_title']}", fontsize=9)
        ax.set_xlabel("年份")
        ax.set_ylabel(spec["ylabel"])
        ax.grid(axis="y", lw=0.4, alpha=0.45)
        panel_tag(ax, chr(ord("a") + index), dx=-0.12)

    handles = [
        Line2D([0], [0], color=SSP_C.get(ssp, "0.3"), lw=1.6, label=SSP_L.get(ssp, ssp))
        for ssp in args.ssps
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), bbox_to_anchor=(0.5, 0.96))
    fig.suptitle(
        f"{spec['figure_title']}（{args.model}）",
        fontsize=11,
        fontweight="bold",
        y=1.02,
    )
    fig.text(
        0.5,
        0.055,
        f"实线为 center-k（K={ANALYSIS_K}）逐年值（{YEAR_WINDOWS}）；同色虚线为各 SSP 全部有效年份的一阶线性拟合。",
        ha="center",
        fontsize=6.2,
        color="0.4",
    )
    fig.text(0.5, 0.012, spec["note"], ha="center", fontsize=6.2, color="0.4")

    suffix = "_combined" if combined else ""
    out_path = out_dir / f"fig_RQ3_{spec['stem']}_global_annual_evolution{suffix}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def save_metric_csvs(
    annual: pd.DataFrame,
    args: argparse.Namespace,
    csv_dir: Path,
    *,
    metric_key: str,
) -> tuple[Path, Path]:
    """保存与两种面板版本对应的逐年源数据。"""
    spec = METRICS[metric_key]
    columns = [
        "scenario",
        "tech",
        "snapshot_year",
        "analysis_year",
        spec["column"],
        "n_regions",
    ]
    plain_path = csv_dir / f"RQ3_{spec['stem']}_global_annual_evolution.csv"
    combined_path = csv_dir / f"RQ3_{spec['stem']}_global_annual_evolution_combined.csv"
    annual[annual["tech"].isin(args.techs)][columns].to_csv(plain_path, index=False)
    annual[columns].to_csv(combined_path, index=False)
    return plain_path, combined_path


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    csv_dir = out_dir / "csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    annual = load_annual_summary(args)
    plain_techs = [tech for tech in ["wind", "solar"] if tech in args.techs]
    if not plain_techs:
        raise SystemExit("--techs 至少需要包含 wind 或 solar。")

    generated: list[Path] = []
    for metric_key in METRICS:
        generated.append(
            plot_metric(
                annual,
                args,
                out_dir,
                metric_key=metric_key,
                techs=plain_techs,
                combined=False,
            )
        )
        if COMBINED_TECH in annual["tech"].values:
            generated.append(
                plot_metric(
                    annual,
                    args,
                    out_dir,
                    metric_key=metric_key,
                    techs=[COMBINED_TECH, *plain_techs],
                    combined=True,
                )
            )
        plain_csv, combined_csv = save_metric_csvs(
            annual,
            args,
            csv_dir,
            metric_key=metric_key,
        )
        print(f"已保存逐年数据：{plain_csv}")
        print(f"已保存逐年数据：{combined_csv}")

    for path in generated:
        print(f"已保存：{path}")


if __name__ == "__main__":
    main()
