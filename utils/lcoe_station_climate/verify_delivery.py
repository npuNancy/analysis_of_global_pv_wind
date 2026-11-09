"""Verify the published LCOE matrix, coverage, shared permissions and sample reads."""
import argparse
from collections import Counter
import csv
import itertools
import json
from pathlib import Path
import numpy as np
import xarray as xr
from utils.lcoe_station_climate.pipeline import sha,write_json


def verify(root):
    def read(name):return json.loads((root/name).read_text())
    cfg=read('inputs/campaign.json');state=read('runtime/state.json')
    done=read('runtime/completion.json');index=read('runtime/authoritative_index.json')
    assert done['status']==index['status']=='COMPLETED'
    assert all(v['state']=='SUCCEEDED' and v['exit_code']=='0:0' for v in state.values())
    assert len(state)==done['units']
    assert sha(root/'runtime/authoritative_index.json')==done['index_sha256']
    fields=['product','model','climate_scenario','station_scenario','patch','tech']
    patches=sorted({e['patch'] for e in index['entries']})
    expected=set(itertools.product(cfg['products'],cfg['models'],cfg['climate_ssps'],cfg['station_ssps'],patches,cfg['techs']))
    actual={tuple(e[k] for k in fields) for e in index['entries']}
    assert actual==expected and len(actual)==len(index['entries'])==index['combination_count']
    paths=set();directories={root.resolve()};counts=Counter();stations=Counter();total_bytes=0
    for e in index['entries']:
        assert e['status'] in ['COMPLETED','EMPTY_NO_STATIONS']
        if e['status']=='EMPTY_NO_STATIONS':assert not e['artifacts'];continue
        assert e['artifacts']
        stations[tuple(e[k] for k in fields if k!='patch')]+=e['artifacts'][0]['station_count']
        for a in e['artifacts']:
            assert all(a[k]==e[k] for k in fields)
            p=Path(a['path']);assert p not in paths;paths.add(p)
            st=p.stat();assert st.st_size==a['size_bytes']
            assert st.st_mode & 0o044==0o044,('Missing shared read permission',p)
            assert a['source_comparison']=='PASSED'
            directories.add(p.parent);counts[e['product']]+=1;total_bytes+=st.st_size
    assert len(paths)==done['files']==index['file_count'] and total_bytes==done['total_bytes']
    resolved={p.resolve() for p in directories}
    assert all(p.is_relative_to(root.resolve()) for p in resolved)
    for p in tuple(resolved):resolved.update(p.parents)
    for p in resolved:
        required=0o005 if p.is_relative_to(root.resolve()) else 0o001
        assert p.stat().st_mode & required==required,('Missing public directory access',p)
    with (root/'catalogs/coverage.csv').open() as f:
        coverage={(r['station_ssp'],r['tech']):int(r['n_mapped']) for r in csv.DictReader(f) if int(r['snapshot'])==max(cfg['snapshots'])}
    for product,model,climate,scenario,tech in itertools.product(cfg['products'],cfg['models'],cfg['climate_ssps'],cfg['station_ssps'],cfg['techs']):
        assert stations[(product,model,climate,scenario,tech)]==coverage[(scenario,tech)]
    samples={}
    for product in cfg['products']:
        entry=next(e for e in index['entries'] if e['product']==product and e['climate_scenario']!=e['station_scenario'] and e['status']=='COMPLETED')
        artifact=next(a for a in entry['artifacts'] if a['years'][0]<=2030<=a['years'][1])
        with xr.open_dataset(artifact['path']) as ds:
            small=ds.isel(station=slice(0,5)).sel(time=slice('2030-01-01','2030-01-03')).load()
            assert small.sizes['time']>0 and small.sizes['station']>0
            assert list(small.snapshot_year.values)==cfg['snapshots']
            assert np.all(np.diff(small.capacity_mw.values,axis=0)>=-1e-7)
            if product=='extreme':
                for name in small.data_vars:
                    if name.startswith('signal_'):assert np.isin(small[name].values[np.isfinite(small[name].values)],[0,1]).all()
            samples[product]=dict(path=artifact['path'],stations=small.sizes['station'],times=small.sizes['time'],status='PASSED')
    result=dict(status='COMPLETED',units=len(state),files=len(paths),files_by_product=dict(counts),
        combinations=len(actual),mapped_coverage='PASSED',public_read_permissions='PASSED',
        samples=samples,total_bytes=total_bytes,index_sha256=done['index_sha256'],validator_sha256=sha(__file__))
    write_json(root/'runtime/final_acceptance.json',result)
    print(json.dumps(result),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    verify(p.parse_args().root)
if __name__=='__main__':main()
