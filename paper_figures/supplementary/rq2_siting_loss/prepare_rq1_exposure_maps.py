"""Prepare comparable 2020s and 2050s wind–solar exposure maps on suitable cells."""
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from paper_figures.common.io import digest
from paper_figures.config import EVENTS, MODELS, ROOT, SSPS, TECHS
from paper_figures.supplementary.global_metric_trends.prepare_union import CACHE, MAPS, UNION
from paper_figures.supplementary.suitable_grid_extreme.prepare import indices

REFERENCE = ROOT / "paper_figures/supplementary/global_metric_trends/outputs/source_data"
DATA = ROOT / "tmp/RQ1_20261123_candidates/source_data"
DECADES = (2020, 2050)
COVERAGE_YEARS = list(range(2020, 2060))
RESOLUTION = .5
NY, NX = int(180/RESOLUTION), int(360/RESOLUTION)


def mapped_cells(patch, lat, lon):
    """Keep the published distinction between single- and dual-technology suitability."""
    members, valid = {}, {}
    shape = (len(lat), len(lon))
    for tech in TECHS:
        members[tech] = np.zeros(shape,bool)
        valid[tech] = np.zeros(shape,bool)
        path = MAPS/tech/patch/"mapping.csv.gz"
        if path.exists():
            frame = pd.read_csv(path,usecols=["lat","lon","common_valid"])
            rr = indices(lat,frame.lat.to_numpy())
            cc = indices(lon % 360,frame.lon.to_numpy() % 360)
            assert frame.common_valid.isin([True,False]).all()
            assert len(set(zip(rr,cc))) == len(frame)
            members[tech][rr,cc] = True
            valid[tech][rr,cc] = frame.common_valid.to_numpy(dtype=bool)
    return [
        valid["wind"] & valid["solar"],
        valid["wind"] & ~members["solar"],
        valid["solar"] & ~members["wind"],
    ]


def reduce_patch(task):
    patch, fingerprint, expected_cells, expected_area = task
    seed = UNION/MODELS[0]/SSPS[0]/f"{patch}.nc"
    with netCDF4.Dataset(seed) as ds:
        ds.set_auto_mask(False)
        lat,lon = ds["lat"][:],ds["lon"][:]
        weights = ds["cell_area_km2"][:]
    groups = mapped_cells(patch,lat,lon)
    suitable = np.logical_or.reduce(groups)
    assert np.count_nonzero(suitable)==sum(mask.sum() for mask in groups)
    w = weights[suitable]
    assert np.isfinite(w).all() and (w>0).all()
    split = [mask[suitable] for mask in groups]
    means = np.empty((len(MODELS),len(SSPS),len(DECADES),len(w)))
    future_support = np.ones(len(w),dtype=bool)
    early_support = future_support.copy()
    for mi,model in enumerate(MODELS):
        for si,ssp in enumerate(SSPS):
            if groups[0].any():
                path = UNION/model/ssp/f"{patch}.nc"
                audit = json.loads(path.with_suffix(".json").read_text())
                assert (audit["model"],audit["ssp"],audit["patch"]) == (model,ssp,patch)
                for tech in TECHS:
                    qa = audit["cache_checks"][tech]
                    assert qa["mask_agreement"] == 1
                    assert max(qa["max_abs_diff_by_year"][5:45]) <= .125 + 1e-6
                with netCDF4.Dataset(path) as ds:
                    ds.set_auto_mask(False)
                    assert (ds.model,ds.scenario,ds.patch) == (model,ssp,patch)
                    assert ds.wind_events.split(",")==list(EVENTS["wind"])
                    assert ds.solar_events.split(",")==list(EVENTS["solar"])
                    assert np.array_equal(lat,ds["lat"][:]) and np.array_equal(lon,ds["lon"][:])
                    assert np.array_equal(weights,ds["cell_area_km2"][:])
                    yy=list(ds["year"][:])
                    selected=ds["union_days"][[yy.index(y) for y in COVERAGE_YEARS]][:,groups[0]]
                valid = np.isfinite(selected)
                assert np.all(np.where(valid,(selected>=0)&(selected<=366),True))
                early_support[split[0]] &= valid[:10].all(axis=0)
                future_support[split[0]] &= valid[10:].all(axis=0)
                for di, decade in enumerate(DECADES):
                    offset = decade-COVERAGE_YEARS[0]
                    means[mi,si,di,split[0]]=selected[offset:offset+10].mean(axis=0,dtype=float)
            for tech,mask,selector in zip(TECHS,groups[1:],split[1:]):
                if not mask.any():
                    continue
                path=CACHE/model/"cache"/ssp/tech/f"{patch}.nc"
                with netCDF4.Dataset(path) as ds:
                    ds.set_auto_mask(False)
                    assert ds.fingerprint==fingerprint[model,ssp,tech]
                    assert (ds.model,ds.scenario,ds.tech,ds.patch)==(model,ssp,tech,patch)
                    assert ds["event"][0]=="any" and np.isclose(ds.min_time_coverage,.99)
                    assert np.array_equal(lat,ds["lat"][:]) and np.array_equal(lon,ds["lon"][:])
                    yy=list(ds["year"][:])
                    for di,decade in enumerate(DECADES):
                        block=ds["event_days"][[yy.index(y) for y in range(decade,decade+10)],0,:,:][:,mask]
                        valid=np.isfinite(block)
                        assert np.all(np.where(valid,(block>=0)&(block<=366),True))
                        if di==0:
                            early_support[selector] &= valid.all(axis=0)
                        else:
                            assert valid.all(), (patch,model,ssp,tech)
                        means[mi,si,di,selector]=block.mean(axis=0,dtype=float)
    kept = future_support & early_support
    assert future_support.sum()==expected_cells,(patch,future_support.sum(),expected_cells)
    np.testing.assert_allclose(w[future_support].sum(),expected_area,rtol=1e-12,atol=1e-8)
    reference_numerator=np.sum(means[:,:,1][:,:,future_support]*w[future_support],axis=-1)
    selected=means[:,:,:,kept].mean(axis=0).transpose(1,0,2)
    assert np.isfinite(selected).all()
    native_r,native_c=np.where(suitable)
    xx=np.floor(((lon[native_c[kept]]+180)%360)/RESOLUTION).astype(int)
    yy=np.floor((lat[native_r[kept]]+90)/RESOLUTION).astype(int).clip(0,NY-1)
    ids,inverse=np.unique(yy*NX+xx,return_inverse=True)
    denominator=np.bincount(inverse,weights=w[kept],minlength=len(ids))
    numerator=np.array([[np.bincount(inverse,weights=vals*w[kept],minlength=len(ids))
                         for vals in dec] for dec in selected])
    counts=[int(np.count_nonzero(kept & selector)) for selector in split]
    return ids,denominator,numerator,counts,reference_numerator


