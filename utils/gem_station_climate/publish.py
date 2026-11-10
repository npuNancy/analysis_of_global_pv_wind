"""Publish station archives, complete product indexes and global annual tables."""
import argparse
import itertools
import os
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pandas as pd

from utils.lcoe_station_climate.pipeline import read,write_json,sha,require
from .prepare import ROOT,MODELS,CLIMATES,STATIONS

RAW=['generation_per_mw','cf_mean','net_loss_per_mw','positive_loss_per_mw','normal_annual_per_mw',
     'event_normal_per_mw','event_actual_per_mw','event_hours','loss_event_hours','loss_hours',
     'cf_valid_count','signal_valid_count','loss_valid_count']
ENERGY={'generation_mwh':'generation_per_mw','net_loss_mwh':'net_loss_per_mw','positive_loss_mwh':'positive_loss_per_mw',
        'normal_annual_mwh':'normal_annual_per_mw','event_normal_mwh':'event_normal_per_mw','event_actual_mwh':'event_actual_per_mw'}


def prepare(root):
    target=root/'publish'
    for d in ['inputs','runtime/tasks','jobs','logs','outputs']:(target/d).mkdir(parents=True,exist_ok=True)
    cfg=read(root/'future/inputs/campaign.json');cfg.update(root=str(target),phase='publish',cpus=4)
    write_json(target/'inputs/campaign.json',cfg)
    tasks=[]
    for phase,source,scenarios,climates in [('future','loss_future',STATIONS,CLIMATES),
        ('transition','loss_transition',['gem2025'],CLIMATES),('historical','historical',['historical'],['historical'])]:
        state=read(root/source/'runtime/state.json')
        require(all(v['state']=='SUCCEEDED' for v in state.values()),source+' not accepted')
        inputs=[]
        for entry in read(root/source/'runtime/tasks.json'):
            task=read(entry['path']);done=read(entry['marker']);require(done['status']=='COMPLETED','Missing annual receipt')
            task['annual']=next(o for o in done['outputs'] if source!='historical' or o['product']=='loss')
            task['calendar']=done['calendar'];inputs.append(task)
        for scenario,climate,tech in itertools.product(scenarios,climates,['solar','wind']):
            unit='_'.join([phase,scenario,climate,tech])
            selected=[t for t in inputs if t['tech']==tech and (phase=='historical' or (t['station_ssp']==scenario and t['climate_ssp']==climate))]
            require(selected,'Missing annual group')
            task=dict(unit=unit,phase=phase,station_ssp=scenario,climate_ssp=climate,tech=tech,source_root=str(root),inputs=selected,
                models=['ERA5-Land'] if phase=='historical' else MODELS,years=list(range(2015,2026)) if phase=='historical' else list(range(2026,2030)) if phase=='transition' else list(range(2030,2060)))
            path=target/'runtime/tasks'/(unit+'.json');write_json(path,task)
            tasks.append(dict(unit=unit,path=str(path),product='publish',model='ensemble',climate_ssp=climate,tech=tech,patch=phase,
                n_union=len(selected),marker=str(target/'runtime/units'/unit/'complete.json')))
    write_json(target/'runtime/tasks.json',tasks);write_json(target/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks)))


def catalog(root,task):
    phase=task['phase'];years=task['years']
    if phase=='historical':
        frame=pd.read_csv(root/'era5_met/inputs/annual_capacity.csv.gz');frame=frame[frame.technology.eq(task['tech'])]
        wide=frame.pivot(index='grid_id',columns='year',values='capacity_mw').reindex(columns=years).fillna(0)
        f=frame.sort_values('grid_id').drop_duplicates('grid_id').set_index('grid_id').loc[wide.index].reset_index()
        cap=wide.to_numpy().T
        f['source_lat']=90-f.grid_id//3600/10;f['source_lon']=(f.grid_id%3600+1800)%3600/10
    else:
        f=pd.read_csv(root/phase/'catalogs'/f'{task["station_ssp"]}_{task["tech"]}.csv.gz').sort_values('grid_id').reset_index(drop=True)
        snapshots=[2025] if phase=='transition' else [2030,2040,2050]
        cap=np.asarray([f[f'capacity_mw_{max(s for s in snapshots if s<=y)}'].to_numpy() for y in years])
    require(not f.grid_id.duplicated().any(),'Duplicate catalogue IDs')
    return f,cap


