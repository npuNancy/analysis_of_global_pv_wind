"""Regression checks for shared data selection and command-line behavior."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import xarray as xr

try:
    from . import _common as common
except ImportError:
    import _common as common


class HeaderVariable:
    dimensions = ("time", "station")
    dtype = np.dtype("float32")

    def ncattrs(self):
        return ["units"]

    def getncattr(self, name):
        return "1"

    def __getitem__(self, key):
        raise AssertionError("Header inspection must not read array values")


class LargeDimension:
    def __len__(self):
        return 1_000_000_000


class HeaderDataset:
    dimensions = {"time": LargeDimension(), "station": range(2)}
    variables = {"wind_cf": HeaderVariable()}

    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def ncattrs(self):
        return ["model"]

    def getncattr(self, name):
        return "CANESM5"


class CommonReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_cli_limit_paths_and_check_only_printed_records(self):
        present = self.root / "present.nc"
        present.touch()
        absent = self.root / "absent.nc"
        find = Mock(return_value=[{"path": str(present)}, {"path": str(absent)}])
        output = io.StringIO()
        with patch("sys.argv", ["reader", "--limit", "1", "--check", "--format", "paths"]), redirect_stdout(output):
            self.assertEqual(common.run_cli(find, self.root, "test"), 0)
        self.assertEqual(output.getvalue(), str(present) + "\n")

        output = io.StringIO()
        with patch("sys.argv", ["reader", "--limit", "0", "--check"]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                common.run_cli(find, self.root, "test")
        self.assertEqual(raised.exception.code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual((result["matched_files"], result["shown_files"]), (2, 2))
        self.assertTrue(result["records"][0]["readable"])
        self.assertFalse(result["records"][1]["exists"])

    def test_cli_inspect_reads_headers_without_array_access(self):
        header = HeaderDataset()
        find = Mock(return_value=[{"path": "first.nc"}, {"path": "second.nc"}])
        output = io.StringIO()
        with patch("netCDF4.Dataset", return_value=header) as opened, \
                patch("sys.argv", ["reader", "--limit", "1", "--inspect"]), redirect_stdout(output):
            common.run_cli(find, self.root, "test")
        result = json.loads(output.getvalue())
        self.assertEqual(result["matched_files"], 2)
        self.assertEqual(result["shown_files"], 1)
        metadata = result["records"][0]["header"]
        self.assertEqual(metadata["dimensions"]["time"], 1_000_000_000)
        self.assertEqual(metadata["variables"]["wind_cf"]["attributes"]["units"], "1")
        opened.assert_called_once_with(Path("first.nc"))
        self.assertTrue(header.closed)

    def test_selection_errors_close_open_dataset(self):
        cases = [
            ({"variables": ["missing"]}, KeyError, "Variables absent", True),
            ({"station_ids": ["missing"]}, KeyError, "Station IDs absent", True),
            ({"station_ids": ["known"]}, ValueError, "station_id coordinate", False),
        ]
        for options, exception, message, with_ids in cases:
            with self.subTest(options=options, with_ids=with_ids):
                coordinates = {"station_id": ("station", ["known"])} if with_ids else {}
                source = xr.Dataset({"wind_cf": ("station", [.5])}, coords=coordinates)
                close = Mock()
                source.set_close(close)
                with patch("xarray.open_dataset", return_value=source):
                    with self.assertRaisesRegex(exception, message):
                        common.open_record("file.nc", **options)
                close.assert_called_once_with()

    def test_latitude_filter_preserves_descending_coordinate_order(self):
        source = xr.Dataset({"value": ("lat", [9, 4, 0, -4, -9])},
                            coords={"lat": [90., 45., 0., -45., -90.]})
        close = Mock()
        source.set_close(close)
        with patch("xarray.open_dataset", return_value=source):
            with common.open_record("grid.nc", lat_range=(-1, 50)) as selected:
                self.assertEqual(selected.lat.values.tolist(), [45., 0.])
                self.assertEqual(selected.value.values.tolist(), [4, 0])
        close.assert_called_once_with()

    def test_annual_file_year_selection_directs_user_to_index(self):
        source = xr.Dataset({"generation_loss": ("station", [1.])})
        close = Mock()
        source.set_close(close)
        with patch("xarray.open_dataset", return_value=source):
            with self.assertRaisesRegex(ValueError, r"annual or baseline years in find_records\(\)"):
                common.open_record("annual_2030.nc", years=(2030, 2030))
        close.assert_called_once_with()

    def test_annual_loss_selection_keeps_capacity_coordinate(self):
        path = self.root / "wind_generation_loss_station_2030.nc"
        source = xr.Dataset(
            {"generation_loss_mwh_all": ("station", [12., 7., 99.])},
            coords={"station_id": ("station", ["active", "zero", "excluded"]),
                    "lon": ("station", [100., 101., 102.]),
                    "lat": ("station", [30., 31., 32.]),
                    "capacity_mw": ("station", [3., 0., 9.])},
        )
        source.generation_loss_mwh_all.attrs["units"] = "MWh"
        source.capacity_mw.attrs["units"] = "MW"
        source.to_netcdf(path)
        with common.open_record(path, variables=["generation_loss_mwh_all", "capacity_mw"],
                                station_ids=["zero", "active"]) as selected:
            self.assertNotIn("time", selected.coords)
            self.assertIn("capacity_mw", selected.coords)
            self.assertEqual(selected.station_id.values.tolist(), ["zero", "active"])
            self.assertEqual(selected.capacity_mw.values.tolist(), [0., 3.])
            self.assertEqual(selected.generation_loss_mwh_all.values.tolist(), [7., 12.])
            unit_loss = (selected.generation_loss_mwh_all /
                         selected.capacity_mw.where(selected.capacity_mw > 0)).load()
        np.testing.assert_allclose(unit_loss.values, [np.nan, 4.], equal_nan=True)

    def test_json_reload_observes_same_size_same_mtime_updates(self):
        path = self.root / "index.json"
        path.write_text('{"path": "old.nc"}', encoding="utf-8")
        previous = path.stat()
        self.assertEqual(common.load_json(path)["path"], "old.nc")
        path.write_text('{"path": "new.nc"}', encoding="utf-8")
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertEqual(path.stat().st_size, previous.st_size)
        self.assertEqual(path.stat().st_mtime_ns, previous.st_mtime_ns)
        self.assertEqual(common.load_json(path)["path"], "new.nc")

    def test_invalid_cli_options_fail_before_query(self):
        for arguments in (["--inspect", "--format", "paths"], ["--limit", "-1"],
                          ["--years", "2040", "2030"]):
            with self.subTest(arguments=arguments):
                find = Mock()
                with patch("sys.argv", ["reader", *arguments]), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        common.run_cli(find, self.root, "test")
                self.assertEqual(raised.exception.code, 2)
                find.assert_not_called()


if __name__ == "__main__":
    unittest.main()
