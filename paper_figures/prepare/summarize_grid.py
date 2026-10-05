"""Combine area-weighted display cells and export Fig. 1 / S5 map source data."""
import itertools
import pandas as pd
import numpy as np
from paper_figures.config import ROOT
from paper_figures.common.cli import parser
from paper_figures.common.io import write_csv,complete,require_complete
from paper_figures.common.metrics import ensemble

def main():
    p=parser(__doc__);p.add_argument('--figure-root',type=__import__('pathlib').Path,default=ROOT/'paper_figures');a=p.parse_args();out=a.output_root/'grid_summary';out.mkdir(parents=True,exist_ok=True);parts=[]
    for t,p in itertools.product(a.techs,a.patches):
        folder=a.output_root/'grid_events'/t/p;require_complete(folder);parts.append(pd.read_csv(folder/'display_grid.csv.gz'))
    keys=['model','climate_ssp','tech','snapshot','lat','lon']
    table=pd.concat(parts,ignore_index=True).groupby(keys,as_index=False)[['weighted_hours','area']].sum();table['hours']=table.weighted_hours/table.area
    write_csv(out/'display_hours.csv.gz',table)
    pivot=table.pivot(index=[k for k in keys if k!='climate_ssp'],columns='climate_ssp',values='hours');pivot['difference']=pivot.ssp585-pivot.ssp126;diff=pivot.reset_index()
    write_csv(out/'model_differences.csv.gz',diff);summary=ensemble(diff,['tech','snapshot','lat','lon'],'difference',len(a.models));write_csv(out/'ensemble_differences.csv.gz',summary)
    write_csv(a.figure_root/'main/fig01_extreme_events/outputs/source_data/panel_ab.csv.gz',summary[summary.snapshot.eq(2050)])
    write_csv(a.figure_root/'supplementary/fig_s05_model_uncertainty/outputs/source_data/panel_ef.csv.gz',summary[summary.snapshot.eq(2050)])
    complete(out,display_resolution_degrees=1,aggregation='area weighted on common valid native cells; no nearest-point subsampling')
if __name__=='__main__':main()
