"""Reuse verified annual grid caches to build common-support event maps."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from paper_figures.config import ROOT,EVENTS,INDEXES
from paper_figures.common.cli import parser
from paper_figures.common.io import write_csv,write_json,complete,require_complete
from utils.data_access.read_extreme_grid import find_records

def run(a,t,p,manifest):
    out=a.output_root/'grid_events'/t/p;out.mkdir(parents=True,exist_ok=True)
    if (out/'complete.json').exists():require_complete(out);return
    values=[];provenance=[];lat=lon=area=domain=None
    for m in a.models:
        climates=[]
        for c in a.climate_ssps:
            rec=next(r for r in manifest['records'] if (r['model'],r['scenario'],r['tech'],r['patch'])==(m,c,t,p))
            file=ROOT/'RQ1_extreme/global/grid/outputs'/m/'cache'/c/t/(p+'.nc')
            formal=find_records(model=m,climate_scenario=c,tech=t,patch=p)
            with xr.open_dataset(file) as ds:
                if ds.attrs['fingerprint']!=rec['fingerprint']:raise ValueError(f'Cache fingerprint mismatch: {file}')
                sig=json.loads(ds.attrs['source_signature']);declared={Path(v[0]).name:v for v in sig['files']}
                for r in formal:
                    src=Path(r['path']);old=declared[src.name];stat=src.stat()
                    if (stat.st_size,stat.st_mtime_ns)!=(old[1],old[2]):raise ValueError(f'Cache source metadata changed: {src}')
                expected=['any',*EVENTS[t]]
                if list(ds.event.values.astype(str))!=expected:raise ValueError('Cached event definitions mismatch')
                if lat is None:
                    lat=ds.lat.values;lon=ds.lon.values;area=ds.cell_area_km2.values;domain=ds.domain_mask.values.astype(bool)
                elif not(np.array_equal(lat,ds.lat.values) and np.array_equal(lon,ds.lon.values)):
                    raise ValueError('Grid coordinate mismatch')
                domain &= ds.domain_mask.values.astype(bool)
                if not np.isclose(ds.attrs['min_time_coverage'],0.99):raise ValueError('Cache temporal coverage policy mismatch')
                periods=[]
                for snap in a.snapshots:
                    v=ds.event_days.sel(year=list(range(snap,snap+10))).values.astype(float)*24
                    valid=np.isfinite(v).all(axis=(0,1))
                    periods.append(np.where(valid[None,:,:],np.mean(v,axis=0),np.nan))
                climates.append(np.stack(periods))
                provenance.append(dict(cache=str(file),fingerprint=rec['fingerprint'],source_signature=sig))
        values.append(np.stack(climates))
    v=np.stack(values);common=np.isfinite(v).all(axis=(0,1,3)) & domain[None,:,:]
    v=np.where(common[None,None,:,None,:,:],v,np.nan)
    ds=xr.Dataset({'event_hours':(('model','climate_ssp','snapshot','event','lat','lon'),v.astype('f4')),
                   'common_mask':(('snapshot','lat','lon'),common.astype('u1')),
                   'cell_area_km2':(('lat','lon'),area)},
                  coords=dict(model=a.models,climate_ssp=a.climate_ssps,snapshot=a.snapshots,event=['all',*EVENTS[t]],lat=lat,lon=lon))
    ds.event_hours.attrs['units']='h yr-1';ds.attrs.update(support='common cells across selected models and climates, all ten years',aggregation='annual observed hours; no missing-time extrapolation')
    tmp=out/'period_hours.tmp.nc';ds.to_netcdf(tmp,encoding={'event_hours':{'zlib':True,'complevel':1}});tmp.replace(out/'period_hours.nc')
    xx,yy=np.meshgrid((lon+180)%360-180,lat);bins=pd.DataFrame(dict(lon=np.floor(xx.ravel())+.5,lat=np.floor(yy.ravel())+.5,area=area.ravel()))
    rows=[]
    for mi,m in enumerate(a.models):
        for ci,c in enumerate(a.climate_ssps):
            for si,s in enumerate(a.snapshots):
                f=bins.copy();f['weighted_hours']=v[mi,ci,si,0].ravel()*f.area
                f=f[common[si].ravel()];f=f.groupby(['lat','lon'],as_index=False)[['weighted_hours','area']].sum();f['hours']=f.weighted_hours/f.area
                f['model']=m;f['climate_ssp']=c;f['snapshot']=s;f['tech']=t;f['patch']=p;rows.append(f)
    write_csv(out/'display_grid.csv.gz',pd.concat(rows,ignore_index=True));write_json(out/'sources.json',provenance)
    complete(out,models=a.models,climate_ssps=a.climate_ssps,snapshots=a.snapshots,tech=t,patch=p,cache_reuse='fingerprint and formal source size/mtime verified')

def main():
    a=parser(__doc__).parse_args();manifest=json.loads((ROOT/'RQ1_extreme/global/grid/outputs/cache_manifest.json').read_text())
    patches=a.patches or manifest['scope']['patches']
    for t in a.techs:
        for p in patches:run(a,t,p,manifest)
if __name__=='__main__':main()
