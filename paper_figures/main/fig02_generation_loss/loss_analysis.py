"""Loss scale, three-factor mechanism, event composition and deployment-optimisable countries.

R = E x CF_ev x r_ev holds for each model and cell (E: capacity-weighted event hours per year,
CF_ev: normal-CF during events, r_ev: net loss / normal generation during events). Differences are
split with the logarithmic-mean (LMDI) identity, which closes exactly when all three factors are
positive. Total loss uses the common-support unit loss times the catalogue capacity of the snapshot.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import SSPS, EVENTS, SNAPSHOTS, OUTPUT, SSP_COLORS
from paper_figures.common.io import write_csv
from paper_figures.main.fig02_generation_loss.meeting_common import OUT, WINDOWS
from paper_figures.main.fig02_generation_loss import meeting_plotting as P
from paper_figures.main.fig01_extreme_events.station_analysis import decompose, EVENT_LABELS

MWH_PER_TWH = 1e6
MW_PER_TW = 1e6
FACTORS = (('E_loss', 'Exposure hours'), ('cf_event', 'Event-period normal CF'), ('r_event', 'Event loss ratio'))
NON_COUNTRIES = ('GLOBAL', 'UNASSIGNED', 'AMBIGUOUS')
CONTRASTS = {'paired 585-126': (('ssp585', 'ssp585'), ('ssp126', 'ssp126')),
             'climate | deploy 126': (('ssp585', 'ssp126'), ('ssp126', 'ssp126')),
             'climate | deploy 585': (('ssp585', 'ssp585'), ('ssp126', 'ssp585')),
             'deploy | climate 126': (('ssp126', 'ssp585'), ('ssp126', 'ssp126')),
             'deploy | climate 585': (('ssp585', 'ssp585'), ('ssp585', 'ssp126'))}


def logmean(a, b):
    return np.where(np.isclose(a, b), a, (a - b) / (np.log(a) - np.log(b)))


def lmdi(row_a, row_b):
    weight = logmean(row_a['R'], row_b['R'])
    return {k: float(weight * np.log(row_a[k] / row_b[k])) for k, _ in FACTORS}


def capacity_tables(window):
    cap = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv')
    catalogue = cap.groupby(['tech', 'station_ssp', 'snapshot']).capacity_mw.sum().rename('catalogue_mw').reset_index()
    glob = window[(window.country == 'GLOBAL') & (window.event == 'all')]
    cov = glob.merge(catalogue, on=['tech', 'station_ssp', 'snapshot'])
    cov['coverage'] = cov.capacity_mw / cov.catalogue_mw
    return catalogue, cov


def total_loss(annual, catalogue):
    g = annual[(annual.event == 'all') & (annual.climate_ssp == annual.station_ssp)].merge(
        catalogue, on=['tech', 'station_ssp', 'snapshot'])
    g['total_TWh'] = g.R * g.catalogue_mw / MWH_PER_TWH
    return g[['model', 'tech', 'station_ssp', 'snapshot', 'year', 'R', 'catalogue_mw', 'capacity_mw', 'total_TWh']]


def scale_intensity(window, catalogue):
    """Total-loss change between snapshots split into capacity scale and unit-loss intensity."""
    g = window[(window.country == 'GLOBAL') & (window.event == 'all') & (window.climate_ssp == window.station_ssp)]
    g = g.merge(catalogue, on=['tech', 'station_ssp', 'snapshot'])
    rows = []
    for (model, tech, ssp), x in g.groupby(['model', 'tech', 'station_ssp']):
        x = x.set_index('snapshot')
        for s0, s1 in ((2030, 2040), (2040, 2050), (2030, 2050)):
            c0, c1, r0, r1 = x.catalogue_mw[s0], x.catalogue_mw[s1], x.R[s0], x.R[s1]
            rows.append(dict(model=model, tech=tech, ssp=ssp, start=s0, end=s1,
                             dL_TWh=(c1 * r1 - c0 * r0) / MWH_PER_TWH, scale_TWh=(c1 - c0) * (r1 + r0) / 2 / MWH_PER_TWH,
                             intensity_TWh=(r1 - r0) * (c1 + c0) / 2 / MWH_PER_TWH, R0=r0, R1=r1, C0_TW=c0 / MW_PER_TW, C1_TW=c1 / MW_PER_TW))
    return pd.DataFrame(rows)


def three_factor(window):
    rows = []
    g = window[(window.country == 'GLOBAL')]
    for (model, tech, snap, event), x in g.groupby(['model', 'tech', 'snapshot', 'event']):
        cell = {(r.climate_ssp, r.station_ssp): r._asdict() for r in x.itertuples()}
        for name, (a, b) in CONTRASTS.items():
            ra, rb = cell[a], cell[b]
            if min(ra['R'], rb['R'], ra['r_event'], rb['r_event']) <= 0:
                continue
            terms = lmdi(ra, rb)
            rows.append(dict(model=model, tech=tech, snapshot=snap, event=event, contrast=name, dR=ra['R'] - rb['R'],
                             **{f'psi_{k}': v for k, v in terms.items()},
                             **{f'{k}_a': ra[k] for k, _ in FACTORS}, **{f'{k}_b': rb[k] for k, _ in FACTORS},
                             R_a=ra['R'], R_b=rb['R']))
    per = pd.DataFrame(rows)
    per['closure'] = per.dR - per[[f'psi_{k}' for k, _ in FACTORS]].sum(axis=1)
    if per.closure.abs().max() > 1e-8:
        raise ValueError('LMDI closure failed')
    cols = ['dR', *[f'psi_{k}' for k, _ in FACTORS], *[f'{k}_{s}' for k, _ in FACTORS for s in 'ab'], 'R_a', 'R_b']
    ens = per.groupby(['tech', 'snapshot', 'event', 'contrast'])[cols].mean().reset_index()
    for k in ['dR', *[f'psi_{k}' for k, _ in FACTORS]]:
        ens[f'{k}_support'] = per.groupby(['tech', 'snapshot', 'event', 'contrast'])[k].apply(P.support).values
    return per, ens


def event_composition(window):
    g = window[window.country == 'GLOBAL'].copy()
    g['normal_annual_per_mw'] = g.normal_annual_mwh / g.capacity_mw
    cols = ['R', 'E_loss', 'cf_event', 'r_event', 'annual_loss_pct', 'normal_annual_per_mw']
    ens = g.groupby(['tech', 'snapshot', 'climate_ssp', 'station_ssp', 'event'])[cols].agg(['mean', 'min', 'max'])
    ens.columns = [f'{a}_{b}' for a, b in ens.columns]
    ens = ens.reset_index()
    ens['paired'] = ens.climate_ssp == ens.station_ssp
    return ens


def optimisable(window):
    """Countries where SSP1-2.6 loses more than SSP5-8.5 and the gap comes from deployment."""
    rows = []
    g = window[(window.event == 'all') & ~window.country.isin(NON_COUNTRIES)]
    for (model, tech, snap, country), x in g.groupby(['model', 'tech', 'snapshot', 'country']):
        cell = {(r.climate_ssp, r.station_ssp): r.R for r in x.itertuples()}
        need = [(c, s) for c in ('ssp126', 'ssp585') for s in ('ssp126', 'ssp585')]
        if any(k not in cell for k in need):
            continue
        d, pc, ps = decompose(cell, 'ssp585', 'ssp126')
        rows.append(dict(model=model, tech=tech, snapshot=snap, country=country, D=d, Phi_C=pc, Phi_S=ps,
                         delta_S_126=cell[('ssp126', 'ssp585')] - cell[('ssp126', 'ssp126')],
                         R126=cell[('ssp126', 'ssp126')], R585=cell[('ssp585', 'ssp585')]))
    per = pd.DataFrame(rows)
    per['criterion'] = (per.D < 0) & (per.Phi_S < 0) & (per.Phi_S / per.D >= 0.5)
    per['criterion_direct'] = per.criterion & (per.delta_S_126 < 0)
    agg = per.groupby(['tech', 'snapshot', 'country']).agg(
        D=('D', 'mean'), Phi_C=('Phi_C', 'mean'), Phi_S=('Phi_S', 'mean'), delta_S_126=('delta_S_126', 'mean'),
        R126=('R126', 'mean'), R585=('R585', 'mean'), cap126_mw=('R126', 'size'), cap585_mw=('R585', 'size'),
        models_criterion=('criterion', 'sum'), models_direct=('criterion_direct', 'sum'), n_models=('model', 'nunique')).reset_index()
    cap = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv').pivot_table(
        index=['tech', 'snapshot', 'country'], columns='station_ssp', values='capacity_mw', aggfunc='sum')
    agg = agg.drop(columns=['cap126_mw', 'cap585_mw']).merge(
        cap[['ssp126', 'ssp585']].rename(columns=dict(ssp126='cap126_mw', ssp585='cap585_mw')).reset_index(),
        on=['tech', 'snapshot', 'country'], how='left')
    ens_ok = (agg.D < 0) & (agg.Phi_S < 0) & (agg.Phi_S / agg.D >= 0.5)
    agg['class'] = np.select([ens_ok & (agg.models_criterion >= 3) & (agg.delta_S_126 < 0),
                              agg.D < 0], ['optimisable', 'R126>R585, climate-led or not robust'],
                             'R126<=R585')
    agg['saving_TWh'] = np.where(agg['class'] == 'optimisable', -agg.delta_S_126 * agg.cap126_mw / MWH_PER_TWH, 0.0)
    return per, agg


def optimisable_shares(agg, window):
    cap = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv')
    rows = []
    for (tech, snap), x in agg.groupby(['tech', 'snapshot']):
        c126 = cap[(cap.tech == tech) & (cap.snapshot == snap) & (cap.station_ssp == 'ssp126')]
        countries_126 = c126[~c126.country.isin(NON_COUNTRIES) & (c126.capacity_mw > 0)]
        total_cap = countries_126.capacity_mw.sum()
        for cls in ('optimisable', 'R126>R585, climate-led or not robust', 'R126<=R585'):
            sel = x[x['class'] == cls]
            rows.append(dict(tech=tech, snapshot=snap, cls=cls, n=len(sel), n_comparable=len(x),
                             n_with_126_capacity=len(countries_126), share_of_comparable=len(sel) / len(x),
                             cap126_TW=sel.cap126_mw.sum() / MW_PER_TW,
                             cap_share_of_126=sel.cap126_mw.sum() / total_cap, saving_TWh=sel.saving_TWh.sum()))
        rows.append(dict(tech=tech, snapshot=snap, cls='not comparable', n=len(countries_126) - len(x), n_comparable=len(x),
                         n_with_126_capacity=len(countries_126),
                         cap126_TW=(total_cap - x.cap126_mw.sum()) / MW_PER_TW,
                         cap_share_of_126=1 - x.cap126_mw.sum() / total_cap))
    return pd.DataFrame(rows)


def plot_scale(cap_loss, catalogue, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 2, figsize=(183 * P.MM, 150 * P.MM), sharex='col')
    groups = {}
    for col, tech in enumerate(('wind', 'solar')):
        ax = axes[0, col]
        for i, ssp in enumerate(SSPS):
            c = catalogue[(catalogue.tech == tech) & (catalogue.station_ssp == ssp)].sort_values('snapshot')
            for snap, mw in zip(c.snapshot, c.catalogue_mw):
                ax.hlines(mw / MW_PER_TW, snap, snap + 9.8, color=SSP_COLORS[ssp], lw=2, label=P.SSP_LABELS[ssp] if snap == 2030 else None)
                ax.text(snap + 4.9, mw / MW_PER_TW, f'{mw / MW_PER_TW:.2f}', color=SSP_COLORS[ssp], fontsize=5,
                        ha='center', va='bottom')
        ax.set_ylabel('Installed capacity (TW)')
        ax.set_title(f'{tech.capitalize()}: capacity snapshot used in each decade', loc='left')
        ax.legend(loc='upper left')
        for row, (var, label) in enumerate((('total_TWh', 'Total net loss (TWh yr$^{-1}$)'),
                                            ('R', 'Unit net loss (MWh MW$^{-1}$ yr$^{-1}$)')), start=1):
            ax = axes[row, col]
            g = cap_loss[cap_loss.tech == tech]
            for ssp in SSPS:
                piv = g[g.station_ssp == ssp].pivot(index='year', columns='model', values=var)
                P.model_band(ax, piv.index, piv, ssp)
                if var == 'R':
                    years = piv.index.to_numpy(dtype=float)
                    slope, intercept = np.polyfit(years, piv.mean(axis=1).to_numpy(dtype=float), 1)
                    ax.plot(years, slope * years + intercept, '--', color=SSP_COLORS[ssp], lw=1.0, zorder=4)
            for x in (2039.5, 2049.5):
                ax.axvline(x, color='0.6', lw=0.5, ls=':')
            ax.set_ylabel(label)
        axes[2, col].set_xlabel('Year'); axes[2, col].set_xlim(2030, 2060)
        axes[1, col].set_title('Total loss = common-support unit loss x catalogue capacity', loc='left')
        axes[2, col].set_title('Unit loss; dashed: least-squares trend', loc='left')
    for i, ax in enumerate(axes.T.flat):
        P.panel_letter(ax, chr(97 + i), x=-0.13)
    groups = {'abc': list(axes[:, 0]), 'def': list(axes[:, 1])}
    fig.tight_layout()
    P.export(fig, folder, 'capacity_total_loss', groups, dict(
        shading='four-model min-max', paths='paired climate = deployment',
        unit_loss_trend='dashed ordinary least-squares line of the four-model mean, 2030-2059'))


def plot_three_factor(ens, comp, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(183 * P.MM, 108 * P.MM), gridspec_kw=dict(width_ratios=[1.35, 1, 1]))
    colors = dict(E_loss='#8c6bb1', cf_event='#41ab5d', r_event='#ef6548')
    for row, tech in enumerate(('wind', 'solar')):
        ax = axes[row, 0]
        e = ens[(ens.tech == tech) & (ens.snapshot == 2050) & (ens.event == 'all')].set_index('contrast').reindex(list(CONTRASTS))
        y = np.arange(len(e))[::-1]
        for j, (k, label) in enumerate(FACTORS):
            ax.barh(y + (j - 1) * 0.25, e[f'psi_{k}'], height=0.24, color=colors[k], label=label)
        ax.scatter(e.dR, y, marker='D', color='k', s=14, zorder=3, label='Total change in R')
        for yy, r in zip(y, e.itertuples()):
            ax.text(1.01, yy, f'{r.dR:+.1f} ({r.dR_support}/4)', transform=ax.get_yaxis_transform(), fontsize=5, va='center')
        ax.set_yticks(y, list(e.index)); ax.axvline(0, color='k', lw=0.5)
        ax.set_xlabel('Contribution to change in unit loss (MWh MW$^{-1}$ yr$^{-1}$)')
        ax.set_title(f'{tech.capitalize()} 2050s: three factors', loc='left')
        if row == 0:
            ax.legend(loc='upper left', bbox_to_anchor=(0, -0.3), ncol=2, fontsize=5)
        c = comp[(comp.tech == tech) & (comp.snapshot == 2050) & (comp.event != 'all') & comp.paired]
        for j, (var, label) in enumerate((('cf_event_mean', 'Event normal CF'), ('r_event_mean', 'Event loss ratio'))):
            ax = axes[row, 1 + j]
            events = list(EVENTS[tech])
            x = np.arange(len(events))
            for i, ssp in enumerate(SSPS):
                v = c[c.station_ssp == ssp].set_index('event').reindex(events)
                ax.scatter(x + (i - 1) * 0.22, v[var], color=SSP_COLORS[ssp], marker=P.SSP_MARKERS[ssp], s=12, label=P.SSP_LABELS[ssp])
                ax.vlines(x + (i - 1) * 0.22, v[var.replace('mean', 'min')], v[var.replace('mean', 'max')], color=SSP_COLORS[ssp], lw=0.6)
                a = comp[(comp.tech == tech) & (comp.snapshot == 2050) & (comp.event == 'all') & (comp.station_ssp == ssp) & comp.paired][var].iloc[0]
                ax.axhline(a, color=SSP_COLORS[ssp], lw=0.6, ls='--')
            ax.set_xticks(x, [EVENT_LABELS[e] for e in events], rotation=35, ha='right')
            ax.set_ylabel(label)
            ax.set_title('By event type, 2050s (dashed: union)', loc='left', fontsize=6)
            if row == 0 and j == 0:
                ax.legend(loc='best', fontsize=5)
    for i, ax in enumerate(axes.flat):
        P.panel_letter(ax, chr(97 + i), x=-0.3 if i % 3 else -0.32)
    fig.tight_layout()
    P.export(fig, folder, 'three_factor', {'abc': list(axes[0]), 'def': list(axes[1])},
             dict(decomposition='LMDI, exact closure per model', support='models with the same sign as the mean'))


def plot_events(comp, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(183 * P.MM, 100 * P.MM))
    for row, tech in enumerate(('wind', 'solar')):
        c = comp[(comp.tech == tech) & (comp.snapshot == 2050) & (comp.event != 'all') & comp.paired]
        events = list(EVENTS[tech]); x = np.arange(len(events))
        for j, (var, label) in enumerate((('E_loss', 'Exposure (h yr$^{-1}$)'), ('R', 'Unit net loss (MWh MW$^{-1}$ yr$^{-1}$)'))):
            ax = axes[row, j]
            for i, ssp in enumerate(SSPS):
                v = c[c.station_ssp == ssp].set_index('event').reindex(events)
                ax.bar(x + (i - 1) * 0.27, v[f'{var}_mean'], width=0.26, color=SSP_COLORS[ssp], label=P.SSP_LABELS[ssp])
                ax.errorbar(x + (i - 1) * 0.27, v[f'{var}_mean'], yerr=[v[f'{var}_mean'] - v[f'{var}_min'], v[f'{var}_max'] - v[f'{var}_mean']],
                            fmt='none', ecolor='0.25', lw=0.6, capsize=0)
            ax.set_xticks(x, [EVENT_LABELS[e] for e in events], rotation=30, ha='right')
            ax.set_ylabel(label); ax.axhline(0, color='k', lw=0.5)
            ax.set_title(f'{tech.capitalize()} 2050s, paired paths', loc='left')
            if row == 0 and j == 0:
                ax.legend(loc='upper left')
    for i, ax in enumerate(axes.flat):
        P.panel_letter(ax, chr(97 + i), x=-0.17)
    fig.tight_layout()
    P.export(fig, folder, 'event_exposure_loss', {'ab': list(axes[0]), 'cd': list(axes[1])},
             dict(note='event types overlap; per-type values do not add to the union', bars='four-model mean', whiskers='min-max'))


def wind_mechanism(window):
    """Per-model wind 2050s event mix under the four climate x deployment corners of 126 and 585."""
    g = window[(window.country == 'GLOBAL') & (window.tech == 'wind') & (window.snapshot == 2050)
               & window.climate_ssp.isin(['ssp126', 'ssp585']) & window.station_ssp.isin(['ssp126', 'ssp585'])].copy()
    g['normal_annual_per_mw'] = g.normal_annual_mwh / g.capacity_mw
    return g[['model', 'climate_ssp', 'station_ssp', 'event', 'R', 'E_loss', 'cf_event', 'r_event',
              'annual_loss_pct', 'normal_annual_per_mw']]


def plot_wind_mechanism(mech, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(183 * P.MM, 100 * P.MM))
    events = list(EVENTS['wind']); x = np.arange(len(events))
    for k, (var, label) in enumerate((('E_loss', 'Change in event hours (h yr$^{-1}$)'),
                                      ('R', 'Change in unit loss\n(MWh MW$^{-1}$ yr$^{-1}$)'))):
        ax = axes[0, k]
        for i, (dep, color) in enumerate((('ssp126', '#8fb3d9'), ('ssp585', '#d98f8f'))):
            m = mech[(mech.station_ssp == dep) & (mech.event != 'all')]
            piv = m.pivot_table(index=['model', 'event'], columns='climate_ssp', values=var)
            d = (piv.ssp585 - piv.ssp126).unstack('event').reindex(columns=events)
            ax.bar(x + (i - 0.5) * 0.38, d.mean(), width=0.36, color=color, label=f'Fixed {P.SSP_LABELS[dep]} deployment')
            for xi, ev in zip(x, events):
                ax.scatter(np.full(len(d), xi + (i - 0.5) * 0.38), d[ev], s=4, color='k', lw=0, zorder=3)
        ax.axhline(0, color='k', lw=0.5); ax.set_xticks(x, [EVENT_LABELS[e] for e in events], rotation=25, ha='right')
        ax.set_ylabel(label); ax.set_title('Climate SSP5-8.5 - SSP1-2.6, 2050s', loc='left')
        if k == 0:
            ax.legend(fontsize=5, loc='lower left')
    cells = [('ssp126', 'ssp126'), ('ssp585', 'ssp126'), ('ssp126', 'ssp585'), ('ssp585', 'ssp585')]
    names = ['C126\nD126', 'C585\nD126', 'C126\nD585', 'C585\nD585']
    for k, (var, label) in enumerate((('R', 'Unit net loss\n(MWh MW$^{-1}$ yr$^{-1}$)'),
                                      ('annual_loss_pct', 'Loss / annual normal\ngeneration (%)'))):
        ax = axes[1, k]
        a = mech[mech.event == 'all']
        for i, (c, d) in enumerate(cells):
            v = a[(a.climate_ssp == c) & (a.station_ssp == d)][var]
            ax.bar(i, v.mean(), width=0.6, color=SSP_COLORS[d], alpha=0.85 if c == d else 0.45, edgecolor='k', lw=0.3)
            ax.scatter(np.full(len(v), i), v, s=5, color='k', lw=0, zorder=3)
            ax.text(i, v.max(), f'{v.mean():.1f}', ha='center', va='bottom', fontsize=5.5)
        ax.set_xticks(range(4), names); ax.set_ylabel(label)
        lo = min(a[var].min() * 0.9, 0); ax.set_ylim(lo, a[var].max() * 1.12)
        ax.set_title('Wind 2050s: climate (C) x deployment (D)', loc='left')
    for i, ax in enumerate(axes.flat):
        P.panel_letter(ax, chr(97 + i), x=-0.15)
    fig.tight_layout()
    P.export(fig, folder, 'wind_loss_mechanism', {'ab': list(axes[0]), 'cd': list(axes[1])},
             dict(bars='four-model mean', dots='individual models', note='event types overlap; per-type changes do not add to the union'))


def plot_optimisable(agg, shares, folder):
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    from paper_figures.common.spatial import countries
    geoms = {iso: g for iso, _, g in countries()}
    colors = {'optimisable': '#1b7837', 'R126>R585, climate-led or not robust': '#a6dba0', 'R126<=R585': '#d9d9d9'}
    fig = plt.figure(figsize=(183 * P.MM, 125 * P.MM))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.9, 1], hspace=0.25, wspace=0.18)
    groups = {}
    for row, tech in enumerate(('wind', 'solar')):
        ax = fig.add_subplot(gs[row, 0], projection=ccrs.PlateCarree())
        ax.set_extent([-180, 180, -58, 80], crs=ccrs.PlateCarree())
        a = agg[(agg.tech == tech) & (agg.snapshot == 2050)].set_index('country')
        for iso, g in geoms.items():
            cls = a['class'].get(iso)
            ax.add_geometries([g], crs=ccrs.PlateCarree(), facecolor=colors.get(cls, 'white'), edgecolor='0.5', lw=0.2)
        P.degree_axes(ax, range(-180, 181, 60), range(-60, 81, 30))
        ax.set_title(f'{tech.capitalize()}, 2050 snapshot: deployment-optimisable countries (white: not comparable)', loc='left')
        handles = [plt.Rectangle((0, 0), 1, 1, fc=c, ec='0.5', lw=0.3) for c in colors.values()]
        ax.legend(handles, ['Optimisable (deployment-led, robust)', 'R126 > R585 but climate-led or < 3/4 models', 'R126 <= R585'],
                  loc='lower left', fontsize=5, frameon=True, framealpha=0.9)
        P.panel_letter(ax, chr(97 + 2 * row), x=-0.04)
        bx = fig.add_subplot(gs[row, 1])
        s = shares[(shares.tech == tech) & (shares.cls == 'optimisable')].sort_values('snapshot')
        x = np.arange(len(s))
        bx.bar(x - 0.18, s.share_of_comparable * 100, width=0.34, color='#5aae61', label='Share of comparable countries')
        bx.bar(x + 0.18, s.cap_share_of_126 * 100, width=0.34, color='#1b7837', label='Share of SSP1-2.6 capacity')
        for xi, r in zip(x, s.itertuples()):
            bx.text(xi - 0.18, r.share_of_comparable * 100, f'{r.n}/{r.n_comparable}', ha='center', va='bottom', fontsize=5)
            bx.text(xi + 0.18, r.cap_share_of_126 * 100, f'{r.cap126_TW:.2f} TW', ha='center', va='bottom', fontsize=5)
        bx.set_xticks(x, [f'{v}s' for v in s.snapshot]); bx.set_ylabel('Share (%)')
        lo, hi = bx.get_ylim(); bx.set_ylim(lo, hi * 1.45)
        bx.set_title('Optimisable share by capacity snapshot', loc='left'); bx.legend(loc='upper right', fontsize=5)
        P.panel_letter(bx, chr(98 + 2 * row), x=-0.2)
        groups[chr(97 + 2 * row) + chr(98 + 2 * row)] = [ax, bx]
    P.export(fig, folder, 'optimisable_countries', groups,
             dict(projection='PlateCarree', criterion='D=R585,585-R126,126<0, Phi_S<0, Phi_S/D>=0.5 in ensemble mean, '
                  '>=3/4 models meeting it, and R(126 climate, 585 deployment) < R(126,126)'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tables', type=Path, default=OUT / 'station_tables')
    p.add_argument('--output', type=Path, default=OUT / 'loss_analysis')
    a = p.parse_args()
    P.configure()
    window = pd.read_csv(a.tables / 'loss_window.csv.gz')
    annual = pd.read_csv(a.tables / 'loss_annual_global.csv.gz')
    src = a.output / 'source_data'
    catalogue, coverage = capacity_tables(window)
    cap_loss = total_loss(annual, catalogue)
    si = scale_intensity(window, catalogue)
    per3, ens3 = three_factor(window)
    comp = event_composition(window)
    per_opt, agg_opt = optimisable(window)
    shares = optimisable_shares(agg_opt, window)
    mech = wind_mechanism(window)
    plot_wind_mechanism(mech, a.output)
    for name, frame in dict(catalogue_capacity=catalogue, coverage=coverage, annual_total_loss=cap_loss,
                            wind_mechanism=mech,
                            scale_intensity=si, three_factor_models=per3, three_factor_ensemble=ens3,
                            event_composition=comp, optimisable_models=per_opt, optimisable_countries=agg_opt,
                            optimisable_shares=shares).items():
        write_csv(src / f'{name}.csv', frame)
    plot_scale(cap_loss, catalogue, a.output)
    plot_three_factor(ens3, comp, a.output)
    plot_events(comp, a.output)
    plot_optimisable(agg_opt, shares, a.output)
    pd.set_option('display.width', 220); pd.set_option('display.max_columns', 40)
    print(catalogue.assign(TW=catalogue.catalogue_mw / MW_PER_TW).round(3).to_string())
    print('coverage min', coverage.coverage.min())
    w = window[(window.country == 'GLOBAL') & (window.event == 'all') & (window.climate_ssp == window.station_ssp)]
    print(w.groupby(['tech', 'snapshot', 'station_ssp'])[['R', 'E_loss', 'cf_event', 'r_event']].mean().round(4).to_string())
    print(si.groupby(['tech', 'ssp', 'start', 'end'])[['dL_TWh', 'scale_TWh', 'intensity_TWh', 'R0', 'R1', 'C0_TW', 'C1_TW']].mean().round(3).to_string())
    print(ens3[(ens3.event == 'all') & (ens3.snapshot == 2050)].round(4).to_string())
    print(comp[(comp.snapshot == 2050) & comp.climate_ssp.isin(['ssp126', 'ssp585']) & comp.station_ssp.isin(['ssp126', 'ssp585'])][
        ['tech', 'climate_ssp', 'station_ssp', 'event', 'R_mean', 'E_loss_mean', 'cf_event_mean', 'r_event_mean', 'annual_loss_pct_mean', 'normal_annual_per_mw_mean']].round(3).to_string())
    print(shares.round(4).to_string())
    print(agg_opt[agg_opt['class'] == 'optimisable'].sort_values(['tech', 'snapshot', 'cap126_mw'], ascending=[True, True, False]).round(3).to_string())


if __name__ == '__main__':
    main()
