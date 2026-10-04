"""Locate published Climate × Station extreme-event shards from their index."""
from __future__ import annotations

from pathlib import Path
import re

try:
    from ._common import load_json, matches, open_record, overlaps, resolve_path, run_cli
except ImportError:
    from _common import load_json, matches, open_record, overlaps, resolve_path, run_cli


DEFAULT_ROOT = Path("/work/home/acjpoxgsdu/extreme_stations_new/extreme_stations_v2")


def find_records(root=DEFAULT_ROOT, *, model=None, climate_scenario=None,
                 station_scenario=None, patch=None, tech=None, years=None,
                 kind=None, snapshot_year=None):
    """Return completed shards selected by Climate, Station, source patch and years.

    ``years`` is an inclusive (first, last) pair. Only authoritative index entries
    are used; attempt directories may contain incomplete or superseded files.
    Legitimate ``SKIPPED_NO_STATIONS`` combinations return no records.
    """
    if snapshot_year is not None:
        raise ValueError("station extreme events have no capacity snapshot year")
    kinds = [kind] if isinstance(kind, str) else list(kind or ["signals"])
    if kinds != ["signals"]:
        raise ValueError("station extreme events only contain kind=signals")
    root = Path(root).expanduser()
    index_path = root / "runtime" / "authoritative_index.json"
    index = load_json(index_path)
    if index.get("kind") != "station-event-index" or index.get("schema") != "station-extreme-v2":
        raise ValueError(f"expected station-event-index schema=station-extreme-v2: {index_path}")
    if index.get("status", "COMPLETED") != "COMPLETED":
        raise ValueError(f"station extreme index is not COMPLETED: {index_path}")
    combinations = index.get("combinations")
    if not isinstance(combinations, dict):
        raise ValueError(f"index combinations must be an object: {index_path}")
    records = []
    for key, combination in sorted(combinations.items()):
        if not isinstance(combination, dict) or any(
            not isinstance(combination.get(name), str) or not combination[name]
            for name in ("model", "climate_scenario", "station_scenario", "patch", "tech")
        ):
            raise ValueError(f"invalid station extreme combination: {key}")
        if not all((matches(combination["model"], model),
                    matches(combination["climate_scenario"], climate_scenario),
                    matches(combination["station_scenario"], station_scenario),
                    matches(combination["patch"], patch), matches(combination["tech"], tech))):
            continue
        outputs = combination.get("outputs")
        if not isinstance(outputs, list):
            raise ValueError(f"station extreme outputs must be a list: {key}")
        status = combination.get("status")
        if status == "SKIPPED_NO_STATIONS":
            if outputs:
                raise ValueError(f"SKIPPED_NO_STATIONS combination has unexpected outputs: {key}")
            continue
        if status != "COMPLETED":
            raise ValueError(f"station extreme combination is not COMPLETED: {key}")
        if not outputs:
            raise ValueError(f"COMPLETED station extreme combination has no outputs: {key}")
        for output in outputs:
            if not isinstance(output, dict) or output.get("status") != "COMPLETED":
                raise ValueError(f"station extreme output is not COMPLETED: {key}")
            period = output.get("period", "")
            if not isinstance(period, str) or not re.fullmatch(r"\d{4}-\d{4}", period):
                raise ValueError(f"invalid station extreme output period: {key}: {period!r}")
            start, end = map(int, period.split("-"))
            if not 1 <= start <= end <= 9998:
                raise ValueError(f"invalid station extreme output period: {key}: {period!r}")
            if not overlaps(start, end, years):
                continue
            artifact = output.get("artifact")
            value = artifact.get("path") if isinstance(artifact, dict) else None
            if not isinstance(value, str) or not value:
                raise ValueError(f"station extreme output lacks artifact.path: {key}")
            records.append({
                "dataset": "extreme_stations", "model": combination["model"],
                "climate_scenario": combination["climate_scenario"],
                "station_scenario": combination["station_scenario"],
                "patch": combination["patch"], "tech": combination["tech"],
                "kind": "signals", "start_year": start, "end_year": end,
                "path": str(resolve_path(value, root)), "status": "COMPLETED",
                "identity": output.get("identity"),
                "mapping_identity": combination.get("mapping_identity"),
                "index": str(index_path),
            })
    return sorted(records, key=lambda r: (r["model"], r["climate_scenario"],
                                         r["station_scenario"], r["patch"], r["tech"],
                                         r["start_year"], r["path"]))


if __name__ == "__main__":
    run_cli(find_records, DEFAULT_ROOT, "extreme_stations", station=True, kinds=("signals",))
