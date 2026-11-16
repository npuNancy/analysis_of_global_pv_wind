"""Validate complete loss calculations on small slices of accepted real pilot series."""
import argparse
from pathlib import Path
import os
import json
import time

import netCDF4 as nc
import numpy as np

from utils.dispatch_station_climate.loss import run
from utils.lcoe_station_climate.pipeline import read, write_json, sha, require

ROOT=Path("/work/home/acxujo26gv/dispatch_2025_climate_storage")
HERE=Path(__file__).resolve().parent


def validate(root,out,count):
    audit=read(root/"future/runtime/pilot_audit.json")
    require(audit["status"]=="COMPLETED","Extraction pilot not accepted")
    (out/"runtime/tasks").mkdir(parents=True,exist_ok=True)
    (out/"mappings").mkdir(exist_ok=True)
    pairs={}
    for source_unit in audit["units"]:
        task=read(root/"future/runtime/tasks"/(source_unit+".json"))
        marker=root/"future/runtime/units"/source_unit/"complete.json"
        done=read(marker)
        require(done["status"]=="COMPLETED","Missing accepted source")
        for scenario in task["mapping"]["station_ssps"]:
            key=(task["model"],task["climate_ssp"],scenario,task["tech"],task["patch"])
            item=pairs.setdefault(key,dict(mapping=task["mapping"],snapshots=task["snapshots"],sources=[]))
            item[task["product"]]=[a for a in done["outputs"] if a["station_scenario"]==scenario]
            item["sources"].append(dict(path=str(marker),sha256=sha(marker)))
    results=[];started=time.monotonic()
    for key,item in sorted(pairs.items()):
        model,climate,scenario,tech,patch=key
        unit="_".join(key)
        require("cf" in item and "extreme" in item,"Missing product pair")
        with np.load(item["mapping"]["path"],allow_pickle=False) as z:
            positions=z[scenario+"_positions"][:count]
            arrays={k:z[k][positions] for k in ["grid_id","latitude","longitude","source_lat","source_lon"]}
            arrays[scenario+"_positions"]=np.arange(len(positions))
            arrays[scenario+"_capacity"]=z[scenario+"_capacity"][:,:len(positions)]
        mapping=out/"mappings"/(unit+".npz")
        if not mapping.exists():np.savez_compressed(mapping,**arrays)
        task=dict(unit=unit,model=model,climate_ssp=climate,station_ssp=scenario,tech=tech,patch=patch,
            years=list(range(2030,2060)),snapshots=item["snapshots"],windows=[[2030,2039],[2040,2049],[2050,2059]],
            source_root=str(root),station_chunk=count,mapping=dict(path=str(mapping),sha256=sha(mapping)),
            cf=item["cf"],extreme=item["extreme"])
        taskfile=out/"runtime/tasks"/(unit+".json")
        if taskfile.exists():require(read(taskfile)==task,"Changed validation task")
        else:write_json(taskfile,task)
        run(out,unit)
        marker=read(out/"runtime/units"/unit/"complete.json")
        with np.load(out/"outputs"/(unit+".npz"),allow_pickle=False) as z, nc.Dataset(out/"outputs"/(unit+".nc")) as ds:
            require(np.isfinite(z["generation_per_mw"]).any(),"No finite generation in pilot slice")
            np.testing.assert_allclose(ds["all_generation_mwh"][:],z["generation_per_mw"]*z["capacity_mw"],rtol=1e-12,atol=1e-8,equal_nan=True)
            np.testing.assert_allclose(ds["annual_cf"][:],z["generation_per_mw"]/z["expected_hours"][:,None],rtol=1e-12,atol=1e-8,equal_nan=True)
            require(np.array_equal(ds["baseline_start_year"][:],[2030,2040,2050]),"Baseline windows")
            results.append(dict(unit=unit,calendar=marker["calendar"],stations=len(positions),years=30,
                finite_generation_cells=int(np.isfinite(z["generation_per_mw"]).sum()),
                finite_loss_cells=int(np.isfinite(z["net_loss_per_mw"]).sum()),
                positive_capacity_cells=int((z["capacity_mw"]>0).sum()),
                sources=item["sources"],outputs=marker["outputs"],
                baseline_shape=list(ds["cf_normal"].shape)))
    write_json(out/"validation.json",dict(status="COMPLETED",units=results,job_id=os.environ.get("SLURM_JOB_ID"),
        wall_seconds=time.monotonic()-started,source_audit_sha256=sha(root/"future/runtime/pilot_audit.json"),
        checks=["native calendars","three full decadal baselines","all named event energy closures",
            "event union","positive loss bounds","native/NPZ generation identity","annual CF integral"],
        scope="Small real station slices; not the full-production acceptance"))
    print("VALIDATED",len(results),"real-data loss slices",flush=True)


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--output-dir",type=Path,default=HERE/"outputs/real_loss_validation")
    p.add_argument("--sample-stations",type=int,default=4)
    a=p.parse_args();require(a.sample_stations>0,"Positive sample count required")
    validate(a.root,a.output_dir,a.sample_stations)


if __name__=="__main__":
    main()
