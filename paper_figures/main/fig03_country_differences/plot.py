"""Render all six Fig. 3 panels from audited existing country data."""
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.text import Text
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from PIL import Image
from paper_figures.config import ROOT, TECHS, SNAPSHOTS
from paper_figures.common.io import digest, write_json
from paper_figures.common.plotting import configure, save_png, export_panel_png
from paper_figures.common.spatial import countries

FOLDER = ROOT / 'paper_figures/main/fig03_country_differences'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
COLORS = {'higher_585': '#af4d48', 'higher_126': '#496e9c',
          'unclear': '#a8a8a8', 'unavailable': '#eeeeee'}
LABELS = {'higher_585': 'SSP585 higher', 'higher_126': 'SSP126 higher',
          'unclear': 'Unclear direction', 'unavailable': 'No comparable result'}
UNIT = 'MWh MW⁻¹ yr⁻¹'


def title(fig, x, y, letter, text):
    fig.text(x, y, letter, fontsize=8, fontweight='bold', va='bottom')
    fig.text(x+0.026, y, text, fontsize=7, va='bottom')


def main():
    audit = json.loads((OUT / 'data_audit.json').read_text())
    assert audit['status'] == 'PASSED'
    ab = pd.read_csv(SOURCE / 'panel_ab.csv')
    cd = pd.read_csv(SOURCE / 'panel_cd.csv')
    e = pd.read_csv(SOURCE / 'panel_e_display.csv')
    f = pd.read_csv(SOURCE / 'panel_f.csv')
    selection = pd.read_csv(SOURCE / 'country_selection.csv').sort_values('order')
    colour_values = pd.concat([ab['mean'], cd['mean']]).dropna()
    limit = float(max(5, np.ceil(np.quantile(np.abs(colour_values), .95) / 5) * 5))
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6.5, 'xtick.labelsize': 6, 'ytick.labelsize': 6,
                         'axes.linewidth': 0.6, 'xtick.major.width': 0.5,
                         'ytick.major.width': 0.5, 'xtick.major.size': 2,
                         'ytick.major.size': 2, 'hatch.linewidth': 0.25,
                         'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183/25.4, 165/25.4), facecolor='white')
    cmap = plt.get_cmap('RdBu_r').copy()
    cmap.set_bad(COLORS['unavailable'])
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
    geo = countries()
    pc = ccrs.PlateCarree()
    for col, tech in enumerate(TECHS):
        left = 0.035 + col * 0.5
        title(fig, left-0.014, 0.970, 'ab'[col], f'{tech.title()} | Country pathway difference')
        ax = fig.add_axes([left, 0.765, 0.445, 0.185], projection=pc)
        ax.set_extent([-180, 180, -60, 85], crs=pc)
        table = ab[ab.tech.eq(tech)].set_index('country')
        for iso, _, geom in geo:
            value = table.loc[iso, 'mean'] if iso in table.index else np.nan
            unclear = np.isfinite(value) and table.loc[iso, 'category'] == 'unclear'
            ax.add_geometries([geom], pc, facecolor=cmap(norm(value)) if np.isfinite(value) else COLORS['unavailable'],
                              edgecolor='#777777', linewidth=0.2, hatch='///' if unclear else None)
        ax.gridlines(xlocs=[-120, 0, 120], ylocs=[0, 60],
                     linewidth=0.25, color='#888888', alpha=0.45, linestyle=':')
        ax.set_xticks([-120, 0, 120], crs=pc)
        ax.set_yticks([0, 60], crs=pc)
        ax.xaxis.set_major_formatter(LongitudeFormatter())
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(axis='both', labelsize=5.5, pad=2, length=2)
        ax.spines['geo'].set_linewidth(0.4)
        ax.text(0.5, 1.045, '2050–2059 · paired SSP585 − SSP126', transform=ax.transAxes,
                ha='center', va='bottom', fontsize=6)
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
                      cax=fig.add_axes([0.105, 0.717, 0.34, 0.011]),
                      orientation='horizontal', ticks=np.linspace(-limit, limit, 7),
                      extend='both', extendfrac=.04)
    cb.outline.set_linewidth(0.4)
    cb.set_label(f'Pathway difference ({UNIT}); panels a–d', labelpad=2, fontsize=6)
    fig.legend(handles=[Patch(facecolor='white', edgecolor='#777777', hatch='///',
                              label='Hatching / ○: <3 of 4 models agree'),
                        Patch(facecolor=COLORS['unavailable'], edgecolor='#bbbbbb',
                              label='No comparable result')],
               loc='center left', bbox_to_anchor=(0.535, 0.714), fontsize=6,
               handlelength=1.5, handleheight=0.9, labelspacing=0.6)
    for col, tech in enumerate(TECHS):
        title(fig, 0.021+col*0.5, 0.658, 'cd'[col], f'{tech.title()} | Country trajectories')
        ax = fig.add_axes([0.115+col*0.5, 0.343, 0.355, 0.299])
        table = cd[cd.tech.eq(tech)].set_index(['country', 'snapshot'])
        values = np.array([[table.loc[(country, snap), 'mean'] for snap in SNAPSHOTS]
                           for country in selection.country])
        ax.imshow(values, cmap=cmap, norm=norm, aspect='auto', interpolation='nearest')
        for row, country in enumerate(selection.country):
            for column, snap in enumerate(SNAPSHOTS):
                item = table.loc[(country, snap)]
                if item.category == 'unclear':
                    ax.scatter(column, row, s=10, facecolors='none', edgecolors='#222222', linewidths=0.45)
        ax.set_xticks(range(3), ['2030s', '2040s', '2050s'])
        ax.set_yticks(range(len(selection)), selection.country, fontsize=6.3)
        ax.tick_params(axis='both', length=0, pad=3)
        ax.set_xticks(np.arange(-0.5, 3, 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(selection), 1), minor=True)
        ax.grid(which='minor', color='white', linewidth=0.35)
        ax.tick_params(which='minor', length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.text(0.5, 0.308, '2030s = 2030–2039; 2040s = 2040–2049; 2050s = 2050–2059',
             ha='center', fontsize=5.8)
    title(fig, 0.021, 0.280, 'e', 'Country distribution and global result | 2050s')
    ax = fig.add_axes([0.110, 0.090, 0.355, 0.175])
    rng = np.random.default_rng(3026)
    counts, global_records = [], []
    for col, tech in enumerate(TECHS):
        country = ab[ab.tech.eq(tech) & ab['mean'].notna()].sort_values('country')
        values = country['mean'].to_numpy()
        counts.append(len(values))
        ax.boxplot([values], positions=[col], widths=0.45, patch_artist=True, showfliers=False,
                   boxprops={'facecolor': '#f4f4f4', 'edgecolor': '#444444', 'linewidth': 0.6},
                   medianprops={'color': '#222222', 'linewidth': 0.9},
                   whiskerprops={'color': '#444444', 'linewidth': 0.6},
                   capprops={'color': '#444444', 'linewidth': 0.6})
        jitter = rng.uniform(-0.18, 0.18, len(country))
        for category, marker in [('higher_585', '^'), ('higher_126', 'v'), ('unclear', 'o')]:
            mask = country.category.eq(category).to_numpy()
            ax.scatter(col+jitter[mask], values[mask], s=5, marker=marker,
                       color=COLORS[category], alpha=0.7, linewidths=0, zorder=3)
        global_ = e[e.tech.eq(tech) & e.country.eq('GLOBAL')].iloc[0]
        ax.errorbar(col+0.31, global_['mean'],
                    yerr=[[global_['mean']-global_.minimum], [global_.maximum-global_['mean']]],
                    fmt='D', color='#111111', markersize=2.5, elinewidth=0.65,
                    capsize=2.5, capthick=0.65, markeredgecolor='white',
                    markeredgewidth=0.3, zorder=5)
        global_records.append(dict(tech=tech, mean=float(global_['mean']),
                                   minimum=float(global_.minimum), maximum=float(global_.maximum)))
    ax.axhline(0, color='#777777', linewidth=0.5, linestyle='--', zorder=1)
    ax.set_xlim(-0.45, 1.55)
    ax.set_xticks([0, 1], [f'Wind (n={counts[0]})', f'Solar (n={counts[1]})'])
    ax.set_ylabel(f'Pathway difference\n({UNIT})', labelpad=3)
    global_rows = e[e.country.eq('GLOBAL')]
    distribution_min = min(ab['mean'].min(), global_rows.minimum.min())
    distribution_max = max(ab['mean'].max(), global_rows.maximum.max())
    distribution_limits = [float(np.floor(distribution_min/25)*25),
                           float(np.ceil(distribution_max/25)*25)]
    ax.set_ylim(*distribution_limits)
    ax.set_yticks(np.arange(-100, 101, 50))
    fig.legend(handles=[Line2D([], [], color='#111111', marker='D', markersize=3, linewidth=0.7,
                               label='Global mean; 4-model min–max')],
               loc='center', bbox_to_anchor=(0.285, 0.049), fontsize=5.8)
    fig.text(0.285, 0.020, 'Box: country median / IQR; whiskers: 1.5 IQR', ha='center', fontsize=5.8)
    title(fig, 0.521, 0.280, 'f', 'Country and capacity shares | 2050s')
    ax = fig.add_axes([0.670, 0.090, 0.240, 0.175])
    labels = []
    for row, (tech, metric) in enumerate([('wind','country_pct'), ('wind','capacity_pct'),
                                         ('solar','country_pct'), ('solar','capacity_pct')]):
        table = f[f.tech.eq(tech)].set_index('category')
        start = 0.0
        for category in COLORS:
            width = float(table.loc[category, metric])
            ax.barh(row, width, left=start, height=0.58, color=COLORS[category],
                    edgecolor='white', linewidth=0.4,
                    hatch='///' if category == 'unavailable' else None)
            if width >= 10:
                ax.text(start+width/2, row, f'{width:.0f}%', ha='center', va='center',
                        fontsize=5.8, color='white' if category in ['higher_585','higher_126'] else '#222222')
            start += width
        if metric == 'country_pct':
            total = f"{int(table.total_countries.iloc[0])}"
            label = tech.title()+'\nCountries'
        else:
            total = f"{table.reference_capacity_mw.sum()/1000:,.0f}\nGW"
            label = tech.title()+'\nCapacity'
        labels.append(label)
        ax.text(103, row, total, ha='left', va='center', fontsize=5.5, clip_on=False)
    ax.set_ylim(3.65, -0.65)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 50, 100])
    ax.set_yticks(range(4), labels, fontsize=5.8)
    ax.tick_params(axis='y', length=0, pad=4)
    ax.set_xlabel('Share (%)', labelpad=2)
    ax.spines['left'].set_visible(False)
    fig.legend(handles=[Patch(facecolor=COLORS[k], edgecolor='#aaaaaa' if k=='unavailable' else 'none',
                              hatch='///' if k=='unavailable' else None, label=LABELS[k]) for k in COLORS],
               loc='center', bbox_to_anchor=(0.75, 0.030), ncol=2, fontsize=5.8,
               handlelength=1.1, columnspacing=1.0, labelspacing=0.5)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        bbox = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
        if bbox.x0 < -0.002 or bbox.y0 < -0.002 or bbox.x1 > 1.002 or bbox.y1 > 1.002:
            outside.append(artist.get_text())
    if outside:
        raise ValueError(f'Text outside figure canvas: {outside}')
    fig.add_artist(Rectangle((0,0), 1,1, transform=fig.transFigure, fill=False, edgecolor='none', linewidth=0))
    save_png(fig, OUT / 'fig03.png')
    panel_outputs = []
    for group, bounds in [('ab', [0, .66, 1, 1]),
                          ('abcd', [0, .301, 1, 1]),
                          ('ef', [0, 0, 1, .301])]:
        hidden = [t for t in fig.texts if group == 'ab' and t.get_position()[1] == .658]
        for text in hidden:
            text.set_visible(False)
        panel_outputs.append(export_panel_png(fig, OUT / f'fig03_{group}.png',
                                               bounds=bounds, close=False))
        for text in hidden:
            text.set_visible(True)
    plt.close(fig)
    with Image.open(OUT / 'fig03.png') as im:
        image_info = dict(pixels=list(im.size), dpi=list(im.info.get('dpi', [])))
        im.verify()
    with Image.open(OUT / 'fig03.png') as im:
        qa = OUT / 'qa'
        qa.mkdir(exist_ok=True)
        width, height = im.size
        im.crop((0, int(height*0.71), width, height)).save(qa / 'panel_ef.png')
        im.crop((0, 0, width, int(height*0.31))).save(qa / 'panel_ab.png')
    sources = sorted(p for p in SOURCE.iterdir() if p.is_file())
    write_json(OUT / 'metadata.json', dict(figure='Fig. 3', created_utc=datetime.now(timezone.utc).isoformat(),
               job_id=os.environ.get('SLURM_JOB_ID'), backend='Python/matplotlib + Cartopy',
               map_projection='Plate Carrée', map_extent_degrees=[-180,180,-60,85],
               canvas_mm=[183,165], image=image_info, panels=list('abcdef'),
               colour_limits=[-limit,limit], colour_limit_quantile=.95, colour_extend='both',
               colour_scale_values=len(colour_values),
               below_colour_scale=int((colour_values < -limit).sum()),
               above_colour_scale=int((colour_values > limit).sum()),
               distribution_y_limits=distribution_limits, values_clipped=int((colour_values.abs()>limit).sum()),
               panel_outputs=panel_outputs,
               text_outside_canvas=outside, data_audit='PASSED', visual_review='PENDING',
               global_results=global_records, png_sha256=digest(OUT/'fig03.png'),
               source_data=[dict(path=str(p.relative_to(OUT)),sha256=digest(p)) for p in sources],
               code_sha256={p.name:digest(p) for p in [FOLDER/'plot.py',FOLDER/'prepare_data.py']}))
    print(json.dumps(dict(png=str(OUT/'fig03.png'), image=image_info, colour_limit=limit)), flush=True)


if __name__ == '__main__':
    main()
