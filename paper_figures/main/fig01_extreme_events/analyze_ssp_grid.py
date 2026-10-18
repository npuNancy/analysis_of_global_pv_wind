"""Compare climate SSPs on common native grids, with event/overlap accounting."""
import argparse
import itertools
import os
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, SNAPSHOTS, TECHS, EVENTS
from paper_figures.common.io import require_complete, write_csv, write_json, digest
from paper_figures.common.spatial import countries, assign

OUT = ROOT / "paper_figures/main/fig01_extreme_events/outputs/ssp_grid"
PAIRS = (("ssp245", "ssp126"), ("ssp585", "ssp126"), ("ssp585", "ssp245"))
EPS = 1e-6

def require(ok, message):
    if not ok:
        raise ValueError(message)

def summarize(frame, keys, value):
    g = frame.groupby(keys)[value]
    result = g.agg(mean="mean", minimum="min", maximum="max", n_models="count").reset_index()
    require(result.n_models.eq(4).all(), "Incomplete model matrix")
    positive = g.apply(lambda v: int((v > EPS).sum())).reset_index(name="positive_models")
    negative = g.apply(lambda v: int((v < -EPS).sum())).reset_index(name="negative_models")
    return result.merge(positive, on=keys).merge(negative, on=keys)

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--pilot", action="store_true")
    a = p.parse_args()
    out = OUT / "pilot" if a.pilot else OUT
    out.mkdir(parents=True, exist_ok=True)
    patches = require_complete(OUTPUT / "event_summary")["patches"]
    require(len(patches) == 47 and len(set(patches)) == 47, "Patch scope")
    if a.pilot:
        patches = patches[:1]
    geo = countries()
    names = dict((iso, name) for iso, name, _ in geo)
    require("CHN" in names and "TWN" not in names, "China geometry")
    totals, spatial, ranks, maps, coverage, sources = [], [], [], [], [], []
    seen = {}
    for tech, patch in itertools.product(TECHS, patches):
        folder = OUTPUT / "grid_events" / tech / patch
        receipt = require_complete(folder)
        require(set(receipt["models"]) == set(MODELS), "Cache model scope")
        path = folder / "period_hours.nc"
        sources.append(dict(path=str(path), bytes=path.stat().st_size, sha256=digest(path)))
        events = ["all", *EVENTS[tech]]
        with xr.open_dataset(path) as ds:
            require(set(ds.event.values.astype(str)) == set(events), "Event scope")
            mask = ds.common_mask.astype(bool).all("snapshot").values
            lat, lon = np.meshgrid(ds.lat.values, (ds.lon.values + 180) % 360 - 180, indexing="ij")
            yy, xx = lat[mask], lon[mask]
            area = ds.cell_area_km2.values[mask].astype(float)
            # One model/scenario/window slice at a time avoids loading unused cells.
            v = np.empty((4, 3, 3, len(events), len(area)), dtype=float)
            for mi, model in enumerate(MODELS):
                for ci, ssp in enumerate(SSPS):
                    for si, snap in enumerate(SNAPSHOTS):
                        v[mi, ci, si] = ds.event_hours.sel(model=model, climate_ssp=ssp,
                            snapshot=snap, event=events).values[:, mask].astype(float) / 24
            coverage.append(dict(tech=tech, patch=patch, n_cells=len(area), area_km2=area.sum()))
        require(np.isfinite(v).all() and (v >= 0).all(), "Invalid event exposure")
        require((v[..., 1:, :] <= v[..., :1, :] + EPS).all(), "Event exceeds union")
        redundancy = v[..., 1:, :].sum(axis=3) - v[..., 0, :]
        require((redundancy >= -1e-4).all(), f"Union exceeds event sum: {redundancy.min()} days")
        print(f"Minimum overlap redundancy: {redundancy.min():.8g} days", flush=True)
        # Negative redundancy is the exact overlap correction in the accounting identity.
        v = np.concatenate([v, -redundancy[..., None, :]], axis=3)
        events += ["overlap_correction"]
        coords = set(zip(np.round(yy, 7), np.round(xx, 7)))
        require(len(coords) == len(area), "Duplicate within patch")
        previous = seen.setdefault(tech, set())
        require(not previous.intersection(coords), "Duplicate native cells between patches")
        previous.update(coords)
        country = assign(xx, yy, geo)
        latitude = np.select([yy < -60, yy < -30, yy < 0, yy < 30, yy < 60],
            ["90S-60S", "60S-30S", "30S-0", "0-30N", "30N-60N"], default="60N-90N")
        for scope, labels in [("global", np.full(len(area), "GLOBAL")),
                              ("country", country), ("latitude", latitude)]:
            ids, inv = np.unique(labels, return_inverse=True)
            areas = np.bincount(inv, weights=area)
            counts = np.bincount(inv)
            for mi, ci, si, ei in itertools.product(range(4), range(3), range(3), range(len(events))):
                numer = np.bincount(inv, weights=v[mi, ci, si, ei] * area)
                for ri, region in enumerate(ids):
                    totals.append((tech, scope, region, MODELS[mi], SSPS[ci], SNAPSHOTS[si],
                        events[ei], numer[ri], areas[ri], counts[ri]))
        for si, snap in enumerate(SNAPSHOTS):
            means = v[:, :, si].mean(axis=0)
            for ei, event in enumerate(events[:-1]):
                order = np.argsort(means[:, ei], axis=0, kind="stable")
                ties = np.any(np.abs(np.diff(np.sort(means[:, ei], axis=0), axis=0)) <= EPS, axis=0)
                for permutation in itertools.permutations(range(3)):
                    selected = np.all(order == np.array(permutation)[:, None], axis=0) & ~ties
                    ranks.append((tech, snap, event, "<".join(SSPS[i] for i in permutation),
                                  area[selected].sum(), area.sum()))
                ranks.append((tech, snap, event, "tie", area[ties].sum(), area.sum()))
            for high, low in PAIRS:
                delta = v[:, SSPS.index(high), si] - v[:, SSPS.index(low), si]
                for ei, event in enumerate(events):
                    d = delta[:, ei]
                    avg = d.mean(axis=0)
                    conditions = {
                        "mean_positive": avg > EPS, "mean_negative": avg < -EPS,
                        "mean_near_zero": np.abs(avg) <= EPS,
                        "positive_4of4": (d > EPS).sum(axis=0) == 4,
                        "negative_4of4": (d < -EPS).sum(axis=0) == 4,
                        "positive_atleast3of4": (d > EPS).sum(axis=0) >= 3,
                        "negative_atleast3of4": (d < -EPS).sum(axis=0) >= 3,
                        "mean_above_1day": avg > 1, "mean_below_minus1day": avg < -1,
                    }
                    for label, selected in conditions.items():
                        spatial.append((tech, snap, high, low, event, label,
                                        area[selected].sum(), area.sum()))
        # One-degree evidence table, retaining model values and all event types for 2050s.
        bins = np.floor(yy).astype(int) * 360 + np.floor(xx).astype(int) + 180
        unique, inv = np.unique(bins, return_inverse=True)
        areas = np.bincount(inv, weights=area)
        for mi, ci, ei in itertools.product(range(4), range(3), range(len(events))):
            numer = np.bincount(inv, weights=v[mi, ci, 2, ei] * area)
            maps.append(pd.DataFrame(dict(tech=tech, model=MODELS[mi], climate_ssp=SSPS[ci],
                event=events[ei], lat=np.floor_divide(unique, 360) + .5,
                lon=unique % 360 - 180 + .5, area_days=numer, area_km2=areas)))
        print(f"Completed {tech}/{patch}: {len(area)} common cells", flush=True)
    keys = ["tech", "scope", "region", "model", "climate_ssp", "snapshot", "event"]
    table = pd.DataFrame(totals, columns=keys + ["area_days", "area_km2", "n_cells"])
    table = table.groupby(keys, as_index=False)[["area_days", "area_km2", "n_cells"]].sum()
    table["days_per_year"] = table.area_days / table.area_km2
    table["region_name"] = table.region.map(names).fillna(table.region)
    write_csv(out / "levels_models.csv.gz", table)
    levels = summarize(table, [k for k in keys if k != "model"], "days_per_year")
    write_csv(out / "levels.csv", levels)
    dkeys = [k for k in keys if k != "climate_ssp"]
    contrasts = []
    for high, low in PAIRS:
        hi = table[table.climate_ssp.eq(high)]
        lo = table[table.climate_ssp.eq(low)]
        joined = hi.merge(lo, on=dkeys, suffixes=("_high", "_low"), validate="one_to_one")
        require(np.allclose(joined.area_km2_high, joined.area_km2_low), "SSP support mismatch")
        row = joined[dkeys].copy()
        row["high"], row["low"] = high, low
        row["difference"] = joined.days_per_year_high - joined.days_per_year_low
        row["area_km2"] = joined.area_km2_high
        contrasts.append(row)
    contrasts = pd.concat(contrasts, ignore_index=True)
    write_csv(out / "contrasts_models.csv.gz", contrasts)
    ckeys = [k for k in dkeys if k != "model"] + ["high", "low"]
    summary = summarize(contrasts, ckeys, "difference")
    write_csv(out / "contrasts.csv", summary)

    explanations = []
    ekeys = ["tech", "scope", "region", "snapshot", "high", "low"]
    for ident, group in summary.groupby(ekeys):
        terms = group.set_index("event")
        event_terms = terms.loc[list(EVENTS[ident[0]]), "mean"]
        pos = event_terms[event_terms > EPS].sort_values(ascending=False)
        neg = event_terms[event_terms < -EPS].sort_values()
        row = dict(zip(ekeys, ident))
        row.update(region_name=names.get(ident[2], ident[2]),
            union_difference=terms.loc["all", "mean"],
            union_minimum=terms.loc["all", "minimum"],
            union_maximum=terms.loc["all", "maximum"],
            positive_models=int(terms.loc["all", "positive_models"]),
            negative_models=int(terms.loc["all", "negative_models"]),
            largest_increasing_event=pos.index[0] if len(pos) else "",
            largest_increase=pos.iloc[0] if len(pos) else 0.0,
            largest_decreasing_event=neg.index[0] if len(neg) else "",
            largest_decrease=neg.iloc[0] if len(neg) else 0.0,
            sum_event_differences=event_terms.sum(),
            overlap_correction_difference=terms.loc["overlap_correction", "mean"])
        explanations.append(row)
    write_csv(out / "regional_explanations.csv", pd.DataFrame(explanations))

    ident = [k for k in dkeys if k != "event"] + ["high", "low"]
    closure = contrasts.pivot(index=ident, columns="event", values="difference")
    for tech in TECHS:
        sub = closure.loc[tech]
        err = sub[list(EVENTS[tech])].sum(axis=1) + sub.overlap_correction - sub["all"]
        require(err.abs().max() < 1e-8, "Event-overlap decomposition does not close")
    # Geographic aggregation must reproduce the global weighted numerator and denominator.
    for scope in ("country", "latitude"):
        gkeys = ["tech", "model", "climate_ssp", "snapshot", "event"]
        regional = table[table.scope.eq(scope)].groupby(gkeys)[["area_days", "area_km2"]].sum()
        glob = table[table.scope.eq("global")].set_index(gkeys)[["area_days", "area_km2"]]
        require(np.allclose(regional.sort_index(), glob.sort_index(), rtol=1e-10, atol=1e-5),
                "Regional/global conservation")
    if not a.pilot:
        old = pd.read_csv(ROOT / "paper_figures/main/fig01_extreme_events/outputs/source_data/panel_event_windows.csv")
        old = old[old.scope.eq("grid")]
        check = table[table.scope.eq("global") & table.event.ne("overlap_correction")].merge(
            old, on=["tech", "model", "climate_ssp", "snapshot", "event"], validate="one_to_one")
        require(len(check) == 468, "Missing global reference rows")
        max_error = float(np.abs(check.days_per_year - check.E / 24).max())
        require(max_error < 1e-5, "Global values do not reproduce accepted tables")
    else:
        max_error = None
    skeys = ["tech", "snapshot", "high", "low", "event", "criterion"]
    sp = pd.DataFrame(spatial, columns=skeys + ["selected_area_km2", "total_area_km2"])
    sp = sp.groupby(skeys, as_index=False)[["selected_area_km2", "total_area_km2"]].sum()
    sp["area_fraction"] = sp.selected_area_km2 / sp.total_area_km2
    write_csv(out / "native_spatial_fractions.csv", sp)
    rkeys = ["tech", "snapshot", "event", "ordering"]
    rank = pd.DataFrame(ranks, columns=rkeys + ["selected_area_km2", "total_area_km2"])
    rank = rank.groupby(rkeys, as_index=False)[["selected_area_km2", "total_area_km2"]].sum()
    rank["area_fraction"] = rank.selected_area_km2 / rank.total_area_km2
    require(np.allclose(rank.groupby(rkeys[:-1]).area_fraction.sum(), 1), "SSP rank partitions")
    write_csv(out / "native_ssp_ordering.csv", rank)
    grid = pd.concat(maps, ignore_index=True).groupby(
        ["tech", "model", "climate_ssp", "event", "lat", "lon"], as_index=False)[["area_days", "area_km2"]].sum()
    grid["days_per_year"] = grid.area_days / grid.area_km2
    write_csv(out / "grid_1degree_2050_models.csv.gz", grid)
    write_csv(out / "coverage.csv", pd.DataFrame(coverage))
    write_json(out / "audit.json", dict(status="PASSED", pilot=a.pilot,
        job_id=os.environ.get("SLURM_JOB_ID"), code_sha256=digest(Path(__file__)),
        models=MODELS, scenarios=SSPS, windows=SNAPSHOTS, patches=patches,
        unit="annual cumulative exposure days (24 hours), not calendar event days",
        spatial_support="native cells common to all models, SSPs, windows and event types",
        weighting="native cell area; equal model weights; no station or capacity weighting",
        zero_tolerance_days=EPS, union_bound_roundoff_tolerance_days=1e-4, reference_max_error_days=max_error,
        decomposition="union difference = sum(event differences) + overlap correction difference",
        overlap="negative of sum(event durations) minus union; includes higher-order multiplicities",
        limitation="Accounting attribution, not causal attribution or unique per-event union allocation.",
        checks=["union bounds", "event-overlap closure", "country and latitude conservation",
                "SSP common support", "native grid uniqueness", "SSP rank partition",
                "four-model completeness", "accepted global table reproduction (full run)"],
        inputs=sources))
    print(f"PASSED: {out}", flush=True)

if __name__ == "__main__":
    main()
