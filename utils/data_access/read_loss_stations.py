#!/usr/bin/env python3
"""Locate accepted station loss and baseline files through completion receipts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

if __package__:
    from ._common import load_json, matches, open_record, overlaps, resolve_path, run_cli
else:
    from _common import load_json, matches, open_record, overlaps, resolve_path, run_cli


DEFAULT_ROOT = Path("/work/home/acjpoxgsdu/generation_loss_stations/loss_stations_v2")
DATASET = "loss_stations"
_UNIT = re.compile(r"loss_(?P<model>.+)_c(?P<climate>\d+)_s(?P<station>\d+)_(?P<tech>wind|solar)_(?P<patch>R\d+C\d+)")
_BATCH = re.compile(r"stations_(\d+)_(\d+)")
_SUCCESS = {"COMPLETED", "SKIPPED_NO_STATIONS"}


def _verified_json(path: Path, digest: str) -> dict:
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"Missing or invalid SHA256: {path}")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != digest:
        raise ValueError(f"SHA256 mismatch: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _identity(unit_id: str) -> dict:
    matched = _UNIT.fullmatch(unit_id)
    if matched is None:
        raise ValueError(f"Invalid loss unit ID: {unit_id}")
    values = matched.groupdict()
    return {
        "model": values["model"],
        "climate_scenario": "ssp" + values["climate"],
        "station_scenario": "ssp" + values["station"],
        "patch": values["patch"],
        "tech": values["tech"],
    }


def _window(request: dict, snapshot: int) -> tuple[int, int]:
    if request.get("analysis_scheme") != "center-k":
        raise ValueError("Expected station loss analysis_scheme=center-k")
    k = request["analysis_k"]
    if not isinstance(k, int) or not 0 <= k <= 5:
        raise ValueError(f"Invalid analysis_k: {k}")
    return max(snapshot, snapshot + 5 - k), min(snapshot + 9, snapshot + 5 + k)


def _annual_paths(chunk: dict, identity: dict, snapshot: int, root: Path,
                  first: int, last: int) -> tuple[str, list[tuple[int, Path]]]:
    if not isinstance(chunk.get("station_count"), int) or chunk["station_count"] < 1:
        raise ValueError("A completed loss chunk must contain stations")
    paths = []
    batch_name = None
    for value in chunk["outputs"]:
        path = resolve_path(value, root)
        matched = re.fullmatch(rf"{identity['tech']}_generation_loss_station_(\d{{4}})\.nc", path.name)
        if matched is None:
            raise ValueError(f"Invalid annual loss filename: {path}")
        batch = path.parent.name
        batch_match = _BATCH.fullmatch(batch)
        if batch_match is None or int(batch_match[2]) - int(batch_match[1]) != chunk["station_count"]:
            raise ValueError(f"Invalid station batch: {path}")
        expected = Path("generation_loss") / identity["model"] / ("climate_" + identity["climate_scenario"]) / ("station_" + identity["station_scenario"]) / identity["patch"] / str(snapshot) / identity["tech"] / batch / path.name
        if len(path.parts) < len(expected.parts) or path.parts[-len(expected.parts):] != expected.parts:
            raise ValueError(f"Annual loss path identity mismatch: {path}")
        if batch_name is not None and batch != batch_name:
            raise ValueError("A station chunk declares multiple batch directories")
        batch_name = batch
        paths.append((int(matched[1]), path))
    if sorted(year for year, _ in paths) != list(range(first, last + 1)):
        raise ValueError(f"Incomplete or duplicate annual loss declarations: {identity}, {snapshot}")
    return batch_name, paths


def find_records(root=DEFAULT_ROOT, *, model=None, climate_scenario=None,
                 station_scenario=None, patch=None, tech=None, years=None,
                 kind=None, snapshot_year=None) -> list[dict]:
    """Return accepted file records without opening NetCDF arrays.

    ``years`` filters analysis years; ``snapshot_year`` filters capacity snapshots.
    Only receipts for selected units are opened. Declared JSON hashes are verified.
    """
    root = Path(root).expanduser()
    if years is not None:
        overlaps(0, 9999, years)
    selected_kind = "loss" if kind is None else kind
    if selected_kind not in ("loss", "baseline"):
        raise ValueError(f"Unknown station loss kind: {selected_kind}")
    completion = load_json(root / "runtime" / "completion.json")
    if completion.get("status") != "COMPLETED":
        raise ValueError("Loss campaign is not COMPLETED")
    filters = dict(model=model, climate_scenario=climate_scenario,
                   station_scenario=station_scenario, patch=patch, tech=tech)
    records = []
    for unit_id, entry in sorted(completion["receipts"].items()):
        identity = _identity(unit_id)
        if not all(matches(value, filters[key]) for key, value in identity.items()):
            continue
        receipt_path = resolve_path(entry["receipt_path"], root)
        receipt = _verified_json(receipt_path, entry.get("receipt_sha256"))
        status = entry.get("scientific_status")
        if (status not in _SUCCESS or receipt.get("status") != "COMPLETED"
                or receipt.get("scientific_status") != status or receipt.get("unit_id") != unit_id):
            raise ValueError(f"Incomplete or inconsistent loss receipt: {receipt_path}")
        if str(receipt.get("job_id")) != str(entry.get("job_id")):
            raise ValueError(f"Loss receipt job identity mismatch: {receipt_path}")
        manifest_info = receipt["manifest"]
        manifest_path = resolve_path(manifest_info["path"], root)
        manifest = _verified_json(manifest_path, manifest_info.get("sha256"))
        request = manifest["request"]
        expected_request = {**identity, "source_patch": identity["patch"]}
        del expected_request["patch"]
        if any(request.get(key) != value for key, value in expected_request.items()):
            raise ValueError(f"Loss manifest identity mismatch: {manifest_path}")
        snapshots = manifest["snapshots"]
        if [item["snapshot_year"] for item in snapshots] != request["snapshot_years"]:
            raise ValueError(f"Loss manifest snapshot coverage mismatch: {manifest_path}")
        actual_status = "COMPLETED" if any(item.get("status") == "COMPLETED" for item in snapshots) else "SKIPPED_NO_STATIONS"
        if manifest.get("status") != status or status != actual_status:
            raise ValueError(f"Loss manifest status mismatch: {manifest_path}")
        artifacts = None
        for snapshot in snapshots:
            snapshot_value = snapshot["snapshot_year"]
            if snapshot.get("status") == "SKIPPED_NO_STATIONS":
                if snapshot.get("station_count") != 0 or snapshot.get("chunks"):
                    raise ValueError(f"Invalid empty loss snapshot: {manifest_path}")
                continue
            if snapshot.get("status") != "COMPLETED" or snapshot.get("station_count", 0) < 1:
                raise ValueError(f"Incomplete loss snapshot: {manifest_path}")
            if not matches(snapshot_value, snapshot_year):
                continue
            first, last = _window(request, snapshot_value)
            if not overlaps(first, last, years):
                continue
            chunks = snapshot.get("chunks", [])
            if sum(chunk["station_count"] for chunk in chunks) != snapshot["station_count"]:
                raise ValueError(f"Loss snapshot station count mismatch: {manifest_path}")
            batches_seen = set()
            for chunk in chunks:
                batch, annual = _annual_paths(chunk, identity, snapshot_value, root, first, last)
                if batch in batches_seen:
                    raise ValueError(f"Duplicate loss station batch: {manifest_path}: {batch}")
                batches_seen.add(batch)
                base_record = dict(dataset=DATASET, **identity, kind=selected_kind,
                                   snapshot_year=snapshot_value, station_batch=batch,
                                   station_count=chunk["station_count"], status="COMPLETED")
                if selected_kind == "loss":
                    for year, path in annual:
                        if overlaps(year, year, years):
                            records.append(dict(base_record, start_year=year, end_year=year, path=str(path)))
                    continue
                annual_path = annual[0][1]
                relative = annual_path.relative_to(annual_path.parents[8] / "generation_loss")
                baseline_dir = annual_path.parents[8] / "baselines" / relative.parent
                baseline_manifest_path = baseline_dir / "manifest.json"
                if artifacts is None:
                    artifacts = {str(resolve_path(item["path"], root)): item for item in receipt["artifacts"]}
                info = artifacts.get(str(baseline_manifest_path))
                if info is None:
                    raise ValueError(f"Baseline manifest is absent from receipt: {baseline_manifest_path}")
                baseline_manifest = _verified_json(baseline_manifest_path, info.get("sha256"))
                if (any(baseline_manifest.get(key) != value for key, value in expected_request.items())
                        or baseline_manifest.get("snapshot_year") != snapshot_value
                        or baseline_manifest.get("analysis_years") != list(range(first, last + 1))):
                    raise ValueError(f"Baseline manifest identity/window mismatch: {baseline_manifest_path}")
                baseline_path = resolve_path(baseline_manifest["baselines"]["exclude_union_selected"], root)
                if baseline_path != baseline_dir / "baseline_12x8__exclude_union_selected.nc":
                    raise ValueError(f"Baseline path mismatch: {baseline_manifest_path}")
                if str(baseline_path) not in artifacts:
                    raise ValueError(f"Baseline is absent from receipt: {baseline_path}")
                records.append(dict(base_record, start_year=first, end_year=last, path=str(baseline_path)))
    return sorted(records, key=lambda item: item["path"])


if __name__ == "__main__":
    run_cli(find_records, DEFAULT_ROOT, DATASET, station=True,
            kinds=("loss", "baseline"), snapshots=True)
