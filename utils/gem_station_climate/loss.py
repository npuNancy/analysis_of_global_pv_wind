"""Compute new LCOE loss windows directly from accepted CF and Extreme series."""
import argparse
import fcntl
import os
from pathlib import Path
import time

import netCDF4 as nc
import numpy as np

from utils.lcoe_station_climate.pipeline import read,write_json,sha,require,fingerprint
from .prepare import ROOT
from .annual import annual_metrics


def prepare(root,phase):
    source=root/phase;target=root/('loss_'+phase)
    states=read(source/'runtime/state.json')
    require(all(s['state']=='SUCCEEDED' for s in states.values()),'Extraction phase is not accepted')
    for d in ['inputs','runtime/tasks','jobs','logs','outputs']:(target/d).mkdir(parents=True,exist_ok=True)
    cfg=read(source/'inputs/campaign.json');cfg.update(root=str(target),phase='loss_'+phase,cpus=4)
    cfg['years']=[2030,2059] if phase=='future' else [2026,2029]
    write_json(target/'inputs/campaign.json',cfg)
    inputs={}
    for task in read(source/'runtime/tasks.json'):
        complete=read(task['marker']);require(complete['status']=='COMPLETED','Missing accepted extraction')
        original=read(task['path'])
        for scenario in original['mapping']['station_ssps']:
            key=(original['model'],original['climate_ssp'],scenario,original['tech'],original['patch'])
            item=inputs.setdefault(key,dict(mapping=original['mapping'],snapshots=original['snapshots']))
            item[task['product']]=[o for o in complete['outputs'] if o['station_scenario']==scenario]
    tasks=[]
    for key,item in sorted(inputs.items()):
        require('cf' in item and 'extreme' in item,'CF and event matrix mismatch')
        unit='_'.join(key);model,climate,scenario,tech,patch=key
        task=dict(unit=unit,model=model,climate_ssp=climate,station_ssp=scenario,tech=tech,patch=patch,
            phase=phase,years=list(range(cfg['years'][0],cfg['years'][1]+1)),
            windows=[[2030,2039],[2040,2049],[2050,2059]] if phase=='future' else [[2026,2029]],
            source_root=str(root),station_chunk=256,**item)
        path=target/'runtime/tasks'/(unit+'.json');write_json(path,task)
        tasks.append(dict(unit=unit,path=str(path),product='loss',model=model,climate_ssp=climate,tech=tech,
            patch=patch,n_union=item['mapping']['n_union'],marker=str(target/'runtime/units'/unit/'complete.json')))
    write_json(target/'runtime/tasks.json',tasks)
    write_json(target/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks)))
    print('Prepared',phase,len(tasks),'Loss units',flush=True)


def headers(records,years):
    result=[];dates=[];calendar=None
    for record in sorted(records,key=lambda r:r['years']):
        if record['years'][1]<years[0] or record['years'][0]>years[-1]:continue
        path=Path(record['path']);require(path.stat().st_size==record['size_bytes'],'Changed extraction')
        with nc.Dataset(path) as ds:
            t=ds['time'];cal=getattr(t,'calendar','standard')
            if calendar is None:calendar=cal
            require(cal==calendar,'Calendar changed between blocks')
            dd=nc.num2date(t[:],t.units,cal,only_use_cftime_datetimes=True)
            keep=np.flatnonzero([(years[0]<=d.year<=years[-1]) for d in dd])
            require(len(keep)>0 and np.all(np.diff(keep)==1),'Noncontiguous year selection')
            result.append(dict(path=str(path),start=int(keep[0]),stop=int(keep[-1])+1,
                               variables=record['variables']))
            dates.extend(dd[keep])
    dates=np.asarray(dates)
    hours=nc.date2num(dates,'hours since 2000-01-01',calendar)
    require(np.allclose(np.diff(hours),3,rtol=0,atol=1e-7),'Native time gaps')
    return result,dates,calendar


