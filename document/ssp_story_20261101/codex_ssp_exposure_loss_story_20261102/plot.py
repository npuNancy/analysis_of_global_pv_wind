#!/usr/bin/env python3
"""Plot the three SSP exposure-loss conclusions and write their Markdown story."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from paper_figures.config import MODELS, SSPS, SSP_COLORS, TECHS  # noqa: E402


SOURCE_DIR = HERE / "outputs" / "source_data"
FIGURE_DIR = HERE / "outputs" / "figures"
PANEL_DIR = HERE / "outputs" / "panels"
MARKDOWN_PATH = HERE / "outputs" / "three_conclusions.md"
DPI = 600
MM_TO_INCH = 1 / 25.4
FULL_WIDTH = 183 * MM_TO_INCH

SSP_LABELS = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
TECH_LABELS = {"wind": "Wind", "solar": "Solar PV"}
CLIMATE_COLOR = "#3E6F9E"
DEPLOYMENT_COLOR = "#D18D2D"
PAIRED_COLOR = "#76507B"
POSITIVE_COLOR = "#B85C4A"
NEGATIVE_COLOR = "#477DA5"
OVERLAP_COLOR = "#888888"

EVENT_LABELS = {
    "high_temp": "High temperature",
    "high_wind": "High wind",
    "hot_humid": "Hot–humid",
    "icing": "Icing",
    "low_resource": "Low resource",
    "cold_highwind": "Cold–high wind",
    "freezing_rain": "Freezing rain",
    "high_humidity": "High humidity",
    "rainstorm": "Rainstorm",
    "overlap_correction": "Overlap correction",
    "all": "Union exposure",
}
EVENT_ORDER = {
    "wind": [
        "high_temp",
        "hot_humid",
        "icing",
        "low_resource",
        "high_wind",
        "overlap_correction",
        "all",
    ],
    "solar": [
        "high_humidity",
        "icing",
        "freezing_rain",
        "low_resource",
        "cold_highwind",
        "rainstorm",
        "overlap_correction",
        "all",
    ],
}


def set_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7.5,
            "axes.linewidth": 0.7,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "grid.color": "#D8D8D8",
            "grid.linewidth": 0.45,
            "grid.alpha": 0.75,
            "lines.linewidth": 1.3,
            "savefig.dpi": DPI,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
            "mathtext.default": "regular",
        }
    )


def read_inputs() -> dict[str, pd.DataFrame]:
    names = (
        "suitable_levels_models",
        "suitable_changes_models",
        "suitable_changes_summary",
        "suitable_event_changes_models",
        "suitable_event_changes_summary",
        "domain_exposure_contrasts_models",
        "domain_exposure_contrasts_summary",
        "station_decomposition_models",
        "station_decomposition_summary",
    )
    return {name: pd.read_csv(SOURCE_DIR / f"{name}.csv") for name in names}


def validate_inputs(data: dict[str, pd.DataFrame]) -> None:
    levels = data["suitable_levels_models"]
    expected_rows = len(TECHS) * len(SSPS) * len(MODELS) * 3
    if len(levels) != expected_rows:
        raise ValueError(f"Expected {expected_rows} suitable-level rows, found {len(levels)}")
    key = ["tech", "model", "climate_ssp", "window_start"]
    if levels.duplicated(key).any() or levels[key].isna().any().any():
        raise ValueError("Suitable-level keys are duplicated or incomplete")
    if set(levels["window_start"]) != {2030, 2040, 2050}:
        raise ValueError("Suitable-level data must contain the 2030s, 2040s and 2050s")

    event_models = data["suitable_event_changes_models"]
    closure_errors: list[float] = []
    for (_, _, _), group in event_models.groupby(["tech", "climate_ssp", "model"]):
        union = group.loc[group["event"].eq("all"), "change_2050s_minus_2030s_days"]
        components = group.loc[~group["event"].eq("all"), "change_2050s_minus_2030s_days"]
        if len(union) != 1:
            raise ValueError("Each event group must contain one union-exposure row")
        closure_errors.append(abs(float(components.sum() - union.iloc[0])))
    if max(closure_errors, default=0.0) > 1e-10:
        raise ValueError("Event components do not close to union exposure")

    station = data["station_decomposition_models"]
    for prefix in ("R", "exposure_days", "cf_event", "r_event", "effective_net_loss_fraction"):
        error = (
            station[f"{prefix}_climate_contribution"]
            + station[f"{prefix}_deployment_contribution"]
            - station[f"{prefix}_paired_difference"]
        ).abs().max()
        if error > 1e-10:
            raise ValueError(f"Station decomposition does not close for {prefix}: {error}")


def save_png(fig: mpl.figure.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}".replace("-", "−")


def add_panel_label(ax: mpl.axes.Axes, label: str, x: float = -0.13) -> None:
    ax.text(
        x,
        1.045,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        color="#111111",
        clip_on=False,
    )


def trajectory_change(
    changes_summary: pd.DataFrame, tech: str, metric: str, ssp: str = "ssp585"
) -> tuple[float, int]:
    row = changes_summary.loc[
        changes_summary["tech"].eq(tech)
        & changes_summary["climate_ssp"].eq(ssp)
        & changes_summary["metric"].eq(metric)
    ]
    if len(row) != 1:
        raise ValueError(f"Missing trajectory summary for {tech}, {ssp}, {metric}")
    return float(row.iloc[0]["mean"]), int(row.iloc[0]["support_mean_direction"])


def draw_trajectory_panel(
    ax: mpl.axes.Axes,
    levels: pd.DataFrame,
    changes_summary: pd.DataFrame,
    tech: str,
    metric: str,
    panel_label: str,
) -> None:
    subset = levels.loc[levels["tech"].eq(tech)].copy()
    x_values = np.arange(3, dtype=float)
    windows = (2030, 2040, 2050)
    ssp_offsets = dict(zip(SSPS, (-0.055, 0.0, 0.055)))
    model_offsets = dict(zip(MODELS, np.linspace(-0.018, 0.018, len(MODELS))))

    for ssp in SSPS:
        color = SSP_COLORS[ssp]
        ssp_data = subset.loc[subset["climate_ssp"].eq(ssp)]
        grouped = ssp_data.groupby("window_start")[metric]
        means = grouped.mean().reindex(windows).to_numpy()
        minima = grouped.min().reindex(windows).to_numpy()
        maxima = grouped.max().reindex(windows).to_numpy()
        ax.fill_between(x_values, minima, maxima, color=color, alpha=0.10, linewidth=0)
        ax.plot(
            x_values,
            means,
            color=color,
            marker="o",
            markersize=3.3,
            markeredgewidth=0.5,
            markeredgecolor="white",
            zorder=3,
        )
        for model in MODELS:
            model_values = (
                ssp_data.loc[ssp_data["model"].eq(model)]
                .set_index("window_start")[metric]
                .reindex(windows)
                .to_numpy()
            )
            ax.scatter(
                x_values + ssp_offsets[ssp] + model_offsets[model],
                model_values,
                s=8,
                facecolor=color,
                edgecolor="white",
                linewidth=0.3,
                alpha=0.68,
                zorder=4,
            )

    metric_summary = {
        "exposure_days": ("exposure_days_change", "days yr$^{-1}$"),
        "net_loss_per_mw": ("net_loss_per_mw_change", "MWh MW$^{-1}$ yr$^{-1}$"),
    }
    change_metric, unit = metric_summary[metric]
    delta, support = trajectory_change(changes_summary, tech, change_metric)
    ax.text(
        0.035,
        0.055,
        f"SSP5-8.5: Δ = {signed(delta)} {unit}\n({support}/4 models)",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=6.8,
        color=SSP_COLORS["ssp585"],
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#D0D0D0", "alpha": 0.88},
    )
    ax.set_xticks(x_values, ("2030s", "2040s", "2050s"))
    ax.set_xlim(-0.25, 2.25)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    if metric == "exposure_days":
        ax.set_ylabel("Exposure (days yr$^{-1}$)")
        metric_title = "exposure"
    else:
        ax.set_ylabel("Net loss (MWh MW$^{-1}$ yr$^{-1}$)")
        metric_title = "net loss"
    ax.set_title(f"{TECH_LABELS[tech]} {metric_title}", loc="left", pad=5)
    add_panel_label(ax, panel_label)


def plot_figure_1(data: dict[str, pd.DataFrame]) -> None:
    levels = data["suitable_levels_models"]
    changes_summary = data["suitable_changes_summary"]
    specs = (
        ("wind", "exposure_days", "a"),
        ("wind", "net_loss_per_mw", "b"),
        ("solar", "exposure_days", "c"),
        ("solar", "net_loss_per_mw", "d"),
    )
    fig, axes = plt.subplots(2, 2, figsize=(FULL_WIDTH, 132 * MM_TO_INCH), constrained_layout=True)
    for ax, (tech, metric, label) in zip(axes.flat, specs):
        draw_trajectory_panel(ax, levels, changes_summary, tech, metric, label)
    handles = [
        Line2D([0], [0], color=SSP_COLORS[ssp], marker="o", markersize=3.5, label=SSP_LABELS[ssp])
        for ssp in SSPS
    ]
    fig.legend(handles=handles, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.025))
    save_png(fig, FIGURE_DIR / "figure_1_ssp_trajectories.png")

    for tech, metric, label in specs:
        panel_fig, panel_ax = plt.subplots(figsize=(88 * MM_TO_INCH, 67 * MM_TO_INCH), constrained_layout=True)
        draw_trajectory_panel(panel_ax, levels, changes_summary, tech, metric, label)
        panel_ax.legend(
            handles=handles,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.945),
            ncol=3,
            frameon=False,
            fontsize=6.0,
        )
        save_png(panel_fig, PANEL_DIR / f"figure_1{label}.png")


def event_intensity_change(
    changes_summary: pd.DataFrame, tech: str
) -> tuple[float, int]:
    row = changes_summary.loc[
        changes_summary["tech"].eq(tech)
        & changes_summary["climate_ssp"].eq("ssp585")
        & changes_summary["metric"].eq("effective_net_loss_fraction_change_pct")
    ]
    if len(row) != 1:
        raise ValueError(f"Missing SSP585 intensity summary for {tech}")
    return float(row.iloc[0]["mean"]), int(row.iloc[0]["support_mean_direction"])


def draw_event_panel(
    ax: mpl.axes.Axes,
    event_models: pd.DataFrame,
    changes_summary: pd.DataFrame,
    tech: str,
    panel_label: str,
) -> None:
    subset = event_models.loc[
        event_models["tech"].eq(tech) & event_models["climate_ssp"].eq("ssp585")
    ]
    order = EVENT_ORDER[tech]
    y_positions = np.arange(len(order))[::-1]
    jitter = dict(zip(MODELS, np.linspace(-0.13, 0.13, len(MODELS))))

    for y, event in zip(y_positions, order):
        event_rows = subset.loc[subset["event"].eq(event)].set_index("model")
        values = event_rows.reindex(MODELS)["change_2050s_minus_2030s_days"].to_numpy()
        mean = float(np.mean(values))
        if event == "all":
            ax.errorbar(
                mean,
                y,
                xerr=np.array([[mean - np.min(values)], [np.max(values) - mean]]),
                fmt="D",
                markersize=4.3,
                color="#111111",
                ecolor="#111111",
                elinewidth=0.9,
                capsize=2.2,
                zorder=4,
            )
        else:
            color = OVERLAP_COLOR if event == "overlap_correction" else (POSITIVE_COLOR if mean >= 0 else NEGATIVE_COLOR)
            bars = ax.barh(y, mean, height=0.55, color=color, edgecolor="none", alpha=0.88, zorder=2)
            if event == "overlap_correction":
                bars[0].set_hatch("////")
                bars[0].set_edgecolor("white")
                bars[0].set_linewidth(0.4)
        for model, value in zip(MODELS, values):
            ax.scatter(
                value,
                y + jitter[model],
                s=9,
                facecolor="white",
                edgecolor="#202020",
                linewidth=0.55,
                zorder=5,
            )

    union_y = y_positions[-1]
    ax.axhline(union_y + 0.52, color="#BEBEBE", linewidth=0.65)
    ax.axvline(0, color="#555555", linewidth=0.7)
    ax.set_yticks(y_positions, [EVENT_LABELS[event] for event in order])
    ax.set_ylim(-0.65, len(order) - 0.35)
    ax.grid(axis="x")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Exposure change (days yr$^{-1}$)")
    intensity, support = event_intensity_change(changes_summary, tech)
    ax.set_title(
        f"{TECH_LABELS[tech]}\nEffective loss / exposure-hour\n{signed(intensity)}% ({support}/4 models)",
        loc="left",
        pad=6,
        fontsize=8,
        linespacing=1.2,
    )
    ax.margins(x=0.12)
    add_panel_label(ax, panel_label, x=-0.28 if tech == "wind" else -0.31)


def plot_figure_2(data: dict[str, pd.DataFrame]) -> None:
    event_models = data["suitable_event_changes_models"]
    changes_summary = data["suitable_changes_summary"]
    specs = (("wind", "a"), ("solar", "b"))
    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH, 91 * MM_TO_INCH), constrained_layout=True)
    for ax, (tech, label) in zip(axes, specs):
        draw_event_panel(ax, event_models, changes_summary, tech, label)
    save_png(fig, FIGURE_DIR / "figure_2_event_substitution.png")

    for tech, label in specs:
        panel_fig, panel_ax = plt.subplots(figsize=(92 * MM_TO_INCH, 89 * MM_TO_INCH), constrained_layout=True)
        draw_event_panel(panel_ax, event_models, changes_summary, tech, label)
        save_png(panel_fig, PANEL_DIR / f"figure_2{label}.png")


def plot_distribution_bars(
    ax: mpl.axes.Axes,
    values_by_category: list[np.ndarray],
    labels: list[str],
    colors: list[str],
    ylabel: str,
    title: str,
    panel_label: str,
) -> None:
    x = np.arange(len(labels), dtype=float)
    means = np.array([np.mean(values) for values in values_by_category])
    minima = np.array([np.min(values) for values in values_by_category])
    maxima = np.array([np.max(values) for values in values_by_category])
    ax.bar(x, means, width=0.62, color=colors, edgecolor="none", alpha=0.90, zorder=2)
    ax.errorbar(
        x,
        means,
        yerr=np.vstack([means - minima, maxima - means]),
        fmt="none",
        ecolor="#222222",
        elinewidth=0.75,
        capsize=2.0,
        zorder=3,
    )
    model_jitter = np.linspace(-0.13, 0.13, len(MODELS))
    for category_index, values in enumerate(values_by_category):
        ax.scatter(
            category_index + model_jitter,
            values,
            s=10,
            facecolor="white",
            edgecolor="#202020",
            linewidth=0.55,
            zorder=4,
        )

    overall_min = min(0.0, float(np.min(minima)))
    overall_max = max(0.0, float(np.max(maxima)))
    span = max(overall_max - overall_min, 1.0)
    ax.set_ylim(overall_min - 0.17 * span, overall_max + 0.23 * span)
    for category_index, mean in enumerate(means):
        offset = 0.045 * span if mean >= 0 else -0.045 * span
        ax.text(
            category_index,
            mean + offset,
            signed(float(mean)),
            ha="center",
            va="bottom" if mean >= 0 else "top",
            fontsize=6.7,
            fontweight="bold",
            color="#222222",
        )

    ax.axhline(0, color="#555555", linewidth=0.7)
    ax.set_xticks(x, labels)
    ax.tick_params(axis="x", labelsize=6.6, length=0)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", pad=5)
    ax.grid(axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    add_panel_label(ax, panel_label)


def domain_values(domain_models: pd.DataFrame, domain: str) -> np.ndarray:
    rows = domain_models.loc[
        domain_models["tech"].eq("wind") & domain_models["domain"].eq(domain)
    ].set_index("model")
    values = rows.reindex(MODELS)["ssp585_minus_ssp126_days"].to_numpy()
    if np.isnan(values).any():
        raise ValueError(f"Incomplete wind domain values for {domain}")
    return values


def station_values(station_models: pd.DataFrame, metric: str) -> np.ndarray:
    rows = station_models.loc[station_models["tech"].eq("wind")].set_index("model")
    values = rows.reindex(MODELS)[metric].to_numpy()
    if np.isnan(values).any():
        raise ValueError(f"Incomplete wind station values for {metric}")
    return values


def draw_figure_3_panels(
    axes: list[mpl.axes.Axes] | np.ndarray,
    domain_models: pd.DataFrame,
    station_models: pd.DataFrame,
) -> None:
    domains = [
        "all_land_area_weighted",
        "suitable_grid_equal_weighted",
        "stations_fixed_ssp126",
        "stations_paired_path",
    ]
    domain_labels = ["All\nland", "Suitable\ngrids", "Stations\nfixed", "Stations\npaired"]
    plot_distribution_bars(
        axes[0],
        [domain_values(domain_models, domain) for domain in domains],
        domain_labels,
        [CLIMATE_COLOR, CLIMATE_COLOR, CLIMATE_COLOR, PAIRED_COLOR],
        "SSP5-8.5 − SSP1-2.6\nexposure (days yr$^{-1}$)",
        "Spatial weighting",
        "a",
    )

    decomposition_labels = ["Climate", "Deployment", "Paired\npath"]
    plot_distribution_bars(
        axes[1],
        [
            station_values(station_models, "exposure_days_climate_contribution"),
            station_values(station_models, "exposure_days_deployment_contribution"),
            station_values(station_models, "exposure_days_paired_difference"),
        ],
        decomposition_labels,
        [CLIMATE_COLOR, DEPLOYMENT_COLOR, PAIRED_COLOR],
        "Exposure (days yr$^{-1}$)",
        "Wind exposure",
        "b",
    )
    plot_distribution_bars(
        axes[2],
        [
            station_values(station_models, "R_climate_contribution"),
            station_values(station_models, "R_deployment_contribution"),
            station_values(station_models, "R_paired_difference"),
        ],
        decomposition_labels,
        [CLIMATE_COLOR, DEPLOYMENT_COLOR, PAIRED_COLOR],
        "Net loss (MWh MW$^{-1}$ yr$^{-1}$)",
        "Wind net loss",
        "c",
    )


def plot_figure_3(data: dict[str, pd.DataFrame]) -> None:
    domain_models = data["domain_exposure_contrasts_models"]
    station_models = data["station_decomposition_models"]
    fig, axes = plt.subplots(1, 3, figsize=(FULL_WIDTH, 83 * MM_TO_INCH), constrained_layout=True)
    draw_figure_3_panels(axes, domain_models, station_models)
    legend_handles = [
        Patch(facecolor=CLIMATE_COLOR, label="Climate signal / fixed deployment"),
        Patch(facecolor=DEPLOYMENT_COLOR, label="Deployment contribution"),
        Patch(facecolor=PAIRED_COLOR, label="Paired pathway"),
    ]
    fig.legend(legend_handles, [handle.get_label() for handle in legend_handles], loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.04))
    save_png(fig, FIGURE_DIR / "figure_3_deployment_reversal.png")

    for index, label in enumerate(("a", "b", "c")):
        panel_fig, panel_ax = plt.subplots(figsize=(73 * MM_TO_INCH, 75 * MM_TO_INCH), constrained_layout=True)
        # Draw only the requested panel on a fresh axis to keep each panel independently editable.
        if index == 0:
            domains = [
                "all_land_area_weighted",
                "suitable_grid_equal_weighted",
                "stations_fixed_ssp126",
                "stations_paired_path",
            ]
            plot_distribution_bars(
                panel_ax,
                [domain_values(domain_models, domain) for domain in domains],
                ["All\nland", "Suitable\ngrids", "Stations\nfixed", "Stations\npaired"],
                [CLIMATE_COLOR, CLIMATE_COLOR, CLIMATE_COLOR, PAIRED_COLOR],
                "SSP5-8.5 − SSP1-2.6\nexposure (days yr$^{-1}$)",
                "Spatial weighting",
                "a",
            )
        elif index == 1:
            plot_distribution_bars(
                panel_ax,
                [
                    station_values(station_models, "exposure_days_climate_contribution"),
                    station_values(station_models, "exposure_days_deployment_contribution"),
                    station_values(station_models, "exposure_days_paired_difference"),
                ],
                ["Climate", "Deployment", "Paired\npath"],
                [CLIMATE_COLOR, DEPLOYMENT_COLOR, PAIRED_COLOR],
                "Exposure (days yr$^{-1}$)",
                "Wind exposure",
                "b",
            )
        else:
            plot_distribution_bars(
                panel_ax,
                [
                    station_values(station_models, "R_climate_contribution"),
                    station_values(station_models, "R_deployment_contribution"),
                    station_values(station_models, "R_paired_difference"),
                ],
                ["Climate", "Deployment", "Paired\npath"],
                [CLIMATE_COLOR, DEPLOYMENT_COLOR, PAIRED_COLOR],
                "Net loss (MWh MW$^{-1}$ yr$^{-1}$)",
                "Wind net loss",
                "c",
            )
        save_png(panel_fig, PANEL_DIR / f"figure_3{label}.png")


def summary_row(
    frame: pd.DataFrame, *, tech: str, ssp: str, metric: str
) -> pd.Series:
    rows = frame.loc[
        frame["tech"].eq(tech)
        & frame["climate_ssp"].eq(ssp)
        & frame["metric"].eq(metric)
    ]
    if len(rows) != 1:
        raise ValueError(f"Missing summary row: {tech}, {ssp}, {metric}")
    return rows.iloc[0]


def event_row(frame: pd.DataFrame, *, tech: str, event: str) -> pd.Series:
    rows = frame.loc[
        frame["tech"].eq(tech)
        & frame["climate_ssp"].eq("ssp585")
        & frame["event"].eq(event)
    ]
    if len(rows) != 1:
        raise ValueError(f"Missing SSP585 event row: {tech}, {event}")
    return rows.iloc[0]


def domain_row(frame: pd.DataFrame, *, tech: str, domain: str) -> pd.Series:
    rows = frame.loc[frame["tech"].eq(tech) & frame["domain"].eq(domain)]
    if len(rows) != 1:
        raise ValueError(f"Missing domain row: {tech}, {domain}")
    return rows.iloc[0]


def station_row(frame: pd.DataFrame, *, metric: str) -> pd.Series:
    rows = frame.loc[frame["tech"].eq("wind") & frame["metric"].eq(metric)]
    if len(rows) != 1:
        raise ValueError(f"Missing wind station row: {metric}")
    return rows.iloc[0]


def markdown_value(row: pd.Series, suffix: str = "") -> str:
    return f"{signed(float(row['mean']))}{suffix} ({int(row['support_mean_direction'])}/4)"


def write_markdown(data: dict[str, pd.DataFrame]) -> None:
    changes = data["suitable_changes_summary"]
    events = data["suitable_event_changes_summary"]
    domains = data["domain_exposure_contrasts_summary"]
    station = data["station_decomposition_summary"]

    trajectory_rows: list[str] = []
    for tech in ("wind", "solar"):
        for ssp in SSPS:
            exposure = summary_row(changes, tech=tech, ssp=ssp, metric="exposure_days_change")
            loss = summary_row(changes, tech=tech, ssp=ssp, metric="net_loss_per_mw_change")
            intensity = summary_row(
                changes, tech=tech, ssp=ssp, metric="effective_net_loss_fraction_change_pct"
            )
            trajectory_rows.append(
                "| "
                + " | ".join(
                    [
                        "风电" if tech == "wind" else "光伏",
                        SSP_LABELS[ssp],
                        markdown_value(exposure),
                        markdown_value(loss),
                        markdown_value(intensity, "%"),
                    ]
                )
                + " |"
            )

    wind_components = {
        event: event_row(events, tech="wind", event=event)
        for event in ("all", "high_temp", "hot_humid", "icing", "low_resource")
    }
    solar_components = {
        event: event_row(events, tech="solar", event=event)
        for event in ("all", "high_humidity", "icing", "freezing_rain", "low_resource")
    }
    wind_intensity = summary_row(
        changes, tech="wind", ssp="ssp585", metric="effective_net_loss_fraction_change_pct"
    )
    solar_intensity = summary_row(
        changes, tech="solar", ssp="ssp585", metric="effective_net_loss_fraction_change_pct"
    )

    domain_order = [
        ("all_land_area_weighted", "全陆地面积加权"),
        ("suitable_grid_equal_weighted", "适宜格点等权"),
        ("stations_fixed_ssp126", "场站固定 SSP1-2.6 部署"),
        ("stations_paired_path", "场站配对路径"),
    ]
    domain_table_rows: list[str] = []
    for domain, label in domain_order:
        wind = domain_row(domains, tech="wind", domain=domain)
        solar = domain_row(domains, tech="solar", domain=domain)
        domain_table_rows.append(
            f"| {label} | {markdown_value(wind)} | {markdown_value(solar)} |"
        )

    exposure_paired = station_row(station, metric="exposure_days_paired_difference")
    exposure_climate = station_row(station, metric="exposure_days_climate_contribution")
    exposure_deployment = station_row(station, metric="exposure_days_deployment_contribution")
    loss_paired = station_row(station, metric="R_paired_difference")
    loss_climate = station_row(station, metric="R_climate_contribution")
    loss_deployment = station_row(station, metric="R_deployment_contribution")

    markdown = f"""# 三个 SSP 暴露—损失结论及证据图

