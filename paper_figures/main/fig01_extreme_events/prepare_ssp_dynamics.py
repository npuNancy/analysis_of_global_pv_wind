"""Read indexed grid signals for SSP frequency, duration and spatial synchrony."""
import argparse
import itertools
import json
import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
import time
import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
from scipy.sparse import csr_matrix
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import write_json, write_csv, digest, require_complete
from paper_figures.common.spatial import countries, assign
from utils.data_access.read_extreme_grid import find_records
from importlib import import_module
year_hours = import_module("RQ1_extreme.global.grid.grid_common").year_hours
from .grid_event_dynamics import FastRuns, build_kernel, STAT_NAMES

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/ssp_grid/dynamics"
TIME_UNITS = "seconds since 2000-01-01 00:00:00"

def marker(folder, **kwargs):
    files = [dict(path=str(p), bytes=p.stat().st_size) for p in sorted(folder.iterdir())
             if p.is_file() and p.name != "complete.json" and ".tmp" not in p.name]
    write_json(folder / "complete.json", dict(status="COMPLETED", files=files, **kwargs))

def write_nc(path, ds):
    temp = path.with_suffix(".tmp.nc")
    enc = {k: dict(zlib=True, complevel=1) for k in ds.data_vars}
    ds.to_netcdf(temp, encoding=enc)
    temp.replace(path)

