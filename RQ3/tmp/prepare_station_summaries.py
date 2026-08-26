#!/usr/bin/env python3
"""从年代场站表一次性提取后续临时图复用的轻量 source-data。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import (
    DECADE_STATION_CSV,
    SSPS,
    TEMP_WIND_ENERGY_COLUMNS,
    TEMP_WIND_ENERGY_SCALE_FACTOR,
    add_common_args,
    apply_temp_wind_energy_correction,
    output_dir,
)


USECOLS = [
    "model", "scenario", "source", "region", "tech", "snapshot_year",
    "station_id", "lon", "lat", "event", "generation_loss_mwh",
    "net_generation_loss_mwh", "normal_generation_mwh",
    "normal_all_generation_mwh", "event_duration_hours", "capacity_mw",
]


def prepare(model: str, out_dir: Path, force: bool = False) -> tuple[Path, Path]:
    station_out = out_dir / "csv/source_station_decade_all.csv"
    country_out = out_dir / "csv/source_country_event_decade.csv"
    if station_out.exists() and country_out.exists() and not force:
        print(f"复用：{station_out}")
        print(f"复用：{country_out}")
        return station_out, country_out

    path = Path(str(DECADE_STATION_CSV).format(model=model))
    if not path.exists():
        raise SystemExit(f"未找到年代场站汇总：{path}")

    station_parts: list[pd.DataFrame] = []
    country_parts: list[pd.DataFrame] = []
    corrected_wind_rows = 0
    for index, chunk in enumerate(pd.read_csv(path, usecols=USECOLS, chunksize=200_000), start=1):
        chunk = chunk[(chunk["model"] == model) & chunk["scenario"].isin(SSPS)].copy()
        if chunk.empty:
            continue
        # 临时修正：场站缓存必须与 region 图使用同一风电 0.1 口径；上游修复后删除。
        corrected_wind_rows += apply_temp_wind_energy_correction(
            chunk,
            context=f"场站 chunk {index}",
            emit_log=False,
        )
        chunk["capacity_event_hours"] = chunk["capacity_mw"] * chunk["event_duration_hours"]
        country_parts.append(
            chunk.groupby(
                ["scenario", "region", "tech", "snapshot_year", "event"], as_index=False
            ).agg(
                net_loss_mwh=("net_generation_loss_mwh", "sum"),
                gross_loss_mwh=("generation_loss_mwh", "sum"),
                normal_event_mwh=("normal_generation_mwh", "sum"),
                normal_all_mwh=("normal_all_generation_mwh", "sum"),
                capacity_mw=("capacity_mw", "sum"),
                capacity_event_hours=("capacity_event_hours", "sum"),
                n_stations=("station_id", "nunique"),
            )
        )
        all_event = chunk[chunk["event"] == "all"].copy()
        station_parts.append(
            all_event[
                [
                    "scenario", "region", "tech", "snapshot_year", "station_id", "lon", "lat",
                    "capacity_mw", "net_generation_loss_mwh", "normal_all_generation_mwh",
                ]
            ]
        )
        print(f"已处理 chunk {index}")

    print(
        "[临时修正] 场站年代汇总：已将风电 "
        f"{', '.join(column for column in TEMP_WIND_ENERGY_COLUMNS if column in USECOLS)} "
        f"× {TEMP_WIND_ENERGY_SCALE_FACTOR:g} "
        f"（影响 {corrected_wind_rows} 行）；上游数据修复后请移除此修正。"
    )

    station = pd.concat(station_parts, ignore_index=True)
    station = (
        station.groupby(
            ["scenario", "region", "tech", "snapshot_year", "station_id", "lon", "lat"],
            as_index=False,
        )
        .agg(
            capacity_mw=("capacity_mw", "first"),
            net_loss_mwh=("net_generation_loss_mwh", "sum"),
            normal_all_mwh=("normal_all_generation_mwh", "sum"),
        )
    )
    station["loss_rate_pct"] = station["net_loss_mwh"] / station["normal_all_mwh"] * 100.0

    country = pd.concat(country_parts, ignore_index=True)
    country = (
        country.groupby(["scenario", "region", "tech", "snapshot_year", "event"], as_index=False)
        .sum(numeric_only=True)
    )
    country["loss_rate_pct"] = country["net_loss_mwh"] / country["normal_all_mwh"] * 100.0
    country["exposure_days_per_year"] = (
        country["capacity_event_hours"] / country["capacity_mw"] / 24.0 / 5.0
    )

    station.to_csv(station_out, index=False)
    country.to_csv(country_out, index=False)
    print(f"已保存：{station_out}（{len(station)} 行）")
    print(f"已保存：{country_out}（{len(country)} 行）")
    return station_out, country_out


def main() -> None:
    parser = add_common_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--force", action="store_true", help="强制重建 source-data。")
    args = parser.parse_args()
    prepare(args.model, output_dir(args.model, args.output_dir), args.force)


if __name__ == "__main__":
    main()
