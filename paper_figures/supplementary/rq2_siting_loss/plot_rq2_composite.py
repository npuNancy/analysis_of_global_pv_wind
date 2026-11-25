"""Combine dispatch-2025 system totals, unit losses, capacity cohorts and temporal attribution."""
from itertools import product
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from paper_figures.common.io import digest
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import MODELS, SNAPSHOTS, SSP_COLORS, SSPS, TECHS
from paper_figures.supplementary.global_metric_trends import plot_dispatch_rq1 as overview
from paper_figures.supplementary.rq2_siting_loss import plot_dispatch_cohorts as cohorts
from paper_figures.main.fig02_generation_loss.plot_climate_layout_waterfall import COLORS as FIG02_COLORS
from paper_figures.supplementary.rq2_siting_loss.prepare_dispatch_decomposition import NAME as DECOMPOSITION, TERMS

NAME = "rq2_dispatch2025_composite"
PERIODS = ("2020s\n(2025)", "2030s", "2040s", "2050s")
HISTORY = "historical"
HEADINGS = {
    "a": "Wind and solar PV combined",
    "b": "Unit-capacity net loss",
    "c": "Additions since 2025",
    "d": "Unit-loss change: 2050s minus 2030s",
}
TOTALS_PATH = overview.DATA / "rq1_dispatch2025_overview_combined_display.csv"
UNIT_PATH = overview.INPUTS / "dispatch2025_station_unit_loss_models.csv"
GEM_PATH = overview.INPUTS / "gem2025_period_models.csv"
DECOMP_PATH = overview.DATA / f"{DECOMPOSITION}_display.csv"
DECOMP_MODELS = overview.DATA / f"{DECOMPOSITION}_models.csv"
WATERFALL_COLORS = (FIG02_COLORS[3], FIG02_COLORS[0], "#487A96", FIG02_COLORS[-1])


def load_unit_loss():
    fields = ["tech", "climate_ssp", "snapshot", "model"]
    future = pd.read_csv(UNIT_PATH).loc[lambda data: data.tech.isin(TECHS)]
    expected = set(product(TECHS, SSPS, MODELS, range(2030, 2060)))
    keys = ["tech", "climate_ssp", "model", "time"]
    assert len(future) == len(expected)
    assert set(future[keys].itertuples(index=False, name=None)) == expected
    assert future.data_status.eq("available").all() and future.station_ssp.eq(future.climate_ssp).all()
    assert future.snapshot.eq(future.time.floordiv(10).mul(10)).all()
    np.testing.assert_allclose(future.value, future.numerator / future.capacity_mw, rtol=1e-12)
    per_model = future.groupby(fields, as_index=False).value.mean()
    summary = per_model.groupby(fields[:-1], as_index=False).value.agg(
        mean="mean", minimum="min", maximum="max", n_models="size")
    historical = pd.read_csv(GEM_PATH).loc[lambda data:
        data.tech.isin(TECHS) & data.year.eq(2025) & data.phase.eq(HISTORY)].copy()
    assert len(historical) == len(TECHS) and historical.model.eq("ERA5-Land").all()
    np.testing.assert_allclose(historical.unit_loss_mwh_per_mw,
                               historical.net_loss_mwh / historical.capacity_mw, rtol=1e-12)
    base = historical.assign(snapshot=2025, value=historical.unit_loss_mwh_per_mw)
    past = base[fields[:-1]].assign(mean=base.value, minimum=base.value, maximum=base.value, n_models=1)
    summary = pd.concat([past, summary], ignore_index=True)
    summary["unit"] = summary.tech.map({"wind": "MWh/MW/year", "solar": "MWh/MWp/year"})
    return summary, pd.concat([base[fields + ["value"]], per_model], ignore_index=True)


def load_decomposition(unit_models):
    keys = ["tech", "climate_ssp", "model"]
    models = pd.read_csv(DECOMP_MODELS).set_index(keys, verify_integrity=True).sort_index()
    unit = unit_models.loc[unit_models.snapshot.isin([2030, 2050])]
    endpoint = unit.pivot(index=keys, columns="snapshot", values="value").sort_index()
    pd.testing.assert_index_equal(models.index, endpoint.index)
    np.testing.assert_allclose(models.loss_2030s, endpoint[2030], rtol=1e-11)
    np.testing.assert_allclose(models.loss_2050s, endpoint[2050], rtol=1e-11)
    np.testing.assert_allclose(models.change, endpoint[2050] - endpoint[2030], atol=1e-10)
    np.testing.assert_allclose(models[list(TERMS[:3])].sum(axis=1), models.change, atol=1e-10)
    display = pd.read_csv(DECOMP_PATH).set_index(keys[:2], verify_integrity=True).sort_index()
    means = models[list(TERMS)].groupby(level=[0, 1]).mean()
    pd.testing.assert_frame_equal(display[list(TERMS)], means, check_exact=False, rtol=1e-11, atol=1e-12)
    return display


