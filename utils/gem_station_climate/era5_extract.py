"""Extract native hourly ERA5-Land meteorology at the historical GEM grid cells."""
import argparse
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import time

import netCDF4 as nc
import numpy as np
import pandas as pd

from utils.lcoe_station_climate.pipeline import read,write_json,sha,require,fingerprint
from .prepare import ROOT

SOURCE=Path('/work/home/acbw9wpn5k/bcsd/data/ERA5_land/global')
VARIABLES=['t2m','u10','v10','ssrd','tp','rh']


def previous(year,month):return (year-1,12) if month==1 else (year,month-1)


def prepare(root):
    target=root/'era5_met'
    for d in ['inputs','runtime/tasks','jobs','logs','outputs']:(target/d).mkdir(parents=True,exist_ok=True)
    frames=[pd.read_csv(p,usecols=['technology','grid_id','latitude','longitude','year','capacity_mw'])
            for p in sorted((root/'inputs/stations/historical_snapshot').glob('stations_01deg_*.csv'))]
    require(len(frames)==11,'Historical station year count')
    table=pd.concat(frames,ignore_index=True)
    table.to_csv(target/'inputs/annual_capacity.csv.gz',index=False)
    union=table.sort_values('grid_id').drop_duplicates('grid_id')[['grid_id','latitude','longitude']].copy()
    union['source_iy']=union.grid_id//3600
    union['source_ix']=(union.grid_id%3600+1800)%3600
    union.to_csv(target/'inputs/mapping.csv',index=False)
    cfg=read(root/'future/inputs/campaign.json')
    cfg.update(root=str(target),phase='era5_met',cpus=2)
    write_json(target/'inputs/campaign.json',cfg)
    periods=[(2014,12)]+[(y,m) for y in range(2015,2026) for m in range(1,13)]
    tasks=[]
    for year,month in periods:
        for var in VARIABLES:
            unit=f'era5_{var}_{year}_{month:02}'
            source=SOURCE/var/f'{var}_{year}_{month:02}.nc';st=source.stat()
            task=dict(unit=unit,year=year,month=month,var=var,source=str(source),size_bytes=st.st_size,mtime_ns=st.st_mtime_ns,
                      mapping=str(target/'inputs/mapping.csv'),mapping_sha256=sha(target/'inputs/mapping.csv'))
            if var in ['ssrd','tp']:
                py,pm=previous(year,month);prev=SOURCE/var/f'{var}_{py}_{pm:02}.nc';ps=prev.stat()
                task.update(previous=str(prev),previous_size=ps.st_size,previous_mtime_ns=ps.st_mtime_ns)
            path=target/'runtime/tasks'/(unit+'.json');write_json(path,task)
            tasks.append(dict(unit=unit,path=str(path),product='era5',model='ERA5-Land',climate_ssp='historical',tech=var,
                patch=f'{year}_{month:02}',n_union=len(union),marker=str(target/'runtime/units'/unit/'complete.json')))
    write_json(target/'runtime/tasks.json',tasks)
    write_json(target/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks),station_cells=len(union)))
    print('ERA5',len(tasks),'units',len(union),'cells',flush=True)


