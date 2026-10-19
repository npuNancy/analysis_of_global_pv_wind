"""2050s SSP585 minus SSP126: climate mechanisms and layout waterfalls."""
import itertools
import json
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS, STATION_FILES
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.metrics import climate_deployment, three_factor
from paper_figures.common.plotting import configure, export_panel_png

FOLDER = ROOT / 'paper_figures/main/fig02_generation_loss'
OUT = FOLDER / 'outputs'
SOURCE = OUT / 'source_data'
STEM = 'fig02_climate_layout_waterfall_2050s'
INPUT = OUTPUT / 'loss_summary/window.csv.gz'
TERMS = ('climate_exposure', 'climate_normal_cf', 'climate_relative_loss', 'layout', 'gap')
COLORS = ('#9EC3D3', '#A6BCA6', '#C99581', '#D39A54', '#30363C')
UNIT = 'MWh MW⁻¹ yr⁻¹'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(snapshot=2050, save=True):
    require(snapshot in (2030, 2040, 2050), "Unsupported capacity snapshot")
    require_complete(INPUT.parent)
    parts = []
    for chunk in pd.read_csv(INPUT, chunksize=50000):
        take = (chunk.country.eq('GLOBAL') & chunk.snapshot.eq(snapshot)
                & chunk.event.eq('all') & chunk.support.eq('common'))
        parts.append(chunk.loc[take])
    inputs = pd.concat(parts, ignore_index=True)
    keys = ['model', 'tech', 'climate_ssp', 'station_ssp']
    expected = set(itertools.product(MODELS, TECHS, SSPS, SSPS))
    require(not inputs.duplicated(keys).any(), 'Duplicate global combination')
    require(set(inputs[keys].itertuples(index=False, name=None)) == expected,
            'Incomplete four-model, two-technology, nine-combination source')
    fields = ['R', 'E_loss', 'cf_event', 'r_event', 'capacity_mw',
              'net_mwh', 'normal_event_mwh', 'capacity_event_hours']
    require(np.isfinite(inputs[fields]).all().all(), 'Nonfinite source value')
    for field in ('capacity_mw', 'capacity_event_hours', 'normal_event_mwh'):
        require(inputs[field].gt(0).all(), 'Nonpositive denominator: ' + field)
    for actual, expected_value in (
        (inputs.R, inputs.net_mwh / inputs.capacity_mw),
        (inputs.E_loss, inputs.capacity_event_hours / inputs.capacity_mw),
        (inputs.cf_event, inputs.normal_event_mwh / inputs.capacity_event_hours),
        (inputs.r_event, inputs.net_mwh / inputs.normal_event_mwh),
        (inputs.R, inputs.E_loss * inputs.cf_event * inputs.r_event),
    ):
        require(np.allclose(actual, expected_value, rtol=1e-11, atol=1e-10),
                'Source ratio identity failed')
    capacities = inputs.groupby(['tech', 'station_ssp']).capacity_mw.agg(['min', 'max'])
    require(np.allclose(capacities['min'], capacities['max'], rtol=1e-12),
            'Capacity differs across models or climates within deployment')
    inputs['window_start'], inputs['window_end'] = snapshot, snapshot + 9
    inputs['station_source'] = inputs.station_ssp.map(STATION_FILES)
    models, fixed = [], []
    for (model, tech), group in inputs.groupby(['model', 'tech']):
        indexed = group.set_index(['climate_ssp', 'station_ssp'])
        attribution = climate_deployment(indexed.R.to_dict())
        components = []
        for deployment in ('ssp126', 'ssp585'):
            base = indexed.loc[('ssp126', deployment)]
            target = indexed.loc[('ssp585', deployment)]
            factors = ['E_loss', 'cf_event', 'r_event']
            values = three_factor(base[factors].to_numpy(float), target[factors].to_numpy(float))
            delta = target.R - base.R
            require(abs(values.sum() - delta) < 1e-9, 'Fixed-deployment Shapley closure')
            components.append(values)
            fixed.append(dict(model=model, tech=tech, snapshot=snapshot,
                              window_start=snapshot, window_end=snapshot + 9, station_ssp=deployment,
                              baseline_climate_ssp='ssp126', target_climate_ssp='ssp585',
                              capacity_mw=base.capacity_mw, climate_exposure=values[0],
                              climate_normal_cf=values[1], climate_relative_loss=values[2],
                              climate_difference=delta, closure=values.sum() - delta, units=UNIT))
        mean = np.mean(components, axis=0)
        require(abs(mean.sum() - attribution['Phi_C']) < 1e-9, 'Climate contribution closure')
        values = [*mean, attribution['Phi_S'], attribution['D']]
        closure = sum(values[:4]) - values[4]
        require(abs(closure) < 1e-9, 'Four-component closure')
        models.append(dict(model=model, tech=tech, snapshot=snapshot, window_start=snapshot,
                           window_end=snapshot + 9, baseline_climate_ssp='ssp126',
                           baseline_station_ssp='ssp126', target_climate_ssp='ssp585',
                           target_station_ssp='ssp585', country='GLOBAL', event='all',
                           support='common', climate_total=attribution['Phi_C'],
                           closure=closure, units=UNIT, **dict(zip(TERMS, values))))
    models = pd.DataFrame(models)
    rows = []
    for tech, group in models.groupby('tech'):
        require(set(group.model) == set(MODELS), 'Incomplete model ensemble')
        for term in TERMS:
            rows.append(dict(tech=tech, snapshot=snapshot, term=term,
                             mean=group[term].mean(), minimum=group[term].min(),
                             maximum=group[term].max(), n_models=len(group), units=UNIT))
    summary = pd.DataFrame(rows)
    wide = summary.pivot(index='tech', columns='term', values='mean')
    require(np.allclose(wide[list(TERMS[:4])].sum(axis=1), wide.gap, atol=1e-10),
            'Ensemble waterfall closure')
    tables = {'inputs': inputs, 'fixed_deployment': pd.DataFrame(fixed),
              'models': models, 'display': summary}
    if save:
        for name, table in tables.items():
            write_csv(SOURCE / f'{STEM}_{name}.csv', table)
    return models, wide, tables


