"""Scientific regression checks for event unions, signed energy and missingness."""
from pathlib import Path
import sys
import unittest
import tempfile
import json
import numpy as np
import netCDF4 as nc
from utils.dispatch_station_climate.loss import compute_events, metric_units

REFERENCE = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage/inputs/reference_code/loss")
sys.path.insert(0, str(REFERENCE))


class EventLossTests(unittest.TestCase):
    def test_overlap_signed_loss_and_missing_are_preserved(self):
        dates = nc.num2date(np.arange(360*8)*3+1.5, "hours since 2030-01-01", "360_day")
        cf = np.full((len(dates),2), .5, dtype="f4")
        cf[:3,0] = [.2,.8,.1]
        cf[:,1] = np.nan
        a = np.zeros(cf.shape,dtype="i1")
        b = a.copy()
        a[:2,0] = 1
        b[1:3,0] = 1
        a[:,1] = b[:,1] = -1
        slots = np.asarray([m*100+h for m in range(1,13) for h in range(1,24,3)])
        base = dict(month_hour_idx=slots,cf_normal=np.full((96,2),.5,dtype="f4"))
        cap = np.array([[2.,3.]])
        out = compute_events(cf, {"signal_icing":a,"signal_high_wind":b}, dates, [2030], cap, [base], [[2030,2039]])
        self.assertAlmostEqual(out["net_generation_loss_mwh_all"][0,0],2.4,places=5)
        self.assertAlmostEqual(out["generation_loss_mwh_all"][0,0],4.2,places=5)
        self.assertEqual(out["event_duration_hours_all"][0,0],9)
        self.assertNotAlmostEqual(out["net_generation_loss_mwh_icing"][0,0]+out["net_generation_loss_mwh_high_wind"][0,0],
                                  out["net_generation_loss_mwh_all"][0,0])
        self.assertTrue(np.isnan(out["net_generation_loss_mwh_all"][0,1]))
        self.assertAlmostEqual(out["net_generation_loss_mwh_all"][0,0],
            out["normal_generation_mwh_all"][0,0]-out["actual_generation_mwh_all"][0,0],places=5)
        self.assertEqual(metric_units("net_generation_loss_per_mw_all"),"MWh MW-1")
        self.assertEqual(metric_units("net_generation_loss_mwh_all"),"MWh")

class NativeArchiveTests(unittest.TestCase):
    def test_native_archive_units_baseline_generation_and_resume(self):
        from utils.dispatch_station_climate.loss import run
        from utils.lcoe_station_climate.pipeline import sha
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);unit="fixture"
            (root/"runtime/tasks").mkdir(parents=True)
            grid=np.array([100])
            mapping=root/"mapping.npz"
            np.savez_compressed(mapping,grid_id=grid,latitude=np.array([40.]),longitude=np.array([10.]),
                source_lat=np.array([40.]),source_lon=np.array([10.]),ssp126_positions=np.array([0]),
                ssp126_capacity=np.array([[2.]]))
            records={}
            for product in ["cf","extreme"]:
                path=root/(product+".nc")
                with nc.Dataset(path,"w") as ds:
                    ds.createDimension("time",2880);ds.createDimension("station",1)
                    t=ds.createVariable("time","f8",("time",));t.units="hours since 2030-01-01";t.calendar="360_day";t[:]=np.arange(2880)*3+1.5
                    ds.createVariable("grid_id","i8",("station",))[:]=grid
                    if product=="cf":
                        names=["wind_cf"]
                        v=ds.createVariable("wind_cf","f4",("time","station"));v[:]=.5;v[0,0]=.2;v[1,0]=.8
                    else:
                        names=["signal_"+x for x in ["high_temp","high_wind","hot_humid","icing","low_resource"]]
                        for name in names:
                            v=ds.createVariable(name,"i1",("time","station"),fill_value=-127);v[:]=0
                        ds["signal_icing"][:2,0]=1
                records[product]=[dict(path=str(path),size_bytes=path.stat().st_size,years=[2030,2030],variables=names)]
            task=dict(unit=unit,model="fixture",climate_ssp="ssp126",station_ssp="ssp126",tech="wind",patch="R00C00",
                snapshots=[2030],years=[2030],windows=[[2030,2030]],station_chunk=1,
                source_root=str(REFERENCE.parents[2]),mapping=dict(path=str(mapping),sha256=sha(mapping)),**records)
            (root/"runtime/tasks"/(unit+".json")).write_text(json.dumps(task))
            run(root,unit)
            marker=json.loads((root/"runtime/units"/unit/"complete.json").read_text())
            self.assertEqual(len(marker["outputs"]),2)
            with nc.Dataset(root/"outputs"/(unit+".nc")) as ds:
                self.assertEqual(ds["cf_normal"].shape,(1,96,1))
                self.assertEqual(ds["year"][:].tolist(),[2030])
                self.assertEqual(ds["expected_hours"][0],8640)
                self.assertEqual(ds["net_generation_loss_per_mw_all"].units,"MWh MW-1")
                self.assertAlmostEqual(ds["all_generation_mwh"][0,0],8640,places=3)
                self.assertAlmostEqual(ds["event_duration_hours_all"][0,0],6)
                self.assertEqual(ds["capacity_mw"].capacity_basis,"MW")
            before=sha(root/"outputs"/(unit+".nc"))
            run(root,unit)
            self.assertEqual(before,sha(root/"outputs"/(unit+".nc")))


if __name__ == "__main__":
    unittest.main()
