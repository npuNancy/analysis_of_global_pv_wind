"""Aggregate accepted reconstruction shards for S07 and S09."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from paper_figures.config import ROOT,MODELS
from paper_figures.common.io import write_csv,write_json
from paper_figures.common.metrics import climate_deployment
from paper_figures.prepare.reconstruct_supplementary import OUT,tasks
def main():
    seasonal=[];baseline=[];audits=[]
    for s,t,p,m in tasks():
        path=OUT/s/t/p/m
        status=json.loads((path/"complete.json").read_text())
        if status["status"]=="EMPTY":continue
        assert status["status"]=="COMPLETED"
        a=pd.read_csv(path/"reproduction.csv");a["station_ssp"]=s;a["tech"]=t;a["model"]=m;a["patch"]=p;audits.append(a)
        baseline.append(pd.read_csv(path/"baseline.csv.gz"))
        if s=="ssp126":seasonal.append(pd.read_csv(path/"seasonal.csv.gz"))
    audit=pd.concat(audits,ignore_index=True);write_csv(OUT/"reproduction.csv.gz",audit)
    b=pd.concat(baseline,ignore_index=True)
    keys=["model","climate_ssp","station_ssp","tech","country","baseline"]
    annual=b.groupby(keys+["year"],as_index=False)[["net_mwh","capacity_mw","valid_capacity_hours"]].sum()
    counts=annual.groupby(keys).year.nunique();assert (counts==10).all()
    window=annual.groupby(keys,as_index=False)[["net_mwh","capacity_mw","valid_capacity_hours"]].mean()
    window["R"]=window.net_mwh/window.capacity_mw
    dest=ROOT/"paper_figures/supplementary/fig_s09_baseline_sensitivity/outputs/source_data";dest.mkdir(parents=True,exist_ok=True)
    write_csv(dest/"annual.csv.gz",annual);write_csv(dest/"window.csv",window)
    rows=[]
    for key,g in window.groupby(["model","tech","country","baseline"]):
        values=g.set_index(["climate_ssp","station_ssp"]).R.to_dict()
        if len(values)!=9:continue
        rows.append(dict(zip(["model","tech","country","baseline"],key),**climate_deployment(values)))
    contrasts=pd.DataFrame(rows);assert contrasts.closure.abs().max()<1e-7
    write_csv(dest/"contrasts.csv",contrasts)
    seasons=pd.concat(seasonal,ignore_index=True)
    keys=["model","climate_ssp","station_ssp","tech","country","event","season"]
    annual_season=seasons.groupby(keys+["year"],as_index=False)[["net_mwh","capacity_mw"]].sum()
    assert (annual_season.groupby(keys).year.nunique()==10).all()
    season_window=annual_season.groupby(keys,as_index=False)[["net_mwh","capacity_mw"]].mean()
    season_window["R"]=season_window.net_mwh/season_window.capacity_mw
    # Seasonal sums must reproduce the accepted annual signed loss.
    old=pd.read_csv(ROOT/"paper_figures/prepare/outputs/loss_summary/window.csv.gz")
    old=old[(old.snapshot==2050)&(old.station_ssp=="ssp126")&(old.support=="common")&old.climate_ssp.isin(["ssp126","ssp585"])]
    k=["model","climate_ssp","station_ssp","tech","country","event"]
    summed=season_window.groupby(k).R.sum()
    comp=summed.to_frame("seasonal_sum").join(old.set_index(k).R)
    assert comp.R.notna().all()
    error=float((comp.seasonal_sum-comp.R).abs().max());assert error<.002
    dest7=ROOT/"paper_figures/supplementary/fig_s07_seasonal_patterns/outputs/source_data"
    write_csv(dest7/"panel_cd.csv",season_window);write_csv(dest7/"annual_reproduction.csv",comp.reset_index())
    write_json(OUT/"complete.json",{"status":"COMPLETED","tasks":len(tasks()),"max_seasonal_error_per_mw":error,
                                   "min_retained_time_fraction":float(audit.retained_time_fraction.min()),
                                   "max_station_annual_error_per_mw":float(audit.max_error_per_mw.max())})
    print("S07/S09 reconstruction and aggregation accepted",flush=True)
if __name__=="__main__":main()
