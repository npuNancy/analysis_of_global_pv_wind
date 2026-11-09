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
            tasks=[dict(unit='unit'+str(i),n_union=10,marker=str(root/('marker'+str(i)))) for i in range(3)]
            (root/'runtime/tasks.json').write_text(json.dumps(tasks))
            (root/'runtime/pilot_accepted.json').write_text('{}')
            submitted=[]
            for user in ['a','b']:
                def command(args):
                    if args[0]=='id':return user
                    if args[0]=='squeue':return '\n'.join(f'{j}|RUNNING' for j in range(1,20))
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
            self.assertEqual(submitted,['unit0','unit1'])
            state=json.loads((root/'runtime/state.json').read_text())
            self.assertEqual(state['unit2']['state'],'NOT_SUBMITTED')

if __name__=='__main__':unittest.main()
