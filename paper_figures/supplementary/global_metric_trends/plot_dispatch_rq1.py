"""Render combined and technology-specific global dispatch-2025 overviews."""
import argparse
import json
from itertools import product
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator
import numpy as np
import pandas as pd

from paper_figures.common.io import digest
from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import MODELS, SSP_COLORS, SSPS, TECHS

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parents[2] / "tmp/RQ1_20261123_candidates"
INPUTS = HERE / "outputs/source_data"
DATA = BUNDLE / "source_data"
FUTURE_YEARS = (2030, 2040, 2050)
HISTORY_YEARS = tuple(range(2015, 2026))
XTICKS = (2020, *FUTURE_YEARS)
COMBINED_XTICKS = (2015, 2020, 2025, *FUTURE_YEARS)
METRICS = (
    ("capacity", "Installed capacity", None, "TW", 1e6),
    ("total_generation", "Annual generation", r"Generation (PWh yr$^{-1}$)", "PWh/year", 1e9),
    ("total_loss", "Annual net loss", r"Net loss (MWh yr$^{-1}$)", "MWh/year", 1.0),
)
COMBINED = "wind+solar"
TECH_LABELS = {"wind": "Wind", "solar": "Solar PV", COMBINED: "Wind and solar PV"}


def load_curves(techs=TECHS):
    keys = ["climate_ssp", "tech", "time"]
    history_path = INPUTS / "gem2025_period_models.csv"
    reference_path = INPUTS / "gem2025_fixed_display.csv"
    history_keys = ["tech", "year"]
    history = pd.read_csv(history_path).loc[
        lambda df: df.year.isin(HISTORY_YEARS) & df.phase.eq("historical") & df.tech.isin(techs)
    ].set_index(history_keys, verify_integrity=True).sort_index()
    reference = pd.read_csv(reference_path).loc[
        lambda df: df.year.isin(HISTORY_YEARS) & df.pathway.eq("historical") & df.tech.isin(techs)
    ].set_index(history_keys, verify_integrity=True).sort_index()
    expected_history = pd.MultiIndex.from_product([sorted(techs), HISTORY_YEARS], names=history_keys)
    assert history.index.equals(reference.index) and history.index.equals(expected_history)
    assert history.model.eq("ERA5-Land").all()
    for name in ("generation_mwh", "net_loss_mwh"):
        np.testing.assert_allclose(history[name], reference[name+"_mean"], rtol=1e-12)
    history = history.reset_index()
    inputs = [{"name": path.name, "sha256": digest(path)} for path in (history_path, reference_path)]
    curves, model_tables, history_models = [], [], []
    for metric, _, _, unit, divisor in METRICS:
        capacity = metric == "capacity"
        model_ids = ("catalogue",) if capacity else MODELS
        source = INPUTS / f"dispatch2025_station_{metric}_models.csv"
        display_path = INPUTS / f"dispatch2025_station_{metric}_display.csv"
        models = pd.read_csv(source).loc[lambda df: df.tech.isin(techs)
                                        & df.time.isin(FUTURE_YEARS)].copy()
        assert models.data_status.eq("available").all()
        assert models.climate_ssp.eq(models.station_ssp).all()
        assert models.unit.eq(unit).all()
        assert set(models[["model", *keys]].itertuples(index=False, name=None)) == set(
            product(model_ids, SSPS, techs, FUTURE_YEARS))
        assert not models.duplicated(["model", *keys]).any()
        assert np.isfinite(models.value).all()
        np.testing.assert_allclose(models.value, models.numerator/divisor, rtol=1e-12)
        model_tables.append(models.assign(metric=metric, plot_year=models.time))
        curve = models.groupby(keys).value.agg(mean="mean", minimum="min", maximum="max",
                                               n_models="count").reset_index()
        display = pd.read_csv(display_path).loc[lambda df: df.tech.isin(techs)
                                                & df.time.isin(FUTURE_YEARS)]
        check = curve.merge(display, on=keys, validate="one_to_one", suffixes=("", "_published"))
        assert len(check) == len(curve) == len(display)
        for field in ["mean", "minimum", "maximum", "n_models"]:
            np.testing.assert_allclose(check[field], check[field+"_published"], rtol=1e-12)
        curves.append(curve.assign(metric=metric, station_ssp=curve.climate_ssp, plot_year=curve.time,
                                   unit=unit, temporal_support="snapshot" if capacity else "year"))
        raw_field = {"capacity": "catalogue_capacity_mw", "total_generation": "generation_mwh",
                     "total_loss": "net_loss_mwh"}[metric]
        historical = history.assign(
            time=history.year, plot_year=history.year, metric=metric, unit=unit,
            model="catalogue" if capacity else "ERA5-Land", snapshot=history.year,
            numerator=history[raw_field], denominator=divisor,
            value=history[raw_field]/divisor, data_status="available",
        )
        history_models.append(historical.reindex(columns=model_tables[-1].columns))
        curves.append(historical[["tech", "climate_ssp", "station_ssp", "time", "plot_year", "metric", "unit"]]
                      .assign(mean=historical.value, minimum=historical.value, maximum=historical.value,
                              n_models=1, temporal_support="snapshot" if capacity else "year"))
        inputs.extend({"name": path.name, "sha256": digest(path)} for path in (source, display_path))
    coverage = ["capacity_mw", "catalogue_capacity_mw", "capacity_coverage"]
    generation, loss = model_tables[1:]
    pd.testing.assert_frame_equal(generation.set_index(["model", *keys])[coverage].sort_index(),
                                  loss.set_index(["model", *keys])[coverage].sort_index())
    display = pd.concat(curves, ignore_index=True)
    assert len(display) == len(METRICS)*len(techs)*(len(HISTORY_YEARS)+len(SSPS)*len(FUTURE_YEARS))
    assert display.plot_year.eq(display.time).all()
    assert set(display.plot_year) == set(HISTORY_YEARS + FUTURE_YEARS)
    assert display.minimum.ge(0).all()
    return display, pd.concat(model_tables + history_models, ignore_index=True), inputs


