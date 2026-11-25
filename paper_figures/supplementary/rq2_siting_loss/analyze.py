"""Summarize spatial distributions and compare layout and climate contrasts."""
from pathlib import Path
import json,sys
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from paper_figures.config import MODELS,SSPS
DATA=HERE/'outputs/source_data';RQ1=ROOT/'tmp/RQ1_20261112_grid_candidates/source_data'
TECHS=('wind','solar')

def main():
    for name in ('grid','station'):
        assert json.loads((HERE/f'outputs/{name}_validation.json').read_text())['status']=='PASSED'
    fixed=pd.read_csv(DATA/'fixed2025_decadal_models.csv')
    cols=['model','climate_ssp','tech','time','exposure_days','intensity_pct','net_loss_per_mw']
    curves=fixed[cols].copy();curves['domain']='fixed2025';curves['weighting']='capacity2025'
    suitable=pd.read_csv(RQ1/'candidate1_intensity_models.csv')
    suitable=suitable[['model','climate_ssp','tech','time','value','net_loss_per_mw_per_year']].rename(columns={'value':'intensity_pct','net_loss_per_mw_per_year':'net_loss_per_mw'})
    exposure=pd.read_csv(RQ1/'candidate1_exposure_models.csv')
    exposure=exposure[['model','climate_ssp','tech','time','value']].rename(columns={'value':'exposure_days'})
    suitable=suitable.merge(exposure[['model','climate_ssp','tech','time','exposure_days']],on=['model','climate_ssp','tech','time'],validate='one_to_one')
    s=suitable[cols].copy();s['domain']='suitable';s['weighting']='area'
    curves=pd.concat([curves,s],ignore_index=True)
    curves.to_csv(DATA/'curve_models.csv',index=False)
    keys=['climate_ssp','tech','time','domain','weighting']
    display=curves.groupby(keys)[['exposure_days','intensity_pct','net_loss_per_mw']].agg(['mean','min','max'])
    display.columns=['_'.join(c) for c in display.columns];display.reset_index().to_csv(DATA/'curve_display.csv',index=False)
    summary=[];models=[];bins=[];overlap=[]
    for tech in TECHS:
        with np.load(DATA/f'fixed2025_{tech}_2050s.npz') as z:f={k:z[k] for k in z.files}
        with np.load(DATA/f'suitable_{tech}_2050s.npz') as z:g={k:z[k] for k in z.files}
        for z in (f,g):
            assert z['models'].tolist()==list(MODELS) and z['ssps'].tolist()==list(SSPS)
        values={domain:z['net_loss'].mean(axis=0) for domain,z in [('fixed2025',f),('suitable',g)]}
        minimum=min(a.min() for a in values.values());maximum=max(a.max() for a in values.values())
        width=max(5.,np.ceil((maximum-minimum)/70/5)*5)
        edges=np.arange(np.floor(minimum/width)*width,np.ceil(maximum/width)*width+width*.5,width)
        for domain,z in [('fixed2025',f),('suitable',g)]:
            for si,ssp in enumerate(SSPS):
                v=values[domain][si]
                counts,_=np.histogram(v,bins=edges);assert counts.sum()==len(v)
                weights=z['capacity'] if domain=='fixed2025' else z['area']
                summary.append(dict(tech=tech,climate_ssp=ssp,domain=domain,n_cells=len(v),mean=v.mean(),median=np.median(v),p10=np.quantile(v,.1),p90=np.quantile(v,.9),minimum=v.min(),maximum=v.max(),negative_fraction=(v<0).mean(),weighted_mean=np.average(v,weights=weights),weighting='capacity2025' if domain=='fixed2025' else 'area'))
                for j,n in enumerate(counts):bins.append(dict(tech=tech,climate_ssp=ssp,domain=domain,left=edges[j],right=edges[j+1],count=int(n),n_cells=len(v),relative_frequency=n/len(v)))
                for mi,m in enumerate(MODELS):
                    vm=z['net_loss'][mi,si]
                    models.append(dict(tech=tech,climate_ssp=ssp,model=m,domain=domain,equal_mean=vm.mean(),median=np.median(vm),weighted_mean=np.average(vm,weights=weights)))
        # Same sampled coordinates diagnose whether two product pipelines agree on overlapping cells.
        def key(z):return np.round(((z['lon']+180)%360-180)*1e4).astype(np.int64)*2000001+np.round(z['lat']*1e4).astype(np.int64)
        gkey=key(g);fkey=key(f);assert len(np.unique(gkey))==len(gkey)
        pos=pd.Index(gkey).get_indexer(fkey);keep=pos>=0
        for mi,m in enumerate(MODELS):
            for si,ssp in enumerate(SSPS):
                x=f['net_loss'][mi,si,keep];y=g['net_loss'][mi,si,pos[keep]];delta=x-y
                overlap.append(dict(tech=tech,model=m,climate_ssp=ssp,n_fixed=len(keep),n_matched=int(keep.sum()),matched_capacity_fraction=float(f['capacity'][keep].sum()/f['capacity'].sum()),mean_difference=delta.mean(),mean_abs_difference=np.abs(delta).mean(),p95_abs_difference=np.quantile(np.abs(delta),.95),max_abs_difference=np.abs(delta).max(),fixed_matched_mean=x.mean(),suitable_matched_mean=y.mean()))
    summary=pd.DataFrame(summary);summary.to_csv(DATA/'distribution_summary.csv',index=False)
    pd.DataFrame(bins).to_csv(DATA/'histogram_bins.csv',index=False)
    models=pd.DataFrame(models);models.to_csv(DATA/'distribution_models.csv',index=False)
    pd.DataFrame(overlap).to_csv(DATA/'overlapping_product_check.csv',index=False)
    contrast=[]
    for (tech,model),group in models.groupby(['tech','model']):
        for metric in ['equal_mean','weighted_mean']:
            p=group.pivot(index='domain',columns='climate_ssp',values=metric).loc[['fixed2025','suitable'],list(SSPS)]
            gaps=p.loc['fixed2025']-p.loc['suitable'];crange=p.max(axis=1)-p.min(axis=1)
            for ssp in SSPS:contrast.append(dict(tech=tech,model=model,metric=metric,climate_ssp=ssp,domain_difference=gaps[ssp],fixed_climate_range=crange['fixed2025'],suitable_climate_range=crange['suitable'],larger_than_both=abs(gaps[ssp])>crange.max()))
    pd.DataFrame(contrast).to_csv(DATA/'domain_climate_contrasts.csv',index=False)
    future=pd.read_csv(DATA/'future_layout_matrix_models.csv')
    future.groupby(['station_ssp','climate_ssp','tech'],as_index=False).unit_loss_mwh_per_mw.mean().to_csv(DATA/'future_layout_matrix_display.csv',index=False)
    future_range=[]
    ensemble=future.groupby(['station_ssp','climate_ssp','tech'],as_index=False).unit_loss_mwh_per_mw.mean();ensemble['model']='ensemble'
    for (tech,model),group in pd.concat([future,ensemble]).groupby(['tech','model']):
        p=group.pivot(index='station_ssp',columns='climate_ssp',values='unit_loss_mwh_per_mw')
        layout_range=p.max(axis=0)-p.min(axis=0);climate_range=p.max(axis=1)-p.min(axis=1)
        future_range.append(dict(tech=tech,model=model,layout_range_min=layout_range.min(),layout_range_max=layout_range.max(),climate_range_min=climate_range.min(),climate_range_max=climate_range.max(),conservative_ratio=layout_range.min()/climate_range.max(),upper_ratio=layout_range.max()/climate_range.min(),layout_larger_at_every_climate=bool(layout_range.min()>climate_range.max())))
    pd.DataFrame(future_range).to_csv(DATA/'future_layout_climate_ranges.csv',index=False)
    print('DISTRIBUTIONS\n',summary.to_string(index=False))
    print('FUTURE RANGES\n',pd.DataFrame(future_range).to_string(index=False))
    print('OVERLAP\n',pd.DataFrame(overlap).groupby('tech')[['n_matched','mean_abs_difference','p95_abs_difference']].mean().to_string())
if __name__=='__main__':main()