def main():
    cache_path=CACHE/"cache_manifest.json"
    cache=json.loads(cache_path.read_text())
    fingerprints={(r["patch"],r["model"],r["scenario"],r["tech"]):r["fingerprint"] for r in cache["records"]}
    coverage = pd.read_csv(REFERENCE/"grid_union_coverage.csv").set_index("patch")
    tasks=[]
    for patch,row in coverage.iterrows():
        fp={(m,s,t):fingerprints[patch,m,s,t] for m in MODELS for s in SSPS for t in TECHS}
        tasks.append((patch,fp,int(row.suitable_common_cells),float(row.suitable_common_area_km2)))
    numerator=np.zeros((len(DECADES),len(SSPS),NY*NX))
    den=np.zeros(NY*NX)
    counts=np.zeros(3,dtype=int)
    prior=np.zeros((len(MODELS),len(SSPS)))

    def merge(result):
        ids,weights,exposure,cells,reference=result
        numerator[:,:,ids] += exposure
        den[ids] += weights
        counts[:] += cells
        prior[:] += reference

    merge(reduce_patch(tasks[0]))
    print(f"Representative patch passed. Reducing {len(tasks)} joint and single-technology cache sets.",flush=True)
    with ProcessPoolExecutor(max_workers=min(6,int(os.environ.get("SLURM_CPUS_PER_TASK","1")))) as pool:
        for i,result in enumerate(pool.map(reduce_patch,tasks[1:]),2):
            merge(result)
            if i%10==0:
                print(f"{i}/{len(tasks)} patches complete.",flush=True)
    ref_file=REFERENCE/"grid_union_decadal.csv"
    ref=pd.read_csv(ref_file).query("scope == 'suitable_grid' and snapshot == 2050")
    published=ref.set_index(["model","climate_ssp"]).loc[
        pd.MultiIndex.from_product([MODELS,SSPS]),"numerator"].to_numpy().reshape(prior.shape)
    np.testing.assert_allclose(prior,published,rtol=1e-10,atol=1e-6)
    maps=np.divide(numerator,den,out=np.full(numerator.shape,np.nan),where=den>0)
    assert np.all(np.isfinite(maps).sum(axis=-1)==np.count_nonzero(den))
    global_means=numerator.sum(axis=-1)/den.sum()
    DATA.mkdir(parents=True,exist_ok=True)
    path=DATA/"rq1_exposure_union_maps.npz"
    np.savez_compressed(path,exposure_days=maps.reshape(len(DECADES),len(SSPS),NY,NX),
                        area_km2=den.reshape(NY,NX),decades=DECADES,ssps=SSPS,
                        lon_edges=np.arange(NX+1)*RESOLUTION-180,lat_edges=np.arange(NY+1)*RESOLUTION-90)
    records=[{"decade":decade,"climate_ssp":ssp,"common_native_cells":int(counts.sum()),
              "display_cells":int(np.count_nonzero(den)),"area_km2":float(den.sum()),
              "global_area_weighted_exposure_days":float(global_means[di,si])}
             for di,decade in enumerate(DECADES) for si,ssp in enumerate(SSPS)]
    pd.DataFrame(records).to_csv(DATA/"rq1_exposure_union_summary.csv",index=False)
    report={"status":"PASSED","scope":"wind and solar suitable-grid spatial union",
            "time_union":"Each dual-technology cell uses the aligned 3-hour wind or solar union; single-technology cells use their own union.",
            "support":"published 2030–2059 common suitable grid, also valid in 2020–2029 for all models and SSPs",
            "counts":dict(zip(("dual","wind_only","solar_only"),map(int,counts))),
            "area_weighting":"native cell area aggregated once within 0.5-degree display bins",
            "historical_and_future_windows":[[d,d+9] for d in DECADES],
            "published_2050s_numerator_reproduced":True,"published_reference_sha256":digest(ref_file),
            "single_technology_cache_manifest_sha256":digest(cache_path),
            "records":records,"map_sha256":digest(path),"job_id":os.environ.get("SLURM_JOB_ID"),"models":list(MODELS)}
    (DATA/"rq1_exposure_union_validation.json").write_text(json.dumps(report,indent=2)+"\n")
    print(pd.DataFrame(records).to_string(index=False),flush=True)


if __name__=="__main__":
    main()