def render(curves, techs, suffix, columns=(0, 1, 2)):
    full = len(techs) == 2
    combined = techs == (COMBINED,)
    single = len(columns) == 1
    history_marker = "None" if combined else "o"
    fig, axes = plt.subplots(len(techs), len(columns), figsize=((108 if single else 230)/25.4,
                                                                      (140 if full else 86)/25.4),
                             squeeze=False)
    fig.subplots_adjust(left=.102, right=.977, bottom=.15 if full else .23, top=.84 if full else .75,
                        wspace=.41, hspace=.56)
    if single:
        fig.subplots_adjust(left=.235, right=.961)
    heading = "Global dispatch-2025 | Capacity, generation and extreme-event loss"
    if combined:
        heading = "Global dispatch-2025 | Wind and solar PV combined"
    fig.suptitle(heading, y=.973, fontsize=9 if single else 10)
    fig.text(.54, .925 if full else .897,
             "2015–2025: annual GEM / ERA5-Land data. Future: paired SSP snapshots.",
             ha="center", va="top", color=".35", fontsize=7)
    for row, tech in zip(axes, techs):
        label = TECH_LABELS[tech]
        for ax, col in zip(row, columns, strict=True):
            metric, title, ylabel, _, _ = METRICS[col]
            capacity = metric == "capacity"
            panel = curves.loc[curves.tech.eq(tech) & curves.metric.eq(metric)]
            historical = panel.loc[panel.climate_ssp.eq("historical")].sort_values("time")
            assert tuple(historical.plot_year) == HISTORY_YEARS
            for scenario, marker in zip(SSPS, ("o", "s", "^")):
                group = panel.loc[panel.climate_ssp.eq(scenario)].sort_values("time")
                assert tuple(group.plot_year) == FUTURE_YEARS
                color = SSP_COLORS[scenario]
                ax.plot([HISTORY_YEARS[-1], FUTURE_YEARS[0]],
                        [historical["mean"].iloc[-1], group["mean"].iloc[0]],
                        color=color, lw=1.35, zorder=2)
                ax.plot(group.plot_year, group["mean"], color=color, lw=1.35,
                        marker=marker, ms=3.6, zorder=2)
            ax.plot(historical.plot_year, historical["mean"], color="black", marker=history_marker,
                    linestyle="-", lw=1.15, ms=3.0, zorder=3)
            letter = "abc"[col] if combined else "abcdef"[TECHS.index(tech)*3+col]
            panel_title = f"{letter}  {title}" if combined else f"{letter}  {label} | {title}"
            ax.set_title(panel_title, loc="left", fontsize=8, pad=8)
            ax.set_xticks(COMBINED_XTICKS if combined else XTICKS)
            ax.set_xlim(HISTORY_YEARS[0]-1, FUTURE_YEARS[-1]+2)
            ax.set_xlabel("Year")
            if capacity:
                ylabel = r"Installed capacity (TW$_p$)" if tech == "solar" else "Installed capacity (TW)"
                if combined:
                    ylabel = "Nameplate capacity (TW)"
            ax.set_ylabel(ylabel)
            ax.set_ylim(bottom=0)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
            if metric == "total_loss":
                loss_range = curves.loc[(curves.tech == tech) & (curves.metric == metric), "maximum"]
                exponent = int(np.floor(np.log10(loss_range.max())))
                factor = 10 ** exponent
                ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _, scale=factor: f"{value/scale:g}"))
                ax.set_ylabel(rf"Net loss ($10^{{{exponent}}}$ MWh yr$^{{-1}}$)")
            if combined:
                ticks = ax.get_yticks()
                lower, upper = ax.get_ylim()
                ax.set_yticks(ticks[(lower <= ticks) & (ticks <= upper)])
            ax.set_axisbelow(True)
            ax.grid(axis="y", color=".9", lw=.5)
    handles = [Line2D([], [], color="black", marker=history_marker, linestyle="-",
                      lw=1.15, ms=3.0, label="Historical (2015–2025)")]
    handles += [Line2D([], [], lw=1.4, color=SSP_COLORS[s], marker=marker, ms=3.6, label=s.upper())
                for s, marker in zip(SSPS, ("o", "s", "^"))]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.54, .03), ncol=4, fontsize=6.5 if single else 8, columnspacing=1.1 if single else 2.0)
    return export_panel_png(fig, BUNDLE / "images" / f"rq1_dispatch2025_overview{suffix}.png")


