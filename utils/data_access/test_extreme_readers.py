"""Small fixtures for authoritative extreme-event selection and native decoding."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import xarray as xr

try:
    from . import read_extreme_grid as grid
    from . import read_extreme_stations as stations
except ImportError:
    import read_extreme_grid as grid
    import read_extreme_stations as stations


class ExtremeReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "runtime").mkdir()

    def write_index(self, index):
        (self.root / "runtime" / "authoritative_index.json").write_text(
            json.dumps(index), encoding="utf-8")

    def grid_index(self):
        return {
            "kind": "grid-v2-unified-index", "schema_version": 1,
            "combinations": {
                "audit-unit": {
                    "model": "CANESM5", "scenario": "ssp126", "patch": "R01C01",
                    "tech": "wind", "artifacts": [
                        {"stage": "baseline", "years": "2015-2024",
                         "unified_output": "outputs/baseline.nc"},
                        {"stage": "signals", "years": "2015-2019",
                         "unified_output": "outputs/first.nc", "output": "/obsolete/first.nc"},
                        {"stage": "signals", "years": "2020-2024",
                         "unified_output": "outputs/second.nc", "output": "/obsolete/second.nc"},
                    ],
                },
            },
        }

    def station_index(self):
        combination = {
            "model": "CANESM5", "climate_scenario": "ssp126",
            "station_scenario": "ssp585", "patch": "R01C01", "tech": "wind",
            "status": "COMPLETED", "mapping_identity": "mapping-id", "outputs": [
                {"status": "COMPLETED", "period": "2015-2019", "identity": "shard-1",
                 "artifact": {"path": "attempts/task/7/outputs/first.nc"}},
                {"status": "COMPLETED", "period": "2020-2024", "identity": "shard-2",
                 "artifact": {"path": "attempts/task/7/outputs/second.nc"}},
            ],
        }
        empty = {**combination, "patch": "R01C02", "status": "SKIPPED_NO_STATIONS", "outputs": []}
        return {"kind": "station-event-index", "schema": "station-extreme-v2",
                "combinations": {"full": combination, "empty": empty}}

    def test_grid_prefers_published_paths_and_separates_baselines(self):
        self.write_index(self.grid_index())
        records = grid.find_records(self.root, model=["CANESM5"], climate_scenario="ssp126",
                                    years=(2019, 2020))
        self.assertEqual([r["kind"] for r in records], ["signals", "signals"])
        self.assertEqual([r["path"] for r in records],
                         [str(self.root / "outputs/first.nc"), str(self.root / "outputs/second.nc")])
        self.assertEqual(len(grid.find_records(self.root, kind="baseline", years=(2024, 2024))), 1)
        self.assertEqual(grid.find_records(self.root, kind="baseline", years=(2025, 2030)), [])
        self.assertEqual(grid.find_records(self.root, model="BCC-CSM2-MR"), [])

    def test_grid_supports_original_index_output_field(self):
        index = self.grid_index()
        artifact = index["combinations"]["audit-unit"]["artifacts"][1]
        artifact.pop("unified_output")
        artifact["output"] = str(self.root / "published.nc")
        self.write_index(index)
        self.assertEqual(grid.find_records(self.root, years=(2015, 2019))[0]["path"],
                         str(self.root / "published.nc"))

    def test_grid_rejects_wrong_schema_and_unfinished_entries(self):
        index = self.grid_index()
        index["schema_version"] = 2
        self.write_index(index)
        with self.assertRaisesRegex(ValueError, "schema_version"):
            grid.find_records(self.root)
        index = self.grid_index()
        index["combinations"]["audit-unit"]["status"] = "RUNNING"
        self.write_index(index)
        with self.assertRaisesRegex(ValueError, "not COMPLETED"):
            grid.find_records(self.root)

    def test_station_filters_both_scenarios_and_skips_empty_combinations(self):
        index = self.station_index()
        other = copy.deepcopy(index["combinations"]["full"])
        other["station_scenario"] = "ssp126"
        index["combinations"]["other-station"] = other
        self.write_index(index)
        records = stations.find_records(self.root, climate_scenario="ssp126",
                                        station_scenario="ssp585", years=(2019, 2020))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["path"], str(self.root / "attempts/task/7/outputs/first.nc"))
        self.assertEqual(stations.find_records(self.root, patch="R01C02"), [])
        self.assertEqual(stations.find_records(self.root, climate_scenario="ssp245"), [])

    def test_station_cli_defaults_to_signals(self):
        self.write_index(self.station_index())
        result = subprocess.run(
            [sys.executable, str(Path(stations.__file__).resolve()), "--root", str(self.root)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["dataset"], "extreme_stations")
        self.assertEqual(output["matched_files"], 2)
        self.assertEqual(output["shown_files"], 2)
        self.assertEqual([record["kind"] for record in output["records"]], ["signals", "signals"])
        self.assertEqual(output["records"][0]["path"],
                         str(self.root / "attempts/task/7/outputs/first.nc"))

    def test_station_rejects_old_schema_and_incomplete_shards(self):
        index = self.station_index()
        index["schema"] = "station-extreme-v1"
        self.write_index(index)
        with self.assertRaisesRegex(ValueError, "station-extreme-v2"):
            stations.find_records(self.root)
        index = self.station_index()
        index["combinations"]["full"]["outputs"][0]["status"] = "RUNNING"
        self.write_index(index)
        with self.assertRaisesRegex(ValueError, "not COMPLETED"):
            stations.find_records(self.root)

    def test_station_rejects_false_empty_status(self):
        index = self.station_index()
        index["combinations"]["full"]["status"] = "SKIPPED_NO_STATIONS"
        self.write_index(index)
        with self.assertRaisesRegex(ValueError, "unexpected outputs"):
            stations.find_records(self.root)

    def test_invalid_periods_are_not_silently_accepted(self):
        for module, index, entry, field in (
            (grid, self.grid_index(), "audit-unit", "years"),
            (stations, self.station_index(), "full", "period"),
        ):
            key = "artifacts" if module is grid else "outputs"
            position = 1 if module is grid else 0
            index["combinations"][entry][key][position][field] = "2024-2020"
            self.write_index(index)
            with self.subTest(module=module.__name__), self.assertRaises(ValueError):
                module.find_records(self.root)

    def test_open_station_shard_preserves_fill_calendar_and_station_ids(self):
        path = self.root / "native.nc"
        ds = xr.Dataset(
            {"signal_icing": (("time", "station"), np.array([[0, 1], [1, -127]], dtype="i1"))},
            coords={"time": ("time", [0, 3], {"units": "hours since 2020-01-01 01:30:00",
                                               "calendar": "365_day"}),
                    "station": [0, 1], "station_id": ("station", ["site-a", "site-b"])},
        )
        ds.to_netcdf(path, encoding={"signal_icing": {"_FillValue": np.int8(-127)}})
        with stations.open_record({"path": str(path)}, variables=["signal_icing"],
                                  years=(2020, 2020), station_ids=["site-b"]) as actual:
            self.assertEqual(actual.sizes["station"], 1)
            self.assertEqual(actual.station_id.item(), "site-b")
            self.assertEqual(actual.time.dt.calendar, "noleap")
            self.assertEqual(actual.time.dt.minute.values.tolist(), [30, 30])
            self.assertEqual(actual.signal_icing.values[0, 0], 1)
            self.assertTrue(np.isnan(actual.signal_icing.values[1, 0]))


if __name__ == "__main__":
    unittest.main()