def read_cohort(prefix):
    source = cohorts.DATA
    paths = [source / f"{prefix}_{field}.csv" for field in ("historical", "summary")]
    historical = pd.read_csv(paths[0]).set_index("tech")
    summary = pd.read_csv(paths[1]).set_index(["tech", "decade", "ssp"]).sort_index()
    by_tech = {}
    for tech in TECHS:
        path = source / f"{prefix}_violin_{tech}.npz"
        with np.load(path, allow_pickle=False) as data:
            by_tech[tech] = {key: data[key] for key in data.files}
        paths.append(path)
    return (by_tech, historical, summary), paths


def path_curves(ax, data, x_history, x_future, year_key):
    historical = data.loc[data.climate_ssp.eq(HISTORY)].sort_values(year_key)
    assert len(historical) == len(x_history)
    for ssp, marker in zip(SSPS, ("o", "s", "^"), strict=True):
        future = data.loc[data.climate_ssp.eq(ssp)].sort_values(year_key)
        assert tuple(future[year_key]) == SNAPSHOTS
        ax.plot([x_history[-1], *x_future], [historical["mean"].iloc[-1], *future["mean"]],
                color=SSP_COLORS[ssp], marker=marker, markevery=[1, 2, 3], ms=3.1, lw=1.15, zorder=2)
    ax.plot(x_history, historical["mean"], color="black", marker="o" if len(x_history) == 1 else "None",
            ms=3.0, lw=1.15, zorder=3)


def style_axis(ax):
    ax.set_axisbelow(True)
    ax.grid(axis="y", color=".90", lw=.48)
    ax.tick_params(axis="both", labelsize=6.5, length=2.6, pad=2.0)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.yaxis.label.set_size(7)


def panel_a(axes, totals):
    labels = (
        ("capacity", "Nameplate capacity", "TW", 1),
        ("total_generation", "Annual generation", r"PWh yr$^{-1}$", 1),
        ("total_loss", "Annual net loss", r"$10^9$ MWh yr$^{-1}$", 1e9),
    )
    for ax, (metric, title, unit, scale) in zip(axes, labels, strict=True):
        data = totals.loc[totals.metric.eq(metric)].copy()
        historical = data.loc[data.climate_ssp.eq(HISTORY)]
        assert tuple(historical.sort_values("time").plot_year) == overview.HISTORY_YEARS
        data["mean"] /= scale
        path_curves(ax, data, overview.HISTORY_YEARS, SNAPSHOTS, "plot_year")
        ax.set_title(title, loc="left", fontsize=8, pad=5)
        ax.set_ylabel(unit)
        ax.set_xticks(overview.COMBINED_XTICKS)
        ax.set_xlim(2014, 2052)
        ax.set_ylim(bottom=0)


def unit_label(tech):
    unit = cohorts.LABELS[tech][1]
    return rf"MWh $\mathrm{{{unit}}}^{{-1}}$ yr$^{{-1}}$"


def panel_b(axes, unit_loss):
    for ax, tech in zip(axes, TECHS, strict=True):
        data = unit_loss.loc[unit_loss.tech.eq(tech)]
        assert data.loc[data.climate_ssp.eq(HISTORY), "snapshot"].tolist() == [2025]
        path_curves(ax, data, (0,), (1, 2, 3), "snapshot")
        ax.set_title(cohorts.LABELS[tech][0], loc="left", fontsize=8, pad=5)
        ax.set_ylabel(unit_label(tech))
        ax.set_xticks(range(4), PERIODS)
        ax.set_xlim(-.24, 3.24)


