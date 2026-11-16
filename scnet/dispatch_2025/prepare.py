"""Prepare the accepted dispatch-2025 layouts for future climate extraction."""
import argparse
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from utils.data_access import read_cf_grid
from utils.gem_station_climate.prepare import source_grid
from utils.lcoe_station_climate import pipeline

ROOT = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage")


def prepare(root, config):
    cfg = pipeline.read(config)
    pipeline.require(str(root) == cfg["root"], "Campaign root mismatch")
    target = root / "future"
    pipeline.require(not (target / "runtime/state.json").exists(), "Extraction already submitted")
    for directory in ["inputs/stations", "catalogs", "mappings", "runtime/tasks", "jobs"]:
        (target / directory).mkdir(parents=True, exist_ok=True)
    logdir = Path(cfg["repo"]) / "logs/dispatch_2025/future"
    logdir.mkdir(parents=True, exist_ok=True)
    if not (target / "logs").exists():
        (target / "logs").symlink_to(logdir, target_is_directory=True)
    frames, provenance = [], []
    for scenario in cfg["station_ssps"]:
        manifest = pipeline.read(root / "inputs/stations" / scenario / "manifest.json")
        pipeline.require(manifest["accepted"] and manifest["scenario"] == scenario, "Unaccepted siting layout")
        check = manifest["case"]["checksums"]
        for year in cfg["snapshots"]:
            path = root / "inputs/stations" / scenario / f"stations_01deg_{year}.csv"
            suffix = f"/{scenario}/gem_2025/{path.name}"
            digest = next(v for k, v in check.items() if k.endswith(suffix))
            pipeline.require(pipeline.sha(path) == digest, "Siting input hash mismatch")
            f = pd.read_csv(path)
            pipeline.require(f.year.eq(year).all() and f.initialization_mode.eq("gem_2025").all(), "Siting metadata")
            pipeline.require(set(f.technology) == set(cfg["techs"]), "Missing technology")
            pipeline.require(not f.duplicated(["technology", "grid_id"]).any(), "Duplicate sites")
            pipeline.require(np.isfinite(f.capacity_mw).all() and f.capacity_mw.gt(0).all(), "Capacity invalid")
            row, col = f.grid_id.to_numpy() // 3600, f.grid_id.to_numpy() % 3600
            pipeline.require(np.allclose(f.latitude, 89.95 - row / 10, atol=1e-8)
                             and np.allclose(f.longitude, -179.95 + col / 10, atol=1e-8), "Grid identity mismatch")
            for tech in cfg["techs"]:
                units = set(f.loc[f.technology.eq(tech), "capacity_unit"])
                pipeline.require(units == ({"MWp"} if tech == "solar" else {"MW"}), "Capacity units")
                accepted = next(c["capacity_gw"] for c in manifest["case"]["native_capacity_validation"]["checks"]
                                if c["year"] == year and c["technology"] == tech)
                pipeline.require(np.isclose(f.loc[f.technology.eq(tech), "capacity_mw"].sum()/1000,
                                            accepted, rtol=1e-9, atol=1e-6), "Accepted capacity mismatch")
            f["scenario"] = scenario
            dest = target / "inputs/stations" / scenario / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.to_csv(dest, index=False)
            frames.append(f)
            provenance.append(dict(path=str(path), sha256=digest, manifest_sha256=pipeline.sha(root/"inputs/stations"/scenario/"manifest.json"),
                                   scenario=scenario, year=year, rows=len(f), capacity_mw=f.groupby("technology").capacity_mw.sum().to_dict()))
    cat = pd.concat(frames, ignore_index=True)
    refs = read_cf_grid.find_records(root=cfg["cf_root"], model=cfg["models"][0],
                                    climate_scenario=cfg["climate_ssps"][0], tech="wind", years=(2030,2030))
    pipeline.require(len(refs) == 47, "Expected 47 source patches")
    grid = source_grid(refs)
    mapping = cat.sort_values(["technology", "grid_id"]).drop_duplicates(["technology", "grid_id"])
    mapping = mapping[["technology","grid_id","latitude","longitude"]].rename(columns={"technology":"tech"})
    mapping = mapping.merge(grid, on="grid_id", how="left", validate="many_to_one")
    mapping["mapping_status"] = np.where(mapping.patch.notna(), "MATCHED", "NO_LAND_POINT_IN_CELL")
    a, b = np.deg2rad(mapping.latitude), np.deg2rad(mapping.source_lat)
    delta = np.deg2rad((mapping.source_lon - mapping.longitude + 180) % 360 - 180)
    mapping["distance_km"] = 6371*2*np.arcsin(np.sqrt(np.sin((b-a)/2)**2 + np.cos(a)*np.cos(b)*np.sin(delta/2)**2))
    mapping.to_csv(target/"inputs/loss_mapping.csv.gz", index=False)
    for product in cfg["products"]:
        index = Path(cfg[product+"_root"]) / "runtime/authoritative_index.json"
        shutil.copyfile(index, target/"inputs"/(product+"_index.json"))
    stage_cfg = {**cfg, "root":str(target), "phase":"future"}
    pipeline.write_json(root/"inputs/campaign.json", cfg)
    pipeline.write_json(root/"inputs/station_provenance.json", provenance)
    pipeline.write_json(target/"inputs/campaign.json", stage_cfg)
    pipeline.prepare(target, target/"inputs/campaign.json")
    pipeline.write_json(root/"runtime/prepared.json", dict(status="COMPLETED", stations=provenance,
        mapping_sha256=pipeline.sha(target/"inputs/loss_mapping.csv.gz"), code_sha256=pipeline.sha(__file__)))
    print(pd.read_csv(target/"catalogs/coverage.csv").to_string(index=False), flush=True)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--config", type=Path, default=Path(__file__).with_name("campaign.json"))
    a = p.parse_args()
    prepare(a.root, a.config)


if __name__ == "__main__":
    main()
