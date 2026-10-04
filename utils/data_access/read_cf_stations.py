"""Locate published BCSD-v2 climate-SSP × station-SSP CF blocks."""
from __future__ import annotations

from pathlib import Path
import re

try:
    from ._common import load_json, matches, open_record, overlaps, resolve_path, run_cli
except ImportError:
    from _common import load_json, matches, open_record, overlaps, resolve_path, run_cli


DEFAULT_ROOT = "/work/home/acjpoxgsdu/cf_stations/cf_stations_v2"
DATASET = "cf_stations"


def _records(entry, context, root):
    status = entry["status"]
    blocks = entry["blocks"]
    if not isinstance(blocks, list):
        raise ValueError(f"CF station blocks must be a list: {context}")
    if status == "EMPTY_NO_STATIONS":
        if entry["station_count"] != 0 or blocks:
            raise ValueError(f"Invalid EMPTY_NO_STATIONS CF entry: {context}")
        return []
    if status != "COMPLETED" or not blocks or entry["station_count"] <= 0:
        raise ValueError(f"CF station entry is not complete: {context}")
    coverage = re.fullmatch(r"(\d{4})-(\d{4})", entry["years"])
    if coverage is None:
        raise ValueError(f"Invalid station CF year range: {context}")
    manifest = resolve_path(entry["manifest"]["path"], root)
    ordered = sorted(blocks, key=lambda block: block["index"])
    if [b["index"] for b in ordered] != list(range(len(ordered))):
        raise ValueError(f"Missing or duplicate station CF block indices: {context}")
    records = []
    for block in ordered:
        if block.get("status") != "COMPLETED":
            raise ValueError(f"Station CF block is not COMPLETED: {context}, block {block['index']}")
        path = resolve_path(block["path"], root)
        # Published station block entries omit years; their indexed names retain them.
        span = re.fullmatch(r"cf_(\d{4})-(\d{4})\.nc", path.name)
        if span is None:
            raise ValueError(f"Cannot read station CF block years from indexed path: {path}")
        start, end = map(int, span.groups())
        if start > end or (records and start != records[-1]["end_year"] + 1):
            raise ValueError(f"Gap, overlap or invalid station CF block years: {path}")
        for field, value in (("start_year", start), ("end_year", end)):
            if field in block and block[field] != value:
                raise ValueError(f"Station CF {field} disagrees with indexed filename: {path}")
        records.append({"dataset": DATASET, **context, "kind": "cf",
                        "start_year": start, "end_year": end, "path": str(path),
                        "status": "COMPLETED", "manifest": str(manifest),
                        "identity": block["identity"], "block_index": block["index"],
                        "station_count": entry["station_count"]})
    if (records[0]["start_year"], records[-1]["end_year"]) != tuple(map(int, coverage.groups())):
        raise ValueError(f"Station CF blocks do not cover declared years: {context}")
    return records


def find_records(root=DEFAULT_ROOT, *, model=None, climate_scenario=None,
                 station_scenario=None, patch=None, tech=None, years=None,
                 kind=None, snapshot_year=None):
    """Query the authoritative index; omit legitimate EMPTY_NO_STATIONS entries.

    Climate and station scenarios are independent filters. Years select overlapping
    blocks; use ``open_record(..., years=...)`` to crop values within each block.
    Relative metadata paths are resolved against the data root.
    """
    if snapshot_year is not None:
        raise ValueError("Station CF has no capacity snapshot axis")
    if years is not None:
        overlaps(0, 9999, years)
    if not matches("cf", kind):
        return []
    root = Path(root).expanduser()
    index_path = root / "index" / "authoritative_index.json"
    index = load_json(index_path)
    if index.get("status") != "COMPLETED":
        raise ValueError(f"Station CF authoritative index is not COMPLETED: {index_path}")
    entries = index["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Station CF authoritative index has no entries: {index_path}")
    wanted = dict(model=model, climate_scenario=climate_scenario,
                  station_scenario=station_scenario, patch=patch, tech=tech)
    records, seen = [], set()
    for entry in entries:
        context = {key: entry["source_patch" if key == "patch" else key] for key in wanted}
        if not all(matches(context[key], value) for key, value in wanted.items()):
            continue
        key = tuple(context.values())
        if key in seen:
            raise ValueError(f"Duplicate station CF index entry: {context}")
        seen.add(key)
        rows = _records(entry, context, root)
        records.extend(r for r in rows if overlaps(r["start_year"], r["end_year"], years))
    return sorted(records, key=lambda r: (r["model"], r["climate_scenario"],
                                        r["station_scenario"], r["patch"],
                                        r["tech"], r["block_index"]))


if __name__ == "__main__":
    run_cli(find_records, DEFAULT_ROOT, DATASET, station=True)
