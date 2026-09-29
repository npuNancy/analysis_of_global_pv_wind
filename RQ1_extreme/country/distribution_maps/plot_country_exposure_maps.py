"""Draw four country exposure maps from validated cached country metrics."""
from __future__ import annotations

import argparse
from pathlib import Path
import string

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm
from matplotlib.cm import ScalarMappable
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
import numpy as np
import pandas as pd

from prepare_country_exposure import OUTPUT, SHAPEFILE, SSPS, country_geometries, sha, write_json

SSP_LABELS = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
TECH_LABELS = {"wind": "Wind", "solar": "Solar PV", "combined": "Wind + solar PV"}
MAX_CIRCLE_AREA = 1000.0


def circle_area(capacity_gw, capacity_max):
    """Matplotlib scatter s is area in points squared."""
    return np.asarray(capacity_gw) / capacity_max * MAX_CIRCLE_AREA


def circle_position(geometry):
    # Largest polygon keeps multipart states anchored on their main landmass.
    parts = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    point = max(parts, key=lambda p: p.area).representative_point()
    return point.x, point.y


def finite_max(values, fallback=1.0):
    finite = np.asarray(values)[np.isfinite(values)]
    return max(float(finite.max()), fallback) if finite.size else fallback


def draw_maps(data, output, model):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "axes.titlesize": 11, "axes.labelsize": 9})
    metadata, geometries = country_geometries(SHAPEFILE)
    features = [(row["country"], geom) for row, geom in zip(metadata, geometries)
                if row["country"] != "Antarctica"]
    selected = data[(data.model == model) & (data.country != "UNASSIGNED")].copy()
    if selected.empty or selected.duplicated(["country", "scenario", "tech"]).any():
        raise ValueError("Missing or duplicate map rows")
    required = {(s, t) for s in SSPS for t in TECH_LABELS}
    if set(zip(selected.scenario, selected.tech)) != required:
        raise ValueError("All three scenarios and technologies are required")
    capacity_max = finite_max(selected.capacity_gw)
    exposure_max = finite_max(selected.grid_2050_days)
    station_max = finite_max(selected.station_2050_days)
    change_max = finite_max(abs(selected.grid_change_days))
    warm = LinearSegmentedColormap.from_list("country_exposure",
        ["#F7F1DC", "#F2DFC2", "#EBC9A4", "#E2AF87", "#D69372", "#C87760", "#B85B52", "#A44047"])
    cool = plt.get_cmap("YlGnBu")
    fill_norm = Normalize(0, exposure_max)
    station_norm = Normalize(0, station_max)
    change_norm = TwoSlopeNorm(vmin=-change_max, vcenter=0, vmax=change_max)
    projection = ccrs.PlateCarree()
    outputs = []
    for change in (False, True):
        for combined in (False, True):
            techs = ["combined"] if combined else ["wind", "solar"]
            nrows = len(techs)
            fig, axes = plt.subplots(nrows, 3, figsize=(14.4, 4.45 if combined else 7.1),
                                     subplot_kw={"projection": projection}, squeeze=False)
            fig.subplots_adjust(left=0.018, right=0.986, top=0.87 if combined else 0.91,
                                bottom=0.31 if combined else 0.205, wspace=0.04, hspace=0.10)
            norm = change_norm if change else fill_norm
            cmap = plt.get_cmap("RdBu_r") if change else warm
            metric = "grid_change_days" if change else "grid_2050_days"
            for row, tech in enumerate(techs):
                for col, ssp in enumerate(SSPS):
                    ax = axes[row, col]
                    ax.set_extent([-180, 180, -60, 85], crs=projection)
                    ax.set_facecolor("#ffffff")
                    table = selected[(selected.tech == tech) & (selected.scenario == ssp)].set_index("country")
                    circles = []
                    for country, geom in features:
                        values = table.loc[country] if country in table.index else None
                        value = values[metric] if values is not None else np.nan
                        face = cmap(norm(value)) if np.isfinite(value) else "#e3e3e3"
                        ax.add_geometries([geom], crs=projection, facecolor=face,
                                          edgecolor="#858585", linewidth=0.28, zorder=1)
                        if values is not None and np.isfinite(values.capacity_gw) and values.capacity_gw > 0:
                            circles.append((*circle_position(geom), values.capacity_gw, values.station_2050_days))
                    circles.sort(key=lambda c: -c[2])
                    for lon, lat, cap, days in circles:
                        ax.scatter(lon, lat, s=circle_area(cap, capacity_max), transform=projection,
                                   c=[cool(station_norm(days)) if np.isfinite(days) else "#b6b6b6"],
                                   edgecolors="white", linewidths=0.55, zorder=3)
                    ax.set_axis_off()
                    label = string.ascii_lowercase[row * 3 + col]
                    ax.set_title(f"({label})  {TECH_LABELS[tech]} | {SSP_LABELS[ssp]}", loc="left", pad=6)
            period = "2050s minus 2030s" if change else "2050s"
            fig.suptitle(f"Country extreme-weather exposure | {period}", y=0.99, fontsize=14)
            fig.text(0.5, 0.93 if combined else 0.952,
                     "Four-model mean · any extreme event · circles: 2050 capacity and 2050–2059 exposure",
                     ha="center", fontsize=9, color="#444444")
            bar_y = 0.185 if combined else 0.117
            for x, width, cm, nm, label in (
                (0.055, 0.30, cmap, norm, "Area-weighted exposure change (days/year)" if change else "Area-weighted exposure (days/year)"),
                (0.41, 0.30, cool, station_norm, "Capacity-weighted exposure (days/year)")):
                cax = fig.add_axes([x, bar_y, width, 0.022 if combined else 0.014])
                cb = fig.colorbar(ScalarMappable(norm=nm, cmap=cm), cax=cax, orientation="horizontal")
                cb.set_label(label, labelpad=3)
                cb.ax.tick_params(labelsize=8, length=2)
                cb.outline.set_linewidth(0.4)
            # Reference capacities use a common linear area scale in all four maps.
            power = 10 ** np.floor(np.log10(capacity_max))
            references = [power / 10, power / 2, power]
            handles = [Line2D([], [], marker="o", linestyle="", markersize=np.sqrt(circle_area(v, capacity_max)),
                              markerfacecolor="#9ca3af", markeredgecolor="white", markeredgewidth=0.55,
                              label=f"{v:,.0f}") for v in references]
            fig.legend(handles=handles, title="2050 capacity (GW)", loc="center",
                       bbox_to_anchor=(0.855, bar_y+0.008), ncol=3, frameon=False,
                       handletextpad=0.8, columnspacing=1.2, fontsize=8, title_fontsize=9)
            note = "Combined fill = wind + solar; combined circle color = capacity-weighted wind + solar."
            fig.text(0.025, 0.031 if combined else 0.025, note, fontsize=8, color="#444444")
            fig.text(0.025, 0.068 if combined else 0.050,
                     "Gray fill/circle: missing exposure. No circle: zero or unavailable capacity. Circle area is proportional to GW.",
                     fontsize=8, color="#444444")
            suffix = "combined" if combined else "wind_solar"
            stem = "country_exposure_change_2050s_minus_2030s" if change else "country_exposure_2050s"
            path = output / (stem + "_" + suffix + ".png")
            fig.savefig(path, dpi=300, facecolor="white")
            plt.close(fig)
            outputs.append(str(path))
    return {"figures": outputs, "model": model, "capacity_max_gw": capacity_max,
            "max_circle_area_pt2": MAX_CIRCLE_AREA, "fill_max_days": exposure_max,
            "change_limits_days": [-change_max, change_max], "station_max_days": station_max,
            "projection": "PlateCarree", "extent": [-180,180,-60,85],
            "shared_scales_across_four_figures": True, "circle_period": "2050 snapshot; exposure 2050–2059"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=OUTPUT/"csv/country_map_metrics.csv")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT/"figures")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = draw_maps(pd.read_csv(args.input), args.output_dir, "ensemble_mean")
    write_json(args.output_dir/"figure_config.json", {**config, "source_csv":str(args.input),
               "source_csv_sha256":sha(args.input), "code_sha256":sha(__file__)})
    print("\n".join(config["figures"]), flush=True)


if __name__ == "__main__":
    main()