def cohort_panel(axes, data):
    archive, historical, summary = data
    for ax, tech in zip(axes, TECHS, strict=True):
        cohorts.draw_cohorts(ax, archive[tech], historical.loc[tech, "stock_unit_loss"], summary.loc[tech])
        ax.set_title(cohorts.LABELS[tech][0], loc="left", fontsize=8, pad=5)
        ax.set_ylabel(unit_label(tech))
        ax.axhline(0, color=".65", lw=.48, zorder=0)
        ax.set_xticks(range(4), PERIODS)
        ax.set_xlim(-.48, 3.5)


def panel_d(axes, decomposition):
    for ax, tech in zip(axes, TECHS, strict=True):
        heights = [0.]
        for i, ssp in enumerate(SSPS):
            values = decomposition.loc[(tech, ssp), list(TERMS)].to_numpy(float)
            start = np.r_[0., np.cumsum(values[:2]), 0.]
            end = start + values
            x = np.arange(len(TERMS)) + 5*i
            ax.bar(x, np.abs(values), bottom=np.minimum(start, end), width=.70,
                   color=WATERFALL_COLORS, edgecolor="white", linewidth=.3, zorder=3)
            for j, (at, val) in enumerate(zip(x, values, strict=True)):
                anchor = max(start[j], end[j]) if val >= 0 else min(start[j], end[j])
                label = f"{val:+.2f}" if abs(val) < 1 else f"{val:+.1f}"
                ax.annotate(label, (at, anchor), xytext=(0, 2 if val >= 0 else -2),
                            textcoords="offset points", ha="center", va="bottom" if val >= 0 else "top",
                            fontsize=6.4, weight="bold" if j == len(TERMS)-1 else "normal")
            ax.hlines(end[:3], x[:3]+.35, x[1:]-.35, color=".52", lw=.55, zorder=3)
            heights.extend(end)
        span = np.ptp(heights)
        padding = .22 * max(span, 1)
        ax.axhline(0, color=".52", lw=.65)
        ax.set_ylim(min(heights)-padding, max(heights)+padding)
        ax.set_xlim(-.65, 13.65)
        ax.set_xticks([1.5, 6.5, 11.5], [ssp.upper() for ssp in SSPS])
        for tick, ssp in zip(ax.get_xticklabels(), SSPS, strict=True):
            tick.set_color(SSP_COLORS[ssp])
        ax.tick_params(axis="x", length=0, pad=3)
        ax.set_title(cohorts.LABELS[tech][0], loc="left", fontsize=8, pad=5)
        ax.set_ylabel(unit_label(tech))


def heading(fig, ax, letter):
    pos = ax.get_position()
    fig.text(pos.x0, pos.y1 + .35 / fig.get_figheight(), rf"$\bf{{{letter}}}$  {HEADINGS[letter]}",
             fontsize=9, ha="left", va="bottom")


def legend(fig, part):
    if part in ("", "a", "b"):
        lines = [Line2D([], [], color="black", lw=1.15, marker="o" if part == "b" else "None",
                        ms=3, linestyle="None" if part == "b" else "-",
                        label="Historical" if part != "b" else "2025 reference")]
        lines.extend(Line2D([], [], color=SSP_COLORS[ssp], lw=1.15, marker=marker, ms=3.2, label=ssp.upper())
                     for ssp, marker in zip(SSPS, ("o", "s", "^"), strict=True))
        fig.legend(handles=lines, loc="lower center", bbox_to_anchor=(.53, .065 if not part else .022),
                   ncol=4, fontsize=7, handlelength=1.5, columnspacing=1.4)
    if part in ("", "c"):
        patches = [Patch(facecolor=cohorts.STOCK_COLOR, alpha=.42, label="2025 capacity")]
        if part:
            patches.extend(Patch(facecolor=SSP_COLORS[s], alpha=.42, label=s.upper()) for s in SSPS)
        patches.extend([
            Line2D([], [], color=".30", marker="o", lw=0, markersize=3.2, label="Cohort mean"),
            Line2D([], [], color=cohorts.STOCK_COLOR, marker="o", markerfacecolor="white", lw=0,
                   markersize=3.1, label="2025 capacity mean under the same SSP"),
        ])
        fig.legend(handles=patches, loc="lower center", bbox_to_anchor=(.28 if not part else .53, .035 if not part else .048),
                   ncol=len(patches), fontsize=6.5, handlelength=1.25, columnspacing=1.2)
        fig.text(.28 if not part else .53, .016, "Violin extent: weighted 0.5th to 99.5th percentiles",
                 ha="center", fontsize=6.1, color=".36")

    if part in ("", "d"):
        terms = ("Layout", "Climate exposure", "Climate intensity", "Net change")
        handles = [Patch(facecolor=color, label=label)
                   for color, label in zip(WATERFALL_COLORS, terms, strict=True)]
        fig.legend(handles=handles, loc="lower center",
                   bbox_to_anchor=(.76 if not part else .53, .035 if not part else .048),
                   ncol=len(handles), fontsize=6.5, handlelength=1.25, columnspacing=1.2)