def load_chunk(records,begin,end,grid,tech,product):
    arrays=[]
    for record in records:
        with nc.Dataset(record['path']) as ds:
            require(np.array_equal(ds['grid_id'][begin:end],grid),'Station ordering changed')
            sl=(slice(record['start'],record['stop']),slice(begin,end))
            if product=='cf':
                arrays.append(np.ma.asarray(ds[tech+'_cf'][sl],dtype='f4').filled(np.nan))
            else:
                names=record['variables'];require(len(names)==(5 if tech=='wind' else 6),'Event definitions differ')
                shape=(record['stop']-record['start'],end-begin)
                event=np.zeros(shape,dtype=bool);valid=np.ones(shape,dtype=bool)
                for name in names:
                    var=ds[name];var.set_auto_maskandscale(False);raw=np.asarray(var[sl])
                    valid&=np.isin(raw,[0,1]);event|=raw==1
                arrays.append(np.where(valid,event,-1).astype('i1'))
    return np.concatenate(arrays,axis=0)


def run(root,unit):
    taskpath=root/'runtime/tasks'/(unit+'.json');task=read(taskpath)
    folder=root/'runtime/units'/unit;folder.mkdir(parents=True,exist_ok=True)
    identity=fingerprint(dict(task_sha256=sha(taskpath),code={p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('annual.py')]}))
    with (folder/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);marker=folder/'complete.json'
        if marker.exists():require(read(marker)['identity']==identity,'Loss identity changed');return
        require(sha(task['mapping']['path'])==task['mapping']['sha256'],'Loss spatial mapping changed')
        with np.load(task['mapping']['path']) as z:
            pos=z[task['station_ssp']+'_positions'];grid=z['grid_id'][pos];n=len(pos)
            result={k:z[k][pos] for k in ['grid_id','latitude','longitude','source_lat','source_lon']}
            cap=z[task['station_ssp']+'_capacity']
        years=np.asarray(task['years']);result['years']=years
        result['capacity_mw']=np.asarray([cap[max(i for i,s in enumerate(task['snapshots']) if s<=y)] for y in years])
        cfh,dates,calendar=headers(task['cf'],years);evh,evdates,evcalendar=headers(task['extreme'],years)
        require(calendar==evcalendar and np.array_equal(dates,evdates),'CF/Extreme native timestamps differ')
        started=time.monotonic()
        for begin in range(0,n,task['station_chunk']):
            end=min(n,begin+task['station_chunk'])
            cf=load_chunk(cfh,begin,end,grid[begin:end],task['tech'],'cf')
            events=load_chunk(evh,begin,end,grid[begin:end],task['tech'],'extreme')
            metrics,baseline=annual_metrics(cf,events,dates,years,task['windows'],3,
                Path(task['source_root'])/'inputs/reference_code')
            for key,values in metrics.items():
                if key=='expected_hours':result[key]=values;continue
                if key not in result:result[key]=np.full((len(years),n),np.nan)
                result[key][:,begin:end]=values
            if 'baseline_cf' not in result:
                result['baseline_month_hour_idx']=baseline[0]['month_hour_idx']
                result['baseline_years']=np.asarray(task['windows'])
                result['baseline_cf']=np.full((len(baseline),len(baseline[0]['month_hour_idx']),n),np.nan,dtype='f4')
                result['baseline_count']=np.zeros_like(result['baseline_cf'],dtype='u2')
            for i,base in enumerate(baseline):
                result['baseline_cf'][i,:,begin:end]=base['cf_normal']
                result['baseline_count'][i,:,begin:end]=base['count']
            print(unit,end,'/',n,'stations',flush=True)
        out=root/'outputs'/(unit+'.npz');tmp=out.with_suffix(f'.{os.getpid()}.tmp.npz')
        require(not out.exists(),'Loss output without receipt')
        np.savez_compressed(tmp,**result);tmp.replace(out)
        write_json(marker,dict(status='COMPLETED',unit=unit,identity=identity,calendar=calendar,
            job_id=os.environ.get('SLURM_JOB_ID'),account=os.environ.get('USER'),wall_seconds=time.monotonic()-started,
            outputs=[dict(path=str(out),sha256=sha(out),size_bytes=out.stat().st_size,station_count=n,years=[int(years[0]),int(years[-1])])]))


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--stage',choices=['prepare','run'],default='prepare');p.add_argument('--phase',choices=['future','transition'],default='future');p.add_argument('--unit')
    a=p.parse_args()
    if a.stage=='prepare':prepare(a.root,a.phase)
    else:require(bool(a.unit),'--unit required');run(a.root,a.unit)


if __name__=='__main__':main()
