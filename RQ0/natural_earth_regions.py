"""Natural Earth admin-0 country point-in-polygon helpers.

The project intentionally uses country names that mostly match Natural Earth
``NAME`` values, except for a few directory/display names such as ``México``.
This module keeps that mapping in one place and avoids bbox-based station
country assignment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_NE_SHP = PROJECT_ROOT / "data" / "maps" / "natural_earth" / "ne_110m_admin_0_countries.shp"

NE_NAME_MAP = {
    "México": "Mexico",
}


def _target_key(target_countries: tuple[str, ...] | list[str] | None) -> tuple[str, ...] | None:
    if target_countries is None:
        return None
    return tuple(target_countries)


@lru_cache(maxsize=16)
def _load_shapes_cached(shp_path: str, target_key: tuple[str, ...] | None):
    import fiona
    from shapely.geometry import shape
    from shapely.prepared import prep

    shp = Path(shp_path)
    if not shp.exists():
        raise FileNotFoundError(f"Natural Earth shapefile 不存在: {shp}")

    if target_key is None:
        target_by_ne_name = None
    else:
        target_by_ne_name = {NE_NAME_MAP.get(name, name): name for name in target_key}

    countries = []
    with fiona.open(shp) as src:
        for rec in src:
            ne_name = rec["properties"].get("NAME")
            if not ne_name or rec["geometry"] is None:
                continue
            if target_by_ne_name is not None and ne_name not in target_by_ne_name:
                continue
            out_name = target_by_ne_name[ne_name] if target_by_ne_name is not None else ne_name
            geom = shape(rec["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            minx, miny, maxx, maxy = geom.bounds
            countries.append(
                {
                    "name": out_name,
                    "ne_name": ne_name,
                    "geom": geom,
                    "prepared": prep(geom),
                    "bounds": (minx, miny, maxx, maxy),
                }
            )
    return tuple(countries)


def load_target_country_shapes(shp_path=DEFAULT_NE_SHP, target_countries=None):
    """Return cached Natural Earth geometries for target countries.

    ``target_countries`` controls both filtering and matching order. Returned
    records contain ``name``, ``geom``, ``prepared`` and ``bounds``.
    """

    return list(_load_shapes_cached(str(shp_path), _target_key(target_countries)))


def assign_countries(lon, lat, target_countries, shp_path=DEFAULT_NE_SHP, outside_label="outside"):
    """Assign points to Natural Earth countries.

    Points are tested with ``contains`` first and ``covers`` second for exact
    boundary cases. Returned labels use the project country names supplied in
    ``target_countries``.
    """

    from shapely.geometry import Point

    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    labels = np.array([outside_label] * len(lon), dtype=object)
    if len(lon) == 0:
        return labels

    finite = np.isfinite(lon) & np.isfinite(lat)
    if not finite.any():
        return labels

    shapes = load_target_country_shapes(shp_path, tuple(target_countries))
    for rec in shapes:
        undecided = (labels == outside_label) & finite
        if not undecided.any():
            break

        minx, miny, maxx, maxy = rec["bounds"]
        candidates = undecided & (lon >= minx) & (lon <= maxx) & (lat >= miny) & (lat <= maxy)
        if not candidates.any():
            continue

        idx = np.flatnonzero(candidates)
        points = [Point(float(lon[i]), float(lat[i])) for i in idx]
        prepared = rec["prepared"]
        hit = np.array([prepared.contains(pt) for pt in points], dtype=bool)

        if not hit.all():
            miss_pos = np.flatnonzero(~hit)
            if len(miss_pos):
                covered = np.array([rec["geom"].covers(points[i]) for i in miss_pos], dtype=bool)
                hit[miss_pos[covered]] = True

        labels[idx[hit]] = rec["name"]

    return labels


def points_in_target_countries(lon, lat, target_countries, shp_path=DEFAULT_NE_SHP):
    """Boolean mask: point falls in any Natural Earth target country."""

    return assign_countries(lon, lat, target_countries, shp_path=shp_path) != "outside"

