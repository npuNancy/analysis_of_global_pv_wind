"""Area-time weighted native-grid humidity distributions from indexed provenance."""
from __future__ import annotations
import argparse
import itertools
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr

from paper_figures.config import ROOT, MODELS, SSPS
from utils.data_access.read_extreme_grid import find_records

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs/meeting_humidity"
REGIONS = ("GLOBAL", "30S-0", "60N-90N")
BINS = np.arange(0., 101., 5.)


def tasks():
    metadata = json.loads((ROOT / "paper_figures/prepare/outputs/event_summary/complete.json").read_text())
    return list(itertools.product(MODELS, SSPS, metadata["patches"]))


def run_one(index, snapshots, max_chunks, out):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Raw meteorological reads require a SLURM compute job.")
    model, ssp, patch = tasks()[index]
    records = find_records(model=model, climate_scenario=ssp, patch=patch, tech="wind", years=(2015, 2015))
    if len(records) != 1:
        raise ValueError("Expected one indexed provenance source")
    with netCDF4.Dataset(records[0]["path"]) as ds:
        provenance = json.loads(ds.provenance)
    input_record = provenance["inputs"]["hurs"]
    path = Path(input_record["path"])
    stat = path.stat()
    if stat.st_size != input_record["size"]:
        raise ValueError("Humidity source size differs from signal provenance")
    shared = ROOT / "paper_figures/prepare/outputs/grid_events"
    masks = []
    for tech in ("wind", "solar"):
        with xr.open_dataset(shared / tech / patch / "period_hours.nc") as ds:
            masks.append(ds.common_mask.astype(bool).all("snapshot").values)
            if tech == "wind":
                area = ds.cell_area_km2.values
                lat, lon = ds.lat.values, ds.lon.values
            elif not (np.array_equal(lat, ds.lat.values) and np.array_equal(lon, ds.lon.values)):
                raise ValueError("Wind and solar support axes differ")
    support = masks[0] & masks[1]
    latitude = np.broadcast_to(lat[:, None], support.shape)
    region_masks = [support, support & (latitude >= -30) & (latitude < 0), support & (latitude >= 60)]
    started = time.monotonic()
    rows, hist_rows, completed = [], [], []
    out.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(path) as ds:
        if not (np.array_equal(ds["lat"][:], lat) and np.array_equal(ds["lon"][:], lon)):
            raise ValueError("Raw humidity grid differs from accepted support")
        tv = ds["time"]
        calendar = getattr(tv, "calendar", "standard")
        times = np.asarray(tv[:])
        dates = netCDF4.num2date(times, tv.units, calendar=calendar, only_use_cftime_datetimes=True)
        years = np.fromiter((d.year for d in dates), dtype=int)
        stamps = netCDF4.date2num(dates, "hours since 2000-01-01", calendar=calendar)
        if not np.allclose(np.diff(stamps), 3.):
            raise ValueError("Nonregular raw humidity time axis")
        var = ds["hurs"]
        if var.dimensions != ("time", "lat", "lon"):
            raise ValueError("Unexpected raw humidity dimension order")
        raw_units = getattr(var, "units", None)
        observed_min, observed_max = float("inf"), float("-inf")
        var.set_var_chunk_cache(128 * 1024**2, 1009, .75)
        for snapshot in snapshots:
            indices = np.flatnonzero((years >= snapshot) & (years < snapshot + 10))
            if not len(indices) or not np.array_equal(indices, np.arange(indices[0], indices[-1] + 1)):
                raise ValueError("Incomplete/noncontiguous decade")
            expected = float(netCDF4.date2num(type(dates[0])(snapshot + 10, 1, 1), tv.units, calendar=calendar)
                             - netCDF4.date2num(type(dates[0])(snapshot, 1, 1), tv.units, calendar=calendar))
            # Use the native coordinate interval, including no-leap calendars.
            nominal_steps = int(round(expected / np.median(np.diff(times))))
            if not (nominal_steps - 1 <= len(indices) <= nominal_steps):
                raise ValueError("More than one boundary sample is absent from a decade")
            totals = np.zeros((len(REGIONS), 7), dtype=float)
            hist = np.zeros((len(REGIONS), len(BINS)-1), dtype=float)
            n_chunks = n_steps = 0
            boundaries = [int(indices[0])] + list(range((int(indices[0]) // 240 + 1) * 240, int(indices[-1]) + 1, 240)) + [int(indices[-1]) + 1]
            for begin, end in zip(boundaries[:-1], boundaries[1:]):
                if max_chunks and n_chunks >= max_chunks:
                    break
                arr = np.asarray(np.ma.filled(var[begin:end], np.nan), dtype=np.float32)
                selected = arr[:, support]
                if np.isfinite(selected).any():
                    observed_min = min(observed_min, float(np.nanmin(selected)))
                    observed_max = max(observed_max, float(np.nanmax(selected)))
                del selected
                for ri, mask in enumerate(region_masks):
                    if not mask.any():
                        continue
                    values = arr[:, mask]
                    weights = np.broadcast_to(area[mask], values.shape)
                    valid = np.isfinite(values)
                    invalid_range = valid & ((values < 0) | (values > 100))
                    if invalid_range.any():
                        raise ValueError(f"Out-of-range relative humidity: {values[invalid_range][:10]}")
                    v, w = values[valid], weights[valid]
                    totals[ri, 0] += w.sum()
                    totals[ri, 1] += np.dot(v.astype(float), w)
                    totals[ri, 2] += w[v >= 85].sum()
                    totals[ri, 3] += w[v >= 90].sum()
                    totals[ri, 4] += w[v >= 95].sum()
                    totals[ri, 5] += (end - begin) * area[mask].sum()
                    totals[ri, 6] += valid.sum()
                    # Each bin is a fraction of grid-area x native three-hour samples.
                    bin_index = np.minimum((v / 5).astype(np.int32), len(BINS) - 2)
                    hist[ri] += np.bincount(bin_index, weights=w, minlength=len(BINS)-1)
                n_chunks += 1
                n_steps += end - begin
                if n_chunks % 20 == 0 or n_chunks == 1:
                    print("READ", model, ssp, patch, snapshot, n_chunks, round(time.monotonic()-started, 1), flush=True)
            complete = n_steps == len(indices)
            if complete:
                for ri, mask in enumerate(region_masks):
                    totals[ri, 5] = nominal_steps * area[mask].sum()
            completed.append(complete)
            for ri, region in enumerate(REGIONS):
                common = dict(model=model, climate_ssp=ssp, patch=patch, snapshot=snapshot, region=region,
                              complete=complete, calendar=calendar, n_steps=n_steps,
                              n_expected_steps=nominal_steps, area_km2=float(area[region_masks[ri]].sum()),
                              n_cells=int(region_masks[ri].sum()))
                rows.append(dict(**common, valid_area_steps=totals[ri,0], rh_area_steps=totals[ri,1],
                                 ge85_area_steps=totals[ri,2], ge90_area_steps=totals[ri,3],
                                 ge95_area_steps=totals[ri,4], expected_area_steps=totals[ri,5],
                                 valid_cell_steps=int(totals[ri,6])))
                if not np.isclose(hist[ri].sum(), totals[ri, 0], rtol=1e-10, atol=1.):
                    raise ValueError("Histogram does not close to valid area-time denominator")
                for bi, value in enumerate(hist[ri]):
                    hist_rows.append(dict(**common, rh_lower=BINS[bi], rh_upper=BINS[bi+1],
                                          area_steps=value))
    name = f"{model}_{ssp}_{patch}"
    pd.DataFrame(rows).to_csv(out / f"{name}_moments.csv", index=False)
    pd.DataFrame(hist_rows).to_csv(out / f"{name}_histogram.csv", index=False)
    metadata = dict(task=index, model=model, climate_ssp=ssp, patch=patch, snapshots=snapshots,
                    complete=all(completed), raw_source=input_record, signal_provenance=records[0],
                    raw_time_basis="Native hurs timestamps; no retiming of binary event signals",
                    weighting="Accepted wind/solar intersected spatial support, native cell area and three-hour samples",
                    units="Relative humidity in percent; physical range [0,100] checked",
                    source_units_attribute=raw_units, observed_min=observed_min, observed_max=observed_max,
                    elapsed_seconds=time.monotonic()-started)
    (out / f"{name}_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2), flush=True)


def aggregate(out, snapshots):
    expected = tasks()
    all_moments, all_hist = [], []
    for model, ssp, patch in expected:
        stem = f"{model}_{ssp}_{patch}"
        meta = json.loads((out / "shards" / f"{stem}_metadata.json").read_text())
        if not meta["complete"] or meta["snapshots"] != snapshots:
            raise ValueError("Partial or mismatched-decade shard cannot be aggregated")
        if (meta["model"], meta["climate_ssp"], meta["patch"]) != (model, ssp, patch):
            raise ValueError("Shard identity differs from the expected task")
        moment = pd.read_csv(out / "shards" / f"{stem}_moments.csv")
        histogram = pd.read_csv(out / "shards" / f"{stem}_histogram.csv")
        expected_keys = set(itertools.product(snapshots, REGIONS))
        if len(moment) != len(expected_keys) or set(zip(moment.snapshot, moment.region)) != expected_keys:
            raise ValueError("Missing or duplicate moment rows")
        if len(histogram) != len(expected_keys) * (len(BINS)-1):
            raise ValueError("Incomplete histogram bin matrix")
        for key, frame in histogram.groupby(["snapshot", "region"]):
            if key not in expected_keys or not np.array_equal(np.sort(frame.rh_lower), BINS[:-1]):
                raise ValueError("Missing or duplicate histogram bins")
        for frame in (moment, histogram):
            if not frame.complete.all() or not (frame.model.eq(model) & frame.climate_ssp.eq(ssp) & frame.patch.eq(patch)).all():
                raise ValueError("CSV shard identity/completeness mismatch")
        if not np.allclose(moment.expected_area_steps, moment.n_expected_steps * moment.area_km2, rtol=1e-10, atol=1.):
            raise ValueError("Expected area-time denominator differs from the complete native calendar")
        all_moments.append(moment)
        all_hist.append(histogram)
    moments = pd.concat(all_moments, ignore_index=True)
    hist = pd.concat(all_hist, ignore_index=True)
    keys = ["model", "climate_ssp", "snapshot", "region"]
    sums = ["valid_area_steps", "rh_area_steps", "ge85_area_steps", "ge90_area_steps",
            "ge95_area_steps", "expected_area_steps"]
    result = moments.groupby(keys)[sums].sum().reset_index()
    result["mean_rh_pct"] = result.rh_area_steps / result.valid_area_steps
    result["coverage"] = result.valid_area_steps / result.expected_area_steps
    for threshold in (85,90,95):
        result[f"fraction_ge{threshold}"] = result[f"ge{threshold}_area_steps"] / result.valid_area_steps
    histogram = hist.groupby(keys+["rh_lower","rh_upper"]).area_steps.sum().reset_index()
    histogram = histogram.merge(result[keys+["valid_area_steps"]], on=keys, validate="many_to_one")
    histogram["probability"] = histogram.area_steps / histogram.valid_area_steps
    if len(result) != len(MODELS) * len(SSPS) * len(snapshots) * len(REGIONS):
        raise ValueError("Incomplete model/scenario/snapshot/region matrix")
    if not np.allclose(histogram.groupby(keys).probability.sum(), 1., atol=1e-10):
        raise ValueError("Global histogram probabilities do not sum to one")
    if result.coverage.min() < .99:
        raise ValueError("Area-time coverage falls below 99 percent")
    tail = histogram[histogram.rh_lower == 95].merge(result[keys+["fraction_ge95"]], on=keys, validate="one_to_one")
    tail_error = float((tail.probability - tail.fraction_ge95).abs().max())
    if tail_error > 1e-10:
        raise ValueError("RH >=95% histogram bin differs from the independent threshold count")
    if not ((result.fraction_ge95 <= result.fraction_ge90 + 1e-12) & (result.fraction_ge90 <= result.fraction_ge85 + 1e-12)).all():
        raise ValueError("Humidity exceedance probabilities are not nested")
    support_summary = moments.groupby(keys)[["area_km2","n_cells"]].sum().reset_index()
    (out / "source_data").mkdir(exist_ok=True)
    result.to_csv(out / "source_data/humidity_models.csv", index=False)
    histogram.to_csv(out / "source_data/humidity_histogram_models.csv", index=False)
    metric_units = {"mean_rh_pct": "percentage_points", "fraction_ge85": "fraction", "fraction_ge90": "fraction", "fraction_ge95": "fraction"}
    long = result.melt(id_vars=keys, value_vars=list(metric_units), var_name="metric", value_name="value")
    summary = long.groupby(["climate_ssp", "snapshot", "region", "metric"]).value.agg(["mean","min","max","count"]).reset_index()
    summary.to_csv(out / "source_data/humidity_summary.csv", index=False)
    contrasts = []
    baseline = long[long.climate_ssp == "ssp126"].drop(columns="climate_ssp")
    for target in ("ssp245", "ssp585"):
        frame = long[long.climate_ssp == target].merge(baseline, on=["model","snapshot","region","metric"], suffixes=("_target","_ref"), validate="one_to_one")
        frame["comparison"] = target + "-ssp126"
        frame["change"] = frame.value_target - frame.value_ref
        contrasts.append(frame[["model","snapshot","region","metric","comparison","change"]])
    if 2015 in snapshots and 2050 in snapshots:
        early = long[long.snapshot == 2015].drop(columns="snapshot")
        frame = long[long.snapshot == 2050].merge(early, on=["model","climate_ssp","region","metric"], suffixes=("_target","_ref"), validate="one_to_one")
        frame["comparison"] = frame.climate_ssp + ":2050s-2015s"
        frame["change"] = frame.value_target - frame.value_ref
        contrasts.append(frame[["model","snapshot","region","metric","comparison","change"]])
    changes = pd.concat(contrasts, ignore_index=True)
    changes["units"] = changes.metric.map(metric_units)
    changes.to_csv(out / "source_data/humidity_changes_models.csv", index=False)
    change_keys = ["snapshot","region","metric","comparison","units"]
    agreement = changes.groupby(change_keys).change.agg(mean="mean", minimum="min", maximum="max", n_models="count",
        positive_models=lambda x: int((x > 0).sum()), negative_models=lambda x: int((x < 0).sum())).reset_index()
    if not agreement.n_models.eq(4).all():
        raise ValueError("Incomplete four-model humidity contrasts")
    agreement.to_csv(out / "source_data/humidity_changes_summary.csv", index=False)
    plot(out, result, histogram)
    (out / "metadata.json").write_text(json.dumps(dict(
        complete=True, task_count=len(expected), snapshots=snapshots,
        minimum_area_time_coverage=float(result.coverage.min()),
        maximum_histogram_threshold_difference=tail_error,
        spatial_support=support_summary[support_summary.model.eq(MODELS[0]) & support_summary.climate_ssp.eq(SSPS[0]) & support_summary.snapshot.eq(snapshots[0])][["region","area_km2","n_cells"]].to_dict(orient="records"),
        models=list(MODELS), scenarios=list(SSPS), regions=list(REGIONS),
        uncertainty="Four-model minimum-maximum; not a confidence interval",
        weighting="Native hurs grid area times three-hour samples on intersected wind/solar spatial support"
    ), indent=2))


def plot(out, result, histogram):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"ssp126":"#1d3b6f", "ssp245":"#b77c19", "ssp585":"#9e1b1b"}
    plt.rcParams.update({"font.size":7, "axes.spines.top":False, "axes.spines.right":False})
    plot_top = np.ceil(100 * histogram.probability.max() / 5) * 5
    for snap in sorted(result.snapshot.unique()):
        fig, axes = plt.subplots(1, 3, figsize=(183/25.4, 75/25.4), layout="constrained")
        for ri, (region, ax) in enumerate(zip(REGIONS, axes)):
            for ssp in SSPS:
                sub = histogram[(histogram.region == region) & (histogram.snapshot == snap) & (histogram.climate_ssp == ssp)]
                summary = sub.groupby("rh_lower").probability.agg(["mean","min","max"])
                ax.stairs(100*summary["mean"].to_numpy(), BINS, color=colors[ssp], label=ssp.upper(), baseline=None)
                lower = 100*summary["min"].to_numpy()
                upper = 100*summary["max"].to_numpy()
                ax.fill_between(BINS, np.r_[lower, lower[-1]], np.r_[upper, upper[-1]], step="post", color=colors[ssp], alpha=.13)
            ax.set(title=f"{chr(97+ri)}  {region}\n{snap}-{snap+9}", xlabel="Relative humidity (%)",
                   ylabel="Area-time frequency per 5-point RH bin (%)", xlim=(0,100), ylim=(0,plot_top))
            ax.axvline(95, color="0.5", lw=.7, ls=":", label="RH 95%")
        for ax in axes:
            ax.legend(fontsize=6, loc="upper left")
        fig.savefig(out / f"humidity_histogram_{snap}.png", dpi=600)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for ri, ax in enumerate(axes):
            bounds = ax.get_tightbbox(renderer).transformed(fig.dpi_scale_trans.inverted()).expanded(1.03,1.06)
            fig.savefig(out / f"humidity_histogram_{snap}_{chr(97+ri)}.png", dpi=600, bbox_inches=bounds)
        plt.close(fig)


def run_task(args):
    return run_one(*args)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--task-index", type=int)
    parser.add_argument("--batch", type=int, default=int(os.environ.get("SLURM_ARRAY_TASK_ID", "0")))
    parser.add_argument("--batches", type=int, default=8)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))
    parser.add_argument("--snapshots", nargs="+", type=int, default=[2015,2050])
    parser.add_argument("--max-chunks", type=int, default=0)
    parser.add_argument("--output-root", type=Path, default=OUT)
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args()
    if args.max_chunks < 0 or (args.task_index is not None and not 0 <= args.task_index < len(tasks())):
        parser.error("Invalid task index or chunk limit")
    if args.batches < 1 or not 0 <= args.batch < args.batches or args.workers < 1:
        parser.error("Invalid batch or worker count")
    if len(set(args.snapshots)) != len(args.snapshots) or any(s not in (2015,2030,2040,2050) for s in args.snapshots):
        parser.error("Use unique snapshot years from 2015, 2030, 2040, 2050")
    if args.aggregate:
        aggregate(args.output_root, args.snapshots)
    else:
        folder = args.output_root / ("pilot" if args.max_chunks else "shards")
        if args.task_index is not None:
            run_one(args.task_index, args.snapshots, args.max_chunks, folder)
        else:
            indices = list(range(len(tasks())))[args.batch::args.batches]
            pending = []
            for index in indices:
                model, ssp, patch = tasks()[index]
                marker = folder / f"{model}_{ssp}_{patch}_metadata.json"
                if marker.exists() and not args.max_chunks:
                    existing = json.loads(marker.read_text())
                    if existing["complete"] and existing["snapshots"] == args.snapshots:
                        print("REUSE", index, model, ssp, patch, flush=True)
                        continue
                    raise ValueError("Existing shard has incompatible coverage")
                pending.append((index, args.snapshots, args.max_chunks, folder))
            with ProcessPoolExecutor(max_workers=args.workers, mp_context=get_context("spawn")) as pool:
                list(pool.map(run_task, pending))
            print("BATCH_COMPLETE", args.batch, len(indices), flush=True)


if __name__ == "__main__":
    main()
