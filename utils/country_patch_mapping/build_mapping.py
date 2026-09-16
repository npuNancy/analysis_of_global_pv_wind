#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建全球场站、国家和 global_bcsd patch 的静态映射文件。

输出文件是可直接用于后续分析的硬编码快照。脚本本身保留在输出目录中，
当场站数据或 Natural Earth 数据更新时可以重新运行生成同样结构的文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
import shapefile
from shapely.geometry import box, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = Path(__file__).resolve().parent / "generated"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bcsd.global_bcsd.patches import PATCH_DICT, REMOVED_PATCHES, patch_bbox


DEFAULT_STATIONS = ROOT / "data" / "stations"
DEFAULT_NATURAL_EARTH = (
    ROOT / "data" / "maps" / "natural_earth" / "ne_110m_admin_0_countries.shp"
)
CHUNK_SIZE = 200_000
NEAREST_FALLBACK_MAX_DISTANCE_DEG = 2.5
SCENARIO_FILES = {
    "ssp126": "stations_SSP1-2.6.csv",
    "ssp245": "stations_SSP2-4.5.csv",
    "ssp585": "stations_SSP5-6.0.csv",
}
STATION_COLUMNS = ["year", "type", "lon", "lat", "capacity_gw"]
OUTPUT_COLUMNS = STATION_COLUMNS + [
    "source_row",
    "station_key",
    "lon_180",
    "country",
    "country_en",
    "country_iso3",
    "country_match_method",
    "country_match_distance_deg",
    "natural_earth_name",
    "natural_earth_iso3",
    "patch_id",
    "raw_patch_id",
    "patch_active",
]


@dataclass(frozen=True)
class CountryRecord:
    """Natural Earth 的一条 admin-0 记录。"""

    order: int
    name: str
    name_en: str
    name_zh: str
    name_zht: str
    admin: str
    sovereign: str
    iso2: str
    iso3: str
    geom: Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_alias(value: Any) -> str:
    """用于国家/情景别名匹配的 Unicode 不区分大小写键。"""
    text = str(value).strip().casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def load_country_records(shp_path: Path) -> list[CountryRecord]:
    reader = shapefile.Reader(str(shp_path), encoding="utf-8")
    records: list[CountryRecord] = []
    for order, item in enumerate(reader.iterShapeRecords()):
        fields = item.record.as_dict()
        geometry = shape(item.shape.__geo_interface__)
        if geometry.is_empty:
            continue
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        records.append(
            CountryRecord(
                order=order,
                name=str(fields.get("NAME") or ""),
                name_en=str(fields.get("NAME_EN") or ""),
                name_zh=str(fields.get("NAME_ZH") or ""),
                name_zht=str(fields.get("NAME_ZHT") or ""),
                admin=str(fields.get("ADMIN") or ""),
                sovereign=str(fields.get("SOVEREIGNT") or ""),
                iso2=str(fields.get("ISO_A2") or ""),
                iso3=str(fields.get("ISO_A3") or ""),
                geom=geometry,
            )
        )
    if not records:
        raise ValueError(f"Natural Earth 文件没有可用几何：{shp_path}")
    return records


def canonical_country(record: CountryRecord) -> str:
    """把台湾归入中国，其余沿用 Natural Earth 的 NAME。"""
    return "China" if record.name == "Taiwan" else record.name


def canonical_metadata(records: list[CountryRecord]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[CountryRecord]] = defaultdict(list)
    for record in records:
        grouped[canonical_country(record)].append(record)

    result: dict[str, dict[str, Any]] = {}
    for country, members in sorted(grouped.items()):
        primary = next((item for item in members if item.name == country), members[0])
        result[country] = {
            "country": country,
            "country_en": primary.name_en,
            "country_zh": primary.name_zh,
            "country_zht": primary.name_zht,
            "country_iso3": "CHN" if country == "China" else primary.iso3,
            "natural_earth_names": [item.name for item in members],
            "natural_earth_iso3": [item.iso3 for item in members],
        }
    return result


