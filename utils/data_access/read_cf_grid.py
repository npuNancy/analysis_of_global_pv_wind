"""Locate native-grid BCSD-v2 capacity-factor blocks in the authoritative index."""
from __future__ import annotations

from pathlib import Path
import re

try:
    from ._common import load_json, matches, open_record, overlaps, resolve_path, run_cli
except ImportError:
    from _common import load_json, matches, open_record, overlaps, resolve_path, run_cli


DEFAULT_ROOT = "/work/home/acjpoxgsdu/cf_grid/cf_grid_v2"
DATASET = "cf_grid"
INDEX_PATH = Path("runtime/authoritative_index.json")
INDEX_SCHEMA = "grid-cf-v1"


def _records(entry, root):
    context = {key: entry[key] for key in ("model", "climate_scenario", "patch", "tech")}
    manifest_path = resolve_path(entry["manifest"]["path"], root)
    if entry.get("status") != "COMPLETED":
        raise ValueError(f"CF index entry is not COMPLETED: {manifest_path}")
    if entry.get("merge_final") is not False:
        raise ValueError(f"Expected merge_final=false CF block entry: {manifest_path}")
    coverage = re.fullmatch(r"(\d{4})-(\d{4})", entry["years"])
    if coverage is None:
        raise ValueError(f"Invalid CF index year range: {manifest_path}")
    blocks = entry["blocks"]
    if not isinstance(blocks, list) or not blocks:
        raise ValueError(f"Completed CF manifest has no blocks: {manifest_path}")
    ordered = sorted(blocks, key=lambda block: block["index"])
    if [b["index"] for b in ordered] != list(range(len(ordered))):
        raise ValueError(f"Missing or duplicate CF block indices: {manifest_path}")
    records = []
    for block in ordered:
        if block.get("status") != "COMPLETED":
            raise ValueError(f"CF block is not COMPLETED: {manifest_path}, block {block['index']}")
        start, end = block["start_year"], block["end_year"]
        if type(start) is not int or type(end) is not int or start > end:
            raise ValueError(f"Invalid CF block years: {manifest_path}")
        if records and start != records[-1]["end_year"] + 1:
            raise ValueError(f"Gap or overlap between CF blocks: {manifest_path}")
        path = resolve_path(block["path"], root)
        if path.suffix != ".nc":
            raise ValueError(f"Invalid CF block path: {path}")
        records.append({"dataset": DATASET, **context, "station_scenario": None,
                        "kind": "cf", "start_year": start, "end_year": end,
                        "path": str(path), "status": "COMPLETED",
                        "manifest": str(manifest_path), "identity": entry["identity"],
                        "block_index": block["index"]})
    if (records[0]["start_year"], records[-1]["end_year"]) != tuple(map(int, coverage.groups())):
        raise ValueError(f"CF blocks do not cover declared years: {manifest_path}")
    return records


def find_records(root=DEFAULT_ROOT, *, model=None, climate_scenario=None,
                 station_scenario=None, patch=None, tech=None, years=None,
                 kind=None, snapshot_year=None):
    """Query runtime/authoritative_index.json without reopening task manifests.

    Relative paths in the unified index are relative to the run root. Years
    select overlapping blocks; open_record can crop the selected time values.
    """
    if station_scenario is not None or snapshot_year is not None:
        raise ValueError("Grid CF has no station scenario or capacity snapshot axis")
    if years is not None:
        overlaps(0, 9999, years)
    if not matches("cf", kind):
        return []
    root = Path(root).expanduser()
    index_path = root / INDEX_PATH
    if not index_path.is_file():
        raise FileNotFoundError(
            f"CF authoritative index does not exist: {index_path}; "
            "run build_cf_grid_index.py --root with this run root first"
        )
    index = load_json(index_path)
    if index.get("schema") != INDEX_SCHEMA or index.get("schema_version") != 1:
        raise ValueError(f"Expected {INDEX_SCHEMA} schema_version=1: {index_path}")
    if index.get("status") != "COMPLETED":
        raise ValueError(f"CF authoritative index is not COMPLETED: {index_path}")
    entries = index["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"CF authoritative index has no entries: {index_path}")
    if (index.get("combination_count") != len(entries)
            or index.get("file_count") != sum(len(entry["blocks"]) for entry in entries)):
        raise ValueError(f"CF authoritative index count mismatch: {index_path}")
    wanted = dict(model=model, climate_scenario=climate_scenario, patch=patch, tech=tech)
    records, seen = [], set()
    for entry in entries:
        context = {key: entry[key] for key in wanted}
        key = tuple(context.values())
        if key in seen:
            raise ValueError(f"Duplicate CF index entry: {context}")
        seen.add(key)
        if not all(matches(context[key], value) for key, value in wanted.items()):
            continue
        rows = _records(entry, root)
        for row in rows:
            if overlaps(row["start_year"], row["end_year"], years):
                records.append(dict(row, index=str(index_path)))
    return sorted(records, key=lambda row: (row["model"], row["climate_scenario"],
                                           row["patch"], row["tech"], row["block_index"]))


if __name__ == "__main__":
    run_cli(find_records, DEFAULT_ROOT, DATASET)
