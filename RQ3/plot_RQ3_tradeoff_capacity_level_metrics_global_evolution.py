#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制全球风光单位装机容量级极端事件损失分解。

图采用 2×3 布局：第一行为风电，第二行为光伏；三列依次为单位装机
极端事件次数、单次事件净损失和单位装机绝对损失量。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from plot_RQ3_extreme_event_capacity_frequency_intensity_global_evolution import (
    DEFAULT_INPUT_CSV,
    load_summary,
)
from plot_RQ3_generation_loss_global_per_capacity_evolution import (
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SSPS,
)
from plot_RQ3_tradeoff_station_level_metrics_global_evolution import plot_summary


OUT_STEM = "fig_RQ3_tradeoff_capacity_level_decomposition_global_evolution"
CSV_NAME = "RQ3_tradeoff_capacity_level_metrics_global_evolution.csv"
CAPACITY_METRICS = [
    ("event_frequency_per_mw_year", "单位装机极端事件次数", "次/(MW·年)"),
    ("loss_per_episode_mwh", "单次事件净损失", "MWh/episode"),
    ("mean_loss_per_mw_year_mwh", "单位装机绝对损失量", "MWh/(MW·年)"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RQ3：绘制风光单位装机容量级损失分解的 2×3 演化图。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--ssps", nargs="+", default=DEFAULT_SSPS, help="需要绘制的 SSP 情景。")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help="全球 episode 与损失强度汇总 CSV。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认：RQ3/outputs/{MODEL}。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / args.model)
    csv_dir = out_dir / "csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    if args.input_csv is None:
        args.input_csv = Path(str(DEFAULT_INPUT_CSV).format(model=args.model))
    summary = load_summary(args)

    csv_path = csv_dir / CSV_NAME
    summary.to_csv(csv_path, index=False)
    figure_path = plot_summary(
        summary,
        args,
        out_dir,
        CAPACITY_METRICS,
        OUT_STEM,
        "全球风光单位装机容量级极端事件损失分解",
        "单位装机绝对损失 = 单位装机极端事件次数 × 单次事件净损失。",
    )

    print(f"已保存：{figure_path}")
    print(f"已保存汇总表：{csv_path}")
    print(
        "分解最大绝对误差："
        f"{summary['factorization_abs_error_mwh'].max():.3e} MWh/(MW·年)"
    )


if __name__ == "__main__":
    main()
