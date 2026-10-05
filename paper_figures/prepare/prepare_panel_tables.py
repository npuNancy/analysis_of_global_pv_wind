"""Model-resolved main/supplementary panel data from accepted shared summaries."""
import numpy as np
import pandas as pd
from paper_figures.config import ROOT
from paper_figures.common.cli import parser
from paper_figures.common.io import write_csv,write_json,require_complete,complete
from paper_figures.common.metrics import ensemble

MAIN={1:'fig01_extreme_events',2:'fig02_generation_loss',3:'fig03_country_differences',4:'fig04_climate_deployment',5:'fig05_residual_loss'}
SUPP={1:'fig_s01_three_factor_decomposition',2:'fig_s02_annual_loss_distribution',3:'fig_s03_loss_concentration',4:'fig_s04_country_counterfactuals',5:'fig_s05_model_uncertainty',6:'fig_s06_loss_metric_sensitivity',7:'fig_s07_seasonal_patterns',8:'fig_s08_event_frequency_duration',10:'fig_s10_coverage_weights_thresholds'}

def main():
    p=parser(__doc__);p.add_argument('--stage',choices=['loss','events'],default='loss');p.add_argument('--figure-root',type=__import__('pathlib').Path,default=ROOT/'paper_figures');a=p.parse_args()
    artifacts=[]
    def save(group,num,name,table):
        folder=a.figure_root/group/(MAIN[num] if group=='main' else SUPP[num])/'outputs/source_data'
        write_csv(folder/name,table);artifacts.append(folder/name)
    if a.stage=='events':
        base=a.output_root/'event_summary';require_complete(base);w=pd.read_csv(base/'window.csv.gz');d=w[w.climate_ssp.eq(w.station_ssp)]
        save('main',1,'panel_cd.csv',d[d.event.eq('all')&d.country.eq('GLOBAL')]);save('main',1,'panel_ef.csv',d[d.snapshot.eq(2050)&d.country.eq('GLOBAL')&d.event.ne('all')])
        save('supplementary',7,'panel_ab.csv',pd.read_csv(base/'seasonal.csv.gz'))
        if (base/'frequency_duration.csv.gz').exists():save('supplementary',8,'panel_abcd.csv',pd.read_csv(base/'frequency_duration.csv.gz'))
        complete(a.output_root/'panel_events',artifact_paths=artifacts,figure_root=str(a.figure_root));return
    base=a.output_root/'loss_summary';require_complete(base)
    annual=pd.read_csv(base/'annual.csv.gz');window=pd.read_csv(base/'window.csv.gz');contrasts=pd.read_csv(base/'contrasts.csv.gz');factor=pd.read_csv(base/'three_factor.csv.gz')
    common=window[window.support.eq('common')];paired=common[common.climate_ssp.eq(common.station_ssp)]
    diff=contrasts[contrasts.support.eq('common')&contrasts.metric.eq('R')&contrasts.event.eq('all')]
    refs=pd.read_csv(a.output_root/'catalogues/capacity_by_country.csv');refs=refs[refs.station_ssp.eq('ssp126')&refs.snapshot.eq(2050)].rename(columns={'capacity_mw':'reference_capacity_mw'})[['tech','country','reference_capacity_mw']]
    special=['GLOBAL','UNASSIGNED','AMBIGUOUS']
    ens=ensemble(diff,['tech','snapshot','country'],'D',len(a.models))
    r126=paired[paired.climate_ssp.eq('ssp126')&paired.event.eq('all')];r_ens=ensemble(r126,['tech','snapshot','country'],'R',len(a.models))
    capacities=refs[~refs.country.isin(special)].groupby('country').reference_capacity_mw.sum().sort_values(ascending=False)
    cases=list(capacities.head(12).index)
    ranked=ens[ens.snapshot.eq(2050)&~ens.country.isin(special)&ens.agreement.ge(3)].copy();ranked['magnitude']=ranked['mean'].abs();ranked=ranked.sort_values(['magnitude','country'],ascending=[False,True])
    for country in ranked.country:
        if country not in cases:cases.append(country)
        if len(cases)>=18:break
    case_table=pd.DataFrame({'country':cases,'order':range(len(cases)),'reason':['reference_capacity_top12' if i<12 else 'large_model_supported_difference' for i in range(len(cases))]})
    write_csv(a.output_root/'loss_summary/country_selection.csv',case_table)
    explanation=cases[:8]
    save('main',2,'panel_ab.csv',annual[annual.support.eq('common')&annual.country.eq('GLOBAL')&annual.event.eq('all')&annual.climate_ssp.eq(annual.station_ssp)])
    save('main',2,'panel_cd.csv',diff[diff.country.eq('GLOBAL')]);save('main',2,'panel_ef.csv',paired[paired.country.eq('GLOBAL')&paired.snapshot.eq(2050)&paired.event.ne('all')])
    save('main',3,'panel_ab.csv',ens[ens.snapshot.eq(2050)&~ens.country.isin(special)])
    save('main',3,'panel_cd.csv',ens[ens.country.isin(cases)].merge(case_table,on='country',validate='many_to_one'))
    save('main',3,'panel_e.csv',diff[diff.snapshot.eq(2050)])
    shares=refs[~refs.country.isin(special)&refs.reference_capacity_mw.gt(0)].merge(ens[ens.snapshot.eq(2050)],on=['country','tech'],how='left',validate='one_to_one');shares['category']=shares.category.fillna('unavailable')
    share_rows=[]
    for t,g in shares.groupby('tech'):
        for category in ['higher_585','higher_126','unclear','unavailable']:
            sel=g[g.category.eq(category)];share_rows.append(dict(tech=t,category=category,countries=len(sel),country_pct=100*len(sel)/len(g),capacity_pct=100*sel.reference_capacity_mw.sum()/g.reference_capacity_mw.sum(),reference_capacity_mw=sel.reference_capacity_mw.sum(),total_countries=len(g)))
    save('main',3,'panel_f.csv',pd.DataFrame(share_rows))
    save('main',4,'panel_ab.csv',common[common.country.eq('GLOBAL')&common.snapshot.eq(2050)&common.event.eq('all')]);save('main',4,'panel_cd.csv',diff[diff.snapshot.eq(2050)&diff.country.isin(['GLOBAL',*explanation])]);save('main',4,'panel_ef.csv',diff[diff.snapshot.eq(2050)&~diff.country.isin(special)].merge(refs,on=['country','tech'],how='left',validate='many_to_one'))
    thresholds=[]
    for t in a.techs:
        early=r_ens[r_ens.tech.eq(t)&r_ens.snapshot.eq(2030)&~r_ens.country.isin(special)&r_ens['mean'].notna()].set_index('country')['mean']
        late=shares[shares.tech.eq(t)&shares.category.ne('unavailable')].country
        population=early.loc[early.index.intersection(late)]
        if len(population):
            for q in [.5,.75,.9]:thresholds.append(dict(tech=t,quantile=q,threshold=float(population.quantile(q)),n_countries=len(population),countries=';'.join(sorted(population.index))))
    thresholds=pd.DataFrame(thresholds,columns=['tech','quantile','threshold','n_countries','countries']);write_csv(base/'residual_thresholds.csv',thresholds)
    fig5=diff[diff.snapshot.eq(2050)&~diff.country.isin(special)].merge(refs,on=['country','tech'],how='left',validate='many_to_one').merge(ens[ens.snapshot.eq(2050)][['tech','country','category','agreement']],on=['tech','country'],how='left',validate='many_to_one')
    if len(thresholds):fig5=fig5.merge(thresholds[thresholds['quantile'].eq(.75)][['tech','threshold']],on='tech',how='left',validate='many_to_one')
    save('main',5,'panel_ab.csv',fig5)
    save('supplementary',1,'panel_abcdef.csv',factor)
    late=annual[annual.support.eq('common')&annual.country.eq('GLOBAL')&annual.snapshot.eq(2050)&annual.event.eq('all')&annual.climate_ssp.eq(annual.station_ssp)]
    ecdf=[]
    for t,g in late.groupby('tech'):
        grid=np.sort(g.R.dropna().unique())
        for (m,c),sample in g.groupby(['model','climate_ssp']):
            values=sample.R.dropna().to_numpy()
            if len(values)!=10:raise ValueError('ECDF requires ten valid years per model')
            ecdf.extend(dict(tech=t,model=m,climate_ssp=c,threshold=x,exceedance_pct=100*np.mean(values>x),n_years=len(values)) for x in grid)
    save('supplementary',2,'panel_ab.csv',pd.DataFrame(ecdf))
    burden=r126[r126.snapshot.eq(2050)&~r126.country.isin(special)].merge(refs,on=['country','tech'],how='left',validate='many_to_one')
    save('supplementary',3,'country_burden_inputs.csv',burden)
    concentration=[]
    for t,g in burden.groupby('tech'):
        wide=g.pivot(index='country',columns='model',values='R').dropna()
        if len(wide.columns)!=len(a.models):continue
        order=wide.mean(axis=1).sort_values(ascending=False,kind='stable').index
        for m in a.models:
            sample=g[g.model.eq(m)].set_index('country').reindex(order)
            sample=sample[sample.reference_capacity_mw.gt(0)];cap=sample.reference_capacity_mw.to_numpy();risk=sample.R.to_numpy();b=cap*np.maximum(risk,0)
            interpretation='covered_positive_net_burden' if np.allclose(cap,sample.capacity_mw,rtol=1e-6,atol=1e-5) else 'reference_capacity_weighted_index'
            for i,country in enumerate(sample.index):
                concentration.append(dict(tech=t,model=m,country=country,rank=i+1,cumulative_capacity_pct=100*cap[:i+1].sum()/cap.sum(),
                                          cumulative_burden_pct=100*b[:i+1].sum()/b.sum() if b.sum()>0 else np.nan,positive_net_burden=b[i],interpretation=interpretation))
    save('supplementary',3,'panel_ab.csv',pd.DataFrame(concentration))
    save('supplementary',4,'panel_abcdefgh.csv',diff)
    save('supplementary',5,'panel_ab.csv',common[common.snapshot.eq(2050)&common.country.eq('GLOBAL')&common.event.eq('all')]);save('supplementary',5,'panel_cd.csv',paired[paired.snapshot.eq(2050)&paired.country.eq('GLOBAL')&paired.event.ne('all')])
    save('supplementary',6,'panel_abcd.csv',contrasts[contrasts.support.eq('common')&contrasts.event.eq('all')])
    save('supplementary',10,'panel_ab.csv',pd.read_csv(base/'capacity_coverage.csv.gz'));save('supplementary',10,'panel_cd.csv',contrasts[contrasts.metric.eq('R')&contrasts.event.eq('all')]);save('supplementary',10,'thresholds.csv',thresholds)
    sensitivity=[]
    allrefs=pd.read_csv(a.output_root/'catalogues/capacity_by_country.csv');allrefs=allrefs[allrefs.snapshot.eq(2050)]
    for _,th in thresholds.iterrows():
        names=th.countries.split(';');late=r_ens[r_ens.tech.eq(th.tech)&r_ens.snapshot.eq(2050)].set_index('country').reindex(names)
        high=late['mean'].gt(th.threshold)&late['mean'].gt(0)
        for reference_ssp in a.station_ssps:
            weights=allrefs[allrefs.tech.eq(th.tech)&allrefs.station_ssp.eq(reference_ssp)].set_index('country').capacity_mw.reindex(names,fill_value=0)
            sensitivity.append(dict(tech=th.tech,quantile=th['quantile'],threshold=th.threshold,reference_ssp=reference_ssp,
                                    country_pct=100*high.mean(),capacity_pct=100*weights[high].sum()/weights.sum() if weights.sum()>0 else np.nan,
                                    n_countries=len(names),high_countries=';'.join(late.index[high])))
    save('supplementary',10,'panel_ef.csv',pd.DataFrame(sensitivity))
    complete(a.output_root/'panel_loss',artifact_paths=artifacts,figure_root=str(a.figure_root),note='Model-resolved panel inputs; plotting computes ensemble summaries where appropriate. Figures not rendered.')
if __name__=='__main__':main()
