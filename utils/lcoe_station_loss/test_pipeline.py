"""Numerical tests for native-calendar integration and capacity accounting."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from netCDF4 import Dataset
from .pipeline import annual_cf,annual_loss,year_hours
from .science import weighted_annual,add_joint,FIELDS
from .pipeline import sha as digest

class MetricTests(unittest.TestCase):
    def test_native_calendars(self):
        self.assertEqual(year_hours([2032],"standard")[0],8784)
        self.assertEqual(year_hours([2032],"365_day")[0],8760)
        self.assertEqual(year_hours([2032],"360_day")[0],8640)

    def test_signed_loss_capacity_and_exclusion(self):
        values=np.array([[2.,-1.,np.nan],[2.,-1.,3.]])
        capacity=np.array([[10.,30.,50.],[20.,30.,50.]])
        energy,total,denominator=weighted_annual(values,capacity,np.array([True,True,False]))
        np.testing.assert_allclose(total,[-10,10])
        np.testing.assert_allclose(denominator,[40,50])
        self.assertTrue(np.isnan(energy[:,2]).all())
        np.testing.assert_allclose(total/denominator,[-.25,.2])

    def test_combined_ratios_use_summed_energy(self):
        records=[]
        for tech,loss,cap in [("wind",-30,10),("solar",60,30)]:
            row=dict(model="a",station_ssp="ssp126",climate_ssp="ssp126",snapshot=2030,year=2030,tech=tech,calendar="365_day",expected_hours=8760)
            row.update({k:0. for k in FIELDS})
            row.update(net_loss_mwh=loss,capacity_mw=cap,normal_annual_mwh=100)
            records.append(row)
        joint=add_joint(pd.DataFrame(records)).iloc[-1]
        self.assertEqual(joint.net_loss_mwh/joint.capacity_mw,.75)
        self.assertEqual(joint.normal_annual_mwh,200)
        self.assertEqual(joint.expected_hours,8760)
        self.assertEqual(joint.calendar,"365_day")

    def test_three_hour_integral_and_missing_cf(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"cf.nc"; n=30*365*8
            with Dataset(p,"w") as ds:
                for k,v in dict(model='test',climate_scenario='ssp245',station_scenario='ssp126',tech='solar',source_patch='test').items():setattr(ds,k,v)
                ds.createDimension("time",n);ds.createDimension("station",2)
                t=ds.createVariable("time","f8",("time",));t.units="hours since 2030-01-01 00:00:00";t.calendar="365_day";t[:]=np.arange(n)*3+1.5
                ds.createVariable("source_grid_lat","f8",("station",))[:]=[5.,5.]
                ds.createVariable("source_grid_lon","f8",("station",))[:]=[-350.,10.1]
                ds.createVariable("grid_id","i8",("station",))[:]=[1,2]
                v=ds.createVariable("solar_cf","f4",("time","station"),fill_value=-999,chunksizes=(240,2))
                v[:]=.25;v[10,1]=-999
            mapping=dict(grid_id=np.array([1,2]),cf_lat_index=np.array([0,0]),cf_lon_index=np.array([0,1]),
                         source_lat=np.array([5.,5.]),source_lon=np.array([10.,10.1]))
            task=dict(task_id="tiny",tech="solar",model='test',climate_ssp='ssp245',station_ssp='ssp126',patch='test',cf=[dict(path=str(p),years=[2030,2059],size_bytes=p.stat().st_size)])
            generation,counts,expected,cal=annual_cf(task,mapping)
            np.testing.assert_allclose(generation[:,0],2190)
            self.assertTrue(np.isnan(generation[0,1]))
            self.assertEqual(counts[0,1],2919)
            np.testing.assert_array_equal(expected,np.full(30,2920))
            self.assertEqual(cal,"365_day")

    def test_loss_tile_alignment_and_net_energy_closure(self):
        with tempfile.TemporaryDirectory() as td:
            records=[]
            for window in (2030,2040,2050):
                p=Path(td)/f"{window}.nc"
                with Dataset(p,"w") as ds:
                    ds.createDimension("analysis_year",10);ds.createDimension("station",2)
                    for k,v in dict(model="test",climate_scenario="ssp126",tech="wind",patch="R01C01").items(): setattr(ds,k,v)
                    ds.createVariable("analysis_year","i4",("analysis_year",))[:]=np.arange(window,window+10)
                    ds.createVariable("station_id",str,("station",))[:]=np.array(["b","a"],dtype=object)
                    ds.createVariable("capacity_mw","f8",("station",))[:]=1
                    for name,vals in {
                        "net_generation_loss_per_mw_all":[-1,2],
                        "normal_all_generation_mwh_all":[100,200],
                        "normal_generation_mwh_all":[3,5],
                        "actual_generation_mwh_all":[4,3]}.items():
                        ds.createVariable(name,"f8",("analysis_year","station"))[:]=np.tile(vals,(10,1))
                records.append(dict(path=str(p),sha256=digest(p),window=window,tile="r0000c0000"))
            task=dict(model="test",climate_ssp="ssp126",tech="wind",patch="R01C01",loss=records)
            mapping=dict(grid_id=np.array([1,2]),tile=np.array(["r0000c0000"]*2),loss_station_id=np.array(["a","b"]))
            loss,normal,error=annual_loss(task,mapping)
            np.testing.assert_array_equal(loss,np.tile([2,-1],(30,1)))
            np.testing.assert_array_equal(normal,np.tile([200,100],(30,1)))
            self.assertEqual(error,0)

if __name__=="__main__": unittest.main()
