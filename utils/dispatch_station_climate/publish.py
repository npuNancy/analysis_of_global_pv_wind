"""Publish the dispatch-2025 future matrix and auditable annual summaries."""
import argparse
import itertools
import os
import stat
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pandas as pd

from utils.gem_station_climate import publish as common
from .loss import task_identity
from utils.lcoe_station_climate.pipeline import read, write_json, sha, require, fingerprint

ROOT = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage")


def prepare(root):
    cfg = read(root/"inputs/campaign.json")
    source = root/"loss_future"
    states = read(source/"runtime/state.json")
    require(all(s["state"]=="SUCCEEDED" for s in states.values()), "Loss phase not accepted")
    target = root/"publish"
    for folder in ["inputs","runtime/tasks","jobs","outputs"]:
        (target/folder).mkdir(parents=True,exist_ok=True)
    logs = Path(cfg["repo"])/"logs/dispatch_2025/publish"
    logs.mkdir(parents=True,exist_ok=True)
    if not (target/"logs").exists():
        (target/"logs").symlink_to(logs,target_is_directory=True)
    write_json(target/"inputs/campaign.json",{**cfg,"root":str(target),"phase":"publish","cpus":4})
    inputs = []
    for entry in read(source/"runtime/tasks.json"):
        task = read(entry["path"]);done = read(entry["marker"])
        require(done["status"]=="COMPLETED","Missing loss receipt")
        task["annual"] = next(o for o in done["outputs"] if o["product"]=="annual_union")
        task["calendar"] = done["calendar"]
        inputs.append(task)
    tasks=[]
    for scenario,climate,tech in itertools.product(cfg["station_ssps"],cfg["climate_ssps"],cfg["techs"]):
        unit="_".join(["future",scenario,climate,tech])
        selected=[t for t in inputs if t["station_ssp"]==scenario and t["climate_ssp"]==climate and t["tech"]==tech]
        require({t["model"] for t in selected}==set(cfg["models"]),"Incomplete model group")
        task=dict(unit=unit,phase="future",station_ssp=scenario,climate_ssp=climate,tech=tech,
                  source_root=str(root),inputs=selected,models=cfg["models"],years=list(range(cfg["years"][0],cfg["years"][1]+1)))
        path=target/"runtime/tasks"/(unit+".json");write_json(path,task)
        tasks.append(dict(unit=unit,path=str(path),product="publish",model="ensemble",climate_ssp=climate,
                          tech=tech,patch="future",n_union=len(selected),marker=str(target/"runtime/units"/unit/"complete.json")))
    write_json(target/"runtime/tasks.json",tasks)
    write_json(target/"runtime/prepared.json",dict(status="COMPLETED",units=len(tasks)))
    print("Prepared",len(tasks),"publication groups",flush=True)


def accepted_tasks(root,stage):
    base=root/stage
    tasks=read(base/"runtime/tasks.json")
    states=read(base/"runtime/state.json")
    require(set(states)=={t["unit"] for t in tasks},"Task state matrix mismatch")
    require(all(v["state"]=="SUCCEEDED" and v["scheduler_state"]=="COMPLETED" and v["exit_code"]=="0:0"
                for v in states.values()),stage+" is not completely accepted")
    for item in tasks:
        task=read(item["path"]);done=read(item["marker"])
        require(done["status"]=="COMPLETED" and done["task_sha256"]==sha(item["path"]),"Task receipt mismatch")
        require(str(done["job_id"])==states[item["unit"]]["job_id"],"Receipt scheduler job mismatch")
        for artifact in done["outputs"]:
            path=Path(artifact["path"])
            require(path.is_file() and path.stat().st_size==artifact["size_bytes"],"Published file missing/changed")
        yield item,task,done


EVENT_UNITS = {
    "generation_loss_mwh": "MWh", "net_generation_loss_mwh": "MWh",
    "relative_generation_loss_pct": "%", "relative_generation_loss_pct_sum": "%",
    "relative_generation_loss_count": "samples", "event_duration_hours": "hours",
    "loss_hours": "hours", "generation_loss_intensity": "1",
    "normalized_generation_loss": "1", "generation_fluctuation_mwh": "MWh",
    "generation_fluctuation_rate": "1", "net_generation_loss_per_mw": "MWh MW-1",
    "normal_generation_mwh": "MWh", "normal_all_generation_mwh": "MWh",
    "actual_generation_mwh": "MWh",
}


