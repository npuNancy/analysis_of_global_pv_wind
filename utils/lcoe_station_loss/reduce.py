"""Reduce annual shards on fixed four-model support and publish nine pairs."""
import json,os,itertools
from pathlib import Path
import numpy as np
import pandas as pd
from .pipeline import read,sha,require,write_json,signature,save_npz,YEARS,WINDOWS
from .science import weighted_annual,add_joint
digest=sha

def validate_release(output,cfg,entries,annual):
    keys=['model','station_ssp','climate_ssp','tech']
    expected=set(itertools.product(cfg['models'],cfg['station_ssps'],cfg['climate_ssps'],cfg['techs']))
    require({tuple(e[k] for k in keys) for e in entries}==expected and len(entries)==len(expected),'Published matrix')
    errors=[];total_bytes=0
    for e in entries:
        p=Path(e['path']);require(sha(p)==e['sha256'],'Archive changed')
        require(p.stat().st_mode & 0o004,'Missing public file read')
        for parent in p.parents:require(parent.stat().st_mode & 0o001,'Missing public traversal')
        e['size_bytes']=p.stat().st_size;total_bytes+=e['size_bytes']
        rows=annual
        for key in keys:rows=rows[rows[key]==e[key]]
        rows=rows.sort_values('year');require(len(rows)==30,'Annual summary coverage')
        with np.load(p,allow_pickle=False) as z:
            require(np.array_equal(z['years'],YEARS),'Archive years')
            require(len(z['grid_id'])==e['grid_count'] and len(np.unique(z['grid_id']))==e['grid_count'],'Archive grids')
            cap=z['capacity_mw'];support=z['common_support'];active=(cap>0)&support[None,:]
            require(cap.shape==(30,e['grid_count']) and np.isfinite(cap).all() and (cap>=0).all(),'Archive capacity')
            require((np.diff(cap,axis=0)>=-1e-7).all(),'Noncumulative capacity')
            denominator=np.where(active,cap,0).sum(axis=1)
            require(np.allclose(denominator,rows.capacity_mw,rtol=1e-12,atol=1e-5),'Capacity summary')
            for name in ['net_loss_mwh','normal_annual_mwh','generation_mwh']:
                values=z[name];require(values.shape==cap.shape,'Energy shape')
                require(np.isfinite(values[active]).all() and np.isnan(values[~active]).all(),'Energy missing semantics')
                total=np.nansum(values,axis=1);reference=rows[name].to_numpy()
                require(np.allclose(total,reference,rtol=1e-12,atol=1e-5),'Archive summary '+name)
                errors.append(float(np.max(np.abs(total-reference))))
    task_state=read(output/'runtime/state.json')
    require(all(v['state']=='SUCCEEDED' and v['exit_code']=='0:0' for v in task_state.values()),'Scheduler completion')
    for e in entries:e['reused_paired']=e.get('reused_paired',False)
    write_json(output/'runtime/authoritative_index.json',dict(status='COMPLETED',schema='lcoe-station-loss-v1',files=entries,
        years=YEARS.tolist(),capacity_snapshots=list(WINDOWS),event='all',wind_energy_scale=1,
        support_scope='station_ssp x climate_ssp x tech; fixed four-model, 30-year support'))
    write_json(output/'runtime/completion.json',dict(status='COMPLETED',files=len(entries),reused_paired_files=sum(e['reused_paired'] for e in entries),
        new_files=sum(not e['reused_paired'] for e in entries),units=len(task_state),annual_records=len(annual),total_bytes=total_bytes,
        index_sha256=sha(output/'runtime/authoritative_index.json'),maximum_summary_error_mwh=max(errors),
        matrix='PASSED',archive_values='PASSED',shared_permissions='PASSED',job_id=os.environ.get('SLURM_JOB_ID')))