def process(task):
    model, ssp, tech, patch, snaps, output_root, block_size = task
    started = time.monotonic()
    events = ["all", *EVENTS[tech]]
    folder = Path(output_root) / "shards" / tech / model / ssp / patch
    folder.mkdir(parents=True, exist_ok=True)
    code = {p.name: digest(p) for p in (Path(__file__), BASE / "grid_event_dynamics.py", BASE / "grid_event_dynamics.c")}
    records = find_records(model=model, climate_scenario=ssp, patch=patch, tech=tech,
                           years=(min(snaps), max(snaps)+9))
    sources = [dict(path=r["path"], bytes=Path(r["path"]).stat().st_size,
                    mtime_ns=Path(r["path"]).stat().st_mtime_ns, identity=r["identity"]) for r in records]
    if (folder / "complete.json").exists():
        old = require_complete(folder)
        if old["code"] != code or old["snapshots"] != list(snaps) or old["sources"] != sources:
            raise ValueError(f"Existing shard has a different input/code identity: {folder}")
        print("REUSE", model, ssp, tech, patch, flush=True)
        return str(folder)
    shared = OUTPUT / "grid_events" / tech / patch
    require_complete(shared)
    with xr.open_dataset(shared / "period_hours.nc") as ds:
        mask = ds.common_mask.astype(bool).all("snapshot").values
        lat_axis, lon_axis = ds.lat.values, ds.lon.values
        yy, xx = np.meshgrid(lat_axis, (lon_axis+180)%360-180, indexing="ij")
        lat, lon = yy[mask], xx[mask]
        area = ds.cell_area_km2.values[mask]
        expected = {s: ds.event_hours.sel(model=model, climate_ssp=ssp, snapshot=s,
                                          event=events).values[:, mask].astype(float) for s in snaps}
    country = assign(lon, lat, countries())
    band = np.select([lat < -60, lat < -30, lat < 0, lat < 30, lat < 60],
        ["90S-60S", "60S-30S", "30S-0", "0-30N", "30N-60N"], default="60N-90N")
    labels = ["global:GLOBAL"] + ["country:"+s for s in np.unique(country)] + ["latitude:"+s for s in np.unique(band)]
    lookup = {s:i for i,s in enumerate(labels)}
    ids = np.stack([np.zeros(len(area), dtype=int),
        np.array([lookup["country:"+s] for s in country]), np.array([lookup["latitude:"+s] for s in band])])
    weights = csr_matrix((np.tile(area, 3), (ids.ravel(), np.tile(np.arange(len(area)), 3))),
                         shape=(len(labels), len(area)))
    region_area = np.asarray(weights.sum(axis=1)).ravel()
    library = build_kernel(output_root)
    all_rows, audits = [], []
    for snap in snaps:
        selected = [r for r in records if r["start_year"] <= snap+9 and r["end_year"] >= snap]
        run = FastRuns(len(events), len(area), area, ids, len(labels), 10*366*8, library)
        sync_parts, valid_parts, times_parts = [], [], []
        annual_valid = np.zeros((10, len(area)), dtype=np.uint32)
        annual_source = np.zeros(10, dtype=int)
        calendar = last_time = current_year = None
        for rec in selected:
            with netCDF4.Dataset(rec["path"]) as ds:
                ds.set_auto_mask(False)
                if not (np.array_equal(ds["lat"][:],lat_axis) and np.array_equal(ds["lon"][:],lon_axis)):
                    raise ValueError("Source grid is different from accepted common-support grid")
                tv = ds["time"]
                cal = getattr(tv, "calendar", "standard")
                dates = netCDF4.num2date(tv[:], tv.units, calendar=cal, only_use_cftime_datetimes=True)
                stamp = np.rint(netCDF4.date2num(dates, TIME_UNITS, calendar=cal)).astype("i8")
                years = np.array([d.year for d in dates])
                if calendar is None:
                    calendar = cal
                if calendar != cal or not np.all(np.diff(stamp) == 10800):
                    raise ValueError("Calendar or three-hour timestep changes")
                variables = [ds["signal_"+e] for e in EVENTS[tech]]
                for var in variables:
                    var.set_var_chunk_cache(16*1024**2, 1009, .75)
                for year in sorted(set(years) & set(range(snap, snap+10))):
                    if current_year is not None and year != current_year:
                        run.finish_year()
                    current_year = year
                    indices = np.flatnonzero(years == year)
                    annual_source[year-snap] += len(indices)
                    for start in range(int(indices[0]), int(indices[-1])+1, block_size):
                        stop = min(start+block_size, int(indices[-1])+1)
                        tt = stamp[start:stop]
                        if last_time is not None and tt[0]-last_time != 10800:
                            raise ValueError("Missing or overlapping timestamps across source segments")
                        last_time = int(tt[-1])
                        raw = [var[start:stop, :, :][:, mask] for var in variables]
                        valid = np.ones(raw[0].shape, dtype=bool)
                        flags = []
                        for arr, var in zip(raw, variables):
                            binary = (arr == 0) | (arr == 1)
                            if np.any(~binary & (arr != getattr(var, "_FillValue", -127))):
                                raise ValueError("Invalid nonbinary event value")
                            valid &= binary
                            flags.append(arr == 1)
                        del raw
                        union = np.logical_or.reduce(flags)
                        f = [union, *flags]
                        for a in f:
                            a &= valid
                        affected_block, valid_block = run.consume(f, valid)
                        annual_valid[year-snap] += valid.sum(axis=0).astype("u4")
                        sync_parts.append(affected_block)
                        valid_parts.append(valid_block)
                        times_parts.append(tt)
            print("READ", model, ssp, tech, patch, rec["start_year"], flush=True)
        run.finish_year()
        run.finish()
        nominal = np.array([year_hours(y, calendar)/3 for y in range(snap, snap+10)])
        if np.any(annual_source != nominal.astype(int)):
            raise ValueError("Incomplete annual source time axis")
        if np.any(annual_valid / nominal[:, None] < .99 - 1e-8):
            raise ValueError("Common support no longer meets annual 99% validity")
        reproduction = float(np.max(np.abs(run.stats[0]*3/10 - expected[snap])))
        if reproduction > 1e-3:
            raise ValueError(f"Original grid exposure not reproduced: {reproduction} hours")
        sync = np.concatenate(sync_parts)
        valid_area = np.concatenate(valid_parts)
        times = np.concatenate(times_parts)
        aggregated = np.stack([np.asarray(weights @ values.T).T for values in run.stats])
        if not np.allclose(sync.sum(axis=0)*3, aggregated[0]*3, rtol=1e-10, atol=1e-3):
            raise ValueError("Temporal spatial-area integral does not match native-cell exposure")
        if not np.allclose(run.hist.sum(axis=2), aggregated[2], rtol=1e-10, atol=1e-6):
            raise ValueError("Weighted complete-event histogram count mismatch")
        for ei, event in enumerate(events):
            for ri, region in enumerate(labels):
                row = dict(model=model, climate_ssp=ssp, tech=tech, patch=patch, snapshot=snap,
                           event=event, region=region, area_km2=region_area[ri], n_years=10)
                row.update({name: aggregated[si, ei, ri] for si,name in enumerate(STAT_NAMES)})
                all_rows.append(row)
        cells = xr.Dataset({name:(("event","cell"),run.stats[si]) for si,name in enumerate(STAT_NAMES)},
             coords=dict(event=events,cell=np.arange(len(area)),lat=("cell",lat),lon=("cell",lon),
                         cell_area_km2=("cell",area)))
        cells.attrs.update(model=model,climate_ssp=ssp,tech=tech,snapshot=snap,step_hours=3,
                           duration_policy="Complete observed runs only; boundary/missing fragments censored",
                           frequency_policy="Known 0-to-1 starts; complete-event count separately retained")
        write_nc(folder / f"cells_{snap}.nc", cells)
        hist = xr.Dataset(dict(area_event_count=(("event","region","length_steps"),run.hist)),
                          coords=dict(event=events,region=labels,length_steps=np.arange(run.hist.shape[2])))
        write_nc(folder / f"duration_hist_{snap}.nc", hist)
        syn = xr.Dataset(dict(affected_area_km2=(("time","event","region"),sync),
                              valid_area_km2=(("time","region"),valid_area),
                              total_area_km2=("region",region_area)),
                         coords=dict(time=times,event=events,region=labels))
        syn.time.attrs.update(units=TIME_UNITS,calendar=calendar)
        syn.attrs.update(model=model,climate_ssp=ssp,tech=tech,snapshot=snap)
        write_nc(folder / f"sync_{snap}.nc", syn)
        audits.append(dict(snapshot=snap,calendar=calendar,n_steps=len(times),
                           max_exposure_error_hours=reproduction,
                           minimum_annual_time_coverage=float((annual_valid/nominal[:,None]).min()),
                           maximum_missing_area_fraction=float((1-valid_area/region_area).max())))
    write_csv(folder/"regional.csv.gz",pd.DataFrame(all_rows))
    marker(folder,model=model,ssp=ssp,tech=tech,patch=patch,snapshots=list(snaps),
           code=code,sources=sources,support_sha256=digest(shared/"period_hours.nc"),
           audits=audits,elapsed_seconds=time.monotonic()-started)
    print("DONE", model, ssp, tech, patch, round(time.monotonic()-started,1), flush=True)
    return str(folder)

