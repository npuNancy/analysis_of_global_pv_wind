"""Small metadata fixtures for the accepted station-loss reading chain."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

if __package__:
    from .read_loss_stations import find_records
else:
    from read_loss_stations import find_records


class LossReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.unit_id = "loss_BCC-CSM2-MR_c126_s585_wind_R02C08"
        self.identity = dict(model="BCC-CSM2-MR", climate_scenario="ssp126",
                             station_scenario="ssp585", source_patch="R02C08", tech="wind")
        self.suffix = Path("BCC-CSM2-MR/climate_ssp126/station_ssp585/R02C08")
        self.manifest_path = self.root / "outputs/task_status" / self.suffix / "wind/manifest.json"
        self.receipt_path = self.root / "runtime/receipts" / self.unit_id / "123.json"
        self.completion_path = self.root / "runtime/completion.json"
        self.baseline_paths = {}
        snapshots, artifacts = [], []
        for year in (2030, 2050):
            directory = self.suffix / str(year) / "wind/stations_0000000_0000002"
            paths = [str(self.root / "outputs/generation_loss" / directory / f"wind_generation_loss_station_{y}.nc")
                     for y in range(year, year + 10)]
            snapshots.append(dict(snapshot_year=year, status="COMPLETED", station_count=2,
                                  chunks=[dict(station_count=2, outputs=paths)]))
            baseline_dir = self.root / "outputs/baselines" / directory
            baseline_path = baseline_dir / "baseline_12x8__exclude_union_selected.nc"
            baseline_manifest = baseline_dir / "manifest.json"
            self.baseline_paths[year] = baseline_manifest
            self.write(baseline_manifest, dict(self.identity, snapshot_year=year,
                                              analysis_years=list(range(year, year + 10)),
                                              baselines={"exclude_union_selected": str(baseline_path)}))
            artifacts.extend([dict(path=str(baseline_path)),
                              dict(path=str(baseline_manifest), sha256=self.digest(baseline_manifest))])
        snapshots.insert(1, dict(snapshot_year=2040, status="SKIPPED_NO_STATIONS", station_count=0))
        self.manifest = dict(status="COMPLETED", request=dict(self.identity, snapshot_years=[2030, 2040, 2050],
                             analysis_scheme="center-k", analysis_k=5, station_chunk_size=256), snapshots=snapshots)
        self.receipt = dict(status="COMPLETED", scientific_status="COMPLETED", unit_id=self.unit_id,
                            job_id="123", run_id="replacement_execution", code_sha="replacement_code",
                            manifest={}, artifacts=artifacts)
        self.completion = dict(status="COMPLETED", receipts={self.unit_id: dict(
            scientific_status="COMPLETED", job_id="123", receipt_path=str(self.receipt_path),
            output_root=str(self.root / "outputs"))})
        self.publish()

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def publish(self):
        self.write(self.manifest_path, self.manifest)
        self.receipt["manifest"] = dict(path=str(self.manifest_path), sha256=self.digest(self.manifest_path))
        self.write(self.receipt_path, self.receipt)
        self.completion["receipts"][self.unit_id]["receipt_sha256"] = self.digest(self.receipt_path)
        self.write(self.completion_path, self.completion)

    def test_snapshot_and_analysis_year_filters(self):
        records = find_records(self.root, model="BCC-CSM2-MR", climate_scenario="ssp126",
                               station_scenario="ssp585", years=(2035, 2036), snapshot_year=2030)
        self.assertEqual([item["start_year"] for item in records], [2035, 2036])
        self.assertTrue(all(item["snapshot_year"] == 2030 and item["kind"] == "loss" for item in records))
        self.assertEqual(find_records(self.root, snapshot_year=2040), [])
        self.assertEqual(find_records(self.root, years=(2035, 2036), snapshot_year=2050), [])

    def test_unselected_receipt_is_not_opened(self):
        self.completion["receipts"]["loss_CANESM5_c126_s126_wind_R02C08"] = dict(
            receipt_path="missing.json", receipt_sha256="not-read")
        self.write(self.completion_path, self.completion)
        self.assertEqual(len(find_records(self.root, model="BCC-CSM2-MR")), 20)

    def test_declared_chain_preserves_execution_provenance(self):
        old = self.root / "historical_outputs/task_status/manifest.json"
        self.write(old, dict(status="RUNNING"))
        records = find_records(self.root, years=(2059, 2059))
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["path"].startswith(str(self.root / "outputs")))

    def test_baseline_uses_hashed_declared_manifest(self):
        records = find_records(self.root, kind="baseline", years=(2035, 2035))
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["start_year"], records[0]["end_year"]), (2030, 2039))
        baseline = self.baseline_paths[2030]
        changed = json.loads(baseline.read_text())
        changed["analysis_years"] = [2030]
        self.write(baseline, changed)
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            find_records(self.root, kind="baseline", snapshot_year=2030)

    def test_rejects_stale_receipt_and_manifest(self):
        self.write(self.receipt_path, dict(self.receipt, status="RUNNING"))
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            find_records(self.root)
        self.publish()
        self.write(self.manifest_path, dict(self.manifest, status="RUNNING"))
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            find_records(self.root)

    def test_rejects_incomplete_campaign_and_receipt(self):
        self.completion["status"] = "RUNNING"
        self.publish()
        with self.assertRaisesRegex(ValueError, "not COMPLETED"):
            find_records(self.root)
        self.completion["status"] = "COMPLETED"
        self.receipt["status"] = "RUNNING"
        self.publish()
        with self.assertRaisesRegex(ValueError, "Incomplete or inconsistent"):
            find_records(self.root)

    def test_rejects_manifest_identity_and_missing_year(self):
        self.manifest["request"]["station_scenario"] = "ssp126"
        self.publish()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            find_records(self.root)
        self.manifest["request"]["station_scenario"] = "ssp585"
        self.manifest["snapshots"][0]["chunks"][0]["outputs"].pop()
        self.publish()
        with self.assertRaisesRegex(ValueError, "Incomplete or duplicate annual"):
            find_records(self.root, snapshot_year=2030)

    def test_legitimate_skipped_task_has_no_records(self):
        self.manifest["status"] = "SKIPPED_NO_STATIONS"
        self.manifest["snapshots"] = [dict(snapshot_year=year, status="SKIPPED_NO_STATIONS", station_count=0)
                                      for year in (2030, 2040, 2050)]
        self.receipt["scientific_status"] = "SKIPPED_NO_STATIONS"
        self.completion["receipts"][self.unit_id]["scientific_status"] = "SKIPPED_NO_STATIONS"
        self.publish()
        self.assertEqual(find_records(self.root), [])
        self.manifest["snapshots"][0]["station_count"] = 1
        self.publish()
        with self.assertRaisesRegex(ValueError, "Invalid empty"):
            find_records(self.root)
