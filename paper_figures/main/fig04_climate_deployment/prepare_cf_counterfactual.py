"""Aggregate annual station CF for the Fig. 4 counterfactual matrices."""
import argparse
import json
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
import cftime
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, MIN_TIME_COVERAGE
from paper_figures.common.io import write_csv, write_json, digest
from utils.data_access import read_cf_stations as reader

HERE = Path(__file__).resolve().parent
CACHE = HERE / "outputs/source_data/cf_counterfactual_shards"

def tasks():
    return [(p.parent.parent.name, p.parent.name, p.name, m)
            for p in sorted((OUTPUT / "loss_shards").glob("*/*/*"))
            if p.is_dir() and (p / "station_support.csv.gz").exists()
            for m in MODELS]

def cache_root(snapshot):
    return CACHE if snapshot == 2050 else CACHE.with_name(CACHE.name + "_" + str(snapshot))

def run(task, snapshot=2050):
    s, tech, patch, model = task
    dest = cache_root(snapshot) / s / tech / patch / model
    done = dest / "complete.json"
    if done.exists():
        meta = json.loads(done.read_text())
        if meta["status"] == "EMPTY":
            return
        assert digest(dest / "annual.csv") == meta["annual_sha256"]
        return
    dest.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "loss_shards" / s / tech / patch / "station_support.csv.gz"
    st = pd.read_csv(path, dtype={"station_id": str})
    st = st[st.snapshot.eq(snapshot) & st.common].sort_values("station_id")
    if st.empty:
        write_json(done, {"status": "EMPTY", "task": task})
        return
    ids = st.station_id.to_numpy()
    assert len(set(ids)) == len(ids)
    cap = st.capacity_mw.to_numpy()
    assert np.isfinite(cap).all() and (cap > 0).all()
    n = len(st)
    rows, sources = [], []
    for climate in SSPS:
        records = reader.find_records(model=model, climate_scenario=climate,
            station_scenario=s, tech=tech, patch=patch, years=(snapshot, snapshot + 9))
        sums = np.zeros((10, n), dtype=np.float64)
        counts = np.zeros((10, n), dtype=np.int32)
        observed = np.zeros(10, dtype=np.int32)
        previous, calendar = None, None
        for rec in records:
            sources.append(rec)
            with reader.open_record(rec, years=(snapshot, snapshot + 9), variables=[tech + "_cf"]) as ds:
                for key, value in [("model", model), ("climate_scenario", climate),
                                   ("station_scenario", s), ("tech", tech), ("source_patch", patch)]:
                    assert ds.attrs[key] == value, (key, ds.attrs.get(key), value)
                rawids = ds.station_id.values.astype(str)
                assert len(set(rawids)) == len(rawids)
                positions = {sid: i for i, sid in enumerate(rawids)}
                ix = np.array([positions[sid] for sid in ids])
                cal = ds.time.dt.calendar
                if calendar is None:
                    calendar = cal
                assert calendar == cal
                times = ds.time.values
                joined = times if previous is None else np.concatenate([[previous], times])
                hours = np.array([float(x / np.timedelta64(1, "h"))
                    if isinstance(x, np.timedelta64) else x.total_seconds() / 3600
                    for x in np.diff(joined)])
                assert (hours == 3).all(), "Gap or overlap in native CF times"
                previous = times[-1]
                yy = ds.time.dt.year.values
                for start in range(0, len(times), 240):
                    sl = slice(start, start + 240)
                    values = ds[tech + "_cf"].isel(time=sl).transpose("time", "station").values[:, ix]
                    valid = np.isfinite(values)
                    assert not ((values[valid] < -1e-6) | (values[valid] > 1 + 1e-6)).any()
                    years = yy[sl]
                    for year in np.unique(years):
                        take = years == year
                        yi = int(year) - snapshot
                        counts[yi] += valid[take].sum(axis=0)
                        sums[yi] += np.where(valid[take], values[take], 0).sum(axis=0, dtype=np.float64)
                        observed[yi] += int(take.sum())
        expected = np.array([int((cftime.datetime(y+1, 1, 1, calendar=calendar) -
            cftime.datetime(y, 1, 1, calendar=calendar)).total_seconds() / 10800)
            for y in range(snapshot, snapshot + 10)])
        assert np.array_equal(observed, expected), (task, climate, observed, expected)
        coverage = counts / expected[:, None]
        assert (coverage >= MIN_TIME_COVERAGE).all(), (task, climate, float(coverage.min()))
        for yi, year in enumerate(range(snapshot, snapshot + 10)):
            rows.append(dict(model=model, climate_ssp=climate, station_ssp=s,
                tech=tech, patch=patch, snapshot=snapshot, year=year, country="GLOBAL",
                n_stations=n, capacity_mw=float(cap.sum()),
                capacity_cf_mw=float(np.dot(sums[yi] / counts[yi], cap)),
                valid_capacity_hours=float(np.dot(counts[yi] * 3., cap)),
                expected_hours=int(expected[yi] * 3),
                min_station_time_coverage=float(coverage[yi].min()), calendar=calendar))
        print("CF", snapshot, s, tech, patch, model, climate, n,
              "min_time_coverage", float(coverage.min()), flush=True)
    write_csv(dest / "annual.csv", pd.DataFrame(rows))
    write_json(dest / "sources.json", sources)
    write_json(done, dict(status="COMPLETED", task=task, rows=len(rows),
        support_sha256=digest(path), annual_sha256=digest(dest / "annual.csv"),
        job_id=os.environ.get("SLURM_JOB_ID")))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=16)
    ap.add_argument("--task", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--snapshots", type=int, nargs="+", choices=[2030, 2040, 2050], default=[2030, 2040, 2050])
    args = ap.parse_args()
    all_tasks = tasks()
    if args.task is not None:
        for snapshot in args.snapshots:
            run(all_tasks[args.task], snapshot)
        return
    shard = int(os.environ.get("SLURM_ARRAY_TASK_ID", "0"))
    assert 0 <= shard < args.shards
    assert args.workers <= int(os.environ.get("SLURM_CPUS_PER_TASK", str(args.workers)))
    with ProcessPoolExecutor(max_workers=args.workers,
            mp_context=multiprocessing.get_context("spawn")) as pool:
        for snapshot in args.snapshots:
            list(pool.map(partial(run, snapshot=snapshot), all_tasks[shard::args.shards], chunksize=1))
    print("SHARD COMPLETE", shard, len(all_tasks[shard::args.shards]), flush=True)

if __name__ == "__main__":
    main()
