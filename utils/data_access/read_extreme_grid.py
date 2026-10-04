"""Locate published BCSD-v2 grid extreme-event signals and baselines."""
from __future__ import annotations

from pathlib import Path
import re

try:
    from ._common import load_json, matches, open_record, overlaps, resolve_path, run_cli
except ImportError:
    from _common import load_json, matches, open_record, overlaps, resolve_path, run_cli


DEFAULT_ROOT = Path("/work/home/acjpoxgsdu/extreme_grid/extreme_grid_v2")


def find_records(root=DEFAULT_ROOT, *, model=None, climate_scenario=None,
                 station_scenario=None, patch=None, tech=None, years=None,
                 kind=None, snapshot_year=None):
    """Return indexed files without opening arrays or scanning output directories.

    ``years`` is an inclusive (first, last) pair. The default kind is ``signals``;
    pass ``kind="baseline"`` to locate the fixed 2015–2024 resource baseline.
    A published grid index may omit status; explicit unfinished statuses fail.
    """
    if station_scenario is not None or snapshot_year is not None:
        raise ValueError("grid extreme events have no station scenario or snapshot year")
    kinds = [kind] if isinstance(kind, str) else list(kind or ["signals"])
    if not kinds or set(kinds) - {"signals", "baseline"}:
        raise ValueError("kind must be signals or baseline")
    root = Path(root).expanduser()
    index_path = root / "runtime" / "authoritative_index.json"
    index = load_json(index_path)
    if index.get("kind") != "grid-v2-unified-index" or index.get("schema_version") != 1:
        raise ValueError(f"expected grid-v2-unified-index schema_version=1: {index_path}")
    if index.get("status", "COMPLETED") != "COMPLETED":
        raise ValueError(f"grid extreme index is not COMPLETED: {index_path}")
    combinations = index.get("combinations")
    if not isinstance(combinations, dict):
        raise ValueError(f"index combinations must be an object: {index_path}")
    records = []
    for key, combination in sorted(combinations.items()):
        if not isinstance(combination, dict) or any(
            not isinstance(combination.get(name), str) or not combination[name]
            for name in ("model", "scenario", "patch", "tech")
        ):
            raise ValueError(f"invalid grid extreme combination: {key}")
        if not all((matches(combination["model"], model),
                    matches(combination["scenario"], climate_scenario),
                    matches(combination["patch"], patch),
                    matches(combination["tech"], tech))):
            continue
        if combination.get("status", "COMPLETED") != "COMPLETED":
            raise ValueError(f"grid extreme combination is not COMPLETED: {key}")
        artifacts = combination.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError(f"grid extreme combination has no artifacts: {key}")
        for artifact in artifacts:
            if not isinstance(artifact, dict) or "stage" not in artifact:
                raise ValueError(f"invalid grid extreme artifact: {key}")
            if artifact["stage"] not in kinds:
                continue
            if artifact.get("status", "COMPLETED") != "COMPLETED":
                raise ValueError(f"grid extreme artifact is not COMPLETED: {key}")
            period = artifact.get("years", "")
            if not isinstance(period, str) or not re.fullmatch(r"\d{4}-\d{4}", period):
                raise ValueError(f"invalid grid extreme artifact years: {key}: {period!r}")
            start, end = map(int, period.split("-"))
            if not 1 <= start <= end <= 9998:
                raise ValueError(f"invalid grid extreme artifact years: {key}: {period!r}")
            if not overlaps(start, end, years):
                continue
            value = artifact.get("unified_output") or artifact.get("output")
            if not isinstance(value, str) or not value:
                raise ValueError(f"grid extreme artifact lacks an output path: {key}")
            records.append({
                "dataset": "extreme_grid", "model": combination["model"],
                "climate_scenario": combination["scenario"], "station_scenario": None,
                "patch": combination["patch"], "tech": combination["tech"],
                "kind": artifact["stage"], "start_year": start, "end_year": end,
                "path": str(resolve_path(value, root)), "status": "COMPLETED",
                "identity": artifact.get("identity"), "index": str(index_path),
            })
    return sorted(records, key=lambda r: (r["model"], r["climate_scenario"], r["patch"],
                                         r["tech"], r["kind"], r["start_year"], r["path"]))


if __name__ == "__main__":
    run_cli(find_records, DEFAULT_ROOT, "extreme_grid", kinds=("signals", "baseline"))
