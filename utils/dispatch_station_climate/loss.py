"""Dispatch station losses by event and union, plus full-year generation."""
import argparse
import fcntl
import os
from pathlib import Path
import sys
import time

import netCDF4 as nc
import numpy as np
import xarray as xr

from utils.gem_station_climate.annual import annual_metrics
from utils.gem_station_climate.loss import headers, load_chunk, prepare
from utils.lcoe_station_climate.pipeline import fingerprint, read, require, sha, write_json

ROOT = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage")


def event_chunk(records, begin, end, grid):
    pieces = {}
    for record in records:
        with nc.Dataset(record["path"]) as ds:
            require(np.array_equal(ds["grid_id"][begin:end], grid), "Event station order changed")
            for name in record["variables"]:
                var = ds[name]
                var.set_auto_maskandscale(False)
                values = np.asarray(var[record["start"]:record["stop"], begin:end])
                pieces.setdefault(name, []).append(np.where(np.isin(values, [0, 1]), values, -1).astype("i1"))
    return {k: np.concatenate(v) for k, v in pieces.items()}


def metric_units(name):
    if "_mwh_" in name:
        return "MWh"
    if "_per_mw_" in name:
        return "MWh MW-1"
    if "_hours_" in name:
        return "hours"
    if "_pct_" in name:
        return "%"
    if "_count_" in name:
        return "samples"
    return "1"


def compute_events(cf, flags, dates, years, capacity, baselines, windows):
    from generation_loss.baseline import align_cf_normal_to_time
    from generation_loss.metrics import calculate_all_metrics
    yy = np.asarray([d.year for d in dates])
    result = {}
    for i, year in enumerate(years):
        rows = np.flatnonzero(yy == year)
        base = baselines[next(j for j, (lo, hi) in enumerate(windows) if lo <= year <= hi)]
        coords = {"time": dates[rows], "station": np.arange(cf.shape[1])}
        data = xr.Dataset({"cf": (("time","station"), cf[rows]),
                           "capacity_mw": ("station", capacity[i]),
                           "time_step_hours": ("time", np.full(len(rows), 3.))}, coords=coords)
        normal = xr.Dataset({"cf_normal": (("month_hour_idx","station"), base["cf_normal"])},
                            coords={"month_hour_idx": base["month_hour_idx"], "station": data.station})
        data["cf_normal"] = align_cf_normal_to_time(data, normal)
        signals = xr.Dataset({k: (("time","station"), np.where(v[rows] >= 0, v[rows], np.nan))
                              for k, v in flags.items()}, coords=coords)
        annual = calculate_all_metrics(data, signals, sorted(flags))
        for name, var in annual.data_vars.items():
            if name == "capacity_mw":
                continue
            if name not in result:
                result[name] = np.full((len(years), cf.shape[1]), np.nan)
            result[name][i] = var.values
    return result


def task_identity(taskpath, reference):
    return fingerprint(dict(task_sha256=sha(taskpath),
        code={str(p):sha(p) for p in [Path(__file__), Path(__file__).parents[1]/"gem_station_climate/annual.py",
                                     Path(__file__).parents[1]/"gem_station_climate/loss.py"]},
        reference={p.name:sha(p) for p in (reference/"loss/generation_loss").glob("*.py")}))


