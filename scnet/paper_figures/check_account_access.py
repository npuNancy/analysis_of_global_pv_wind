"""Compute-node environment and shared-output ACL smoke check."""
import json
import os
from pathlib import Path
import subprocess
import numpy as np
import pandas as pd
import xarray as xr
import netCDF4
import cftime
from paper_figures.config import ROOT
from paper_figures.common.io import write_json,complete


def main():
    user=subprocess.check_output(['id','-un'],text=True).strip()
    status=ROOT/'logs/paper_figures/completion_status';rows=json.loads((status/'acl_input_probe_paths.json').read_text());checked=[];seen=set()
    for r in rows:
        if r['kind']!='data' or r['product'] in seen:continue
        with netCDF4.Dataset(r['path']) as ds:
            variables=[v for v in ds.variables.values() if v.ndim and np.dtype(v.dtype).kind in 'fiub' and all(v.shape)]
            if not variables:raise ValueError('No numeric sample variable')
            value=variables[-1][tuple(0 for _ in variables[-1].shape)]
        checked.append(dict(product=r['product'],path=r['path']));seen.add(r['product'])
    if len(checked)!=5:raise ValueError('Expected five data products')
    out=status/'accounts'/user/'access_probe';out.mkdir(parents=True,exist_ok=True)
    with netCDF4.Dataset(out/'acl_roundtrip.nc','w') as ds:
        ds.createDimension('sample',1);ds.createVariable('value','i4',('sample',))[:]=[os.getuid()]
    write_json(out/'checks.json',dict(user=user,uid=os.getuid(),checked=checked,status='PASSED'));complete(out)
    print('ACCESS_PASSED',user,flush=True)

if __name__=='__main__':main()
