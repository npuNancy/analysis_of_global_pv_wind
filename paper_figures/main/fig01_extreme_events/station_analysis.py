"""Station exposure: paired-path trends, climate/deployment attribution and layout shift-share.

Exposure is the capacity-weighted annual event duration on the Loss common stations (h/yr, shown in
days/yr). Paired paths are the climate = deployment diagonal. The deployment contribution is split per
country into a between-country capacity-share term and a within-country term; both use the two
climates of each contrast symmetrically, so the country terms add up exactly to Phi_S.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import MODELS, SSPS, EVENTS, SNAPSHOTS, OUTPUT, SSP_COLORS
from paper_figures.common.io import write_csv, write_json
from paper_figures.main.fig01_extreme_events.meeting_common import OUT
from paper_figures.main.fig01_extreme_events import meeting_plotting as P

EVENT_LABELS = {'all': 'All events (union)', 'high_temp': 'High temperature', 'high_wind': 'High wind',
                'hot_humid': 'Hot-humid', 'icing': 'Icing', 'low_resource': 'Low resource',
                'cold_highwind': 'Cold high wind', 'freezing_rain': 'Freezing rain',
                'high_humidity': 'High humidity', 'rainstorm': 'Rainstorm'}
PAIRS = (('ssp585', 'ssp126'), ('ssp245', 'ssp126'), ('ssp245', 'ssp585'))
LAYOUT_CASES = (('wind', 'ssp585', 'ssp126'), ('solar', 'ssp585', 'ssp126'), ('solar', 'ssp245', 'ssp126'), ('solar', 'ssp245', 'ssp585'))
HOURS_PER_DAY = 24


def decompose(cell, a, b):
    """Symmetric climate/deployment split of cell[(a,a)] - cell[(b,b)]; cell maps (climate, deploy)."""
    phi_c = 0.5 * ((cell[(a, b)] - cell[(b, b)]) + (cell[(a, a)] - cell[(b, a)]))
    phi_s = 0.5 * ((cell[(b, a)] - cell[(b, b)]) + (cell[(a, a)] - cell[(a, b)]))
    return cell[(a, a)] - cell[(b, b)], phi_c, phi_s


def trends(annual):
    paired = annual[annual.climate_ssp == annual.station_ssp].copy()
    paired['days'] = paired.E / HOURS_PER_DAY
    rows = []
    for (tech, event, ssp, model), g in paired.groupby(['tech', 'event', 'station_ssp', 'model']):
        g = g.sort_values('year')
        slope = np.polyfit(g.year, g.days, 1)[0] * 10
        rows.append(dict(tech=tech, event=event, ssp=ssp, model=model, slope_days_per_decade=slope))
    slopes = pd.DataFrame(rows)
    summary = slopes.groupby(['tech', 'event', 'ssp']).slope_days_per_decade.agg(['mean', 'min', 'max']).reset_index()
    summary['support'] = [P.support(slopes[(slopes.tech == r.tech) & (slopes.event == r.event) & (slopes.ssp == r.ssp)]
                                    .slope_days_per_decade) for r in summary.itertuples()]
    return paired, slopes, summary


def attribution(window):
    glob = window[window.country == 'GLOBAL']
    rows = []
    for (model, tech, snap, event), g in glob.groupby(['model', 'tech', 'snapshot', 'event']):
        cell = {(r.climate_ssp, r.station_ssp): r.E / HOURS_PER_DAY for r in g.itertuples()}
        if len(cell) != 9:
            raise ValueError(f'Incomplete cross matrix: {model} {tech} {snap} {event}')
        for a, b in PAIRS:
            d, pc, ps = decompose(cell, a, b)
            rows.append(dict(model=model, tech=tech, snapshot=snap, event=event, pair=f'{a}-{b}',
                             D=d, Phi_C=pc, Phi_S=ps, E_a=cell[(a, a)], E_b=cell[(b, b)]))
    per_model = pd.DataFrame(rows)
    ens = per_model.groupby(['tech', 'snapshot', 'event', 'pair'])[['D', 'Phi_C', 'Phi_S', 'E_a', 'E_b']].mean().reset_index()
    for k in ('D', 'Phi_C', 'Phi_S'):
        ens[f'{k}_support'] = [P.support(per_model[(per_model.tech == r.tech) & (per_model.snapshot == r.snapshot)
                                                   & (per_model.event == r.event) & (per_model.pair == r.pair)][k])
                               for r in ens.itertuples()]
    return per_model, ens


def ordering(window):
    glob = window[(window.country == 'GLOBAL') & (window.event == 'all') & (window.climate_ssp == window.station_ssp)]
    rows = []
    for (tech, snap), g in glob.groupby(['tech', 'snapshot']):
        piv = g.pivot(index='model', columns='station_ssp', values='E') / HOURS_PER_DAY
        order = piv.mean().sort_values(ascending=False).index.tolist()
        agree = int(sum(all(piv.loc[m, order[i]] > piv.loc[m, order[i + 1]] for i in range(2)) for m in piv.index))
        rows.append(dict(tech=tech, snapshot=snap, order=' > '.join(order), models_with_same_order=agree,
                         **{f'{s}_days': piv[s].mean() for s in SSPS}))
    return pd.DataFrame(rows)


def shift_share(window, tech, a, b, snapshot=2050):
    """Country terms of Phi_S for deployment a vs b, averaged over climates a and b."""
    w = window[(window.tech == tech) & (window.snapshot == snapshot) & (window.event == 'all')
               & (window.country != 'GLOBAL') & window.station_ssp.isin([a, b]) & window.climate_ssp.isin([a, b])]
    rows = []
    for (model, climate), g in w.groupby(['model', 'climate_ssp']):
        piv = g.pivot(index='country', columns='station_ssp', values=['capacity_mw', 'E'])
        cap = piv['capacity_mw'].reindex(columns=[b, a]).fillna(0)
        share = cap / cap.sum()
        e = piv['E'].reindex(columns=[b, a]) / HOURS_PER_DAY
        e_mean = e.mean(axis=1)
        between = (share[a] - share[b]) * e_mean
        within = (0.5 * (share[a] + share[b]) * (e[a] - e[b])).fillna(0)
        total = (share[a] * e[a].fillna(0)).sum() - (share[b] * e[b].fillna(0)).sum()
        e_global = 0.5 * ((share[a] * e[a].fillna(0)).sum() + (share[b] * e[b].fillna(0)).sum())
        between_centered = (share[a] - share[b]) * (e_mean - e_global)
        if not np.isclose(between.sum() + within.sum(), total, rtol=0, atol=1e-9):
            raise ValueError('Shift-share closure failed')
        for k in piv.index:
            rows.append(dict(model=model, climate=climate, country=k, share_b=share.at[k, b], share_a=share.at[k, a],
                             E_b=e.at[k, b], E_a=e.at[k, a], between=between_centered[k], within=within[k],
                             cap_a_mw=cap.at[k, a], cap_b_mw=cap.at[k, b]))
    per = pd.DataFrame(rows)
    avg = per.groupby(['model', 'country'])[['share_b', 'share_a', 'E_b', 'E_a', 'between', 'within', 'cap_a_mw', 'cap_b_mw']].mean().reset_index()
    avg['total'] = avg.between + avg.within
    ens = avg.groupby('country')[['share_b', 'share_a', 'E_b', 'E_a', 'between', 'within', 'total', 'cap_a_mw', 'cap_b_mw']].mean()
    ens['support'] = avg.groupby('country').total.apply(lambda v: P.support(v))
    ens = ens.reset_index().assign(tech=tech, pair=f'{a}-{b}', snapshot=snapshot)
    model_totals = avg.groupby('model')[['between', 'within', 'total']].sum().reset_index().assign(tech=tech, pair=f'{a}-{b}')
    return ens, model_totals


def plot_trends(paired, tech, folder):
    import matplotlib.pyplot as plt
    events = ['all', *EVENTS[tech]]
    ncol = 3 if tech == 'wind' else 4
    nrow = int(np.ceil(len(events) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(183 * P.MM, 50 * P.MM * nrow), squeeze=False)
    groups = {}
    for i, event in enumerate(events):
        ax = axes.flat[i]
        g = paired[(paired.tech == tech) & (paired.event == event)]
        for ssp in SSPS:
            piv = g[g.station_ssp == ssp].pivot(index='year', columns='model', values='days')
            P.model_band(ax, piv.index, piv, ssp)
        for x in (2039.5, 2049.5):
            ax.axvline(x, color='0.6', lw=0.5, ls=':')
        ax.set_title(EVENT_LABELS[event], loc='left')
        ax.set_xlim(2030, 2059)
        if i % ncol == 0:
            ax.set_ylabel('Exposure (days yr$^{-1}$)')
        letter = chr(97 + i)
        P.panel_letter(ax, letter)
        groups[letter] = [ax]
    for ax in axes.flat[len(events):]:
        ax.axis('off')
    axes.flat[0].legend(loc='upper left', ncol=1)
    fig.suptitle(f'{tech.capitalize()} stations: capacity-weighted exposure on paired climate-deployment paths '
                 '(dotted lines: switch to the 2040 and 2050 capacity snapshots)', x=0.01, ha='left', fontsize=7)
    fig.tight_layout()
    P.export(fig, folder, f'station_trends_{tech}', groups,
             dict(unit='days per year (24 h)', shading='four-model min-max', mean='equal-weight four-model mean'))


def plot_attribution(window, per_model, ens, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(183 * P.MM, 110 * P.MM), gridspec_kw=dict(width_ratios=[1, 1.15, 1.15]))
    groups = {}
    labels = [P.SSP_LABELS[s] for s in SSPS]
    for row, tech in enumerate(('wind', 'solar')):
        g = window[(window.country == 'GLOBAL') & (window.event == 'all') & (window.tech == tech) & (window.snapshot == 2050)]
        mat = (g.groupby(['station_ssp', 'climate_ssp']).E.mean() / HOURS_PER_DAY).unstack().reindex(index=SSPS, columns=SSPS)
        ax = axes[row, 0]
        im = ax.imshow(mat.values, cmap='YlOrBr', origin='lower')
        for i in range(3):
            for j in range(3):
                dark = mat.values[i, j] > np.nanmin(mat.values) + 0.6 * np.ptp(mat.values)
                ax.text(j, i, f'{mat.values[i, j]:.1f}', ha='center', va='center', fontsize=6,
                        color='white' if dark else 'black', fontweight='bold' if i == j else 'normal')
            ax.add_patch(plt.Rectangle((i - .5, i - .5), 1, 1, fill=False, lw=1.0, ec='k'))
        ax.set_xticks(range(3), labels); ax.set_yticks(range(3), labels)
        ax.set_xlabel('Climate pathway'); ax.set_ylabel('Deployment pathway')
        ax.spines[:].set_visible(True)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03); cb.set_label('2050s exposure (days yr$^{-1}$)')
        P.attach(ax, cb.ax)
        ax.set_title(f'{tech.capitalize()}: climate x deployment, 2050s', loc='left')
        # pair contrasts 2050s
        ax = axes[row, 1]
        for k, pair in enumerate(f'{a}-{b}' for a, b in PAIRS):
            e = ens[(ens.tech == tech) & (ens.snapshot == 2050) & (ens.event == 'all') & (ens.pair == pair)].iloc[0]
            pm = per_model[(per_model.tech == tech) & (per_model.snapshot == 2050) & (per_model.event == 'all') & (per_model.pair == pair)]
            for off, key, color in ((-0.18, 'Phi_C', P.CLIMATE_COLOR), (0.18, 'Phi_S', P.DEPLOY_COLOR)):
                ax.bar(k + off, e[key], width=0.34, color=color, label=('Climate' if key == 'Phi_C' else 'Deployment') if k == 0 else None)
                ax.scatter(np.full(len(pm), k + off), pm[key], s=5, color='k', zorder=3, lw=0)
            ax.scatter(k, e['D'], marker='D', s=18, color=P.NET_COLOR, zorder=4, label='Net paired difference' if k == 0 else None)
        ax.axhline(0, color='k', lw=0.5)
        ax.set_xticks(range(3), ['585 - 126', '245 - 126', '245 - 585'])
        ax.set_ylabel('Contribution (days yr$^{-1}$)')
        ax.set_title('Paired-path difference, 2050s', loc='left')
        lo, hi = ax.get_ylim(); ax.set_ylim(lo, hi + 0.45 * (hi - lo))
        ax.legend(loc='upper right', fontsize=5.5)
        ax = axes[row, 2]
        for k, snap in enumerate(SNAPSHOTS):
            for pair_i, (pair, shift) in enumerate((('ssp585-ssp126', -0.22), ('ssp245-ssp126', 0.22))):
                e = ens[(ens.tech == tech) & (ens.snapshot == snap) & (ens.event == 'all') & (ens.pair == pair)].iloc[0]
                x = k + shift
                ax.bar(x - 0.09, e['Phi_C'], width=0.17, color=P.CLIMATE_COLOR)
                ax.bar(x + 0.09, e['Phi_S'], width=0.17, color=P.DEPLOY_COLOR)
                ax.scatter(x, e['D'], marker='D', s=14, color=P.NET_COLOR, zorder=4)
                ax.text(x, -0.02, '585' if pair_i == 0 else '245', transform=ax.get_xaxis_transform(),
                        ha='center', va='top', fontsize=5)
        ax.axhline(0, color='k', lw=0.5)
        ax.set_xticks(range(3), ['2030s', '2040s', '2050s']); ax.tick_params(axis='x', pad=8)
        ax.set_ylabel('Contribution (days yr$^{-1}$)')
        ax.set_title('Difference from SSP1-2.6 by decade', loc='left')
        for c, ax in enumerate(axes[row]):
            letter = chr(97 + row * 3 + c); P.panel_letter(ax, letter, x=-0.22)
        groups[chr(97 + row * 3) + chr(98 + row * 3) + chr(99 + row * 3)] = list(axes[row])
    fig.tight_layout()
    P.export(fig, folder, 'station_attribution', groups,
             dict(decomposition='symmetric: Phi_C and Phi_S average the two fixed-deployment and two fixed-climate differences',
                  dots='individual models', diamond='four-model mean paired difference'))


def plot_layout(layout, folder, names):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(LAYOUT_CASES), 2, figsize=(183 * P.MM, 62 * P.MM * len(LAYOUT_CASES)),
                             gridspec_kw=dict(width_ratios=[1.1, 1]))
    groups = {}
    for row, (tech, a, b) in enumerate(LAYOUT_CASES):
        d = layout[(layout.tech == tech) & (layout.pair == f'{a}-{b}')].copy()
        d = d[~d.country.isin(['UNASSIGNED', 'AMBIGUOUS'])]
        d['dshare'] = (d.share_a - d.share_b) * 100
        d['E_mean'] = d[['E_a', 'E_b']].mean(axis=1)
        ax = axes[row, 0]
        size = (d[['cap_a_mw', 'cap_b_mw']].max(axis=1) / 1e3).clip(lower=1)
        colors = np.where(d.total < 0, '#2166ac', '#b2182b')
        ax.scatter(d.E_mean, d.dshare, s=size / size.max() * 300, c=colors, alpha=0.55, lw=0.3, edgecolor='k')
        e_glob = np.nansum(0.5 * (d.share_a + d.share_b) * d.E_mean) / np.nansum(0.5 * (d.share_a + d.share_b))
        ax.axhline(0, color='k', lw=0.5); ax.axvline(e_glob, color='0.4', lw=0.6, ls='--')
        for r in d.reindex(d.total.abs().sort_values(ascending=False).index).head(7).itertuples():
            ax.annotate(names.get(r.country, r.country), (r.E_mean, r.dshare), fontsize=5, xytext=(3, 2), textcoords='offset points')
        ax.set_xlabel('Country exposure, mean of the two deployments (days yr$^{-1}$)')
        ax.set_ylabel(f'Capacity-share change, {P.SSP_LABELS[a]} - {P.SSP_LABELS[b]} (pp)')
        ax.set_title(f'{tech.capitalize()} {P.SSP_LABELS[a]} vs {P.SSP_LABELS[b]} deployment, 2050 snapshot', loc='left')
        ax = axes[row, 1]
        top = d.reindex(d.total.abs().sort_values(ascending=False).index).head(10).iloc[::-1]
        y = np.arange(len(top))
        ax.barh(y, top.between, color='#7f7f7f', height=0.7, label='Capacity-share shift between countries')
        ax.barh(y, top.within, left=np.where(np.sign(top.within) == np.sign(top.between), top.between, 0), color=P.DEPLOY_COLOR,
                height=0.7, label='Within-country layout')
        ax.scatter(top.total, y, marker='D', s=10, color='k', zorder=3, label='Country total')
        ax.set_yticks(y, [f"{names.get(c, c)} ({s}/4)" for c, s in zip(top.country, top.support)])
        ax.axvline(0, color='k', lw=0.5)
        total = layout[(layout.tech == tech) & (layout.pair == f'{a}-{b}')]
        ax.set_xlabel('Contribution to deployment term (days yr$^{-1}$)')
        ax.set_title(f'Top-10 country contributions (sum of all countries {total.total.sum():+.2f})', loc='left')
        if row == 0:
            lo, hi = ax.get_xlim(); ax.set_xlim(lo, hi + 0.6 * (hi - lo))
            ax.legend(loc='upper right', fontsize=5)
        for c in range(2):
            P.panel_letter(axes[row, c], chr(97 + 2 * row + c), x=-0.2 if c == 0 else -0.45)
        groups[chr(97 + 2 * row) + chr(98 + 2 * row)] = list(axes[row])
    fig.tight_layout()
    P.export(fig, folder, 'station_layout', groups,
             dict(bubble='area proportional to the larger of the two deployments capacities',
                  color='blue: country lowers the global deployment term; red: raises it',
                  between='(share_a - share_b) x (country exposure - global mean exposure)',
                  within='mean share x (country exposure_a - country exposure_b)'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tables', type=Path, default=OUT / 'station_tables')
    p.add_argument('--output', type=Path, default=OUT / 'station_analysis')
    a = p.parse_args()
    P.configure()
    annual = pd.read_csv(a.tables / 'events_annual_global.csv.gz')
    window = pd.read_csv(a.tables / 'events_window.csv.gz')
    names = pd.read_csv(OUTPUT / 'catalogues/countries.csv').set_index('country').name.to_dict()
    src = a.output / 'source_data'
    paired, slopes, slope_summary = trends(annual)
    per_model, ens = attribution(window)
    order = ordering(window)
    layout, totals = zip(*(shift_share(window, *case) for case in LAYOUT_CASES))
    layout = pd.concat(layout, ignore_index=True); totals = pd.concat(totals, ignore_index=True)
    write_csv(src / 'paired_annual_exposure.csv.gz', paired[['model', 'tech', 'station_ssp', 'snapshot', 'year', 'event', 'days']])
    write_csv(src / 'paired_trend_slopes.csv', slopes); write_csv(src / 'paired_trend_summary.csv', slope_summary)
    write_csv(src / 'attribution_models.csv', per_model); write_csv(src / 'attribution_ensemble.csv', ens)
    write_csv(src / 'paired_ordering.csv', order)
    write_csv(src / 'layout_country_terms.csv', layout); write_csv(src / 'layout_model_totals.csv', totals)
    for tech in ('wind', 'solar'):
        plot_trends(paired, tech, a.output)
    plot_attribution(window, per_model, ens, a.output)
    plot_layout(layout, a.output, names)
    pd.set_option('display.width', 200)
    print(order.round(3).to_string())
    print(ens[(ens.event == 'all')].round(3).to_string())
    print(slope_summary[slope_summary.event == 'all'].round(3).to_string())
    print(totals.groupby(['tech', 'pair'])[['between', 'within', 'total']].agg(['mean', 'min', 'max']).round(3).to_string())


if __name__ == '__main__':
    main()
