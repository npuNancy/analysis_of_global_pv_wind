"""Calculate hourly historical CF/events and annual loss with annual GEM capacity."""
import argparse
import fcntl
import os
from pathlib import Path
import sys
import time
import warnings

import netCDF4 as nc
import numpy as np
import pandas as pd

from utils.lcoe_station_climate.pipeline import read,write_json,sha,require,fingerprint
from .prepare import ROOT
from .annual import annual_metrics


def prepare(root):
    source=root/'era5_met';target=root/'historical'
    require(all(v['state']=='SUCCEEDED' for v in read(source/'runtime/state.json').values()),'ERA5 meteorology not accepted')
    for d in ['inputs','runtime/tasks','mappings','jobs','logs','outputs']:(target/d).mkdir(parents=True,exist_ok=True)
    cfg=read(source/'inputs/campaign.json');cfg.update(root=str(target),phase='historical',cpus=4,models=['ERA5-Land'],
        climate_ssps=['historical'],station_ssps=['historical'],years=[2015,2025],snapshots=list(range(2015,2026)))
    write_json(target/'inputs/campaign.json',cfg)
    frame=pd.read_csv(source/'inputs/annual_capacity.csv.gz');union=pd.read_csv(source/'inputs/mapping.csv')
    inputs={}
    for task in read(source/'runtime/tasks.json'):
        done=read(task['marker']);require(done['status']=='COMPLETED','Incomplete meteorology file')
        original=read(task['path']);inputs.setdefault(original['var'],[]).append(done['outputs'][0])
    for rows in inputs.values():rows.sort(key=lambda r:r['path'])
    tasks=[]
    for tech,g in frame.groupby('technology'):
        sites=g.sort_values('grid_id').drop_duplicates('grid_id')
        capacities=g.pivot(index='grid_id',columns='year',values='capacity_mw').reindex(columns=cfg['snapshots']).fillna(0)
        for begin in range(0,len(sites),256):
            tile=f'{begin//256:04}';unit=f'ERA5_{tech}_{tile}';s=sites.iloc[begin:begin+256]
            mapping=target/'mappings'/(unit+'.npz')
            positions=pd.Index(union.grid_id).get_indexer(s.grid_id)
            require((positions>=0).all(),'ERA5 site missing in meteorology')
            np.savez_compressed(mapping,grid_id=s.grid_id.to_numpy(),latitude=s.latitude.to_numpy(),longitude=s.longitude.to_numpy(),
                source_lat=(90-union.source_iy.iloc[positions].to_numpy()/10),source_lon=union.source_ix.iloc[positions].to_numpy()/10,
                positions=positions,capacity_mw=capacities.loc[s.grid_id].to_numpy().T,years=np.asarray(cfg['snapshots']))
            variables=['t2m','u10','v10','rh']+(['ssrd','tp'] if tech=='solar' else [])
            task=dict(unit=unit,tech=tech,tile=tile,source_root=str(root),mapping=str(mapping),mapping_sha256=sha(mapping),
                inputs={v:inputs[v] for v in variables},years=cfg['snapshots'],
                reference_sha256=sha(root/'inputs/reference_code_manifest.json'),dependency_sha256=sha(root/'inputs/windpowerlib_manifest.json'))
            path=target/'runtime/tasks'/(unit+'.json');write_json(path,task)
            tasks.append(dict(unit=unit,path=str(path),product='historical',model='ERA5-Land',climate_ssp='historical',tech=tech,
                patch=tile,n_union=len(s),marker=str(target/'runtime/units'/unit/'complete.json')))
    write_json(target/'runtime/tasks.json',tasks)
    write_json(target/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks)))
    print('Prepared',len(tasks),'historical CF/Extreme/Loss units',flush=True)


def meteorology(task,mapping):
    values={};reference=None
    for var,records in task['inputs'].items():
        pieces=[];times=[]
        for record in records:
            require(Path(record['path']).stat().st_size==record['size_bytes'],'Changed ERA5 extraction')
            with nc.Dataset(record['path']) as ds:
                require(np.array_equal(ds['grid_id'][mapping['positions']],mapping['grid_id']),'ERA5 station order')
                pieces.append(np.ma.asarray(ds['value'][:,mapping['positions']],dtype='f4').filled(np.nan))
                times.append(np.asarray(ds['time'][:]))
        axis=np.concatenate(times)
        if reference is None:reference=axis
        require(np.array_equal(axis,reference),'ERA5 variable times differ')
        values[var]=np.concatenate(pieces,axis=0)
    require(np.all(np.diff(reference)==3600),'ERA5 hourly time discontinuity')
    return values,reference,pd.to_datetime(reference,unit='s')


