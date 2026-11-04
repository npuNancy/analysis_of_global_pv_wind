"""Summarize existing cross-technology time-union caches on global/suitable grids."""
import json
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, SSPS, EVENTS
from paper_figures.main.fig01_extreme_events.meeting_common import patches
from paper_figures.supplementary.suitable_grid_extreme.prepare import indices, digest

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DATA = OUT / "source_data"
UNION = ROOT / "paper_figures/main/fig01_extreme_events/outputs/grid_union"
CACHE = ROOT / "RQ1_extreme/global/grid/outputs"
MAPS = ROOT / "paper_figures/supplementary/suitable_grid_extreme/outputs/source_data/patches"
YEARS = np.arange(2030, 2060)


def process(patch):
    arrays, provenance = [], []
    lat = lon = area = domain = None
    for model, ssp in product(MODELS, SSPS):
        path = UNION / model / ssp / (patch + ".nc")
        audit = json.loads(path.with_suffix(".json").read_text())
        assert (audit["model"], audit["ssp"], audit["patch"]) == (model, ssp, patch)
        # Validate the existing reconstruction against native technology caches.
        for tech in ("wind", "solar"):
            check = audit["cache_checks"][tech]
            assert check["mask_agreement"] == 1
            assert max(check["max_abs_diff_by_year"][15:45]) <= .125 + 1e-6
        with netCDF4.Dataset(path) as ds:
            ds.set_auto_mask(False)
            assert (ds.model, ds.scenario, ds.patch) == (model, ssp, patch)
            assert ds.wind_events.split(",") == list(EVENTS["wind"])
            assert ds.solar_events.split(",") == list(EVENTS["solar"])
            yy = list(ds["year"][:]); yi = [yy.index(y) for y in YEARS]
            a = ds["union_days"][yi].astype("f4")
            valid = ds["valid_hours"][yi].astype(float)
            nominal = ds["nominal_hours"][yi].astype(float)
            d = ds["domain_mask"][:] == 1
            expected = d[None] & (valid / nominal[:, None, None] >= .99 - 1e-8)
            assert np.array_equal(np.isfinite(a), expected)
            assert np.all(a[np.isfinite(a)] >= 0)
            assert np.all(np.where(expected, a <= valid / 24 + 1e-6, True))
            if lat is None:
                lat, lon = ds["lat"][:], ds["lon"][:]
                area = ds["cell_area_km2"][:].astype(float)
                domain = d
            else:
                assert np.array_equal(lat, ds["lat"][:]) and np.array_equal(lon, ds["lon"][:])
                assert np.array_equal(area, ds["cell_area_km2"][:])
                domain &= d
            arrays.append(a)
            stat = path.stat()
            provenance.append(dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                                   audit_sha256=digest(path.with_suffix(".json")), pairing=ds.pairing))
    values = np.stack(arrays)
    common = domain & np.isfinite(values).all(axis=(0, 1))
    rows, coverage = [], []
    for i, (model, ssp) in enumerate(product(MODELS, SSPS)):
        for j, year in enumerate(YEARS):
            rows.append(dict(scope="grid", patch=patch, model=model, climate_ssp=ssp, year=int(year),
                             numerator=float(np.dot(values[i, j][common], area[common])),
                             denominator=float(area[common].sum()), n_cells=int(common.sum())))
    members, valid_members = {}, {}
    mapping_sources = []
    for tech in ("wind", "solar"):
        mask = np.zeros(area.shape, bool); good = mask.copy()
        path = MAPS / tech / patch / "mapping.csv.gz"
        if path.exists():
            frame = pd.read_csv(path)
            rr = indices(lat, frame.lat.values); cc = indices(lon % 360, frame.lon.values % 360)
            assert len(set(zip(rr, cc))) == len(frame)
            assert frame.common_valid.isin([True, False]).all()
            mask[rr, cc] = True
            good[rr, cc] = frame.common_valid.to_numpy(dtype=bool)
            mapping_sources.append(dict(path=str(path), sha256=digest(path)))
        members[tech], valid_members[tech] = mask, good
    both = members["wind"] & members["solar"]
    wind_only = members["wind"] & ~members["solar"]
    solar_only = members["solar"] & ~members["wind"]
    union_mask = both & valid_members["wind"] & valid_members["solar"] & common
    own_masks = {"wind": wind_only & valid_members["wind"],
                 "solar": solar_only & valid_members["solar"]}
    suitable = union_mask | own_masks["wind"] | own_masks["solar"]
    catalogue = members["wind"] | members["solar"]
    denominator = float(area[suitable].sum())
    for i, (model, ssp) in enumerate(product(MODELS, SSPS)):
        numerators = np.sum(values[i][:, union_mask] * area[union_mask], axis=1)
        for tech, mask in own_masks.items():
            if not mask.any():
                continue
            path = CACHE / model / "cache" / ssp / tech / (patch + ".nc")
            with netCDF4.Dataset(path) as ds:
                ds.set_auto_mask(False)
                assert np.array_equal(ds["lat"][:], lat) and np.array_equal(ds["lon"][:], lon)
                assert str(ds["event"][0]) == "any"
                yy = list(ds["year"][:]); yi = [yy.index(y) for y in YEARS]
                single = ds["event_days"][yi, 0, :, :][:, mask].astype(float)
                assert np.isfinite(single).all()
                numerators += np.sum(single * area[mask], axis=1)
                stat = path.stat()
                provenance.append(dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                                       fingerprint=ds.fingerprint))
        for j, year in enumerate(YEARS):
            rows.append(dict(scope="suitable_grid", patch=patch, model=model, climate_ssp=ssp,
                             year=int(year), numerator=float(numerators[j]), denominator=denominator,
                             n_cells=int(suitable.sum())))
    coverage.append(dict(patch=patch, grid_common_cells=int(common.sum()),
                         grid_common_area_km2=float(area[common].sum()),
                         suitable_catalogue_cells=int(catalogue.sum()),
                         suitable_common_cells=int(suitable.sum()),
                         suitable_common_area_km2=denominator,
                         both_technologies_cells=int(union_mask.sum()),
                         wind_only_cells=int(own_masks["wind"].sum()),
                         solar_only_cells=int(own_masks["solar"].sum())))
    folder = DATA / "union_patches" / patch
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(folder / "annual.csv", index=False)
    (folder / "provenance.json").write_text(json.dumps(dict(caches=provenance, mappings=mapping_sources), indent=2))
    print("Completed", patch, coverage[0], flush=True)
    return coverage[0]