def render(wide):
    configure()
    plt.rcParams.update({'font.sans-serif': ['DejaVu Sans'], 'font.size': 6.5,
                         'axes.labelsize': 6, 'xtick.labelsize': 6, 'ytick.labelsize': 6,
                         'axes.linewidth': .6, 'xtick.major.size': 2,
                         'ytick.major.size': 2, 'savefig.pad_inches': 0})
    fig = plt.figure(figsize=(183 / 25.4, 85 / 25.4), facecolor='white')
    fig.text(.5, .94, '2050s | SSP585 − SSP126', ha='center', fontsize=8)
    axes, limits = [], {}
    for col, tech in enumerate(TECHS):
        left = .105 + col * .5
        ax = fig.add_axes([left, .31, .360, .49])
        axes.append(ax)
        fig.text(left - .08, .84, 'ab'[col], fontsize=8, fontweight='bold')
        fig.text(left - .056, .84, 'Wind' if tech == 'wind' else 'Solar', fontsize=7)
        values = wide.loc[tech, list(TERMS)].to_numpy(float)
        edges = np.r_[0, np.cumsum(values[:4]), values[4]]
        pad = max(.4, np.ptp(edges) * .20)
        limits[tech] = [float(edges.min() - pad), float(edges.max() + 1.4 * pad)]
        level = 0.
        for x, (value, color) in enumerate(zip(values, COLORS)):
            start = level if x < 4 else 0.
            end = start + value
            ax.bar(x, abs(value), bottom=min(start, end), width=.67,
                   color=color, edgecolor='white', linewidth=.3, zorder=3)
            ax.annotate(f'{value:+.2f}', (x, max(start, end)),
                        xytext=(0, 4), textcoords='offset points',
                        ha='center', va='bottom', fontsize=6,
                        fontweight='bold' if x == 4 else 'normal')
            if x < 4:
                level = end
                ax.plot([x + .335, x + .665], [level, level],
                        color='#8f969b', lw=.6, zorder=4)
        ax.axhline(0, color='#6d757b', lw=.65)
        ax.set(xlim=(-.65, 4.65), ylim=limits[tech], xticks=range(5),
               xticklabels=['Exposure', 'Normal CF\n(event)', 'Relative loss\n(event)',
                            'Layout', 'Net gap'],
               ylabel='Contribution to net-loss gap\n(' + UNIT + ')')
        ax.tick_params(axis='x', length=0, pad=5, labelsize=5.8)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.grid(axis='y', color='#dddddd', linewidth=.4)
        ax.set_axisbelow(True)
        ax.plot([-.335, -.335, 2.335, 2.335], [-.22, -.245, -.245, -.22],
                transform=ax.get_xaxis_transform(), clip_on=False, color='#6d757b', lw=.6)
        ax.text(1, -.275, 'Climate contributions', transform=ax.get_xaxis_transform(),
                ha='center', va='top', fontsize=6, color='#487A96')
    fig.text(.5, .075, 'Exact attribution within each model, then four-model means; panel y-scales differ.',
             ha='center', fontsize=6)
    fig.text(.5, .025, 'Within each deployment: unit loss = exposure × event-period normal CF × event-period relative loss.',
             ha='center', fontsize=6)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in axes:
        labels = [*ax.texts, *ax.get_xticklabels()]
        for a, b in itertools.combinations(labels, 2):
            require(not a.get_window_extent(renderer).overlaps(b.get_window_extent(renderer)),
                    'Overlapping labels: ' + a.get_text() + ' / ' + b.get_text())
    product = export_panel_png(fig, OUT / f'{STEM}.png')
    return product, limits