def validate_native_loss(artifact, task, done, catalogue, cfg):
    expected=catalogue[catalogue.mapping_status.eq("MATCHED") & catalogue.patch.eq(task["patch"])]
    require(artifact["station_count"]==len(expected),"Loss receipt station count")
    years=np.arange(cfg["years"][0],cfg["years"][1]+1)
    windows=[[year,year+9] for year in cfg["snapshots"]]
    require(np.array_equal(task["years"],years) and task["windows"]==windows,"Loss task time coverage")
    with nc.Dataset(artifact["path"]) as ds:
        grid=np.asarray(ds["grid_id"][:])
        require(len(ds.dimensions["station"])==len(expected),"Native loss station count")
        require(np.array_equal(np.sort(grid),np.sort(expected.grid_id.to_numpy())),
                "Loss station identifiers differ from catalogue")
        ids=np.array([f"{cfg['station_prefix']}:{task['station_ssp']}:{task['tech']}:{g}" for g in grid],dtype=object)
        require(np.array_equal(ds["station_id"][:],ids),"Native loss station IDs")
        require(np.array_equal(ds["year"][:],years),"Annual loss years")
        require(ds.identity==done["identity"] and ds.calendar==done["calendar"],"Native loss identity/calendar")
        for attr,key in [("model","model"),("climate_scenario","climate_ssp"),
                         ("station_scenario","station_ssp"),("tech","tech"),("source_patch","patch")]:
            require(getattr(ds,attr)==task[key],"Native loss scenario metadata")
        require(ds.wind_energy_scale==1 and ds.time_step_hours==3,"Native loss scale/cadence")
        require(ds["capacity_mw"].capacity_basis==cfg["capacity_basis"][task["tech"]],"Capacity basis mismatch")
        suffixes=[name.removeprefix("signal_") for name in task["extreme"][0]["variables"]]+["all"]
        fields={name+"_"+suffix:units for name,units in EVENT_UNITS.items() for suffix in suffixes}
        fields.update(all_generation_mwh="MWh",annual_cf="1",cf_valid_count="samples",
                      signal_valid_count="samples",loss_valid_count="samples",capacity_mw="MW")
        for name,units in fields.items():
            require(name in ds.variables,"Missing native loss variable: "+name)
            require(ds[name].dimensions==("year","station") and ds[name].units==units,
                    "Native loss dimensions/units: "+name)
        for name,units in [("cf_normal","1"),("baseline_count","samples")]:
            require(ds[name].dimensions==("window","month_hour_idx","station") and
                    ds[name].shape==(len(windows),96,len(expected)) and ds[name].units==units,
                    "Native baseline dimensions/units: "+name)
        require(np.array_equal(ds["baseline_start_year"][:],[w[0] for w in windows]) and
                np.array_equal(ds["baseline_end_year"][:],[w[1] for w in windows]),"Native baseline windows")


def validate_annual_archive(artifact, catalogue, cfg):
    cat=catalogue.sort_values("grid_id")
    years=np.arange(cfg["years"][0],cfg["years"][1]+1)
    require(artifact["station_count"]==len(cat),"Annual archive station count")
    require(artifact["years"]==cfg["years"],"Annual archive year metadata")
    with np.load(artifact["path"],allow_pickle=False) as z:
        require(np.array_equal(z["years"],years),"Annual archive years")
        require(np.array_equal(z["grid_id"],cat.grid_id.to_numpy()),"Annual archive station catalogue")
        expected=np.asarray([cat[f"capacity_mw_{max(s for s in cfg['snapshots'] if s<=year)}"].to_numpy()
                             for year in years])
        np.testing.assert_allclose(z["capacity_mw"],expected,rtol=1e-12,atol=1e-7)
        require(np.array_equal(z["mapped"],cat.mapping_status.eq("MATCHED").to_numpy()),"Annual archive mapping")
        support=z["common_support"]
        require(support.shape==(len(cat),) and not (support & ~z["mapped"]).any(),"Annual archive support")
        required=set(common.ENERGY)|{"cf_mean","event_hours","loss_event_hours","loss_hours",
                                     "cf_valid_count","signal_valid_count","loss_valid_count"}
        require(required<=set(z.files),"Annual archive fields")


