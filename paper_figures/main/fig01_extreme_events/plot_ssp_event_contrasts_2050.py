"""Compare 2050s SSP585–SSP126 event exposure at grid and installed-capacity scales."""
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.text import Text
from PIL import Image

from paper_figures.config import ROOT, MODELS, TECHS, EVENTS
from paper_figures.common.io import digest, write_json

BASE = ROOT / "paper_figures/main/fig01_extreme_events"
OUT = BASE / "outputs"
SOURCE = OUT / "source_data/ssp_event_contrasts_2050"
STEM = "fig01_ssp_event_contrasts_2050"
INPUTS = {
    "grid_models": OUT / "source_data/ssp_grid_2050/panel_cd_models.csv",
    "grid_levels": OUT / "source_data/ssp_grid_2050/panel_cd.csv",
    "station_models": OUT / "source_data/ssp_station_2050/event_models.csv",
    "station_levels": OUT / "source_data/ssp_station_2050/event_levels.csv",
    "station_manifest": OUT / "source_data/ssp_station_2050/manifest.json",
}
NAMES = {
    "high_temp": "High temperature", "high_wind": "High wind",
    "hot_humid": "Hot–humid", "icing": "Icing", "low_resource": "Low resource",
    "cold_highwind": "Cold + high wind", "freezing_rain": "Freezing rain",
    "high_humidity": "High humidity", "rainstorm": "Rainstorm",
}
STYLES = {
    "grid": dict(facecolor="#b9bfc7", edgecolor="#616b76", hatch=None),
    "station": dict(facecolor="#779bbd", edgecolor="#234b78", hatch="///"),
}
LABELS = {
    "grid": "Global grid (area-weighted)",
    "station": "Global installed capacity (capacity-weighted)",
}
CAPTION = """# 2050年代各事件暴露时长的SSP585−SSP126差值

左图a为风电，右图b为光伏。每类事件的上方灰色条表示全球网格面积加权结果，下方蓝色斜线条表示全球装机容量加权结果。
横轴为年均累计暴露时长之差，单位day yr⁻¹；1 day = 24 h，不是发生过事件的日历天数。
正值表示SSP585暴露更长，负值表示SSP585暴露更短。条形及数值标签为四个气候模式的差值均值；
水平细线为先逐模式相减后得到的最小值—最大值，不是置信区间。

时期统一为2050–2059年，装机采用各部署路径的2050年容量快照。
网格比较气候SSP585与SSP126；装机比较(气候585, 部署585)与(气候126, 部署126)，因而同时包含气候与部署变化。
场站SSP585沿用正式产品映射，对应原始SSP5-6.0部署文件。
各事件可能重叠，分类差值之和不等于全部事件并集差；图中仅展示各类事件。
冻雨、覆冰沿用上游气象阈值事件标签，不代表直接观测的降水相态或实际积冰量。

图件及源数据由plot_ssp_event_contrasts_2050.py生成。完整图及a、b独立子图均为600 dpi PNG，两面板共用线性坐标范围。
"""

def need(condition, message):
    if not condition:
        raise ValueError(message)

