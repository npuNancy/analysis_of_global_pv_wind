"""Preserve the paired LCOE loss and capacity accounting definitions."""
from pathlib import Path
import numpy as np
import pandas as pd
from netCDF4 import Dataset
from utils.lcoe_station_climate.pipeline import sha as digest, require

def annual_loss(task,mapping):
    n=len(mapping["grid_id"])
    loss=np.full((30,n),np.nan); normal=np.full((30,n),np.nan)
    found=np.zeros((30,n),dtype=bool)
    maximum_closure=0.
    for record in task["loss"]:
        window=record["window"]
        selected=np.flatnonzero(mapping["tile"]==record["tile"])
        require(len(selected)>0,"Unexpected tile")
        path=Path(record["path"])
        # Verify only selected accepted files, once per scientific task.
        require(digest(path)==record["sha256"],f"Loss file hash {path}")
        with Dataset(path) as ds:
            for key,value in [("model",task["model"]),("climate_scenario",task["climate_ssp"]),("tech",task["tech"]),("patch",task["patch"])]:
                require(ds.getncattr(key)==value,f"Loss identity {key}")
            require(np.array_equal(ds["analysis_year"][:],np.arange(window,window+10)),"Loss year coverage")
            ids=np.asarray(ds["station_id"][:]).astype(str)
            require(len(np.unique(ids))==len(ids),"Duplicate tile IDs")
            where=pd.Index(ids).get_indexer(mapping["loss_station_id"][selected])
            require((where>=0).all(),"Station missing from tile")
            require(np.all(ds["capacity_mw"][:]==1),"Expected reference 1 MW")
            def values(name):
                require(ds[name].dimensions==("analysis_year","station"),name+" dimensions")
                return np.ma.asarray(ds[name][:],dtype=float).filled(np.nan)[:,where]
            l=values("net_generation_loss_per_mw_all")
            baseline=values("normal_all_generation_mwh_all")
            evnormal=values("normal_generation_mwh_all")
            evactual=values("actual_generation_mwh_all")
            error=np.abs(l-(evnormal-evactual))
            if np.isfinite(error).any():
                maximum_closure=max(maximum_closure,float(np.nanmax(error)))
                require(np.allclose(l,evnormal-evactual,rtol=1e-5,atol=2e-3,equal_nan=True),"Net event energy closure")
            rows=np.arange(window-2030,window-2030+10)
            require(not found[np.ix_(rows,selected)].any(),"Duplicate loss tile")
            loss[np.ix_(rows,selected)]=l
            normal[np.ix_(rows,selected)]=baseline
            found[np.ix_(rows,selected)]=True
    require(found.all(),"Incomplete mapped loss coverage")
    return loss,normal,maximum_closure

FIELDS=["net_loss_mwh","normal_annual_mwh","generation_mwh","capacity_mw",
        "mapped_capacity_mw","catalogue_capacity_mw","n_stations","n_mapped","n_catalogue"]

def weighted_annual(unit_values, capacity, common):
    require(unit_values.shape==capacity.shape,"Metric/capacity shape mismatch")
    active=capacity>0
    valid=active & common[None,:]
    require(np.isfinite(unit_values[valid]).all(),"Nonfinite supported metric")
    energy=np.where(valid,unit_values*capacity,np.nan)
    total=np.nansum(energy,axis=1,dtype=np.float64)
    denominator=np.where(valid,capacity,0).sum(axis=1,dtype=np.float64)
    return energy,total,denominator

def add_joint(frame):
    keys=["model","station_ssp","climate_ssp","snapshot","year"]
    require(not frame.duplicated(keys+["tech"]).any(),"Duplicate annual records")
    require(frame.groupby(keys).tech.nunique().eq(2).all(),"Incomplete technologies")
    combined=frame.groupby(keys,as_index=False)[FIELDS].sum(min_count=2)
    native=["calendar","expected_hours"]
    require(frame.groupby(keys)[native].nunique().eq(1).all().all(),"Technology calendars differ")
    metadata=frame.groupby(keys,as_index=False)[native].first()
    combined=combined.merge(metadata,on=keys,validate="one_to_one")
    combined["tech"]="wind+solar"
    return pd.concat([frame,combined],ignore_index=True)
