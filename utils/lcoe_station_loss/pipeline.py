"""Complete the LCOE annual loss matrix using released loss and station CF."""
import argparse
import itertools
import json
import os
from pathlib import Path
import time
import cftime
import netCDF4 as nc
import numpy as np
import pandas as pd
from utils.lcoe_station_climate.pipeline import read,sha,write_json,require
from scnet.lcoe_station_climate.control import locked
from .science import annual_loss

YEARS=np.arange(2030,2060)
WINDOWS=(2030,2040,2050)

def signature():
    return {name:sha(Path(__file__).with_name(name)) for name in ['pipeline.py','science.py']}

def save_npz(path,**arrays):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.stem+f'.{os.getpid()}.tmp.npz')
    np.savez_compressed(tmp,**arrays);tmp.replace(path)

def year_hours(years,calendar):
    return np.array([(cftime.datetime(int(y)+1,1,1,calendar=calendar)-cftime.datetime(int(y),1,1,calendar=calendar)).total_seconds()/3600 for y in years])

def annual_cf(task,mapping):
    n=len(mapping['grid_id']);sums=np.zeros((30,n));counts=np.zeros((30,n),dtype='i4')
    observed=np.zeros(30,dtype='i4');calendar=None;last=None
    for record in sorted(task['cf'],key=lambda r:r['years']):
        path=Path(record['path']);require(path.stat().st_size==record['size_bytes'],'Changed station CF')
        with nc.Dataset(path) as ds:
            require(np.array_equal(ds['grid_id'][:],mapping['grid_id']),'CF grid order')
            for name,key in [('source_grid_lat','source_lat'),('source_grid_lon','source_lon')]:
                require(np.allclose(ds[name][:],mapping[key],atol=1e-5,rtol=0),'CF source coordinate')
            var=ds[task['tech']+'_cf'];require(var.dimensions==('time','station'),'CF dimensions')
            t=ds['time'];cal=getattr(t,'calendar','standard')
            if calendar is None:calendar=cal
            require(calendar==cal,'Changing calendar')
            dates=nc.num2date(t[:],t.units,cal,only_use_cftime_datetimes=True)
            yy=np.array([d.year for d in dates]);pos=np.flatnonzero((yy>=2030)&(yy<=2059))
            if not len(pos):continue
            hours=nc.date2num(dates[pos],'hours since 2000-01-01',cal)
            require(np.allclose(np.diff(hours),3,atol=1e-8,rtol=0),'CF timestep gap')
            if last is not None:require(abs(hours[0]-last-3)<1e-8,'CF block gap')
            last=hours[-1]
            for y in np.unique(yy[pos]):observed[y-2030]+=np.count_nonzero(yy[pos]==y)
            var.set_var_chunk_cache(size=16*1024*1024,nelems=1009,preemption=.5)
            for begin in range(int(pos[0]),int(pos[-1])+1,240):
                end=min(begin+240,int(pos[-1])+1)
                values=np.ma.asarray(var[begin:end,:],dtype='f4').filled(np.nan)
                valid=np.isfinite(values)
                require(np.all((values[valid]>=-1e-6)&(values[valid]<=1+1e-6)),'CF bounds')
                for y in np.unique(yy[begin:end]):
                    take=yy[begin:end]==y
                    counts[y-2030]+=valid[take].sum(axis=0)
                    sums[y-2030]+=np.where(valid[take],values[take],0).sum(axis=0,dtype='f8')
    require(calendar is not None,'No CF calendar')
    expected=(year_hours(YEARS,calendar)/3).astype(int)
    require(np.array_equal(observed,expected),'Incomplete CF time coverage')
    generation=sums*3.;generation[counts!=expected[:,None]]=np.nan
    return generation,counts,expected,calendar

