"""Prepare and audit Fig. 2 and the migrated Fig. S12 source data."""
import itertools
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, SNAPSHOTS, EVENTS
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.metrics import ensemble

FOLDER = ROOT / 'paper_figures/main/fig02_generation_loss'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
UNIT = 'MWh MW⁻¹ yr⁻¹'

def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit():
    OUT.mkdir(parents=True, exist_ok=True)
    final_path = ROOT / 'logs/paper_figures/completion_status/final_audit.json'
    final = json.loads(final_path.read_text())
    require(final['acceptance']['status'] == 'PASSED' and
            final['verified_output_units'] == final['manifest_units'] == 664,
            'Preparation acceptance incomplete')
    for folder in ['loss_summary', 'event_summary', 'panel_loss', 'catalogues']:
        require_complete(OUTPUT / folder)
    a, c, e = [pd.read_csv(SOURCE / name) for name in
               ['panel_ab.csv', 'panel_cd.csv', 'panel_ef.csv']]
    keys = ['model', 'climate_ssp', 'station_ssp', 'tech', 'snapshot', 'country', 'event', 'support']
    first = a.iloc[0]
    require(np.isclose(first.R, first.net_mwh / first.capacity_mw), 'Sample normalization')
    for t, count in [(a, 720), (c, 24), (e, 132)]:
        require(len(t) == count, 'Incomplete panel table')
        require(t.country.eq('GLOBAL').all() and t.support.eq('common').all(), 'Scope mismatch')
        require(set(t.model) == set(MODELS), 'Model coverage')
    require(not c.duplicated(['model', 'tech', 'snapshot']).any(), 'Duplicate contrast')
    require(c.event.eq('all').all() and c.metric.eq('R').all(), 'Contrast metric mismatch')
    for t, extra in [(a, ['year']), (e, [])]:
        require(not t.duplicated(keys + extra).any(), 'Duplicate loss record')
        require(t.climate_ssp.eq(t.station_ssp).all(), 'Unpaired pathway')
        require(np.isfinite(t[['R', 'net_mwh', 'capacity_mw']]).all().all(), 'Missing loss value')
        require(t.capacity_mw.gt(0).all(), 'Non-positive denominator')
        require(np.allclose(t.R, t.net_mwh / t.capacity_mw, rtol=1e-11), 'Normalization mismatch')
    require(a.event.eq('all').all(), 'Annual table must use event union')
    expected = set(itertools.product(MODELS, SSPS, TECHS, range(2030, 2060)))
    require(set(a[['model', 'climate_ssp', 'tech', 'year']].itertuples(index=False, name=None))
            == expected, 'Missing annual combination')
    require((a.snapshot == (a.year // 10) * 10).all(), 'Year/snapshot mismatch')
    cap = a.groupby(['station_ssp', 'tech', 'snapshot']).capacity_mw.agg(['min', 'max'])
    require(np.allclose(cap['min'], cap['max']), 'Common support capacity varies')
    window = a.groupby(keys, as_index=False).agg(
        R=('R', 'mean'), net_mwh=('net_mwh', 'mean'), capacity_mw=('capacity_mw', 'first'),
        available_capacity_mw=('available_capacity_mw', 'first'), n_stations=('n_stations', 'first'),
        n_years=('year', 'nunique'))
    require(window.n_years.eq(10).all(), 'Incomplete decade')
    window['year_start'] = window.snapshot
    window['year_end'] = window.snapshot + 9
    wide = window.pivot(index=['model', 'tech', 'snapshot'], columns='climate_ssp', values='R')
    contrasts = []
    for ssp, field in [('ssp245', 'D245'), ('ssp585', 'D')]:
        reference = c.set_index(['model', 'tech', 'snapshot'])[field].sort_index()
        delta = (wide[ssp] - wide.ssp126).sort_index()
        require(reference.index.equals(delta.index) and np.allclose(reference, delta, atol=1e-10),
                'Stored contrast differs from within-model annual means')
        block = window[window.climate_ssp.eq(ssp)].copy()
        base = window[window.climate_ssp.eq('ssp126')][
            ['model', 'tech', 'snapshot', 'R', 'capacity_mw', 'n_stations']].rename(
                columns={'R': 'reference_R', 'capacity_mw': 'reference_capacity_mw',
                         'n_stations': 'reference_n_stations'})
        block = block.merge(base, on=['model', 'tech', 'snapshot'], validate='one_to_one')
        block['difference'] = block.R - block.reference_R
        block['reference_climate_ssp'] = 'ssp126'
        block['reference_station_ssp'] = 'ssp126'
        contrasts.append(block)
    contrasts = pd.concat(contrasts, ignore_index=True)
    require(e.snapshot.eq(2050).all(), 'Wrong event period')
    expected_events = {(m, s, t, ev) for m in MODELS for s in SSPS for t in TECHS for ev in EVENTS[t]}
    require(set(e[['model', 'climate_ssp', 'tech', 'event']].itertuples(index=False, name=None))
            == expected_events, 'Missing event combination')
    denominator = window[window.snapshot.eq(2050)][
        ['model', 'climate_ssp', 'tech', 'capacity_mw']].rename(columns={'capacity_mw': 'all_capacity_mw'})
    check = e.merge(denominator, on=['model', 'climate_ssp', 'tech'], validate='many_to_one')
    require(np.allclose(check.capacity_mw, check.all_capacity_mw), 'Event denominator differs from all valid capacity')
    event_path = OUTPUT / 'event_summary/window.csv.gz'
    chunks = []
    for part in pd.read_csv(event_path, chunksize=50000):
        chunks.append(part[part.country.eq('GLOBAL') & part.snapshot.eq(2050) &
                           part.climate_ssp.eq('ssp126') & part.station_ssp.eq('ssp126') &
                           part.event.ne('all')])
    exposure = pd.concat(chunks, ignore_index=True)
    require(len(exposure) == 44 and np.isfinite(exposure.E).all(), 'Incomplete ordering exposure')
    require(not exposure.duplicated(['model', 'tech', 'event']).any(), 'Duplicate ordering exposure')
    order = {}
    for tech in TECHS:
        g = exposure[exposure.tech.eq(tech)].groupby('event', as_index=False).E.mean()
        order[tech] = g.sort_values(['E', 'event'], ascending=[False, True]).event.tolist()
        require(set(order[tech]) == set(EVENTS[tech]), 'Ordering event mismatch')
    refs_path = OUTPUT / 'catalogues/capacity_by_country.csv'
    refs = pd.read_csv(refs_path).groupby(['station_ssp', 'tech', 'snapshot']).capacity_mw.sum()
    coverage = window.copy()
    coverage['catalogue_capacity_mw'] = [
        refs.loc[(r.station_ssp, r.tech, r.snapshot)] for r in coverage.itertuples()]
    coverage['capacity_coverage_pct'] = 100 * coverage.capacity_mw / coverage.catalogue_capacity_mw
    require(coverage.capacity_coverage_pct.between(0, 100 + 1e-8).all(), 'Invalid capacity coverage')
    annual_display = ensemble(a, ['tech', 'climate_ssp', 'snapshot', 'year'], 'R')
    contrast_display = ensemble(contrasts, ['tech', 'climate_ssp', 'snapshot'], 'difference')
    event_display = ensemble(e, ['tech', 'climate_ssp', 'event'], 'R')
    event_display['row'] = [order[r.tech].index(r.event) for r in event_display.itertuples()]
    for t in [annual_display, contrast_display, event_display]:
        require(t.n_models.eq(4).all() and t['mean'].notna().all(), 'Ensemble incomplete')
        t['units'] = UNIT
    for name, table in {
        'panel_ab_display.csv': annual_display, 'panel_cd_models.csv': contrasts,
        'panel_cd_display.csv': contrast_display, 'panel_ef_display.csv': event_display,
        'panel_ef_ordering.csv': exposure, 'capacity_coverage.csv': coverage}.items():
        write_csv(SOURCE / name, table)
    inputs = [SOURCE / n for n in ['panel_ab.csv', 'panel_cd.csv', 'panel_ef.csv']]
    inputs += [event_path, refs_path, final_path]
    result = {
        'status': 'PASSED', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'input_rows': {'ab': len(a), 'cd': len(c), 'ef': len(e)},
        'display_rows': {'ab': len(annual_display), 'cd': len(contrast_display), 'ef': len(event_display)},
        'checks': ['664 accepted units', 'full model/pathway/year/event coverage', 'unique records',
                   'signed energy divided by common capacity', 'fixed capacity within snapshot',
                   'ten-year means and within-model paired differences', 'event denominators equal all valid capacity',
                   'Fig. 1 exposure-based event order', 'four-model equal weighting', 'catalogue capacity coverage'],
        'event_order': order, 'capacity_coverage_pct': [float(coverage.capacity_coverage_pct.min()),
                                                       float(coverage.capacity_coverage_pct.max())],
        'negative_event_model_values': int(e.R.lt(0).sum()), 'zero_event_model_values': int(e.R.eq(0).sum()),
        'input_sha256': {str(p.relative_to(ROOT)): digest(p) for p in inputs},
        'support': 'Common finite annual fields across climates, models, events and ten years within each deployment snapshot',
        'limitation': 'Annual Loss validity does not establish identical valid three-hourly timestamps',
        'units': UNIT, 'wind_energy_scale': 1,
    }
    write_json(OUT / 'data_audit.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return annual_display, contrasts, contrast_display, event_display, order




def main():
    a, contrasts, contrast_display, event_display, order = audit()
    path = OUTPUT / 'loss_summary/window.csv.gz'
    parts = []
    for part in pd.read_csv(path, chunksize=50000):
        parts.append(part[part.country.eq('GLOBAL') & part.support.eq('common') &
                          part.climate_ssp.eq(part.station_ssp)])
    windows = pd.concat(parts, ignore_index=True)
    keys = ['model', 'climate_ssp', 'station_ssp', 'tech', 'snapshot', 'event']
    expected = {(m, s, s, t, y, ev) for m in MODELS for s in SSPS
                for t in TECHS for y in SNAPSHOTS for ev in ('all', *EVENTS[t])}
    require(not windows.duplicated(keys).any(), 'Duplicate window')
    require(set(windows[keys].itertuples(index=False, name=None)) == expected,
            'Incomplete global paired windows')
    require(np.isfinite(windows[['R', 'net_mwh', 'capacity_event_hours', 'capacity_mw']]).all().all(),
            'Missing window inputs')
    require(windows.capacity_mw.gt(0).all(), 'Non-positive capacity')
    require(np.allclose(windows.R, windows.net_mwh / windows.capacity_mw), 'Window normalization')
    annual = pd.read_csv(SOURCE / 'panel_ab.csv')
    mean = annual.groupby(keys, as_index=False)[['R', 'net_mwh', 'capacity_event_hours', 'capacity_mw']].mean()
    union = windows[windows.event.eq('all')].copy()
    check = union.merge(mean, on=keys, suffixes=('', '_annual'), validate='one_to_one')
    for col in ['R', 'net_mwh', 'capacity_event_hours', 'capacity_mw']:
        require(np.allclose(check[col], check[col + '_annual'], rtol=1e-10, atol=1e-9),
                'Annual/window mismatch: ' + col)
    require(union.capacity_event_hours.gt(0).all(), 'Non-positive union exposure')
    union['E_days_per_year'] = union.capacity_event_hours / union.capacity_mw / 24
    union['I_mwh_per_mw_day'] = union.net_mwh / union.capacity_event_hours * 24
    require(np.allclose(union.R, union.E_days_per_year * union.I_mwh_per_mw_day),
            'R = E times I failed')
    records = []
    for (model, tech, snapshot), block in union.groupby(['model', 'tech', 'snapshot']):
        block = block.set_index('climate_ssp')
        base, target = block.loc['ssp126'], block.loc['ssp585']
        exposure = (target.E_days_per_year - base.E_days_per_year) * (
            target.I_mwh_per_mw_day + base.I_mwh_per_mw_day) / 2
        intensity = (target.I_mwh_per_mw_day - base.I_mwh_per_mw_day) * (
            target.E_days_per_year + base.E_days_per_year) / 2
        gap = target.R - base.R
        records.append(dict(model=model, tech=tech, snapshot=snapshot,
                            baseline_climate_ssp='ssp126', baseline_station_ssp='ssp126',
                            target_climate_ssp='ssp585', target_station_ssp='ssp585',
                            baseline_R=base.R, target_R=target.R,
                            baseline_E_days=base.E_days_per_year, target_E_days=target.E_days_per_year,
                            baseline_I=base.I_mwh_per_mw_day, target_I=target.I_mwh_per_mw_day,
                            baseline_capacity_mw=base.capacity_mw, target_capacity_mw=target.capacity_mw,
                            exposure=exposure, intensity=intensity, gap=gap,
                            closure=exposure + intensity - gap, units=UNIT))
    decomposition = pd.DataFrame(records)
    require(decomposition.closure.abs().max() < 1e-9, 'Two-factor closure')
    display = pd.concat([ensemble(decomposition, ['tech', 'snapshot'], term).assign(term=term)
                         for term in ['exposure', 'intensity', 'gap']], ignore_index=True)
    d = display.pivot(index=['tech', 'snapshot'], columns='term', values='mean')
    require(np.allclose(d.exposure + d.intensity, d.gap, atol=1e-10), 'Ensemble closure')
    reference = contrasts[contrasts.climate_ssp.eq('ssp585')][['model', 'tech', 'snapshot', 'difference']]
    check = decomposition.merge(reference, on=['model', 'tech', 'snapshot'], validate='one_to_one')
    require(np.allclose(check.gap, check.difference, atol=1e-10), 'Waterfall gap differs from paired contrast')
    events = windows[windows.event.ne('all')].copy()
    event_summary = ensemble(events, ['tech', 'climate_ssp', 'snapshot', 'event'], 'R')
    require(event_summary.n_models.eq(4).all(), 'Incomplete event ensemble')
    denom = union[['model', 'climate_ssp', 'tech', 'snapshot', 'capacity_mw']].rename(
        columns={'capacity_mw': 'union_capacity_mw'})
    check = events.merge(denom, on=['model', 'climate_ssp', 'tech', 'snapshot'], validate='many_to_one')
    require(np.allclose(check.capacity_mw, check.union_capacity_mw), 'Event/union capacity mismatch')
    reference = pd.read_csv(SOURCE / 'panel_ef.csv').set_index(keys).sort_index()
    current = events[events.snapshot.eq(2050)].set_index(keys).sort_index()
    require(reference.index.equals(current.index) and np.allclose(reference.R, current.R),
            '2050s events differ from archived panel')
    trends = []
    for (tech, ssp), block in a.groupby(['tech', 'climate_ssp']):
        block = block.sort_values('year')
        require(np.array_equal(block.year, np.arange(2030, 2060)), 'Incomplete trend years')
        slope, intercept = np.polyfit(block.year, block['mean'], 1)
        trends.append(dict(tech=tech, climate_ssp=ssp, slope=slope, intercept=intercept,
                           start_year=2030, end_year=2059, n_years=30,
                           slope_units='MWh MW-1 yr-2'))
    for name, table in {
        'global_window_models.csv': windows, 'union_factors_models.csv': union,
        'two_factor_models.csv': decomposition, 'two_factor_display.csv': display,
        'event_composition_models.csv': events, 'event_composition_display.csv': event_summary,
        'annual_trends.csv': pd.DataFrame(trends)}.items():
        write_csv(SOURCE / name, table)
    supplement = ROOT / 'paper_figures/supplementary/fig_s12_global_loss_contrasts/outputs'
    for name, table in {
        'panel_ab_models.csv': contrasts, 'panel_ab_display.csv': contrast_display,
        'panel_cd_models.csv': pd.read_csv(SOURCE / 'panel_ef.csv'),
        'panel_cd_display.csv': event_display, 'capacity_coverage.csv': pd.read_csv(SOURCE / 'capacity_coverage.csv')
    }.items():
        write_csv(supplement / 'source_data' / name, table)
    result = json.loads((OUT / 'data_audit.json').read_text())
    result['input_sha256'][str(path.relative_to(ROOT))] = digest(path)
    result['two_factor_max_closure'] = float(decomposition.closure.abs().max())
    result['new_source_rows'] = {'windows': len(windows), 'decomposition': len(decomposition),
                                 'event_models': len(events), 'event_display': len(event_summary)}
    result['negative_event_means'] = event_summary[event_summary['mean'].lt(0)].to_dict('records')
    result['negative_event_model_count_all_decades'] = int(events.R.lt(0).sum())
    result['checks'] += ['global 3-decade event matrix', 'annual/window union agreement',
                         'R = E times I', 'exact model and ensemble two-factor closure',
                         'waterfall gap equals archived paired contrast', 'event/union capacity equality',
                         'archived 2050s event reproduction', '30-year least-squares trends']
    result['supplementary_migration'] = 'Fig. S12: original Fig. 2 c-d -> a-b; e-f -> c-d'
    write_json(OUT / 'data_audit.json', result)
    write_json(supplement / 'data_audit.json', {
        'status': 'PASSED', 'source_audit': str((OUT / 'data_audit.json').relative_to(ROOT)),
        'source_audit_sha256': digest(OUT / 'data_audit.json'), 'event_order': order,
        'source_data_sha256': {p.name: digest(p) for p in sorted((supplement / 'source_data').glob('*.csv'))}})
    print(json.dumps({'status': result['status'], 'rows': result['new_source_rows'],
                      'closure': result['two_factor_max_closure'],
                      'negative_event_means': result['negative_event_means']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