## 核心观点

高排放路径改变的不只是极端事件暴露时长，还包括事件组合、事件期发电价值和容量的空间权重。因此，“更多暴露”不能直接等同于“更大损失”；部署变化甚至能让暴露下降与单位装机损失上升同时出现。

## 结论 1：高排放使风、光风险轨迹分叉，暴露与损失只在光伏上同向

![三个 SSP 下风电与光伏的暴露和单位装机净损失轨迹](figures/figure_1_ssp_trajectories.png)

**图 1｜三个 SSP 下适宜格点的暴露与单位装机净损失轨迹。** 实线和实心圆为四模式等权均值，阴影为四模式最小—最大范围，小点为单个气候模式。图内 Δ 为 SSP5-8.5 下 2050s 减 2030s 的四模式均值；括号给出与均值方向一致的模式数。

2050s 相对 2030s 的变化如下：

| 技术 | SSP | 暴露变化（day yr⁻¹） | 单位装机净损失变化（MWh MW⁻¹ yr⁻¹） | 每暴露小时有效净损失比例变化 |
|---|---|---:|---:|---:|
{chr(10).join(trajectory_rows)}

SSP5-8.5 下，风电暴露增加 {markdown_value(summary_row(changes, tech='wind', ssp='ssp585', metric='exposure_days_change'))} day yr⁻¹，但单位装机净损失仅变化 {markdown_value(summary_row(changes, tech='wind', ssp='ssp585', metric='net_loss_per_mw_change'))} MWh MW⁻¹ yr⁻¹；光伏暴露减少 {markdown_value(summary_row(changes, tech='solar', ssp='ssp585', metric='exposure_days_change'))} day yr⁻¹，净损失同步减少 {markdown_value(summary_row(changes, tech='solar', ssp='ssp585', metric='net_loss_per_mw_change'))} MWh MW⁻¹ yr⁻¹。气候强迫扩大的是两种技术的响应差异，而不是统一抬升可再生能源风险。