def main():
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Run cache reduction on a compute node with prepare_union.sh")
    DATA.mkdir(parents=True, exist_ok=True)
    pp = patches()
    # A representative patch passes before the remaining workers start.
    reports = [process("R02C08")]
    with ProcessPoolExecutor(max_workers=min(4, int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))) as pool:
        reports.extend(pool.map(process, [p for p in pp if p != "R02C08"]))
    frames = [pd.read_csv(DATA / "union_patches" / p / "annual.csv") for p in pp]
    data = pd.concat(frames).groupby(["scope", "model", "climate_ssp", "year"], as_index=False)[
        ["numerator", "denominator", "n_cells"]].sum()
    assert len(data) == 2 * 4 * 3 * 30
    assert data.denominator.gt(0).all()
    data["exposure_days"] = data.numerator / data.denominator
    data["tech"] = "wind+solar"
    data["event"] = "cross_technology_union"
    data["snapshot"] = data.year // 10 * 10
    data.to_csv(DATA / "grid_union_annual.csv", index=False)
    data.groupby(["scope", "model", "climate_ssp", "tech", "event", "snapshot"], as_index=False)[
        ["numerator", "denominator", "n_cells", "exposure_days"]].mean().to_csv(
            DATA / "grid_union_decadal.csv", index=False)
    pd.DataFrame(reports).to_csv(DATA / "grid_union_coverage.csv", index=False)
    (OUT / "union_validation.json").write_text(json.dumps(dict(status="PASSED", patches=len(pp),
        annual_rows=len(data), union="all five wind and six solar signal labels; time overlaps counted once",
        temporal_alignment="Existing grid_union cache: solar t paired with wind t+1.5h for the same 3h interval; solar year",
        suitable="spatial union of suitable catalogues; only applicable technology at single-tech cells",
        missingness="at least 99% annual time coverage; observed hours; common spatial support across all 4 models, 3 SSPs, 30 years",
        preparation_job_id=os.environ.get("SLURM_JOB_ID")), indent=2))
    print("Union validation PASSED", flush=True)


if __name__ == "__main__":
    main()
