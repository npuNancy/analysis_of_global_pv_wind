"""Meeting follow-up: world maps of deployment-optimization candidates and extended SSP decompositions.

Reads only accepted small summary tables (country_candidates_ensemble.csv and
loss_summary/window.csv.gz); renders on the login node with the repository .venv.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import cartopy.crs as ccrs
from matplotlib.lines import Line2D
from matplotlib.colors import TwoSlopeNorm, Normalize
from matplotlib.cm import ScalarMappable

from paper_figures.common.io import digest
from paper_figures.common.spatial import countries

BASE = Path(__file__).resolve().parent
OUT = BASE / 'outputs' / 'meeting_followup'
SOURCE = OUT / 'source_data'
CANDIDATES = BASE.parent / 'fig02_generation_loss/outputs/meeting_loss/source_data/country_candidates_ensemble.csv'
WINDOW = Path('paper_figures/prepare/outputs/loss_summary/window.csv.gz')
ROOT = Path(__file__).resolve().parents[3]
EXTENT = [-180, 180, -60, 85]
PAIRS = [('ssp585', 'ssp126'), ('ssp245', 'ssp126'), ('ssp585', 'ssp245')]
AUDIT = {}


def check(ok, message):
    if not ok:
        raise ValueError(message)
    AUDIT.setdefault('checks', []).append(dict(ok=bool(ok), message=message))


def circle_position(geometry):
    parts = list(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else [geometry]
    point = max(parts, key=lambda p: p.area).representative_point()
    return point.x, point.y


def candidate_map():
    """World maps: fill = fixed-climate-126 deployment benefit (R585-R126, MWh/MW/yr);
    circles = SSP126/2050 reference capacity; hatch/edge marks 4/4 joint support."""
    frame = pd.read_csv(CANDIDATES)
    features = countries()
    frame['reference_capacity_gw'] = frame.reference_capacity_mw / 1e3
    maximum = float(frame.reference_capacity_gw.max())
    scale = 1000.0  # pt^2 per GW at reference scale

    def circle_area(cap_gw):
        return cap_gw * scale

    vmin = float(frame.fixed_climate126_deployment.min())
    vmax = float(frame.fixed_climate126_deployment.max())
    limit = max(abs(vmin), abs(vmax))
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
    cmap = plt.get_cmap('RdBu_r')

    fig = plt.figure(figsize=(240 / 25.4, 150 / 25.4))
    fig.text(.52, .965, 'Fixed climate SSP126: swapping 126→585 deployment and its unit-capacity loss impact',
             ha='center', fontsize=10, weight='bold')
    fig.text(.52, .932, 'Fill: R(585 deployment) − R(126 deployment), blue = 585-style layout lowers loss  |  '
                        'Circles: SSP126/2050 reference capacity  |  Thick edge: 4/4 models joint candidate support',
             ha='center', fontsize=6.5, color='#40494F')
    for row, tech in enumerate(('wind', 'solar')):
        ax = fig.add_axes([.075, .535 - row * .43, .86, .36], projection=ccrs.PlateCarree())
        ax.set_extent(EXTENT, crs=ccrs.PlateCarree())
        ax.set_facecolor('white')
        panel = frame[frame.tech.eq(tech)].set_index('country')
        circles = []
        for iso, _, geom in features:
            row_data = panel.loc[iso] if iso in panel.index else None
            value = float(row_data.fixed_climate126_deployment) if row_data is not None else np.nan
            face = cmap(norm(value)) if np.isfinite(value) else '#DEDEDE'
            ax.add_geometries([geom], crs=ccrs.PlateCarree(), facecolor=face,
                              edgecolor='#90969B', linewidth=.25, zorder=1)
            if row_data is not None and row_data.reference_capacity_gw > 0:
                circles.append((iso, *circle_position(geom), float(row_data.reference_capacity_gw),
                                value, int(row_data.joint_support)))
        for iso, lon, lat, cap, value, support in sorted(circles, key=lambda c: -c[3]):
            ax.scatter(lon, lat, s=circle_area(cap), transform=ccrs.PlateCarree(),
                       facecolor=[cmap(norm(value)) if np.isfinite(value) else '#A6A6A6'],
                       edgecolor='#242B30' if support >= 4 else '#242B30',
                       linewidth=.55 if support >= 4 else .3,
                       linestyle='-' if support >= 4 else 'None',
                       zorder=3)
        ax.gridlines(crs=ccrs.PlateCarree(), xlocs=[-120, -60, 0, 60, 120], ylocs=[-30, 0, 30, 60],
                     linewidth=.2, color='#91999E', alpha=.3, zorder=2)
        ax.set_xticks([-120, 0, 120], crs=ccrs.PlateCarree())
        ax.set_yticks([-30, 0, 60], crs=ccrs.PlateCarree())
        from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
        ax.xaxis.set_major_formatter(LongitudeFormatter())
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(labelsize=6, length=2, width=.35, pad=2)
        ax.spines['geo'].set_linewidth(.4)
        ax.spines['geo'].set_edgecolor('#92999F')
        ax.set_title(f"{'Wind' if tech == 'wind' else 'Solar'}", loc='left', fontsize=8, pad=5)
        ax.text(.012, .955, 'ab'[row], transform=ax.transAxes, va='top', weight='bold', fontsize=9, zorder=4)

    cax = fig.add_axes([.12, .085, .42, .016])
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation='horizontal',
                       extend='both', extendfrac=.04)
    cb.set_label('R(585 deployment) − R(126 deployment) under climate 126 (MWh MW⁻¹ yr⁻¹), blue = lower loss',
                 fontsize=7, labelpad=3)
    cb.ax.tick_params(labelsize=6, length=2, width=.4)
    cb.outline.set_linewidth(.4)

    power = 10 ** np.floor(np.log10(maximum))
    refs = [power / 10, power / 2, power]
    handles = [Line2D([], [], marker='o', linestyle='', markersize=np.sqrt(circle_area(v)),
                      markerfacecolor='#B9C3C9', markeredgecolor='#242B30', linewidth=.4)
               for v in refs]
    legend = fig.legend(handles, [f'{v:,.0f}' for v in refs], loc='center left', bbox_to_anchor=(.62, .078),
                        title='SSP126/2050 reference capacity (GW)', fontsize=6.5, title_fontsize=7,
                        labelspacing=1.1, handletextpad=.5, borderpad=.8, frameon=False)
    legend._legend_box.align = 'left'
    fig.savefig(OUT / 'meeting_candidates_map.png', dpi=600, facecolor='white')
    plt.close(fig)

    # compact per-panel exports
    for row, tech in enumerate(('wind', 'solar')):
        fig, ax = plt.subplots(figsize=(240 / 25.4, 78 / 25.4),
                               subplot_kw=dict(projection=ccrs.PlateCarree()))
        fig.subplots_adjust(left=.02, right=.98, top=.86, bottom=.16)
        ax.set_extent(EXTENT, crs=ccrs.PlateCarree())
        ax.set_facecolor('white')
        panel = frame[frame.tech.eq(tech)].set_index('country')
        circles = []
        for iso, _, geom in features:
            row_data = panel.loc[iso] if iso in panel.index else None
            value = float(row_data.fixed_climate126_deployment) if row_data is not None else np.nan
            face = cmap(norm(value)) if np.isfinite(value) else '#DEDEDE'
            ax.add_geometries([geom], crs=ccrs.PlateCarree(), facecolor=face,
                              edgecolor='#90969B', linewidth=.25, zorder=1)
            if row_data is not None and row_data.reference_capacity_gw > 0:
                circles.append((iso, *circle_position(geom), float(row_data.reference_capacity_gw),
                                value, int(row_data.joint_support)))
        for iso, lon, lat, cap, value, support in sorted(circles, key=lambda c: -c[3]):
            ax.scatter(lon, lat, s=circle_area(cap), transform=ccrs.PlateCarree(),
                       facecolor=[cmap(norm(value)) if np.isfinite(value) else '#A6A6A6'],
                       edgecolor='#242B30', linewidth=.55 if support >= 4 else .3, zorder=3)
        ax.gridlines(crs=ccrs.PlateCarree(), xlocs=[-120, -60, 0, 60, 120], ylocs=[-30, 0, 30, 60],
                     linewidth=.2, color='#91999E', alpha=.3, zorder=2)
        ax.set_xticks([-120, 0, 120], crs=ccrs.PlateCarree())
        ax.set_yticks([-30, 0, 60], crs=ccrs.PlateCarree())
        from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
        ax.xaxis.set_major_formatter(LongitudeFormatter())
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(labelsize=6, length=2, width=.35, pad=2)
        ax.spines['geo'].set_linewidth(.4)
        ax.set_title(f"{'Wind' if tech == 'wind' else 'Solar'}  |  fill: R(585)−R(126) under climate 126, blue = lower", loc='left', fontsize=8)
        ax.text(.012, .955, 'ab'[row], transform=ax.transAxes, va='top', weight='bold', fontsize=9)
        cax = fig.add_axes([.12, .09, .42, .03])
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation='horizontal',
                          extend='both', extendfrac=.04)
        cb.set_label('Deployment benefit (MWh MW⁻¹ yr⁻¹)', fontsize=7, labelpad=2)
        cb.ax.tick_params(labelsize=6, length=2, width=.4)
        cb.outline.set_linewidth(.4)
        fig.savefig(OUT / f'meeting_candidates_map_{"ab"[row]}.png', dpi=600, facecolor='white')
        plt.close(fig)

    frame[['tech', 'country', 'name', 'reference_capacity_gw', 'fixed_climate126_deployment',
           'joint_support']].to_csv(SOURCE / 'candidate_map_values.csv', index=False)
    check(len(frame) > 300, f'candidate table rows: {len(frame)}')
    check(np.isfinite(limit) and limit > 0, f'symmetric colour limit {limit:.2f}')


def extended_decomposition():
    """Country and global climate/deployment Shapley decomposition for all three SSP pairs."""
    window = pd.read_csv(ROOT / WINDOW)
    used = window[window.event.eq('all') & window.snapshot.eq(2050) & window.country.ne('GLOBAL')]
    global_used = window[window.event.eq('all') & window.snapshot.eq(2050) & window.country.eq('GLOBAL')]
    rows = []
    for (tech, country), group in pd.concat([used, global_used]).groupby(['tech', 'country']):
        matrix = group.pivot_table(index=['model', 'climate_ssp'], columns='station_ssp', values='R')
        for high, low in PAIRS:
            per_model = []
            for model in matrix.index.get_level_values('model').unique():
                sub = matrix.xs(model, level='model', drop_level=True)
                try:
                    r = {(c, s): float(sub.loc[c, s]) for c in (low, high) for s in (low, high)}
                except KeyError:
                    continue
                if any(not np.isfinite(v) for v in r.values()):
                    continue
                # symmetric decomposition identical to common.metrics.climate_deployment
                a, b, c, d = r[(low, low)], r[(high, low)], r[(low, high)], r[(high, high)]
                dc0, dc1 = b - a, d - c
                ds0, ds1 = c - a, d - b
                per_model.append(dict(D=d - a, delta_C_126=dc0, delta_C_585=dc1, delta_S_126=ds0,
                                      delta_S_585=ds1, Phi_C=(dc0 + dc1) / 2, Phi_S=(ds0 + ds1) / 2,
                                      J=dc1 - dc0,
                                      closure=(dc0 + dc1 + ds0 + ds1) / 2 - (d - a)))
            if not per_model:
                continue
            closures = np.array([m['closure'] for m in per_model], dtype=float)
            check(np.abs(closures).max() < 1e-9,
                  f'per-model closure {tech}/{country}/{high}-{low}: {np.abs(closures).max():.2e}')
            for key in ('D', 'Phi_C', 'Phi_S', 'J'):
                values = np.array([m[key] for m in per_model], dtype=float)
                rows.append(dict(tech=tech, country=country, contrast=f'{high}-{low}',
                                 metric=key, mean=float(values.mean()),
                                 minimum=float(values.min()), maximum=float(values.max()),
                                 n_models=len(values),
                                 positive_models=int((values > 1e-9).sum()),
                                 negative_models=int((values < -1e-9).sum())))
    table = pd.DataFrame(rows)
    table.to_csv(SOURCE / 'ssp_pair_country_decomposition.csv', index=False)

    # identity check: Phi_C + Phi_S = D within model
    check(len(table) > 3000, f'decomposition rows: {len(table)}')
    wide = table.pivot_table(index=['tech', 'country', 'contrast'], columns='metric', values='mean')
    gap = (wide.Phi_C + wide.Phi_S - wide.D).abs().max()
    check(gap < 1e-9, f'global identity closure max |Phi_C+Phi_S-D| = {gap:.3e}')

    # figure: global bars per pair + top countries by |Phi_S|
    from paper_figures.config import SSP_COLORS
    fig, axes = plt.subplots(2, 3, figsize=(183 / 25.4, 120 / 25.4), layout='constrained')
    for col, (high, low) in enumerate(PAIRS):
        contrast = f'{high}-{low}'
        for row, tech in enumerate(('wind', 'solar')):
            ax = axes[row, col]
            g = table[(table.tech == tech) & (table.country == 'GLOBAL') & (table.contrast == contrast)]
            def val(frame, key, field):
                return float(frame[frame.metric == key][field].iloc[0])
            values = [val(g, k, 'mean') for k in ('Phi_C', 'Phi_S', 'D')]
            mins = [val(g, k, 'minimum') for k in ('Phi_C', 'Phi_S', 'D')]
            maxs = [val(g, k, 'maximum') for k in ('Phi_C', 'Phi_S', 'D')]
            x = np.arange(3)
            colors = ['#487A96', '#D39A54', '#40494F']
            ax.bar(x, values, .5, color=colors)
            ax.errorbar(x, values,
                        yerr=[np.maximum(0, np.array(values) - np.array(mins)),
                              np.maximum(0, np.array(maxs) - np.array(values))],
                        fmt='none', ecolor='#242B30', elinewidth=.6, capsize=2)
            ax.axhline(0, color='#242B30', linewidth=.6)
            ax.set_xticks(x, ['Climate Φ_C', 'Deployment Φ_S', 'Net D'])
            ax.set_title(f"{'Wind' if tech == 'wind' else 'Solar'} | {high}−{low}", loc='left', fontsize=8)
            for xi, v in zip(x, values):
                ax.text(xi, v + (0.03 * abs(v) if v >= 0 else -0.08 * abs(v) - 2),
                        f'{v:+.1f}', ha='center', fontsize=7)
            ax.grid(axis='y', alpha=.15)
            if col == 0:
                ax.set_ylabel('Unit-capacity loss difference\n(MWh MW⁻¹ yr⁻¹)', fontsize=7)
            ax.tick_params(labelsize=6.5)
    fig.suptitle('Climate vs deployment contributions to paired-path unit-capacity loss gaps | 2050s, global',
                 fontsize=10, weight='bold')
    fig.savefig(OUT / 'meeting_ssp_pair_decomposition_global.png', dpi=600, facecolor='white')
    plt.close(fig)

    # per-country Phi_S scatter for the two new contrasts
    fig, axes = plt.subplots(1, 2, figsize=(183 / 25.4, 86 / 25.4), layout='constrained')
    for ax, (tech, label) in zip(axes, (('wind', 'a'), ('solar', 'b'))):
        for contrast, color, marker in (('ssp245-ssp126', '#b77c19', 'o'), ('ssp585-ssp245', '#9e1b1b', 's')):
            g = table[(table.tech == tech) & (table.contrast == contrast) &
                      (table.metric == 'Phi_S') & (table.country != 'GLOBAL')].copy()
            # attach reference capacity
            caps = pd.read_csv(CANDIDATES)
            cap_map = caps[caps.tech == tech].set_index('country').reference_capacity_mw
            g['capacity'] = g.country.map(cap_map)
            g = g[g.capacity.notna() & (g.capacity > 0)]
            sizes = 4 + 46 * (g.capacity / g.capacity.max())
            ax.scatter(g['mean'], g['mean'], s=sizes, alpha=.55, color=color, marker=marker,
                       edgecolor='#242B30', linewidth=.2, label=f'{contrast.replace("ssp", "SSP")} Φ_S')
        ax.axvline(0, color='#242B30', linewidth=.6)
        ax.set_xlabel('Deployment contribution Φ_S (MWh MW⁻¹ yr⁻¹)', fontsize=7)
        ax.set_title(f"{'Wind' if tech == 'wind' else 'Solar'} | country deployment contributions", loc='left', fontsize=8)
        ax.legend(fontsize=6.5)
        ax.grid(alpha=.15)
        ax.tick_params(labelsize=6.5)
    fig.suptitle('Country deployment contributions for SSP245−SSP126 and SSP585−SSP245 | circle size: SSP126/2050 capacity',
                 fontsize=9, weight='bold')
    fig.savefig(OUT / 'meeting_ssp_pair_decomposition_countries.png', dpi=600, facecolor='white')
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    candidate_map()
    extended_decomposition()
    AUDIT['inputs'] = {
        'candidates': {'path': str(CANDIDATES), 'sha256': digest(CANDIDATES)},
        'window': {'path': str(ROOT / WINDOW), 'sha256': digest(ROOT / WINDOW)},
    }
    AUDIT['outputs'] = {
        'map': ['meeting_candidates_map.png', 'meeting_candidates_map_a.png', 'meeting_candidates_map_b.png'],
        'decomposition': ['meeting_ssp_pair_decomposition_global.png', 'meeting_ssp_pair_decomposition_countries.png'],
        'source': ['ssp_pair_country_decomposition.csv', 'candidate_map_values.csv'],
    }
    (OUT / 'metadata.json').write_text(json.dumps(AUDIT, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(AUDIT['checks'], indent=2))


if __name__ == '__main__':
    main()