def write_combined():
    curves, models, inputs = load_curves((*TECHS, COMBINED))
    by_tech = models.pivot(index=["metric", "model", "climate_ssp", "station_ssp", "time"],
                           columns="tech", values="value")
    np.testing.assert_allclose(by_tech[COMBINED], by_tech[list(TECHS)].sum(axis=1), rtol=1e-12)
    curves = curves.loc[curves.tech.eq(COMBINED)].copy()
    models = models.loc[models.tech.eq(COMBINED)].copy()
    prefix = "rq1_dispatch2025_overview_combined"
    DATA.mkdir(parents=True, exist_ok=True)
    curves.to_csv(DATA / f"{prefix}_display.csv", index=False)
    models.to_csv(DATA / f"{prefix}_models.csv", index=False)
    products = [render(curves, (COMBINED,), "_combined")]
    products.extend(render(curves, (COMBINED,), f"_combined_{letter}", columns=(col,))
                    for col, letter in enumerate("abc"))
    validation = {"inputs": inputs, "products": products, "ticks": list(COMBINED_XTICKS),
                  "history": {"years": list(HISTORY_YEARS), "style": "black solid line without markers"},
                  "transition": {"from": HISTORY_YEARS[-1], "to": FUTURE_YEARS[0]},
                  "checks": ["historical and future values plotted at their actual years",
                             "published combined totals match the sum of wind and PV per model and year",
                             "combined generation and loss use matching effective capacity and coverage"]}
    (DATA / f"{prefix}_validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    print("Rendered the 1 × 3 wind and solar PV overview and its three panels.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--combined-only", action="store_true", help="Render only the wind and PV combined figure.")
    args = parser.parse_args()
    configure()
    write_combined()
    if args.combined_only:
        return

    curves, models, inputs = load_curves()
    DATA.mkdir(parents=True, exist_ok=True)
    curves.loc[(curves.metric == "capacity") & (curves.tech == "solar"), "unit"] = "TWp"
    models.loc[(models.metric == "capacity") & (models.tech == "solar"), "unit"] = "TWp"
    curves.to_csv(DATA/"rq1_dispatch2025_display.csv", index=False)
    models.to_csv(DATA/"rq1_dispatch2025_models.csv", index=False)
    products = [render(curves, techs, suffix)
                for techs, suffix in [(TECHS, ""), (TECHS[:1], "_abc"), (TECHS[1:], "_def")]]
    validation = {"inputs": inputs, "products": products, "ticks": list(XTICKS),
                  "history": {"years": list(HISTORY_YEARS), "capacity": "annual GEM catalogue",
                              "energy": "annual ERA5-Land with same-year capacity"},
                  "transition": {"from": HISTORY_YEARS[-1], "to": FUTURE_YEARS[0], "scenarios": list(SSPS)},
                  "checks": ["three matched climate and layout SSPs at the exact years 2030, 2040 and 2050",
                             "11 actual-year historical points connected by a black line and energy values cross-checked",
                             "each SSP starts at the common 2025 point and connects to its own 2030 value",
                             "published values and four-model ranges reproduced",
                             "generation and loss use matching effective capacity and coverage"]}
    (DATA/"rq1_dispatch2025_validation.json").write_text(json.dumps(validation, indent=2)+"\n")
    print("Rendered the 2 × 3 dispatch-2025 overview and both row groups.", flush=True)


if __name__ == "__main__":
    main()
