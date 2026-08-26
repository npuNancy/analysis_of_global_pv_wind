#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 26 个国家、3 个 w/o combined 指标结果中 SSP1-2.6 与 SSP5-8.5 的交叉。

交叉仅依据 wind/solar 的年代均值折线判断：若两个情景的均值差在相邻年代
之间变号，或在某个年代近似为 0，则判为交叉。误差条重叠不计作曲线交叉。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "CANESM5"
DEFAULT_INPUT_DIR = ROOT / "RQ3/outputs/{model}/region_generation_loss"
DECADE_ORDER = [2030, 2040, 2050]
COMPARE_SSPS = ("ssp126", "ssp585")
TECHS = ("wind", "solar")


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    filename_suffix: str
    value_column: str
    unit: str


METRICS = (
    MetricSpec(
        key="absolute_loss",
        label="绝对损失量",
        filename_suffix="generation_loss_region_evolution.csv",
        value_column="net_generation_loss_twh_mean",
        unit="TWh/年",
    ),
    MetricSpec(
        key="relative_loss_rate",
        label="相对损失率",
        filename_suffix="generation_loss_rate_region_evolution.csv",
        value_column="loss_rate_pct_mean",
        unit="%",
    ),
    MetricSpec(
        key="loss_per_capacity",
        label="单位装机损失",
        filename_suffix="generation_loss_per_capacity_region_evolution.csv",
        value_column="loss_twh_per_tw_mean",
        unit="TWh/TW",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="搜索国家级风光损失结果中 SSP1-2.6 与 SSP5-8.5 的均值曲线交叉。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="region_generation_loss 根目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="结果 CSV 输出目录；默认与输入目录相同。",
    )
    parser.add_argument(
        "--atol",
        type=float,
        default=1e-12,
        help="判断两个情景在年代点相等时使用的绝对容差。",
    )
    return parser.parse_args()


def expected_csv_path(region_dir: Path, metric: MetricSpec) -> Path:
    """按三个绘图脚本的命名约定返回单个国家的指标 CSV。"""
    return region_dir / f"RQ3_{region_dir.name}_{metric.filename_suffix}"


def format_event(event: dict[str, object]) -> str:
    if event["crossing_type"] == "touch_at_decade":
        return f"{int(event['start_year'])}s"
    return f"{int(event['start_year'])}s-{int(event['end_year'])}s"


def find_tech_crossings(
    data: pd.DataFrame,
    *,
    metric: MetricSpec,
    tech: str,
    atol: float,
) -> tuple[list[dict[str, object]], int]:
    """返回单项技术的交叉事件及 SSP126/SSP585 共同年代数。"""
    subset = data[
        (data["tech"] == tech)
        & (data["scenario"].isin(COMPARE_SSPS))
        & (data["snapshot_year"].isin(DECADE_ORDER))
    ]
    if subset.empty:
        return [], 0

    duplicate_mask = subset.duplicated(["scenario", "snapshot_year"], keep=False)
    if duplicate_mask.any():
        duplicates = subset.loc[duplicate_mask, ["scenario", "snapshot_year"]]
        raise ValueError(f"{tech}/{metric.key} 存在重复情景—年代记录：\n{duplicates}")

    wide = subset.pivot(index="snapshot_year", columns="scenario", values=metric.value_column)
    if not set(COMPARE_SSPS).issubset(wide.columns):
        return [], 0
    wide = wide.reindex(DECADE_ORDER)
    common_mask = wide[list(COMPARE_SSPS)].notna().all(axis=1)
    common_years = [year for year in DECADE_ORDER if bool(common_mask.loc[year])]
    difference = wide["ssp126"] - wide["ssp585"]

    events: list[dict[str, object]] = []
    touched_years: set[int] = set()
    for year in common_years:
        diff = float(difference.loc[year])
        if np.isclose(diff, 0.0, atol=atol, rtol=0.0):
            touched_years.add(year)
            events.append(
                {
                    "tech": tech,
                    "crossing_type": "touch_at_decade",
                    "start_year": year,
                    "end_year": year,
                    "estimated_crossing_year": float(year),
                    "difference_start": diff,
                    "difference_end": diff,
                    "ssp126_start": float(wide.loc[year, "ssp126"]),
                    "ssp585_start": float(wide.loc[year, "ssp585"]),
                    "ssp126_end": float(wide.loc[year, "ssp126"]),
                    "ssp585_end": float(wide.loc[year, "ssp585"]),
                }
            )

    for start_year, end_year in zip(DECADE_ORDER[:-1], DECADE_ORDER[1:]):
        if start_year not in common_years or end_year not in common_years:
            continue
        if start_year in touched_years or end_year in touched_years:
            continue
        difference_start = float(difference.loc[start_year])
        difference_end = float(difference.loc[end_year])
        if difference_start * difference_end >= 0:
            continue
        fraction = -difference_start / (difference_end - difference_start)
        crossing_year = start_year + fraction * (end_year - start_year)
        events.append(
            {
                "tech": tech,
                "crossing_type": "between_decades",
                "start_year": start_year,
                "end_year": end_year,
                "estimated_crossing_year": crossing_year,
                "difference_start": difference_start,
                "difference_end": difference_end,
                "ssp126_start": float(wide.loc[start_year, "ssp126"]),
                "ssp585_start": float(wide.loc[start_year, "ssp585"]),
                "ssp126_end": float(wide.loc[end_year, "ssp126"]),
                "ssp585_end": float(wide.loc[end_year, "ssp585"]),
            }
        )
    return events, len(common_years)


def analyze(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    input_dir = args.input_dir or Path(str(DEFAULT_INPUT_DIR).format(model=args.model))
    if not input_dir.is_dir():
        raise SystemExit(f"未找到国家结果目录：{input_dir}")
    region_dirs = sorted(path for path in input_dir.iterdir() if path.is_dir())
    if len(region_dirs) != 26:
        raise SystemExit(f"预期 26 个国家目录，实际找到 {len(region_dirs)} 个：{input_dir}")

    screening_rows: list[dict[str, object]] = []
    crossing_rows: list[dict[str, object]] = []
    for region_dir in region_dirs:
        for metric in METRICS:
            csv_path = expected_csv_path(region_dir, metric)
            if not csv_path.exists():
                raise SystemExit(f"缺少预期的 w/o combined 数据 CSV：{csv_path}")
            data = pd.read_csv(csv_path)
            required = {"region", "scenario", "tech", "snapshot_year", metric.value_column}
            missing_columns = sorted(required - set(data.columns))
            if missing_columns:
                raise ValueError(f"{csv_path} 缺少字段：{missing_columns}")
            regions = data["region"].dropna().unique()
            if len(regions) != 1:
                raise ValueError(f"{csv_path} 应只包含一个国家，实际为：{regions}")
            region = str(regions[0])

            row: dict[str, object] = {
                "model": args.model,
                "region": region,
                "metric": metric.key,
                "metric_label": metric.label,
                "unit": metric.unit,
            }
            figure_events: list[dict[str, object]] = []
            for tech in TECHS:
                events, common_decades = find_tech_crossings(
                    data,
                    metric=metric,
                    tech=tech,
                    atol=args.atol,
                )
                row[f"{tech}_common_decades"] = common_decades
                row[f"{tech}_has_crossing"] = bool(events)
                row[f"{tech}_crossing_intervals"] = ";".join(
                    format_event(event) for event in events
                )
                for event in events:
                    crossing_rows.append(
                        {
                            "model": args.model,
                            "region": region,
                            "metric": metric.key,
                            "metric_label": metric.label,
                            "unit": metric.unit,
                            **event,
                        }
                    )
                figure_events.extend(events)
            row["has_any_crossing"] = bool(figure_events)
            row["crossing_techs"] = ";".join(
                tech for tech in TECHS if bool(row[f"{tech}_has_crossing"])
            )
            screening_rows.append(row)

    screening = pd.DataFrame(screening_rows)
    if len(screening) != 78:
        raise RuntimeError(f"筛查范围应为 26 × 3 = 78，实际为 {len(screening)}。")
    crossings = pd.DataFrame(crossing_rows)
    return screening, crossings


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir or Path(str(DEFAULT_INPUT_DIR).format(model=args.model))
    output_dir = args.output_dir or input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    screening, crossings = analyze(args)
    screening_path = output_dir / "RQ3_ssp126_ssp585_crossing_screening_78.csv"
    crossings_path = output_dir / "RQ3_ssp126_ssp585_crossings.csv"
    screening.to_csv(screening_path, index=False)
    crossings.to_csv(crossings_path, index=False)

    positives = screening[screening["has_any_crossing"]]
    print("判定口径：年代均值折线差值变号或端点相等；误差条重叠不计为交叉。")
    print(f"已检查：{len(screening)} 个国家—指标结果。")
    print(f"存在交叉：{len(positives)} 个国家—指标结果，共 {len(crossings)} 个技术交叉事件。")
    if crossings.empty:
        print("未发现 SSP1-2.6 与 SSP5-8.5 的均值曲线交叉。")
    else:
        display = crossings[
            [
                "region",
                "metric_label",
                "tech",
                "start_year",
                "end_year",
                "estimated_crossing_year",
            ]
        ].copy()
        display["estimated_crossing_year"] = display["estimated_crossing_year"].round(2)
        print(display.to_string(index=False))
    print(f"已保存完整筛查表：{screening_path}")
    print(f"已保存交叉明细表：{crossings_path}")


if __name__ == "__main__":
    main()