def render(totals, unit_loss, cumulative, decomposition, part="", cohort_limits=None):
    draw = {
        "a": (panel_a, totals),
        "b": (panel_b, unit_loss),
        "c": (cohort_panel, cumulative),
        "d": (panel_d, decomposition),
    }
    if not part:
        fig, grid = plt.subplots(3, 3, figsize=(13.5, 9))
        fig.subplots_adjust(left=.063, right=.978, bottom=.132, top=.890, wspace=.36, hspace=.60)
        sections = dict(zip(HEADINGS, (grid[:, 0], grid[0, 1:], grid[1, 1:], grid[2, 1:])))
    else:
        nrows, ncols = (3, 1) if part == "a" else (1, 2)
        sizes = {"a": (97/25.4, 217/25.4), "d": (9, 6)}
        fig, axes = plt.subplots(nrows, ncols, figsize=sizes.get(part, (166/25.4, 82/25.4)))
        fig.subplots_adjust(left=.152 if part == "a" else .091, right=.977,
                            bottom=.105 if part == "a" else .258, top=.863 if part == "a" else .805,
                            wspace=.35, hspace=.59)
        if part == "d":
            fig.subplots_adjust(bottom=.155, top=.855)
        sections = {part: axes}
    for key, axes in sections.items():
        for ax in axes:
            style_axis(ax)
        panel, data = draw[key]
        panel(axes, data)
        heading(fig, axes[0], key)
    if "c" in sections:
        if cohort_limits is None:
            cohort_limits = [ax.get_ylim() for ax in sections["c"]]
        for ax, ylim in zip(sections["c"], cohort_limits, strict=True):
            ax.set_ylim(*ylim)
    for ax in fig.axes:
        lower, upper = ax.get_ylim()
        ticks = ax.get_yticks()
        ax.set_yticks(ticks[(lower <= ticks) & (ticks <= upper)])
    legend(fig, part)
    suffix = f"_{part}" if part else ""
    bounds = (0, 0, 1, 1) if part in ("", "d") else None
    export = export_panel_png(fig, overview.BUNDLE / "images" / f"{NAME}{suffix}.png", bounds=bounds)
    if bounds is not None:
        width, height = export["image"]["pixels"]
        assert width * 2 == height * 3, (width, height)
    return export, cohort_limits


def main():
    configure()
    totals = pd.read_csv(TOTALS_PATH)
    unit_loss, unit_models = load_unit_loss()
    cumulative, c_paths = read_cohort(cohorts.PREFIX)
    decomposition = load_decomposition(unit_models)
    unit_loss.to_csv(overview.DATA / f"{NAME}_unit_loss_display.csv", index=False)
    unit_models.to_csv(overview.DATA / f"{NAME}_unit_loss_models.csv", index=False)
    figure, limits = render(totals, unit_loss, cumulative, decomposition)
    products = [figure]
    for part in HEADINGS:
        product, _ = render(totals, unit_loss, cumulative, decomposition, part=part, cohort_limits=limits)
        products.append(product)
    source = [TOTALS_PATH, UNIT_PATH, GEM_PATH, *c_paths, DECOMP_PATH, DECOMP_MODELS]
    metadata = {
        "products": products,
        "inputs": [{"path": p.name, "sha256": digest(p)} for p in source],
        "layout": [["a", "b", "b"], ["a", "c", "c"], ["a", "d", "d"]],
        "historical_unit_loss": "ERA5-Land, 2025 only",
        "future_unit_loss": "Annual valid-capacity weighted global mean, then ten years and four models",
        "cohort_limits": dict(zip(TECHS, limits, strict=True)),
        "checks": ["The 2030s and 2050s decomposition endpoints equal panel b for every model",
                   "Layout, climate exposure and climate intensity sum to the plotted net change"],
    }
    (overview.DATA / f"{NAME}_validation.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(unit_loss.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
