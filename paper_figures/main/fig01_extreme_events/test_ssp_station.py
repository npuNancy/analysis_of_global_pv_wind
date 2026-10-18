"""Independent checks for SSP contrast semantics and capacity-weighted runs."""
import unittest
import tempfile
import numpy as np
import pandas as pd
from .analyze_ssp_station import KEY, differences, climate_deployment, decomposition, additive_overlap
from .grid_event_dynamics import Runs, FastRuns, build_kernel

class StationSSPTests(unittest.TestCase):
    def setUp(self):
        rows=[]
        for m in ["A","B","C","D"]:
            for i,c in enumerate(["ssp126","ssp245","ssp585"]):
                for j,s in enumerate(["ssp126","ssp245","ssp585"]):
                    rows.append(dict(model=m,climate_ssp=c,station_ssp=s,tech="wind",snapshot=2050,region="global:GLOBAL",event="all",metric="exposure_days",value=2*i+3*j+i*j))
        self.long=pd.DataFrame(rows)
    def test_fixed_and_paired(self):
        d=differences(self.long)
        q=d[d.high.eq("ssp585")&d.low.eq("ssp126")&d.model.eq("A")].set_index("comparison").difference
        self.assertEqual(q["paired"],14)
        self.assertEqual(q["ssp126"],4)
        self.assertEqual(q["ssp585"],8)
    def test_climate_deployment(self):
        d=climate_deployment(self.long)
        q=d[d.high.eq("ssp585")&d.low.eq("ssp126")&d.model.eq("A")].iloc[0]
        self.assertEqual(q.climate_component,6)
        self.assertEqual(q.deployment_component,8)
        self.assertEqual(q.paired_difference,14)
    def test_overlap(self):
        u=self.long.copy();h=self.long.assign(event="high_temp",value=10);l=self.long.assign(event="low_resource",value=7)
        x=additive_overlap(pd.concat([u,h,l]),["exposure_days"])
        self.assertTrue(np.array_equal(x[x.event.eq("overlap_correction")].value.to_numpy(),u.value.to_numpy()-17))
    def test_frequency_duration_identity(self):
        c=self.long.drop(columns=["metric","value"])
        index=c.climate_ssp.map({"ssp126":1.,"ssp245":2.,"ssp585":3.})
        c["complete_frequency_per_year"]=index;c["mean_complete_hours"]=index*6
        c["censored_exposure_days"]=.5*index
        c["exposure_days"]=index*index*6/24+c.censored_exposure_days
        d,error=decomposition(c)
        self.assertLess(error,1e-10)
        self.assertTrue(np.allclose(d.frequency_days+d.duration_days+d.censored_days,d.net_days))
    def test_weighted_runs_and_integral(self):
        raw=np.array([[0,0],[1,0],[1,1],[0,1],[0,0],[1,0],[0,0]],bool)
        valid=np.ones_like(raw);cap=np.array([1.,9.]);ids=np.zeros((1,2),int)
        with tempfile.TemporaryDirectory() as t:
            fast=FastRuns(1,2,cap,ids,1,100,build_kernel(t));ref=Runs(1,2,cap,ids,1,100)
            areas=[]
            for a,b in [(0,2),(2,5),(5,7)]:
                affected,_=fast.consume([raw[a:b]],valid[a:b]);areas.append(affected)
                ref.consume([raw[a:b]],valid[a:b])
            fast.finish_year();fast.finish();ref.finish_year();ref.finish()
            self.assertTrue(np.array_equal(fast.stats,ref.stats))
            self.assertTrue(np.allclose(fast.hist,ref.hist))
            self.assertAlmostEqual(np.concatenate(areas).sum(),21)
            self.assertEqual(fast.stats[1,0].tolist(),[2,1])
            self.assertAlmostEqual(fast.hist[0,0,2],10)
    def test_no_event_duration_undefined(self):
        c=self.long.drop(columns=["metric","value"]).assign(complete_frequency_per_year=0.,mean_complete_hours=np.nan,censored_exposure_days=0.,exposure_days=0.)
        d,_=decomposition(c)
        self.assertTrue(d.frequency_days.isna().all())

    def test_merge_before_quantiles(self):
        import xarray as xr
        from pathlib import Path
        from .summarize_ssp_station_dynamics import reduce_sync
        from paper_figures.config import EVENTS
        events=["all",*EVENTS["wind"]]
        with tempfile.TemporaryDirectory() as tmp:
            folders=[]
            for i,(cap,series) in enumerate([(1.,[1,1,0,0]),(9.,[0,0,9,9])]):
                folder=Path(tmp)/str(i);folder.mkdir();folders.append(folder)
                affected=np.tile(np.array(series)[:,None,None],(1,len(events),1))
                ds=xr.Dataset(dict(affected_capacity_mw=(("time","event","region"),affected),valid_capacity_mw=(("time","region"),np.full((4,1),cap))),coords=dict(time=np.arange(4)*10800,event=events,region=["global:GLOBAL"]))
                ds.time.attrs["calendar"]="365_day"
                ds.to_netcdf(folder/"sync_2050.nc")
                h=np.zeros((len(events),1,4));h[:,:,2]=cap
                xr.Dataset(dict(capacity_event_count=(("event","region","length_steps"),h)),coords=dict(event=events,region=["global:GLOBAL"],length_steps=np.arange(4))).to_netcdf(folder/"duration_hist_2050.nc")
            sub=pd.DataFrame(dict(region=["global:GLOBAL"]*len(events),event=events,capacity_mw=10.,observed_steps=20.,complete_count=10.))
            rows,_=reduce_sync(Path(tmp),"wind","A","ssp126","ssp126",2050,sub,folders)
            self.assertEqual(rows[0]["p95_capacity_pct"],90.)
            self.assertEqual(rows[0]["mean_observed_capacity_pct"],50.)
            self.assertEqual(rows[0]["p90_complete_hours"],6.)
            self.assertEqual(rows[0]["above20_longest_observed_hours"],6)

if __name__=="__main__":unittest.main()