## 结论 2：事件替换解释了“风电暴露增加、损失不增”

![SSP5-8.5 下风电与光伏的事件暴露组成变化](figures/figure_2_event_substitution.png)

**图 2｜SSP5-8.5 下 2050s 相对 2030s 的事件暴露组成变化。** 横条为四模式等权均值，空心点为单个模式；“Union exposure”菱形及横线分别表示事件并集的均值与模式范围。重叠修正项被显式保留，使各事件分量之和严格闭合到并集暴露。暖色表示正贡献，蓝色表示负贡献；颜色只编码变化方向。

风电并集暴露净增 {markdown_value(wind_components['all'])} day yr⁻¹，主要由高温 {markdown_value(wind_components['high_temp'])} 和高温高湿 {markdown_value(wind_components['hot_humid'])} 推动，同时结冰 {markdown_value(wind_components['icing'])}、低资源 {markdown_value(wind_components['low_resource'])} 抵消部分增量。每暴露小时有效净损失比例下降 {markdown_value(wind_intensity, '%')}；事件时长增加，但新增暴露没有按原强度转化为损失。

光伏并集暴露变化为 {markdown_value(solar_components['all'])} day yr⁻¹，主要来自高湿 {markdown_value(solar_components['high_humidity'])}、结冰 {markdown_value(solar_components['icing'])}、冻雨 {markdown_value(solar_components['freezing_rain'])} 和低资源 {markdown_value(solar_components['low_resource'])} 的共同下降；每暴露小时有效净损失比例只变化 {markdown_value(solar_intensity, '%')}。因此，光伏损失下降主要随暴露收缩，风电则由事件组合和事件期强度变化控制。

