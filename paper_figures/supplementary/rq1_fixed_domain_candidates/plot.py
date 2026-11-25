"""Redraw the RQ1 fixed-domain comparisons from existing source tables."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
DATA = OUT / "source_data"
DELIVERY = ROOT / "tmp/RQ1_20261112_candidates"
SOURCE = ROOT / "paper_figures/supplementary/global_metric_trends/outputs/source_data"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".mplconfig"))
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, FixedLocator
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import SSP_COLORS

TECHS = ("wind", "solar")
SSPS = ("ssp126", "ssp245", "ssp585")
MODELS = ("BCC-CSM2-MR", "CANESM5", "MPI-ESM1-2-HR", "MRI-ESM2-0")
LABELS = {"wind": "Wind", "solar": "Solar PV"}
SSP_LABELS = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
MARKERS = {"ssp126": "o", "ssp245": "s", "ssp585": "^"}
UNITS = {"exposure": "days/year", "loss": "MWh/MW/year"}
METRIC_LABELS = {"exposure": "Exposure (days yr$^{-1}$)",
                 "loss": "Net loss (MWh MW$^{-1}$ yr$^{-1}$)"}
PROVENANCE, PLOT_QA = [], []


def read_source(name):
    path = SOURCE / name
    frame = pd.read_csv(path)
    PROVENANCE.append(dict(file=str(path.relative_to(ROOT)),
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rows=len(frame)))
    (DATA / "inputs").mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, DATA / "inputs" / name)
    return frame


def prepare():
    records = []
    for name, scope, metric in (
        ("grid_exposure_models.csv", "global_grid", "exposure"),
        ("suitable_grid_exposure_models.csv", "suitable_grid", "exposure"),
        ("suitable_grid_unit_loss_models.csv", "suitable_grid", "loss"),
    ):
        frame = read_source(name)
        frame = frame[frame.tech.isin(TECHS)].copy()
        frame["period_start"] = frame.time.astype(int) // 10 * 10
        assert set(frame.climate_ssp) == set(SSPS) and set(frame.model) == set(MODELS)
        assert frame.denominator.gt(0).all()
        np.testing.assert_allclose(frame.value, frame.numerator / frame.denominator, rtol=1e-10)
        for tech, g in frame.groupby("tech"):
            assert np.ptp(g.denominator) < max(1e-6, abs(g.denominator.mean()) * 1e-10)
        keys = ["model", "climate_ssp", "tech", "period_start"]
        for key, g in frame.groupby(keys):
            assert len(g) == (10 if metric == "loss" else 1)
            record = dict(zip(keys, key))
            record.update(scope=scope, metric=metric, value=float(g.value.mean()),
                          denominator=float(g.denominator.mean()),
                          weighting="equal_1MW_per_grid" if metric == "loss" else "native_cell_area",
                          unit=UNITS[metric], station_ssp="not_applicable", capacity_snapshot=np.nan)
            record["coverage_fraction"] = float(g.coverage.mean()) if "coverage" in g else np.nan
            records.append(record)
    fixed = read_source("gem2025_fixed_models.csv")
    fixed = fixed[fixed.tech.isin(TECHS) & fixed.year.between(2030, 2059)].copy()
    fixed["period_start"] = fixed.year // 10 * 10
    for tech, g in fixed.groupby("tech"):
        np.testing.assert_allclose(g.capacity_mw, g.capacity_mw.iloc[0], rtol=1e-12)
        assert g.n_stations.nunique() == 1
    for key, g in fixed.groupby(["model", "pathway", "tech", "period_start"]):
        assert len(g) == 10
        for metric, column in (("exposure", "exposure_days"), ("loss", "unit_loss_mwh_per_mw")):
            numerator = "exposure_mw_days" if metric == "exposure" else "net_loss_mwh"
            np.testing.assert_allclose(g[column], g[numerator] / g.capacity_mw, rtol=1e-10)
            model, scenario, tech, start = key
            records.append(dict(model=model, climate_ssp=scenario, tech=tech, period_start=start,
                                scope="fixed2025", metric=metric, value=float(g[column].mean()),
                                denominator=float(g.capacity_mw.mean()), weighting="fixed_2025_capacity",
                                unit=UNITS[metric], station_ssp="gem2025", capacity_snapshot=2025,
                                coverage_fraction=np.nan, n_stations=int(g.n_stations.iloc[0])))
    dec = pd.DataFrame(records)
    dec["period_end"] = dec.period_start + 9
    assert len(dec) == 360
    assert not dec.duplicated(["scope", "metric", "tech", "model", "climate_ssp", "period_start"]).any()
    assert np.isfinite(dec.value).all()
    keys = ["scope", "metric", "tech", "model", "period_start", "period_end", "unit", "weighting"]
    pivot = dec.pivot(index=keys, columns="climate_ssp", values="value")
    differences = []
    for target in SSPS[1:]:
        f = (pivot[target] - pivot.ssp126).rename("value").reset_index()
        f["target_ssp"], f["reference_ssp"] = target, "ssp126"
        differences.append(f)
    differences = pd.concat(differences, ignore_index=True)
    keys = ["scope", "metric", "tech", "model", "climate_ssp", "unit", "weighting"]
    pivot = dec.pivot(index=keys, columns="period_start", values="value")
    changes = (pivot[2050] - pivot[2030]).rename("value").reset_index()
    changes["reference_period"], changes["target_period"] = "2030-2039", "2050-2059"
    dec.to_csv(DATA / "decadal_models.csv", index=False)
    differences.to_csv(DATA / "scenario_differences.csv", index=False)
    changes.to_csv(DATA / "temporal_changes.csv", index=False)
    means = dec.groupby(["scope", "metric", "tech", "climate_ssp", "period_start"], as_index=False).value.agg(
        mean="mean", minimum="min", maximum="max", n_models="count")
    assert means.n_models.eq(4).all()
    means.to_csv(DATA / "decadal_ensemble.csv", index=False)
    (DATA / "input_manifest.json").write_text(json.dumps(PROVENANCE, ensure_ascii=False, indent=2) + "\n")
    return dec, differences, changes


def select(frame, **filters):
    mask = np.ones(len(frame), dtype=bool)
    for key, value in filters.items():
        mask &= frame[key].eq(value).to_numpy()
    return frame.loc[mask]


def values(frame, **filters):
    f = select(frame, **filters).set_index("model").loc[list(MODELS)]
    assert len(f) == 4
    return f.value.to_numpy(float)


def forest(ax, vals, y, color):
    ax.plot([vals.min(), vals.max()], [y, y], color=color, lw=1.2, alpha=.65, zorder=2)
    ax.scatter(vals, y + np.array([-.11, -.036, .036, .11]), s=15,
               facecolors="white", edgecolors=color, linewidths=.65, zorder=3)
    ax.scatter(vals.mean(), y, s=32, marker="D", facecolors=color, edgecolors="white", linewidths=.6, zorder=4)


def draw_panel(ax, spec, dec, diff, change):
    tech, metric, kind = spec["tech"], spec.get("metric"), spec["kind"]
    ax.tick_params(labelsize=6.8, length=2.5, width=.65)
    ax.grid(axis="y", color=".9", lw=.4, zorder=0)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    if kind == "trend":
        scope = spec["scope"]
        for scenario in SSPS:
            g = select(dec, scope=scope, tech=tech, metric=metric, climate_ssp=scenario)
            means = g.groupby("period_start").value.mean().reindex([2030, 2040, 2050])
            ax.plot([0, 1, 2], means, color=SSP_COLORS[scenario], marker=MARKERS[scenario],
                    lw=1.25, ms=3.8, mec="white", mew=.35)
        ax.set_xticks([0, 1, 2], ["2030s", "2040s", "2050s"])
        ax.set_xlim(-.12, 2.12)
        ax.set_ylabel(METRIC_LABELS[metric], fontsize=7)
        name = "suitable grid" if scope == "suitable_grid" else "global grid"
        ax.set_title(f"{LABELS[tech]} | {name}", fontsize=8.2, pad=8)
    elif kind == "contrast":
        scopes = spec["scopes"]
        for y, scope in enumerate(scopes):
            v = values(diff, scope=scope, tech=tech, metric=metric, period_start=2050, target_ssp="ssp585")
            color = SSP_COLORS["ssp585"] if scope == "suitable_grid" else "#657687"
            forest(ax, v, y, color)
            support = int(np.sum(v > 0)) if v.mean() > 0 else int(np.sum(v < 0))
            direction = "higher" if v.mean() > 0 else "lower"
            ax.text(.98, 1 - (y + .5) / len(scopes), f"{support}/4 {direction}",
                    transform=ax.transAxes, ha="right", va="center", fontsize=6.4, color=".35",
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85, "pad": .5})
        scope_names = {"suitable_grid": "Suitable\ngrid", "global_grid": "Global\ngrid", "fixed2025": "Fixed 2025\n(supplement)"}
        ax.set_yticks(range(len(scopes)), [scope_names[s] for s in scopes])
        ax.set_ylim(len(scopes) - .55, -.45)
        ax.axvline(0, color=".45", ls="--", lw=.7)
        unit = "days yr$^{-1}$" if metric == "exposure" else "MWh MW$^{-1}$ yr$^{-1}$"
        ax.set_xlabel("SSP585 − SSP126 (" + unit + ")", fontsize=7)
        ax.set_title(f"{LABELS[tech]} | 2050–2059 difference", fontsize=8.2, pad=8)
        ax.grid(False)
        ax.grid(axis="x", color=".92", lw=.4)
    elif kind == "change":
        for x, scenario in enumerate(SSPS):
            v = values(change, scope="suitable_grid", metric=metric, tech=tech, climate_ssp=scenario)
            color = SSP_COLORS[scenario]
            ax.plot([x, x], [v.min(), v.max()], lw=1.2, color=color, alpha=.7)
            ax.scatter(x + np.array([-.13, -.045, .045, .13]), v, s=15,
                       facecolors="white", edgecolors=color, lw=.65, zorder=3)
            ax.scatter(x, v.mean(), color=color, marker="D", s=32, edgecolors="white", lw=.6, zorder=4)
        ax.axhline(0, color=".45", lw=.7, ls="--")
        ax.set_xticks([0, 1, 2], [SSP_LABELS[s] for s in SSPS])
        ax.set_xlim(-.4, 2.4)
        ax.set_ylabel("Exposure change (days yr$^{-1}$)" if metric == "exposure" else "Net-loss change (MWh MW$^{-1}$ yr$^{-1}$)", fontsize=7)
        name = "exposure" if metric == "exposure" else "net loss"
        ax.set_title(f"{LABELS[tech]} | grid {name} change", fontsize=8.2, pad=8)
    elif kind == "joint_change":
        for scenario in SSPS:
            x = values(change, scope="fixed2025", metric="exposure", tech=tech, climate_ssp=scenario)
            y = values(change, scope="fixed2025", metric="loss", tech=tech, climate_ssp=scenario)
            color = SSP_COLORS[scenario]
            ax.scatter(x, y, s=18, facecolors="white", edgecolors=color, lw=.75, zorder=3)
            ax.scatter(x.mean(), y.mean(), s=38, marker="D", facecolors=color, edgecolors="white", lw=.65, zorder=4)
        ax.axvline(0, color=".45", lw=.7, ls="--")
        ax.axhline(0, color=".45", lw=.7, ls="--")
        ax.set_xlabel("Exposure change (days yr$^{-1}$)", fontsize=7)
        ax.set_ylabel("Net-loss change (MWh MW$^{-1}$ yr$^{-1}$)", fontsize=7)
        ax.set_title(f"{LABELS[tech]} | fixed 2025 supplement", fontsize=8.2, pad=8)


def harmonize(axes, specs):
    for i in range(0, len(axes), 2):
        row, kind = axes[i:i+2], specs[i]["kind"]
        if kind in ("trend", "change"):
            lim = [min(a.get_ylim()[0] for a in row), max(a.get_ylim()[1] for a in row)]
            for a in row:
                a.set_ylim(lim)
        elif kind == "contrast":
            lim = [min(a.get_xlim()[0] for a in row), max(a.get_xlim()[1] for a in row)]
            span = lim[1] - lim[0]
            lim = [lim[0] - .03 * span, lim[1] + .28 * span]
            for a in row:
                a.set_xlim(lim)
        else:
            for getter, setter in (("get_xlim", "set_xlim"), ("get_ylim", "set_ylim")):
                lo, hi = min(getattr(a, getter)()[0] for a in row), max(getattr(a, getter)()[1] for a in row)
                for a in row:
                    getattr(a, setter)((lo, hi))


def render(name, specs, title, subtitle, note, dec, diff, change, letters=None, limits=None):
    rows = len(specs) // 2
    height = {1: 83, 2: 142, 3: 200}[rows]
    fig, axes = plt.subplots(rows, 2, figsize=(183/25.4, height/25.4), squeeze=False)
    fig.subplots_adjust(left=.13, right=.974, bottom=.25 if rows == 1 else .17 if rows == 2 else .15,
                        top=.65 if rows == 1 else .83 if rows == 2 else .875,
                        wspace=.42, hspace=.60 if rows > 1 else .2)
    axes = list(axes.flat)
    for index, (ax, spec) in enumerate(zip(axes, specs)):
        draw_panel(ax, spec, dec, diff, change)
        ax.text(-.30, 1.06, (letters or "abcdefgh")[index], transform=ax.transAxes,
                fontsize=9, fontweight="bold", va="bottom")
    harmonize(axes, specs)
    if limits:
        for ax, (xlim, ylim) in zip(axes, limits):
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
    for ax in axes:
        for axis, bounds in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            lo, hi = sorted(bounds)
            ticks = axis.get_majorticklocs()
            axis.set_major_locator(FixedLocator(ticks[(ticks >= lo) & (ticks <= hi)]))
    fig.suptitle(title, y=.988, fontsize=10, fontweight="medium")
    fig.text(.5, .915 if rows == 1 else .951 if rows == 2 else .962,
             subtitle, ha="center", va="center", fontsize=7.1, color=".3")
    legend_y = .815 if rows == 1 else .887 if rows == 2 else .918
    handles = [Line2D([0], [0], color=SSP_COLORS[s], marker=MARKERS[s], ms=3.5, lw=1.2,
                      label=SSP_LABELS[s]) for s in SSPS]
    fig.legend(handles=handles, ncol=3, loc="center", bbox_to_anchor=(.53, legend_y),
               fontsize=7, handlelength=1.8, columnspacing=2)
    fig.text(.52, .022, note, ha="center", va="bottom", fontsize=6.3, color=".35", linespacing=1.5)
    bounds = [(ax.get_xlim(), ax.get_ylim()) for ax in axes]
    qa = export_panel_png(fig, OUT / f"{name}.png")
    qa["panels"] = [dict(letter=(letters or "abcdefgh")[i], **s,
                          xlim=list(bounds[i][0]), ylim=list(bounds[i][1])) for i, s in enumerate(specs)]
    PLOT_QA.append(qa)
    return bounds


def figures(dec, diff, change):
    plans = [
        ("rq1_01_loss",
         [dict(kind="trend", scope="suitable_grid", metric="loss", tech=t) for t in TECHS] +
         [dict(kind="contrast", scopes=["suitable_grid", "fixed2025"], metric="loss", tech=t) for t in TECHS],
         "RQ1 candidate 1 | Does higher forcing mean greater net loss?",
         "Primary: fixed suitable grids, 1 MW per grid | Supplement: fixed 2025 assets",
         "a–b: four-GCM decadal means. c–d: within-GCM SSP585 − SSP126 differences.\n"
         "Small circles: four GCMs; diamonds: mean; whiskers: min–max, not confidence intervals."),
        ("rq1_02_exposure",
         [dict(kind="trend", scope="suitable_grid", metric="exposure", tech=t) for t in TECHS] +
         [dict(kind="trend", scope="global_grid", metric="exposure", tech=t) for t in TECHS] +
         [dict(kind="contrast", scopes=["suitable_grid", "global_grid"], metric="exposure", tech=t) for t in TECHS],
         "RQ1 candidate 2 | Opposite exposure responses in wind and solar",
         "Area-weighted event-union duration | Fixed spatial support within each product",
         "a–d: four-GCM decadal means. e–f: within-GCM SSP585 − SSP126 differences.\n"
         "Small circles: four GCMs; diamonds: mean; whiskers: min–max. Exposure days = event hours / 24."),
        ("rq1_03_exposure_loss",
         [dict(kind="change", metric="exposure", tech=t) for t in TECHS] +
         [dict(kind="change", metric="loss", tech=t) for t in TECHS] +
         [dict(kind="joint_change", tech=t) for t in TECHS],
         "RQ1 candidate 3 | Does growing exposure imply growing loss?",
         "Within-GCM changes: 2050–2059 minus 2030–2039",
         "a–b: area-weighted grid exposure; c–d: equal-1-MW grid loss; e–f: fixed-2025 capacity weights.\n"
         "Small circles: four GCMs; diamonds: mean; whiskers: min–max. Grid rows are not a decomposition."),
    ]
    for name, specs, title, subtitle, note in plans:
        bounds = render(name, specs, title, subtitle, note, dec, diff, change)
        for start in range(0, len(specs), 2):
            letters = "abcdefgh"[start:start+2]
            kind = specs[start]["kind"]
            if kind == "trend":
                group_note = "Lines and symbols: four-GCM decadal means. Spatial support is fixed within each product."
            elif kind == "contrast":
                group_note = "2050–2059 within-GCM SSP585 − SSP126 differences.\nSmall circles: four GCMs; diamonds: mean; whiskers: min–max, not confidence intervals."
            elif kind == "change":
                weighting = "Area-weighted exposure" if specs[start]["metric"] == "exposure" else "Equal-1-MW grid net loss"
                group_note = weighting + "; within-GCM 2050s minus 2030s.\nSmall circles: four GCMs; diamonds: mean; whiskers: min–max, not confidence intervals."
            else:
                group_note = "Fixed 2025 assets; capacity-weighted changes from 2030–2039 to 2050–2059.\nSmall circles: four GCMs; diamonds: means. Positions and capacity are fixed."
            render(name + "_" + letters, specs[start:start+2], title, subtitle, group_note,
                   dec, diff, change, letters=letters, limits=bounds[start:start+2])


def main():
    for path in (OUT, DATA, DELIVERY / "images", DELIVERY / "source_data"):
        path.mkdir(parents=True, exist_ok=True)
    configure()
    plt.rcParams.update({"font.sans-serif": ["DejaVu Sans", "Arial", "sans-serif"],
                         "axes.labelsize": 7, "font.size": 7, "axes.titleweight": "regular"})
    dec, diff, change = prepare()
    figures(dec, diff, change)
    for name in ("rq1_01_loss.png", "rq1_02_exposure.png", "rq1_03_exposure_loss.png"):
        shutil.copy2(OUT / name, DELIVERY / "images" / name)
    for source in DATA.glob("*.csv"):
        shutil.copy2(source, DELIVERY / "source_data" / source.name)
    shutil.copy2(DATA / "input_manifest.json", DELIVERY / "source_data/input_manifest.json")
    metadata = dict(figure_contract=json.loads((HERE / "figure_contract.json").read_text()), inputs=PROVENANCE,
                    checks=dict(decadal_records=len(dec), scenario_difference_records=len(diff),
                                temporal_change_records=len(change), four_models_per_cell=True,
                                source_ratio_reconstruction="passed", fixed_denominators="passed", future_deployment_inputs=0),
                    figures=PLOT_QA, visual_review="pending")
    (OUT / "qa.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"figures": len(PLOT_QA), "main_figures": 3, "delivery": str(DELIVERY)}, ensure_ascii=False))


if __name__ == "__main__":
    from datetime import datetime
    from contextlib import redirect_stdout, redirect_stderr
    logdir = ROOT / "logs/paper_figures/rq1_fixed_domain_candidates"
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / ("plot_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".out")
    with logfile.open("w") as handle, redirect_stdout(handle), redirect_stderr(handle):
        main()
    print("Completed; log:", logfile)
