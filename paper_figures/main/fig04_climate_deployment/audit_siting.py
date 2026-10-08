"""Audit deployed capacity and the country composition of Fig. 4 contrasts."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs' / 'siting_audit'
PREP = ROOT / 'paper_figures/prepare/outputs'
FILES = {'ssp126': 'stations_SSP1-2.6.csv', 'ssp245': 'stations_SSP2-4.5.csv', 'ssp585': 'stations_SSP5-6.0.csv'}

def main():
    OUT.mkdir(exist_ok=True, parents=True)
    summaries, temporal, overlap, hashes = [], [], [], {}
    late = {}
    for s, name in FILES.items():
        path = ROOT / 'data/stations' / name
        hashes[str(path)] = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
        f = pd.read_csv(path)
        assert set(f.columns) == {'year', 'type', 'lon', 'lat', 'capacity_gw'}
        assert np.isfinite(f[['lon', 'lat', 'capacity_gw']]).all().all()
        assert (f.capacity_gw >= 0).all()
        f['lon'] = (f.lon + 180) % 360 - 180
        f['lon_key'] = (f.lon * 100000).round().astype('int64')
        f['lat_key'] = (f.lat * 100000).round().astype('int64')
        for (y, t), g in f.groupby(['year', 'type']):
            cap = g.capacity_gw
            summaries.append(dict(station_ssp=s, year=int(y), tech=t, rows=len(g), positive_rows=int((cap > 0).sum()),
                duplicate_coords=int(g.duplicated(['lon_key', 'lat_key']).sum()), capacity_gw=float(cap.sum()),
                weighted_lat=float(np.average(g.lat, weights=cap)), max_lat=float(g.lat.max()), north60_capacity_pct=float(100*cap[g.lat>60].sum()/cap.sum()), abs_lat_ge45_capacity_pct=float(100 * cap[g.lat.abs() >= 45].sum() / cap.sum()),
                north_capacity_pct=float(100 * cap[g.lat >= 0].sum() / cap.sum()),
                median_capacity_mw=float(cap.median()*1000), max_capacity_mw=float(cap.max()*1000)))
        for t, g in f.groupby('type'):
            q = g.pivot_table(index=['lon_key','lat_key'], columns='year', values='capacity_gw', aggfunc='sum', fill_value=0)
            for a, b in zip(q.columns[:-1], q.columns[1:]):
                delta = q[b] - q[a]
                temporal.append(dict(station_ssp=s, tech=t, year_a=int(a), year_b=int(b),
                    decreasing_cells=int((delta < -1e-6).sum()), removed_cells=int(((q[a] > 0) & (q[b] == 0)).sum()),
                    decrease_gw=float(-delta[delta < 0].sum()), growth_gw=float(delta.sum())))
            late[s,t] = q[2050]
        print('station input complete',s,flush=True)
    pd.DataFrame(summaries).to_csv(OUT/'station_summary.csv', index=False)
    pd.DataFrame(temporal).to_csv(OUT/'temporal_capacity.csv', index=False)
    for t in sorted({k[1] for k in late}):
        for a,b in itertools.combinations(FILES,2):
            x,y = late[a,t].align(late[b,t],fill_value=0)
            p,q = x/x.sum(),y/y.sum()
            overlap.append(dict(tech=t,station_a=a,station_b=b,common_cells=int(((x>0)&(y>0)).sum()),
                union_cells=int(((x>0)|(y>0)).sum()),jaccard=float(((x>0)&(y>0)).sum()/((x>0)|(y>0)).sum()),
                normalized_capacity_overlap_pct=float(100*np.minimum(p,q).sum()),
                a_capacity_on_b_footprint_pct=float(100*p[y>0].sum()),b_capacity_on_a_footprint_pct=float(100*q[x>0].sum())))
    pd.DataFrame(overlap).to_csv(OUT/'deployment_overlap.csv',index=False)
    w = pd.read_csv(HERE/'outputs/source_data/model_combinations_coverage.csv')
    assert not w.duplicated(['model','tech','country','climate_ssp','station_ssp']).any()
    terms, totals, shares = [], [], []
    for (model,t,c),g in w.groupby(['model','tech','climate_ssp']):
        for a,b in itertools.combinations(FILES,2):
            ga = g[g.station_ssp.eq(a)&g.country.ne('GLOBAL')].set_index('country')
            gb = g[g.station_ssp.eq(b)&g.country.ne('GLOBAL')].set_index('country')
            x = pd.concat({'a':ga[['capacity_mw','R']], 'b':gb[['capacity_mw','R']]},axis=1)
            ca,cb = x['a']['capacity_mw'].fillna(0),x['b']['capacity_mw'].fillna(0)
            ra,rb = x['a']['R'].fillna(0),x['b']['R'].fillna(0)
            pa,pb = ca/ca.sum(),cb/cb.sum()
            both = (ca>0)&(cb>0)
            between = ((pb-pa)*(ra+rb)/2).where(both,0)
            within = ((pa+pb)*(rb-ra)/2).where(both,0)
            entry_exit = (pb*rb-pa*ra).where(~both,0)
            total = float(g[g.country.eq('GLOBAL')&g.station_ssp.eq(b)].R.iloc[0]-g[g.country.eq('GLOBAL')&g.station_ssp.eq(a)].R.iloc[0])
            assert np.isclose(between.sum()+within.sum()+entry_exit.sum(),total,atol=1e-8)
            totals.append(dict(model=model,tech=t,climate_ssp=c,station_a=a,station_b=b,total=total,
                between_country=float(between.sum()),within_country=float(within.sum()),entry_exit=float(entry_exit.sum())))
            for country in x.index:
                terms.append(dict(model=model,tech=t,climate_ssp=c,station_a=a,station_b=b,country=country,
                    weight_a=float(pa[country]),weight_b=float(pb[country]),R_a=float(ra[country]),R_b=float(rb[country]),
                    between_country=float(between[country]),within_country=float(within[country]),entry_exit=float(entry_exit[country]),
                    total=float((pb*rb-pa*ra)[country])))
    pd.DataFrame(totals).to_csv(OUT/'country_decomposition.csv',index=False)
    pd.DataFrame(terms).to_csv(OUT/'country_decomposition_detail.csv',index=False)
    parts=[]
    for part in pd.read_csv(PREP/'loss_summary/window.csv.gz',chunksize=50000):
        parts.append(part[part.country.eq('GLOBAL')&part.snapshot.eq(2050)])
    global_w=pd.concat(parts,ignore_index=True)
    global_w.to_csv(OUT/'global_loss_metrics.csv',index=False)
    caps=pd.read_csv(PREP/'catalogues/capacity_by_country.csv')
    caps=caps[caps.snapshot.eq(2050)].copy()
    caps['share_pct']=100*caps.capacity_mw/caps.groupby(['station_ssp','tech']).capacity_mw.transform('sum')
    caps.sort_values(['tech','station_ssp','share_pct'],ascending=[True,True,False]).to_csv(OUT/'country_capacity_share.csv',index=False)
    cancellation = []
    for (model, tech, station_ssp), g in w[w.country.ne('GLOBAL')].groupby(['model', 'tech', 'station_ssp']):
        rates = g.pivot(index='country', columns='climate_ssp', values='R')
        cap = g[g.climate_ssp.eq('ssp126')].set_index('country').capacity_mw
        contribution = (rates.ssp585-rates.ssp126)*cap/cap.sum()
        cancellation.append(dict(model=model, tech=tech, station_ssp=station_ssp,
            signed=float(contribution.sum()), positive=float(contribution.clip(lower=0).sum()),
            negative=float(contribution.clip(upper=0).sum()), absolute=float(contribution.abs().sum())))
    pd.DataFrame(cancellation).to_csv(OUT/'climate_country_cancellation.csv', index=False)
    baseline_path = ROOT/'paper_figures/supplementary/fig_s09_baseline_sensitivity/outputs/source_data/contrasts.csv'
    baseline = pd.read_csv(baseline_path)
    baseline[baseline.country.eq('GLOBAL')].to_csv(OUT/'global_baseline_sensitivity.csv', index=False)
    hashes[str(baseline_path)] = hashlib.file_digest(baseline_path.open('rb'), 'sha256').hexdigest()
    for path in [Path(__file__), HERE/'outputs/source_data/model_combinations_coverage.csv',
                 PREP/'loss_summary/window.csv.gz', PREP/'catalogues/capacity_by_country.csv']:
        hashes[str(path)] = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    for filename in ['station_summary.csv','deployment_overlap.csv','temporal_capacity.csv']:
        print(filename,flush=True)
        print(pd.read_csv(OUT/filename).to_string(index=False),flush=True)
    print('decomposition ensemble',flush=True)
    print(pd.DataFrame(totals).groupby(['tech','climate_ssp','station_a','station_b'])[['total','between_country','within_country','entry_exit']].mean().to_string(),flush=True)
    metadata=dict(job_id=os.environ.get('SLURM_JOB_ID'),input_and_code_sha256=hashes,
        scope='Fig4 2050 snapshot, existing accepted source tables; no upstream source or plotting changes',
        country_decomposition='symmetric split on countries with capacity in both deployments; entry/exit countries separate',
        coordinate_keys='normalized longitude and latitude rounded to 1e-5 degree; input CSV coordinates unchanged')
    (OUT/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print('AUDIT COMPLETE',flush=True)

if __name__ == '__main__':
    main()
