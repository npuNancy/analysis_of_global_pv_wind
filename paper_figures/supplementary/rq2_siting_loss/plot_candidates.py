"""Visualize fixed-fleet loss contributions and LCOE-2025 scenario ranges for RQ2."""
import hashlib
import json
from itertools import permutations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import MODELS, SSPS, TECHS

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "tmp/RQ1_20261116_candidates/source_data"
BUNDLE = ROOT / "tmp/RQ1_20261119_candidates"
DATA = BUNDLE / "source_data/rq2_candidates"
IMAGES = BUNDLE / "images/rq2_candidates"
LCOE_INDEX = Path("/work/home/acxujo26gv/lcoe_gem2025_climate_storage/runtime/authoritative_index.json")
LAYOUTS = ("ssp126", "ssp245", "ssp560")
LABELS = {"wind": "Wind", "solar": "Solar PV"}
UNIT = r"MWh MW$^{-1}$ yr$^{-1}$"


def fixed_loss_contributions():
    """Attribute an exact model-level product difference using all six factor orders."""
    fixed = pd.read_csv(ARCHIVE / "fixed2025_decadal_models.csv")
    fixed = fixed.loc[fixed.time.eq(2050) & fixed.climate_ssp.isin(["ssp126", "ssp585"])]
    assert len(fixed) == len(MODELS) * len(TECHS) * 2
    records = []
    for (tech, model), group in fixed.groupby(["tech", "model"]):
        ends = group.set_index("climate_ssp").loc[["ssp126", "ssp585"]]
        assert ends["capacity_mw"].nunique() == ends["n_cells"].nunique() == 1
        hours = ends["loss_valid_days"].to_numpy() * 24
        rate = ends["intensity_pct"].to_numpy() / 100
        loss = ends["net_loss_per_mw"].to_numpy()
        normal_cf = loss / (hours * rate)
        assert ((hours > 0) & (normal_cf > 0) & (normal_cf <= 1) & (rate > 0)).all()
        low, high = np.column_stack([hours, normal_cf, rate])
        contributions = np.zeros(3)
        for order in permutations(range(3)):
            current = low.copy()
            for factor in order:
                previous = np.prod(current)
                current[factor] = high[factor]
                contributions[factor] += np.prod(current) - previous
        contributions /= 6
        change = float(loss[1] - loss[0])
        np.testing.assert_allclose(contributions.sum(), change, atol=1e-10)
        records.append(dict(
            tech=tech, model=model, valid_hours_126=hours[0], valid_hours_585=hours[1],
            event_normal_cf_126=normal_cf[0], event_normal_cf_585=normal_cf[1],
            intensity_126=rate[0], intensity_585=rate[1],
            loss_126=loss[0], loss_585=loss[1],
            exposure_contribution=contributions[0], normal_cf_contribution=contributions[1],
            intensity_contribution=contributions[2], net_change=change,
        ))
    return pd.DataFrame(records)