def summarize(output):
    cfg=read(output/"inputs/campaign.json"); MODELS=cfg["models"]
    paired=Path(cfg["paired_root"])
    pairs=[(s,c) for s in cfg["station_ssps"] for c in cfg["climate_ssps"] if c!=cfg["paired"][s]]
    prepared=json.loads((output/"runtime/prepared.json").read_text())
    require(prepared["status"]=="COMPLETED","Preparation incomplete")
    catalog=pd.read_csv(paired/"catalogue.csv.gz")
    require(digest(paired/"catalogue.csv.gz")==prepared["catalogue_sha256"],"Changed catalogue")
    tasks=json.loads((output/"runtime/tasks.json").read_text())
    require(digest(output/"runtime/tasks.json")==prepared["task_manifest_sha256"],"Changed task manifest")
    rows,coverage,sources,station_outputs=[],[],[],[]
    source_dir=output/"source_data"; source_dir.mkdir(parents=True,exist_ok=True)
    for scenario,climate in pairs:
        for tech in ["wind","solar"]:
            sites=catalog[(catalog.station_ssp==scenario)&(catalog.tech==tech)]
            cells=sites.drop_duplicates("grid_id").sort_values("grid_id")
            all_ids=cells.grid_id.to_numpy()
            cap=sites.pivot(index="grid_id",columns="snapshot",values="capacity_mw").reindex(index=all_ids,columns=WINDOWS).fillna(0).to_numpy().T
            cap=np.repeat(cap,10,axis=0)
            require(np.isfinite(cap).all() and (cap>=0).all(),"Bad capacities")
            catalog_counts=(cap>0).sum(axis=1); catalog_capacity=cap.sum(axis=1)
            mapped_mask=cells.mapping_status.eq("MATCHED").to_numpy()
            metric={model:{name:np.full((30,len(all_ids)),np.nan) for name in
                ["net_loss_per_mw","normal_generation_per_mw","generation_per_mw"]} for model in MODELS}
            common=np.ones(len(all_ids),dtype=bool)&mapped_mask
            counts={}; calendars={}; seen={model:set() for model in MODELS}
            relevant=[t for t in tasks if t["station_ssp"]==scenario and t["climate_ssp"]==climate and t["tech"]==tech and not t["paired_control"]]
            for t in relevant:
                dest=output/"shards"/t["unit"]
                meta=json.loads((dest/"complete.json").read_text())
                require(meta["status"]=="COMPLETED","Incomplete unit")
                require(meta["identity"]["task_sha256"]==digest(t["path"]) and meta["identity"]["code"]==signature(),"Stale unit")
                require(meta["metrics_sha256"]==digest(dest/"metrics.npz"),"Changed scientific cache")
                with np.load(dest/"metrics.npz",allow_pickle=False) as z:
                    ids=z["grid_id"]; ix=pd.Index(all_ids).get_indexer(ids)
                    require((ix>=0).all() and not seen[t["model"]].intersection(ids),"Duplicate/unknown unit grids")
                    seen[t["model"]].update(ids)
                    require(np.array_equal(z["years"],YEARS),"Year mismatch")
                    require(np.allclose(np.repeat(z["capacity_mw"],10,axis=0),cap[:,ix],rtol=1e-12),"Capacity changed")
                    common[ix] &= z["valid"].all(axis=0)
                    for name in metric[t["model"]]:
                        metric[t["model"]][name][:,ix]=z[name]
                    if t["model"] in counts:
                        require(np.array_equal(counts[t["model"]],z["expected_count"]),"Inconsistent calendar")
                    counts[t["model"]]=z["expected_count"]
                calendars[t["model"]]=meta["calendar"]
                sources.append(dict(path=str(dest/"complete.json"),sha256=digest(dest/"complete.json")))
            for model in MODELS:
                require(seen[model]==set(all_ids[mapped_mask]),"Incomplete mapped coverage")
            support=cells[["grid_id","latitude","longitude","mapping_status","distance_km","mapping_alternatives",
                           "patch","loss_station_id","source_lat","source_lon"]].copy()
            support["common_valid"]=common
            support["exclusion_reason"]=np.where(common,"",np.where(mapped_mask,"INCOMPLETE_CF_OR_LOSS_BASELINE","NO_SUITABLE_CF_CELL"))
            support.to_csv(source_dir/f"support_{scenario}_{climate}_{tech}.csv.gz",index=False)
            for model in MODELS:
                arrays={}
                for source_name,target_name in [
                    ("net_loss_per_mw","net_loss_mwh"),
                    ("normal_generation_per_mw","normal_annual_mwh"),
                    ("generation_per_mw","generation_mwh")]:
                    energy,total,denominator=weighted_annual(metric[model][source_name],cap,common)
                    arrays[target_name]=energy
                    arrays[target_name+"_total"]=total
                require(np.all(denominator>0),"No valid global capacity")
                expected_hours=counts[model]*3
                require(np.all(arrays["generation_mwh_total"]>=-1e-6) and
                        np.all(arrays["generation_mwh_total"]<=denominator*expected_hours+1e-4),"CF energy bounds")
                filename=output/"station_results"/scenario/climate/model/f"{tech}.npz"
                save_npz(filename,grid_id=all_ids,years=YEARS,latitude=cells.latitude.to_numpy(),
                    longitude=cells.longitude.to_numpy(),source_latitude=cells.source_lat.to_numpy(),
                    source_longitude=cells.source_lon.to_numpy(),capacity_mw=cap,common_support=common,
                    mapped=mapped_mask,expected_hours=expected_hours,
                    **{k:v for k,v in arrays.items() if not k.endswith("_total")})
                station_outputs.append(dict(path=str(filename),sha256=digest(filename),model=model,
                    station_ssp=scenario,climate_ssp=climate,tech=tech,calendar=calendars[model],grid_count=len(all_ids)))
                for yi,year in enumerate(YEARS):
                    record=dict(model=model,station_ssp=scenario,climate_ssp=climate,tech=tech,
                        snapshot=int(year)//10*10,year=int(year),calendar=calendars[model],expected_hours=int(expected_hours[yi]),
                        capacity_mw=float(denominator[yi]),catalogue_capacity_mw=float(catalog_capacity[yi]),
                        mapped_capacity_mw=float(cap[yi,mapped_mask].sum()),n_catalogue=int(catalog_counts[yi]),
                        n_mapped=int((cap[yi,mapped_mask]>0).sum()),n_stations=int(((cap[yi]>0)&common).sum()),
                        net_loss_mwh=float(arrays["net_loss_mwh_total"][yi]),
                        normal_annual_mwh=float(arrays["normal_annual_mwh_total"][yi]),
                        generation_mwh=float(arrays["generation_mwh_total"][yi]))
                    rows.append(record)
            for yi,year in enumerate(YEARS):
                if int(year) not in WINDOWS: continue
                coverage.append(dict(station_ssp=scenario,climate_ssp=climate,tech=tech,snapshot=int(year),
                    catalogue_capacity_mw=float(catalog_capacity[yi]),mapped_capacity_mw=float(cap[yi,mapped_mask].sum()),
                    valid_capacity_mw=float(cap[yi,common].sum()),n_catalogue=int(catalog_counts[yi]),
                    n_valid=int(((cap[yi]>0)&common).sum())))
    annual=pd.DataFrame(rows)
    require(len(annual)==len(MODELS)*len(pairs)*2*30,"Incomplete cross results")
    old=read(paired/'station_results/manifest.json')
    for entry in old['files']:
        path=paired/'station_results'/entry['station_ssp']/entry['model']/(entry['tech']+'.npz')
        require(sha(path)==entry['sha256'],'Changed paired archive')
        station_outputs.append(dict(entry,path=str(path),reused_paired=True))
    old_annual=pd.read_csv(paired/'source_data/global_annual_models.csv')
    annual=pd.concat([annual,old_annual[old_annual.tech.isin(['wind','solar'])]],ignore_index=True)
    coverage.extend(pd.read_csv(paired/'source_data/capacity_coverage.csv').to_dict('records'))
    require(len(annual)==len(MODELS)*len(cfg['station_ssps'])*len(cfg['climate_ssps'])*2*30,'Incomplete nine-pair matrix')
    annual=add_joint(annual)
    require(annual.groupby(["station_ssp","climate_ssp","tech","year"]).model.nunique().eq(4).all(),"Model coverage")
    require(annual.groupby(["station_ssp","climate_ssp","tech","year"]).capacity_mw.nunique().eq(1).all(),"Changing common capacity")
    for name,values in {
        "unit_loss_mwh_per_mw":annual.net_loss_mwh/annual.capacity_mw,
        "loss_fraction_pct":100*annual.net_loss_mwh/annual.normal_annual_mwh,
        "generation_pwh":annual.generation_mwh/1e9,
        "unit_generation_mwh_per_mw":annual.generation_mwh/annual.capacity_mw,
        "capacity_coverage_pct":100*annual.capacity_mw/annual.catalogue_capacity_mw}.items():
        require(np.isfinite(values).all(),name+" nonfinite")
        annual[name]=values
    require(annual.capacity_coverage_pct.between(0,100+1e-8).all(),"Coverage range")
    annual["support"]="four models and all 30 years; complete native-year CF; finite loss and positive annual baseline"
    annual["event"]="all"; annual["wind_energy_scale"]=1
    annual.to_csv(source_dir/"global_annual_models.csv",index=False)
    metrics=["net_loss_mwh","unit_loss_mwh_per_mw","loss_fraction_pct","generation_pwh","unit_generation_mwh_per_mw"]
    display=annual.groupby(["station_ssp","climate_ssp","tech","year"])[metrics].agg(["mean","min","max","count"])
    display.columns=["_".join(c) for c in display.columns]
    display.reset_index().to_csv(source_dir/"global_annual_ensemble.csv",index=False)
    decade=annual.groupby(["model","station_ssp","climate_ssp","tech","snapshot"],as_index=False)[metrics+["capacity_mw","capacity_coverage_pct"]].mean()
    decade.to_csv(source_dir/"global_decadal_models.csv",index=False)
    decade.groupby(["station_ssp","climate_ssp","tech","snapshot"],as_index=False)[metrics+["capacity_mw","capacity_coverage_pct"]].mean().to_csv(source_dir/"global_decadal_ensemble.csv",index=False)
    pd.DataFrame(coverage).to_csv(source_dir/"capacity_coverage.csv",index=False)
    write_json(output/"station_results"/"manifest.json",dict(status="COMPLETED",files=station_outputs,
        dimensions="All energy/capacity arrays: (30 analysis years, grid). grid_id indexes the original unique 0.1-degree raster cell.",
        units={"capacity_mw":"MW","net_loss_mwh":"MWh/year","normal_annual_mwh":"MWh/year","generation_mwh":"MWh/year"},
        missing="Excluded common support and inactive station-years have NaN energy; capacity retains full catalogue, including excluded stations.",
        negative_loss="Negative net loss is retained; it denotes an event-associated gain.",
        provenance=str(output/"inputs/provenance.json")))
    write_json(output/"summary_complete.json",dict(status="COMPLETED",annual_records=len(annual),station_files=len(station_outputs),
        units_checked=len(sources),sources=sources,minimum_capacity_coverage_pct=float(annual.capacity_coverage_pct.min()),
        minimum_combined_capacity_coverage_pct=float(annual[annual.tech.eq("wind+solar")].capacity_coverage_pct.min()),
        checks=["four-model fixed support","complete native CF calendar","capacity conservation","CF energy bounds",
                "technology sum before ratios","all model/scenario/year combinations","signed loss","hash-linked per-station arrays"],
        job_id=os.environ.get("SLURM_JOB_ID")))
    validate_release(output,cfg,station_outputs,annual)
    print("Summary complete",len(annual),"annual rows",len(station_outputs),"station files",flush=True)