def write_native(path,mapping,times,variables,task,identity):
    tmp=path.with_suffix(f'.{os.getpid()}.tmp.nc')
    with nc.Dataset(tmp,'w') as ds:
        ds.createDimension('time',len(times));ds.createDimension('station',len(mapping['grid_id']));ds.createDimension('snapshot',11)
        tv=ds.createVariable('time','i8',('time',));tv[:]=times;tv.units='seconds since 1970-01-01';tv.calendar='proleptic_gregorian'
        ds.createVariable('snapshot_year','i4',('snapshot',))[:]=mapping['years']
        for name,source,dtype in [('grid_id','grid_id','i8'),('lat','latitude','f8'),('lon','longitude','f8'),
                                  ('source_grid_lat','source_lat','f8'),('source_grid_lon','source_lon','f8')]:
            ds.createVariable(name,dtype,('station',))[:]=mapping[source]
        ids=np.array([f'gem:historical:{task["tech"]}:{g}' for g in mapping['grid_id']],dtype=object)
        ds.createVariable('station_id',str,('station',))[:]=ids
        cap=ds.createVariable('capacity_mw','f8',('snapshot','station'));cap[:]=mapping['capacity_mw'];cap.units='MW'
        cap.capacity_basis='MWp/DC' if task['tech']=='solar' else 'MW'
        for name,values in variables.items():
            event=name.startswith('signal_');var=ds.createVariable(name,'i1' if event else 'f4',('time','station'),
                fill_value=np.int8(-127) if event else np.float32(np.nan),zlib=True,complevel=1,chunksizes=(168,len(ids)))
            var[:]=values;var.units='1'
            if event:var.flag_values=np.array([0,1],dtype='i1');var.flag_meanings='no_event event'
        ds.setncatts(dict(schema='gem-historical-station-v1',identity=identity,model='ERA5-Land',climate_scenario='historical',
            station_scenario='historical',tech=task['tech'],activation_mask='off',capacity_semantics='annual_year_end_stock',
            time_semantics='native hourly ERA5-Land valid_time',baseline_years='2015-2024',
            loss_window='2015-2025',source_mapping='same corrected 0.1-degree raster cell'))
    tmp.replace(path)
    return dict(path=str(path),size_bytes=path.stat().st_size,sha256=sha(path),station_count=len(mapping['grid_id']),
                years=[2015,2025],variables=list(variables),time_count=len(times),calendar='proleptic_gregorian')