def run(root,unit):
    taskpath=root/'runtime/tasks'/(unit+'.json');task=read(taskpath);shared=Path(task['source_root'])
    folder=root/'runtime/units'/unit;folder.mkdir(parents=True,exist_ok=True)
    marker=folder/'complete.json';require(not marker.exists(),'Publish group already complete')
    cat,capacity=catalog(shared,task);grid=cat.grid_id.to_numpy();lookup=pd.Index(grid);ny=len(task['years']);n=len(cat)
    groups={};seen_by_model={};expected_by_model={};calendars={}
    for model in task['models']:
        arrays={k:np.full((ny,n),np.nan) for k in RAW};seen=np.zeros(n,dtype=bool)
        for source in task['inputs']:
            if task['phase']!='historical' and source['model']!=model:continue
            record=source['annual'];path=Path(record['path'])
            require(path.stat().st_size==record['size_bytes'],'Annual archive size changed')
            with np.load(path,allow_pickle=False) as z:
                require(np.array_equal(z['years'],task['years']),'Annual year mismatch')
                positions=lookup.get_indexer(z['grid_id']);require((positions>=0).all() and not seen[positions].any(),'Duplicate or unexpected station')
                require(np.allclose(capacity[:,positions],z['capacity_mw'],rtol=1e-12,atol=1e-7),'Annual capacity mismatch')
                for key in RAW:arrays[key][:,positions]=z[key]
                hours=z['expected_hours']
                if model in expected_by_model:require(np.array_equal(hours,expected_by_model[model]),'Annual calendar hours differ')
                expected_by_model[model]=hours;seen[positions]=True
            calendars[model]=source['calendar']
        require(seen.any(),'No stations in model')
        groups[model]=arrays;seen_by_model[model]=seen
    common=np.ones(n,dtype=bool)
    for model,a in groups.items():
        step=1 if task['phase']=='historical' else 3;expected=expected_by_model[model][:,None]/step
        valid=np.isfinite(a['net_loss_per_mw'])&np.isfinite(a['normal_annual_per_mw'])&(a['normal_annual_per_mw']>0)&np.isfinite(a['generation_per_mw'])
        valid&=(a['cf_valid_count']==expected)&(a['signal_valid_count']>=.99*expected)
        common&=valid.all(axis=0)
    require(common.any(),'No common valid capacity')
    outputs=[];rows=[]
    for model,a in groups.items():
        active=(capacity>0)&common[None,:];seen=seen_by_model[model]
        result=dict(years=np.asarray(task['years']),grid_id=grid,latitude=cat.latitude.to_numpy(),longitude=cat.longitude.to_numpy(),
            source_latitude=cat.source_lat.to_numpy(),source_longitude=cat.source_lon.to_numpy(),capacity_mw=capacity,
            common_support=common,mapped=seen,expected_hours=expected_by_model[model])
        for key,value in ENERGY.items():result[key]=np.where(active,a[value]*capacity,np.nan)
        for key in ['cf_mean','event_hours','loss_event_hours','loss_hours','cf_valid_count','signal_valid_count','loss_valid_count']:
            result[key]=np.where(active,a[key],np.nan)
        require(np.allclose(result['net_loss_mwh'],result['event_normal_mwh']-result['event_actual_mwh'],rtol=2e-6,atol=.05,equal_nan=True),'Event energy closure failed')
        require(np.all((a['cf_mean'][active]>=-1e-6)&(a['cf_mean'][active]<=1+1e-6)),'Annual CF outside bounds')
        path=shared/'station_results'/task['phase']/task['station_ssp']/task['climate_ssp']/model/(task['tech']+'.npz')
        path.parent.mkdir(parents=True,exist_ok=True);require(not path.exists(),'Published archive exists')
        tmp=path.with_suffix(f'.{os.getpid()}.tmp.npz');np.savez_compressed(tmp,**result);tmp.replace(path)
        outputs.append(dict(path=str(path),sha256=sha(path),size_bytes=path.stat().st_size,model=model,phase=task['phase'],
            station_ssp=task['station_ssp'],climate_ssp=task['climate_ssp'],tech=task['tech'],calendar=calendars[model],
            years=[task['years'][0],task['years'][-1]],station_count=n))
        for i,year in enumerate(task['years']):
            good=active[i];valid_capacity=float(capacity[i,good].sum())
            require(valid_capacity>0,'Zero valid global capacity')
            row=dict(phase=task['phase'],model=model,station_ssp=task['station_ssp'],climate_ssp=task['climate_ssp'],tech=task['tech'],year=year,
                calendar=calendars[model],expected_hours=expected_by_model[model][i],capacity_mw=valid_capacity,
                catalogue_capacity_mw=float(capacity[i].sum()),mapped_capacity_mw=float(capacity[i,seen].sum()),
                n_catalogue=int((capacity[i]>0).sum()),n_mapped=int(((capacity[i]>0)&seen).sum()),n_stations=int(good.sum()),
                exposure_mw_days=float((capacity[i,good]*a['event_hours'][i,good]/24).sum()))
            row.update({name:float(np.nansum(result[name][i])) for name in ENERGY})
            rows.append(row)
    table=root/'outputs'/(unit+'.csv');pd.DataFrame(rows).to_csv(table,index=False)
    write_json(marker,dict(status='COMPLETED',unit=unit,task_sha256=sha(taskpath),code_sha256=sha(__file__),job_id=os.environ.get('SLURM_JOB_ID'),
        account=os.environ.get('USER'),outputs=outputs,summary=dict(path=str(table),sha256=sha(table)),common_stations=int(common.sum())))
    print('Published',unit,'common stations',int(common.sum()),flush=True)