## 结论 3：部署路径反转风电气候信号，并把容量移向“更少但更伤”的事件暴露

![空间口径和部署路径对风电暴露与损失信号的反转](figures/figure_3_deployment_reversal.png)

**图 3｜空间权重与部署路径改变 2050s 风电风险信号。** 柱为四模式等权均值，误差线为模式最小—最大范围，空心点为单个模式。a，SSP5-8.5 减 SSP1-2.6 的暴露差在全陆地、适宜格点和固定部署场站上为正，采用各情景配对部署后转为负。b–c，对称分解将场站配对路径差分拆为气候贡献与部署贡献，两者严格相加为配对路径差。

| 空间口径 | 风电暴露差（day yr⁻¹） | 光伏暴露差（day yr⁻¹） |
|---|---:|---:|
{chr(10).join(domain_table_rows)}

配对部署路径下，风电暴露变化为 {markdown_value(exposure_paired)} day yr⁻¹，而单位装机净损失增加 {markdown_value(loss_paired)} MWh MW⁻¹ yr⁻¹。对称分解表明，气候项贡献暴露 {markdown_value(exposure_climate)} day yr⁻¹、损失 {markdown_value(loss_climate)} MWh MW⁻¹ yr⁻¹；部署项贡献暴露 {markdown_value(exposure_deployment)} day yr⁻¹、损失 {markdown_value(loss_deployment)} MWh MW⁻¹ yr⁻¹。部署变化压低事件暴露时长，却把容量权重移向单位时间损失更高的事件环境，最终反转了只看气候暴露得到的风险排序。