def run(root,unit):
    taskpath=root/'runtime/tasks'/(unit+'.json');task=read(taskpath)
    folder=root/'runtime/units'/unit;folder.mkdir(parents=True,exist_ok=True)
    identity=fingerprint(dict(task_sha256=sha(taskpath),code_sha256=sha(__file__)))
    with (folder/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker=folder/'complete.json'
        if marker.exists():
            done=read(marker);require(done['identity']==identity,'ERA5 cached identity')
            require(all(Path(o['path']).stat().st_size==o['size_bytes'] for o in done['outputs']),'ERA5 cached size')
            print('Already completed',unit);return
        require(sha(task['mapping'])==task['mapping_sha256'],'Changed ERA5 mapping')
        mapping=pd.read_csv(task['mapping']);iy=mapping.source_iy.to_numpy();ix=mapping.source_ix.to_numpy()
        source=Path(task['source']);st=source.stat()
        require((st.st_size,st.st_mtime_ns)==(task['size_bytes'],task['mtime_ns']),'Changed ERA5 source')
        out=root/'outputs'/task['var']/f'{task["year"]}_{task["month"]:02}.nc'
        require(not out.exists(),'ERA5 output has no matching receipt')
        out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix(f'.{os.getpid()}.tmp.nc')
        start_time=time.monotonic()
        with ExitStack() as stack:
            src=stack.enter_context(nc.Dataset(source));var=src[task['var']]
            times=np.asarray(src['valid_time'][:]);dates=nc.num2date(times,src['valid_time'].units,src['valid_time'].calendar)
            require(np.all(np.diff(times)==3600),'ERA5 hourly time gaps')
            lat=np.asarray(src['latitude'][:]);lon=np.asarray(src['longitude'][:])
            require(np.allclose(lat[iy],90-iy/10,rtol=0,atol=2e-5),'ERA5 latitude mismatch')
            require(np.allclose(lon[ix],ix/10,rtol=0,atol=2e-5),'ERA5 longitude mismatch')
            previous_var=None
            if 'previous' in task:
                ps=Path(task['previous']).stat()
                require((ps.st_size,ps.st_mtime_ns)==(task['previous_size'],task['previous_mtime_ns']),'Changed ERA5 halo')
                prev=stack.enter_context(nc.Dataset(task['previous']));previous_var=prev[task['var']]
                require(int(prev['valid_time'][-1])+3600==int(times[0]),'ERA5 month halo gap')
            dst=stack.enter_context(nc.Dataset(tmp,'w'))
            dst.createDimension('time',len(times));dst.createDimension('station',len(mapping))
            tv=dst.createVariable('time','i8',('time',));tv[:]=times;tv.units=src['valid_time'].units;tv.calendar=src['valid_time'].calendar
            for name,values,kind in [('grid_id',mapping.grid_id,'i8'),('source_lat',lat[iy],'f8'),('source_lon',lon[ix],'f8')]:
                dst.createVariable(name,kind,('station',))[:]=values
            target=dst.createVariable('value','f4',('time','station'),zlib=True,complevel=1,
                chunksizes=(min(168,len(times)),min(256,len(mapping))),fill_value=np.float32(np.nan))
            target.units={'ssrd':'W m-2','tp':'mm h-1'}.get(task['var'],getattr(var,'units',''))
            dst.setncatts(dict(schema='gem-era5-hourly-v1',model='ERA5-Land',variable=task['var'],source_file=str(source),
                identity=identity,time_semantics='native hourly valid_time; accumulated variables differenced with reset at 01 UTC',
                mapping_method='same_corrected_0.1_degree_raster_cell'))
            _,cy,cx=var.chunking();codes=(iy//cy)*((len(lon)+cx-1)//cx)+ix//cx
            order=np.argsort(codes,kind='stable');cuts=np.flatnonzero(np.diff(codes[order]))+1
            groups=np.split(order,cuts)
            for number,pos in enumerate(groups,1):
                y=int(iy[pos[0]]//cy*cy);x=int(ix[pos[0]]//cx*cx)
                raw=np.ma.asarray(var[:,y:y+cy,x:x+cx],dtype='f4').filled(np.nan)
                values=raw[:,iy[pos]-y,ix[pos]-x].copy();del raw
                if previous_var is not None:
                    before=np.ma.asarray(previous_var[-1,y:y+cy,x:x+cx],dtype='f4').filled(np.nan)[iy[pos]-y,ix[pos]-x]
                    increments=np.diff(values,axis=0,prepend=before[None,:])
                    reset=np.array([d.hour==1 for d in dates]);increments[reset]=values[reset]
                    increments=np.maximum(increments,0)
                    values=increments*(1000.0 if task['var']=='tp' else 1/3600.0)
                if task['var']=='rh':values=np.where(np.isfinite(values),np.clip(values,0,100),np.nan)
                target[:,pos]=values
                if number%10==0:print(unit,number,'/',len(groups),'spatial chunks',flush=True)
            dst.sync()
        tmp.replace(out)
        elapsed=time.monotonic()-start_time
        write_json(marker,dict(status='COMPLETED',identity=identity,unit=unit,job_id=os.environ.get('SLURM_JOB_ID'),
            account=os.environ.get('USER'),wall_seconds=elapsed,
            outputs=[dict(path=str(out),size_bytes=out.stat().st_size,sha256=sha(out),years=[task['year'],task['year']],time_count=len(times))]))
        print('COMPLETED',unit,round(elapsed,1),'seconds',flush=True)


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--stage',choices=['prepare','run'],default='prepare');p.add_argument('--unit')
    a=p.parse_args()
    if a.stage=='prepare':prepare(a.root)
    else:
        require(bool(a.unit),'--unit required');run(a.root,a.unit)


if __name__=='__main__':main()