def run(root,unit):
    path=root/'runtime/tasks'/(unit+'.json');task=read(path);shared=Path(task['source_root'])
    folder=root/'runtime/units'/unit;folder.mkdir(parents=True,exist_ok=True)
    identity=fingerprint(dict(task_sha256=sha(path),code={p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('annual.py')]}))
    with (folder/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);marker=folder/'complete.json'
        if marker.exists():require(read(marker)['identity']==identity,'Historical identity changed');return
        require(sha(task['mapping'])==task['mapping_sha256'],'Historical mapping changed')
        sys.path[:0]=[str(shared/'inputs/python_modules'),str(shared/'inputs/reference_code/cf'),str(shared/'inputs/reference_code/extreme')]
        import cf_physics as physics
        import registry
        from tools import common
        with np.load(task['mapping']) as z:mapping={k:z[k] for k in z.files}
        started=time.monotonic();raw,times,dates=meteorology(task,mapping);tech=task['tech']
        weather=dict(temp_C=raw['t2m']-273.15,wind_ms=np.hypot(raw['u10'],raw['v10']).astype('f4'),rh_pct=raw['rh'])
        valid_cf=np.isfinite(raw['u10']) & np.isfinite(raw['v10'])
        if tech=='wind':
            ws,power,rated=physics._get_power_curve_arrays()
            cf=physics.compute_wind_cf_chunk(raw['u10'],raw['v10'],ws,power,rated,physics.power_law_ratio())
        else:
            weather.update(rsds=raw['ssrd'],precip_mmh=raw['tp'])
            valid_cf &= np.isfinite(raw['t2m']) & np.isfinite(raw['ssrd'])
            cf=np.empty_like(raw['ssrd']);doy=dates.dayofyear.to_numpy();hour=dates.hour.to_numpy()
            for k in range(cf.shape[1]):
                cf[:,k]=physics.compute_solar_cf_chunk(raw['ssrd'][:,k:k+1,None]/1000,
                    weather['temp_C'][:,k:k+1,None],raw['u10'][:,k:k+1,None],raw['v10'][:,k:k+1,None],
                    doy,hour,np.array([mapping['source_lat'][k]]),np.array([mapping['source_lon'][k]])).reshape(-1)
        cf[~valid_cf]=np.nan
        masks=registry.simple_signals(tech,weather,skip_missing=True)
        valid={name:np.logical_and.reduce([np.isfinite(weather[k]) for k in registry.REQUIRED[tech][name]]) for name in masks}
        pseudo=pd.DatetimeIndex([pd.Timestamp(2000,d.month,d.day,d.hour) for d in dates])
        resource=weather[registry.LOWRES_RESOURCE[tech]]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            rolled=common.roll_centered(resource,24)
            reference=(dates.year>=2015)&(dates.year<=2024)
            clim=common.clim288(rolled,pseudo,reference)
            anomaly=rolled-clim[pseudo.month.to_numpy()-1,pseudo.hour.to_numpy()]
            threshold=np.nanpercentile(anomaly[reference],5,axis=0,method='linear')
        night=(common.solar_elevation(mapping['source_lat'],mapping['source_lon'],pseudo)<=0).T if tech=='solar' else None
        masks['low_resource']=common.low_resource_from_anomaly(anomaly,threshold,night=night)
        valid['low_resource']=np.isfinite(anomaly)&np.isfinite(threshold)[None,:]
        selected=(dates.year>=2015)&(dates.year<=2025)
        cf=cf[selected];output_times=times[selected];output_dates=dates[selected]
        event=np.zeros(cf.shape,dtype=bool);good=np.ones(cf.shape,dtype=bool);signals={}
        for name,mask in masks.items():
            event|=mask[selected];good&=valid[name][selected]
            signals['signal_'+name]=np.where(valid[name][selected],mask[selected],-127).astype('i1')
        union=np.where(good,event,-1).astype('i1')
        result,baselines=annual_metrics(cf,union,output_dates,np.arange(2015,2026),[[2015,2025]],1,shared/'inputs/reference_code')
        result.update({k:v for k,v in mapping.items() if k!='positions'})
        result.update(baseline_cf=baselines[0]['cf_normal'][None],baseline_count=baselines[0]['count'][None],
                      baseline_month_hour_idx=baselines[0]['month_hour_idx'],baseline_years=np.array([[2015,2025]]))
        out=root/'outputs'/unit;out.mkdir(parents=True,exist_ok=True)
        cf_record=write_native(out/'cf_2015-2025.nc',mapping,output_times,{tech+'_cf':cf},task,identity)
        ev_record=write_native(out/'signals_2015-2025.nc',mapping,output_times,signals,task,identity)
        annual=out/'annual.npz';tmp=annual.with_suffix(f'.{os.getpid()}.tmp.npz');np.savez_compressed(tmp,**result);tmp.replace(annual)
        records=[dict(product='cf',**cf_record),dict(product='extreme',**ev_record),dict(product='loss',path=str(annual),
            size_bytes=annual.stat().st_size,sha256=sha(annual),station_count=len(mapping['grid_id']),years=[2015,2025])]
        write_json(marker,dict(status='COMPLETED',identity=identity,unit=unit,model='ERA5-Land',calendar='proleptic_gregorian',
            job_id=os.environ.get('SLURM_JOB_ID'),account=os.environ.get('USER'),wall_seconds=time.monotonic()-started,outputs=records))
        print('COMPLETED',unit,round(time.monotonic()-started,1),'seconds',flush=True)


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--stage',choices=['prepare','run'],default='prepare');p.add_argument('--unit')
    a=p.parse_args()
    if a.stage=='prepare':prepare(a.root)
    else:require(bool(a.unit),'--unit required');run(a.root,a.unit)


if __name__=='__main__':main()
