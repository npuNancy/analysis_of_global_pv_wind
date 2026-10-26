"""Same-SSP climate-window x capacity-snapshot matrix and its decomposition over time.

For one SSP the change of unit loss between decades t0 and t1 is
R(t1, s1) - R(t0, s0) = Phi_C + Phi_S, where Phi_C averages the climate-window change at the two fixed
capacity snapshots and Phi_S averages the snapshot change at the two fixed climate windows. Total loss
L = C x R (catalogue capacity C) adds a capacity-scale term: dL = dC x mean(R) + mean(C) x (Phi_C + Phi_S).
Support: stations with finite per-MW results in every model, window and year, and positive normal
generation; each snapshot weights its own capacity.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import MODELS, SSPS, OUTPUT, SSP_COLORS
from paper_figures.common.io import write_csv
from paper_figures.main.fig02_generation_loss.meeting_common import OUT, WINDOWS
from paper_figures.main.fig02_generation_loss import meeting_plotting as P

VARS = ('net', 'positive', 'normal_event', 'normal_annual', 'event_hours')
STEPS = ((2030, 2040), (2040, 2050), (2030, 2050))
NON_COUNTRIES = ('UNASSIGNED', 'AMBIGUOUS')
MWH_PER_TWH = 1e6


def load(root, ssp, tech):
    data = {}
    for model in MODELS:
        parts = sorted((root / ssp / tech / model).glob('*.npz'))
        if not parts:
            raise FileNotFoundError(f'No results for {ssp}/{tech}/{model}')
        arrays = [np.load(p) for p in parts]
        ids = np.concatenate([a['station_id'] for a in arrays])
        if len(set(ids)) != len(ids):
            raise ValueError('Station appears in more than one source patch')
        data[model] = (ids, {v: np.concatenate([a[v] for a in arrays], axis=-1) for v in VARS})
    ids0 = data[MODELS[0]][0]
    order = {m: pd.Series(np.arange(len(i)), index=i)[ids0].to_numpy() for m, (i, _) in data.items()}
    stacked = {v: np.stack([data[m][1][v][..., order[m]] for m in MODELS]) for v in VARS}
    return ids0, stacked


def cells(ids, stacked, ssp, tech):
    cap = pd.read_csv(OUTPUT / f'catalogues/capacity_{ssp}_{tech}.csv.gz', dtype={'station_id': str})
    cap = cap[cap.capacity_mw > 0]
    finite = np.isfinite(stacked['net']).all(axis=(0, 1, 2)) & (stacked['normal_annual'] > 0).all(axis=(0, 1, 2))
    rows, support = [], []
    pos = pd.Series(np.arange(len(ids)), index=ids)
    for snap in WINDOWS:
        c = cap[cap.snapshot == snap]
        present = c.station_id.isin(pos.index).to_numpy()
        idx = np.full(len(c), -1)
        idx[present] = pos[c.station_id[present]].to_numpy()
        ok = present & np.where(present, finite[np.maximum(idx, 0)], False)
        support.append(dict(ssp=ssp, tech=tech, snapshot=snap, stations=len(c), mapped=int(present.sum()),
                            supported=int(ok.sum()), capacity_mw=c.capacity_mw.sum(),
                            supported_capacity_mw=c.capacity_mw[ok].sum()))
        idx, weights, country = idx[ok], c.capacity_mw.to_numpy()[ok], c.country.to_numpy()[ok]
        groups = {'GLOBAL': np.ones(len(idx), bool), **{k: country == k for k in np.unique(country)}}
        for wi, window in enumerate(WINDOWS):
            for name, sel in groups.items():
                if not sel.any():
                    continue
                w = weights[sel]
                sums = {v: np.einsum('myn,n->my', stacked[v][:, wi][:, :, idx[sel]], w) for v in VARS}
                for mi, model in enumerate(MODELS):
                    rows.append(dict(ssp=ssp, tech=tech, model=model, country=name, window=window, snapshot=snap,
                                     capacity_mw=w.sum(), **{f'{v}_mwh': sums[v][mi].mean() for v in VARS}))
    frame = pd.DataFrame(rows).rename(columns={'event_hours_mwh': 'capacity_event_hours'})
    frame['R'] = frame.net_mwh / frame.capacity_mw
    frame['E'] = frame.capacity_event_hours / frame.capacity_mw
    frame['cf_event'] = frame.normal_event_mwh / frame.capacity_event_hours
    frame['r_event'] = frame.net_mwh / frame.normal_event_mwh
    return frame, pd.DataFrame(support)


def decompose_time(frame, catalogue):
    rows = []
    for (ssp, tech, model, country), g in frame.groupby(['ssp', 'tech', 'model', 'country']):
        R = g.set_index(['window', 'snapshot']).R
        for t0, t1 in STEPS:
            need = [(t0, t0), (t1, t0), (t0, t1), (t1, t1)]
            if any(k not in R.index for k in need):
                continue
            r00, r10, r01, r11 = (R[k] for k in need)
            phi_c = 0.5 * ((r10 - r00) + (r11 - r01)); phi_s = 0.5 * ((r01 - r00) + (r11 - r10))
            row = dict(ssp=ssp, tech=tech, model=model, country=country, start=t0, end=t1,
                       R00=r00, R10=r10, R01=r01, R11=r11, dR=r11 - r00, Phi_C=phi_c, Phi_S=phi_s)
            if country == 'GLOBAL':
                c0 = catalogue[(ssp, tech, t0)]; c1 = catalogue[(ssp, tech, t1)]
                cbar = 0.5 * (c0 + c1)
                row.update(C0_TW=c0 / 1e6, C1_TW=c1 / 1e6, dL_TWh=(c1 * r11 - c0 * r00) / MWH_PER_TWH,
                           scale_TWh=(c1 - c0) * 0.5 * (r00 + r11) / MWH_PER_TWH,
                           climate_TWh=cbar * phi_c / MWH_PER_TWH, deploy_TWh=cbar * phi_s / MWH_PER_TWH)
            rows.append(row)
    per = pd.DataFrame(rows)
    if (per.dR - per.Phi_C - per.Phi_S).abs().max() > 1e-9:
        raise ValueError('Decomposition closure failed')
    g = per[per.country == 'GLOBAL']
    if (g.dL_TWh - g.scale_TWh - g.climate_TWh - g.deploy_TWh).abs().max() > 1e-9:
        raise ValueError('Total-loss closure failed')
    cols = [c for c in per.columns if c not in ('ssp', 'tech', 'model', 'country', 'start', 'end')]
    ens = per.groupby(['ssp', 'tech', 'country', 'start', 'end'])[cols].mean().reset_index()
    for k in ('dR', 'Phi_C', 'Phi_S', 'climate_TWh', 'deploy_TWh'):
        if k in per:
            ens[f'{k}_support'] = per.groupby(['ssp', 'tech', 'country', 'start', 'end'])[k].apply(P.support).values
    return per, ens


def plot(frame, per, ens, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(183 * P.MM, 112 * P.MM), gridspec_kw=dict(width_ratios=[0.9, 1.25, 1]))
    groups = {}
    for row, tech in enumerate(('wind', 'solar')):
        ax = axes[row, 0]
        g = frame[(frame.tech == tech) & (frame.country == 'GLOBAL') & (frame.ssp == 'ssp126')]
        mat = g.groupby(['snapshot', 'window']).R.mean().unstack().reindex(index=list(WINDOWS), columns=list(WINDOWS))
        im = ax.imshow(mat.values, cmap='YlOrBr', origin='lower')
        for i in range(3):
            for j in range(3):
                dark = mat.values[i, j] > np.nanmin(mat.values) + 0.6 * np.ptp(mat.values)
                ax.text(j, i, f'{mat.values[i, j]:.1f}', ha='center', va='center', fontsize=6,
                        color='white' if dark else 'black', fontweight='bold' if i == j else 'normal')
            ax.add_patch(plt.Rectangle((i - .5, i - .5), 1, 1, fill=False, lw=1.0, ec='k'))
        ax.set_xticks(range(3), [f'{w}s' for w in WINDOWS]); ax.set_yticks(range(3), [str(w) for w in WINDOWS])
        ax.set_xlabel('Climate window'); ax.set_ylabel('Capacity snapshot')
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03); cb.set_label('Unit net loss (MWh MW$^{-1}$ yr$^{-1}$)')
        P.attach(ax, cb.ax)
        ax.set_title(f'{tech.capitalize()}, SSP1-2.6', loc='left')
        ax = axes[row, 1]
        x0 = 0
        ticks, labels = [], []
        for ssp in SSPS:
            for t0, t1 in STEPS:
                e = ens[(ens.tech == tech) & (ens.ssp == ssp) & (ens.country == 'GLOBAL') & (ens.start == t0) & (ens.end == t1)].iloc[0]
                pm = per[(per.tech == tech) & (per.ssp == ssp) & (per.country == 'GLOBAL') & (per.start == t0) & (per.end == t1)]
                for off, key, color in ((-0.17, 'Phi_C', P.CLIMATE_COLOR), (0.17, 'Phi_S', P.DEPLOY_COLOR)):
                    ax.bar(x0 + off, e[key], width=0.32, color=color,
                           label=('Climate window' if key == 'Phi_C' else 'Capacity snapshot') if x0 == 0 else None)
                    ax.scatter(np.full(len(pm), x0 + off), pm[key], s=4, color='k', lw=0, zorder=3)
                ax.scatter(x0, e['dR'], marker='D', s=14, color=SSP_COLORS[ssp], ec='k', lw=0.3, zorder=4,
                           label='Net change' if x0 == 0 else None)
                ticks.append(x0); labels.append(f"{str(t0)[2:]}s-{str(t1)[2:]}s")
                x0 += 1
            x0 += 0.6
        ax.set_xticks(ticks, labels, rotation=45, ha='right', fontsize=5)
        for i, ssp in enumerate(SSPS):
            ax.text(i * 3.6 + 1, 1.0, P.SSP_LABELS[ssp], transform=ax.get_xaxis_transform(), ha='center',
                    va='bottom', color=SSP_COLORS[ssp], fontsize=6)
        ax.axhline(0, color='k', lw=0.5)
        ax.set_ylabel('Change in unit loss (MWh MW$^{-1}$ yr$^{-1}$)')
        lo, hi = ax.get_ylim(); ax.set_ylim(lo, hi + 0.35 * (hi - lo))
        ax.legend(loc='upper left', fontsize=5, ncol=3, bbox_to_anchor=(0, 0.93))
        ax = axes[row, 2]
        for i, ssp in enumerate(SSPS):
            e = ens[(ens.tech == tech) & (ens.ssp == ssp) & (ens.country == 'GLOBAL') & (ens.start == 2030) & (ens.end == 2050)].iloc[0]
            parts = (('scale_TWh', 'Capacity scale', '#7f7f7f'), ('climate_TWh', 'Climate window', P.CLIMATE_COLOR),
                     ('deploy_TWh', 'Capacity snapshot (siting)', P.DEPLOY_COLOR))
            for j, (k, label, color) in enumerate(parts):
                ax.bar(i + (j - 1) * 0.26, e[k], width=0.25, color=color, label=label if i == 0 else None)
            ax.scatter(i, e['dL_TWh'], marker='D', s=14, color=SSP_COLORS[ssp], ec='k', lw=0.3, zorder=4,
                       label='Net change' if i == 0 else None)
        ax.set_xticks(range(3), [P.SSP_LABELS[s] for s in SSPS]); ax.axhline(0, color='k', lw=0.5)
        ax.set_ylabel('Change in total loss, 2030s to 2050s (TWh yr$^{-1}$)')
        ax.legend(loc='upper right', fontsize=5)
        axes[row, 1].set_title('Unit-loss change split, same SSP', loc='left', pad=10)
        ax.set_title('Total-loss change split', loc='left')
        for c, ax in enumerate(axes[row]):
            P.panel_letter(ax, chr(97 + 3 * row + c), x=-0.3 if c == 0 else -0.2)
        groups[chr(97 + 3 * row) + chr(98 + 3 * row) + chr(99 + 3 * row)] = list(axes[row])
    fig.tight_layout()
    P.export(fig, folder, 'same_ssp_decomposition', groups,
             dict(support='stations finite in all four models, three windows and ten years',
                  climate_window='includes the window-specific normal-CF baseline and internal variability'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=OUT / 'station_loss_cross')
    p.add_argument('--output', type=Path, default=OUT / 'cross_time')
    a = p.parse_args()
    P.configure()
    frames, supports = [], []
    for ssp in SSPS:
        for tech in ('wind', 'solar'):
            ids, stacked = load(a.input, ssp, tech)
            f, s = cells(ids, stacked, ssp, tech)
            frames.append(f); supports.append(s)
            print('loaded', ssp, tech, len(ids), flush=True)
    frame = pd.concat(frames, ignore_index=True); support = pd.concat(supports, ignore_index=True)
    cap = pd.read_csv(OUTPUT / 'catalogues/capacity_by_country.csv')
    catalogue = cap.groupby(['station_ssp', 'tech', 'snapshot']).capacity_mw.sum().to_dict()
    per, ens = decompose_time(frame, catalogue)
    official = pd.read_csv(OUT / 'station_tables/loss_window.csv.gz')
    official = official[(official.country == 'GLOBAL') & (official.event == 'all') & (official.climate_ssp == official.station_ssp)]
    diag = frame[(frame.country == 'GLOBAL') & (frame.window == frame.snapshot)].merge(
        official[['model', 'station_ssp', 'tech', 'snapshot', 'R']].rename(columns=dict(station_ssp='ssp', R='R_official')),
        on=['model', 'ssp', 'tech', 'snapshot'])
    diag['rel_diff'] = (diag.R - diag.R_official) / diag.R_official
    src = a.output / 'source_data'
    write_csv(src / 'cells.csv.gz', frame); write_csv(src / 'support.csv', support)
    write_csv(src / 'decomposition_models.csv.gz', per); write_csv(src / 'decomposition_ensemble.csv', ens)
    write_csv(src / 'diagonal_vs_published.csv', diag)
    plot(frame, per, ens, a.output)
    pd.set_option('display.width', 220); pd.set_option('display.max_columns', 40)
    print(support.assign(cov=support.supported_capacity_mw / support.capacity_mw).round(4).to_string())
    print('diagonal vs published R, max |rel diff|', diag.rel_diff.abs().max())
    print(ens[ens.country == 'GLOBAL'].round(3).to_string())


if __name__ == '__main__':
    main()
