"""Small metadata and NetCDF checks for the two CF readers."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr

try:
    from . import read_cf_grid as grid
    from . import read_cf_stations as stations
    from .build_cf_grid_index import build_index
except ImportError:
    import read_cf_grid as grid
    import read_cf_stations as stations
    from build_cf_grid_index import build_index


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class CFReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def grid_manifest(self, climate="ssp126", patch="R01C01"):
        path = self.root / "outputs" / "M" / climate / patch / "wind" / "manifest.json"
        value = {
            "status": "COMPLETED", "merge_final": False, "identity": "current",
            "provenance": {"model": "M", "scenario": climate, "patch": patch,
                           "tech": "wind", "years": "2015-2024"},
            "blocks": [
                {"index": 0, "status": "COMPLETED", "start_year": 2015, "end_year": 2019,
                 "path": "blocks/current/cf_2015-2019.nc"},
                {"index": 1, "status": "COMPLETED", "start_year": 2020, "end_year": 2024,
                 "path": "blocks/current/cf_2020-2024.nc"},
            ],
        }
        write_json(path, value)
        return path, value

    def grid_index(self):
        entries = []
        for path in sorted((self.root / "outputs").glob("*/*/*/*/manifest.json")):
            value = json.loads(path.read_text())
            model, scenario, patch_name, tech = path.relative_to(self.root / "outputs").parts[:4]
            entries.append(dict(model=model, climate_scenario=scenario, patch=patch_name, tech=tech,
                                years=value["provenance"]["years"], identity=value["identity"],
                                status=value["status"], merge_final=value["merge_final"],
                                manifest={"path": str(path.relative_to(self.root))},
                                blocks=[dict(block, path=str(Path(block["path"]) if Path(block["path"]).is_absolute()
                                                             else (path.parent / block["path"]).relative_to(self.root)))
                                        for block in value["blocks"]]))
        value = dict(schema=grid.INDEX_SCHEMA, schema_version=1, status="COMPLETED",
                     combination_count=len(entries), file_count=sum(len(e["blocks"]) for e in entries),
                     entries=entries)
        path = self.root / grid.INDEX_PATH
        write_json(path, value)
        return path, value

    def grid_campaign(self):
        path, manifest = self.grid_manifest()
        for block in manifest["blocks"]:
            target = path.parent / block["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"NetCDF fixture: metadata-only index validation")
        expected = dict(schema="cf-grid-v2-job-pack-v2", merge_final=False, code_sha="code",
                        models=["M"], scenarios=["ssp126"], patches=["R01C01"], techs=["wind"],
                        years="2015-2024", count=1,
                        jobs=[dict(model="M", scenario="ssp126", patch="R01C01", tech="wind",
                                   years="2015-2024", merge_final=False,
                                   expected_manifest=str(path.relative_to(self.root)))])
        completion = dict(status="COMPLETED", merge_final=False, code_sha="code", run_id="run",
                          succeeded_units=1, year_nc_files=2)
        write_json(self.root / "runtime/final_expected_manifest.json", expected)
        write_json(self.root / "runtime/completion.json", completion)
        return path, manifest, expected, completion

    def station_entry(self, climate="ssp126", station="ssp585", patch="R01C01"):
        directory = Path("outputs") / "M" / ("climate_" + climate) / ("station_" + station) / patch / "wind"
        return {
            "model": "M", "climate_scenario": climate, "station_scenario": station,
            "source_patch": patch, "tech": "wind", "status": "COMPLETED",
            "station_count": 2, "years": "2015-2024",
            "manifest": {"path": str(directory / "manifest.json")},
            "blocks": [
                {"index": i, "identity": f"block-{i}", "status": "COMPLETED",
                 "path": str(directory / "blocks" / "current" / f"cf_{start}-{end}.nc")}
                for i, (start, end) in enumerate(((2015, 2019), (2020, 2024)))
            ],
        }

    def station_index(self, entries, status="COMPLETED"):
        path = self.root / "index" / "authoritative_index.json"
        write_json(path, {"status": status, "entries": entries})
        return path

    def test_grid_uses_manifest_identity_and_orders_blocks(self):
        path, value = self.grid_manifest()
        historical = path.parent / "blocks" / "obsolete" / "cf_2015-2019.nc"
        historical.parent.mkdir(parents=True)
        historical.touch()
        value["blocks"].reverse()
        write_json(path, value)
        self.grid_index()
        records = grid.find_records(self.root)
        self.assertEqual([r["start_year"] for r in records], [2015, 2020])
        self.assertTrue(all("/current/" in r["path"] for r in records))
        self.assertEqual(records[0]["path"], str(path.parent / "blocks/current/cf_2015-2019.nc"))
        self.assertIsNone(records[0]["station_scenario"])

    def test_grid_queries_index_without_reading_manifests_or_directories(self):
        self.grid_manifest()
        broken, value = self.grid_manifest(climate="ssp585")
        value["status"] = "RUNNING"
        write_json(broken, value)
        self.grid_index()
        for manifest in (self.root / "outputs").glob("*/*/*/*/manifest.json"):
            manifest.unlink()
        with patch.object(Path, "iterdir", side_effect=AssertionError("Query must not scan directories")):
            records = grid.find_records(self.root, climate_scenario=["ssp126"], years=(2019, 2020))
        self.assertEqual(len(records), 2)
        self.assertEqual(len(grid.find_records(self.root, climate_scenario="ssp126", years=(2021, 2021))), 1)
        self.assertEqual(grid.find_records(self.root, climate_scenario="ssp245"), [])
        with self.assertRaisesRegex(ValueError, "COMPLETED"):
            grid.find_records(self.root)

    def test_grid_checks_all_blocks_before_year_filter(self):
        path, value = self.grid_manifest()
        value["blocks"][1]["status"] = "RUNNING"
        write_json(path, value)
        self.grid_index()
        with self.assertRaisesRegex(ValueError, "COMPLETED"):
            grid.find_records(self.root, years=(2015, 2015))

    def test_grid_rejects_truncated_or_inconsistent_metadata(self):
        path, original = self.grid_manifest()
        mutations = [
            lambda v: v["blocks"].pop(),
            lambda v: v["blocks"][1].update(index=0),
            lambda v: v["blocks"][1].update(start_year=2021),
            lambda v: v.update(merge_final=True),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = copy.deepcopy(original)
                mutate(value)
                write_json(path, value)
                self.grid_index()
                with self.assertRaises(ValueError):
                    grid.find_records(self.root)

    def test_grid_preserves_absolute_path(self):
        path, value = self.grid_manifest()
        absolute = str(self.root / "timestamped" / "cf_2015-2019.nc")
        value["blocks"][0]["path"] = absolute
        write_json(path, value)
        self.grid_index()
        self.assertEqual(grid.find_records(self.root)[0]["path"], absolute)

    def test_grid_requires_published_index_and_valid_counts(self):
        self.grid_manifest()
        with self.assertRaisesRegex(FileNotFoundError, "build_cf_grid_index"):
            grid.find_records(self.root)
        path, original = self.grid_index()
        for update in [dict(schema="wrong"), dict(status="RUNNING"), dict(file_count=0),
                       dict(combination_count=0), dict(entries=[])]:
            write_json(path, dict(original, **update))
            with self.assertRaises(ValueError):
                grid.find_records(self.root)
        duplicate = dict(original, entries=original["entries"] * 2, combination_count=2, file_count=4)
        write_json(path, duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            grid.find_records(self.root)

    def test_builder_publishes_complete_index_with_source_hashes(self):
        path, manifest, _, _ = self.grid_campaign()
        historical = path.parent / "blocks/old/cf_2015-2019.nc"
        historical.parent.mkdir(parents=True)
        historical.write_bytes(b"old")
        built = build_index(self.root)
        self.assertEqual(built["combination_count"], 1)
        self.assertEqual(built["file_count"], 2)
        self.assertEqual(built["entries"][0]["manifest"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(all(block["size_bytes"] > 0 for block in built["entries"][0]["blocks"]))
        self.assertEqual(len(grid.find_records(self.root, years=(2020, 2020))), 1)
        self.assertEqual(json.loads(path.read_text()), manifest)
        self.assertEqual(json.loads((self.root / grid.INDEX_PATH).read_text()), built)

    def test_builder_failure_preserves_existing_index(self):
        path, manifest, _, _ = self.grid_campaign()
        build_index(self.root)
        index_path = self.root / grid.INDEX_PATH
        previous = index_path.read_bytes()
        missing = path.parent / manifest["blocks"][1]["path"]
        missing.unlink()
        with self.assertRaises(FileNotFoundError):
            build_index(self.root)
        self.assertEqual(index_path.read_bytes(), previous)
        self.assertEqual(list(index_path.parent.glob(".authoritative_index.*.tmp")), [])

    def test_builder_rejects_incomplete_or_mismatched_campaign(self):
        path, manifest, expected, completion = self.grid_campaign()
        cases = [
            ("runtime/completion.json", dict(completion, status="RUNNING")),
            ("runtime/completion.json", dict(completion, year_nc_files=3)),
            ("runtime/final_expected_manifest.json", dict(expected, patches=["R01C01", "R01C02"])),
            ("runtime/final_expected_manifest.json", dict(expected, jobs=[])),
            (str(path.relative_to(self.root)), dict(manifest, provenance=dict(manifest["provenance"], model="other"))),
            (str(path.relative_to(self.root)), dict(manifest, blocks=manifest["blocks"][:1])),
        ]
        for relative, bad in cases:
            with self.subTest(relative=relative, bad=bad):
                target = self.root / relative
                original = target.read_bytes()
                write_json(target, bad)
                with self.assertRaises(ValueError):
                    build_index(self.root)
                self.assertFalse((self.root / grid.INDEX_PATH).exists())
                target.write_bytes(original)

    def test_stations_cross_scenarios_and_empty_entries(self):
        wanted = self.station_entry()
        empty = self.station_entry(patch="R01C02")
        empty.update(status="EMPTY_NO_STATIONS", station_count=0, blocks=[])
        other = self.station_entry(climate="ssp585", station="ssp126")
        self.station_index([other, empty, wanted])
        records = stations.find_records(self.root, climate_scenario="ssp126",
                                        station_scenario="ssp585", years=(2020, 2020))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["patch"], "R01C01")
        self.assertEqual(records[0]["start_year"], 2020)
        self.assertEqual(records[0]["path"], str(self.root / wanted["blocks"][1]["path"]))
        self.assertEqual(len(stations.find_records(self.root)), 4)

    def test_stations_reject_incomplete_index_and_entry(self):
        entry = self.station_entry()
        self.station_index([entry], status="RUNNING")
        with self.assertRaisesRegex(ValueError, "COMPLETED"):
            stations.find_records(self.root)
        entry["blocks"][1]["status"] = "RUNNING"
        self.station_index([entry])
        with self.assertRaisesRegex(ValueError, "COMPLETED"):
            stations.find_records(self.root, years=(2015, 2015))

    def test_stations_reject_truncated_or_duplicate_entries(self):
        entry = self.station_entry()
        self.station_index([entry, entry])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            stations.find_records(self.root)
        entry["blocks"].pop()
        self.station_index([entry])
        with self.assertRaisesRegex(ValueError, "cover declared years"):
            stations.find_records(self.root)

    def test_stations_empty_status_requires_no_artifacts(self):
        entry = self.station_entry()
        entry.update(status="EMPTY_NO_STATIONS", station_count=0)
        self.station_index([entry])
        with self.assertRaisesRegex(ValueError, "EMPTY_NO_STATIONS"):
            stations.find_records(self.root)

    def test_stations_require_indexed_year_filename(self):
        entry = self.station_entry()
        entry["blocks"][0]["path"] = "ambiguous.nc"
        self.station_index([entry])
        with self.assertRaisesRegex(ValueError, "indexed path"):
            stations.find_records(self.root)

    def test_grid_open_record_crops_tiny_netcdf(self):
        path, _ = self.grid_manifest()
        self.grid_index()
        nc = path.parent / "blocks/current/cf_2015-2019.nc"
        nc.parent.mkdir(parents=True)
        data = xr.Dataset({"wind_cf": (("time", "lat", "lon"), np.ones((2, 2, 2), dtype="f4"))},
                          coords={"time": np.array(["2015-01-01", "2016-01-01"], dtype="datetime64[ns]"),
                                  "lat": [1., 0.], "lon": [100., 101.]})
        data.to_netcdf(nc)
        with grid.open_record(grid.find_records(self.root)[0], variables=["wind_cf"],
                              years=(2016, 2016), lat_range=(0, 0), lon_range=(101, 101)) as opened:
            self.assertEqual(dict(opened.sizes), {"time": 1, "lat": 1, "lon": 1})
            self.assertEqual(float(opened.wind_cf.values[0, 0, 0]), 1.0)

    def test_stations_open_record_preserves_requested_ids(self):
        entry = self.station_entry()
        self.station_index([entry])
        nc = self.root / entry["blocks"][0]["path"]
        nc.parent.mkdir(parents=True)
        data = xr.Dataset({"wind_cf": (("time", "station"), np.array([[.1, .2], [.3, .4]], dtype="f4"))},
                          coords={"time": np.array(["2015-01-01", "2016-01-01"], dtype="datetime64[ns]"),
                                  "station_id": ("station", ["one", "two"]), "station": [0, 1]})
        data.to_netcdf(nc)
        with stations.open_record(stations.find_records(self.root)[0], variables=["wind_cf"],
                                  years=(2016, 2016), station_ids=["two", "one"]) as opened:
            self.assertEqual(opened.station_id.values.tolist(), ["two", "one"])
            np.testing.assert_allclose(opened.wind_cf.values, [[.4, .3]])


if __name__ == "__main__":
    unittest.main()