def prepare(root,config):
    from paper_figures.prepare.prepare_suitable_grid_loss import index as loss_index
    cfg=read(config);paired=Path(cfg['paired_root']);climate=Path(cfg['climate_root'])
    require(read(paired/'delivery_manifest.json')['status']=='COMPLETED','Paired release incomplete')
    require(read(climate/'runtime/final_acceptance.json')['status']=='COMPLETED','CF release incomplete')
    frozen=root/'inputs/campaign.json'
    if frozen.exists():require(read(frozen)==cfg,'Conflicting campaign')
    else:write_json(frozen,cfg)
    groups,sources,loss_sha=loss_index(Path(cfg['loss_root']))
    cf_index=read(climate/'runtime/authoritative_index.json')
    cf={tuple(e[k] for k in ['model','climate_scenario','station_scenario','tech','patch']):e['artifacts']
        for e in cf_index['entries'] if e['product']=='cf' and e['status']=='COMPLETED'}
    originals=read(paired/'tasks.json');tasks=[]
    # Two large paired units are rerun solely as independent numerical controls.
    pilots=[max((t for t in originals if t['model']==cfg['models'][0] and t['tech']==tech),key=lambda t:t['n_stations'])['task_id'] for tech in cfg['techs']]
    for old in originals:
        original=read(paired/'tasks'/(old['task_id']+'.json'))
        m,s,tech,patch=(original[k] for k in ['model','station_ssp','tech','patch'])
        if m not in cfg['models'] or s not in cfg['station_ssps'] or tech not in cfg['techs']:continue
        mapping=paired/'mapped'/s/tech/(patch+'.npz')
        require(sha(mapping)==original['mapping_sha256'],'Changed original mapping')
        tiles={r['tile'] for r in original['loss']}
        for c in cfg['climate_ssps']:
            control=c==cfg['paired'][s]
            if control and old['task_id'] not in pilots:continue
            unit='_'.join([m,s,c,tech,patch])
            loss=[dict(window=w,tile=t,**v) for (w,t),v in sorted(groups[(tech,patch)][(m,c)].items()) if t in tiles]
            require(len(loss)==len(tiles)*3,'Incomplete loss tiles')
            source_cf=[r for r in cf[(m,c,s,tech,patch)] if r['years'][0]<=2059 and r['years'][1]>=2030]
            task=dict(unit=unit,task_id=unit,model=m,station_ssp=s,climate_ssp=c,tech=tech,patch=patch,
                mapping=str(mapping),mapping_sha256=sha(mapping),loss=loss,cf=source_cf,paired_control=control)
            if control:task['reference']=str(paired/'shards'/m/s/tech/patch/'metrics.npz')
            path=root/'tasks'/(unit+'.json')
            if path.exists():require(read(path)==task,'Conflicting prepared task')
            else:write_json(path,task)
            tasks.append(dict(unit=unit,task_id=unit,path=str(path),model=m,station_ssp=s,climate_ssp=c,tech=tech,patch=patch,
                n_union=old['n_stations'],marker=str(root/'shards'/unit/'complete.json'),paired_control=control))
    write_json(root/'runtime/tasks.json',tasks)
    write_json(root/'inputs/provenance.json',dict(loss_completion_sha256=loss_sha,loss_manifests=sources,
        cf_index_sha256=sha(climate/'runtime/authoritative_index.json'),paired_delivery_sha256=sha(paired/'delivery_manifest.json'),
        paired_manifest_sha256=sha(paired/'station_results/manifest.json'),science=signature()))
    write_json(root/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks),controls=len(pilots),
        task_manifest_sha256=sha(root/'runtime/tasks.json'),catalogue_sha256=sha(paired/'catalogue.csv.gz')))
    print('PREPARED',len(tasks),'units',flush=True)

def run(root,unit):
    task_path=root/'tasks'/(unit+'.json');task=read(task_path);dest=root/'shards'/unit;dest.mkdir(parents=True,exist_ok=True)
    identity=dict(task_sha256=sha(task_path),code=signature());marker=dest/'complete.json'
    with locked(dest/'run.lock'):
        if marker.exists():
            old=read(marker);require(old['identity']==identity,'Stale result')
            require(sha(dest/'metrics.npz')==old['metrics_sha256'],'Changed metrics');return
        start=time.monotonic();require(sha(task['mapping'])==task['mapping_sha256'],'Changed mapping')
        with np.load(task['mapping'],allow_pickle=False) as z:mapping={k:z[k] for k in z.files}
        loss,normal,closure=annual_loss(task,mapping)
        generation,counts,expected,calendar=annual_cf(task,mapping)
        valid=np.isfinite(loss)&np.isfinite(normal)&np.isfinite(generation)&(normal>0)
        arrays=dict(grid_id=mapping['grid_id'],years=YEARS,net_loss_per_mw=loss,normal_generation_per_mw=normal,
            generation_per_mw=generation,cf_valid_count=counts,expected_count=expected,valid=valid,
            capacity_mw=mapping['capacity_mw'],source_lat=mapping['source_lat'],source_lon=mapping['source_lon'])
        control_error={}
        if task['paired_control']:
            with np.load(task['reference'],allow_pickle=False) as old:
                require(set(old.files)==set(arrays),'Control fields differ')
                for name,value in arrays.items():
                    require(np.allclose(value,old[name],rtol=1e-12,atol=1e-8,equal_nan=True),'Control mismatch '+name)
                    if np.issubdtype(value.dtype,np.floating):
                        delta=np.abs(value-old[name]);control_error[name]=float(np.nanmax(delta)) if np.isfinite(delta).any() else 0.
        save_npz(dest/'metrics.npz',**arrays)
        write_json(marker,dict(status='COMPLETED',identity=identity,metrics_sha256=sha(dest/'metrics.npz'),
            calendar=calendar,n_stations=len(mapping['grid_id']),elapsed_seconds=time.monotonic()-start,
            maximum_event_energy_closure_per_mw=closure,paired_control=task['paired_control'],control_max_errors=control_error,
            job_id=os.environ.get('SLURM_JOB_ID')))
        print('COMPLETED',unit,time.monotonic()-start,flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['prepare','run','finalize'],required=True);p.add_argument('--config',type=Path);p.add_argument('--unit')
    a=p.parse_args()
    if a.stage=='prepare':prepare(a.root,a.config)
    elif a.stage=='run':run(a.root,a.unit)
    else:
        from .reduce import summarize
        summarize(a.root)
if __name__=='__main__':main()
