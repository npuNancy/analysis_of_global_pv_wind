#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取静态全球 country/patch/station 映射的轻量查询接口。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DATA_DIR = Path(__file__).resolve().parent
MAPPING_JSON = DATA_DIR / "mapping.json"


@lru_cache(maxsize=1)
def _payload() -> dict:
    if not MAPPING_JSON.exists():
        raise FileNotFoundError(
            f"没有找到 {MAPPING_JSON}；请先运行 python {DATA_DIR / 'build_mapping.py'}"
        )
    return json.loads(MAPPING_JSON.read_text(encoding="utf-8"))


def _alias_key(value: object) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value).strip().casefold(), flags=re.UNICODE)


def normalize_scenario(value: object) -> str:
    """将常见 SSP 写法统一为 ``ssp126``、``ssp245`` 或 ``ssp585``。

    特别约定：``ssp560``/``SSP5-6.0`` 与 ``ssp585`` 使用同一套场站映射。
    """
    text = str(value).strip().casefold()
    match = re.search(r"ssp[^0-9]*([0-9])[^0-9]*([0-9])[^0-9]*([0-9])", text)
    digits = "".join(match.groups()) if match else "".join(re.findall(r"\d", text))[:3]
    aliases = {"126": "ssp126", "245": "ssp245", "585": "ssp585", "560": "ssp585"}
    try:
        return aliases[digits]
    except KeyError as exc:
        raise ValueError(
            f"无法识别 SSP 情景 {value!r}；支持 ssp126、ssp245、ssp585，且 ssp560=ssp585"
        ) from exc


def normalize_country(value: object) -> str:
    """把英文名、Natural Earth 名称、ISO2/ISO3 或常见中文名转为 canonical country。"""
    key = _alias_key(value)
    aliases = _payload()["country_aliases"]
    try:
        return aliases[key]
    except KeyError as exc:
        raise KeyError(f"无法识别国家/地区 {value!r}；可用 country_names() 查看名称") from exc


def country_names() -> list[str]:
    """返回 canonical country 名称。"""
    return sorted(_payload()["countries"])


def patch_for_point(lon: float, lat: float, *, include_removed: bool = False) -> str | None:
    """返回场站坐标所属的核心 patch。

    场站经度按 [0, 360) 解释；边界采用 global_bcsd 的纬度下边界包含、上边界不包含，
    经度左闭右开规则。落入生产中已移除的纯海 patch 时默认返回 ``None``。
    """
    lon_display = ((float(lon) + 180.0) % 360.0) - 180.0
    col = int(np.floor((lon_display + 180.0) / 30.0)) + 1
    row = int(np.ceil((90.0 - float(lat)) / 30.0))
    row = min(max(row, 1), 6)
    raw = f"R{row:02d}C{col:02d}"
    item = _payload()["patches"].get(raw)
    if item is None:
        raise ValueError(f"坐标 ({lon}, {lat}) 计算出未知 patch {raw}")
    if item["active"] or include_removed:
        return raw
    return None


def patch_info(patch_id: str) -> dict:
    """返回一个 patch 的边界与 active 状态。"""
    try:
        return dict(_payload()["patches"][patch_id])
    except KeyError as exc:
        raise KeyError(f"未知 patch {patch_id!r}") from exc


def patches_for_country(
    country: object,
    scenario: object | None = None,
    *,
    source: str = "geometry",
) -> list[str]:
    """返回国家所在 patch。

    ``source='geometry'`` 返回 Natural Earth 边界与 patch 核心区相交的结果；
    ``source='station'`` 返回对应 SSP 中实际出现过场站的 patch。
    """
    canonical = normalize_country(country)
    record = _payload()["countries"][canonical]
    if source == "geometry":
        return list(record["geometry_patches"])
    if source != "station":
        raise ValueError("source 只能是 'geometry' 或 'station'")
    if scenario is None:
        raise ValueError("source='station' 时必须提供 scenario")
    return list(record["station_patches"][normalize_scenario(scenario)])


def station_mapping_path(scenario: object) -> Path:
    """返回 SSP 场站逐行映射 CSV 路径。"""
    canonical = normalize_scenario(scenario)
    return DATA_DIR / _payload()["scenarios"][canonical]["mapping_file"]


def load_station_mapping(
    scenario: object,
    *,
    columns: Iterable[str] | None = None,
    usecols: Iterable[str] | None = None,
) -> pd.DataFrame:
    """读取一个 SSP 的逐行场站映射。默认读取全部列。"""
    if columns is not None and usecols is not None:
        raise ValueError("columns 与 usecols 不能同时提供")
    selected = list(columns if columns is not None else usecols) if (columns is not None or usecols is not None) else None
    return pd.read_csv(station_mapping_path(scenario), usecols=selected)


def stations_for_country(
    country: object,
    scenario: object,
    *,
    year: int | None = None,
    station_type: str | None = None,
    patch_id: str | None = None,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """读取并筛选某个国家的场站装机记录。"""
    canonical = normalize_country(country)
    requested = list(columns) if columns is not None else None
    required = {"country"}
    if year is not None:
        required.add("year")
    if station_type is not None:
        required.add("type")
    if patch_id is not None:
        required.add("patch_id")
    selected = None if requested is None else list(dict.fromkeys([*requested, *required]))
    table = load_station_mapping(scenario, columns=selected)
    table = table[table["country"] == canonical]
    if year is not None:
        table = table[table["year"] == int(year)]
    if station_type is not None:
        table = table[table["type"].astype(str).str.casefold() == str(station_type).casefold()]
    if patch_id is not None:
        table = table[table["patch_id"] == patch_id]
    if requested is not None:
        table = table[requested]
    return table.reset_index(drop=True)


def capacity_summary(country: object | None = None, scenario: object = "ssp126") -> pd.DataFrame:
    """读取按国家、年份和风光类型汇总的装机容量。"""
    path = DATA_DIR / _payload()["scenarios"][normalize_scenario(scenario)]["country_capacity_file"]
    table = pd.read_csv(path)
    if country is not None:
        table = table[table["country"] == normalize_country(country)]
    return table.reset_index(drop=True)


__all__ = [
    "capacity_summary",
    "country_names",
    "load_station_mapping",
    "normalize_country",
    "normalize_scenario",
    "patch_for_point",
    "patch_info",
    "patches_for_country",
    "station_mapping_path",
    "stations_for_country",
]
