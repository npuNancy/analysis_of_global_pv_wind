"""Render capacity-weighted loss distributions for the dispatch-2025 cohorts."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import ROOT, SNAPSHOTS, SSP_COLORS, SSPS, TECHS
from paper_figures.supplementary.rq2_siting_loss.prepare_dispatch_cohorts import DATA, PREFIX

IMAGES = ROOT / "tmp/RQ1_20261123_candidates/images/rq2_candidates"
STOCK_COLOR = "#6e747b"
COLORS = {"stock": STOCK_COLOR, **SSP_COLORS}
OFFSETS = dict(zip(COLORS, (-.33, -.11, .11, .33), strict=True))
LABELS = {"wind": ("Wind", "MW"), "solar": ("Solar PV", r"MW_{p}")}


def violin(ax, values, weights, x, color):
    assert weights.size == values.size and np.isfinite(values).all() and (weights > 0).all()
    order = np.argsort(values)
    cumulative_weight = np.cumsum(weights[order])
    indices = np.searchsorted(cumulative_weight, cumulative_weight[-1] * np.array([.005, .995]))
    lower, upper = values[order[indices]]
    y = np.linspace(lower, upper, 256)
    density = gaussian_kde(values, weights=weights)(y)
    half_width = .089 * density / density.max()
    ax.fill_betweenx(y, x-half_width, x+half_width, facecolor=color, alpha=.33, linewidth=0)
    ax.plot(x-half_width, y, color=color, linewidth=.65)
    ax.plot(x+half_width, y, color=color, linewidth=.65)
    mean = np.average(values, weights=weights)
    ax.scatter(x, mean, s=13, color=color, edgecolor="white", linewidth=.55, zorder=4)
    return mean


def draw_cohorts(ax, values, historical_mean_expected, group):
    historical_mean = violin(ax, values["stock_2025_values"], values["stock_2025_weights"], 0, STOCK_COLOR)
    np.testing.assert_allclose(historical_mean, historical_mean_expected)
    for tick, year in enumerate(SNAPSHOTS, 1):
        for cohort, color in COLORS.items():
            x = tick + OFFSETS[cohort]
            key = f"{cohort}_{year}"
            y, weights = values[f"{key}_values"], values[f"{key}_weights"]
            if not weights.size:
                assert group.loc[(year, cohort), "added_nominal_mw"] == 0
                ax.text(x, .045, "No\nadditions", transform=ax.get_xaxis_transform(),
                        color=".40", ha="center", va="bottom", fontsize=5.3)
                continue
            mean = violin(ax, y, weights, x, color)
            if cohort == "stock":
                np.testing.assert_allclose(mean, group.loc[(year, slice(None)), "stock_unit_loss"].mean())
                continue
            row = group.loc[(year, cohort)]
            np.testing.assert_allclose([mean, weights.sum()], [row.added_unit_loss, row.added_capacity_mw])
            matched_x = x + .080
            ax.plot([x, matched_x], [mean, row.stock_unit_loss], color=".40", lw=.60, zorder=3)
            ax.scatter(matched_x, row.stock_unit_loss, s=12, facecolors="white",
                       edgecolors=STOCK_COLOR, linewidth=.83, zorder=4)


def render(data, historical, summary):
    fig, axes = plt.subplots(1, 2, figsize=(190/25.4, 91/25.4))
    fig.subplots_adjust(left=.102, right=.982, bottom=.284, top=.887, wspace=.33)
    for i, (ax, tech) in enumerate(zip(axes, TECHS, strict=True)):
        group = summary.loc[tech]
        tech_label, capacity_unit = LABELS[tech]
        ax.set_title(tech_label, loc="left", fontsize=9, pad=7)
        ax.text(-.20, 1.045, "ab"[i], transform=ax.transAxes, weight="bold", fontsize=9)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color=".9", lw=.5)
        ax.axhline(0, color=".63", lw=.55)
        ax.set_xticks(range(4), ["2020s\n(2025 only)", "2030s", "2040s", "2050s"])
        ax.set_xlim(-.48, 3.5)
        ax.set_ylabel("Unit-capacity net loss\n" + rf"(MWh $\mathrm{{{capacity_unit}}}^{{-1}}$ yr$^{{-1}}$)")
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        draw_cohorts(ax, data[tech], historical.loc[tech, "stock_unit_loss"], group)
        lower, upper = ax.get_ylim()
        ticks = ax.get_yticks()
        ax.set_yticks(ticks[(lower <= ticks) & (ticks <= upper)])
    handles = [Patch(facecolor=color, alpha=.48, label=label)
               for color, label in zip(COLORS.values(), ("2025 capacity", *(s.upper() + " additions" for s in SSPS)))]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.52, .112), ncol=4,
               fontsize=7, handlelength=1.2, columnspacing=1.8)
    keys = [Line2D([], [], marker="o", color=".28", lw=0, markersize=3.4, label="Cohort mean"),
            Line2D([], [], marker="o", color=STOCK_COLOR, markerfacecolor="white",
                   lw=0, markersize=3.1, label="2025 capacity mean under the same SSP")]
    fig.legend(handles=keys, loc="lower center", bbox_to_anchor=(.52, .053), ncol=2,
               fontsize=6.5, handlelength=1.15, columnspacing=1.65)
    fig.text(.52, .028, "Violin extent: weighted 0.5th to 99.5th percentiles",
             ha="center", va="center", color=".37", fontsize=6.1)
    return export_panel_png(fig, IMAGES / f"{PREFIX}.png")


def main():
    configure()
    summary = pd.read_csv(DATA / f"{PREFIX}_summary.csv").set_index(["tech", "decade", "ssp"]).sort_index()
    history = pd.read_csv(DATA / f"{PREFIX}_historical.csv").set_index("tech")
    data = {}
    for tech in TECHS:
        with np.load(DATA / f"{PREFIX}_violin_{tech}.npz", allow_pickle=False) as archive:
            data[tech] = {key: archive[key] for key in archive.files}
    product = render(data, history, summary)
    metadata = {
        "file": product,
        "panels": list(TECHS),
        "density": "Capacity-weighted Gaussian KDE of grid-level annual net losses per MW or MWp, "
                   "shown between the 0.5th and 99.5th weighted percentiles. Each violin scales to "
                   "the same maximum width. Means use the full data.",
        "aggregation": "Future values average ten years then four models per grid. "
                       "Gray future violins additionally average three SSPs per grid.",
        "markers": "Filled: capacity-weighted cohort mean. Hollow: mean for 2025 capacity in the "
                   "matching climate SSP.",
    }
    (DATA / f"{PREFIX}_figure_validation.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(product, indent=2))


if __name__ == "__main__":
    main()
