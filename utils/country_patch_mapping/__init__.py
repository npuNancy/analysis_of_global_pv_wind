"""全球 country / patch / station 静态映射。"""

from .mapping import (
    capacity_summary,
    country_names,
    load_station_mapping,
    normalize_country,
    normalize_scenario,
    patch_for_point,
    patch_info,
    patches_for_country,
    stations_for_country,
)

__all__ = [
    "capacity_summary",
    "country_names",
    "load_station_mapping",
    "normalize_country",
    "normalize_scenario",
    "patch_for_point",
    "patch_info",
    "patches_for_country",
    "stations_for_country",
]
