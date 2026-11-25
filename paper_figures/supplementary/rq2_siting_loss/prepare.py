"""Prepare RQ2 fixed-site and suitable-grid loss evidence from published products."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd
import h5py

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from paper_figures.config import MODELS, SSPS
OUT=HERE/'outputs'; DATA=OUT/'source_data'; CACHE=OUT/'cache'
SG=ROOT/'paper_figures/prepare/outputs/suitable_grid_loss'
MAP=ROOT/'paper_figures/supplementary/suitable_grid_extreme/outputs/source_data/patches'
RAW=Path('/work/home/acsep06cn2/generation_loss_suitable_grid/suitable_grid')
STATION=Path('/work/home/acxujo26gv/lcoe_gem2025_climate_storage')
RQ1=ROOT/'tmp/RQ1_20261112_grid_candidates/source_data'
TECHS=('wind','solar')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def save_json(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
def require(x,message):
    if not x:raise ValueError(message)

def grid_patch(task):
    tech,patch,records,completion_sha=task
    dest=CACHE/'grid_patches'/tech;dest.mkdir(parents=True,exist_ok=True)
    path=dest/(patch+'.npz');meta=dest/(patch+'.json')
    support_path=SG/'shards'/tech/patch/'support.csv.gz'
    mapping_path=MAP/tech/patch/'mapping.csv.gz'
    inputs=dict(completion=completion_sha,support=sha(support_path),mapping=sha(mapping_path),manifests=[r['sha256'] for r in records])
    if path.exists() and meta.exists() and json.loads(meta.read_text())['inputs']==inputs:return str(path)
    support=pd.read_csv(support_path).set_index('station_id')
    mapping=pd.read_csv(mapping_path)
    mapping['station_id']=[f'{tech}:{lon:.6f}:{lat:.6f}' for lon,lat in zip(mapping.lon,mapping.lat)]
    require(mapping.station_id.is_unique,'Mapping duplicates')
    require(np.array_equal(mapping.common_valid,support.loc[mapping.station_id,'common']),'Support mismatch')
    selected=mapping[mapping.common_valid].set_index('station_id')
    ids=selected.index
    values=np.full((len(MODELS),len(SSPS),len(ids)),np.nan)
    files=0
    for r in records:
        receipt=json.loads(Path(r['receipt']).read_text())
        require(receipt['manifest_sha256']==r['sha256'] and receipt['status']=='COMPLETED','Receipt')
        mp=Path(r['manifest']);require(sha(mp)==r['sha256'],'Manifest hash')
        manifest=json.loads(mp.read_text())
        mi=list(MODELS).index(r['model']);si=list(SSPS).index(r['climate_ssp'])
        seen=set()
        for tile in manifest['tiles']:
            if int(tile['window_start'])!=2050:continue
            item=next(f for f in tile['files'] if Path(f['path']).name=='annual_loss.nc')
            fp=mp.parent/item['path'];require(fp.stat().st_size==item['size'],'Annual size')
            with h5py.File(fp,'r') as z:
                require(list(z['analysis_year'][:])==list(range(2050,2060)),'Years')
                station_ids=z['station_id'][:].astype(str)
                require(not seen.intersection(station_ids),'Duplicate tile IDs');seen.update(station_ids)
                pos=ids.get_indexer(station_ids);keep=pos>=0
                v=z['net_generation_loss_per_mw_all'][:][:,keep]
                require(v.shape==(10,int(keep.sum())) and np.isfinite(v).all(),'Nonfinite common loss')
                values[mi,si,pos[keep]]=v.mean(axis=0,dtype=np.float64)
            files+=1
        require(len(seen)==len(mapping),'Incomplete patch grid coverage')
    require(np.isfinite(values).all(),'Incomplete grid model/SSP coverage')
    np.savez_compressed(path,station_id=ids.to_numpy(dtype=str),lon=selected.lon.to_numpy(),lat=selected.lat.to_numpy(),area=selected.cell_area_km2.to_numpy(),net_loss=values)
    save_json(meta,dict(inputs=inputs,files=files,n_cells=len(ids),sha256=sha(path)))
    print('grid',tech,patch,len(ids),files,flush=True)
    return str(path)

def prepare_grid():
    completion_sha=sha(RAW/'runtime/completion.json')
    require(json.loads((RAW/'runtime/completion.json').read_text())['status']=='COMPLETED','Grid incomplete')
    require(json.loads((SG/'complete.json').read_text())['completion_sha256']==completion_sha,'Grid source changed')
    records=json.loads((SG/'sources.json').read_text())
    groups={}
    for r in records:groups.setdefault((r['tech'],r['patch']),[]).append(r)
    tasks=[(t,p,rr,completion_sha) for (t,p),rr in sorted(groups.items())]
    workers=min(24,int(os.environ.get('SLURM_CPUS_PER_TASK','1')))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(grid_patch,t) for t in tasks]):future.result()
    rows=[]
    for tech in TECHS:
        chunks=[]
        for t,p,_,_ in tasks:
            if t==tech:
                with np.load(CACHE/'grid_patches'/t/(p+'.npz')) as z:chunks.append({k:z[k] for k in z.files})
        arrays={k:np.concatenate([c[k] for c in chunks],axis=2 if k=='net_loss' else 0) for k in chunks[0]}
        require(len(set(arrays['station_id']))==len(arrays['station_id']),'Global duplicate IDs')
        require(len(arrays['station_id'])=={'wind':574922,'solar':546978}[tech],'RQ1 cell count')
        np.savez_compressed(DATA/f'suitable_{tech}_2050s.npz',**arrays,models=np.array(MODELS),ssps=np.array(SSPS))
        reference=pd.read_csv(RQ1/'candidate1_intensity_models.csv')
        equal=pd.read_csv(SG/'decadal.csv')
        for mi,m in enumerate(MODELS):
            for si,s in enumerate(SSPS):
                v=arrays['net_loss'][mi,si]
                area=float(np.average(v,weights=arrays['area']));avg=float(v.mean())
                ref=reference[(reference.model==m)&(reference.climate_ssp==s)&(reference.tech==tech)&(reference.time==2050)].iloc[0]
                np.testing.assert_allclose(area,ref.net_loss_per_mw_per_year,rtol=1e-7,atol=1e-6)
                ref2=equal[(equal.model==m)&(equal.climate_ssp==s)&(equal.tech==tech)&(equal.window_start==2050)&(equal.support=='common')].iloc[0]
                np.testing.assert_allclose(avg,ref2.net_loss_per_mw,rtol=1e-7,atol=1e-6)
                rows.append(dict(model=m,climate_ssp=s,tech=tech,n_cells=len(v),equal_grid_mean=avg,area_mean=area))
    pd.DataFrame(rows).to_csv(DATA/'suitable_2050s_validation.csv',index=False)
    save_json(OUT/'grid_validation.json',dict(status='PASSED',source_completion_sha256=completion_sha,patches=len(tasks),checks=['all common cells, four models, three SSPs and ten years','area and equal-grid means reproduce RQ1 and published summaries']))

def read_station(entry,fields):
    path=Path(entry['path'])
    require(path.stat().st_size==entry['size_bytes'] and sha(path)==entry['sha256'],'Station archive hash: '+str(path))
    with np.load(path,allow_pickle=False) as z:return {k:z[k] for k in fields}

def station_pair(task):
    model,ssp,tech,transition,future=task
    path=CACHE/f'fixed_{model}_{ssp}_{tech}.npz'
    if path.exists():return str(path)
    t=read_station(transition,['grid_id','capacity_mw','common_support'])
    fields=['grid_id','years','capacity_mw','common_support','source_latitude','source_longitude','net_loss_mwh','event_normal_mwh','event_hours','loss_event_hours']
    f=read_station(future,fields)
    order=np.argsort(t['grid_id']);ids=t['grid_id'][order]
    pos=pd.Index(f['grid_id']).get_indexer(ids);require((pos>=0).all(),'Missing 2025 grid')
    cap=t['capacity_mw'][0,order]
    require(np.all(t['capacity_mw']==t['capacity_mw'][0]),'Changing 2025 capacity')
    valid=t['common_support'][order]&f['common_support'][pos]
    denom=f['capacity_mw'][:,pos]
    require((denom[:,valid]>0).all(),'Nonpositive annual capacity')
    arrays=dict(grid_id=ids,capacity=cap,valid=valid,years=f['years'],lon=f['source_longitude'][pos],lat=f['source_latitude'][pos])
    for new,old in [('net','net_loss_mwh'),('normal','event_normal_mwh')]:
        arrays[new]=np.divide(f[old][:,pos],denom,out=np.full_like(denom,np.nan,dtype=float),where=denom>0)
    arrays['exposure']=f['event_hours'][:,pos]/24
    arrays['valid_days']=f['loss_event_hours'][:,pos]/24
    for k in ['net','normal','exposure','valid_days']:require(np.isfinite(arrays[k][:,valid]).all(),k)
    np.savez_compressed(path,**arrays)
    print('fixed',model,ssp,tech,int(valid.sum()),flush=True)
    return str(path)

def prepare_stations():
    index_path=STATION/'runtime/authoritative_index.json'
    completion=json.loads((STATION/'runtime/completion.json').read_text())
    require(completion['status']=='COMPLETED' and sha(index_path)==completion['index_sha256'],'Station index')
    index=json.loads(index_path.read_text())
    entries={(e['phase'],e['station_ssp'],e['climate_ssp'],e['model'],e['tech']):e for e in index['annual_archives']}
    tasks=[]
    for m in MODELS:
        for s in SSPS:
            station={'ssp126':'ssp126','ssp245':'ssp245','ssp585':'ssp560'}[s]
            for t in TECHS:tasks.append((m,s,t,entries['transition','gem2025',s,m,t],entries['future',station,s,m,t]))
    with ProcessPoolExecutor(max_workers=min(3,int(os.environ.get('SLURM_CPUS_PER_TASK','1')))) as pool:
        for f in as_completed([pool.submit(station_pair,t) for t in tasks]):f.result()
    published=pd.read_csv(ROOT/'paper_figures/supplementary/global_metric_trends/outputs/source_data/gem2025_fixed_models.csv')
    rows=[];coverage=[]
    for tech in TECHS:
        chunks={}
        for m in MODELS:
            for s in SSPS:
                with np.load(CACHE/f'fixed_{m}_{s}_{tech}.npz') as z:chunks[m,s]={k:z[k] for k in z.files}
        ref=next(iter(chunks.values()))
        common=np.logical_and.reduce([c['valid'] for c in chunks.values()])
        for (m,s),c in chunks.items():
            require(np.array_equal(ref['grid_id'],c['grid_id']),'Fixed IDs across SSP')
            np.testing.assert_array_equal(ref['capacity'],c['capacity'])
            require(np.array_equal(c['valid'],common),'Fixed support differs across SSP/model: recompute published comparison')
            np.testing.assert_allclose(ref['lon'][common],c['lon'][common],atol=1e-8)
            np.testing.assert_allclose(ref['lat'][common],c['lat'][common],atol=1e-8)
            w=c['capacity'][common]
            for yeari,year in enumerate(c['years']):
                old=published[(published.pathway==s)&(published.model==m)&(published.tech==tech)&(published.year==year)].iloc[0]
                np.testing.assert_allclose(np.average(c['net'][yeari,common],weights=w),old.unit_loss_mwh_per_mw,rtol=1e-9)
                np.testing.assert_allclose(np.average(c['exposure'][yeari,common],weights=w),old.exposure_days,rtol=1e-9)
            for start in (2030,2040,2050):
                select=(c['years']>=start)&(c['years']<start+10)
                net=c['net'][select][:,common];normal=c['normal'][select][:,common]
                rows.append(dict(model=m,climate_ssp=s,tech=tech,time=start,n_cells=int(common.sum()),capacity_mw=float(w.sum()),exposure_days=float(np.average(c['exposure'][select][:,common].mean(axis=0),weights=w)),intensity_pct=float(100*(net*w).sum()/(normal*w).sum()),net_loss_per_mw=float(np.average(net.mean(axis=0),weights=w)),loss_valid_days=float(np.average(c['valid_days'][select][:,common].mean(axis=0),weights=w))))
        net=np.array([[chunks[m,s]['net'][-10:,common].mean(axis=0) for s in SSPS] for m in MODELS])
        np.savez_compressed(DATA/f'fixed2025_{tech}_2050s.npz',grid_id=ref['grid_id'][common],lon=ref['lon'][common],lat=ref['lat'][common],capacity=ref['capacity'][common],net_loss=net,models=np.array(MODELS),ssps=np.array(SSPS))
        coverage.append(dict(tech=tech,n_catalogue=len(common),n_valid=int(common.sum()),catalogue_capacity_mw=float(ref['capacity'].sum()),valid_capacity_mw=float(ref['capacity'][common].sum())))
    pd.DataFrame(rows).to_csv(DATA/'fixed2025_decadal_models.csv',index=False)
    pd.DataFrame(coverage).to_csv(DATA/'fixed2025_coverage.csv',index=False)
    # Check all future layout supports before using the published factorial matrix.
    supports=[]
    for station in ('ssp126','ssp245','ssp560'):
        for tech in TECHS:
            first=None
            for m in MODELS:
                for s in SSPS:
                    e=entries['future',station,s,m,tech]
                    with np.load(e['path']) as z:
                        now=(z['grid_id'],z['common_support'],z['capacity_mw'][-1])
                    if first is None:first=now
                    require(all(np.array_equal(a,b) for a,b in zip(first,now)),'Future support/capacity differs across climate/model')
            supports.append(dict(station_ssp=station,tech=tech,n_cells=int(first[1].sum()),capacity_mw=float(first[2][first[1]].sum())))
    e=index['summaries']['global_annual_models.csv'];require(sha(e['path'])==e['sha256'],'Summary checksum')
    pub=pd.read_csv(e['path']);pub=pub[(pub.phase=='future')&(pub.year>=2050)&pub.tech.isin(TECHS)]
    pub.groupby(['model','station_ssp','climate_ssp','tech'],as_index=False).unit_loss_mwh_per_mw.mean().to_csv(DATA/'future_layout_matrix_models.csv',index=False)
    pd.DataFrame(supports).to_csv(DATA/'future_layout_support.csv',index=False)
    save_json(OUT/'station_validation.json',dict(status='PASSED',index_sha256=completion['index_sha256'],archive_count=len(tasks)*2,published_annual_checks=720,fixed_support='identical IDs, capacities and valid masks across four models and three SSPs',future_support='within each layout: identical IDs, valid masks and 2050 capacity across four models and three SSPs'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['grid','stations','all'],default='all');args=parser.parse_args()
    for p in (OUT,DATA,CACHE):p.mkdir(parents=True,exist_ok=True)
    if args.stage in ('grid','all'):prepare_grid()
    if args.stage in ('stations','all'):prepare_stations()
    print('DONE',args.stage,flush=True)
if __name__=='__main__':main()