def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--models",nargs="+",default=list(MODELS),choices=MODELS)
    p.add_argument("--ssps",nargs="+",default=list(SSPS),choices=SSPS)
    p.add_argument("--techs",nargs="+",default=list(TECHS),choices=TECHS)
    p.add_argument("--patches",nargs="+")
    p.add_argument("--snapshots",nargs="+",type=int,default=list(SNAPSHOTS),choices=SNAPSHOTS)
    p.add_argument("--output-root",type=Path,default=OUT)
    p.add_argument("--workers",type=int,default=min(8,int(os.environ.get("SLURM_CPUS_PER_TASK","8"))))
    p.add_argument("--time-chunk",type=int,default=240)
    p.add_argument("--batch",type=int,default=0)
    p.add_argument("--batches",type=int,default=1)
    a=p.parse_args()
    if not 0 <= a.batch < a.batches or a.workers < 1 or a.time_chunk < 1:
        p.error("Invalid batch/worker/chunk setting")
    patches=a.patches or require_complete(OUTPUT/"event_summary")["patches"]
    tasks=[(m,s,t,patch,tuple(a.snapshots),str(a.output_root),a.time_chunk)
           for t,m,s,patch in itertools.product(a.techs,a.models,a.ssps,patches)]
    tasks=tasks[a.batch::a.batches]
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=get_context("spawn")) as pool:
        outputs=list(pool.map(process,tasks))
    batch_dir=a.output_root/"batches"/f"{a.batch:03d}"
    batch_dir.mkdir(parents=True,exist_ok=True)
    write_json(batch_dir/"shards.json",outputs)
    marker(batch_dir,batch=a.batch,batches=a.batches,shard_count=len(outputs))
    print("BATCH PASSED",a.batch,len(outputs),flush=True)

if __name__=="__main__":
    main()
