"""Audit existing Fig. 3 tables and add only missing model/coverage provenance."""
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, TECHS, SNAPSHOTS, SHAPEFILE
from paper_figures.common.io import digest, write_csv, write_json, require_complete
from paper_figures.common.metrics import ensemble
from paper_figures.common.spatial import countries

FOLDER = ROOT / 'paper_figures/main/fig03_country_differences'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
SPECIAL = ['GLOBAL', 'UNASSIGNED', 'AMBIGUOUS']
CATEGORIES = ['higher_585', 'higher_126', 'unclear', 'unavailable']


def compare(actual, expected, keys, columns):
    a = actual.set_index(keys).sort_index()
    b = expected.set_index(keys).sort_index()
    pd.testing.assert_index_equal(a.index, b.index)
    for column in columns:
        if pd.api.types.is_numeric_dtype(a[column]):
            np.testing.assert_allclose(a[column], b[column], rtol=1e-9, atol=1e-8, equal_nan=True)
        else:
            assert a[column].equals(b[column]), column


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    final = json.loads((ROOT / 'logs/paper_figures/completion_status/final_audit.json').read_text())
    assert final['verified_output_units'] == 664 and final['acceptance']['status'] == 'PASSED'
    require_complete(OUTPUT / 'loss_summary')
    require_complete(OUTPUT / 'panel_loss')
    require_complete(OUTPUT / 'catalogues')
    ab, cd, e, f = [pd.read_csv(SOURCE / name) for name in
                    ['panel_ab.csv', 'panel_cd.csv', 'panel_e.csv', 'panel_f.csv']]
    all_diff = pd.read_csv(OUTPUT / 'loss_summary/contrasts.csv.gz')
    diff = all_diff[all_diff.support.eq('common') & all_diff.metric.eq('R') & all_diff.event.eq('all')].copy()
    assert set(diff.model) == set(MODELS)
    assert not diff.duplicated(['model', 'tech', 'snapshot', 'country']).any()
    np.testing.assert_allclose(diff.D, diff.R585 - diff.R126, equal_nan=True)
    ens = ensemble(diff, ['tech', 'snapshot', 'country'], 'D')
    columns = ['mean', 'minimum', 'maximum', 'n_models', 'agreement', 'category']
    compare(ab, ens[ens.snapshot.eq(2050) & ~ens.country.isin(SPECIAL)],
            ['tech', 'snapshot', 'country'], columns)
    compare(e, diff[diff.snapshot.eq(2050)], ['model', 'tech', 'snapshot', 'country'],
            ['D', 'R126', 'R585'])
    selection = pd.read_csv(OUTPUT / 'panel_loss/country_selection.csv')
    refs = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv')
    refs = refs[refs.station_ssp.eq('ssp126') & refs.snapshot.eq(2050)].copy()
    ranking = refs[~refs.country.isin(SPECIAL)].groupby('country').capacity_mw.sum().sort_values(ascending=False)
    assert selection.sort_values('order').country.tolist()[:12] == ranking.head(12).index.tolist()
    expected_cases = ranking.head(12).index.tolist()
    candidates = ens[ens.snapshot.eq(2050) & ~ens.country.isin(SPECIAL) & ens.agreement.ge(3)].copy()
    candidates['magnitude'] = candidates['mean'].abs()
    for country in candidates.sort_values(['magnitude', 'country'], ascending=[False, True]).country:
        if country not in expected_cases:
            expected_cases.append(country)
        if len(expected_cases) == 18:
            break
    assert selection.sort_values('order').country.tolist() == expected_cases
    compare(cd, ens[ens.country.isin(expected_cases)], ['tech', 'snapshot', 'country'], columns)
    assert len(cd) == 18 * 2 * 3
    members = refs[~refs.country.isin(SPECIAL) & refs.capacity_mw.gt(0)].rename(
        columns={'capacity_mw': 'reference_capacity_mw'}).merge(
            ab, on=['tech', 'snapshot', 'country'], how='left', validate='one_to_one')
    members['category'] = members.category.fillna('unavailable')
    rows = []
    for tech, g in members.groupby('tech'):
        for category in CATEGORIES:
            selected = g[g.category.eq(category)]
            rows.append(dict(tech=tech, category=category, countries=len(selected),
                             country_pct=100*len(selected)/len(g),
                             capacity_pct=100*selected.reference_capacity_mw.sum()/g.reference_capacity_mw.sum(),
                             reference_capacity_mw=selected.reference_capacity_mw.sum(), total_countries=len(g)))
    compare(f, pd.DataFrame(rows), ['tech', 'category'],
            ['countries', 'country_pct', 'capacity_pct', 'reference_capacity_mw', 'total_countries'])
    np.testing.assert_allclose(f.groupby('tech')[['country_pct', 'capacity_pct']].sum(), 100)
    # Read accepted small summaries, never the annual products or preparation shards.
    window = pd.read_csv(OUTPUT / 'loss_summary/window.csv.gz')
    paired = window[window.support.eq('common') & window.event.eq('all')
                    & window.climate_ssp.eq(window.station_ssp)
                    & window.climate_ssp.isin(['ssp126', 'ssp585'])].copy()
    assert not paired.duplicated(['model', 'tech', 'snapshot', 'country', 'climate_ssp']).any()
    np.testing.assert_allclose(paired.R, paired.net_mwh / paired.capacity_mw, equal_nan=True)
    reconstructed = paired.pivot(index=['model', 'tech', 'snapshot', 'country'],
                                 columns='climate_ssp', values='R')
    keys = ['model', 'tech', 'snapshot', 'country']
    reconstructed = reconstructed.reindex(pd.MultiIndex.from_frame(diff[keys]))
    reconstructed['D'] = reconstructed.ssp585 - reconstructed.ssp126
    compare(diff, reconstructed.reset_index(), keys, ['D'])
    cat = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv')
    global_cat = cat.groupby(['station_ssp', 'tech', 'snapshot'], as_index=False).capacity_mw.sum()
    global_cat['country'] = 'GLOBAL'
    cat = pd.concat([cat, global_cat], ignore_index=True).rename(columns={'capacity_mw': 'catalogue_capacity_mw'})
    paired = paired.merge(cat, on=['station_ssp', 'tech', 'snapshot', 'country'], how='left', validate='many_to_one')
    paired['coverage_pct'] = 100 * paired.capacity_mw / paired.catalogue_capacity_mw
    paired['window_start'] = paired.snapshot
    paired['window_end'] = paired.snapshot + 9
    paired['station_source'] = paired.station_ssp.map(
        {'ssp126': 'stations_SSP1-2.6.csv', 'ssp585': 'stations_SSP5-6.0.csv'})
    assert paired.coverage_pct.between(-1e-8, 100+1e-6).all()
    geo = countries()
    ids = [iso for iso, _, _ in geo]
    assert ids.count('CHN') == 1 and 'TWN' not in ids
    assert all(g.is_valid for _, _, g in geo)
    assert set(ab.country).issubset(ids) and 'TWN' not in set(paired.country)
    prj = SHAPEFILE.with_suffix('.prj').read_text()
    assert 'GCS_WGS_1984' in prj
    write_csv(SOURCE / 'panel_abcd_models.csv', diff)
    write_csv(SOURCE / 'paired_pathways_coverage.csv', paired)
    write_csv(SOURCE / 'panel_f_members.csv', members)
    write_csv(SOURCE / 'country_selection.csv', selection)
    write_csv(SOURCE / 'panel_e_display.csv', ens[ens.snapshot.eq(2050)])
    summary = {}
    for tech in TECHS:
        country = ab[ab.tech.eq(tech) & ab['mean'].notna()]
        glob = ens[ens.tech.eq(tech) & ens.country.eq('GLOBAL') & ens.snapshot.eq(2050)].iloc[0]
        summary[tech] = dict(comparable_countries=len(country), country_median=float(country['mean'].median()),
                             mean_difference_range=[float(country['mean'].min()), float(country['mean'].max())],
                             global_mean=float(glob['mean']), global_min=float(glob.minimum), global_max=float(glob.maximum),
                             reference_countries=int(f[f.tech.eq(tech)].total_countries.iloc[0]),
                             reference_capacity_gw=float(members[members.tech.eq(tech)].reference_capacity_mw.sum()/1000))
    input_paths = [OUTPUT / 'loss_summary' / n for n in ['contrasts.csv.gz', 'window.csv.gz']]
    input_paths += [OUTPUT / 'catalogues/capacity_by_country.csv', ROOT / 'logs/paper_figures/completion_status/final_audit.json']
    write_json(OUT / 'data_audit.json', dict(status='PASSED', created_utc=datetime.now(timezone.utc).isoformat(),
               job_id=os.environ.get('SLURM_JOB_ID'), panels={p:'PASSED' for p in 'abcdef'},
               original_tables_preserved=True, preparation_campaign_rerun=False,
               model_count=4, selected_countries=expected_cases, country_geometry_count=len(ids),
               china_union_valid=True, crs='WGS84', summary=summary,
               coverage_pct_range=[float(paired.coverage_pct.min()), float(paired.coverage_pct.max())],
               inputs={str(p.relative_to(ROOT)):digest(p) for p in input_paths}))
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
