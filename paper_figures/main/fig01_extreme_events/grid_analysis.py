"""Grid-level weather exposure trends, SSP contrasts, icing time-axis comparison and humidity/icing
mechanisms from the grid summaries and raw BCSD diagnostics.

All regional values are area-weighted on the per-patch common support (exposure) or on the event land
domain (raw meteorology). Model statistics are computed per model first and then averaged equally.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import MODELS, SSPS, SSP_COLORS
from paper_figures.common.io import write_csv
from paper_figures.main.fig01_extreme_events.meeting_common import OUT, LAT_BANDS, GRID_YEARS, lat_band, patches
from paper_figures.main.fig01_extreme_events import meeting_plotting as P
from paper_figures.main.fig01_extreme_events.grid_meteo import WINDOW_YEARS

REGIONS = ('GLOBAL',) + tuple(b[0] for b in LAT_BANDS)
WEATHER = [('union:all', 'All weather events (cross-technology union)'),
           ('wind:high_temp', 'High temperature'), ('wind:high_wind', 'High wind'), ('wind:hot_humid', 'Hot-humid'),
           ('wind:icing', 'Icing'), ('wind:low_resource', 'Low wind resource'),
           ('solar:cold_highwind', 'Cold high wind'), ('solar:freezing_rain', 'Freezing rain'),
           ('solar:high_humidity', 'High humidity'), ('solar:low_resource', 'Low solar resource'),
           ('solar:rainstorm', 'Rainstorm')]
EXTRA = [('wind:any', 'Wind-relevant union'), ('solar:any', 'Solar-relevant union'), ('solar:icing', 'Icing (solar time axis)')]
HIST_EDGES = np.r_[-1, np.arange(0, 101), 101]


def region_masks(lat):
    bands = lat_band(lat)
    return {'GLOBAL': np.ones(len(lat), bool), **{name: bands == name for name, _, _ in LAT_BANDS}}


def exposure_series(folder):
    """(region, model, ssp, product, year) area-weighted days per year."""
    num = {r: 0.0 for r in REGIONS}; den = {r: 0.0 for r in REGIONS}
    maps = []
    for patch in patches():
        z = np.load(folder / f'{patch}.npz')
        products = list(z['products'])
        for r, m in region_masks(z['lat']).items():
            num[r] = num[r] + z['rows'][..., m].sum(axis=-1)
            den[r] = den[r] + z['row_area'][m].sum()
        maps.append((z['map_keys'], z['map_area'], z['maps']))
    rows = []
    for r in REGIONS:
        days = num[r] / den[r]
        for mi, model in enumerate(MODELS):
            for si, ssp in enumerate(SSPS):
                for pi, product in enumerate(products):
                    for yi, year in enumerate(GRID_YEARS):
                        rows.append((r, model, ssp, product, year, days[mi, si, pi, yi], den[r]))
    series = pd.DataFrame(rows, columns=['region', 'model', 'ssp', 'product', 'year', 'days', 'area_km2'])
    keys = np.concatenate([k for k, _, _ in maps])
    area = np.concatenate([a for _, a, _ in maps])
    values = np.concatenate([v for _, _, v in maps], axis=-1)
    df = pd.DataFrame({'key': keys, 'area': area})
    agg_area = df.groupby('key').area.sum()
    weighted = pd.DataFrame(values.reshape(-1, values.shape[-1]).T, index=keys).groupby(level=0).sum()
    map_days = weighted.values.T.reshape(values.shape[:-1] + (len(agg_area),)) / agg_area.values
    return series, products, agg_area.index.values, agg_area.values, map_days


def contrasts(series):
    """Per-model 2050s SSP differences and changes relative to 2015-2024, with model support."""
    w = series.assign(period=np.select([series.year.between(2015, 2024), series.year.between(2050, 2059)],
                                       ['2015-2024', '2050-2059'], ''))
    w = w[w.period != ''].groupby(['region', 'model', 'ssp', 'product', 'period']).days.mean().unstack('period').reset_index()
    rows = []
    for (region, product, model), g in w.groupby(['region', 'product', 'model']):
        g = g.set_index('ssp')
        for a, b in (('ssp585', 'ssp126'), ('ssp245', 'ssp126'), ('ssp585', 'ssp245')):
            rows.append(dict(region=region, product=product, model=model, contrast=f'{a}-{b}',
                             value=g.at[a, '2050-2059'] - g.at[b, '2050-2059']))
        for s in SSPS:
            rows.append(dict(region=region, product=product, model=model, contrast=f'{s}:2050s-2015_24',
                             value=g.at[s, '2050-2059'] - g.at[s, '2015-2024']))
    per = pd.DataFrame(rows)
    ens = per.groupby(['region', 'product', 'contrast']).value.agg(['mean', 'min', 'max']).reset_index()
    ens['support'] = per.groupby(['region', 'product', 'contrast']).value.apply(P.support).values
    return per, ens


def slopes(series):
    rows = []
    for (region, product, ssp, model), g in series.groupby(['region', 'product', 'ssp', 'model']):
        rows.append(dict(region=region, product=product, ssp=ssp, model=model,
                         slope=np.polyfit(g.year, g.days, 1)[0] * 10))
    per = pd.DataFrame(rows)
    ens = per.groupby(['region', 'product', 'ssp']).slope.agg(['mean', 'min', 'max']).reset_index()
    ens['support'] = per.groupby(['region', 'product', 'ssp']).slope.apply(P.support).values
    return per, ens


def meteo(folder):
    """Region sums of raw diagnostics: annual (model, ssp, stat, year), monthly and histograms."""
    acc = {}
    for model in MODELS:
        for ssp in SSPS:
            for patch in patches():
                z = np.load(folder / model / ssp / f'{patch}.npz')
                masks = region_masks(z['lat'])
                for key in z.files:
                    if not key.startswith(('annual_', 'monthly_', 'hist')):
                        continue
                    for r, m in masks.items():
                        v = z[key][..., m, :].sum(axis=-2) if key == 'hist' else z[key][..., m].sum(axis=-1)
                        k = (model, ssp, r, key)
                        acc[k] = acc.get(k, 0) + v
    return acc


def meteo_tables(acc):
    annual, monthly, hist = [], [], []
    for (model, ssp, region, key), v in acc.items():
        if key == 'annual_w':
            w = v
            stats = {s: acc[(model, ssp, region, f'annual_{s}')] / w for s in ('T', 'RH', 'lnRH', 'lnes', 'rh85', 'rh90', 'rh95', 'cold', 'coldhum')}
            for yi, year in enumerate(WINDOW_YEARS):
                annual.append(dict(model=model, ssp=ssp, region=region, year=year, **{s: x[yi] for s, x in stats.items()}))
        elif key == 'monthly_w':
            for wi, window in enumerate(('2015-2024', '2050-2059')):
                for mo in range(12):
                    w = v[wi, mo]
                    row = dict(model=model, ssp=ssp, region=region, window=window, month=mo + 1)
                    for s in ('T', 'RH', 'lnRH', 'lnes', 'rh85', 'rh90', 'rh95', 'cold', 'coldhum'):
                        row[s] = acc[(model, ssp, region, f'monthly_{s}')][wi, mo] / w
                    row['w'] = w
                    for var in ('rsds', 'ws'):
                        row[f'w_{var}'] = acc[(model, ssp, region, f'monthly_w_{var}')][wi, mo]
                        row[var] = acc[(model, ssp, region, f'monthly_{var}')][wi, mo] / row[f'w_{var}']
                    monthly.append(row)
        elif key == 'hist':
            for wi, window in enumerate(('2015-2024', '2050-2059')):
                h = v[wi] / v[wi].sum()
                for b, x in enumerate(h):
                    hist.append(dict(model=model, ssp=ssp, region=region, window=window, bin=b, lower=HIST_EDGES[b], prob=x))
    return pd.DataFrame(annual), pd.DataFrame(monthly), pd.DataFrame(hist)


def window_means(monthly):
    """Time-weighted window means; the joint icing condition is decomposed into cold and conditional humidity."""
    m = monthly.copy()
    for s in ('T', 'RH', 'lnRH', 'lnes', 'rh85', 'rh90', 'rh95', 'cold', 'coldhum'):
        m[f'{s}_w'] = m[s] * m.w
    g = m.groupby(['model', 'ssp', 'region', 'window'])
    out = g[[f'{s}_w' for s in ('T', 'RH', 'lnRH', 'lnes', 'rh85', 'rh90', 'rh95', 'cold', 'coldhum')]].sum().div(g.w.sum(), axis=0)
    out.columns = [c[:-2] for c in out.columns]
    for var in ('rsds', 'ws'):
        m[f'{var}_x'] = m[var] * m[f'w_{var}']
        out[var] = m.groupby(['model', 'ssp', 'region', 'window'])[f'{var}_x'].sum() / g[f'w_{var}'].sum()
    out = out.reset_index()
    out['hum_given_cold'] = out.coldhum / out.cold
    return out


def mechanism_contrasts(wm, monthly):
    rows = []
    for (region, model), g in wm.groupby(['region', 'model']):
        g = g.set_index(['ssp', 'window'])
        def diff(var, a, b):
            return g.at[a, var] - g.at[b, var]
        for a, b in ((('ssp585', '2050-2059'), ('ssp126', '2050-2059')),
                     *[((s, '2050-2059'), (s, '2015-2024')) for s in SSPS]):
            label = f'{a[0]}-{b[0]}' if a[1] == b[1] else f'{a[0]}:2050s-2015_24'
            pc0, pc1 = g.at[b, 'cold'], g.at[a, 'cold']; ph0, ph1 = g.at[b, 'hum_given_cold'], g.at[a, 'hum_given_cold']
            rows.append(dict(region=region, model=model, contrast=label,
                             dT=diff('T', a, b), dRH=diff('RH', a, b), dlnRH=diff('lnRH', a, b),
                             dlne=diff('lnRH', a, b) + diff('lnes', a, b), dlnes=diff('lnes', a, b),
                             drh85=diff('rh85', a, b), drh90=diff('rh90', a, b), drh95=diff('rh95', a, b),
                             dcold=pc1 - pc0, dhum_given_cold=ph1 - ph0, djoint=diff('coldhum', a, b),
                             joint_cold_term=(pc1 - pc0) * 0.5 * (ph0 + ph1), joint_hum_term=0.5 * (pc0 + pc1) * (ph1 - ph0),
                             drsds=diff('rsds', a, b), dws=diff('ws', a, b), drsds_pct=100 * diff('rsds', a, b) / g.at[b, 'rsds'],
                             dws_pct=100 * diff('ws', a, b) / g.at[b, 'ws']))
    per = pd.DataFrame(rows)
    value_cols = [c for c in per.columns if c.startswith(('d', 'joint'))]
    ens = per.groupby(['region', 'contrast'])[value_cols].mean().reset_index()
    for c in value_cols:
        ens[f'{c}_support'] = per.groupby(['region', 'contrast'])[c].apply(P.support).values
    m = monthly[monthly.region == '60-90N'].copy()
    m['hum_given_cold'] = m.coldhum / m.cold
    mon = []
    for (model, mo), g in m.groupby(['model', 'month']):
        g = g.set_index(['ssp', 'window'])
        a, b = ('ssp585', '2050-2059'), ('ssp126', '2050-2059')
        pc0, pc1, ph0, ph1 = g.at[b, 'cold'], g.at[a, 'cold'], g.at[b, 'hum_given_cold'], g.at[a, 'hum_given_cold']
        mon.append(dict(model=model, month=mo, cold_126=pc0, cold_585=pc1, hgc_126=ph0, hgc_585=ph1,
                        joint_126=g.at[b, 'coldhum'], joint_585=g.at[a, 'coldhum'], T_126=g.at[b, 'T'], T_585=g.at[a, 'T'],
                        rsds_126=g.at[b, 'rsds'], rsds_585=g.at[a, 'rsds'], rh95_126=g.at[b, 'rh95'], rh95_585=g.at[a, 'rh95'],
                        cold_term=(pc1 - pc0) * 0.5 * (np.nan_to_num(ph0) + np.nan_to_num(ph1)),
                        hum_term=0.5 * (pc0 + pc1) * (np.nan_to_num(ph1) - np.nan_to_num(ph0))))
    return per, ens, pd.DataFrame(mon)


def meteo_maps(folder):
    """1-degree window means of RH, rsds and wind speed: dict var -> (model, ssp, window, key) and keys."""
    num, den = {}, {}
    for model in MODELS:
        for ssp in SSPS:
            for patch in patches():
                z = np.load(folder / model / ssp / f'{patch}.npz')
                lat, lon, area, domain = z['lat'], z['lon'], z['area'], z['domain']
                keys = ((np.floor(lat).astype(int) + 90)[:, None] * 360 + (np.floor(((lon + 180) % 360) - 180).astype(int) + 180)[None, :])[domain]
                for var, wvar in (('RH', 'w'), ('rsds', 'w_rsds'), ('ws', 'w_ws')):
                    w = z[f'map_{wvar}'][:, domain]; x = z[f'map_{var}'][:, domain]
                    for wi in range(2):
                        k = (var, model, ssp, wi)
                        num.setdefault(k, []).append(pd.Series(x[wi] * area[domain] / np.maximum(w[wi], 1)).groupby(keys).sum())
                        den.setdefault(k, []).append(pd.Series(area[domain] * (w[wi] > 0)).groupby(keys).sum())
    out = {}
    for k in num:
        n = pd.concat(num[k]).groupby(level=0).sum(); d = pd.concat(den[k]).groupby(level=0).sum()
        out[k] = n / d
    return out


def country_contributions(map_keys, map_area, map_days, products, product='solar:high_humidity'):
    """Area-weighted 2050s SSP5-8.5 - SSP1-2.6 change by country, from 1-degree bins."""
    from paper_figures.common.spatial import countries, assign
    lat = map_keys // 360 - 90 + 0.5; lon = map_keys % 360 - 180 + 0.5
    iso = assign(lon, lat, countries())
    pi = products.index(product)
    rows = []
    for mi, model in enumerate(MODELS):
        d = map_days[mi, 2, pi, 3] - map_days[mi, 0, pi, 3]
        rows.append(pd.DataFrame(dict(model=model, country=iso, band=lat_band(lat), d=d, key=map_keys, area_km2=map_area)))
    return pd.concat(rows, ignore_index=True)


def plot_maps(mmaps, map_keys, map_days, products, folder):
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    fig, axes = plt.subplots(3, 2, figsize=(183 * P.MM, 150 * P.MM), subplot_kw=dict(projection=ccrs.PlateCarree()))
    def grid_of(series):
        g = np.full((180, 360), np.nan); k = series.index.values
        g[k // 360, k % 360] = series.values
        return g
    def mean_diff(var, a, b, rel=False):
        diffs = []
        for model in MODELS:
            x, y = mmaps[(var, model, *a)], mmaps[(var, model, *b)]
            diffs.append(((x - y) / y * 100) if rel else (x - y))
        return pd.concat(diffs, axis=1).mean(axis=1)
    pi = products.index('solar:high_humidity')
    hh = pd.Series((map_days[:, 2, pi, 3] - map_days[:, 0, pi, 3]).mean(axis=0), index=map_keys)
    panels = [(mean_diff('RH', ('ssp585', 1), ('ssp126', 1)), 'Mean RH, 2050s SSP5-8.5 - SSP1-2.6 (pp)', 4, 'BrBG'),
              (hh, 'High-humidity exposure, 2050s SSP5-8.5 - SSP1-2.6 (days yr$^{-1}$)', 15, 'BrBG'),
              (mean_diff('ws', ('ssp126', 1), ('ssp126', 0), True), '10-m wind speed, SSP1-2.6, 2050s vs 2015-2024 (%)', 6, 'PuOr_r'),
              (mean_diff('ws', ('ssp585', 1), ('ssp585', 0), True), '10-m wind speed, SSP5-8.5, 2050s vs 2015-2024 (%)', 6, 'PuOr_r'),
              (mean_diff('rsds', ('ssp126', 1), ('ssp126', 0), True), 'Surface solar radiation, SSP1-2.6, 2050s vs 2015-2024 (%)', 6, 'RdYlBu_r'),
              (mean_diff('rsds', ('ssp585', 1), ('ssp585', 0), True), 'Surface solar radiation, SSP5-8.5, 2050s vs 2015-2024 (%)', 6, 'RdYlBu_r')]
    groups = {}
    for i, (ax, (series, title, lim, cmap)) in enumerate(zip(axes.flat, panels)):
        mesh = ax.pcolormesh(np.arange(-180, 181), np.arange(-90, 91), grid_of(series), cmap=cmap, vmin=-lim, vmax=lim,
                             transform=ccrs.PlateCarree(), shading='flat')
        P.draw_borders(ax); ax.set_extent([-180, 180, -60, 85], crs=ccrs.PlateCarree())
        P.degree_axes(ax, range(-180, 181, 60), range(-60, 91, 30))
        cb = fig.colorbar(mesh, ax=ax, orientation='horizontal', fraction=0.06, pad=0.1, extend='both')
        cb.ax.tick_params(labelsize=5); P.attach(ax, cb.ax)
        ax.set_title(title, loc='left', fontsize=6)
        P.panel_letter(ax, chr(97 + i), x=-0.05)
        groups.setdefault(['ab', 'cd', 'ef'][i // 2], []).append(ax)
    fig.tight_layout()
    P.export(fig, folder, 'grid_change_maps', groups, dict(projection='PlateCarree', display='1-degree area-weighted, four-model mean'))


def plot_trends(series, ens_c, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 3, figsize=(183 * P.MM, 205 * P.MM))
    g = series[series.region == 'GLOBAL']
    groups = {}
    for i, (product, label) in enumerate(WEATHER):
        ax = axes.flat[i]
        for ssp in SSPS:
            piv = g[(g['product'] == product) & (g.ssp == ssp)].pivot(index='year', columns='model', values='days')
            P.model_band(ax, piv.index, piv, ssp)
        e = ens_c[(ens_c.region == 'GLOBAL') & (ens_c['product'] == product) & (ens_c.contrast == 'ssp585-ssp126')].iloc[0]
        ax.text(0.02, 0.97, f"2050s 585-126: {e['mean']:+.2f} d ({e['support']}/4)", transform=ax.transAxes,
                fontsize=5.5, va='top')
        ax.set_title(label, loc='left'); ax.set_xlim(2015, 2060)
        lo, hi = ax.get_ylim(); ax.set_ylim(lo, hi + 0.15 * (hi - lo))
        if i % 3 == 0:
            ax.set_ylabel('Exposure (days yr$^{-1}$)')
        P.panel_letter(ax, chr(97 + i), x=-0.18)
        groups[chr(97 + i)] = [ax]
    leg = axes.flat[11]
    for ssp in SSPS:
        leg.plot([], [], color=SSP_COLORS[ssp], label=P.SSP_LABELS[ssp])
    leg.fill_between([], [], [], color='0.6', alpha=0.3, label='Four-model min-max')
    leg.legend(loc='center left', fontsize=7); leg.axis('off')
    groups['a'].append(leg)
    fig.tight_layout()
    P.export(fig, folder, 'grid_weather_trends', groups,
             dict(domain='common land support of all models, SSPs and products', unit='days per year (24 h)'))


def plot_contrast_matrix(ens_c, map_keys, map_days, products, folder):
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import cartopy.crs as ccrs
    fig = plt.figure(figsize=(183 * P.MM, 175 * P.MM))
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1.05], hspace=0.32, left=0.12, right=0.86, top=0.95, bottom=0.06)
    ax = fig.add_subplot(gs[0])
    items = WEATHER + EXTRA
    mat = np.full((len(REGIONS), len(items)), np.nan); sup = np.zeros_like(mat)
    for j, (product, _) in enumerate(items):
        for i, region in enumerate(REGIONS):
            e = ens_c[(ens_c.region == region) & (ens_c['product'] == product) & (ens_c.contrast == 'ssp585-ssp126')].iloc[0]
            mat[i, j] = e['mean']; sup[i, j] = e['support']
    lim = np.nanmax(np.abs(mat))
    norm = mcolors.SymLogNorm(linthresh=0.5, vmin=-lim, vmax=lim)
    im = ax.imshow(mat, cmap='RdBu_r', norm=norm, aspect='auto')
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f'{mat[i, j]:+.2f}' + ('*' if sup[i, j] == 4 else ''), ha='center', va='center', fontsize=4.8,
                    color='white' if abs(mat[i, j]) > 0.5 * lim else 'black')
    short = {'union:all': 'All (cross-tech union)', 'wind:any': 'Wind-relevant union', 'solar:any': 'Solar-relevant union',
             'solar:icing': 'Icing (solar axis)', 'wind:icing': 'Icing (native axis)'}
    ax.set_xticks(range(len(items)), [short.get(p, l) for p, l in items], rotation=35, ha='right', fontsize=5.5)
    ax.set_yticks(range(len(REGIONS)), ['Global land'] + [r for r in REGIONS[1:]])
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01); cb.set_label('2050s SSP5-8.5 - SSP1-2.6 (days yr$^{-1}$)')
    P.attach(ax, cb.ax)
    ax.set_title('Grid exposure difference by latitude band, 2050s (* all four models agree in sign)', loc='left')
    P.panel_letter(ax, 'a', x=-0.08)
    mx = fig.add_subplot(gs[1], projection=ccrs.PlateCarree())
    pi = products.index('union:all')
    diff = (map_days[:, 2, pi, 3] - map_days[:, 0, pi, 3])
    mean = diff.mean(axis=0)
    agree = (np.sign(diff) == np.sign(mean)).sum(axis=0) >= 3
    grid = np.full((180, 360), np.nan)
    lat_i, lon_i = map_keys // 360, map_keys % 360
    grid[lat_i, lon_i] = mean
    mesh = mx.pcolormesh(np.arange(-180, 181), np.arange(-90, 91), grid, cmap='RdBu_r', vmin=-15, vmax=15,
                         transform=ccrs.PlateCarree(), shading='flat')
    hatch = np.full((180, 360), np.nan); hatch[lat_i[~agree], lon_i[~agree]] = 1
    mx.contourf(np.arange(-179.5, 180), np.arange(-89.5, 90), hatch, levels=[0.5, 1.5], hatches=['////'], colors='none',
                transform=ccrs.PlateCarree())
    P.draw_borders(mx); mx.set_extent([-180, 180, -60, 85], crs=ccrs.PlateCarree())
    P.degree_axes(mx, range(-180, 181, 60), range(-60, 91, 30))
    cb2 = fig.colorbar(mesh, ax=mx, orientation='horizontal', fraction=0.05, pad=0.08, extend='both')
    cb2.set_label('Cross-technology weather union, 2050s SSP5-8.5 - SSP1-2.6 (days yr$^{-1}$); hatched: < 3/4 models agree')
    P.attach(mx, cb2.ax)
    mx.set_title('Where the cross-technology exposure changes (1-degree area-weighted display grid)', loc='left')
    P.panel_letter(mx, 'b', x=-0.03)
    P.export(fig, folder, 'grid_contrasts', {'a': [ax], 'b': [mx]},
             dict(projection='PlateCarree', colour_scale_a='symmetric log, linear within +-0.5 day'))


def plot_icing(series, ens_c, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(183 * P.MM, 58 * P.MM), gridspec_kw=dict(width_ratios=[1.2, 1, 1.1]))
    g = series[series.region == 'GLOBAL']
    ax = axes[0]
    for product, ls in (('wind:icing', '-'), ('solar:icing', '--')):
        for ssp in ('ssp126', 'ssp585'):
            piv = g[(g['product'] == product) & (g.ssp == ssp)].pivot(index='year', columns='model', values='days')
            ax.plot(piv.index, piv.mean(axis=1), color=SSP_COLORS[ssp], ls=ls,
                    label=f"{P.SSP_LABELS[ssp]}, {'native T/RH steps' if product.startswith('wind') else 'interpolated to radiation steps'}")
    ax.set_ylabel('Global icing exposure (days yr$^{-1}$)'); ax.set_title('Same threshold, two time axes', loc='left')
    ax.legend(fontsize=5, loc='upper left', bbox_to_anchor=(0, -0.12), ncol=1); ax.set_xlim(2015, 2060)
    ax = axes[1]
    ratio = []
    for ssp in SSPS:
        a = g[(g['product'] == 'wind:icing') & (g.ssp == ssp)].groupby('year').days.mean()
        b = g[(g['product'] == 'solar:icing') & (g.ssp == ssp)].groupby('year').days.mean()
        ax.plot(a.index, (b / a - 1) * 100, color=SSP_COLORS[ssp], label=P.SSP_LABELS[ssp])
    ax.axhline(0, color='k', lw=0.5); ax.set_ylabel('Interpolated vs native (%)'); ax.set_xlim(2015, 2060)
    ax.set_title('Relative level difference', loc='left'); ax.legend(fontsize=5)
    ax = axes[2]
    x = np.arange(len(REGIONS))
    for k, (product, color) in enumerate((('wind:icing', '#3b6ea8'), ('solar:icing', '#9ecae1'))):
        e = ens_c[(ens_c['product'] == product) & (ens_c.contrast == 'ssp585-ssp126')].set_index('region').reindex(list(REGIONS))
        ax.bar(x + (k - 0.5) * 0.38, e['mean'], width=0.36, color=color,
               label='Native time axis (wind product)' if k == 0 else 'Radiation time axis (solar product)')
        ax.errorbar(x + (k - 0.5) * 0.38, e['mean'], yerr=[e['mean'] - e['min'], e['max'] - e['mean']], fmt='none', ecolor='0.3', lw=0.6)
        for xi, s in zip(x, e.support):
            ax.text(xi + (k - 0.5) * 0.38, 0, f'{s}', fontsize=4.5, ha='center', va='bottom' if k else 'top')
    ax.axhline(0, color='k', lw=0.5); ax.set_xticks(x, ['Global'] + list(REGIONS[1:]), rotation=30, ha='right')
    ax.set_ylabel('2050s SSP5-8.5 - SSP1-2.6 (days yr$^{-1}$)'); ax.set_title('SSP contrast (numbers: model support)', loc='left')
    ax.legend(fontsize=5, loc='lower left')
    for i, a in enumerate(axes):
        P.panel_letter(a, chr(97 + i), x=-0.22)
    fig.tight_layout()
    P.export(fig, folder, 'icing_time_axis', {'a': [axes[0]], 'b': [axes[1]], 'c': [axes[2]]})


def plot_humidity(hist, wm, mech_ens, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(183 * P.MM, 110 * P.MM))
    centers = np.r_[-0.5, np.arange(0.5, 100), 100.5]
    for c, region in enumerate(('GLOBAL', '0-30S', '60-90N')):
        ax = axes[0, c]
        h = hist[(hist.region == region) & (hist.window == '2050-2059')]
        for ssp in SSPS:
            piv = h[h.ssp == ssp].pivot(index='bin', columns='model', values='prob') * 100
            P.model_band(ax, centers[piv.index], piv, ssp)
        h0 = hist[(hist.region == region) & (hist.window == '2015-2024') & (hist.ssp == 'ssp126')].groupby('bin').prob.mean() * 100
        ax.plot(centers[h0.index], h0, color='0.4', lw=0.7, ls=':', label='2015-2024 (SSP1-2.6 run)')
        for t in (85, 95):
            ax.axvline(t, color='0.5', lw=0.4, ls='--')
        ax.set_xlim(20, 101); ax.set_xlabel('Near-surface relative humidity (%)')
        ax.set_ylabel('Area-time share per 1% bin (%)')
        ax.set_title({'GLOBAL': 'Global land', '0-30S': '0-30$^\\circ$S', '60-90N': '60-90$^\\circ$N'}[region] + ', 2050s', loc='left')
        ax = axes[1, c]
        a = wm[wm.region == region]
        for i, ssp in enumerate(SSPS):
            v = a[a.ssp == ssp].groupby('window').RH.agg(['mean', 'min', 'max']).reindex(['2015-2024', '2050-2059'])
            xs = np.arange(2) + (i - 1) * 0.26
            ax.bar(xs, v['mean'], width=0.25, color=SSP_COLORS[ssp], label=P.SSP_LABELS[ssp])
            ax.errorbar(xs, v['mean'], yerr=[v['mean'] - v['min'], v['max'] - v['mean']], fmt='none', ecolor='0.25', lw=0.6)
        lo = a.RH.min(); hi = a.RH.max(); pad = 0.25 * (hi - lo) + 0.2
        ax.set_ylim(lo - pad, hi + pad); ax.set_xticks([0, 1], ['2015-2024', '2050-2059'])
        ax.set_ylabel('Window mean RH (%)')
        e = mech_ens[(mech_ens.region == region) & (mech_ens.contrast == 'ssp585-ssp126')].iloc[0]
        ax.set_title(f"585-126 2050s: RH {e.dRH:+.2f} pp, ln e {100 * e.dlne:+.1f}%, ln e$_s$ {100 * e.dlnes:+.1f}%",
                     loc='left', fontsize=5.5)
    for i, ax in enumerate(axes.T.flat):
        P.panel_letter(ax, chr(97 + i), x=-0.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=4, fontsize=5, frameon=False, bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    P.export(fig, folder, 'humidity', {'ab': list(axes[:, 0]), 'cd': list(axes[:, 1]), 'ef': list(axes[:, 2])},
             dict(note='ln RH = ln e - ln e_s holds exactly per sample (Magnus over water)'))


def plot_highlat(mon, mech_ens, series, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(183 * P.MM, 105 * P.MM))
    m = mon.groupby('month').mean(numeric_only=True)
    lo = mon.groupby('month').min(numeric_only=True); hi = mon.groupby('month').max(numeric_only=True)
    months = m.index
    panels = ((('cold_126', 'cold_585'), 'P(T < -2$^\\circ$C) (%)', 100),
              (('hgc_126', 'hgc_585'), 'P(RH $\\geq$ 85% | T < -2$^\\circ$C) (%)', 100),
              (('joint_126', 'joint_585'), 'P(icing condition) (%)', 100))
    for k, (cols, label, scale) in enumerate(panels):
        ax = axes[0, k]
        for col, ssp in zip(cols, ('ssp126', 'ssp585')):
            ax.plot(months, m[col] * scale, color=SSP_COLORS[ssp], marker=P.SSP_MARKERS[ssp], ms=2.5, label=P.SSP_LABELS[ssp])
            ax.fill_between(months, lo[col] * scale, hi[col] * scale, color=SSP_COLORS[ssp], alpha=0.15, lw=0)
        ax.set_xticks(range(1, 13), list('JFMAMJJASOND')); ax.set_ylabel(label)
        ax.set_title('60-90$^\\circ$N, 2050s', loc='left')
        if k == 0:
            ax.legend(fontsize=5)
    ax = axes[1, 0]
    ax.bar(months - 0.2, m.cold_term * 100, width=0.4, color='#6baed6', label='Fewer cold hours')
    ax.bar(months + 0.2, m.hum_term * 100, width=0.4, color='#fd8d3c', label='Higher humidity when cold')
    ax.plot(months, (m.joint_585 - m.joint_126) * 100, 'kD', ms=2.5, label='Net change')
    ax.axhline(0, color='k', lw=0.5); ax.set_xticks(range(1, 13), list('JFMAMJJASOND'))
    ax.set_ylabel('Contribution to joint change (pp)'); ax.set_title('Decomposition, 585 - 126', loc='left'); ax.legend(fontsize=5)
    ax = axes[1, 1]
    delta = mon.assign(drsds=mon.rsds_585 - mon.rsds_126, drh=(mon.rh95_585 - mon.rh95_126) * 100)
    band = delta.groupby('month')[['drsds', 'drh']].agg(['mean', 'min', 'max'])
    ax.plot(months, band[('drsds', 'mean')], color='#9e1b1b', marker='o', ms=2.5, label='Surface solar radiation')
    ax.fill_between(months, band[('drsds', 'min')], band[('drsds', 'max')], color='#9e1b1b', alpha=0.15, lw=0)
    ax.axhline(0, color='k', lw=0.5); ax.set_xticks(range(1, 13), list('JFMAMJJASOND'))
    ax.set_ylabel('$\\Delta$ rsds, 585 - 126 (W m$^{-2}$)')
    ax2 = ax.twinx()
    ax2.plot(months, band[('drh', 'mean')], color='#2b8cbe', ls='--', marker='s', ms=2.5, label='P(RH $\\geq$ 95%)')
    ax2.fill_between(months, band[('drh', 'min')], band[('drh', 'max')], color='#2b8cbe', alpha=0.12, lw=0)
    ax2.set_ylabel('$\\Delta$ P(RH $\\geq$ 95%) (pp)', color='#2b8cbe'); ax2.spines['right'].set_visible(True)
    P.attach(ax, ax2)
    first, first_labels = ax.get_legend_handles_labels()
    second, second_labels = ax2.get_legend_handles_labels()
    ax.legend(first + second, first_labels + second_labels, fontsize=5, loc='upper center')
    ax.set_title('Radiation and humidity changes', loc='left')
    ax = axes[1, 2]
    g = series[series.region == '60-90N']
    for product, ls in (('solar:low_resource', '-'), ('solar:high_humidity', '--')):
        for ssp in ('ssp126', 'ssp585'):
            piv = g[(g['product'] == product) & (g.ssp == ssp)].pivot(index='year', columns='model', values='days')
            ax.plot(piv.index, piv.mean(axis=1), color=SSP_COLORS[ssp], ls=ls, lw=0.9, label=P.SSP_LABELS[ssp] if product == 'solar:low_resource' else None)
    ax.plot([], [], 'k-', label='Low solar resource'); ax.plot([], [], 'k--', label='High humidity')
    ax.legend(fontsize=5, ncol=2, loc='upper left', bbox_to_anchor=(0.0, -0.18), frameon=False)
    ax.set_xlim(2015, 2060); ax.set_ylabel('Exposure (days yr$^{-1}$)')
    ax.set_title('60-90$^\\circ$N event exposure', loc='left')
    for i, a in enumerate(axes.flat):
        P.panel_letter(a, chr(97 + i), x=-0.22)
    fig.tight_layout()
    P.export(fig, folder, 'highlat_mechanism', {'abc': list(axes[0]), 'def': list(axes[1])})


def plot_resources(mech_ens, ens_c, folder):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(183 * P.MM, 105 * P.MM))
    x = np.arange(len(REGIONS)); labels = ['Global'] + list(REGIONS[1:])
    panels = ((axes[0, 0], 'dws_pct', 'Mean 10-m wind speed change (%)', mech_ens),
              (axes[0, 1], 'drsds_pct', 'Mean surface solar radiation change (%)', mech_ens),
              (axes[1, 0], 'wind:low_resource', 'Low wind resource exposure change (days yr$^{-1}$)', ens_c),
              (axes[1, 1], 'solar:low_resource', 'Low solar resource exposure change (days yr$^{-1}$)', ens_c))
    for ax, var, label, table in panels:
        pending = []
        for i, ssp in enumerate(SSPS):
            contrast = f'{ssp}:2050s-2015_24'
            if table is mech_ens:
                e = table[table.contrast == contrast].set_index('region').reindex(list(REGIONS))
                vals, sup = e[var], e[f'{var}_support']
            else:
                e = table[(table['product'] == var) & (table.contrast == contrast)].set_index('region').reindex(list(REGIONS))
                vals, sup = e['mean'], e['support']
            ax.bar(x + (i - 1) * 0.27, vals, width=0.26, color=SSP_COLORS[ssp], label=P.SSP_LABELS[ssp])
            pending.append((vals, sup, i))
        ax.axhline(0, color='k', lw=0.5); ax.set_xticks(x, labels); ax.set_ylabel(label)
        lo, hi = ax.get_ylim(); span = hi - lo
        ax.set_ylim(lo - 0.08 * span, hi + 0.22 * span)
        for vals, sup, i in pending:
            for xi, v, s in zip(x, vals, sup):
                if int(s) < 4:
                    ax.text(xi + (i - 1) * 0.27, v + (0.03 * span if v >= 0 else -0.03 * span), str(int(s)),
                            fontsize=5, ha='center', va='bottom' if v >= 0 else 'top')
        ax.set_title('2050-2059 minus 2015-2024 (numbers: model support below 4/4)', loc='left', fontsize=6)
    axes[0, 0].legend(fontsize=5)
    for i, a in enumerate(axes.flat):
        P.panel_letter(a, chr(97 + i), x=-0.13)
    fig.tight_layout()
    P.export(fig, folder, 'resource_changes', {'ab': list(axes[0]), 'cd': list(axes[1])},
             dict(note='low-resource events use each SSP run\'s own 2015-2024 month-hour climatology and P5 threshold'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--summary', type=Path, default=OUT / 'grid_summary')
    p.add_argument('--meteo', type=Path, default=OUT / 'grid_meteo')
    p.add_argument('--output', type=Path, default=OUT / 'grid_analysis')
    p.add_argument('--reuse', action='store_true', help='reuse exposure source tables written by an earlier run')
    p.add_argument('--replot', action='store_true', help='redraw the humidity, high-latitude and resource figures from saved tables')
    a = p.parse_args()
    P.configure()
    src = a.output / 'source_data'
    if a.replot:
        plot_humidity(pd.read_csv(src / 'rh_histograms.csv.gz'), pd.read_csv(src / 'meteo_window.csv.gz'),
                      pd.read_csv(src / 'mechanism_ensemble.csv.gz'), a.output)
        plot_highlat(pd.read_csv(src / 'highlat_monthly.csv.gz'), pd.read_csv(src / 'mechanism_ensemble.csv.gz'),
                     pd.read_csv(src / 'annual_exposure.csv.gz'), a.output)
        plot_resources(pd.read_csv(src / 'mechanism_ensemble.csv.gz'), pd.read_csv(src / 'contrasts_ensemble.csv'), a.output)
        return
    if a.reuse and (src / 'map_1deg.npz').exists():
        series = pd.read_csv(src / 'annual_exposure.csv.gz')
        z = np.load(src / 'map_1deg.npz')
        products, map_keys, map_area, map_days = list(z['products']), z['keys'], z['area'], z['days']
    else:
        series, products, map_keys, map_area, map_days = exposure_series(a.summary)
    per_c, ens_c = contrasts(series)
    per_s, ens_s = slopes(series)
    write_csv(src / 'annual_exposure.csv.gz', series); write_csv(src / 'contrasts_models.csv', per_c)
    write_csv(src / 'contrasts_ensemble.csv', ens_c); write_csv(src / 'slopes_models.csv', per_s)
    write_csv(src / 'slopes_ensemble.csv', ens_s)
    np.savez_compressed(src / 'map_1deg.npz', keys=map_keys, area=map_area, days=map_days, products=np.array(products),
                        models=np.array(MODELS), ssps=np.array(SSPS))
    cc = country_contributions(map_keys, map_area, map_days, products)
    write_csv(src / 'high_humidity_country_bins.csv.gz', cc)
    plot_trends(series, ens_c, a.output)
    plot_contrast_matrix(ens_c, map_keys, map_days, products, a.output)
    plot_icing(series, ens_c, a.output)
    if a.meteo.exists():
        annual, monthly, hist = meteo_tables(meteo(a.meteo))
        wm = window_means(monthly)
        per_m, ens_m, mon = mechanism_contrasts(wm, monthly)
        for name, frame in dict(meteo_annual=annual, meteo_monthly=monthly, rh_histograms=hist, meteo_window=wm,
                                mechanism_models=per_m, mechanism_ensemble=ens_m, highlat_monthly=mon).items():
            write_csv(src / f'{name}.csv.gz', frame)
        mmaps = meteo_maps(a.meteo)
        plot_maps(mmaps, map_keys, map_days, products, a.output)
        plot_humidity(hist, wm, ens_m, a.output)
        plot_highlat(mon, ens_m, series, a.output)
        plot_resources(ens_m, ens_c, a.output)
        pd.set_option('display.width', 250); pd.set_option('display.max_columns', 60)
        print(ens_m.round(4).to_string())
    pd.set_option('display.width', 250)
    print(ens_c[ens_c.contrast == 'ssp585-ssp126'].round(3).to_string())
    print(ens_s[ens_s.region == 'GLOBAL'].round(3).to_string())


if __name__ == '__main__':
    main()
