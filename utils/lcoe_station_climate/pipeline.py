"""Extract native CF and event flags to LCOE stations using frozen source indices."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import itertools
import json
import os
from pathlib import Path
import time
import netCDF4 as nc
import numpy as np
import pandas as pd


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8');temp.replace(path)


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def fingerprint(value): return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def require(value,message):
    if not value: raise ValueError(message)


def source_records(root,config):
    from utils.data_access import read_cf_grid,read_extreme_grid
    result={}
    for product,reader in [('cf',read_cf_grid),('extreme',read_extreme_grid)]:
        if product not in config['products']:continue
        rows=reader.find_records(root=config[product+'_root'],model=config['models'],
            climate_scenario=config['climate_ssps'],tech=config['techs'],years=config['years'])
        for r in rows:
            key=(product,r['model'],r['climate_scenario'],r['tech'],r['patch'])
            result.setdefault(key,[]).append(r)
    return result


def prepare(root,config_path):
    cfg=read(config_path);root.mkdir(parents=True,exist_ok=True)
    frozen=root/'inputs/campaign.json'
    if frozen.exists():require(read(frozen)==cfg,'Conflicting frozen campaign')
    else:write_json(frozen,cfg)
    pieces=[];sources=[]
    for scenario,year in itertools.product(cfg['station_ssps'],cfg['snapshots']):
        path=root/'inputs/stations'/scenario/f'stations_01deg_{year}.csv'
        f=pd.read_csv(path)
        require(f.scenario.eq(scenario).all() and f.year.eq(year).all(),'Station input identity')
        require(not f.duplicated(['technology','grid_id']).any(),'Duplicate station grid')
        require(np.isfinite(f.capacity_mw).all() and f.capacity_mw.gt(0).all(),'Invalid capacity')
        f=f.rename(columns={'scenario':'station_ssp','technology':'tech','year':'snapshot'})
        pieces.append(f);sources.append({'path':str(path),'sha256':sha(path)})
    catalogue=pd.concat(pieces,ignore_index=True)
    mapping_path=root/'inputs/loss_mapping.csv.gz'
    mapping=pd.read_csv(mapping_path)
    require(not mapping.duplicated(['tech','grid_id']).any(),'Duplicate mapping')
    catalogue=catalogue.merge(mapping.drop(columns=['latitude','longitude']),on=['tech','grid_id'],validate='many_to_one')
    require(len(catalogue)==sum(len(f) for f in pieces),'Catalogue mapping lost rows')
    records=source_records(root,cfg)
    mappings={};coverage=[];groups={}
    for (scenario,tech),g in catalogue.groupby(['station_ssp','tech']):
        wide=g.pivot(index='grid_id',columns='snapshot',values='capacity_mw').reindex(columns=cfg['snapshots']).fillna(0)
        require((np.diff(wide.to_numpy(),axis=1)>=-1e-7).all(),'Noncumulative capacity')
        f=g.sort_values(['grid_id','snapshot']).drop_duplicates('grid_id').copy()
        for year in cfg['snapshots']:f[f'capacity_mw_{year}']=f.grid_id.map(wide[year])
        f['station_id']=[f'lcoe:{scenario}:{tech}:{int(i)}' for i in f.grid_id]
        f['activation_year']=[next(y for y in cfg['snapshots'] if wide.loc[i,y]>0) for i in f.grid_id]
        path=root/'catalogs'/f'{scenario}_{tech}.csv.gz';f.to_csv(path,index=False)
        for year in cfg['snapshots']:
            cap=f[f'capacity_mw_{year}'];valid=f.mapping_status.eq('MATCHED')
            coverage.append(dict(station_ssp=scenario,tech=tech,snapshot=year,n_catalogue=int((cap>0).sum()),
                n_mapped=int(((cap>0)&valid).sum()),catalogue_capacity_mw=float(cap.sum()),mapped_capacity_mw=float(cap[valid].sum())))
        for patch,pg in f[f.mapping_status.eq('MATCHED')].groupby('patch'):
            groups.setdefault((tech,patch),{})[scenario]=pg.sort_values('grid_id')
    for (tech,patch),by_scenario in groups.items():
        union=pd.concat(by_scenario.values()).sort_values('grid_id').drop_duplicates('grid_id')
        array={k:union[k].to_numpy(dtype='i8' if k in ['grid_id','cf_lat_index','cf_lon_index'] else 'f8')
               for k in ['grid_id','latitude','longitude','cf_lat_index','cf_lon_index','source_lat','source_lon','distance_km']}
        for s,g in by_scenario.items():
            array[s+'_positions']=np.searchsorted(union.grid_id.to_numpy(),g.grid_id.to_numpy())
            array[s+'_capacity']=g[[f'capacity_mw_{y}' for y in cfg['snapshots']]].to_numpy().T
            array[s+'_activation']=g.activation_year.to_numpy(dtype='i4')
        path=root/'mappings'/tech/(patch+'.npz');path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            with np.load(path,allow_pickle=False) as old:
                require(set(old.files)==set(array) and all(np.array_equal(old[k],v) for k,v in array.items()),'Mapping conflict')
        else:np.savez_compressed(path,**array)
        mappings[(tech,patch)]=dict(path=str(path),sha256=sha(path),station_ssps=sorted(by_scenario),n_union=len(union))
    tasks=[]
    for key,rows in sorted(records.items()):
        product,model,climate,tech,patch=key
        if (tech,patch) not in mappings:continue
        rows=sorted(rows,key=lambda r:r['start_year'])
        require(rows[0]['start_year']<=cfg['years'][0] and rows[-1]['end_year']>=cfg['years'][1],'Incomplete indexed years')
        require(all(a['end_year']+1==b['start_year'] for a,b in zip(rows,rows[1:])),'Source block gaps')
        unit='_'.join(key)
        task=dict(unit=unit,product=product,model=model,climate_ssp=climate,tech=tech,patch=patch,
                  mapping=mappings[(tech,patch)],sources=rows,years=cfg['years'],snapshots=cfg['snapshots'],time_chunk=cfg['time_chunk'])
        for r in task['sources']:
            st=Path(r['path']).stat();r['size_bytes']=st.st_size;r['mtime_ns']=st.st_mtime_ns
        path=root/'runtime/tasks'/(unit+'.json');write_json(path,task)
        tasks.append(dict(unit=unit,path=str(path),product=product,model=model,climate_ssp=climate,tech=tech,patch=patch,
                          n_union=task['mapping']['n_union'],marker=str(root/'runtime/units'/unit/'complete.json')))
    write_json(root/'runtime/tasks.json',tasks)
    pd.DataFrame(coverage).to_csv(root/'catalogs/coverage.csv',index=False)
    catalogue[catalogue.mapping_status.ne('MATCHED')].to_csv(root/'catalogs/unmapped_stations.csv.gz',index=False)
    write_json(root/'inputs/provenance.json',dict(stations=sources,loss_mapping_sha256=sha(mapping_path),
        cf_index_sha256=sha(root/'inputs/cf_index.json'),extreme_index_sha256=sha(root/'inputs/extreme_index.json'),
        siting_commit='e9eff0d0547de79090559ea3d7efc93912613ec6',mapping='same original raster cell; frozen nearest released BCSD point from LCOE loss evaluation'))
    write_json(root/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks),tasks_sha256=sha(root/'runtime/tasks.json'),
        catalogue_rows=len(catalogue),mapping_count=len(mapping),activation_mask='off',common_loss_support_filter=False))
    print('Prepared',len(tasks),'units',flush=True)


def spatial_groups(variable,mapping):
    iy,ix=mapping['cf_lat_index'],mapping['cf_lon_index']
    chunks=variable.chunking();cy,cx=chunks[1:] if isinstance(chunks,list) else (32,32)
    codes=(iy//cy)*((variable.shape[2]+cx-1)//cx)+ix//cx
    order=np.argsort(codes,kind='stable');cuts=np.flatnonzero(np.diff(codes[order]))+1
    return [(p,int(iy[p[0]]//cy*cy),int(ix[p[0]]//cx*cx),cy,cx) for p in np.split(order,cuts) if len(p)]


def gather(variable,start,stop,mapping,groups):
    out=np.empty((stop-start,len(mapping['grid_id'])),dtype=variable.dtype)
    for positions,y,x,cy,cx in groups:
        block=np.asarray(variable[start:stop,y:y+cy,x:x+cx])
        out[:,positions]=block[:,mapping['cf_lat_index'][positions]-y,mapping['cf_lon_index'][positions]-x]
    return out


def assert_coordinates(src,mapping):
    lat=np.asarray(src['lat'][:])[mapping['cf_lat_index']]
    lon=np.asarray(src['lon'][:])[mapping['cf_lon_index']]
    require(np.allclose(lat,mapping['source_lat'],rtol=0,atol=2e-5),'Source latitude differs from frozen mapping')
    require(np.all(abs((lon-mapping['source_lon']+180)%360-180)<2e-5),'Source longitude differs from frozen mapping')


def check_source(record):
    s=Path(record['path']).stat()
    require(s.st_size==record['size_bytes'] and s.st_mtime_ns==record['mtime_ns'],'Source changed: '+record['path'])


def extract_block(root,task,record,mapping,identity):
    product=task['product'];start,end=record['start_year'],record['end_year']
    name=('cf' if product=='cf' else 'signals')+f'_{start}-{end}.nc'
    blockmarker=root/'runtime/units'/task['unit']/(name+'.json')
    if blockmarker.exists():
        old=read(blockmarker);require(old['identity']==identity,'Cached identity conflict')
        require(all(Path(r['path']).stat().st_size==r['size_bytes'] for r in old['outputs']),'Cached file size mismatch')
        return old
    check_source(record)
    outputs=[];temps=[];t0=time.monotonic()
    with ExitStack() as stack:
        src=stack.enter_context(nc.Dataset(record['path']));src.set_auto_maskandscale(False)
        assert_coordinates(src,mapping)
        names=[task['tech']+'_cf'] if product=='cf' else sorted(k for k in src.variables if k.startswith('signal_'))
        require(bool(names),'No requested variables')
        for n in names:require(src[n].dimensions==('time','lat','lon'),'Unexpected variable dimensions')
        times=np.asarray(src['time'][:]);require(len(times)>0 and np.all(np.diff(times)>0),'Invalid source times')
        calendar=getattr(src['time'],'calendar','standard')
        dates=nc.num2date(times,src['time'].units,calendar)
        keep=np.flatnonzero([(task['years'][0]<=d.year<=task['years'][1]) for d in dates])
        require(len(keep)>0 and np.all(np.diff(keep)==1),'Noncontiguous requested time')
        first,last=int(keep[0]),int(keep[-1])+1;nt=last-first
        destinations=[]
        for scenario in task['mapping']['station_ssps']:
            pos=mapping[scenario+'_positions'];n=len(pos)
            out=root/'outputs'/product/task['model']/('climate_'+task['climate_ssp'])/('station_'+scenario)/task['patch']/task['tech']/name
            require(not out.exists(),'Output without matching receipt: '+str(out))
            out.parent.mkdir(parents=True,exist_ok=True)
            tmp=out.with_name(out.name+f'.{os.environ.get("SLURM_JOB_ID","local")}.{os.getpid()}.tmp');temps.append((tmp,out))
            dst=stack.enter_context(nc.Dataset(tmp,'w'))
            dst.createDimension('time',nt);dst.createDimension('station',n);dst.createDimension('snapshot',len(task['snapshots']))
            tv=dst.createVariable('time',src['time'].dtype,('time',),fill_value=False)
            tv.setncatts({k:v for k,v in src['time'].__dict__.items() if k!='_FillValue'});tv[:]=times[first:last]
            dst.createVariable('station','i4',('station',))[:]=np.arange(n)
            sid=dst.createVariable('station_id',str,('station',));sid[:]=np.array([f'lcoe:{scenario}:{task["tech"]}:{g}' for g in mapping['grid_id'][pos]],dtype=object);sid.cf_role='timeseries_id'
            for name2,key,dtype in [('grid_id','grid_id','i8'),('lat','latitude','f8'),('lon','longitude','f8'),
                    ('source_grid_lat','source_lat','f8'),('source_grid_lon','source_lon','f8'),('source_iy','cf_lat_index','i4'),('source_ix','cf_lon_index','i4'),('match_dist_km','distance_km','f8')]:
                dst.createVariable(name2,dtype,('station',))[:]=mapping[key][pos]
            for n2 in ['lat','source_grid_lat']:dst[n2].units='degrees_north'
            for n2 in ['lon','source_grid_lon']:dst[n2].units='degrees_east'
            dst['match_dist_km'].units='km'
            dst.createVariable('mapping_status','i1',('station',))[:]=0
            dst['mapping_status'].flag_values=np.array([0],dtype='i1');dst['mapping_status'].flag_meanings='matched'
            dst.createVariable('activation_year','i4',('station',))[:]=mapping[scenario+'_activation']
            dst.createVariable('snapshot_year','i4',('snapshot',))[:]=task['snapshots']
            cap=dst.createVariable('capacity_mw','f8',('snapshot','station'));cap[:]=mapping[scenario+'_capacity'];cap.units='MW'
            if task.get('siting_commit')=='95c9ecf':cap.capacity_basis='MWp/DC' if task['tech']=='solar' else 'MW'
            attrs={k:src.getncattr(k) for k in src.ncattrs() if k not in ['_NCProperties','identity']}
            attrs.update(Conventions='CF-1.9',featureType='timeSeries',schema='lcoe-station-climate-v1',
                model=task['model'],climate_scenario=task['climate_ssp'],station_scenario=scenario,tech=task['tech'],
                source_patch=task['patch'],source_file=record['path'],source_identity=record.get('identity') or '',
                identity=identity,activation_mask='off',mapping_method=task.get('mapping_method','frozen_LCOE_loss_same_raster_cell'),
                capacity_note='Snapshot metadata only; not multiplied into CF or event flags.')
            dst.setncatts(attrs)
            for varname in names:
                v=src[varname];fill=getattr(v,'_FillValue',None)
                kwargs={'fill_value':fill} if fill is not None else {'fill_value':False}
                target=dst.createVariable(varname,v.dtype,('time','station'),zlib=True,complevel=1,shuffle=True,
                    chunksizes=(min(task['time_chunk'],nt),min(256,n)),**kwargs)
                target.setncatts({k:v2 for k,v2 in v.__dict__.items() if k not in ['_FillValue','coordinates']})
                target.coordinates='station_id lon lat source_grid_lon source_grid_lat'
                target.set_auto_maskandscale(False)
            destinations.append((scenario,pos,dst,tmp,out))
        stats={s:{} for s,_,_,_,_ in destinations}
        for varname in names:
            variable=src[varname];groups=spatial_groups(variable,mapping)
            fill=getattr(variable,'_FillValue',None)
            counts={s:[0,0] for s,_,_,_,_ in destinations}
            for a in range(first,last,task['time_chunk']):
                b=min(last,a+task['time_chunk']);values=gather(variable,a,b,mapping,groups)
                if product=='extreme':require(np.isin(values,[0,1,fill]).all(),'Invalid source event flags')
                for scenario,pos,dst,_,_ in destinations:
                    arr=values[:,pos];dst[varname][a-first:b-first,:]=arr
                    valid=np.isfinite(arr) if fill is None else np.isfinite(arr)&(arr!=fill)
                    counts[scenario][0]+=int(valid.sum());counts[scenario][1]+=int((arr==1).sum()) if product=='extreme' else 0
            for scenario,pos,dst,_,_ in destinations:
                stats[scenario][varname]=dict(valid_count=counts[scenario][0],missing_count=nt*len(pos)-counts[scenario][0])
                if product=='extreme':stats[scenario][varname]['event_count']=counts[scenario][1]
        # Independent point reads, including first/middle/last timestamps, before publication.
        for scenario,pos,dst,tmp,out in destinations:
            dst.sync();ti=np.unique([0,nt//2,nt-1]);pi=np.unique([0,len(pos)//2,len(pos)-1])
            for varname in names:
                for j in pi:
                    k=pos[j]
                    expected=np.asarray(src[varname][ti+first,int(mapping['cf_lat_index'][k]),int(mapping['cf_lon_index'][k])])
                    actual=np.asarray(dst[varname][ti,int(j)])
                    np.testing.assert_array_equal(actual,expected)
            outputs.append(dict(path=str(out),model=task['model'],climate_scenario=task['climate_ssp'],station_scenario=scenario,
                tech=task['tech'],patch=task['patch'],product=product,years=[max(start,task['years'][0]),min(end,task['years'][1])],
                station_count=len(pos),time_count=nt,calendar=calendar,time_units=src['time'].units,
                time_first=float(times[first]),time_last=float(times[last-1]),variables=names,statistics=stats[scenario],source_comparison='PASSED'))
    check_source(record)
    for (tmp,out),item in zip(temps,outputs):
        tmp.replace(out);item.update(size_bytes=out.stat().st_size,sha256=sha(out))
    result=dict(status='COMPLETED',identity=identity,source=record,outputs=outputs,wall_seconds=time.monotonic()-t0)
    write_json(blockmarker,result)
    print(task['unit'],name,'complete',round(result['wall_seconds'],1),'seconds',flush=True)
    return result


def run(root,unit):
    path=root/'runtime/tasks'/(unit+'.json');task=read(path)
    folder=root/'runtime/units'/unit;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        identity=fingerprint(dict(task_sha256=sha(path),code_sha256=sha(__file__)))
        require(sha(task['mapping']['path'])==task['mapping']['sha256'],'Mapping hash mismatch')
        if (folder/'complete.json').exists():
            require(read(folder/'complete.json')['identity']==identity,'Complete task identity conflict');print('Already completed',unit);return
        with np.load(task['mapping']['path'],allow_pickle=False) as z:mapping={k:z[k] for k in z.files}
        blocks=[extract_block(root,task,r,mapping,identity) for r in task['sources']]
        write_json(folder/'complete.json',dict(status='COMPLETED',identity=identity,unit=unit,task_sha256=sha(path),
            code_sha256=sha(__file__),job_id=os.environ.get('SLURM_JOB_ID'),account=os.environ.get('USER'),
            outputs=[o for b in blocks for o in b['outputs']],wall_seconds=sum(b['wall_seconds'] for b in blocks)))


def finalize(root):
    cfg=read(root/'inputs/campaign.json');tasks=read(root/'runtime/tasks.json');entries={};files=[]
    for t in tasks:
        marker=read(t['marker']);require(marker['status']=='COMPLETED','Incomplete unit '+t['unit'])
        require(marker['task_sha256']==sha(t['path']),'Changed task input')
        for item in marker['outputs']:
            require(Path(item['path']).stat().st_size==item['size_bytes'],'Output size mismatch')
            key=(item['product'],item['model'],item['climate_scenario'],item['station_scenario'],item['patch'],item['tech'])
            entries.setdefault(key,[]).append(item);files.append(item)
    all_patches=sorted({r['patch'] for records in source_records(root,cfg).values() for r in records})
    index=[]
    for key in itertools.product(cfg['products'],cfg['models'],cfg['climate_ssps'],cfg['station_ssps'],all_patches,cfg['techs']):
        artifacts=sorted(entries.get(key,[]),key=lambda x:x['years'])
        if artifacts:
            require(artifacts[0]['years'][0]==cfg['years'][0] and artifacts[-1]['years'][1]==cfg['years'][1],'Incomplete output years')
            for a,b in zip(artifacts,artifacts[1:]):
                require(a['years'][1]+1==b['years'][0],'Year gap')
                require(a['calendar']==b['calendar'] and a['station_count']==b['station_count'],'Inconsistent shard identity')
                times=nc.num2date([a['time_last']],a['time_units'],a['calendar'])
                last=nc.date2num(times,b['time_units'],b['calendar'])[0]
                # Time units differ by product; compare decoded hours explicitly.
                first_date=nc.num2date(b['time_first'],b['time_units'],b['calendar'])
                last_date=nc.num2date(last,b['time_units'],b['calendar'])
                require(abs((first_date-last_date).total_seconds()-10800)<1e-3,'Native time discontinuity')
        index.append(dict(zip(['product','model','climate_scenario','station_scenario','patch','tech'],key),
            status='COMPLETED' if artifacts else 'EMPTY_NO_STATIONS',artifacts=artifacts))
    write_json(root/'runtime/authoritative_index.json',dict(schema='lcoe-station-climate-v1',status='COMPLETED',
        combination_count=len(index),file_count=len(files),years=cfg['years'],entries=index,
        activation_mask='off',capacity_snapshots=cfg['snapshots'],source_provenance=str(root/'inputs/provenance.json')))
    write_json(root/'runtime/completion.json',dict(status='COMPLETED',units=len(tasks),files=len(files),
        nonempty_combinations=len(entries),empty_combinations=len(index)-len(entries),total_bytes=sum(f['size_bytes'] for f in files),
        index_sha256=sha(root/'runtime/authoritative_index.json'),source_comparisons='PASSED'))
    print('Finalized',len(files),'files',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['prepare','run','finalize'],required=True);p.add_argument('--config',type=Path);p.add_argument('--unit')
    a=p.parse_args()
    if a.stage=='prepare':require(a.config is not None,'--config required');prepare(a.root,a.config)
    elif a.stage=='run':require(a.unit is not None,'--unit required');run(a.root,a.unit)
    else:finalize(a.root)
if __name__=='__main__':main()
