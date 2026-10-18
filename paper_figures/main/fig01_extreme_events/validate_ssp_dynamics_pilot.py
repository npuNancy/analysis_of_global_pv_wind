"""Validate compiled and Python streaming implementations on real pilot data."""
import numpy as np
import xarray as xr
from .prepare_ssp_dynamics import OUT, marker
from paper_figures.common.io import require_complete,write_json
from paper_figures.config import TECHS

def main():
    checks=[]
    for tech in TECHS:
        relative=f"shards/{tech}/CANESM5/ssp126/R02C08"
        slow=OUT/"pilot"/relative;fast=OUT/"pilot_fast"/relative
        a=require_complete(slow);b=require_complete(fast)
        if a["sources"]!=b["sources"] or a["snapshots"]!=b["snapshots"]:
            raise ValueError("Pilot source identities differ")
        for name in ("cells_2050.nc","duration_hist_2050.nc","sync_2050.nc"):
            with xr.open_dataset(slow/name,decode_times=False) as ds0,xr.open_dataset(fast/name,decode_times=False) as ds1:
                if dict(ds0.sizes)!=dict(ds1.sizes):raise ValueError("Pilot dimensions differ")
                for coord in ds0.coords:
                    if not np.array_equal(ds0[coord],ds1[coord]):raise ValueError("Pilot coordinates differ")
                for var in ds0.data_vars:
                    x=ds0[var].values;y=ds1[var].values
                    if np.issubdtype(x.dtype,np.integer):
                        if not np.array_equal(x,y):raise ValueError(f"Integer mismatch: {tech}/{name}/{var}")
                    elif not np.allclose(x,y,rtol=1e-10,atol=1e-5,equal_nan=True):
                        raise ValueError(f"Floating mismatch: {tech}/{name}/{var}")
                    checks.append(dict(tech=tech,file=name,variable=var,max_abs_difference=float(np.nanmax(np.abs(x-y)))))
        print("PILOT MATCH",tech,"Python seconds",a["elapsed_seconds"],"compiled seconds",b["elapsed_seconds"],flush=True)
    folder=OUT/"pilot_fast/validation";folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/"checks.json",dict(status="PASSED",checks=checks))
    marker(folder,comparison="Full ten-year, two-technology real-data equivalence",
           full_scope=1128,source_patch="R02C08")
    print("PILOT VALIDATION PASSED",flush=True)

if __name__=="__main__":
    main()