def build_country_aliases(
    records: list[CountryRecord], metadata: dict[str, dict[str, Any]]
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for record in records:
        target = canonical_country(record)
        for value in (
            record.name,
            record.name_en,
            record.name_zh,
            record.name_zht,
            record.admin,
            record.sovereign,
            record.iso2,
            record.iso3,
        ):
            if value and value not in {"-99", "None"}:
                aliases[normalize_alias(value)] = target
    for country, item in metadata.items():
        for value in (country, item["country_en"], item["country_zh"], item["country_zht"]):
            if value:
                aliases[normalize_alias(value)] = country

    # Natural Earth 110m 的字段已有绝大多数别名，这些是分析中常用的补充写法。
    explicit = {
        "中国": "China",
        "中华人民共和国": "China",
        "prc": "China",
        "台湾": "China",
        "中华民国": "China",
        "美国": "United States of America",
        "united states": "United States of America",
        "us": "United States of America",
        "usa": "United States of America",
        "英国": "United Kingdom",
        "uk": "United Kingdom",
        "britain": "United Kingdom",
        "俄罗斯": "Russia",
        "韩国": "South Korea",
        "北韩": "North Korea",
        "朝鲜": "North Korea",
        "日本": "Japan",
        "印度": "India",
        "德国": "Germany",
        "法国": "France",
        "澳大利亚": "Australia",
        "加拿大": "Canada",
        "巴西": "Brazil",
    }
    for key, value in explicit.items():
        if value in metadata:
            aliases[normalize_alias(key)] = value
    return dict(sorted(aliases.items()))


def patch_payload() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for patch_id, raw_bbox in PATCH_DICT.items():
        lon_w, lon_e, lat_s, lat_n = patch_bbox(patch_id)
        result[patch_id] = {
            "bbox_lat_n_lon_w_lat_s_lon_e": [float(v) for v in raw_bbox],
            "bbox_lon_w_lon_e_lat_s_lat_n": [lon_w, lon_e, lat_s, lat_n],
            "active": patch_id not in REMOVED_PATCHES,
        }
    return result


def patch_id_for_points(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按 global_bcsd 的左闭右开核心区规则计算 patch。"""
    lon_display = ((lon + 180.0) % 360.0) - 180.0
    col = np.floor((lon_display + 180.0) / 30.0).astype(np.int16) + 1
    # 纬度下边界包含在当前块中；90°和浮点边界分别做裁剪。
    row = np.ceil((90.0 - lat) / 30.0).astype(np.int16)
    row = np.clip(row, 1, 6)
    raw = np.array([f"R{r:02d}C{c:02d}" for r, c in zip(row, col)], dtype=object)
    active = np.array([item not in REMOVED_PATCHES for item in raw], dtype=bool)
    active_patch = raw.copy()
    active_patch[~active] = ""
    return active_patch, raw, active


def assign_points(
    lon: np.ndarray, lat: np.ndarray, records: list[CountryRecord]
) -> dict[str, np.ndarray]:
    """给一批不重复的场站坐标分配国家和 patch。"""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon_display = ((lon + 180.0) % 360.0) - 180.0
    countries = np.full(len(lon), "UNMAPPED", dtype=object)
    country_en = np.full(len(lon), "UNMAPPED", dtype=object)
    country_iso3 = np.full(len(lon), "", dtype=object)
    country_match_method = np.full(len(lon), "UNMAPPED", dtype=object)
    country_match_distance = np.full(len(lon), np.nan, dtype=float)
    ne_name = np.full(len(lon), "", dtype=object)
    ne_iso3 = np.full(len(lon), "", dtype=object)

    geometries = [item.geom for item in records]
    tree = STRtree(geometries)
    points = shapely.points(lon_display, lat)
    pairs = tree.query(points, predicate="covered_by")
    assigned = np.full(len(lon), -1, dtype=np.int32)
    # 极少数争议边界可能返回多个候选；优先较小几何，再按文件顺序稳定打破平局。
    areas = np.array([max(float(item.geom.area), 0.0) for item in records])
    for point_index, geometry_index in zip(pairs[0], pairs[1]):
        point_index = int(point_index)
        geometry_index = int(geometry_index)
        old = assigned[point_index]
        if old < 0 or areas[geometry_index] < areas[old]:
            assigned[point_index] = geometry_index

    for index in np.flatnonzero(assigned >= 0):
        item = records[int(assigned[index])]
        countries[index] = canonical_country(item)
        country_en[index] = item.name_en if item.name != "Taiwan" else "People's Republic of China"
        country_iso3[index] = "CHN" if item.name == "Taiwan" else item.iso3
        country_match_method[index] = "polygon"
        country_match_distance[index] = 0.0
        ne_name[index] = item.name
        ne_iso3[index] = item.iso3

    # Natural Earth 110m 对小岛和海岸线的表示较粗，部分由高分辨率土地掩膜产生的
    # 场站点会落在其多边形外。用最近边界做透明回退，避免国家场站汇总漏项。
    missing = np.flatnonzero(assigned < 0)
    if len(missing):
        nearest_pairs, distances = tree.query_nearest(
            points[missing], return_distance=True, all_matches=False
        )
        for local_index, geometry_index, distance in zip(
            nearest_pairs[0], nearest_pairs[1], distances
        ):
            point_index = int(missing[int(local_index)])
            geometry_index = int(geometry_index)
            distance = float(distance)
            if distance > NEAREST_FALLBACK_MAX_DISTANCE_DEG:
                continue
            item = records[geometry_index]
            countries[point_index] = canonical_country(item)
            country_en[point_index] = (
                item.name_en if item.name != "Taiwan" else "People's Republic of China"
            )
            country_iso3[point_index] = "CHN" if item.name == "Taiwan" else item.iso3
            country_match_method[point_index] = "nearest_boundary"
            country_match_distance[point_index] = distance
            ne_name[point_index] = item.name
            ne_iso3[point_index] = item.iso3

    patch, raw_patch, patch_active = patch_id_for_points(lon, lat)
    return {
        "lon_180": lon_display,
        "country": countries,
        "country_en": country_en,
        "country_iso3": country_iso3,
        "country_match_method": country_match_method,
        "country_match_distance_deg": country_match_distance,
        "natural_earth_name": ne_name,
        "natural_earth_iso3": ne_iso3,
        "patch_id": patch,
        "raw_patch_id": raw_patch,
        "patch_active": patch_active,
    }


def unique_coordinates(csv_path: Path) -> np.ndarray:
    values: set[tuple[float, float]] = set()
    for chunk in pd.read_csv(csv_path, usecols=["lon", "lat"], chunksize=CHUNK_SIZE):
        values.update(zip(chunk["lon"].astype(float), chunk["lat"].astype(float)))
    return np.asarray(sorted(values), dtype=float)


def rows_with_mapping(
    chunk: pd.DataFrame,
    scenario: str,
    source_row_start: int,
    coordinate_map: dict[tuple[float, float], tuple[Any, ...]],
) -> pd.DataFrame:
    keys = list(zip(chunk["lon"].astype(float), chunk["lat"].astype(float)))
    info = [coordinate_map[key] for key in keys]
    mapped = pd.DataFrame(
        info,
        columns=[
            "lon_180",
            "country",
            "country_en",
            "country_iso3",
            "country_match_method",
            "country_match_distance_deg",
            "natural_earth_name",
            "natural_earth_iso3",
            "patch_id",
            "raw_patch_id",
            "patch_active",
        ],
        index=chunk.index,
    )
    result = chunk[STATION_COLUMNS].copy()
    result["source_row"] = np.arange(source_row_start, source_row_start + len(chunk))
    result["station_key"] = (
        scenario
        + ":"
        + result["type"].astype(str)
        + ":"
        + result["lon"].map(lambda value: f"{float(value):.4f}")
        + ":"
        + result["lat"].map(lambda value: f"{float(value):.4f}")
    )
    for column in mapped.columns:
        result[column] = mapped[column].to_numpy()
    return result[OUTPUT_COLUMNS]


def aggregate_chunk(mapped: pd.DataFrame, by_patch: bool) -> pd.DataFrame:
    columns = ["country", "country_iso3", "year", "type"]
    if by_patch:
        columns.append("patch_id")
    return (
        mapped.groupby(columns, dropna=False, sort=False)
        .agg(station_count=("capacity_gw", "size"), capacity_gw=("capacity_gw", "sum"))
        .reset_index()
    )


def build_station_files(
    output_dir: Path,
    stations_dir: Path,
    records: list[CountryRecord],
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for scenario, filename in SCENARIO_FILES.items():
        input_path = stations_dir / filename
        if not input_path.exists():
            raise FileNotFoundError(input_path)
        print(f"[构建] {scenario}: 收集坐标 {input_path}")
        coords = unique_coordinates(input_path)
        assigned = assign_points(coords[:, 0], coords[:, 1], records)
        coordinate_map = {
            (float(lon), float(lat)): tuple(values[index] for values in assigned.values())
            for index, (lon, lat) in enumerate(coords)
        }

        station_output = output_dir / f"stations_{scenario}.csv"
        patch_parts: list[pd.DataFrame] = []
        country_parts: list[pd.DataFrame] = []
        row_start = 1
        first = True
        total_rows = 0
        with station_output.open("w", encoding="utf-8", newline="") as handle:
            for chunk in pd.read_csv(input_path, chunksize=CHUNK_SIZE):
                mapped = rows_with_mapping(chunk, scenario, row_start, coordinate_map)
                mapped.to_csv(
                    handle,
                    index=False,
                    header=first,
                    float_format="%.10g",
                    lineterminator="\n",
                )
                first = False
                row_start += len(mapped)
                total_rows += len(mapped)
                patch_parts.append(aggregate_chunk(mapped, by_patch=True))
                country_parts.append(aggregate_chunk(mapped, by_patch=False))

        patch_summary = (
            pd.concat(patch_parts, ignore_index=True)
            .groupby(["country", "country_iso3", "year", "type", "patch_id"], dropna=False)
            .agg(station_count=("station_count", "sum"), capacity_gw=("capacity_gw", "sum"))
            .reset_index()
            .sort_values(["country", "year", "type", "patch_id"], na_position="first")
        )
        country_summary = (
            pd.concat(country_parts, ignore_index=True)
            .groupby(["country", "country_iso3", "year", "type"], dropna=False)
            .agg(station_count=("station_count", "sum"), capacity_gw=("capacity_gw", "sum"))
            .reset_index()
            .sort_values(["country", "year", "type"])
        )
        patch_path = output_dir / f"country_patch_capacity_{scenario}.csv"
        country_path = output_dir / f"country_capacity_summary_{scenario}.csv"
        patch_summary.to_csv(patch_path, index=False, float_format="%.10g", lineterminator="\n")
        country_summary.to_csv(country_path, index=False, float_format="%.10g", lineterminator="\n")
        unmapped = int((assigned["country"] == "UNMAPPED").sum())
        inactive_patch_rows = int((~assigned["patch_active"]).sum())
        summaries[scenario] = {
            "source_file": str(input_path.relative_to(ROOT)),
            "source_sha256": sha256(input_path),
            "mapping_file": station_output.name,
            "country_capacity_file": country_path.name,
            "country_patch_capacity_file": patch_path.name,
            "row_count": total_rows,
            "unique_coordinate_count": int(len(coords)),
            "unmapped_unique_coordinate_count": unmapped,
            "inactive_patch_unique_coordinate_count": inactive_patch_rows,
        }
        print(
            f"[完成] {scenario}: {total_rows:,} 行, {len(coords):,} 个坐标, "
            f"未匹配国家 {unmapped:,}, 无效 patch {inactive_patch_rows:,}"
        )
    return summaries


def country_patch_rows(
    records: list[CountryRecord],
    metadata: dict[str, dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    output_dir: Path,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    canonical_geometries: dict[str, Any] = {}
    for country in metadata:
        members = [item.geom for item in records if canonical_country(item) == country]
        canonical_geometries[country] = unary_union(members)

    active_patch_ids = [item for item in PATCH_DICT if item not in REMOVED_PATCHES]
    geometry_patches: dict[str, list[str]] = {}
    for country, geometry in canonical_geometries.items():
        geometry_patches[country] = []
        for patch_id in active_patch_ids:
            lon_w, lon_e, lat_s, lat_n = patch_bbox(patch_id)
            if geometry.intersects(box(lon_w, lat_s, lon_e, lat_n)):
                geometry_patches[country].append(patch_id)

    station_patches: dict[str, dict[str, list[str]]] = {
        scenario: defaultdict(list) for scenario in SCENARIO_FILES
    }
    station_counts: dict[tuple[str, str], int] = defaultdict(int)
    station_capacities: dict[tuple[str, str], float] = defaultdict(float)
    for scenario in SCENARIO_FILES:
        path = output_dir / summaries[scenario]["country_patch_capacity_file"]
        table = pd.read_csv(path)
        table = table[table["patch_id"].notna() & (table["country"] != "UNMAPPED")]
        for country, group in table.groupby("country", sort=False):
            station_patches[scenario][str(country)] = sorted(group["patch_id"].astype(str).unique())
        for row in table.itertuples(index=False):
            key = (str(row.country), str(row.patch_id))
            station_counts[key] += int(row.station_count)
            station_capacities[key] += float(row.capacity_gw)

    rows: list[dict[str, Any]] = []
    for country, item in metadata.items():
        all_patches = sorted(
            set(geometry_patches[country])
            | {
                patch
                for scenario in SCENARIO_FILES
                for patch in station_patches[scenario].get(country, [])
            }
        )
        for patch_id in all_patches:
            row: dict[str, Any] = {
                "country": country,
                "country_en": item["country_en"],
                "country_iso3": item["country_iso3"],
                "patch_id": patch_id,
                "geometry_intersects": patch_id in geometry_patches[country],
            }
            for scenario in SCENARIO_FILES:
                row[f"station_observed_{scenario}"] = patch_id in station_patches[scenario].get(country, [])
                row[f"station_count_{scenario}"] = station_counts.get((country, patch_id), 0)
                row[f"capacity_gw_{scenario}"] = station_capacities.get((country, patch_id), 0.0)
            rows.append(row)
    table = pd.DataFrame(rows).sort_values(["country", "patch_id"])
    table.to_csv(output_dir / "country_patch_mapping.csv", index=False, float_format="%.10g", lineterminator="\n")

    json_countries: dict[str, dict[str, Any]] = {}
    for country, item in metadata.items():
        json_countries[country] = {
            **item,
            "geometry_patches": geometry_patches[country],
            "station_patches": {
                scenario: station_patches[scenario].get(country, []) for scenario in SCENARIO_FILES
            },
        }
    return table, json_countries


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations-dir", type=Path, default=DEFAULT_STATIONS)
    parser.add_argument("--natural-earth", type=Path, default=DEFAULT_NATURAL_EARTH)
    parser.add_argument("--output-dir", type=Path, default=GENERATED_DIR)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_country_records(args.natural_earth)
    metadata = canonical_metadata(records)
    aliases = build_country_aliases(records, metadata)
    summaries = build_station_files(output_dir, args.stations_dir.resolve(), records)
    country_table, json_countries = country_patch_rows(records, metadata, summaries, output_dir)

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "coordinate_convention": {
            "station_input_longitude": "[0, 360)",
            "natural_earth_longitude": "[-180, 180]",
            "station_lon_180": "((lon + 180) % 360) - 180",
            "patch_boundary": "30°×30° 核心区，纬度下边界包含、上边界不包含；经度左闭右开",
            "country_assignment": "Natural Earth admin-0 点覆盖（covered_by）；多边形外坐标在阈值内使用最近边界回退，超出阈值才标记为 UNMAPPED",
            "nearest_fallback": f"多边形外坐标在 {NEAREST_FALLBACK_MAX_DISTANCE_DEG}° 内归入最近 Natural Earth 边界，并标记 country_match_method=nearest_boundary",
        },
        "china_rule": "canonical China = Natural Earth China + Taiwan; Taiwan station rows retain natural_earth_name=Taiwan",
        "patches": patch_payload(),
        "scenarios": summaries,
        "country_aliases": aliases,
        "countries": json_countries,
        "validation": {
            "natural_earth_record_count": len(records),
            "canonical_country_count": len(metadata),
            "country_patch_row_count": int(len(country_table)),
            "active_patch_count": int(sum(item not in REMOVED_PATCHES for item in PATCH_DICT)),
            "removed_patch_count": int(len(REMOVED_PATCHES)),
        },
        "sources": {
            "natural_earth_shapefile": str(args.natural_earth.resolve().relative_to(ROOT)),
            "natural_earth_sha256": sha256(args.natural_earth),
            "patch_definition": "bcsd/global_bcsd/patches.py",
        },
    }
    write_json(output_dir / "mapping.json", payload)
    write_json(
        output_dir / "patches.json",
        {
            "patches": patch_payload(),
            "active_patch_ids": [item for item in PATCH_DICT if item not in REMOVED_PATCHES],
            "removed_patch_ids": sorted(REMOVED_PATCHES),
        },
    )
    print(f"[完成] 国家数 {len(metadata)}，国家-patch 行数 {len(country_table)}")
    print(f"[输出] {output_dir}")


if __name__ == "__main__":
    main()
