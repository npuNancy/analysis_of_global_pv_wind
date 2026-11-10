"""Inspect source metadata and station inputs on a compute node."""
import argparse
import json
import os
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pandas as pd

from utils.data_access import read_cf_grid, read_extreme_grid
from utils.lcoe_station_climate.pipeline import sha, write_json

ROOT = Path('/work/home/acxujo26gv/lcoe_gem2025_climate_storage')
ERA5 = Path('/work/home/acbw9wpn5k/bcsd/data/ERA5_land/global')


def metadata(path):
    with nc.Dataset(path) as ds:
        result = dict(path=str(path), dimensions={k:len(v) for k,v in ds.dimensions.items()},
                      attributes=ds.__dict__, variables={})
        for name,var in ds.variables.items():
            result['variables'][name] = dict(dimensions=var.dimensions, dtype=str(var.dtype),
                chunks=var.chunking(), attributes=var.__dict__)
            if name in ['time','valid_time','lat','lon','latitude','longitude']:
                result['variables'][name]['ends'] = np.asarray(var[[0,-1]]).tolist()
        return result


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args();root=a.root
    result=dict(status='COMPLETED',job_id=os.environ.get('SLURM_JOB_ID'),stations=[],era5={},sources={})
    frames=[]
    for path in sorted((root/'inputs/stations').glob('*/*.csv')):
        f=pd.read_csv(path)
        if not path.name.startswith('stations_01deg_'):continue
        frames.append(f[['technology','grid_id','latitude','longitude']])
        result['stations'].append(dict(path=str(path),sha256=sha(path),count=len(f),
            capacity=f.groupby('technology').capacity_mw.sum().to_dict()))
    union=pd.concat(frames).drop_duplicates(['technology','grid_id'])
    union.to_csv(root/'inputs/station_union.csv',index=False)
    result['union_counts']=union.groupby('technology').size().to_dict()
    for var in ['t2m','u10','v10','ssrd','tp','rh']:
        missing=[]
        for year in range(2014,2026):
            for month in range(1,13):
                path=ERA5/var/f'{var}_{year}_{month:02}.nc'
                if not path.is_file():missing.append(str(path))
        result['era5'][var]=dict(missing=missing,first=metadata(ERA5/var/f'{var}_2015_01.nc'),
                                  last=metadata(ERA5/var/f'{var}_2025_12.nc'))
    for product,reader in [('cf',read_cf_grid),('extreme',read_extreme_grid)]:
        records=reader.find_records(model='CANESM5',climate_scenario='ssp126',years=(2026,2029))
        write_json(root/'inputs'/f'{product}_probe_records.json',records)
        result['sources'][product]=dict(records=len(records),patches=sorted({r['patch'] for r in records}),
            examples=[metadata(next(r['path'] for r in records if r['tech']==t)) for t in ['wind','solar']])
    # Convert numpy-valued NetCDF attributes without loading scientific arrays.
    result=json.loads(json.dumps(result,default=lambda x:x.tolist() if hasattr(x,'tolist') else str(x)))
    write_json(root/'runtime/probe.json',result)
    print(json.dumps(dict(status=result['status'],union_counts=result['union_counts'],
                         era5_missing={v:len(r['missing']) for v,r in result['era5'].items()})),flush=True)


if __name__=='__main__':main()
