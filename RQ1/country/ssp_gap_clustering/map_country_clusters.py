"""World maps of country unit-loss gap clusters on a Plate Carree projection.

Reads the country_cluster_assignments.csv tables already produced by
country_unit_loss_clustering.py and paints each country by its cluster label
for every model and the ensemble mean, wind and solar in separate figures;
the maps are written into each model's outputs/<model>/figures directory
alongside an updated run_config.json.
Countries dropped from the clustering (zero-coverage or incomplete across
models) stay unpainted. Figures are PNG only; importing this module does not
read inputs or draw figures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import cartopy.crs as ccrs
import cartopy.io.shapereader as shp
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PACKAGE_DIR / "outputs"
MODELS = ("CANESM5", "MPI-ESM1-2-HR", "MRI-ESM2-0", "BCC-CSM2-MR")
TECHS = ("wind", "solar")
TECH_LABEL = {"wind": "Wind", "solar": "Solar"}
CLUSTER_COLORS = ("#1d3b6f", "#b64342", "#42949e", "#9a4d8e",
                  "#d08b32", "#5f7f4f")
LAND_COLOR = "#E9ECEF"
EDGE_COLOR = "#9AA0A6"
OCEAN_COLOR = "white"
LOGGER = logging.getLogger("rq1.map_country_clusters")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def configure_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 8, "axes.linewidth": 0.8,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })


def load_assignments(outputs: Path, model: str) -> pd.DataFrame:
    path = outputs / model / "csv" / "country_cluster_assignments.csv"
    table = pd.read_csv(path)
    if not table["model"].eq(model).all():
        raise ValueError(f"Unexpected model column in {path}")
    return table


def paint_map(assignments: pd.DataFrame, model: str, tech: str,
              output: Path) -> None:
    configure_style()
    subset = assignments[assignments["tech"].eq(tech)]
    label_by_country = dict(zip(subset["country"], subset["cluster"]))
    clusters = sorted(set(label_by_country.values()))
    projection = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(11.0, 5.6), subplot_kw={"projection": projection})
    ax.set_global()
    records = list(shp.Reader(shp.natural_earth(
        resolution="110m", category="cultural", name="admin_0_countries")).records())
    ne_names = {record.attributes.get("NAME") for record in records}
    matched = 0
    for record in records:
        name = record.attributes.get("NAME")
        cluster = label_by_country.get(name)
        color = (CLUSTER_COLORS[(int(cluster) - 1) % len(CLUSTER_COLORS)]
                 if cluster is not None else LAND_COLOR)
        if cluster is not None:
            matched += 1
        ax.add_geometries([record.geometry], crs=projection, facecolor=color,
                          edgecolor=EDGE_COLOR, linewidth=0.3)
    missing = set(label_by_country) - ne_names
    if missing:
        LOGGER.warning("%s / %s: %d clustered countries absent from Natural "
                       "Earth 110m shapes: %s", model, tech, len(missing),
                       ", ".join(sorted(missing)))
    ax.spines["geo"].set_linewidth(0.6)
    counts = subset.groupby("cluster").size()
    handles = [Patch(facecolor=CLUSTER_COLORS[(cluster - 1) % len(CLUSTER_COLORS)],
                     edgecolor=EDGE_COLOR,
                     label=f"Cluster {cluster} (n={int(counts[cluster])})")
               for cluster in clusters]
    handles.append(Patch(facecolor=LAND_COLOR, edgecolor=EDGE_COLOR,
                         label="Excluded"))
    ax.legend(handles=handles, loc="lower left", fontsize=8,
              frameon=True, framealpha=0.9, borderpad=0.5, handlelength=1.4)
    ax.set_title(f"{model} · {TECH_LABEL[tech]} · SSP5-8.5 minus SSP1-2.6 "
                 "unit-loss gap clusters", fontsize=10, pad=6)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.02)
    fig.savefig(output, dpi=600, facecolor="white")
    plt.close(fig)
    LOGGER.info("Painted %d/%d clustered countries -> %s", matched,
                len(label_by_country), output)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    config = {
        "cluster_map": {
            "projection": "PlateCarree",
            "basemap": "Natural Earth 110m admin_0_countries (cartopy cache)",
            "cluster_colors": list(CLUSTER_COLORS),
            "not_clustered_color": LAND_COLOR,
            "source": "country_cluster_assignments.csv per model output set",
            "script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest(),
            "figure_format": "png", "dpi": 600,
        }
    }
    for model in (*MODELS, "ensemble_mean"):
        assignments = load_assignments(args.outputs_dir, model)
        model_config = {"model": model, **config}
        for tech in TECHS:
            paint_map(assignments, model, tech, args.outputs_dir / model /
                      "figures" / f"cluster_map_{model}_{tech}.png")
        (args.outputs_dir / model / "run_config.json").write_text(
            json.dumps(model_config, indent=2, ensure_ascii=False),
            encoding="utf-8")
    LOGGER.info("Saved: %s", args.outputs_dir)


if __name__ == "__main__":
    main()