def prepare():
    grid = pd.read_csv(INPUTS["grid_models"])
    station = pd.read_csv(INPUTS["station_models"])
    grid_ref = pd.read_csv(INPUTS["grid_levels"])
    station_ref = pd.read_csv(INPUTS["station_levels"])
    manifest = json.loads(INPUTS["station_manifest"].read_text())
    for name in ["event_models.csv", "event_levels.csv"]:
        path = INPUTS["station_models"].parent / name
        need(digest(path) == manifest["table_hashes"][name], "Station source hash: " + name)
    need(grid.snapshot.eq(2050).all() and station.snapshot.eq(2050).all(), "Window")
    need(grid.scope.eq("global").all() and grid.region.eq("GLOBAL").all(), "Global grid")
    need(station.region.eq("global:GLOBAL").all(), "Global capacity")
    need(station.climate_ssp.eq(station.station_ssp).all(), "Paired climate/deployment paths")
    keys = ["tech", "event", "model", "climate_ssp"]
    grid = grid.rename(columns={"days_per_year": "value"})
    # Preserve spatial support and capacity-path identity with the source levels.
    grid["station_ssp"] = pd.NA
    grid["weighting"] = "common native-grid area"
    station["weighting"] = "effective installed capacity"
    levels = pd.concat([grid.assign(spatial_level="grid"),
                        station.assign(spatial_level="station")], ignore_index=True)
    levels = levels[levels.climate_ssp.isin(["ssp126", "ssp585"])].copy()
    need(not levels.duplicated(["spatial_level"] + keys).any(), "Unique model levels")
    need(np.isfinite(levels.value).all(), "Finite source exposure")
    for (scope, tech), rows in levels.groupby(["spatial_level", "tech"]):
        need(set(rows.event) == set(EVENTS[tech]), "Complete event inventory")
        need(set(rows.model) == set(MODELS), "Complete four-model ensemble")
        need(rows.groupby(["event", "climate_ssp"]).size().eq(4).all(), "Four models per cell")

    refs = pd.concat([grid_ref.assign(spatial_level="grid"),
                      station_ref.assign(spatial_level="station")], ignore_index=True)
    reference_keys = ["spatial_level", "tech", "event", "climate_ssp"]
    expected = levels.groupby(reference_keys).value.mean().rename("calculated")
    check = expected.to_frame().join(refs.set_index(reference_keys)[["mean"]], validate="one_to_one")
    level_error = float((check.calculated - check["mean"]).abs().max())
    need(check["mean"].notna().all() and level_error < 1e-9, "Reproduce existing figure levels")

    pair_keys = ["spatial_level", "tech", "event", "model", "snapshot"]
    wide = levels.pivot(index=pair_keys, columns="climate_ssp", values="value")
    need(wide[["ssp126", "ssp585"]].notna().all().all(), "Matched SSP/model pairs")
    paired = wide.rename(columns={"ssp126": "value_low", "ssp585": "value_high"}).reset_index()
    paired.columns.name = None
    paired["difference"] = paired.value_high - paired.value_low
    paired["high"] = "ssp585"
    paired["low"] = "ssp126"
    paired["station_ssp_high"] = np.where(paired.spatial_level.eq("station"), "ssp585", "")
    paired["station_ssp_low"] = np.where(paired.spatial_level.eq("station"), "ssp126", "")
    paired["period_start"] = 2050
    paired["period_end"] = 2059
    paired["unit"] = "day yr-1"
    summary = paired.groupby(["spatial_level", "tech", "event"], as_index=False).agg(
        mean=("difference", "mean"), minimum=("difference", "min"),
        maximum=("difference", "max"), n_models=("difference", "size"),
        positive_models=("difference", lambda x: int((x > 0).sum())),
        negative_models=("difference", lambda x: int((x < 0).sum())),
        ssp126_mean=("value_low", "mean"), ssp585_mean=("value_high", "mean"))
    need(len(summary) == 22 and summary.n_models.eq(4).all(), "22 event/scope comparisons")
    delta_error = float((summary["mean"] - (summary.ssp585_mean - summary.ssp126_mean)).abs().max())
    need(delta_error < 1e-9, "Difference of ensemble means")
    summary["high"] = "ssp585"
    summary["low"] = "ssp126"
    summary["snapshot"] = 2050
    summary["period_start"] = 2050
    summary["period_end"] = 2059
    summary["unit"] = "day yr-1"
    SOURCE.mkdir(parents=True, exist_ok=True)
    for name, frame in [("levels_models", levels), ("contrasts_models", paired), ("contrasts", summary)]:
        frame.to_csv(SOURCE / (name + ".csv"), index=False)
    return summary, {"source_level_max_error": level_error,
                     "paired_difference_max_error": delta_error, "n_models": 4,
                     "summary_rows": len(summary), "paired_model_rows": len(paired)}

def number(value):
    digits = 4 if 0 < abs(value) < .005 else 2
    return f"{value:+.{digits}f}".replace("-", "−")

def panel(ax, tech, letter, summary, limit):
    rows = summary[summary.tech.eq(tech)].set_index(["spatial_level", "event"])
    events = list(EVENTS[tech])
    positions = np.arange(len(events), dtype=float) + (6 - len(events)) / 2
    for i, yy in enumerate(positions):
        if i % 2 == 0:
            ax.axhspan(yy - .48, yy + .48, color="#f4f6f8", zorder=0)
    for scope, offset in [("grid", -.17), ("station", .17)]:
        for event, yy in zip(events, positions):
            row = rows.loc[(scope, event)]
            y = yy + offset
            ax.barh(y, row["mean"], height=.27, linewidth=.55, zorder=2, **STYLES[scope])
            ax.hlines(y, row.minimum, row.maximum, color="#303841", linewidth=.7, zorder=3)
            edge = row.maximum if row["mean"] >= 0 else row.minimum
            direction = 1 if row["mean"] >= 0 else -1
            ax.annotate(number(row["mean"]), (edge, y),
                        xytext=(direction * 3.5, 0), textcoords="offset points",
                        ha="left" if direction > 0 else "right", va="center",
                        fontsize=6.8, color="#243244")
    ax.axvline(0, color="#434b54", linewidth=.8, zorder=1)
    ax.set_xlim(-limit, limit)
    ax.set_ylim(5.6, -.6)
    ax.set_yticks(positions, [NAMES[e] for e in events])
    ax.set_xticks(np.arange(-limit, limit + .01, 2))
    ax.tick_params(axis="y", length=0, pad=4)
    ax.tick_params(axis="x", length=3, width=.65)
    ax.spines["left"].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#dce2e8", linewidth=.45)
    ax.set_xlabel("Exposure difference (day yr⁻¹)", labelpad=5)
    ax.set_title("Wind" if tech == "wind" else "Solar PV", loc="left",
                 fontsize=9, fontweight="bold", pad=10)
    ax.text(-.18, 1.04, letter, transform=ax.transAxes, fontsize=10,
            fontweight="bold", va="bottom", ha="left")

