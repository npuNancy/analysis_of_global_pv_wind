"""Prepare corrected spatial mappings and independent climate extraction units."""
import argparse
import json
from pathlib import Path
import shutil

import netCDF4 as nc
import numpy as np
import pandas as pd

from utils.data_access import read_cf_grid, read_extreme_grid
from utils.lcoe_station_climate.pipeline import read, require, sha, write_json

ROOT=Path('/work/home/acxujo26gv/lcoe_gem2025_climate_storage')
MODELS=['CANESM5','MPI-ESM1-2-HR','MRI-ESM2-0','BCC-CSM2-MR']
CLIMATES=['ssp126','ssp245','ssp585']
STATIONS=['ssp126','ssp245','ssp560']


def source_grid(records):
    """Join by the containing 0.1-degree raster cell, including exact edges."""
    frames=[]
    for record in records:
        with nc.Dataset(record['path']) as ds:
            lat=np.asarray(ds['lat'][:],dtype='f8');lon=np.asarray(ds['lon'][:],dtype='f8')
            lat10=np.rint(lat*10).astype('i8');lon10=np.rint(((lon+180)%360-180)*10).astype('i8')
            require(np.max(abs(lat-lat10/10))<2e-5,'Latitude is not the expected 0.1-degree lattice')
            require(np.max(abs(((lon-lon10/10+180)%360)-180))<2e-5,'Longitude lattice')
            row=900-lat10;col=(lon10+1800)%3600
            domain=np.asarray(ds['domain_mask'][:])==1
            iy,ix=np.nonzero(domain & (row[:,None]>=0) & (row[:,None]<1800))
            frames.append(pd.DataFrame(dict(grid_id=row[iy]*3600+col[ix],patch=record['patch'],
                cf_lat_index=iy,cf_lon_index=ix,source_lat=lat[iy],source_lon=lon[ix])))
    grid=pd.concat(frames,ignore_index=True)
    require(not grid.grid_id.duplicated().any(),'Source patches overlap in corrected raster cells')
    return grid


def catalogue(root):
    pieces=[];provenance=[]
    for scenario in STATIONS+['historical_snapshot']:
        paths=sorted((root/'inputs/stations'/scenario).glob('stations_01deg_*.csv'))
        require(len(paths)==(11 if scenario=='historical_snapshot' else 3),'Station year count')
        for path in paths:
            f=pd.read_csv(path)
            require(not f.duplicated(['technology','grid_id']).any(),'Duplicate station IDs')
            require(np.isfinite(f.capacity_mw).all() and f.capacity_mw.gt(0).all(),'Invalid capacity')
            f['station_ssp']='historical' if scenario=='historical_snapshot' else scenario
            pieces.append(f);provenance.append(dict(path=str(path),sha256=sha(path)))
    write_json(root/'inputs/station_provenance.json',provenance)
    return pd.concat(pieces,ignore_index=True).rename(columns={'technology':'tech','year':'snapshot'})


