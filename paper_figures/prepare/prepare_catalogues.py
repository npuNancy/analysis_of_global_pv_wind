"""Build authoritative station-capacity-country catalogues and input provenance."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from paper_figures.config import INDEXES,ROOT,STATION_FILES,SHAPEFILE
from paper_figures.common.cli import parser
from paper_figures.common.io import digest,write_csv,write_json,complete
from paper_figures.common.spatial import countries,assign

def main():
    a=parser(__doc__).parse_args();out=a.output_root/'catalogues';out.mkdir(parents=True,exist_ok=True)
    provenance={key:dict(path=str(p),sha256=digest(p)) for key,p in INDEXES.items()}
    write_json(out/'input_versions.json',provenance)
    index=json.loads(INDEXES['extreme_stations'].read_text());geo=countries()
    write_csv(out/'countries.csv',pd.DataFrame([dict(country=iso,name=name) for iso,name,g in geo]))
    refs=[];bubbles=[];coverage=[];identities=[]
    for s in a.station_ssps:
        cat=index['catalogs'][s];raw=ROOT/'data/stations'/STATION_FILES[s]
        if digest(raw)!=cat['source_sha256']:raise ValueError(f'Station copy differs from formal catalogue: {raw}')
        cap_path=next(p for p in cat['files'] if p.endswith('/capacity_rows.csv.gz'))
        if digest(cap_path)!=cat['files'][cap_path]:raise ValueError('Capacity catalogue digest mismatch')
        cap=pd.read_csv(cap_path)
        print('capacity columns',s,list(cap),flush=True)
        for t in a.techs:
            info=cat['catalogs'][t]
            if digest(info['path'])!=info['sha256']:raise ValueError('Station catalogue digest mismatch')
            st=pd.read_csv(info['path']);st.station_id=st.station_id.astype(str)
            if st.station_id.duplicated().any():raise ValueError('Duplicate formal station ID')
            st['country']=assign(st.lon.to_numpy(),st.lat.to_numpy(),geo)
            write_csv(out/f'stations_{s}_{t}.csv.gz',st)
            part=cap[cap.type.eq(t)&cap.year.isin(a.snapshots)].copy()
            part=part.groupby(['station_id','year'],as_index=False).capacity_gw.sum()
            part['capacity_mw']=part.pop('capacity_gw')*1000
            if (~np.isfinite(part.capacity_mw)|(part.capacity_mw<0)).any():raise ValueError('Invalid catalogue capacity')
            part=part.merge(st[['station_id','lon','lat','country']],on='station_id',how='left',validate='many_to_one')
            if part.country.isna().any():raise ValueError('Capacity row absent from catalogue')
            part.rename(columns={'year':'snapshot'},inplace=True);part['station_ssp']=s;part['tech']=t
            write_csv(out/f'capacity_{s}_{t}.csv.gz',part)
            by=part.groupby(['snapshot','country'],as_index=False).capacity_mw.sum();by['station_ssp']=s;by['tech']=t;refs.append(by)
            b=part[part.snapshot.eq(2050)].copy();b['lon_bin']=np.floor((b.lon+180)%360)-180+0.5;b['lat_bin']=np.floor(b.lat)+0.5
            b=b.groupby(['lon_bin','lat_bin'],as_index=False).capacity_mw.sum();b['station_ssp']=s;b['tech']=t;bubbles.append(b)
            coverage.append(dict(station_ssp=s,tech=t,stations=len(st),unassigned=int(st.country.eq('UNASSIGNED').sum()),ambiguous=int(st.country.eq('AMBIGUOUS').sum())))
            identities.append(dict(station_ssp=s,tech=t,catalog_sha256=info['sha256'],capacity_sha256=cat['files'][cap_path]))
    write_csv(out/'capacity_by_country.csv',pd.concat(refs,ignore_index=True))
    write_csv(out/'capacity_bubbles.csv',pd.concat(bubbles,ignore_index=True))
    write_csv(out/'catalogue_coverage.csv',pd.DataFrame(coverage))
    # Preserve all formal task states, including legal empties.
    states=[]
    for c in index['combinations'].values():
        states.append({k:c[k] for k in ['model','climate_scenario','station_scenario','patch','tech','status']})
    write_csv(out/'event_task_states.csv.gz',pd.DataFrame(states))
    complete(out,provenance=provenance,catalogues=identities,shapefile_sha256=digest(SHAPEFILE),
             capacity_semantics='snapshot_total',unassigned_policy='retain; never nearest-country')
if __name__=='__main__': main()