def render(summary, limit, technologies, suffix):
    single = len(technologies) == 1
    width = 100 if single else 183
    height = 112
    fig = plt.figure(figsize=(width / 25.4, height / 25.4))
    fig.suptitle("SSP585 − SSP126 | 2050–2059", y=.975, fontsize=10, fontweight="bold")
    handles = [Patch(label=LABELS[s], linewidth=.55, **STYLES[s]) for s in ["grid", "station"]]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .927),
               ncol=1 if single else 2, fontsize=7, frameon=False,
               handlelength=2.4, handleheight=1.1, columnspacing=2)
    for column, tech in enumerate(technologies):
        rect = [.30, .25, .64, .51] if single else [.16 + .49 * column, .25, .32, .55]
        ax = fig.add_axes(rect)
        panel(ax, tech, "a" if tech == "wind" else "b", summary, limit)
    statistics_text = fig.text(.5, .115, "Bars / labels: four-model mean; whiskers: model min–max",
             ha="center", fontsize=6.5)
    fig.text(.5, .078, "Negative: less exposure in SSP585 | Positive: more exposure",
             ha="center", fontsize=6.5)
    fig.text(.5, .041, "Capacity comparison includes climate + deployment changes.",
             ha="center", fontsize=6.3, color="#536272")
    fig.text(.5, .012, "Event types can overlap; their differences are not additive.",
             ha="center", fontsize=6.3, color="#536272")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = fig.bbox
    for ax in fig.axes:
        need(ax.xaxis.label.get_window_extent(renderer).y0 > statistics_text.get_window_extent(renderer).y1 + 2,
             "Axis label overlaps the statistical note")
    outside = []
    for item in fig.findobj(Text):
        if item.get_visible() and item.get_text().strip():
            box = item.get_window_extent(renderer)
            if box.x0 < bounds.x0 - 1 or box.y0 < bounds.y0 - 1 or box.x1 > bounds.x1 + 1 or box.y1 > bounds.y1 + 1:
                outside.append(item.get_text())
    need(not outside, "Text exceeds canvas: " + repr(outside))
    filename = OUT / (STEM + suffix + ".png")
    fig.savefig(filename, dpi=600, facecolor="white")
    plt.close(fig)
    with Image.open(filename) as image:
        pixels = list(image.size)
    return {"file": filename.name, "pixels": pixels, "sha256": digest(filename),
            "text_clipping": "PASSED"}

def main():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial"],
        "font.size": 7.2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": .65, "axes.unicode_minus": True, "hatch.linewidth": .45,
    })
    OUT.mkdir(parents=True, exist_ok=True)
    summary, validation = prepare()
    extent = float(np.abs(summary[["minimum", "maximum"]].to_numpy()).max())
    limit = max(2., 2 * math.ceil((extent + .6) / 2))
    files = [render(summary, limit, list(TECHS), ""),
             render(summary, limit, ["wind"], "_a"),
             render(summary, limit, ["solar"], "_b")]
    (OUT / (STEM + "_caption.md")).write_text(CAPTION, encoding="utf-8")
    write_json(OUT / (STEM + "_metadata.json"), {
        "status": "PASSED", "created_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "Python/matplotlib", "archetype": "quantitative grid",
        "core_question": "Which event-specific SSP585-minus-SSP126 exposure differences change with area versus capacity weighting?",
        "panels": {"a": "wind; five event types", "b": "solar PV; six event types"},
        "comparison": "SSP585 minus SSP126", "period": [2050, 2059],
        "capacity_snapshot": 2050, "unit": "day yr-1",
        "scope": {"grid": "area-weighted; common native-grid support; climate SSP",
                  "station": "capacity-weighted; paired climate and station SSP"},
        "statistic": "equal-weight mean of four paired model differences",
        "uncertainty": "four-model min–max; not confidence intervals",
        "models": list(MODELS), "x_limits": [-limit, limit], "axes": "linear, shared, zero-based bars",
        "dpi": 600, "canvas_mm": [183, 112], "files": files, "validation": validation,
        "inputs": {str(p.relative_to(ROOT)): digest(p) for p in INPUTS.values()},
        "source_data": {str(p.relative_to(ROOT)): digest(p) for p in SOURCE.glob("*.csv")},
        "code_sha256": digest(Path(__file__)), "job_id": os.environ.get("SLURM_JOB_ID"),
    })
    print(summary[["spatial_level", "tech", "event", "mean", "minimum", "maximum"]].to_string(index=False))
    print("RENDERED:", ", ".join(f["file"] for f in files))

if __name__ == "__main__":
    main()