def build_stage(root,cat,records,phase):
    target=root/phase
    for folder in ['inputs','catalogs','mappings','runtime/tasks','jobs','logs']:(target/folder).mkdir(parents=True,exist_ok=True)
    if phase=='future':
        scenarios=STATIONS;snapshots=[2030,2040,2050];years=[2015,2060]
        cat=cat[cat.station_ssp.isin(scenarios)].copy()
    else:
        scenarios=['gem2025'];snapshots=[2025];years=[2026,2029]
        cat=cat[cat.station_ssp.eq('historical') & cat.snapshot.eq(2025)].copy()
        cat['station_ssp']='gem2025'
    base=read(Path(__file__).resolve().parents[2]/'scnet/lcoe_station_climate/campaign.json')
    cfg={**base,'root':str(target),'repo':str(root/'code'),'station_ssps':scenarios,
         'snapshots':snapshots,'years':years,'cpus':4,'campaign':'gem2025','phase':phase}
    write_json(target/'inputs/campaign.json',cfg)
    groups={};coverage=[]
    for (scenario,tech),g in cat.groupby(['station_ssp','tech']):
        wide=g.pivot(index='grid_id',columns='snapshot',values='capacity_mw').reindex(columns=snapshots).fillna(0)
        if phase=='future':require((np.diff(wide.to_numpy(),axis=1)>=-1e-7).all(),'Future cumulative capacity')
        f=g.sort_values(['grid_id','snapshot']).drop_duplicates('grid_id').copy()
        for year in snapshots:f[f'capacity_mw_{year}']=f.grid_id.map(wide[year])
        f['activation_year']=[next(y for y in snapshots if wide.loc[i,y]>0) for i in f.grid_id]
        f.to_csv(target/'catalogs'/f'{scenario}_{tech}.csv.gz',index=False)
        for year in snapshots:
            cap=f[f'capacity_mw_{year}'];valid=f.mapping_status.eq('MATCHED')
            coverage.append(dict(station_ssp=scenario,tech=tech,snapshot=year,n_catalogue=int((cap>0).sum()),
                n_mapped=int(((cap>0)&valid).sum()),catalogue_capacity_mw=float(cap.sum()),mapped_capacity_mw=float(cap[valid].sum())))
        for patch,pg in f[f.mapping_status.eq('MATCHED')].groupby('patch'):
            groups.setdefault((tech,patch),{})[scenario]=pg.sort_values('grid_id')
    mappings={}
    for (tech,patch),by_scenario in groups.items():
        union=pd.concat(by_scenario.values()).sort_values('grid_id').drop_duplicates('grid_id')
        arrays={k:union[k].to_numpy(dtype='i8' if k in ['grid_id','cf_lat_index','cf_lon_index'] else 'f8')
            for k in ['grid_id','latitude','longitude','cf_lat_index','cf_lon_index','source_lat','source_lon','distance_km']}
        for scenario,f in by_scenario.items():
            arrays[scenario+'_positions']=np.searchsorted(union.grid_id.to_numpy(),f.grid_id.to_numpy())
            arrays[scenario+'_capacity']=f[[f'capacity_mw_{y}' for y in snapshots]].to_numpy().T
            arrays[scenario+'_activation']=f.activation_year.to_numpy(dtype='i4')
        path=target/'mappings'/tech/(patch+'.npz');path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            with np.load(path) as old:require(set(old.files)==set(arrays) and all(np.array_equal(old[k],v) for k,v in arrays.items()),'Changed mapping')
        else:np.savez_compressed(path,**arrays)
        mappings[tech,patch]=dict(path=str(path),sha256=sha(path),station_ssps=sorted(by_scenario),n_union=len(union))
    tasks=[];bykey={}
    for product,rows in records.items():
        for r in rows:
            if r['end_year']>=years[0] and r['start_year']<=years[1]:
                bykey.setdefault((product,r['model'],r['climate_scenario'],r['tech'],r['patch']),[]).append(r.copy())
    for key,rows in sorted(bykey.items()):
        product,model,climate,tech,patch=key
        if (tech,patch) not in mappings:continue
        rows.sort(key=lambda r:r['start_year']);unit='_'.join(key)
        for r in rows:
            stat=Path(r['path']).stat();r.update(size_bytes=stat.st_size,mtime_ns=stat.st_mtime_ns)
        task=dict(unit=unit,product=product,model=model,climate_ssp=climate,tech=tech,patch=patch,
            mapping=mappings[tech,patch],sources=rows,years=years,snapshots=snapshots,time_chunk=240,
            mapping_method='same_corrected_0.1_degree_raster_cell',siting_commit='95c9ecf',phase=phase)
        path=target/'runtime/tasks'/(unit+'.json');write_json(path,task)
        tasks.append(dict(unit=unit,path=str(path),product=product,model=model,climate_ssp=climate,tech=tech,patch=patch,
            n_union=task['mapping']['n_union'],marker=str(target/'runtime/units'/unit/'complete.json')))
    pd.DataFrame(coverage).to_csv(target/'catalogs/coverage.csv',index=False)
    cat[cat.mapping_status.ne('MATCHED')].to_csv(target/'catalogs/unmapped_stations.csv.gz',index=False)
    write_json(target/'runtime/tasks.json',tasks)
    write_json(target/'runtime/prepared.json',dict(status='COMPLETED',units=len(tasks),tasks_sha256=sha(target/'runtime/tasks.json')))
    print(phase,len(tasks),'units',flush=True)


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args();root=a.root
    require(not (root/'future/runtime/state.json').exists(),'Preparation already submitted')
    cat=catalogue(root)
    records={k:reader.find_records(model=MODELS,climate_scenario=CLIMATES,years=(2015,2060))
             for k,reader in [('cf',read_cf_grid),('extreme',read_extreme_grid)]}
    refs=[r for r in records['cf'] if r['model']=='CANESM5' and r['climate_scenario']=='ssp126' and r['tech']=='wind' and r['start_year']==2015]
    require(len(refs)==47,'Expected 47 climate patches')
    grid=source_grid(refs)
    cat=cat.merge(grid,on='grid_id',how='left',validate='many_to_one')
    cat['mapping_status']=np.where(cat.patch.notna(),'MATCHED','NO_LAND_POINT_IN_CELL')
    a_lat=np.deg2rad(cat.latitude);b_lat=np.deg2rad(cat.source_lat)
    dlon=np.deg2rad((cat.source_lon-cat.longitude+180)%360-180)
    cat['distance_km']=6371*2*np.arcsin(np.sqrt(np.sin((b_lat-a_lat)/2)**2+np.cos(a_lat)*np.cos(b_lat)*np.sin(dlon/2)**2))
    (root/'catalogs').mkdir(exist_ok=True)
    cat.to_csv(root/'catalogs/annual_capacities.csv.gz',index=False)
    unique=cat.sort_values(['tech','grid_id']).drop_duplicates(['tech','grid_id'])
    unique.to_csv(root/'catalogs/spatial_mapping.csv.gz',index=False)
    for product,rows in records.items():write_json(root/'inputs'/f'{product}_source_records.json',rows)
    for phase in ['future','transition']:build_stage(root,cat,records,phase)
    write_json(root/'runtime/prepared.json',dict(status='COMPLETED',union=len(unique),mapped=int(unique.patch.notna().sum()),
        mapping_sha256=sha(root/'catalogs/spatial_mapping.csv.gz'),code_sha256=sha(__file__)))


if __name__=='__main__':main()