def main():
    models, wide, tables = prepare()
    product, limits = render(wide)
    metadata = dict(
        created_utc=datetime.now(timezone.utc).isoformat(), job_id=os.getenv('SLURM_JOB_ID'),
        backend='Python/matplotlib', archetype='quantitative grid', size_mm=[183, 85],
        dpi=600, snapshot=2050, analysis_window=[2050, 2059], models=list(MODELS),
        comparison='SSP585 minus SSP126', panels={'a': 'wind', 'b': 'solar'},
        products=[product], units=UNIT, factor_colors=dict(zip(TERMS, COLORS)),
        figure_question='How do climate mechanisms and deployment layout contribute to the paired loss gap?',
        decomposition='Within-deployment three-factor Shapley (six orders), averaged over deployments 126 and 585; symmetric layout contribution',
        center='Equal-weight mean of four model-level contributions',
        uncertainty='Model min-max retained in source tables; bars display means only',
        support='Common stations and capacity across climates and models within each deployment',
        event='all: selected-event time union', wind_energy_scale=1,
        station_sources=STATION_FILES, axis_limits=limits,
        definitions={'E': 'capacity_event_hours / capacity_mw',
                     'CF_event': 'normal_event_mwh / capacity_event_hours',
                     'r_event': 'net_mwh / normal_event_mwh'},
        maximum_closure=float(models.closure.abs().max()), data_audit='PASSED',
        label_overlap_check='PASSED', visual_review='PENDING',
        input_sha256={str(INPUT.relative_to(ROOT)): digest(INPUT)},
        source_sha256={name: digest(SOURCE / f'{STEM}_{name}.csv') for name in tables},
        code_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                     (FOLDER / 'plot_climate_layout_waterfall.py',
                      ROOT / 'paper_figures/common/metrics.py',
                      ROOT / 'paper_figures/common/plotting.py')})
    write_json(OUT / f'{STEM}_metadata.json', metadata)
    print(wide.to_string())
    print(json.dumps({'product': product, 'maximum_closure': metadata['maximum_closure']}))


if __name__ == '__main__':
    main()
