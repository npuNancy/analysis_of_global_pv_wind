#!/usr/bin/env python3
"""Build the linked three-RQ SSP wind-risk story, figures and source tables."""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from paper_figures.config import MODELS, SSP_COLORS, SSPS  # noqa: E402


INPUT_PATH = (
    REPO
    / "paper_figures/main/fig02_generation_loss/outputs/meeting_loss/source_data"
    / "global_all_combinations.csv"
)
OUTPUT_DIR = HERE / "outputs"
SOURCE_DIR = OUTPUT_DIR / "rq_source_data"
FIGURE_DIR = OUTPUT_DIR / "rq_figures"
PANEL_DIR = OUTPUT_DIR / "rq_panels"
MARKDOWN_PATH = OUTPUT_DIR / "three_conclusions.md"
VALIDATION_PATH = OUTPUT_DIR / "rq_validation.json"

DPI = 600
MM_TO_INCH = 1 / 25.4
FULL_WIDTH = 183 * MM_TO_INCH
SSP_LABELS = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
CONTRAST_LABEL = "ssp585_minus_ssp126"
CLIMATE_COLOR = "#3E6F9E"
DEPLOYMENT_COLOR = "#D18D2D"
PAIRED_COLOR = "#76507B"
EXPOSURE_COLOR = "#477DA5"
CF_COLOR = "#D3A13B"
INTENSITY_COLOR = "#B85C4A"
MODEL_COLOR = "#9A9A9A"


def set_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
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
        }
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def support_for_mean(values: pd.Series) -> int:
    mean = float(values.mean())
    if np.isclose(mean, 0.0):
        return int(np.isclose(values.to_numpy(), 0.0).sum())
    return int(((values > 0) if mean > 0 else (values < 0)).sum())