def lcoe_scenario_ranges():
    index = json.loads(LCOE_INDEX.read_text())
    assert index["status"] == "COMPLETED"
    summary = index["summaries"]["global_annual_models.csv"]
    path = Path(summary["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == summary["sha256"]
    annual = pd.read_csv(path)
    sample = annual.loc[annual.phase.eq("future") & annual.year.between(2050, 2059) & annual.tech.isin(TECHS)]
    keys = ["tech", "model", "station_ssp", "climate_ssp"]
    assert len(sample) == len(TECHS) * len(MODELS) * len(LAYOUTS) * len(SSPS) * 10
    assert not sample.duplicated(keys + ["year"]).any()
    assert sample.groupby(keys).size().eq(10).all()
    matrix = sample.groupby(keys, as_index=False)["unit_loss_mwh_per_mw"].mean()
    historical_check = pd.read_csv(ARCHIVE / "future_layout_matrix_models.csv").sort_values(keys)
    np.testing.assert_allclose(matrix.unit_loss_mwh_per_mw, historical_check.unit_loss_mwh_per_mw, atol=1e-10)
    records = []
    for (tech, model), group in matrix.groupby(["tech", "model"]):
        table = group.pivot(index="station_ssp", columns="climate_ssp", values="unit_loss_mwh_per_mw")
        table = table.loc[list(LAYOUTS), list(SSPS)]
        layout = table.max(axis=0) - table.min(axis=0)
        climate = table.max(axis=1) - table.min(axis=1)
        records.append(dict(
            tech=tech, model=model, layout_min=layout.min(), layout_max=layout.max(),
            climate_min=climate.min(), climate_max=climate.max(),
            lower_ratio=layout.min() / climate.max(), upper_ratio=layout.max() / climate.min(),
        ))
    return matrix, pd.DataFrame(records)


def draw_contributions(ax, tech, data, show_labels):
    fields = ["exposure_contribution", "normal_cf_contribution", "intensity_contribution", "net_change"]
    labels = ["Valid event duration", "Normal CF in events", "Event-period loss rate", "Net change"]
    group = data.loc[data.tech.eq(tech)].set_index("model").loc[list(MODELS), fields]
    y = np.arange(len(fields))
    ax.axvline(0, color=".45", lw=.65, zorder=1)
    ax.barh(y, group.mean().to_numpy(), height=.56, color=["#487A96"]*3+["#2e3034"], zorder=2)
    for i, row in enumerate(group.to_numpy()):
        ax.scatter(row, y + (i-1.5)*.11, color="white", edgecolors="#263945", s=18, linewidths=.75, zorder=3)
    ax.set_yticks(y, labels if show_labels else [""]*len(labels))
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(len(fields)-.5, -.5)
    assert np.abs(data[fields].to_numpy()).max() < 16
    ax.set_xlim(-16, 16)
    ax.set_xticks([-16, -8, 0, 8, 16])
    ax.set_xlabel(f"SSP585 − SSP126 ({UNIT})")


def draw_ranges(ax, tech, data, show_labels):
    group = data.loc[data.tech.eq(tech)].set_index("model").loc[list(MODELS)]
    y = np.arange(len(group))
    for kind, offset, color, marker in [("layout", -.14, "#B27736", "o"), ("climate", .14, "#487A96", "s")]:
        low = group[kind+"_min"]
        high = group[kind+"_max"]
        positions = y + offset
        ax.hlines(positions, low, high, color=color, lw=1.65, zorder=2)
        for values in (low, high):
            ax.scatter(values, positions, marker=marker, color=color, s=13, linewidths=0, zorder=3)
    ax.set_yticks(y, list(MODELS) if show_labels else [""]*len(y))
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(len(y)-.5, -.5)
    ax.set_xlim(0, 45 if tech == "wind" else 8)
    ax.set_xlabel(f"Scenario spread ({UNIT})")


def export_group(name, draw, data, title, handles):
    products = []
    for techs, suffix in [(TECHS, ""), (TECHS[:1], "_a"), (TECHS[1:], "_b")]:
        full = len(techs) == 2
        fig, axes = plt.subplots(1, len(techs), figsize=((200 if full else 115)/25.4, 90/25.4),
                                 squeeze=False)
        fig.subplots_adjust(left=.21 if full else .34, right=.97, bottom=.29,
                            top=.77, wspace=.21)
        fig.suptitle(title, y=.96, fontsize=9)
        for pos, (ax, tech) in enumerate(zip(axes[0], techs)):
            draw(ax, tech, data, show_labels=(pos == 0))
            ax.set_title(("a" if tech == "wind" else "b") + "  " + LABELS[tech], loc="left",
                         fontsize=8, fontweight="bold")
            ax.grid(axis="x", color=".9", linewidth=.5, zorder=0)
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.53 if full else .55, .05),
                   ncol=2, fontsize=7)
        products.append(export_panel_png(fig, IMAGES/f"{name}{suffix}.png"))
    return products


def main():
    configure()
    DATA.mkdir(parents=True, exist_ok=True)
    contributions = fixed_loss_contributions()
    matrix, ranges = lcoe_scenario_ranges()
    contributions.to_csv(DATA/"fixed2025_loss_contributions.csv", index=False)
    matrix.to_csv(DATA/"lcoe2025_crossed_loss_models.csv", index=False)
    ranges.to_csv(DATA/"lcoe2025_scenario_ranges.csv", index=False)
    products = export_group(
        "fixed2025_loss_contributions", draw_contributions, contributions,
        "Fixed 2025 capacity | Loss contributions in the 2050s",
        [Patch(facecolor="#487A96", label="Four-model mean"),
         Line2D([], [], marker="o", linestyle="none", mfc="white", mec="#263945", label="Individual model")],
    )
    products += export_group(
        "lcoe2025_scenario_ranges", draw_ranges, ranges,
        "LCOE-2025 | Layout and climate spreads in the 2050s",
        [Line2D([], [], color="#B27736", marker="o", label="Layout spread"),
         Line2D([], [], color="#487A96", marker="s", label="Climate spread")],
    )
    (DATA/"figure_validation.json").write_text(json.dumps({"products": products}, indent=2)+"\n")
    print(contributions.round(4).to_string(index=False))
    print(ranges.round(4).to_string(index=False))
    print(contributions.select_dtypes("number").join(contributions.tech).groupby("tech").mean().round(4))


if __name__ == "__main__":
    main()