def finalize(root):
    stage=root/'publish';states=read(stage/'runtime/state.json')
    require(all(v['state']=='SUCCEEDED' for v in states.values()),'Publication groups incomplete')
    archives=[];frames=[]
    for task in read(stage/'runtime/tasks.json'):
        done=read(task['marker']);archives.extend(done['outputs']);frames.append(pd.read_csv(done['summary']['path']))
    frame=pd.concat(frames,ignore_index=True)
    keys=['phase','model','station_ssp','climate_ssp','year']
    numeric=list(ENERGY)+['capacity_mw','catalogue_capacity_mw','mapped_capacity_mw','n_catalogue','n_mapped','n_stations','exposure_mw_days']
    require(frame.groupby(keys).tech.nunique().eq(2).all(),'Missing technology in global totals')
    joint=frame.groupby(keys,as_index=False)[numeric].sum(min_count=2)
    metadata=frame.groupby(keys,as_index=False)[['calendar','expected_hours']].first()
    joint=joint.merge(metadata,on=keys,validate='one_to_one');joint['tech']='wind+solar'
    frame=pd.concat([frame,joint],ignore_index=True)
    frame['unit_loss_mwh_per_mw']=frame.net_loss_mwh/frame.capacity_mw
    frame['loss_fraction_pct']=100*frame.net_loss_mwh/frame.normal_annual_mwh
    frame['unit_generation_mwh_per_mw']=frame.generation_mwh/frame.capacity_mw
    frame['cf_mean']=frame.generation_mwh/frame.capacity_mw/frame.expected_hours
    frame['exposure_days']=frame.exposure_mw_days/frame.capacity_mw
    frame['capacity_coverage']=frame.capacity_mw/frame.catalogue_capacity_mw
    require(len(frame)==3417,'Unexpected annual scenario/year/model matrix')
    data=root/'source_data';data.mkdir(exist_ok=True)
    frame.sort_values(keys+['tech']).to_csv(data/'global_annual_models.csv',index=False)
    metrics=numeric+['unit_loss_mwh_per_mw','loss_fraction_pct','unit_generation_mwh_per_mw','cf_mean','exposure_days','capacity_coverage']
    grouping=['phase','station_ssp','climate_ssp','tech','year']
    ensemble=frame.groupby(grouping)[metrics].agg(['mean','min','max']);ensemble.columns=['_'.join(c) for c in ensemble.columns]
    ensemble=ensemble.reset_index();ensemble['n_models']=frame.groupby(grouping).size().to_numpy()
    require((ensemble.n_models==np.where(ensemble.phase.eq('historical'),1,4)).all(),'Incomplete model ensemble')
    ensemble.to_csv(data/'global_annual_ensemble.csv',index=False)
    frame[grouping+['model','n_catalogue','n_mapped','n_stations','catalogue_capacity_mw','mapped_capacity_mw','capacity_mw','capacity_coverage']].to_csv(data/'capacity_coverage.csv',index=False)
    entries=[]
    for phase in ['future','transition']:
        groups={};cfg=read(root/phase/'inputs/campaign.json')
        for task in read(root/phase/'runtime/tasks.json'):
            done=read(task['marker']);require(done['status']=='COMPLETED','Missing native extraction')
            for artifact in done['outputs']:
                key=tuple(artifact[k] for k in ['product','model','climate_scenario','station_scenario','tech','patch'])
                groups.setdefault(key,[]).append(artifact)
        patches=sorted({r['patch'] for r in read(root/'inputs/cf_source_records.json')})
        for key in itertools.product(['cf','extreme'],MODELS,CLIMATES,cfg['station_ssps'],['solar','wind'],patches):
            artifacts=groups.get(key,[])
            entries.append(dict(phase=phase,**dict(zip(['product','model','climate_scenario','station_scenario','tech','patch'],key)),
                status='COMPLETED' if artifacts else 'EMPTY_NO_STATIONS',artifacts=artifacts))
    for task in read(root/'historical/runtime/tasks.json'):
        done=read(task['marker'])
        for artifact in done['outputs']:
            if artifact['product']=='loss':continue
            entries.append(dict(phase='historical',product=artifact['product'],model='ERA5-Land',climate_scenario='historical',
                station_scenario='historical',tech=task['tech'],patch=task['patch'],status='COMPLETED',artifacts=[artifact]))
    files=[a for e in entries for a in e['artifacts']]+archives
    for artifact in files:
        path=Path(artifact['path']);require(path.stat().st_size==artifact['size_bytes'],'Published size mismatch')
        require(path.stat().st_mode & 0o004,'Result is not publicly readable')
    require(len(archives)==98,'Expected 98 station annual archives')
    fields={key:dict(dimensions=['year','station'],units='MWh') for key in ENERGY}
    fields.update({key:dict(dimensions=['year','station'],units='hours') for key in ['event_hours','loss_event_hours','loss_hours']})
    fields.update({key:dict(dimensions=['year','station'],units='samples') for key in ['cf_valid_count','signal_valid_count','loss_valid_count']})
    fields.update(cf_mean=dict(dimensions=['year','station'],units='1'),
        capacity_mw=dict(dimensions=['year','station'],units='MWp/DC for solar; MW for wind',semantics='full catalogue capacity, including excluded locations'),
        years=dict(dimensions=['year'],units='calendar year'),expected_hours=dict(dimensions=['year'],units='hours'),
        grid_id=dict(dimensions=['station'],semantics='row * 3600 + column in the corrected 0.1-degree raster'),
        common_support=dict(dimensions=['station'],semantics='valid across all models and years of this phase/pathway/technology'),
        mapped=dict(dimensions=['station'],semantics='present in native climate mapping'))
    for key in ['latitude','longitude','source_latitude','source_longitude']:
        fields[key]=dict(dimensions=['station'],units='degrees',semantics='source sampling point' if key.startswith('source_') else 'station raster centre')
    schema=root/'station_results/manifest.json'
    write_json(schema,dict(status='COMPLETED',schema='gem-lcoe-annual-v1',fields=fields,
        station_semantics='One technology in one 0.1-degree cell; capacities aggregated within that cell',
        common_support_criteria='All years and models: finite net loss, finite positive normal annual energy, complete CF, at least 99% valid event timesteps',
        capacity_timing='Year-end historical stock applied to the full year; fixed 2025 stock in 2026-2029; decadal LCOE snapshots thereafter',
        event_semantics='Union of selected events; missingness retained; signed net loss',
        generation_semantics='Annual climate-driven estimate, not observed generation; no intra-year commissioning adjustment',
        native_cadence_hours=dict(historical=1,transition=3,future=3)))
    provenance={}
    for name in ['station_provenance.json','reference_code_manifest.json','windpowerlib_manifest.json','requests_dependencies_manifest.json']:
        path=root/'inputs'/name
        provenance[name]=dict(path=str(path),sha256=sha(path))
    index=root/'runtime/authoritative_index.json'
    write_json(index,dict(status='COMPLETED',schema='gem-lcoe-climate-v1',entries=entries,annual_archives=archives,
        native_files=sum(len(e['artifacts']) for e in entries),total_bytes=sum(f['size_bytes'] for f in files),
        annual_schema=dict(path=str(schema),sha256=sha(schema)),provenance=provenance,
        summaries={p.name:dict(path=str(p),size_bytes=p.stat().st_size,sha256=sha(p)) for p in data.glob('*.csv')}))
    write_json(root/'runtime/completion.json',dict(status='COMPLETED',index_sha256=sha(index),annual_archives=len(archives),
        annual_model_rows=len(frame),ensemble_rows=len(ensemble),job_id=os.environ.get('SLURM_JOB_ID'),
        historical_window=[2015,2025],transition_window=[2026,2029],future_windows=[[2030,2039],[2040,2049],[2050,2059]]))
    print('COMPLETED',len(files),'files',len(frame),'annual model rows',flush=True)


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--stage',choices=['prepare','run','finalize'],default='prepare');p.add_argument('--unit')
    a=p.parse_args()
    if a.stage=='prepare':prepare(a.root)
    elif a.stage=='finalize':finalize(a.root)
    else:require(bool(a.unit),'--unit required');run(a.root,a.unit)


if __name__=='__main__':main()
