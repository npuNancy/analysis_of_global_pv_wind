"""Compute-node acceptance checks for shared figure data and scientific closure."""
import json
import numpy as np
import pandas as pd
from paper_figures.common.cli import parser
from paper_figures.common.io import write_json,complete,require_complete
from paper_figures.common.metrics import safe_ratio

def main():
    p=parser(__doc__);p.add_argument('--event-reference-root',type=__import__('pathlib').Path);a=p.parse_args();root=a.output_root
    if a.event_reference_root is not None:
        import itertools
        checked=[]
        for station,tech,patch in itertools.product(a.station_ssps,a.techs,a.patches):
            relative=__import__('pathlib').Path('station_events')/station/tech/patch
            for base in [root,a.event_reference_root]:require_complete(base/relative)
            for name in ['monthly.csv.gz','frequency_duration.csv.gz']:
                left=pd.read_csv(root/relative/name);right=pd.read_csv(a.event_reference_root/relative/name)
                left=left[left.snapshot.isin(a.snapshots)];right=right[right.snapshot.isin(a.snapshots)]
                keys=[k for k in ['model','climate_ssp','station_ssp','tech','patch','snapshot','year','month','country','event'] if k in left]
                left=left.sort_values(keys).reset_index(drop=True);right=right.sort_values(keys).reset_index(drop=True)
                pd.testing.assert_frame_equal(left,right,check_exact=False,rtol=1e-10,atol=1e-7)
                checked.append(dict(station_ssp=station,tech=tech,patch=patch,file=name,rows=len(left)))
        out=root/'parallel_acceptance';write_json(out/'comparison.json',dict(status='PASSED',checks=checked));complete(out)
        return
    for stage in ['catalogues','loss_summary','event_summary','grid_summary','panel_loss','panel_events']:require_complete(root/stage)
    annual=pd.read_csv(root/'loss_summary/annual.csv.gz');w=pd.read_csv(root/'loss_summary/window.csv.gz');d=pd.read_csv(root/'loss_summary/contrasts.csv.gz');f=pd.read_csv(root/'loss_summary/three_factor.csv.gz')
    def near(left,right,name):
        if not np.allclose(left,right,rtol=1e-8,atol=1e-7,equal_nan=True):raise ValueError(name)
    near(w.annual_loss_pct,100*safe_ratio(w.net_mwh,w.normal_annual_mwh),'Window generation normalization must use ratio of energy totals')
    common=w[w.support.eq('common')];near(common.R,safe_ratio(common.net_mwh,common.capacity_mw),'Common-support capacity normalization')
    near(d.Phi_C+d.Phi_S,d.D,'Climate/deployment closure')
    valid=f[['psi_E','psi_CF','psi_r','delta_C']].notna().all(axis=1)
    near(f.loc[valid,['psi_E','psi_CF','psi_r']].sum(axis=1),f.loc[valid,'delta_C'],'Three-factor closure')
    cover=pd.read_csv(root/'loss_summary/capacity_coverage.csv.gz')
    if (cover.coverage_pct.dropna()>100.0001).any():raise ValueError('Analysis capacity exceeds catalogue capacity')
    monthly=pd.read_csv(root/'event_summary/monthly.csv.gz');ea=pd.read_csv(root/'event_summary/annual.csv.gz');keys=['model','climate_ssp','station_ssp','tech','snapshot','year','country','event']
    totals=monthly.groupby(keys).E.sum().sort_index();direct=ea.set_index(keys).E.sort_index();near(totals,direct,'Monthly exposure closure')
    ew=pd.read_csv(root/'event_summary/window.csv.gz');sk=['model','climate_ssp','station_ssp','tech','snapshot','country','event']
    season=pd.read_csv(root/'event_summary/seasonal.csv.gz').groupby(sk).E.sum().sort_index();near(season,ew.set_index(sk).E.sort_index(),'Seasonal exposure closure')
    paired=ew.merge(common,on=sk,suffixes=('_event','_loss'),validate='one_to_one')
    diagnostic=float((paired.E-paired.E_loss).abs().max()) if len(paired) else None
    out=root/'acceptance';out.mkdir(parents=True,exist_ok=True)
    write_json(out/'checks.json',dict(status='PASSED',annual_rows=len(annual),window_rows=len(w),contrast_rows=len(d),three_factor_defined_rows=int(valid.sum()),
                                    maximum_exposure_difference_between_meteorological_and_loss_validity=diagnostic,
                                    interpretation='Exposure definitions need not coincide; finite annual Loss does not prove identical valid timestamps',
                                    figures_rendered=False))
    complete(out,scientific_checks='normalization, capacity bounds, country/global conservation upstream, paired and three-factor closure, monthly and seasonal closure')
if __name__=='__main__':main()