def run(root, unit):
    taskpath = root/"runtime/tasks"/(unit+".json")
    task = read(taskpath)
    folder = root/"runtime/units"/unit
    folder.mkdir(parents=True, exist_ok=True)
    reference = Path(task["source_root"])/"inputs/reference_code"
    sys.path.insert(0, str(reference/"loss"))
    from generation_loss.config import EVENTS_BY_TECH
    identity = task_identity(taskpath, reference)
    with (folder/"run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker = folder/"complete.json"
        if marker.exists():
            require(read(marker)["identity"] == identity, "Loss identity changed")
            for item in read(marker)["outputs"]:
                require(Path(item["path"]).stat().st_size == item["size_bytes"], "Loss output changed")
            return
        require(sha(task["mapping"]["path"]) == task["mapping"]["sha256"], "Mapping changed")
        with np.load(task["mapping"]["path"]) as z:
            pos = z[task["station_ssp"]+"_positions"]
            grid = z["grid_id"][pos]
            result = {k:z[k][pos] for k in ["grid_id","latitude","longitude","source_lat","source_lon"]}
            cap = z[task["station_ssp"]+"_capacity"]
        n = len(pos)
        years = np.asarray(task["years"])
        capacity = np.asarray([cap[max(i for i,s in enumerate(task["snapshots"]) if s <= y)] for y in years])
        result.update(years=years, capacity_mw=capacity)
        cfh, dates, calendar = headers(task["cf"], years)
        evh, evdates, evcalendar = headers(task["extreme"], years)
        require(calendar == evcalendar and np.array_equal(dates, evdates), "CF/Extreme native timestamps differ")
        require(set(evh[0]["variables"]) == {"signal_"+s for s in EVENTS_BY_TECH[task["tech"]]}, "Event set mismatch")
        output = root/"outputs"/(unit+".npz")
        native = root/"outputs"/(unit+".nc")
        require(not output.exists() and not native.exists(), "Output exists without completion receipt")
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = native.with_suffix(f".{os.getpid()}.tmp.nc")
        started = time.monotonic()
        with nc.Dataset(tmp, "w") as ds:
            for k,v in {"year":len(years), "station":n, "window":len(task["windows"]), "month_hour_idx":96}.items():
                ds.createDimension(k, v)
            ds.createVariable("year", "i4", ("year",))[:] = years
            ds.createVariable("snapshot_year", "i4", ("year",))[:] = years//10*10
            ds.createVariable("station", "i4", ("station",))[:] = np.arange(n)
            ds.createVariable("station_id", str, ("station",))[:] = np.array(
                [f"dispatch2025:{task['station_ssp']}:{task['tech']}:{g}" for g in grid], dtype=object)
            for k in ["grid_id","latitude","longitude","source_lat","source_lon"]:
                ds.createVariable(k, "i8" if k=="grid_id" else "f8", ("station",))[:] = result[k]
            ds.createVariable("capacity_mw", "f8", ("year","station"))[:] = capacity
            ds["capacity_mw"].units = "MW"
            ds["capacity_mw"].capacity_basis = "MWp/DC" if task["tech"]=="solar" else "MW"
            ds.setncatts(dict(schema="dispatch2025-loss-v1", model=task["model"], climate_scenario=task["climate_ssp"],
                station_scenario=task["station_ssp"], tech=task["tech"], source_patch=task["patch"], calendar=calendar,
                identity=identity, time_step_hours=3, baseline="decadal month-hour normal CF excluding event union",
                event_semantics="Named events and their time union all; missing remains missing",
                wind_energy_scale=1.0))
            for begin in range(0, n, task["station_chunk"]):
                end = min(n, begin+task["station_chunk"])
                cf = load_chunk(cfh, begin, end, grid[begin:end], task["tech"], "cf")
                flags = event_chunk(evh, begin, end, grid[begin:end])
                valid = np.logical_and.reduce([v>=0 for v in flags.values()])
                union = np.where(valid, np.logical_or.reduce([v==1 for v in flags.values()]), -1).astype("i1")
                metrics, baseline = annual_metrics(cf, union, dates, years, task["windows"], 3, reference)
                for key, values in metrics.items():
                    if key == "expected_hours":
                        result[key] = values
                        continue
                    if key not in result:
                        result[key] = np.full((len(years), n), np.nan)
                    result[key][:,begin:end] = values
                if "baseline_cf" not in result:
                    require(len(baseline[0]["month_hour_idx"]) == 96, "Expected 12 x 8 baseline slots")
                    result["baseline_month_hour_idx"] = baseline[0]["month_hour_idx"]
                    result["baseline_years"] = np.asarray(task["windows"])
                    result["baseline_cf"] = np.full((len(baseline),96,n),np.nan,dtype="f4")
                    result["baseline_count"] = np.zeros((len(baseline),96,n),dtype="u2")
                for j,base in enumerate(baseline):
                    result["baseline_cf"][j,:,begin:end] = base["cf_normal"]
                    result["baseline_count"][j,:,begin:end] = base["count"]
                event_metrics = compute_events(cf, flags, dates, years, capacity[:,begin:end], baseline, task["windows"])
                np.testing.assert_allclose(event_metrics["net_generation_loss_mwh_all"],
                    metrics["net_loss_per_mw"]*capacity[:,begin:end], rtol=2e-6, atol=.05, equal_nan=True)
                for suffix in [k.removeprefix("signal_") for k in flags]+["all"]:
                    net=event_metrics["net_generation_loss_mwh_"+suffix]
                    normal=event_metrics["normal_generation_mwh_"+suffix]
                    actual=event_metrics["actual_generation_mwh_"+suffix]
                    positive=event_metrics["generation_loss_mwh_"+suffix]
                    np.testing.assert_allclose(net,normal-actual,rtol=2e-6,atol=.05,equal_nan=True)
                    require(np.all((positive>=-1e-6)|np.isnan(positive)),"Negative positive-loss energy")
                    require(np.all((positive-net>=-1e-5)|np.isnan(net)),"Positive loss below signed loss")
                for name, values in event_metrics.items():
                    if name not in ds.variables:
                        v = ds.createVariable(name, "f8", ("year","station"), zlib=True, complevel=1)
                        v.units = metric_units(name)
                    ds[name][:,begin:end] = values
                for name, values, units in [
                    ("all_generation_mwh", metrics["generation_per_mw"]*capacity[:,begin:end], "MWh"),
                    ("annual_cf", metrics["cf_mean"], "1"),
                    ("cf_valid_count", metrics["cf_valid_count"], "samples"),
                    ("signal_valid_count", metrics["signal_valid_count"], "samples"),
                    ("loss_valid_count", metrics["loss_valid_count"], "samples")]:
                    if name not in ds.variables:
                        ds.createVariable(name, "f8", ("year","station"), zlib=True, complevel=1).units=units
                    ds[name][:,begin:end] = values
                print(unit, end, "/", n, "stations", flush=True)
            ds.createVariable("expected_hours","f8",("year",))[:] = result["expected_hours"]
            ds["expected_hours"].units="hours"
            ds.createVariable("month_hour_idx","i4",("month_hour_idx",))[:] = result["baseline_month_hour_idx"]
            ds.createVariable("baseline_start_year","i4",("window",))[:] = result["baseline_years"][:,0]
            ds.createVariable("baseline_end_year","i4",("window",))[:] = result["baseline_years"][:,1]
            ds.createVariable("cf_normal","f4",("window","month_hour_idx","station"),zlib=True)[:] = result["baseline_cf"]
            ds.createVariable("baseline_count","u2",("window","month_hour_idx","station"),zlib=True)[:] = result["baseline_count"]
            ds["cf_normal"].units="1"
            ds["baseline_count"].units="samples"
            for coord in ["latitude","source_lat"]:ds[coord].units="degrees_north"
            for coord in ["longitude","source_lon"]:ds[coord].units="degrees_east"
        tmparchive = output.with_suffix(f".{os.getpid()}.tmp.npz")
        np.savez_compressed(tmparchive, **result)
        tmparchive.replace(output)
        tmp.replace(native)
        artifacts = [dict(path=str(p),product=product,sha256=sha(p),size_bytes=p.stat().st_size,
                          station_count=n,years=[int(years[0]),int(years[-1])])
                     for p,product in [(output,"annual_union"),(native,"loss")]]
        write_json(marker,dict(status="COMPLETED",unit=unit,identity=identity,calendar=calendar,
            task_sha256=sha(taskpath),job_id=os.environ.get("SLURM_JOB_ID"),account=os.environ.get("USER"),
            wall_seconds=time.monotonic()-started,outputs=artifacts))


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--stage",choices=["prepare","run"],default="prepare")
    p.add_argument("--unit")
    a=p.parse_args()
    if a.stage=="prepare":
        prepare(a.root,"future")
        cfg=read(a.root/"loss_future/inputs/campaign.json")
        cfg["job_dir"]=str(a.root/"loss_future/jobs")
        write_json(a.root/"loss_future/inputs/campaign.json",cfg)
        logdir=Path(cfg["repo"])/"logs/dispatch_2025/loss_future"
        logdir.mkdir(parents=True,exist_ok=True)
        link=a.root/"loss_future/logs"
        if not link.is_symlink():
            link.rmdir()
            link.symlink_to(logdir,target_is_directory=True)
    else:
        require(bool(a.unit),"--unit required")
        run(a.root,a.unit)


if __name__=="__main__":
    main()
