"""Publish a unified CF grid index from the completed campaign's task manifests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import tempfile

if __package__:
    from ._common import resolve_path
    from .read_cf_grid import DEFAULT_ROOT, INDEX_PATH, INDEX_SCHEMA, _records
else:
    from _common import resolve_path
    from read_cf_grid import DEFAULT_ROOT, INDEX_PATH, INDEX_SCHEMA, _records


def _document(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def build_index(root=DEFAULT_ROOT):
    """Validate every expected task and file, then atomically publish the index.

    Reads JSON and file metadata only. Existing indices remain intact if any
    validation fails. The completion record and task manifests are not modified.
    """
    root = Path(root).expanduser().resolve()
    completion, completion_source = _document(root / "runtime/completion.json")
    expected, expected_source = _document(root / "runtime/final_expected_manifest.json")
    if completion.get("status") != "COMPLETED" or completion.get("merge_final") is not False:
        raise ValueError("CF campaign must be COMPLETED with merge_final=false")
    if expected.get("schema") != "cf-grid-v2-job-pack-v2" or expected.get("merge_final") is not False:
        raise ValueError("Expected cf-grid-v2-job-pack-v2 with merge_final=false")
    axes = [expected[name] for name in ("models", "scenarios", "patches", "techs")]
    if any(not values or len(values) != len(set(values)) for values in axes):
        raise ValueError("Expected task axes must be nonempty and unique")
    combinations = set(product(*axes))
    jobs = expected["jobs"]
    if (expected.get("count") != len(jobs) or len(jobs) != len(combinations)
            or completion.get("succeeded_units") != len(jobs)):
        raise ValueError("Expected tasks and completion counts disagree")
    if completion.get("code_sha") != expected.get("code_sha"):
        raise ValueError("Expected tasks and completion code_sha disagree")

    entries, seen, paths_seen = [], set(), set()
    for job in jobs:
        key = tuple(job[name] for name in ("model", "scenario", "patch", "tech"))
        if key not in combinations or key in seen:
            raise ValueError(f"Unexpected or duplicate CF task: {key}")
        seen.add(key)
        if job.get("years") != expected["years"] or job.get("merge_final") is not False:
            raise ValueError(f"CF task coverage/configuration mismatch: {key}")
        manifest_path = resolve_path(job["expected_manifest"], root).resolve()
        normal_path = root / "outputs" / key[0] / key[1] / key[2] / key[3] / "manifest.json"
        if manifest_path != normal_path.resolve():
            raise ValueError(f"CF expected manifest path identity mismatch: {manifest_path}")
        manifest, source = _document(manifest_path)
        provenance = manifest["provenance"]
        if (any(provenance.get(name) != job[name] for name in ("model", "scenario", "patch", "tech"))
                or provenance.get("years") != job["years"]):
            raise ValueError(f"CF manifest provenance disagrees with expected task: {manifest_path}")
        entry = dict(model=key[0], climate_scenario=key[1], patch=key[2], tech=key[3],
                     years=provenance["years"], identity=manifest["identity"],
                     status=manifest["status"], merge_final=manifest["merge_final"],
                     manifest=source, blocks=[])
        for block in manifest["blocks"]:
            entry["blocks"].append({**{name: block[name] for name in
                                       ("index", "start_year", "end_year", "status")},
                                    "path": str(resolve_path(block["path"], manifest_path.parent))})
        rows = _records(entry, root)
        entry["blocks"].sort(key=lambda block: block["index"])
        for block, row in zip(entry["blocks"], rows):
            path = Path(row["path"])
            if row["path"] in paths_seen:
                raise ValueError(f"Duplicate CF file declaration: {path}")
            paths_seen.add(row["path"])
            if not path.is_file() or not os.access(path, os.R_OK):
                raise FileNotFoundError(f"CF block is missing or unreadable: {path}")
            stat = path.stat()
            if stat.st_size == 0:
                raise ValueError(f"CF block is empty: {path}")
            block["size_bytes"] = stat.st_size
        entries.append(entry)
    if seen != combinations or completion.get("year_nc_files") != len(paths_seen):
        raise ValueError("CF task/file coverage disagrees with completion")

    entries.sort(key=lambda entry: tuple(entry[name] for name in
                                        ("model", "climate_scenario", "patch", "tech")))
    index = dict(schema=INDEX_SCHEMA, schema_version=1, status="COMPLETED",
                 generated_at=datetime.now(timezone.utc).isoformat(),
                 root=str(root), run_id=completion["run_id"], years=expected["years"],
                 combination_count=len(entries), file_count=len(paths_seen),
                 sources=dict(completion=completion_source, expected_manifest=expected_source),
                 entries=entries)
    destination = root / INDEX_PATH
    # Write beside the destination so readers observe either complete version.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".authoritative_index.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(index, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Completed CF run root, not its outputs subdirectory")
    args = parser.parse_args()
    try:
        index = build_index(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(dict(path=str(Path(index["root"]) / INDEX_PATH),
                          status=index["status"], combination_count=index["combination_count"],
                          file_count=index["file_count"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