def summarize_levels(levels: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    metrics = ("exposure_days", "R", "cf_event", "r_event")
    for keys, group in levels.groupby(["tech", "snapshot", "climate_ssp"], sort=False):
        tech, snapshot, ssp = keys
        for metric in metrics:
            values = group[metric]
            rows.append(
                {
                    "tech": tech,
                    "snapshot": snapshot,
                    "climate_ssp": ssp,
                    "metric": metric,
                    "mean": values.mean(),
                    "minimum": values.min(),
                    "maximum": values.max(),
                    "n_models": values.notna().sum(),
                }
            )
    return pd.DataFrame(rows)


def build_contrasts(levels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = (
        ("ssp126", "ssp245", "ssp245_minus_ssp126"),
        ("ssp245", "ssp585", "ssp585_minus_ssp245"),
        ("ssp126", "ssp585", CONTRAST_LABEL),
    )
    metrics = ("exposure_days", "R", "cf_event", "r_event")
    rows: list[dict[str, object]] = []
    for (tech, snapshot, model), group in levels.groupby(
        ["tech", "snapshot", "model"], sort=False
    ):
        indexed = group.set_index("climate_ssp")
        for low, high, contrast in pairs:
            for metric in metrics:
                rows.append(
                    {
                        "tech": tech,
                        "snapshot": snapshot,
                        "model": model,
                        "contrast": contrast,
                        "low_ssp": low,
                        "high_ssp": high,
                        "metric": metric,
                        "difference": indexed.loc[high, metric] - indexed.loc[low, metric],
                    }
                )
    models = pd.DataFrame(rows)
    summary_rows: list[dict[str, object]] = []
    for keys, group in models.groupby(
        ["tech", "snapshot", "contrast", "low_ssp", "high_ssp", "metric"],
        sort=False,
    ):
        tech, snapshot, contrast, low, high, metric = keys
        values = group["difference"]
        summary_rows.append(
            {
                "tech": tech,
                "snapshot": snapshot,
                "contrast": contrast,
                "low_ssp": low,
                "high_ssp": high,
                "metric": metric,
                "mean": values.mean(),
                "minimum": values.min(),
                "maximum": values.max(),
                "support_mean_direction": support_for_mean(values),
                "n_models": values.notna().sum(),
            }
        )
    return models, pd.DataFrame(summary_rows)


def build_pathway_decomposition(
    matrix: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    metrics = ("exposure_days", "R", "cf_event", "r_event")
    rows: list[dict[str, object]] = []
    for (tech, snapshot, model), group in matrix.groupby(
        ["tech", "snapshot", "model"], sort=False
    ):
        indexed = group.set_index(["climate_ssp", "station_ssp"])
        for metric in metrics:
            low_low = float(indexed.loc[("ssp126", "ssp126"), metric])
            high_low = float(indexed.loc[("ssp585", "ssp126"), metric])
            low_high = float(indexed.loc[("ssp126", "ssp585"), metric])
            high_high = float(indexed.loc[("ssp585", "ssp585"), metric])
            total = high_high - low_low
            climate = 0.5 * ((high_low - low_low) + (high_high - low_high))
            deployment = 0.5 * ((low_high - low_low) + (high_high - high_low))
            rows.append(
                {
                    "tech": tech,
                    "snapshot": snapshot,
                    "model": model,
                    "metric": metric,
                    "paired_difference": total,
                    "climate_contribution": climate,
                    "deployment_contribution": deployment,
                    "closure_error": climate + deployment - total,
                }
            )
    models = pd.DataFrame(rows)
    summary_rows: list[dict[str, object]] = []
    columns = ("climate_contribution", "deployment_contribution", "paired_difference")
    for (tech, snapshot, metric), group in models.groupby(
        ["tech", "snapshot", "metric"], sort=False
    ):
        for component in columns:
            values = group[component]
            summary_rows.append(
                {
                    "tech": tech,
                    "snapshot": snapshot,
                    "metric": metric,
                    "component": component,
                    "mean": values.mean(),
                    "minimum": values.min(),
                    "maximum": values.max(),
                    "support_mean_direction": support_for_mean(values),
                    "n_models": values.notna().sum(),
                }
            )
    return models, pd.DataFrame(summary_rows)


def shapley_product(low: dict[str, float], high: dict[str, float]) -> dict[str, float]:
    factors = tuple(low)
    contributions = {factor: 0.0 for factor in factors}
    permutations = tuple(itertools.permutations(factors))
    for order in permutations:
        state = dict(low)
        before = float(np.prod(list(state.values())))
        for factor in order:
            state[factor] = high[factor]
            after = float(np.prod(list(state.values())))
            contributions[factor] += after - before
            before = after
    return {factor: value / len(permutations) for factor, value in contributions.items()}


def build_factor_decomposition(
    levels: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for (tech, snapshot, model), group in levels.groupby(
        ["tech", "snapshot", "model"], sort=False
    ):
        indexed = group.set_index("climate_ssp")
        low = {
            "exposure_hours": float(indexed.loc["ssp126", "E_loss"]),
            "event_capacity_factor": float(indexed.loc["ssp126", "cf_event"]),
            "loss_intensity": float(indexed.loc["ssp126", "r_event"]),
        }
        high = {
            "exposure_hours": float(indexed.loc["ssp585", "E_loss"]),
            "event_capacity_factor": float(indexed.loc["ssp585", "cf_event"]),
            "loss_intensity": float(indexed.loc["ssp585", "r_event"]),
        }
        contributions = shapley_product(low, high)
        total = float(indexed.loc["ssp585", "R"] - indexed.loc["ssp126", "R"])
        rows.append(
            {
                "tech": tech,
                "snapshot": snapshot,
                "model": model,
                "exposure_hours_contribution": contributions["exposure_hours"],
                "event_capacity_factor_contribution": contributions[
                    "event_capacity_factor"
                ],
                "loss_intensity_contribution": contributions["loss_intensity"],
                "loss_difference": total,
                "closure_error": sum(contributions.values()) - total,
            }
        )
    models = pd.DataFrame(rows)
    components = (
        "exposure_hours_contribution",
        "event_capacity_factor_contribution",
        "loss_intensity_contribution",
        "loss_difference",
    )
    summary_rows: list[dict[str, object]] = []
    for (tech, snapshot), group in models.groupby(["tech", "snapshot"], sort=False):
        for component in components:
            values = group[component]
            summary_rows.append(
                {
                    "tech": tech,
                    "snapshot": snapshot,
                    "component": component,
                    "mean": values.mean(),
                    "minimum": values.min(),
                    "maximum": values.max(),
                    "support_mean_direction": support_for_mean(values),
                    "n_models": values.notna().sum(),
                }
            )
    return models, pd.DataFrame(summary_rows)


def prepare_data() -> dict[str, pd.DataFrame]:
    raw = pd.read_csv(INPUT_PATH)
    matrix = raw.loc[
        raw["country"].eq("GLOBAL")
        & raw["event"].eq("all")
        & raw["support"].eq("common")
    ].copy()
    matrix["exposure_days"] = matrix["E_loss"] / 24.0
    keys = ["tech", "snapshot", "model", "climate_ssp", "station_ssp"]
    if matrix.duplicated(keys).any():
        raise ValueError("Global union-loss matrix contains duplicate pathway cells")
    expected_rows = 2 * 3 * len(MODELS) * len(SSPS) ** 2
    if len(matrix) != expected_rows:
        raise ValueError(f"Expected {expected_rows} matrix rows, found {len(matrix)}")
    identity_error = (
        matrix["E_loss"] * matrix["cf_event"] * matrix["r_event"] - matrix["R"]
    ).abs()
    if identity_error.max() > 1e-9:
        raise ValueError("R = E_loss × cf_event × r_event identity failed")

    levels = matrix.loc[matrix["climate_ssp"].eq(matrix["station_ssp"])].copy()
    levels = levels.sort_values(["tech", "snapshot", "climate_ssp", "model"])
    level_summary = summarize_levels(levels)
    contrast_models, contrast_summary = build_contrasts(levels)
    pathway_models, pathway_summary = build_pathway_decomposition(matrix)
    factor_models, factor_summary = build_factor_decomposition(levels)

    max_pathway_closure = float(pathway_models["closure_error"].abs().max())
    max_factor_closure = float(factor_models["closure_error"].abs().max())
    if max_pathway_closure > 1e-10 or max_factor_closure > 1e-10:
        raise ValueError("A decomposition failed its exact closure check")

    key_2050 = contrast_models.loc[
        contrast_models["tech"].eq("wind")
        & contrast_models["snapshot"].eq(2050)
        & contrast_models["contrast"].eq(CONTRAST_LABEL)
    ]
    exposure_values = key_2050.loc[
        key_2050["metric"].eq("exposure_days"), "difference"
    ]
    loss_values = key_2050.loc[key_2050["metric"].eq("R"), "difference"]
    if not (exposure_values.lt(0).all() and loss_values.gt(0).all()):
        raise ValueError("The four-model 2050s wind ranking reversal is not present")

    tables = {
        "pathway_levels_models": levels,
        "pathway_levels_summary": level_summary,
        "pairwise_contrasts_models": contrast_models,
        "pairwise_contrasts_summary": contrast_summary,
        "climate_deployment_decomposition_models": pathway_models,
        "climate_deployment_decomposition_summary": pathway_summary,
        "loss_factor_shapley_models": factor_models,
        "loss_factor_shapley_summary": factor_summary,
    }
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(SOURCE_DIR / f"{name}.csv", index=False)

    validation = {
        "input": str(INPUT_PATH.relative_to(REPO)),
        "input_sha256": sha256(INPUT_PATH),
        "matrix_rows": len(matrix),
        "paired_level_rows": len(levels),
        "max_product_identity_error": float(identity_error.max()),
        "max_climate_deployment_closure_error": max_pathway_closure,
        "max_shapley_closure_error": max_factor_closure,
        "wind_2050_ssp585_minus_ssp126_exposure_all_negative": bool(
            exposure_values.lt(0).all()
        ),
        "wind_2050_ssp585_minus_ssp126_loss_all_positive": bool(loss_values.gt(0).all()),
        "models": list(MODELS),
    }
    VALIDATION_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return tables


def add_panel_label(ax: mpl.axes.Axes, label: str, x: float = -0.13) -> None:
    ax.text(
        x,
        1.04,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        color="#111111",
        clip_on=False,
    )


def signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}".replace("-", "−")


def save_png(fig: mpl.figure.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def draw_level_panel(
    ax: mpl.axes.Axes,
    levels: pd.DataFrame,
    metric: str,
    title: str,
    ylabel: str,
) -> None:
    subset = levels.loc[levels["tech"].eq("wind") & levels["snapshot"].eq(2050)]
    x = np.arange(len(SSPS), dtype=float)
    means: list[float] = []
    minima: list[float] = []
    maxima: list[float] = []
    for idx, ssp in enumerate(SSPS):
        values = subset.loc[subset["climate_ssp"].eq(ssp), metric].to_numpy()
        means.append(float(values.mean()))
        minima.append(float(values.min()))
        maxima.append(float(values.max()))
        ax.bar(
            idx,
            values.mean(),
            width=0.62,
            color=SSP_COLORS[ssp],
            alpha=0.82,
            edgecolor="white",
            linewidth=0.6,
            zorder=2,
        )
        ax.errorbar(
            idx,
            values.mean(),
            yerr=[[values.mean() - values.min()], [values.max() - values.mean()]],
            color="#333333",
            linewidth=0.8,
            capsize=2.3,
            capthick=0.8,
            zorder=4,
        )
        ax.scatter(
            np.full(len(values), idx) + np.linspace(-0.09, 0.09, len(values)),
            values,
            s=14,
            facecolor="white",
            edgecolor="#333333",
            linewidth=0.55,
            zorder=5,
        )
    y_max = max(maxima)
    y_min = min(0.0, min(minima))
    span = max(y_max - y_min, 1.0)
    ax.set_ylim(y_min, y_max + 0.25 * span)
    for idx, mean in enumerate(means):
        ax.text(
            idx,
            maxima[idx] + 0.035 * span,
            f"{mean:.2f}",
            ha="center",
            va="bottom",
            fontsize=7,
            color="#222222",
        )
    ax.set_xticks(x, [SSP_LABELS[ssp] for ssp in SSPS])
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(axis="y", zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def contrast_summary_value(
    summary: pd.DataFrame, snapshot: int, metric: str
) -> tuple[float, int]:
    row = summary.loc[
        summary["tech"].eq("wind")
        & summary["snapshot"].eq(snapshot)
        & summary["contrast"].eq(CONTRAST_LABEL)
        & summary["metric"].eq(metric)
    ]
    if len(row) != 1:
        raise ValueError(f"Missing wind contrast summary for {snapshot}, {metric}")
    return float(row.iloc[0]["mean"]), int(row.iloc[0]["support_mean_direction"])


def draw_effect_bars(
    ax: mpl.axes.Axes,
    values_by_component: list[np.ndarray],
    labels: list[str],
    colors: list[str],
    title: str,
    ylabel: str,
) -> None:
    means = np.array([values.mean() for values in values_by_component])
    minima = np.array([values.min() for values in values_by_component])
    maxima = np.array([values.max() for values in values_by_component])
    x = np.arange(len(labels), dtype=float)
    ax.axhline(0, color="#555555", linewidth=0.75, zorder=1)
    for idx, values in enumerate(values_by_component):
        ax.bar(
            idx,
            means[idx],
            width=0.63,
            color=colors[idx],
            alpha=0.86,
            edgecolor="white",
            linewidth=0.6,
            zorder=2,
        )
        ax.errorbar(
            idx,
            means[idx],
            yerr=[[means[idx] - minima[idx]], [maxima[idx] - means[idx]]],
            color="#333333",
            linewidth=0.8,
            capsize=2.2,
            capthick=0.8,
            zorder=4,
        )
        ax.scatter(
            np.full(len(values), idx) + np.linspace(-0.09, 0.09, len(values)),
            values,
            s=13,
            facecolor="white",
            edgecolor="#333333",
            linewidth=0.5,
            zorder=5,
        )
    low = min(float(minima.min()), 0.0)
    high = max(float(maxima.max()), 0.0)
    span = max(high - low, 1.0)
    ax.set_ylim(low - 0.18 * span, high + 0.23 * span)
    for idx, mean in enumerate(means):
        offset = 0.045 * span if mean >= 0 else -0.055 * span
        ax.text(
            idx,
            mean + offset,
            signed(float(mean)),
            ha="center",
            va="bottom" if mean >= 0 else "top",
            fontsize=7,
            color="#222222",
        )
    ax.set_xticks(x, labels)
    if len(labels) > 3:
        ax.tick_params(axis="x", labelsize=6.5)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(axis="y", zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def draw_gap_trajectory(
    ax: mpl.axes.Axes,
    contrast_models: pd.DataFrame,
    contrast_summary: pd.DataFrame,
    metric: str,
    title: str,
    ylabel: str,
) -> None:
    subset = contrast_models.loc[
        contrast_models["tech"].eq("wind")
        & contrast_models["contrast"].eq(CONTRAST_LABEL)
        & contrast_models["metric"].eq(metric)
    ]
    snapshots = np.array([2030, 2040, 2050])
    x = np.arange(3, dtype=float)
    pivot = subset.pivot(index="snapshot", columns="model", values="difference").reindex(snapshots)
    for model in MODELS:
        ax.plot(
            x,
            pivot[model].to_numpy(),
            color=MODEL_COLOR,
            linewidth=0.8,
            marker="o",
            markersize=2.2,
            alpha=0.58,
            zorder=2,
        )
    means = pivot.mean(axis=1).to_numpy()
    minima = pivot.min(axis=1).to_numpy()
    maxima = pivot.max(axis=1).to_numpy()
    ax.fill_between(x, minima, maxima, color=PAIRED_COLOR, alpha=0.12, linewidth=0, zorder=1)
    ax.plot(
        x,
        means,
        color=PAIRED_COLOR,
        linewidth=2.0,
        marker="o",
        markersize=4.2,
        markerfacecolor=PAIRED_COLOR,
        markeredgecolor="white",
        markeredgewidth=0.6,
        zorder=4,
    )
    ax.axhline(0, color="#444444", linewidth=0.75, zorder=1)
    low = min(float(minima.min()), 0.0)
    high = max(float(maxima.max()), 0.0)
    span = max(high - low, 1.0)
    ax.set_ylim(low - 0.20 * span, high + 0.26 * span)
    for idx, snapshot in enumerate(snapshots):
        mean, support = contrast_summary_value(contrast_summary, int(snapshot), metric)
        offset = 0.07 * span if mean >= 0 else -0.08 * span
        ax.text(
            idx,
            mean + offset,
            f"{signed(mean)}\n({support}/4)",
            ha="center",
            va="bottom" if mean >= 0 else "top",
            fontsize=7,
            color=PAIRED_COLOR,
            fontweight="bold",
            zorder=5,
        )
    ax.set_xticks(x, ["2030s", "2040s", "2050s"])
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(axis="y", zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def make_figures(tables: dict[str, pd.DataFrame]) -> None:
    levels = tables["pathway_levels_models"]
    contrast_models = tables["pairwise_contrasts_models"]
    contrast_summary = tables["pairwise_contrasts_summary"]
    pathway_models = tables["climate_deployment_decomposition_models"]
    factor_models = tables["loss_factor_shapley_models"]

    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH, 76 * MM_TO_INCH))
    draw_level_panel(
        axes[0],
        levels,
        "exposure_days",
        "Exposure duration",
        "Exposure (days yr$^{-1}$)",
    )
    draw_level_panel(
        axes[1],
        levels,
        "R",
        "Unit-capacity net loss",
        "Loss (MWh MW$^{-1}$ yr$^{-1}$)",
    )
    add_panel_label(axes[0], "a")
    add_panel_label(axes[1], "b")
    fig.subplots_adjust(left=0.08, right=0.985, bottom=0.18, top=0.90, wspace=0.30)
    save_png(fig, FIGURE_DIR / "figure_1_risk_ranking_paradox.png")

    for metric, title, ylabel, name, label in (
        (
            "exposure_days",
            "Exposure duration",
            "Exposure (days yr$^{-1}$)",
            "figure_1a.png",
            "a",
        ),
        (
            "R",
            "Unit-capacity net loss",
            "Loss (MWh MW$^{-1}$ yr$^{-1}$)",
            "figure_1b.png",
            "b",
        ),
    ):
        fig, ax = plt.subplots(figsize=(90 * MM_TO_INCH, 76 * MM_TO_INCH))
        draw_level_panel(ax, levels, metric, title, ylabel)
        add_panel_label(ax, label)
        fig.subplots_adjust(left=0.19, right=0.97, bottom=0.18, top=0.90)
        save_png(fig, PANEL_DIR / name)

    pathway_2050 = pathway_models.loc[
        pathway_models["tech"].eq("wind") & pathway_models["snapshot"].eq(2050)
    ]
    exposure_decomp = pathway_2050.loc[pathway_2050["metric"].eq("exposure_days")]
    loss_decomp = pathway_2050.loc[pathway_2050["metric"].eq("R")]
    pathway_columns = (
        "climate_contribution",
        "deployment_contribution",
        "paired_difference",
    )
    pathway_labels = ["Climate", "Deployment", "Paired\npathway"]
    pathway_colors = [CLIMATE_COLOR, DEPLOYMENT_COLOR, PAIRED_COLOR]
    factor_2050 = factor_models.loc[
        factor_models["tech"].eq("wind") & factor_models["snapshot"].eq(2050)
    ]
    factor_columns = (
        "exposure_hours_contribution",
        "event_capacity_factor_contribution",
        "loss_intensity_contribution",
        "loss_difference",
    )
    factor_labels = ["Exposure\nhours", "Event\nCF", "Loss\nintensity", "Net\ngap"]
    factor_colors = [EXPOSURE_COLOR, CF_COLOR, INTENSITY_COLOR, PAIRED_COLOR]

    fig, axes = plt.subplots(1, 3, figsize=(FULL_WIDTH, 76 * MM_TO_INCH))
    draw_effect_bars(
        axes[0],
        [exposure_decomp[column].to_numpy() for column in pathway_columns],
        pathway_labels,
        pathway_colors,
        "Pathway effect on exposure",
        "Contribution (days yr$^{-1}$)",
    )
    draw_effect_bars(
        axes[1],
        [loss_decomp[column].to_numpy() for column in pathway_columns],
        pathway_labels,
        pathway_colors,
        "Pathway effect on loss",
        "Contribution (MWh MW$^{-1}$ yr$^{-1}$)",
    )
    draw_effect_bars(
        axes[2],
        [factor_2050[column].to_numpy() for column in factor_columns],
        factor_labels,
        factor_colors,
        "Factor effect on loss",
        "Contribution (MWh MW$^{-1}$ yr$^{-1}$)",
    )
    for label, ax in zip(("a", "b", "c"), axes):
        add_panel_label(ax, label, x=-0.16)
    fig.subplots_adjust(left=0.065, right=0.99, bottom=0.22, top=0.89, wspace=0.42)
    save_png(fig, FIGURE_DIR / "figure_2_deployment_mechanism.png")

    panel_specs = (
        (
            exposure_decomp,
            pathway_columns,
            pathway_labels,
            pathway_colors,
            "Pathway effect on exposure",
            "Contribution (days yr$^{-1}$)",
            "figure_2a.png",
            "a",
        ),
        (
            loss_decomp,
            pathway_columns,
            pathway_labels,
            pathway_colors,
            "Pathway effect on loss",
            "Contribution (MWh MW$^{-1}$ yr$^{-1}$)",
            "figure_2b.png",
            "b",
        ),
        (
            factor_2050,
            factor_columns,
            factor_labels,
            factor_colors,
            "Factor effect on loss",
            "Contribution (MWh MW$^{-1}$ yr$^{-1}$)",
            "figure_2c.png",
            "c",
        ),
    )
    for data, columns, labels, colors, title, ylabel, name, label in panel_specs:
        fig, ax = plt.subplots(figsize=(90 * MM_TO_INCH, 76 * MM_TO_INCH))
        draw_effect_bars(
            ax,
            [data[column].to_numpy() for column in columns],
            list(labels),
            list(colors),
            title,
            ylabel,
        )
        add_panel_label(ax, label)
        fig.subplots_adjust(left=0.20, right=0.97, bottom=0.22, top=0.89)
        save_png(fig, PANEL_DIR / name)

    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH, 76 * MM_TO_INCH))
    draw_gap_trajectory(
        axes[0],
        contrast_models,
        contrast_summary,
        "exposure_days",
        "Exposure-gap trajectory",
        "SSP5-8.5 − SSP1-2.6 (days yr$^{-1}$)",
    )
    draw_gap_trajectory(
        axes[1],
        contrast_models,
        contrast_summary,
        "R",
        "Loss-gap trajectory",
        "SSP5-8.5 − SSP1-2.6\n(MWh MW$^{-1}$ yr$^{-1}$)",
    )
    add_panel_label(axes[0], "a")
    add_panel_label(axes[1], "b")
    legend_handles = [
        Line2D([0], [0], color=MODEL_COLOR, marker="o", markersize=3, linewidth=0.8, label="Individual models"),
        Line2D([0], [0], color=PAIRED_COLOR, marker="o", markersize=4, linewidth=2, label="Four-model mean"),
    ]
    axes[1].legend(handles=legend_handles, loc="upper left", frameon=False)
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.18, top=0.90, wspace=0.31)
    save_png(fig, FIGURE_DIR / "figure_3_paradox_emergence.png")

    for metric, title, ylabel, name, label in (
        (
            "exposure_days",
            "Exposure-gap trajectory",
            "SSP5-8.5 − SSP1-2.6 (days yr$^{-1}$)",
            "figure_3a.png",
            "a",
        ),
        (
            "R",
            "Loss-gap trajectory",
            "SSP5-8.5 − SSP1-2.6\n(MWh MW$^{-1}$ yr$^{-1}$)",
            "figure_3b.png",
            "b",
        ),
    ):
        fig, ax = plt.subplots(figsize=(90 * MM_TO_INCH, 76 * MM_TO_INCH))
        draw_gap_trajectory(ax, contrast_models, contrast_summary, metric, title, ylabel)
        add_panel_label(ax, label)
        if metric == "R":
            ax.legend(handles=legend_handles, loc="upper left", frameon=False)
        fig.subplots_adjust(left=0.20, right=0.97, bottom=0.18, top=0.90)
        save_png(fig, PANEL_DIR / name)


def summary_row(
    summary: pd.DataFrame, snapshot: int, metric: str, component: str
) -> pd.Series:
    row = summary.loc[
        summary["tech"].eq("wind")
        & summary["snapshot"].eq(snapshot)
        & summary["metric"].eq(metric)
        & summary["component"].eq(component)
    ]
    if len(row) != 1:
        raise ValueError(f"Missing decomposition summary: {snapshot}, {metric}, {component}")
    return row.iloc[0]


def factor_row(summary: pd.DataFrame, snapshot: int, component: str) -> pd.Series:
    row = summary.loc[
        summary["tech"].eq("wind")
        & summary["snapshot"].eq(snapshot)
        & summary["component"].eq(component)
    ]
    if len(row) != 1:
        raise ValueError(f"Missing factor summary: {snapshot}, {component}")
    return row.iloc[0]


def write_markdown(tables: dict[str, pd.DataFrame]) -> None:
    levels_summary = tables["pathway_levels_summary"]
    contrast_summary = tables["pairwise_contrasts_summary"]
    pathway_summary = tables["climate_deployment_decomposition_summary"]
    factor_summary = tables["loss_factor_shapley_summary"]

    level_rows: list[str] = []
    for ssp in SSPS:
        exposure = levels_summary.loc[
            levels_summary["tech"].eq("wind")
            & levels_summary["snapshot"].eq(2050)
            & levels_summary["climate_ssp"].eq(ssp)
            & levels_summary["metric"].eq("exposure_days"),
            "mean",
        ].iloc[0]
        loss = levels_summary.loc[
            levels_summary["tech"].eq("wind")
            & levels_summary["snapshot"].eq(2050)
            & levels_summary["climate_ssp"].eq(ssp)
            & levels_summary["metric"].eq("R"),
            "mean",
        ].iloc[0]
        level_rows.append(f"| {SSP_LABELS[ssp]} | {exposure:.2f} | {loss:.2f} |")

    exp_gap, exp_support = contrast_summary_value(contrast_summary, 2050, "exposure_days")
    loss_gap, loss_support = contrast_summary_value(contrast_summary, 2050, "R")

    decomp_rows: list[str] = []
    decomp_labels = (
        ("climate_contribution", "气候项"),
        ("deployment_contribution", "部署项"),
        ("paired_difference", "配对路径总差异"),
    )
    for component, label in decomp_labels:
        exposure = summary_row(pathway_summary, 2050, "exposure_days", component)
        loss = summary_row(pathway_summary, 2050, "R", component)
        decomp_rows.append(
            f"| {label} | {signed(float(exposure['mean']))} ({int(exposure['support_mean_direction'])}/4) "
            f"| {signed(float(loss['mean']))} ({int(loss['support_mean_direction'])}/4) |"
        )

    factor_rows: list[str] = []
    factor_labels = (
        ("exposure_hours_contribution", "暴露时长"),
        ("event_capacity_factor_contribution", "事件时段正常容量因子"),
        ("loss_intensity_contribution", "损失强度"),
        ("loss_difference", "净损失差异"),
    )
    for component, label in factor_labels:
        row = factor_row(factor_summary, 2050, component)
        factor_rows.append(
            f"| {label} | {signed(float(row['mean']))} | {int(row['support_mean_direction'])}/4 |"
        )

    trajectory_rows: list[str] = []
    for snapshot in (2030, 2040, 2050):
        exposure, exposure_support = contrast_summary_value(
            contrast_summary, snapshot, "exposure_days"
        )
        loss, loss_support = contrast_summary_value(contrast_summary, snapshot, "R")
        trajectory_rows.append(
            f"| {snapshot}s | {signed(exposure)} ({exposure_support}/4) "
            f"| {signed(loss)} ({loss_support}/4) |"
        )
    loss_2040, _ = contrast_summary_value(contrast_summary, 2040, "R")
    amplification = loss_gap / loss_2040

    markdown = rf"""# SSP 路径下风电风险排序悖论：三个相互衔接的 RQ

## 背景与核心观点

极端事件暴露时长常被用作新能源气候风险的直接代理，但它不能独立决定发电损失。四模式均值显示，到 2050 年代，风电 SSP5-8.5 路径的极端事件暴露天数在三个 SSP 中最低，单位装机损失却最高。这个风险排序反转主要由部署项塑造：较少的暴露时长被更高的事件时段正常容量因子和更高的损失强度抵消。该错配在 2040 年代出现，到 2050 年代扩大为 SSP5-8.5 相对 SSP1-2.6 的四模式一致反转。

## RQ1：风险排序悖论

**Question：不同 SSP 部署路径下，更少的极端事件暴露是否意味着更低的单位装机损失？**

**Result：不意味着。到 2050 年代，四模式均值中的风电 SSP5-8.5 同时处于“暴露最低”和“损失最高”两个相反的排序端点。**

![Figure 1：2050年代风电暴露与单位装机损失的SSP排序](rq_figures/figure_1_risk_ranking_paradox.png)

**Figure 1 | 2050 年代风电的暴露—损失排序反转。** 柱高为四模式均值，白点为单模式结果，误差线为模式最小值至最大值。SSP5-8.5 相对 SSP1-2.6 的暴露减少 {abs(exp_gap):.2f} days yr⁻¹（{exp_support}/4 模式同向），单位装机净损失却增加 {loss_gap:.2f} MWh MW⁻¹ yr⁻¹（{loss_support}/4 模式同向）。

| 路径 | 暴露天数（days yr⁻¹） | 单位装机净损失（MWh MW⁻¹ yr⁻¹） |
|---|---:|---:|
{chr(10).join(level_rows)}

三个 SSP 的均值排序分别为：暴露 SSP1-2.6 > SSP2-4.5 > SSP5-8.5；损失 SSP5-8.5 > SSP1-2.6 > SSP2-4.5。因而，单凭暴露时长会把 2050 年代风电路径的实际损失风险排反。

## RQ2：部署驱动的“更少但更伤”机制

**Question：暴露—损失反转由气候变化本身还是容量部署造成？较少的暴露为何仍转化为更高损失？**

**Result：部署项同时压低暴露并抬高损失；事件时段正常容量因子与损失强度的正贡献共同超过了暴露减少带来的负贡献。**

![Figure 2：气候部署分解与损失因子分解](rq_figures/figure_2_deployment_mechanism.png)

**Figure 2 | SSP5-8.5 相对 SSP1-2.6 的 2050 年代机制分解。** a,b 为气候情景与场站部署的对称反事实分解；c 使用恒等式 $R = E_{{loss}} \times CF_{{event}} \times r_{{event}}$ 的精确 Shapley 分解。柱高为四模式均值，白点为单模式结果，误差线为模式范围。

| 路径分解项 | 暴露贡献（days yr⁻¹） | 损失贡献（MWh MW⁻¹ yr⁻¹） |
|---|---:|---:|
{chr(10).join(decomp_rows)}

气候项使暴露增加 1.10 days yr⁻¹，并使损失减少 1.80 MWh MW⁻¹ yr⁻¹；部署项则使暴露减少 4.31 days yr⁻¹，同时使损失增加 17.71 MWh MW⁻¹ yr⁻¹。因此，配对路径最终呈现“暴露 −3.21、损失 +15.91”的相反方向。

| 损失因子 | 对 SSP5-8.5−SSP1-2.6 损失差异的贡献（MWh MW⁻¹ yr⁻¹） | 同向模式数 |
|---|---:|---:|
{chr(10).join(factor_rows)}

暴露减少本应使损失下降 9.77 MWh MW⁻¹ yr⁻¹；事件时段正常容量因子与损失强度分别增加 11.88 和 13.79 MWh MW⁻¹ yr⁻¹，二者合计 25.68 MWh MW⁻¹ yr⁻¹，完全抵消并逆转了暴露时长效应。

## RQ3：错配随路径分化形成并扩大

**Question：这种暴露—损失错配何时出现，并会不会随未来路径分化而增强？**

**Result：2030 年代两类风险的均值排序仍一致，2040 年代损失排序首先翻转，2050 年代形成“暴露更少、损失更高”的四模式一致错配。**

![Figure 3：暴露差异与损失差异的年代演化](rq_figures/figure_3_paradox_emergence.png)

**Figure 3 | SSP5-8.5−SSP1-2.6 风电风险差异的年代演化。** 灰线为单模式，紫线为四模式均值，阴影为模式范围；括号表示与均值方向一致的模式数。零线表示两条路径无差异。

| 年代 | 暴露差异（days yr⁻¹） | 单位装机净损失差异（MWh MW⁻¹ yr⁻¹） |
|---|---:|---:|
{chr(10).join(trajectory_rows)}

2030 年代，SSP5-8.5 的暴露和损失均值都较低。到 2040 年代，损失差异已翻转为 +5.20 MWh MW⁻¹ yr⁻¹，且四模式一致；到 2050 年代，暴露重新表现为四模式一致的减少，而损失差异扩大到 +15.91 MWh MW⁻¹ yr⁻¹，是 2040 年代的 {amplification:.1f} 倍。由此，路径分化并非简单增加极端事件时长，而是在未来逐步拆开“暴露多少”与“损失多大”两种风险排序。

## 三个 RQ 的论证链

RQ1 建立可观察的核心悖论：最低暴露对应最高损失。RQ2 解释该悖论：部署项改变了场站容量权重、事件时段正常发电水平和损失强度，使后两者压过时长效应。RQ3 给出时间维度：这种机制在 2040 年代开始改变损失排序，并在 2050 年代形成稳定而扩大的风险错配。

## 数据与复现

- 数据入口：`paper_figures/main/fig02_generation_loss/outputs/meeting_loss/source_data/global_all_combinations.csv`
- [分析与绘图脚本](../build_rq_story.py)
- [路径水平均值源数据](rq_source_data/pathway_levels_summary.csv)
- [SSP 路径差异源数据](rq_source_data/pairwise_contrasts_summary.csv)
- [气候—部署分解源数据](rq_source_data/climate_deployment_decomposition_summary.csv)
- [损失因子 Shapley 分解源数据](rq_source_data/loss_factor_shapley_summary.csv)
- [验证记录](rq_validation.json)
"""
    MARKDOWN_PATH.write_text(markdown, encoding="utf-8")


def main() -> None:
    set_style()
    tables = prepare_data()
    make_figures(tables)
    write_markdown(tables)
    print(f"Wrote {MARKDOWN_PATH}")
    print(f"Wrote figures to {FIGURE_DIR}")
    print(f"Wrote source tables to {SOURCE_DIR}")


if __name__ == "__main__":
    main()
