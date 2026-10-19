"""Plot 2050s global-grid SSP contrasts from audited exposure and dynamics summaries."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch, Rectangle
from matplotlib.text import Text
from matplotlib.transforms import Bbox
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from PIL import Image
from paper_figures.config import ROOT, TECHS, EVENTS, SSPS, SSP_COLORS, MODELS
from paper_figures.common.io import digest, write_json
from paper_figures.common.spatial import countries

FOLDER = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = FOLDER / "outputs"
GRID = OUT / "ssp_grid"
DYN = GRID / "dynamics/summary"
SOURCE = OUT / "source_data/ssp_grid_2050"
STEM = "fig01_ssp_grid_2050"
METRICS = ("exposure_days", "starts_per_year", "mean_complete_hours", "p95_area_pct")
UNITS = dict(zip(METRICS, ("day yr-1", "events cell-1 yr-1", "h event-1", "% of common area")))
METRIC_LABELS = ("Exposure\n(day yr⁻¹)", "Frequency\n(events cell⁻¹ yr⁻¹)", "Mean duration\n(h event⁻¹)", "Area P95\n(%)")
NAMES = {"high_temp": "High temperature", "high_wind": "High wind",
         "hot_humid": "Hot–humid", "icing": "Icing", "low_resource": "Low resource",
         "cold_highwind": "Cold + high wind", "freezing_rain": "Freezing rain",
         "high_humidity": "High humidity", "rainstorm": "Rainstorm",
         "overlap_correction": "Overlap correction", "all": "Union"}
SHORT = dict(NAMES, high_temp="High temp.", cold_highwind="Cold + wind",
             high_humidity="High humid.", freezing_rain="Freezing rain",
             overlap_correction="Overlap", low_resource="Low resource")
REGIONS = ("GLOBAL", "60N-90N", "30N-60N", "0-30N", "30S-0", "60S-30S")
LAT_LABELS = ("Global", "60–90°N", "30–60°N", "0–30°N", "0–30°S", "30–60°S")
GROUPS = {"ab": (0, .75, 1, 1), "cd": (0, .51, 1, .75),
          "ef": (0, .235, 1, .51), "gh": (0, 0, 1, .235)}
INPUTS = [DYN / "levels.csv", DYN / "levels_models.csv.gz",
          GRID / "levels.csv", GRID / "levels_models.csv.gz",
          GRID / "contrasts.csv", GRID / "contrasts_models.csv.gz",
          OUT / "source_data/panel_ab.csv.gz", OUT / "source_data/panel_ab_capacity.csv",
          GRID / "audit.json", DYN / "audit.json"]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def select_csv(path, selector):
    parts = []
    for chunk in pd.read_csv(path, chunksize=100000):
        part = chunk.loc[selector(chunk)]
        if len(part):
            parts.append(part)
    require(bool(parts), f"No selected rows: {path}")
    return pd.concat(parts, ignore_index=True)

def check_ensemble(levels, models, keys, value):
    require(not models.duplicated(keys + ["model"]).any(), "Duplicate model rows")
    require(set(models.model) == set(MODELS), "Model membership")
    expected = models.groupby(keys)[value].agg(["mean", "min", "max", "count"]).sort_index()
    actual = levels.set_index(keys).sort_index()
    require(expected.index.equals(actual.index), "Ensemble keys differ")
    require(expected["count"].eq(4).all(), "Incomplete ensemble")
    require(np.allclose(expected[["mean", "min", "max"]],
                        actual[["mean", "minimum", "maximum"]], atol=1e-9),
            "Model values do not reproduce plotted summaries")

def prepare():
    SOURCE.mkdir(parents=True, exist_ok=True)
    for p in (GRID / "audit.json", DYN / "audit.json"):
        require(json.loads(p.read_text())["status"] == "PASSED", f"Failed source audit: {p}")
    glob = lambda d: d.snapshot.eq(2050) & d.region.eq("global:GLOBAL") & d.event.eq("all") & d.metric.isin(METRICS)
    overview = select_csv(DYN / "levels.csv", glob)
    overview_models = select_csv(DYN / "levels_models.csv.gz", glob)
    check_ensemble(overview, overview_models, ["tech", "climate_ssp", "metric"], "value")
    require(len(overview) == 24, "Overview matrix")
    overview["unit"] = overview.metric.map(UNITS)
    base = overview[overview.climate_ssp.eq("ssp126")].set_index(["tech", "metric"])["mean"]
    overview["baseline_mean"] = [base.loc[(r.tech, r.metric)] for r in overview.itertuples()]
    for field in ("mean", "minimum", "maximum"):
        overview["relative_" + field] = overview[field] / overview.baseline_mean
    overview.to_csv(SOURCE / "panel_ab.csv", index=False)
    overview_models.to_csv(SOURCE / "panel_ab_models.csv", index=False)
    selector = lambda d: d.snapshot.eq(2050) & d.scope.eq("global") & ~d.event.isin(["all", "overlap_correction"])
    events = select_csv(GRID / "levels.csv", selector)
    event_models = select_csv(GRID / "levels_models.csv.gz", selector)
    check_ensemble(events, event_models, ["tech", "climate_ssp", "event"], "days_per_year")
    events["unit"] = "day yr-1"
    events.to_csv(SOURCE / "panel_cd.csv", index=False)
    event_models.to_csv(SOURCE / "panel_cd_models.csv", index=False)
    selector = lambda d: d.snapshot.eq(2050) & d.scope.isin(["global", "latitude"]) & d.low.eq("ssp126") & d.high.isin(["ssp245", "ssp585"])
    regional = select_csv(GRID / "contrasts.csv", selector)
    regional_models = select_csv(GRID / "contrasts_models.csv.gz", selector)
    keys = ["tech", "region", "high", "low", "event"]
    check_ensemble(regional, regional_models, keys, "difference")
    require(set(regional.region) == set(REGIONS), "Unexpected global/latitude support")
    max_closure = 0.
    for tech in TECHS:
        part = regional_models[regional_models.tech.eq(tech)]
        pivot = part.pivot(index=["region", "model", "high", "low"], columns="event", values="difference")
        err = (pivot[list(EVENTS[tech])].sum(axis=1) + pivot.overlap_correction - pivot["all"]).abs().max()
        max_closure = max(max_closure, float(err))
    require(max_closure < 1e-8, "Event overlap accounting does not close")
    regional["unit"] = "day yr-1"
    regional.to_csv(SOURCE / "panel_ef.csv", index=False)
    regional_models.to_csv(SOURCE / "panel_ef_models.csv", index=False)
    maps = pd.read_csv(OUT / "source_data/panel_ab.csv.gz")
    require(maps.snapshot.eq(2050).all() and maps.n_models.eq(4).all(), "Map scope")
    require(not maps.duplicated(["tech", "lat", "lon"]).any(), "Duplicate display grid")
    for col in ("mean", "minimum", "maximum"):
        maps[col] /= 24
    maps["unit"] = "day yr-1"
    maps["high"], maps["low"] = "ssp585", "ssp126"
    maps.to_csv(SOURCE / "panel_gh.csv.gz", index=False)
    bubbles = pd.read_csv(OUT / "source_data/panel_ab_capacity.csv")
    bubbles.to_csv(SOURCE / "panel_gh_capacity.csv", index=False)
    # Independent reproduction of the global exposure displayed in the dynamics overview.
    prior = select_csv(GRID / "levels.csv", lambda d: d.snapshot.eq(2050) & d.scope.eq("global") & d.event.eq("all"))
    joined = overview[overview.metric.eq("exposure_days")].merge(prior, on=["tech", "climate_ssp"], suffixes=("_new", "_old"))
    exposure_error = float((joined.mean_new - joined.mean_old).abs().max())
    require(len(joined) == 6 and exposure_error < 1e-5, "Exposure reference mismatch")
    return overview, events, regional, maps, bubbles, {"overlap_closure_max_days": max_closure,
            "global_exposure_reference_error_days": exposure_error, "ensemble_checks": "PASSED"}

def title(fig, col, y, letter, text):
    x = .022 + .50 * col
    fig.text(x, y, letter, weight="bold", fontsize=8, va="center")
    fig.text(x + .028, y, text, fontsize=7, va="center")

def legend(fig, y):
    fig.legend(handles=[Patch(facecolor=SSP_COLORS[s], label=s.upper()) for s in SSPS],
               loc="center", bbox_to_anchor=(.27, y), ncol=3,
               handlelength=1.4, columnspacing=1.2, fontsize=6, frameon=False)
    fig.text(.72, y, "Bars: model mean; whiskers: min–max (n = 4)",
             fontsize=5.5, va="center", ha="center")

def draw_overview(fig, table):
    legend(fig, .953)
    for col, tech in enumerate(TECHS):
        title(fig, col, .978, "ab"[col], f"{'Wind' if tech == 'wind' else 'Solar PV'} | Global event union")
        ax = fig.add_axes([.085 + col * .50, .805, .390, .128])
        data = table[table.tech.eq(tech)].set_index(["metric", "climate_ssp"])
        for si, ssp in enumerate(SSPS):
            rows = data.loc[[(m, ssp) for m in METRICS]]
            x = np.arange(4) + (si - 1) * .24
            ax.bar(x, rows.relative_mean, width=.22, color=SSP_COLORS[ssp], zorder=2)
            ax.errorbar(x, rows.relative_mean,
                        yerr=[rows.relative_mean - rows.relative_minimum,
                              rows.relative_maximum - rows.relative_mean],
                        fmt="none", ecolor="#333333", elinewidth=.55, capsize=0, zorder=3)
            for xx, row in zip(x, rows.itertuples()):
                ax.text(xx, row.relative_maximum + .008, f"{row.mean:.2f}",
                        rotation=90, fontsize=5.3, ha="center", va="bottom")
        ax.axhline(1, color="#555555", linestyle=(0, (3, 2)), lw=.55, zorder=1)
        require(table.relative_minimum.min() > .90 and table.relative_maximum.max() < 1.25,
                "Overview uncertainty outside truncated axis")
        ax.set_ylim(.90, 1.25)
        ax.set_yticks([.90, .95, 1, 1.05, 1.10, 1.15, 1.20, 1.25])
        ax.text(.99, .98, "Y axis starts at 0.90", transform=ax.transAxes,
                ha="right", va="top", fontsize=5.1, color="#555555")
        for yy in (.012, .032):
            ax.plot([-.012, .012], [yy - .008, yy + .008], transform=ax.transAxes,
                    color="#333333", lw=.7, clip_on=False)
        ax.set_xlim(-.6, 3.6)
        ax.set_xticks(range(4), METRIC_LABELS, fontsize=5.6)
        ax.set_ylabel("Relative to SSP126 mean", fontsize=6)
        ax.grid(axis="y", color="#e6e6e6", lw=.35, zorder=0)
    fig.text(.5, .766, "2050–2059 · Labels: original values and units · Area P95: 95th percentile of simultaneous affected area",
             ha="center", fontsize=5.7)

def draw_events(fig, table):
    legend(fig, .708)
    segments = {"wind": [(0, 2), (10, 30)], "solar": [(0, 5), (8, 15), (20, 30)]}
    ticks = {"wind": [0, 15, 20, 25, 30], "solar": [0, 10, 25, 30]}
    axes_metadata = {}
    for col, tech in enumerate(TECHS):
        title(fig, col, .734, "cd"[col], f"{'Wind' if tech == 'wind' else 'Solar PV'} | Exposure by event")
        data = table[table.tech.eq(tech)].set_index(["event", "climate_ssp"])
        omitted = [(a[1], b[0]) for a, b in zip(segments[tech], segments[tech][1:])]
        def compress(values):
            values = np.asarray(values, dtype=float)
            return values - sum(np.clip(values - lo, 0, hi - lo) for lo, hi in omitted)
        for row in data.itertuples():
            require(any(lo <= row.minimum <= row.mean <= row.maximum <= hi
                        for lo, hi in segments[tech]), "Event mean/model range lies in an omitted interval")
        ax = fig.add_axes([.15 + .50 * col, .552, .325, .137])
        for si, ssp in enumerate(SSPS):
            rows = data.loc[[(e, ssp) for e in EVENTS[tech]]]
            yy = np.arange(len(EVENTS[tech])) + (si - 1) * .24
            mean = compress(rows["mean"])
            ax.barh(yy, mean, height=.21, color=SSP_COLORS[ssp], zorder=2)
            ax.errorbar(mean, yy,
                        xerr=[mean - compress(rows.minimum), compress(rows.maximum) - mean],
                        fmt="none", ecolor="#333333", elinewidth=.55, capsize=0, zorder=3)
        ax.set_ylim(5.5, -.6)
        ax.set_xlim(0, compress(30))
        ax.set_xticks(compress(ticks[tech]), ticks[tech])
        ax.set_yticks(range(len(EVENTS[tech])))
        ax.set_yticklabels([NAMES[e].replace("High temperature", "High\ntemperature")
                            .replace("Cold + high wind", "Cold +\nhigh wind")
                            for e in EVENTS[tech]], fontsize=5.8)
        ax.tick_params(axis="y", length=0, pad=3)
        ax.grid(axis="x", color="#e6e6e6", lw=.35, zorder=0)
        ax.spines["left"].set_visible(False)
        # Compress omitted intervals in one axes so every bar is a single rectangle.
        for lo, hi in omitted:
            x = float(compress(lo))
            trans = ax.get_xaxis_transform()
            ax.plot([x - .25, x + .25], [0, 0], transform=trans, color="white",
                    lw=2, solid_capstyle="butt", clip_on=False, zorder=4)
            for offset in (-.10, .10):
                ax.plot([x + offset - .08, x + offset + .08], [-.012, .012],
                        transform=trans, color="#444444", lw=.65, clip_on=False, zorder=5)
            for value, dx, align in ((lo, -3, "right"), (hi, 3, "left")):
                ax.annotate(str(value), (x, 0), xycoords=trans, xytext=(dx, -4.5),
                            textcoords="offset points", ha=align, va="top", fontsize=5.8)
        if tech == "wind":
            for event in ("high_wind", "hot_humid"):
                yy = list(EVENTS[tech]).index(event)
                for xx, ssp in zip((11, 14, 17), SSPS):
                    ax.text(compress(xx), yy, f"{data.loc[(event, ssp), 'mean']:.3f}",
                            va="center", color=SSP_COLORS[ssp], fontsize=5.5)
        fig.text(.15 + .50 * col + .325 / 2, .531, "Exposure (day yr⁻¹)",
                 ha="center", fontsize=6)
        axes_metadata[tech] = {"visible_ranges": segments[tech],
                               "omitted_ranges": omitted,
                               "mm_per_day": .325 / float(compress(30)) * 183,
                               "coordinate_mapping": "subtract omitted interval lengths",
                               "continuous_bars": True, "break_marks": "bottom x-axis only",
                               "mean_and_full_model_range_visible": True}
    fig.text(.5, .516, "2050–2059 · Omitted (day yr⁻¹): wind 2–10; solar 5–8 and 15–20 · Event types may overlap",
             ha="center", fontsize=5.3)
    return axes_metadata

def draw_regions(fig, table):
    heat_axes = []
    limit = float(np.ceil(table["mean"].abs().max()))
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
    cmap = plt.get_cmap("RdBu_r")
    for col, tech in enumerate(TECHS):
        title(fig, col, .496, "ef"[col], f"{'Wind' if tech == 'wind' else 'Solar PV'} | Regional event accounting")
        fig.text(.27 + .5 * col, .480, "2050–2059 · Exposure differences from SSP126", ha="center", fontsize=5.8)
        events = [*EVENTS[tech], "overlap_correction", "all"]
        ax = fig.add_axes([.135 + .50 * col, .325, .34, .145])
        heat_axes.append(ax)
        nregions = len(REGIONS)
        stride, nrows = nregions + 1, 2 * nregions + 1
        values = np.full((nrows, len(events)), np.nan)
        data = table[table.tech.eq(tech)].set_index(["high", "region", "event"])
        positions = []
        for ci, high in enumerate(("ssp245", "ssp585")):
            for ri, region in enumerate(REGIONS):
                y = ri + stride * ci
                positions.append(y)
                for ei, event in enumerate(events):
                    values[y, ei] = data.loc[(high, region, event), "mean"]
        ax.imshow(values, cmap=cmap, norm=norm, aspect="auto", interpolation="nearest")
        for yi, xi in np.argwhere(np.isfinite(values)):
            val = values[yi, xi]
            text = "0.0" if abs(val) < .05 else f"{val:+.1f}"
            ax.text(xi, yi, text, ha="center", va="center", fontsize=5.1,
                    weight="bold" if yi in (0, stride) else "normal",
                    color="white" if abs(val) > .65 * limit else "#222222")
        ax.set_yticks(positions, list(LAT_LABELS) * 2, fontsize=5.6)
        for tick in ax.get_yticklabels():
            if tick.get_text() == "Global":
                tick.set_fontweight("bold")
        for row in (0, stride):
            ax.axhline(row + .5, color="#777777", lw=.4)
        ax.set_xticks(range(len(events)), [SHORT[e] for e in events], rotation=48, ha="right", fontsize=5.3)
        ax.tick_params(length=0, pad=2)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for offset, label in ((0, "SSP245 − 126"), (stride, "SSP585 − 126")):
            ax.text(-.29, 1 - (offset + nregions / 2) / nrows, label, transform=ax.transAxes,
                    rotation=90, va="center", ha="center", fontsize=5.5, fontweight="bold")
        ax.add_patch(Rectangle((len(events) - 1.5, -.5), 1, nrows, fill=False,
                               edgecolor="#333333", linewidth=.7, clip_on=False))
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
                      cax=fig.add_axes([.30, .268, .40, .006]), orientation="horizontal")
    cb.set_label("Exposure difference (day yr⁻¹)", fontsize=5.8, labelpad=1)
    cb.ax.tick_params(labelsize=5.4, length=2, pad=1)
    cb.outline.set_linewidth(.4)
    footer = fig.text(.5, .238, "Sum of event changes + overlap correction = union change · Four-model means; accounting, not causal attribution",
             ha="center", fontsize=5.3)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in heat_axes:
        for tick in ax.get_xticklabels():
            require(not tick.get_window_extent(renderer).overlaps(cb.ax.get_window_extent(renderer)),
                    "Heatmap tick label overlaps colorbar")
    require(not footer.get_window_extent(renderer).overlaps(cb.ax.xaxis.label.get_window_extent(renderer)),
            "Heatmap colorbar label overlaps footer")
    return limit

def draw_maps(fig, maps, bubbles):
    pc = ccrs.PlateCarree()
    geo = countries()
    norm = TwoSlopeNorm(vmin=-12.5, vcenter=0, vmax=12.5)
    cmap = plt.get_cmap("RdBu_r")
    for col, tech in enumerate(TECHS):
        title(fig, col, .220, "gh"[col], f"{'Wind' if tech == 'wind' else 'Solar PV'} | Grid exposure difference")
        fig.text(.27 + .50 * col, .204, "2050–2059 · SSP585 − SSP126", ha="center", fontsize=6)
        ax = fig.add_axes([.045 + .5 * col, .069, .430, .127], projection=pc)
        ax.set_extent([-180, 180, -60, 85], crs=pc)
        ax.add_geometries([g for _, _, g in geo], pc, facecolor="#f4f4f4", edgecolor="none", zorder=0)
        data = np.full((180, 360), np.nan)
        subset = maps[maps.tech.eq(tech)]
        data[(subset.lat + 89.5).round().astype(int), (subset.lon + 179.5).round().astype(int)] = subset["mean"]
        ax.pcolormesh(np.arange(-180, 181), np.arange(-90, 91), data, cmap=cmap,
                      norm=norm, transform=pc, shading="flat", zorder=1)
        ax.add_geometries([g for _, _, g in geo], pc, facecolor="none", edgecolor="#666666", linewidth=.22, zorder=2)
        b = bubbles[bubbles.tech.eq(tech)].sort_values("capacity_gw", ascending=False)
        ax.scatter(b.lon_bin, b.lat_bin, s=b.capacity_gw * .45, transform=pc, facecolors="none",
                   edgecolors="#8a8a8a", linewidths=.22, alpha=.45, zorder=3)
        ax.gridlines(xlocs=[-120, -60, 0, 60, 120], ylocs=[-30, 0, 30, 60],
                     linewidth=.25, color="#888888", alpha=.45, linestyle=":")
        ax.set_xticks([-120, 0, 120], crs=pc)
        ax.set_yticks([0, 60], crs=pc)
        ax.xaxis.set_major_formatter(LongitudeFormatter())
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.tick_params(labelsize=5.3, length=2, pad=2)
        ax.spines["geo"].set_linewidth(.4)
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
        cax=fig.add_axes([.095, .037, .345, .007]), orientation="horizontal",
        ticks=[-12.5, -6.25, 0, 6.25, 12.5], extend="both")
    cb.set_label("Exposure difference (day yr⁻¹)", labelpad=1, fontsize=6)
    cb.ax.tick_params(labelsize=5.3, pad=1, length=2)
    cb.outline.set_linewidth(.4)
    leg = fig.add_axes([.54, .022, .42, .028])
    leg.set_xlim(0, 1); leg.set_ylim(0, 1); leg.axis("off")
    leg.text(0, .65, "Reference capacity\n(GW; SSP126, 2050)", va="center", fontsize=5.6)
    for x, v in zip((.58, .76, .94), (10, 50, 150)):
        leg.scatter([x], [.65], s=v * .45, facecolors="none", edgecolors="#8a8a8a", lw=.45, clip_on=False)
        leg.text(x, .03, str(v), ha="center", va="bottom", fontsize=5.5)
    fig.text(.5, .004, "Native area-weighted 1° display · Capacity circles are a fixed geographic reference, not statistical weights",
             ha="center", fontsize=5.4)
    return {tech: float((part["mean"].abs() > 12.5).mean())
            for tech, part in maps[maps.lat.between(-60, 85)].groupby("tech")}

def export(fig, name, bounds):
    renderer = fig.canvas.get_renderer()
    region = Bbox.from_extents(*bounds)
    clipped = []
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer).transformed(fig.transFigure.inverted())
        if box.overlaps(region) and (box.x0 < region.x0 - .002 or box.x1 > region.x1 + .002
                                    or box.y0 < region.y0 - .002 or box.y1 > region.y1 + .002):
            clipped.append(artist.get_text())
    require(not clipped, f"Clipped text in {name}: {clipped}")
    bbox = region.transformed(fig.transFigure).transformed(fig.dpi_scale_trans.inverted())
    path = OUT / name
    fig.savefig(path, dpi=600, bbox_inches=bbox, facecolor="white", pad_inches=0)
    with Image.open(path) as im:
        pixels = list(im.size); im.verify()
    return dict(path=name, sha256=digest(path), pixels=pixels, dpi=600, text_clipping="PASSED")

def main():
    overview, events, regional, maps, bubbles, checks = prepare()
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 6,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": .6,
        "xtick.labelsize": 5.8, "ytick.labelsize": 5.8, "xtick.major.width": .5,
        "ytick.major.width": .5, "xtick.major.size": 2, "ytick.major.size": 2})
    fig = plt.figure(figsize=(183 / 25.4, 260 / 25.4), dpi=150, facecolor="white")
    draw_overview(fig, overview)
    event_axes = draw_events(fig, events)
    heat_limit = draw_regions(fig, regional)
    saturation = draw_maps(fig, maps, bubbles)
    fig.canvas.draw()
    products = [export(fig, STEM + ".png", (0, 0, 1, 1))]
    products += [export(fig, STEM + "_" + group + ".png", bounds) for group, bounds in GROUPS.items()]
    plt.close(fig)
    metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        job_id=os.environ.get("SLURM_JOB_ID"), backend="Python/matplotlib + Cartopy",
        archetype="quantitative grid", canvas_mm=[183, 260], dpi=600,
        window=[2050, 2059], columns=["wind", "solar"], scenarios=list(SSPS), models=list(MODELS),
        core_question="How do climate SSPs differ in global event dynamics, event exposure and regional event composition?",
        panels={"ab": "union metrics grouped by metric; 3 SSP bars; fixed SSP126 ensemble-mean normalization",
                "cd": "event exposure grouped horizontal bars for three SSPs; continuous bars on compressed coordinates; bottom x-axis break marks only",
                "ef": "global and latitude-band event exposure contrasts; exact overlap accounting; SSP245 and SSP585 versus SSP126",
                "gh": "SSP585 minus SSP126 union exposure; original Fig.1 map data and style"},
        overview_y_limits=[.90, 1.25],
        overview_axis_truncated=True,
        event_axes=event_axes,
        event_comparison="Absolute event exposure under three SSPs; equal-model means and min-max",
        uncertainty="four-model mean and min-max; no significance inference",
        metric_definitions={"exposure": "area-weighted annual union hours / 24; not calendar event days",
            "frequency": "area-weighted known event starts per grid cell per year",
            "duration": "area-weighted complete-event pooled hours per complete event; censored fragments excluded",
            "extent": "time P95 of simultaneous affected share of fixed common area; not temporal mean",
            "normalization": "all model values divided by that metric and technology's SSP126 ensemble mean"},
        weighting="common native cell area; equal model weights; no capacity weighting",
        overlap_definition="union exposure minus sum of individual-event exposures; signed correction changes close exactly",
        projection="PlateCarree", map_extent=[-180, 180, -60, 85],
        map_limits_days=[-12.5, 12.5], map_extend="both", saturation_fraction=saturation,
        heatmap_limits_days=[-heat_limit, heat_limit],
        heatmap_regions=list(REGIONS),
        capacity_reference="fixed SSP126/2050, 3-degree bins; symbol area 0.45 points^2 per GW",
        checks=checks, products=products, visual_review="PENDING",
        source_data=[dict(path=str(p.relative_to(OUT)), sha256=digest(p)) for p in [SOURCE / name for name in ("panel_ab.csv", "panel_ab_models.csv", "panel_cd.csv", "panel_cd_models.csv", "panel_ef.csv", "panel_ef_models.csv", "panel_gh.csv.gz", "panel_gh_capacity.csv")]],
        inputs=[dict(path=str(p), sha256=digest(p)) for p in INPUTS],
        code_sha256=digest(Path(__file__)))
    write_json(OUT / (STEM + "_metadata.json"), metadata)
    print(json.dumps({"products": products, "checks": checks, "heatmap_limit": heat_limit}), flush=True)

if __name__ == "__main__":
    main()
