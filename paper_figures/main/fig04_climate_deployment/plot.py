"""Render the six Fig. 4 panels from accepted model-resolved preparation tables."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.patches import Rectangle, Patch
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from paper_figures.config import ROOT, OUTPUT, MODELS, SSPS, TECHS
from paper_figures.common.io import write_csv, write_json, digest
from paper_figures.common.metrics import ensemble, climate_deployment
from paper_figures.common.plotting import configure, save_png

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SOURCE = OUT / "source_data"
UNIT = r"MWh MW$^{-1}$ yr$^{-1}$"
METRICS = ["D", "delta_C_126", "delta_C_585", "delta_S_126",
           "delta_S_585", "Phi_C", "Phi_S", "J"]
COLORS = ["#487A96", "#D39A54"]
INPUTS = [SOURCE / f"panel_{name}.csv" for name in ("ab", "cd", "ef")]
INPUTS += [OUTPUT / "loss_summary/window.csv.gz",
           OUTPUT / "panel_loss/country_selection.csv",
           OUTPUT / "catalogues/capacity_by_country.csv",
           ROOT / "logs/paper_figures/completion_status/final_audit.json"]


def summarize(frame, keys):
    result = None
    for metric in METRICS:
        part = ensemble(frame, keys, metric, len(MODELS))
        part = part.rename(columns={c: f"{metric}_{c}" for c in part if c not in keys})
        result = part if result is None else result.merge(part, on=keys, validate="one_to_one")
    return result


def prepare():
    audit = json.loads(INPUTS[-1].read_text())
    assert audit["acceptance"]["status"] == "PASSED"
    ab, cd, ef = [pd.read_csv(p) for p in INPUTS[:3]]
    for frame in (ab, cd, ef):
        assert set(frame.model) == set(MODELS)
        assert frame.snapshot.eq(2050).all() and frame.support.eq("common").all()
        assert frame.event.eq("all").all() and "TWN" not in set(frame.country)
    assert len(ab) == 72
    assert not ab.duplicated(["model", "tech", "climate_ssp", "station_ssp"]).any()
    assert np.isfinite(ab.R).all()
    assert np.allclose(ab.R, ab.net_mwh / ab.capacity_mw)
    # A representative global combination is checked before country-wide validation.
    sample = ab[ab.tech.eq("wind") & ab.model.eq(MODELS[0])]
    expected = climate_deployment(sample.set_index(["climate_ssp", "station_ssp"]).R.to_dict())
    actual = cd[cd.tech.eq("wind") & cd.model.eq(MODELS[0]) & cd.country.eq("GLOBAL")].iloc[0]
    assert all(np.isclose(actual[k], expected[k], atol=1e-9) for k in METRICS)
    print("Representative global wind comparison passed", flush=True)

    chunks = []
    for chunk in pd.read_csv(INPUTS[3], chunksize=50000):
        take = chunk.snapshot.eq(2050) & chunk.event.eq("all") & chunk.support.eq("common")
        chunks.append(chunk.loc[take])
    window = pd.concat(chunks, ignore_index=True)
    keys = ["model", "tech", "country", "climate_ssp", "station_ssp"]
    assert not window.duplicated(keys).any()
    caps = window.groupby(["tech", "country", "station_ssp"]).capacity_mw.agg(["min", "max"])
    assert np.allclose(caps["min"], caps["max"], rtol=1e-10, atol=1e-6)
    refs = pd.read_csv(INPUTS[5])
    catalogue = refs[refs.snapshot.eq(2050)].rename(columns={"capacity_mw": "catalogue_capacity_mw"})
    globals_ = catalogue.groupby(["tech", "station_ssp", "snapshot"], as_index=False).catalogue_capacity_mw.sum()
    globals_["country"] = "GLOBAL"
    catalogue = pd.concat([catalogue, globals_], ignore_index=True)
    window = window.merge(catalogue[["tech", "station_ssp", "country", "catalogue_capacity_mw"]],
                          on=["tech", "station_ssp", "country"], validate="many_to_one", how="left")
    window["coverage_pct"] = 100 * window.capacity_mw / window.catalogue_capacity_mw
    window["window_start"] = 2050
    window["window_end"] = 2059
    window["unit"] = "MWh MW-1 yr-1"
    window["station_source"] = window.station_ssp.map(
        {"ssp126": "stations_SSP1-2.6.csv", "ssp245": "stations_SSP2-4.5.csv",
         "ssp585": "stations_SSP5-6.0.csv"})
    write_csv(SOURCE / "model_combinations_coverage.csv", window)
    indexed = window.set_index(keys).R
    checked = pd.concat([cd, ef]).drop_duplicates(["model", "tech", "country"])
    for row in checked.itertuples():
        r = {}
        for c in ("ssp126", "ssp585"):
            for s in ("ssp126", "ssp585"):
                r[c, s] = indexed.get((row.model, row.tech, row.country, c, s), np.nan)
        derived = climate_deployment(r)
        assert all(np.isclose(getattr(row, k), derived[k], equal_nan=True,
                              rtol=1e-10, atol=1e-8) for k in METRICS)
    all_closure = checked.Phi_C + checked.Phi_S - checked.D
    assert all_closure.dropna().abs().max() < 1e-8

    selection = pd.read_csv(INPUTS[4]).sort_values("order").head(8)
    cases = ["GLOBAL", *selection.country]
    assert set(cd.country) == set(cases) and len(cd) == 72
    assert np.isfinite(cd[METRICS]).all().all()
    heat = ensemble(ab, ["tech", "climate_ssp", "station_ssp"], "R", len(MODELS))
    contributions = summarize(cd, ["tech", "country"])
    points = summarize(ef, ["tech", "country"])
    ref = ef.groupby(["tech", "country"], as_index=False).reference_capacity_mw.first()
    points = points.merge(ref, on=["tech", "country"], validate="one_to_one")
    points["reference_capacity_gw"] = points.reference_capacity_mw / 1000
    points["plotted"] = (points[["delta_C_126_mean", "delta_C_585_mean", "J_mean"]].notna().all(axis=1)
                         & points.reference_capacity_gw.gt(0))
    points["exclusion_reason"] = np.where(points.plotted, "",
        np.where(~points.reference_capacity_gw.gt(0), "no_positive_reference_capacity",
                 "incomplete_four_model_counterfactual"))
    points["J_consistent"] = points.J_agreement.ge(3)
    for filename, frame in [("panel_ab_ensemble.csv", heat),
                            ("panel_cd_ensemble.csv", contributions),
                            ("panel_ef_ensemble.csv", points)]:
        write_csv(SOURCE / filename, frame)
    selected = contributions.merge(selection, on="country", how="left")
    selected = selected.merge(ref, on=["tech", "country"], how="left")
    selected.loc[selected.country.eq("GLOBAL"), "reason"] = "global_all_valid_stations"
    write_csv(SOURCE / "country_selection_audit.csv", selected)

    report = {
        "status": "PASSED",
        "upstream_acceptance": audit["acceptance"]["status"],
        "panels_ab": {"rows": len(ab), "cells": len(heat), "models_per_cell": 4},
        "panels_cd": {"rows": len(cd), "countries": cases,
                      "max_absolute_closure": float(all_closure.abs().max())},
        "panels_ef": {},
        "fixed_deployment_capacity_invariant": True,
        "country_contrasts_recomputed_from_nine_combinations": True,
        "china_taiwan_merged": "Inherited CHN catalogue; no TWN rows",
        "common_support": "Fixed stations and capacities across 4 models, 3 climates and 10 years",
        "time_support_limitation": "Finite annual Loss does not establish identical valid timestamps",
        "global_capacity_coverage_pct": window[window.country.eq("GLOBAL")].groupby(
            ["tech", "station_ssp"]).coverage_pct.first().to_dict(),
    }
    report["global_capacity_coverage_pct"] = {
        "/".join(k): float(v) for k, v in report["global_capacity_coverage_pct"].items()}
    for tech in TECHS:
        subset = points[points.tech.eq(tech)]
        report["panels_ef"][tech] = {
            "available_country_rows": len(subset), "plotted_countries": int(subset.plotted.sum()),
            "excluded_countries": subset.loc[~subset.plotted, ["country", "exclusion_reason"]].to_dict("records"),
            "J_at_least_3_of_4_agree": int((subset.plotted & subset.J_consistent).sum()),
        }
    write_json(OUT / "data_audit.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return ab, cd, ef, heat, contributions, points, cases


def label_panel(fig, letter, title, x, y):
    fig.text(x, y, letter, fontsize=8, weight="bold", va="bottom")
    fig.text(x + .025, y, title, fontsize=7, weight="bold", va="bottom")


def render(ab, cd, ef, heat, contributions, points, cases):
    configure()
    plt.rcParams.update({"font.size": 6.5, "axes.labelsize": 6.5,
                         "xtick.labelsize": 6, "ytick.labelsize": 6,
                         "legend.fontsize": 6, "axes.linewidth": .6})
    fig = plt.figure(figsize=(183 / 25.4, 165 / 25.4))
    axes = []
    hmin, hmax = heat["mean"].min(), heat["mean"].max()
    if hmin < 0:
        lim = max(abs(hmin), abs(hmax))
        hnorm, hcmap = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim), "RdBu_r"
    else:
        hnorm, hcmap = Normalize(np.floor(hmin / 10) * 10, np.ceil(hmax / 10) * 10), "Blues"
    for i, tech in enumerate(TECHS):
        left = .12 + i * .455
        ax = fig.add_axes([left, .802, .32, .145])
        axes.append(ax)
        matrix = heat[heat.tech.eq(tech)].pivot(index="climate_ssp", columns="station_ssp", values="mean").reindex(index=SSPS, columns=SSPS)
        im = ax.imshow(matrix, cmap=hcmap, norm=hnorm, aspect="auto")
        for row in range(3):
            for col in range(3):
                value = matrix.iloc[row, col]
                color = "white" if hnorm(value) > .62 else "#182735"
                ax.text(col, row, f"{value:.1f}", ha="center", va="center", color=color, fontsize=7)
            ax.add_patch(Rectangle((row-.47, row-.47), .94, .94,
                                   fill=False, lw=1, edgecolor="#262626"))
        ax.set(xticks=range(3), xticklabels=["126", "245", "585"],
               yticks=range(3), yticklabels=["126", "245", "585"],
               xlabel="Station SSP", ylabel="Climate SSP")
        ax.tick_params(length=0, pad=3)
        label_panel(fig, "ab"[i], f'{"Wind" if i == 0 else "Solar"} | global net loss', left-.035, .965)
    cax = fig.add_axes([.928, .806, .014, .139])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label(UNIT, fontsize=6)
    cb.ax.tick_params(labelsize=6, width=.5, length=2)

    lows, highs = [], []
    for tech in TECHS:
        g = contributions[contributions.tech.eq(tech)]
        lows.extend(np.minimum(g.Phi_C_mean, 0) + np.minimum(g.Phi_S_mean, 0))
        highs.extend(np.maximum(g.Phi_C_mean, 0) + np.maximum(g.Phi_S_mean, 0))
        lows.extend(g.D_minimum)
        highs.extend(g.D_maximum)
    span = max(highs) - min(lows)
    limits = (min(lows)-.055*span, max(highs)+.06*span)
    names = {"GLOBAL": "Global", "USA": "United States", "CHN": "China",
             "BRA": "Brazil", "RUS": "Russia", "IND": "India", "IRN": "Iran",
             "KAZ": "Kazakhstan", "AUS": "Australia"}
    for i, tech in enumerate(TECHS):
        left = .12 + i * .455
        ax = fig.add_axes([left, .484, .32, .217])
        axes.append(ax)
        g = contributions[contributions.tech.eq(tech)].set_index("country")
        for y, country in enumerate(cases):
            if country not in g.index or pd.isna(g.loc[country, "D_mean"]):
                ax.text(0, y, "not comparable", va="center", fontsize=6)
                continue
            row = g.loc[country]
            positive = negative = 0
            for metric, color in zip(("Phi_C_mean", "Phi_S_mean"), COLORS):
                value = row[metric]
                base = positive if value >= 0 else negative
                ax.barh(y, value, left=base, color=color, height=.57, edgecolor="white", linewidth=.25)
                if value >= 0:
                    positive += value
                else:
                    negative += value
            model_values = cd[cd.tech.eq(tech) & cd.country.eq(country)].set_index("model").reindex(MODELS).D
            ax.plot([row.D_minimum, row.D_maximum], [y+.22, y+.22], color="#333333", lw=.6, zorder=4)
            ax.scatter(model_values, y+np.array([.16, .20, .24, .28]), s=5,
                       c="#555555", linewidths=0, zorder=5)
            ax.scatter(row.D_mean, y, marker="D", s=13, facecolor="#222222", edgecolor="white", linewidth=.3, zorder=6)
        ax.axvline(0, color="#666666", lw=.55, zorder=0)
        ax.axhline(.5, color="#dddddd", lw=.5, zorder=0)
        ax.set(yticks=range(len(cases)), yticklabels=[names.get(c, c) for c in cases],
               ylim=(len(cases)-.5, -.6), xlim=limits, xlabel=f"Contribution / path difference ({UNIT})")
        ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.tick_params(axis="y", length=0, pad=3)
        ax.tick_params(axis="x", length=2, width=.5)
        label_panel(fig, "cd"[i], "Climate and deployment contributions", left-.035, .715)
    handles = [Patch(facecolor=COLORS[0], label="Climate"),
               Patch(facecolor=COLORS[1], label="Deployment"),
               Line2D([], [], marker="D", color="#222222", ls="", markersize=3, label="Net difference"),
               Line2D([], [], marker=".", color="#555555", lw=.6, markersize=3, label="4 models; min–max")]
    fig.legend(handles=handles, loc="center", bbox_to_anchor=(.52, .746), ncol=4,
               handlelength=1.4, columnspacing=1.3)

    plotted = points[points.plotted]
    jlim = np.ceil(plotted.J_mean.abs().max()/5)*5
    jnorm = TwoSlopeNorm(vmin=-jlim, vcenter=0, vmax=jlim)
    # Include the displayed model points in shared square limits.
    detail = ef[ef.country.isin(cases[1:3])]
    extent = np.r_[plotted.delta_C_126_mean, plotted.delta_C_585_mean,
                   detail.delta_C_126, detail.delta_C_585]
    lo = np.floor(np.nanmin(extent)/10)*10-4
    hi = np.ceil(np.nanmax(extent)/10)*10+4
    scale = .06  # marker area (pt squared) per GW, identical for both technologies
    for i, tech in enumerate(TECHS):
        left = .156 + i*.455
        ax = fig.add_axes([left, .112, .244, .2706])
        axes.append(ax)
        subset = plotted[plotted.tech.eq(tech)].sort_values("reference_capacity_gw", ascending=False)
        ax.plot([lo, hi], [lo, hi], color="#888888", ls="--", lw=.7, zorder=0)
        ax.axvline(0, color="#cccccc", lw=.5, zorder=0)
        ax.axhline(0, color="#cccccc", lw=.5, zorder=0)
        for consistent in (True, False):
            g = subset[subset.J_consistent.eq(consistent)]
            ax.scatter(g.delta_C_126_mean, g.delta_C_585_mean,
                       s=scale*g.reference_capacity_gw, c=g.J_mean,
                       cmap="RdBu_r", norm=jnorm, edgecolors="#252525" if consistent else "#aaaaaa",
                       linewidths=.5 if consistent else .8, alpha=.88, zorder=3)
        for country in cases[1:3]:
            g = detail[detail.tech.eq(tech) & detail.country.eq(country)]
            ax.scatter(g.delta_C_126, g.delta_C_585, s=6, marker="+",
                       color="#444444", linewidths=.45, zorder=4)
        offsets = {"wind": {"USA": (-17, -10), "CHN": (10, -12), "BRA": (-13, 12)},
                   "solar": {"USA": (-25, -8), "CHN": (9, 8), "BRA": (-26, 10)}}
        for country, offset in offsets[tech].items():
            row = subset[subset.country.eq(country)]
            if row.empty:
                continue
            r = row.iloc[0]
            ax.annotate(country, (r.delta_C_126_mean, r.delta_C_585_mean),
                        xytext=offset, textcoords="offset points", fontsize=6,
                        arrowprops={"arrowstyle": "-", "lw": .45, "color": "#666666"},
                        zorder=8)
        ax.set(xlim=(lo, hi), ylim=(lo, hi), aspect="equal",
               xlabel=f"Climate difference, deployment 126\n({UNIT})",
               ylabel=f"Climate difference, deployment 585\n({UNIT})")
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.tick_params(length=2, width=.5)
        ax.text(.97, .97, f"n = {len(subset)} countries", ha="right", va="top",
                transform=ax.transAxes, fontsize=6)
        label_panel(fig, "ef"[i], "Climate response under fixed deployment", .085+i*.455, .404)
    cax = fig.add_axes([.928, .132, .014, .223])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=jnorm, cmap="RdBu_r"), cax=cax)
    cb.set_label(f"Interaction J ({UNIT})", fontsize=6)
    cb.ax.tick_params(labelsize=6, width=.5, length=2)
    bubble_handles = [plt.scatter([], [], s=scale*v, facecolors="none",
                                   edgecolors="#666666", linewidths=.6, label=f"{v:,} GW")
                      for v in (100, 500, 1500)]
    fig.legend(handles=bubble_handles, loc="center", bbox_to_anchor=(.33, .025),
               ncol=3, title="Reference capacity: SSP126, 2050", title_fontsize=6,
               handletextpad=.5, columnspacing=1.2)
    fig.text(.60, .033, "Grey edge: J direction agreement <3/4", fontsize=6)
    fig.text(.60, .013, "+  Four models for USA and CHN", fontsize=6)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    from matplotlib.text import Text
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer)
        if not np.isfinite(box.extents).all():
            continue
        if box.x0 < -1 or box.y0 < -1 or box.x1 > fig.bbox.width+1 or box.y1 > fig.bbox.height+1:
            outside.append(artist.get_text())
    # Limit QA to active ticks; Matplotlib retains hidden out-of-range tick labels.
    outside = [s for s in outside if not s.replace("−", "-").replace(".", "").lstrip("-").isdigit()]
    if outside:
        raise ValueError(f"Text outside canvas: {outside}")
    for heading in fig.texts:
        if heading.get_fontweight() != "bold":
            continue
        box = heading.get_window_extent(renderer)
        for ax in axes:
            for label in (ax.xaxis.label, ax.yaxis.label):
                if box.overlaps(label.get_window_extent(renderer)):
                    raise ValueError(f"Panel heading overlaps axis label: {heading.get_text()}")
    save_png(fig, OUT / "fig04.png")
    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "job_id": os.environ.get("SLURM_JOB_ID"), "backend": "Python/matplotlib",
        "panels": "a-f", "snapshot": 2050, "analysis_window": [2050, 2059],
        "models": list(MODELS), "center": "Equal-weight mean of four model-resolved metrics",
        "range": "Four-model minimum–maximum, not a confidence interval",
        "case_order": cases, "scatter_modeled_detail": ["USA", "CHN"],
        "unit": "MWh MW-1 yr-1", "dpi": 600, "nominal_size_mm": [183, 165],
        "heatmap_limits": [hnorm.vmin, hnorm.vmax], "contribution_limits": list(limits),
        "scatter_limits": [lo, hi], "interaction_limits": [-jlim, jlim],
        "bubble_area_pt2_per_gw": scale,
        "inputs_sha256": {str(p.relative_to(ROOT)): digest(p) for p in INPUTS},
        "code_sha256": {str(p.relative_to(ROOT)): digest(p) for p in
                        [Path(__file__), ROOT/"paper_figures/common/metrics.py",
                         ROOT/"paper_figures/common/plotting.py"]},
        "automatic_qa": {"text_inside_canvas": True, "panel_headings_clear_of_axis_labels": True, "shared_technology_scales": True,
                         "scatter_equal_axes": True, "PNG_only": True},
        "visual_review": "pending",
    }
    write_json(OUT / "metadata.json", metadata)
    plt.close(fig)
    print(f"Saved {OUT / 'fig04.png'}", flush=True)


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    render(*prepare())


if __name__ == "__main__":
    main()
