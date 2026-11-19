"""Small native-calendar fixtures for LCOE station extraction and restart contracts."""
import json
import fcntl
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import netCDF4 as nc
import numpy as np
from utils.lcoe_station_climate import pipeline as p
from scnet.create_lcoe_station_climate_jobs import generate
from scnet.lcoe_station_climate import control


class ExtractionTests(unittest.TestCase):
    def fixture(self,root,product):
        src=root/'source.nc'
        with nc.Dataset(src,'w') as ds:
            for name,n in [('time',8),('lat',3),('lon',4)]:ds.createDimension(name,n)
            ds.createVariable('lat','f8',('lat',))[:]=[1.,2.,3.]
            ds.createVariable('lon','f8',('lon',))[:]=[350.,351.,352.,353.]
            t=ds.createVariable('time','f8',('time',));t[:]=np.arange(8)*3+1.5;t.units='hours since 2030-01-01';t.calendar='360_day'
            name='wind_cf' if product=='cf' else 'signal_icing'
            v=ds.createVariable(name,'f4' if product=='cf' else 'i1',('time','lat','lon'),fill_value=-999. if product=='cf' else -127,chunksizes=(3,2,2))
            x=np.arange(96).reshape(8,3,4)/100 if product=='cf' else np.arange(96).reshape(8,3,4)%2
            v[:]=x;v[2,0,1]=v._FillValue
        mapping=dict(grid_id=np.array([10,20,30]),cf_lat_index=np.array([0,2,1]),cf_lon_index=np.array([1,3,0]),
            latitude=np.array([1.05,3.05,2.05]),longitude=np.array([-8.95,-6.95,-9.95]),
            source_lat=np.array([1.,3.,2.]),source_lon=np.array([-9.,-7.,-10.]),distance_km=np.ones(3))
        for s,pos in [('ssp126',[0,1,2]),('ssp560',[0,2])]:
            mapping[s+'_positions']=np.array(pos);mapping[s+'_capacity']=np.ones((3,len(pos)))
            mapping[s+'_activation']=np.full(len(pos),2040)
        stat=src.stat();record=dict(path=str(src),start_year=2030,end_year=2030,size_bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,identity='source-fixture')
        task=dict(unit='unit',product=product,model='test',climate_ssp='ssp585',tech='wind',patch='R01C01',years=[2030,2030],snapshots=[2030,2040,2050],time_chunk=3,mapping=dict(station_ssps=['ssp126','ssp560']))
        return task,record,mapping

    def test_cf_values_calendar_capacities_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,record,mapping=self.fixture(root,'cf')
            result=p.extract_block(root,task,record,mapping,'identity')
            self.assertEqual(len(result['outputs']),2)
            for item in result['outputs']:
                with nc.Dataset(item['path']) as ds:
                    self.assertEqual(ds['time'].calendar,'360_day')
                    self.assertEqual(ds.activation_mask,'off')
                    self.assertEqual(ds['capacity_mw'].shape,(3,item['station_count']))
                    self.assertTrue(np.ma.is_masked(ds['wind_cf'][2,0]))
                    self.assertFalse(np.ma.is_masked(ds['wind_cf'][0,0]))
                    self.assertEqual(ds['activation_year'][0],2040)
            self.assertEqual(p.extract_block(root,task,record,mapping,'identity'),result)
            with self.assertRaises(ValueError):p.extract_block(root,task,record,mapping,'changed')

    def test_events_preserve_raw_fill_and_flags(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,record,mapping=self.fixture(root,'extreme')
            result=p.extract_block(root,task,record,mapping,'identity')
            with nc.Dataset(result['outputs'][0]['path']) as ds:
                ds.set_auto_maskandscale(False)
                self.assertEqual(ds['signal_icing'][2,0],-127)
                self.assertEqual(set(np.unique(ds['signal_icing'][:])),{-127,0,1})

    def test_campaign_station_identity_and_capacity_basis(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,record,mapping=self.fixture(root,'cf')
            task.update(station_prefix='dispatch2025',capacity_basis={'wind':'MW'})
            result=p.extract_block(root,task,record,mapping,'identity')
            with nc.Dataset(result['outputs'][0]['path']) as ds:
                self.assertEqual(ds.schema,'dispatch2025-station-climate-v1')
                self.assertTrue(str(ds['station_id'][0]).startswith('dispatch2025:ssp126:wind:'))
                self.assertEqual(ds['capacity_mw'].capacity_basis,'MW')

    def test_climate_account_routing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'inputs').mkdir();(root/'runtime').mkdir()
            account=dict(username='a',max_active=20,submit_lock=str(root/'a.lock'),climate_ssps=['ssp126'])
            (root/'inputs/campaign.json').write_text(json.dumps(dict(accounts=[account])))
            tasks=[dict(unit='other',climate_ssp='ssp245',n_union=100,marker=str(root/'other')),
                   dict(unit='ours',climate_ssp='ssp126',n_union=10,marker=str(root/'ours'))]
            (root/'runtime/tasks.json').write_text(json.dumps(tasks))
            (root/'runtime/pilot_accepted.json').write_text('{}')
            def command(args):
                if args[0]=='id':return 'a'
                if args[0]=='squeue':return ''
                raise AssertionError(args)
            calls=[]
            def sbatch(args,**kwargs):
                calls.append(Path(args[-1]).stem)
                return SimpleNamespace(returncode=0,stdout='10001',stderr='')
            with patch.object(control,'command',command),patch.object(control.subprocess,'run',sbatch),patch('sys.argv',['control','--root',str(root),'--submit']):
                control.main()
            self.assertEqual(calls,['ours'])
            state=json.loads((root/'runtime/state.json').read_text())
            self.assertEqual(state['other']['state'],'NOT_SUBMITTED')

    def test_incremental_selection_and_single_station_output(self):
        cfg=dict(climate_ssps=["ssp126","ssp585"],station_ssps=["ssp126","ssp560"],
                 station_ssps_by_climate={"ssp126":["ssp560"],"ssp585":["ssp126","ssp560"]})
        self.assertEqual(set(p.scenario_pairs(cfg)),
                         {("ssp126","ssp560"),("ssp585","ssp126"),("ssp585","ssp560")})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,record,mapping=self.fixture(root,"cf")
            task["mapping"]["station_ssps"]=["ssp560"]
            task["siting_commits"]={"ssp560":"accepted-commit"}
            result=p.extract_block(root,task,record,mapping,"incremental")
            self.assertEqual(len(result["outputs"]),1)
            self.assertEqual(result["outputs"][0]["station_scenario"],"ssp560")
            with nc.Dataset(result["outputs"][0]["path"]) as ds:
                self.assertEqual(ds.siting_commit,"accepted-commit")
                self.assertEqual(ds["grid_id"][:].tolist(),[10,30])
        for selection in [{"ssp126":["ssp560"]},
                          {"ssp126":["bad"],"ssp585":["ssp560"]},
                          {"ssp126":["ssp560","ssp560"],"ssp585":["ssp560"]}]:
            with self.assertRaises(ValueError):
                p.scenario_pairs({**cfg,"station_ssps_by_climate":selection})

    def test_prepare_selected_matrix_and_mapping_count(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for folder in ["inputs","catalogs","mappings","runtime/tasks"]:
                (root/folder).mkdir(parents=True,exist_ok=True)
            cfg=dict(root=str(root),station_ssps=["ssp126","ssp585"],climate_ssps=["ssp126","ssp585"],
                     station_ssps_by_climate={"ssp126":["ssp585"],"ssp585":["ssp126","ssp585"]},
                     snapshots=[2030,2040,2050],years=[2030,2059],time_chunk=240,
                     models=["model"],products=["cf","extreme"],techs=["wind"])
            p.write_json(root/"inputs/campaign.json",cfg)
            for scenario,grid in [("ssp126",10),("ssp585",20)]:
                path=root/"inputs/stations"/scenario;path.mkdir(parents=True)
                for year in cfg["snapshots"]:
                    pd.DataFrame([dict(scenario=scenario,technology="wind",year=year,grid_id=grid,
                        latitude=1.,longitude=2.,capacity_mw=1.)]).to_csv(path/f"stations_01deg_{year}.csv",index=False)
            pd.DataFrame([dict(tech="wind",grid_id=g,latitude=1.,longitude=2.,patch="R01C01",
                mapping_status="MATCHED",cf_lat_index=0,cf_lon_index=i,source_lat=1.,source_lon=2.,
                distance_km=0.) for i,g in enumerate([10,20])]).to_csv(root/"inputs/loss_mapping.csv.gz",index=False)
            source=root/"source";source.write_text("source metadata fixture")
            records={}
            for product in cfg["products"]:
                p.write_json(root/"inputs"/(product+"_index.json"),{})
                for climate in cfg["climate_ssps"]:
                    records[product,"model",climate,"wind","R01C01"]=[
                        dict(path=str(source),start_year=2030,end_year=2059)]
            with patch.object(p,"source_records",return_value=records):
                p.prepare(root,root/"inputs/campaign.json")
            prepared=p.read(root/"runtime/prepared.json")
            self.assertEqual(prepared["units"],4)
            self.assertEqual(prepared["mapping_count"],2)
            pairs=set()
            for item in p.read(root/"runtime/tasks.json"):
                task=p.read(item["path"])
                pairs.update((task["climate_ssp"],s) for s in task["mapping"]["station_ssps"])
                self.assertEqual(task["mapping"]["n_union"],2)
            self.assertEqual(pairs,set(p.scenario_pairs(cfg)))

    def test_coordinates_reject_different_grid(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,record,mapping=self.fixture(root,'cf');mapping['source_lat'][0]+=1
            with self.assertRaises(ValueError):p.extract_block(root,task,record,mapping,'identity')

    def test_source_changes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,record,_=self.fixture(root,'cf');record['size_bytes']+=1
            with self.assertRaises(ValueError):p.check_source(record)

    def test_generator_dry_run_and_collision(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config=dict(root=str(root/'data'),repo=str(root/'code'),activate='/env/bin/activate',cpus=2,partition='wzhctest')
            jobs=root/'jobs';tasks=[dict(unit='cf_A_ssp126_wind_R01C01')]
            self.assertEqual(len(generate(config,tasks,'run',jobs,True)),1);self.assertFalse(jobs.exists())
            generated=generate(config,tasks,'run',jobs);body=Path(generated[0]['script']).read_text()
            self.assertIn('source /env/bin/activate',body)
            with self.assertRaises(ValueError):generate(config,tasks*2,'run',jobs)
            with self.assertRaises(FileExistsError):generate(config,tasks,'run',jobs,cpus=3)

    def test_submission_releases_global_lock_and_respects_other_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'inputs').mkdir();(root/'runtime').mkdir()
            accounts=[dict(username=u,max_active=20,submit_lock=str(root/(u+'.lock'))) for u in ['a','b']]
            (root/'inputs/campaign.json').write_text(json.dumps(dict(accounts=accounts)))
            tasks=[dict(unit='unit'+str(i),n_union=10,marker=str(root/('marker'+str(i)))) for i in range(4)]
            (root/'runtime/tasks.json').write_text(json.dumps(tasks))
            (root/'runtime/pilot_accepted.json').write_text('{}')
            submitted=[]
            for user in ['a','b']:
                def command(args):
                    if args[0]=='id':return user
                    if args[0]=='squeue':return '\n'.join(f'{j}|RUNNING' for j in range(1,20))
                    if args[0]=='sacct':return '\n'.join(j+('|COMPLETED' if j=='10001' else '|RUNNING') for j in args[2].split(','))
                    raise AssertionError(args)
                def sbatch(args,**kwargs):
                    with (root/'runtime/queue.lock').open('a') as lock:
                        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        state=json.loads((root/'runtime/state.json').read_text())
                        unit=Path(args[-1]).stem
                        self.assertEqual(state[unit]['state'],'SUBMITTING')
                        self.assertEqual(state[unit]['account'],user)
                    submitted.append(unit)
                    return SimpleNamespace(returncode=0,stdout=str(10000+len(submitted)),stderr='')
                with patch.object(control,'command',command),patch.object(control.subprocess,'run',sbatch),patch('sys.argv',['control','--root',str(root),'--submit']):
                    control.main()
            self.assertEqual(submitted,['unit0','unit1','unit2'])
            state=json.loads((root/'runtime/state.json').read_text())
            self.assertEqual(state['unit3']['state'],'NOT_SUBMITTED')
            before=(root/'runtime/state.json').read_bytes()
            (root/'marker0').write_text('{"status":"COMPLETED"}')
            def inspect(args):
                if args[0]=='id':return 'a'
                if args[0]=='squeue':return ''
                if args[0]=='sacct':return '10001|COMPLETED|0:0|10|2048K'
                raise AssertionError(args)
            account_before=(root/'runtime/account_a.json').read_bytes()
            with patch.object(control,'command',inspect),patch('sys.argv',['control','--root',str(root),'--read-only']),patch('builtins.print') as output:
                control.main()
            result=json.loads(output.call_args.args[0])
            self.assertEqual(result['units']['unit0']['state'],'SUCCEEDED')
            self.assertEqual((root/'runtime/state.json').read_bytes(),before)
            self.assertEqual((root/'runtime/account_a.json').read_bytes(),account_before)
            state['unit3'].update(state='SUBMISSION_FAILED',account='a',evidence='script unreadable')
            (root/'runtime/state.json').write_text(json.dumps(state))
            with patch.object(control,'command',inspect),patch('sys.argv',['control','--root',str(root),'--retry','unit3']):
                control.main()
            retried=json.loads((root/'runtime/state.json').read_text())['unit3']
            self.assertEqual(retried['state'],'NOT_SUBMITTED')
            self.assertEqual(retried['attempt'],0)
            self.assertNotIn('job_id',retried)

if __name__=='__main__':unittest.main()
