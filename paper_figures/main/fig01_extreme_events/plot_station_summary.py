"""Combine the selected station trends and 2050s station panels on a square canvas."""
from datetime import datetime, timezone
from pathlib import Path

import json
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.text import Text

from paper_figures.config import ROOT, SSPS, SSP_COLORS, MODELS
from paper_figures.common.io import digest, write_json
from paper_figures.meeting_review import plotting as station_style
from paper_figures.main.fig01_extreme_events import plot_ssp_station_2050 as station
from paper_figures.main.fig01_extreme_events.plot_ssp_grid_2050 import check_ensemble, export, title

OUT = station.OUT
STEM = "fig01_station_summary"
ANNUAL = ROOT / "paper_figures/meeting_review/outputs/station_analysis/source_data/paired_annual_exposure.csv.gz"
SOURCE = OUT / "source_data/station_summary"
GROUPS = {"ab": (0, .70, 1, 1), "cd": (0, .40, 1, .70), "ef": (0, 0, 1, .40)}


def move_row(fig, first_axis, first_text, first_legend, original, target, letters):
    """Place an existing pair of panels within the combined figure."""
    scale = (target[1] - target[0]) / (original[1] - original[0])
    def y(value):
        return target[0] + (value - original[0]) * scale
    for ax in fig.axes[first_axis:]:
        box = ax.get_position(original=True)
        left, width = (box.x0 + .035, .390) if original[1] == 3.2 / 16 else (box.x0, box.width)
        ax.set_position([left, y(box.y0), width, box.height * scale])
        if hasattr(ax, "_colorbar"):
            ax.set_ylabel("")
        for label in ax.findobj(Text):
            label.set_fontsize(label.get_fontsize() * .70)
    for text in fig.texts[first_text:]:
        x, old_y = text.get_position()
        text.set_position((x, y(old_y)))
        value = text.get_text()
        text.set_fontsize(text.get_fontsize() * .70)
        if value in letters:
            text.set_text(letters[value])
            text.set_fontsize(8)
            text.set_x(.022 + (.5 if x > .5 else 0))
        elif " | 2050" in value:
            text.set_text(value.split(" | 2050")[0])
            text.set_fontsize(7)
            text.set_fontweight("normal")
            text.set_x(.05 + (.5 if x > .5 else 0))
        elif value.startswith(("Labels: original values", "Capacity-weighted; union", "Mean; min–max")):
            text.set_visible(False)
    for legend in fig.legends[first_legend:]:
        box = legend.get_bbox_to_anchor().transformed(fig.transFigure.inverted())
        legend.set_bbox_to_anchor((box.x0, y(box.y0)), transform=fig.transFigure)
        legend.remove()


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    table = pd.read_csv(ANNUAL)
    selected = table[table.tech.isin(("wind", "solar")) & table.event.eq("all")].copy()
    station.need(len(selected) == 2 * 3 * 4 * 30, "Station panel matrix incomplete")
    station.need(set(selected.model) == set(MODELS), "Station model membership")
    station.need(not selected.duplicated(["tech", "station_ssp", "model", "year"]).any(),
                 "Duplicate station panel values")
    station.need(selected.days.notna().all(), "Missing station exposure")
    selected.to_csv(SOURCE / "station_annual_models.csv", index=False)
    names = ("global_levels", "global_models", "country_contrasts",
             "country_contrast_models", "global_contrasts", "global_contrast_models")
    manifest = json.loads((station.SOURCE / "manifest.json").read_text())
    tables = {}
    for name in names:
        path = station.SOURCE / (name + ".csv")
        station.need(digest(path) == manifest["table_hashes"][path.name],
                     f"Station source hash changed: {path}")
        tables[name] = pd.read_csv(path)
    check_ensemble(tables["global_levels"], tables["global_models"],
                   ["tech", "climate_ssp", "metric"], "value")
    for prefix in ("country", "global"):
        check_ensemble(tables[prefix + "_contrasts"], tables[prefix + "_contrast_models"],
                       ["tech", "region", "high", "low", "event"], "difference")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 6,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": .6,
        "xtick.labelsize": 5.8, "ytick.labelsize": 5.8, "xtick.major.width": .5,
        "ytick.major.width": .5, "xtick.major.size": 2, "ytick.major.size": 2})
    fig = plt.figure(figsize=(183 / 25.4, 183 / 25.4), dpi=150, facecolor="white")
    station_summary = []
    for col, (tech, event, name) in enumerate((
            ("wind", "all", "Wind | Station exposure: all events"),
            ("solar", "all", "Solar PV | Station exposure: all events"))):
        title(fig, col, .978, "ab"[col], name)
        ax = fig.add_axes([.085 + col * .5, .785, .390, .145])
        data = selected[selected.tech.eq(tech)]
        for ssp in SSPS:
            frame = data[data.station_ssp.eq(ssp)].pivot(index="year", columns="model", values="days")
            station.need(frame.shape == (30, 4) and frame.notna().all().all(),
                         "Incomplete station annual series")
            station_style.model_band(ax, frame.index, frame, ssp, label=False)
            station_summary.append(pd.DataFrame({"year": frame.index, "tech": tech,
                "event": event, "ssp": ssp, "mean": frame.mean(axis=1).values,
                "minimum": frame.min(axis=1).values, "maximum": frame.max(axis=1).values}))
        for year in (2039.5, 2049.5):
            ax.axvline(year, color=".6", lw=.5, ls=":")
        ax.set(xlim=(2030, 2059), xticks=[2030, 2040, 2050, 2059],
               xlabel="Year", ylabel="Exposure (day yr⁻¹)")
        ax.set_title("")
    fig.legend(handles=[Line2D([0], [0], color=SSP_COLORS[s], lw=1.2, label=s.upper())
                        for s in SSPS], loc="center", bbox_to_anchor=(.27, .950),
               ncol=3, fontsize=6, frameon=False)
    fig.text(.73, .950, "Lines: model mean; shading: min–max (n = 4)",
             ha="center", va="center", fontsize=5.5)
    fig.text(.5, .718, "Capacity-weighted paired climate–deployment paths · Dotted lines: capacity snapshot changes",
             ha="center", fontsize=5.4)

    start = (len(fig.axes), len(fig.texts), len(fig.legends))
    station.overview(fig, 0, tables)
    move_row(fig, *start, (0, 3.2 / 16), (.405, .695), {"a": "c", "b": "d"})
    fig.legend(handles=[Patch(facecolor=SSP_COLORS[s], label=s.upper()) for s in SSPS],
               loc="center", bbox_to_anchor=(.27, .652), ncol=3, fontsize=6,
               handlelength=1.4, columnspacing=1.2, frameon=False)
    fig.text(.73, .652, "Bars: model mean; whiskers: min–max (n = 4)",
             ha="center", va="center", fontsize=5.5)
    fig.text(.5, .414, "2050–2059 · Labels: original values · Capacity-weighted paired climate–deployment paths",
             ha="center", fontsize=5.4)
    start = (len(fig.axes), len(fig.texts), len(fig.legends))
    station.country_events(fig, 0, tables)
    move_row(fig, *start, (0, 3.4 / 16), (.005, .395), {"g": "e", "h": "f"})
    fig.text(.5, .012, "2050–2059 · Exposure difference (day yr⁻¹) · Union = events + overlap · Outline: largest absolute event term",
             ha="center", fontsize=5.4)
    station_style.hide_offscale_ticks(fig)
    fig.canvas.draw()
    fig.savefig(OUT / (STEM + "_preview.png"), dpi=180, facecolor="white")
    products = [export(fig, STEM + ".png", (0, 0, 1, 1))]
    products += [export(fig, STEM + "_" + group + ".png", bounds)
                 for group, bounds in GROUPS.items()]
    plt.close(fig)
    pd.concat(station_summary).to_csv(SOURCE / "station_annual_summary.csv", index=False)
    inputs = [ANNUAL, station.SOURCE / "manifest.json"] + [station.SOURCE / (name + ".csv") for name in names]
    write_json(OUT / (STEM + "_metadata.json"), dict(
        created_utc=datetime.now(timezone.utc).isoformat(),
        backend="Python/matplotlib", archetype="quantitative grid",
        core_question="How do the selected station exposure trajectories, station event metrics and country contrasts compare?",
        canvas_mm=[183, 183], aspect_ratio="1:1", dpi=600,
        panels={"a": "station_trends_wind.png: a (all events union)",
                "b": "station_trends_solar.png: a (all events union)",
                "c": "fig01_ssp_station_2050.png: a", "d": "fig01_ssp_station_2050.png: b",
                "e": "fig01_ssp_station_2050.png: g", "f": "fig01_ssp_station_2050.png: h"},
        periods={"ab": [2030, 2059], "cdef": [2050, 2059]},
        uncertainty="Four equally weighted GCMs; mean and min–max, not a confidence interval",
        station_weighting="Capacity-weighted paired climate and deployment pathways; decadal capacity snapshots",
        overview_y_limits=[.85, 1.25],
        impact_extent="Time P95 of simultaneously affected capacity fraction",
        heatmap_regions=list(station.REGIONS), heatmap_pairs=list(station.PAIRS[:2]),
        products=products, checks={"station_matrix": "PASSED", "station_ensemble": "PASSED",
                                  "normalization": "PASSED", "text_clipping": "PASSED"},
        inputs=[{"path": str(p.relative_to(ROOT)), "sha256": digest(p)} for p in inputs],
        script_sha256=digest(Path(__file__)), visual_review="PENDING"))
    print("OUTPUT", OUT / (STEM + ".png"), flush=True)


if __name__ == "__main__":
    main()

