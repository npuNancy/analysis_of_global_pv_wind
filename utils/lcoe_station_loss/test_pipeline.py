"""Numerical tests for native-calendar integration and capacity accounting."""
import tempfile
import unittest
import itertools
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
from netCDF4 import Dataset
from .pipeline import annual_cf,annual_loss,year_hours
from .science import weighted_annual,add_joint,FIELDS
from .pipeline import sha as digest
from .pipeline import write_json,save_npz,signature
from .reduce import summarize

class MetricTests(unittest.TestCase):
    def test_full_matrix_reduction_preserves_paired_archives(self):
        """Independent negative-loss fixture exercises all nine climate/layout pairs."""
        previous_umask=os.umask(0o022);self.addCleanup(os.umask,previous_umask)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);root.chmod(0o755);paired=root/'paired'
            cfg=dict(models=['a','b','c','d'],station_ssps=['ssp126','ssp245','ssp560'],
                climate_ssps=['ssp126','ssp245','ssp585'],techs=['wind','solar'],paired_root=str(paired),
                paired=dict(ssp126='ssp126',ssp245='ssp245',ssp560='ssp585'))
            write_json(root/'inputs/campaign.json',cfg)
            sites=[];tasks=[];old_entries=[];old_rows=[];coverage=[]
            cap=np.repeat(np.array([[1.,5.],[2.,5.],[3.,5.]]),10,axis=0)
            energy=np.column_stack([-2*cap[:,0],np.full(30,np.nan)])
            common=np.array([True,False]);years=np.arange(2030,2060)
            for s,tech in itertools.product(cfg['station_ssps'],cfg['techs']):
                for snapshot,k in [(2030,1.),(2040,2.),(2050,3.)]:
                    for gid,capacity in [(1,k),(2,5.)]:
                        sites.append(dict(station_ssp=s,tech=tech,snapshot=snapshot,grid_id=gid,capacity_mw=capacity,
                            latitude=5.,longitude=10.,mapping_status='MATCHED' if gid==1 else 'NO_SUITABLE_CF_CELL',
                            distance_km=0.,mapping_alternatives=1,patch='p',loss_station_id='point',source_lat=5.,source_lon=10.))
                    coverage.append(dict(station_ssp=s,climate_ssp=cfg['paired'][s],tech=tech,snapshot=snapshot,
                        catalogue_capacity_mw=k+5,mapped_capacity_mw=k,valid_capacity_mw=k,n_catalogue=2,n_valid=1))
                for m,c in itertools.product(cfg['models'],cfg['climate_ssps']):
                    if c==cfg['paired'][s]:
                        path=paired/'station_results'/s/m/(tech+'.npz')
                        save_npz(path,years=years,grid_id=np.array([1,2]),latitude=np.array([5.,5.]),longitude=np.array([10.,10.]),
                            source_latitude=np.array([5.,5.]),source_longitude=np.array([10.,10.]),capacity_mw=cap,
                            common_support=common,mapped=common,expected_hours=np.full(30,8760),
                            net_loss_mwh=energy,normal_annual_mwh=energy*-50,generation_mwh=energy*-40)
                        old_entries.append(dict(path=str(path),sha256=digest(path),model=m,station_ssp=s,climate_ssp=c,
                            tech=tech,calendar='365_day',grid_count=2))
                        for yi,y in enumerate(years):
                            k=cap[yi,0]
                            old_rows.append(dict(model=m,station_ssp=s,climate_ssp=c,tech=tech,year=y,snapshot=y//10*10,
                                capacity_mw=k,mapped_capacity_mw=k,catalogue_capacity_mw=k+5,n_stations=1,n_mapped=1,n_catalogue=2,
                                net_loss_mwh=-2*k,normal_annual_mwh=100*k,generation_mwh=80*k,calendar='365_day',expected_hours=8760))
                    else:
                        unit='_'.join([m,s,c,tech]);path=root/'tasks'/(unit+'.json');write_json(path,{'unit':unit})
                        tasks.append(dict(unit=unit,path=str(path),model=m,station_ssp=s,climate_ssp=c,tech=tech,paired_control=False))
                        folder=root/'shards'/unit
                        save_npz(folder/'metrics.npz',grid_id=np.array([1]),years=years,capacity_mw=np.array([[1.],[2.],[3.]]),
                            valid=np.ones((30,1),bool),net_loss_per_mw=np.full((30,1),-2.),normal_generation_per_mw=np.full((30,1),100.),
                            generation_per_mw=np.full((30,1),80.),expected_count=np.full(30,2920))
                        write_json(folder/'complete.json',dict(status='COMPLETED',identity=dict(task_sha256=digest(path),code=signature()),
                            metrics_sha256=digest(folder/'metrics.npz'),calendar='365_day'))
            pd.DataFrame(sites).to_csv(paired/'catalogue.csv.gz',index=False)
            (paired/'source_data').mkdir();pd.DataFrame(old_rows).to_csv(paired/'source_data/global_annual_models.csv',index=False)
            pd.DataFrame(coverage).to_csv(paired/'source_data/capacity_coverage.csv',index=False)
            write_json(paired/'station_results/manifest.json',dict(files=old_entries))
            write_json(root/'runtime/tasks.json',tasks)
            write_json(root/'runtime/prepared.json',dict(status='COMPLETED',catalogue_sha256=digest(paired/'catalogue.csv.gz'),task_manifest_sha256=digest(root/'runtime/tasks.json')))
            write_json(root/'runtime/state.json',{t['unit']:dict(state='SUCCEEDED',exit_code='0:0') for t in tasks})
            summarize(root)
            result=json.loads((root/'runtime/completion.json').read_text())
            self.assertEqual((result['files'],result['new_files'],result['reused_paired_files'],result['annual_records']),(72,48,24,3240))
            annual=pd.read_csv(root/'source_data/global_annual_models.csv')
            np.testing.assert_allclose(annual.unit_loss_mwh_per_mw,-2.)
            np.testing.assert_allclose(annual.loss_fraction_pct,-2.)
            self.assertTrue(all(digest(e['path'])==e['sha256'] for e in old_entries))

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