def finalize(root):
    cfg=read(root/"inputs/campaign.json")
    grouped={};native_loss=[];catalogues={}
    for scenario,tech in itertools.product(cfg["station_ssps"],cfg["techs"]):
        path=root/"future/catalogs"/f"{scenario}_{tech}.csv.gz"
        frame=pd.read_csv(path)
        catalogues[scenario,tech]=frame
        require(not frame.grid_id.duplicated().any(),"Duplicate station catalogue")
    extraction_sha=sha(Path(__file__).parents[1]/"lcoe_station_climate/pipeline.py")
    for entry,task,done in accepted_tasks(root,"future"):
        require(done["code_sha256"]==extraction_sha,"Extraction code mismatch")
        require(done["identity"]==fingerprint(dict(task_sha256=sha(entry["path"]),code_sha256=extraction_sha)),
                "Extraction fingerprint mismatch")
        for artifact in done["outputs"]:
            require(artifact["source_comparison"]=="PASSED","Extraction comparison missing")
            key=tuple(artifact[k] for k in ["product","model","climate_scenario","station_scenario","tech","patch"])
            grouped.setdefault(key,[]).append(artifact)
    patches=sorted({r["patch"] for r in read(root/"future/inputs/cf_index.json")["entries"]})
    entries=[]
    for key in itertools.product(cfg["products"],cfg["models"],cfg["climate_ssps"],cfg["station_ssps"],cfg["techs"],patches):
        product,model,climate,scenario,tech,patch=key
        artifacts=sorted(grouped.get(key,[]),key=lambda a:a["years"])
        cat=catalogues[scenario,tech]
        expected=cat[cat.mapping_status.eq("MATCHED") & cat.patch.eq(patch)]
        require(bool(artifacts)==bool(len(expected)),"Missing populated station product")
        if artifacts:
            require(artifacts[0]["years"][0]==cfg["years"][0] and artifacts[-1]["years"][1]==cfg["years"][1],
                    "Native product year coverage")
            require(all(a["years"][1]+1==b["years"][0] for a,b in zip(artifacts,artifacts[1:])),"Native year gaps")
            for artifact in artifacts:
                require(artifact["station_count"]==len(expected),"Native station count mismatch")
                require(cfg["years"][0]<=artifact["years"][0]<=artifact["years"][1]<=cfg["years"][1],"Unexpected years")
        entries.append(dict(phase="future",**dict(zip(["product","model","climate_scenario","station_scenario","tech","patch"],key)),
                            status="COMPLETED" if artifacts else "EMPTY_NO_STATIONS",artifacts=artifacts))
    expected_loss={(model,climate,scenario,tech,patch) for model,climate,scenario,tech,patch
        in itertools.product(cfg["models"],cfg["climate_ssps"],cfg["station_ssps"],cfg["techs"],patches)
        if ((catalogues[scenario,tech].mapping_status=="MATCHED") & (catalogues[scenario,tech].patch==patch)).any()}
    seen_loss=set()
    for entry,task,done in accepted_tasks(root,"loss_future"):
        require(done["identity"]==task_identity(Path(entry["path"]),root/"inputs/reference_code"),"Loss code/reference fingerprint mismatch")
        key=tuple(task[k] for k in ["model","climate_ssp","station_ssp","tech","patch"])
        require(key not in seen_loss,"Duplicate loss unit");seen_loss.add(key)
        artifact=next(a for a in done["outputs"] if a["product"]=="loss")
        validate_native_loss(artifact,task,done,catalogues[task["station_ssp"],task["tech"]],cfg)
        native_loss.append(dict(**{k:task[k] for k in ["model","climate_ssp","station_ssp","tech","patch"]},
                                **artifact,receipt=dict(path=entry["marker"],sha256=sha(entry["marker"])),calendar=done["calendar"]))
    require(seen_loss==expected_loss,"Incomplete annual loss matrix")
    archives=[];frames=[]
    for entry,task,done in accepted_tasks(root,"publish"):
        require(done["code_sha256"]==sha(common.__file__),"Annual publication code mismatch")
        archives.extend(done["outputs"])
        require(sha(done["summary"]["path"])==done["summary"]["sha256"],"Summary hash mismatch")
        frames.append(pd.read_csv(done["summary"]["path"]))
    archive_keys=[tuple(a[k] for k in ["model","climate_ssp","station_ssp","tech"]) for a in archives]
    expected_archives=set(itertools.product(cfg["models"],cfg["climate_ssps"],cfg["station_ssps"],cfg["techs"]))
    require(len(archive_keys)==len(set(archive_keys)) and set(archive_keys)==expected_archives,
            "Annual archive matrix mismatch")
    for artifact in archives:
        validate_annual_archive(artifact,catalogues[artifact["station_ssp"],artifact["tech"]],cfg)
    frame=pd.concat(frames,ignore_index=True)
    keys=["phase","model","station_ssp","climate_ssp","year"]
    numeric=list(common.ENERGY)+["capacity_mw","catalogue_capacity_mw","mapped_capacity_mw","n_catalogue","n_mapped","n_stations","exposure_mw_days"]
    require(frame.groupby(keys).tech.nunique().eq(2).all(),"Incomplete technologies")
    joint=frame.groupby(keys,as_index=False)[numeric].sum(min_count=2)
    joint=joint.merge(frame.groupby(keys,as_index=False)[["calendar","expected_hours"]].first(),on=keys,validate="one_to_one")
    joint["tech"]="wind+solar"
    frame=pd.concat([frame,joint],ignore_index=True)
    frame["unit_loss_mwh_per_mw"]=frame.net_loss_mwh/frame.capacity_mw
    frame["loss_fraction_pct"]=100*frame.net_loss_mwh/frame.normal_annual_mwh
    frame["unit_generation_mwh_per_mw"]=frame.generation_mwh/frame.capacity_mw
    frame["cf_mean"]=frame.generation_mwh/frame.capacity_mw/frame.expected_hours
    frame["exposure_days"]=frame.exposure_mw_days/frame.capacity_mw
    frame["capacity_coverage"]=frame.capacity_mw/frame.catalogue_capacity_mw
    keycols=["model","climate_ssp","station_ssp","tech","year"]
    expected=set(itertools.product(cfg["models"],cfg["climate_ssps"],cfg["station_ssps"],["wind","solar","wind+solar"],range(cfg["years"][0],cfg["years"][1]+1)))
    require(not frame.duplicated(keycols).any() and set(frame[keycols].itertuples(index=False,name=None))==expected,"Annual global matrix mismatch")
    require(np.isfinite(frame[numeric+["cf_mean","unit_loss_mwh_per_mw"]].to_numpy()).all(),"Nonfinite global metrics")
    np.testing.assert_allclose(frame.net_loss_mwh,frame.event_normal_mwh-frame.event_actual_mwh,rtol=2e-6,atol=.2)
    require(frame.capacity_coverage.between(0,1.000001).all() and frame.cf_mean.between(0,1).all(),"Global bounds")
    data=root/"source_data";data.mkdir(exist_ok=True)
    frame.sort_values(keys+["tech"]).to_csv(data/"global_annual_models.csv",index=False)
    metrics=numeric+["unit_loss_mwh_per_mw","loss_fraction_pct","unit_generation_mwh_per_mw","cf_mean","exposure_days","capacity_coverage"]
    grouping=["phase","station_ssp","climate_ssp","tech","year"]
    ensemble=frame.groupby(grouping)[metrics].agg(["mean","min","max"])
    ensemble.columns=["_".join(c) for c in ensemble.columns]
    ensemble=ensemble.reset_index()
    ensemble["n_models"]=frame.groupby(grouping).size().to_numpy()
    require(ensemble.n_models.eq(len(cfg["models"])).all(),"Incomplete ensemble")
    ensemble.to_csv(data/"global_annual_ensemble.csv",index=False)
    frame[grouping+["model","n_catalogue","n_mapped","n_stations","catalogue_capacity_mw","mapped_capacity_mw","capacity_mw","capacity_coverage"]].to_csv(data/"capacity_coverage.csv",index=False)
    coverage=pd.read_csv(root/"future/catalogs/coverage.csv")
    coverage.to_csv(data/"catalogue_capacity.csv",index=False)
    schema=root/"station_results/manifest.json"
    write_json(schema,dict(status="COMPLETED",schema="dispatch2025-annual-v1",
        annual_summary_fields={**{k:"MWh" for k in common.ENERGY},"capacity_mw":"MWp/DC solar; MW wind","cf_mean":"1",
            "event_hours":"hours","years":"calendar year","common_support":"valid over all years and four models within this climate/station/tech path"},
        native_loss_fields="Same event-specific and all-union variables as generation_loss.metrics.calculate_all_metrics; units on variables",
        native_loss_dimensions=["year","station"],normal_cf_dimensions=["window","month_hour_idx","station"],
        capacity_timing="2030,2040,2050 total capacity snapshots applied to the corresponding decade",
        generation_semantics="Climate-driven full-year CF integral; wind scale 1",
        years=cfg["years"],windows=[[s,s+9] for s in cfg["snapshots"]],
        missingness="Native loss files retain mapped sites and NaNs. Published summary archives use complete CF, at least 99% event timesteps, finite loss and positive annual normal generation over all years/models.",
        events="Wind five labels, solar six labels, and their time union all. Shared baseline excludes all selected events."))
    access=dict(files_checked=0,directories_checked=0)
    for path in itertools.chain([root,*root.parents],root.rglob("*")):
        mode=path.stat().st_mode
        if stat.S_ISDIR(mode):
            require(mode & 0o001,"Shared directory cannot be traversed: "+str(path))
            access["directories_checked"]+=1
        elif stat.S_ISREG(mode):
            require(mode & 0o004,"Shared file cannot be read: "+str(path))
            access["files_checked"]+=1
    index=root/"runtime/authoritative_index.json"
    artifacts=[a for e in entries for a in e["artifacts"]]+archives+native_loss
    write_json(index,dict(status="COMPLETED",schema="dispatch2025-climate-v1",name=cfg["name"],
        years=cfg["years"],models=cfg["models"],climate_ssps=cfg["climate_ssps"],station_ssps=cfg["station_ssps"],
        entries=entries,annual_archives=archives,loss_files=native_loss,native_files=sum(len(e["artifacts"]) for e in entries),
        total_bytes=sum(a["size_bytes"] for a in artifacts),annual_schema=dict(path=str(schema),sha256=sha(schema)),
        provenance={p.name:dict(path=str(p),sha256=sha(p)) for p in (root/"inputs").glob("*.json")},
        summaries={p.name:dict(path=str(p),sha256=sha(p),size_bytes=p.stat().st_size) for p in data.glob("*.csv")}))
    write_json(root/"runtime/completion.json",dict(status="COMPLETED",index_sha256=sha(index),shared_access=access,
        annual_archives=len(archives),annual_model_rows=len(frame),ensemble_rows=len(ensemble),native_loss_files=len(native_loss),
        windows=[[s,s+9] for s in cfg["snapshots"]],job_id=os.environ.get("SLURM_JOB_ID"),
        capacity_coverage_min=float(frame.capacity_coverage.min()),capacity_coverage_max=float(frame.capacity_coverage.max())))
    print("COMPLETED",len(archives),"annual archives",len(native_loss),"event loss files",len(frame),"model rows",flush=True)


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--stage",choices=["prepare","run","finalize"],default="prepare")
    p.add_argument("--unit")
    a=p.parse_args()
    if a.stage=="prepare":prepare(a.root)
    elif a.stage=="finalize":finalize(a.root)
    else:
        require(bool(a.unit),"--unit required")
        common.run(a.root,a.unit)


if __name__=="__main__":
    main()