## 数据与复现

- 三张完整图均为 PNG、600 dpi；各子图另存于 [`panels/`](panels/)。
- 图 1 数据：[`suitable_levels_models.csv`](source_data/suitable_levels_models.csv) 与 [`suitable_changes_summary.csv`](source_data/suitable_changes_summary.csv)。
- 图 2 数据：[`suitable_event_changes_models.csv`](source_data/suitable_event_changes_models.csv) 与 [`suitable_event_changes_summary.csv`](source_data/suitable_event_changes_summary.csv)。
- 图 3 数据：[`domain_exposure_contrasts_models.csv`](source_data/domain_exposure_contrasts_models.csv) 与 [`station_decomposition_models.csv`](source_data/station_decomposition_models.csv)。
- 绘图与 Markdown 生成脚本：[`../plot.py`](../plot.py)；输入一致性检查：[`validation.json`](validation.json)。
"""
    MARKDOWN_PATH.write_text(markdown, encoding="utf-8")


def main() -> None:
    set_style()
    data = read_inputs()
    validate_inputs(data)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    plot_figure_1(data)
    plot_figure_2(data)
    plot_figure_3(data)
    write_markdown(data)
    print(f"Wrote {MARKDOWN_PATH}")
    print(f"Wrote 3 complete figures to {FIGURE_DIR}")
    print(f"Wrote 9 individual panels to {PANEL_DIR}")


if __name__ == "__main__":
    main()
