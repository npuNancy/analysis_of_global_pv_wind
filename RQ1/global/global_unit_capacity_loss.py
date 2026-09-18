"""Global unit-capacity losses for four CMIP6 models and their equal-weight mean.

Read annual station NetCDF results through data/loss_outputs. Each output set
contains annual trajectories, 2050s event shares and SSP126-based two-factor and
three-factor waterfalls. The default pipeline reads model/SSP/technology units in
parallel; the original single-process pipeline remains available with
``--execution-mode single``. Figures are PNG only; importing this module does not
read inputs or draw figures.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import xarray as xr


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
LOSS_ROOT = PROJECT_ROOT / "data/loss_outputs"
MODELS = ("CANESM5", "MPI-ESM1-2-HR", "MRI-ESM2-0", "BCC-CSM2-MR")
SSPS = ("ssp126", "ssp245", "ssp585")
TECHS = ("wind", "solar")
SNAPSHOTS = (2030, 2040, 2050)
SNAPSHOT_YEARS = 10.0
MEAN_PERIOD = "mean_2030s_2050s"
SSP_LABEL = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp585": "SSP5-8.5"}
SSP_COLOR = {"ssp126": "#1d3b6f", "ssp245": "#b77c19", "ssp585": "#9e1b1b"}
TECH_LABEL = {"wind": "Wind", "solar": "Solar"}
EVENT_LABEL = {
    "low_resource": "Low resource", "high_temp": "High temperature",
    "high_wind": "High wind", "hot_humid": "Hot-humid", "icing": "Icing",
    "rainstorm": "Rainstorm", "cold_highwind": "Cold-high wind",
    "freezing_rain": "Freezing rain", "high_humidity": "High humidity",
}
EVENT_COLOR = dict(zip(EVENT_LABEL, [
    "#3b6fb6", "#d95f02", "#b2182b", "#e78ac3", "#67a9cf",
    "#1b9e77", "#7570b3", "#80cdc1", "#66a61e",
]))
TECH_EVENTS = {
    "wind": ("low_resource", "high_temp", "high_wind", "hot_humid", "icing"),
    "solar": ("low_resource", "icing", "rainstorm", "cold_highwind",
              "freezing_rain", "high_humidity"),
}
UNIT_COLUMN = "unit_capacity_loss_mwh_per_mw_year"
UNIT_LABEL = "Unit-capacity loss (MWh MW$^{-1}$ yr$^{-1}$)"
ANNUAL_KEYS = ["scenario", "tech", "snapshot_year", "analysis_year"]
EXP_COLOR, RES_COLOR, INT_COLOR, INK = "#9EC3D3", "#A6C48A", "#C99581", "#30363C"
LOGGER = logging.getLogger("rq1.global_unit_capacity_loss")


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
        "font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "legend.frameon": False,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })


def normalize_scenario(value: str) -> str:
    value = str(value).lower()
    return "ssp585" if value == "ssp560" else value


def read_patch_manifest(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    patches = sorted(payload["patches"])
    if payload.get("active_patch_count") != 47 or len(patches) != 47:
        raise ValueError(f"Expected 47 active patches: {path}")
    return patches


def scenario_directory(root: Path, model: str, scenario: str) -> Path:
    candidates = [root / model / scenario]
    if scenario == "ssp585":
        candidates.append(root / model / "ssp560")
    found = [path for path in candidates if path.is_dir()]
    if len(found) != 1:
        raise ValueError(f"Expected exactly one scenario directory: {candidates}")
    return found[0]


def finite_vector(ds: xr.Dataset, name: str, path: Path) -> np.ndarray:
    variable = ds[name]
    values = variable.to_numpy().astype(float)
    if variable.dims != ("station",) or not np.isfinite(values).all():
        raise ValueError(f"Invalid station vector {name}: {path}")
    return values


def task_manifest_path(task_dir: Path) -> Path:
    """Resolve the normal task manifest or the upstream no-stations marker."""
    normal = task_dir / "manifest.json"
    if normal.is_file():
        return normal
    markers = sorted(task_dir.glob("manifest.json.*"))
    if len(markers) != 1:
        raise FileNotFoundError(
            f"Expected manifest.json or one manifest marker in {task_dir}; found {markers}"
        )
    return markers[0]


def task_snapshots(manifest: dict, manifest_path: Path) -> list[dict]:
    """Normalize completed manifests and manifest.json.SKIPPED_NO_STATIONS."""
    if manifest.get("status") == "SKIPPED_NO_STATIONS":
        if manifest.get("station_count", 0) != 0:
            raise ValueError(f"Skipped task has non-zero station_count: {manifest_path}")
        return [{"snapshot_year": snapshot, "status": "SKIPPED_NO_STATIONS",
                 "station_count": 0} for snapshot in SNAPSHOTS]
    snapshots = manifest.get("snapshots")
    if snapshots is None:
        snapshots = [{"snapshot_year": snapshot, "status": "COMPLETED"}
                     for snapshot in manifest.get("snapshot_years", SNAPSHOTS)]
    return snapshots


def load_model_unit(
    model: str, scenario: str, tech: str, loss_root: Path, patches: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read one independent model/SSP/technology unit."""
    records, inventory, coverage = [], [], []
    station_sets: dict[tuple, set[str]] = {}
    status_root = scenario_directory(loss_root / "task_status", model, scenario)
    result_root = scenario_directory(loss_root / "generation_loss", model, scenario)
    for patch in patches:
        manifest_path = task_manifest_path(status_root / patch / tech)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {"model": model, "patch": patch, "tech": tech}
        if any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError(f"Unexpected task metadata: {manifest_path}")
        if normalize_scenario(manifest["scenario"]) != scenario:
            raise ValueError(f"Scenario mismatch: {manifest_path}")
        snapshots = task_snapshots(manifest, manifest_path)
        if sorted(item["snapshot_year"] for item in snapshots) != list(SNAPSHOTS):
            raise ValueError(f"Incomplete snapshot coverage: {manifest_path}")
        for item in snapshots:
            snapshot = item["snapshot_year"]
            coverage.append({"model": model, "scenario": scenario, "tech": tech,
                             "patch_id": patch, **item})
            folder = result_root / patch / str(snapshot) / tech
            if item["status"] == "SKIPPED_NO_STATIONS":
                if list(folder.glob(f"{tech}_generation_loss_station_*.nc")):
                    raise ValueError(f"Files conflict with empty-station status: {folder}")
                continue
            if item["status"] != "COMPLETED":
                raise ValueError(f"Incomplete snapshot: {manifest_path}: {snapshot}")
            first_ids = None
            first_capacity = None
            for year in range(snapshot, snapshot + int(SNAPSHOT_YEARS)):
                path = folder / f"{tech}_generation_loss_station_{year}.nc"
                required = [
                    "station_id", "capacity_mw", "activation_year",
                    "normal_generation_mwh_all",
                    *[name for event in ("all", *TECH_EVENTS[tech])
                      for name in (f"net_generation_loss_mwh_{event}",
                                   f"event_duration_hours_{event}")],
                ]
                with xr.open_dataset(path, cache=False) as source:
                    attrs = dict(source.attrs)
                    ds = source[required].load()
                expected_attrs = {
                    "model": model, "tech": tech, "patch_id": patch,
                    "snapshot_year": snapshot, "analysis_year": year,
                    "analysis_scheme": "center-k", "analysis_k": 5,
                    "source": "global_bcsd_patch",
                }
                if any(attrs.get(k) != v for k, v in expected_attrs.items()):
                    raise ValueError(f"Unexpected result metadata: {path}")
                if normalize_scenario(attrs["scenario"]) != scenario:
                    raise ValueError(f"Scenario mismatch: {path}")
                if set(json.loads(attrs["supported_events"])) != set(TECH_EVENTS[tech]):
                    raise ValueError(f"Unexpected event categories: {path}")
                ids = ds.station_id.to_numpy().astype(str)
                capacity = finite_vector(ds, "capacity_mw", path)
                activation = finite_vector(ds, "activation_year", path)
                if (capacity < 0).any() or (activation > snapshot).any():
                    raise ValueError(f"Invalid snapshot capacity or activation: {path}")
                station_count = item.get("station_count")
                if station_count is not None and len(ids) != station_count:
                    raise ValueError(f"Station count mismatch: {path}")
                if len(set(ids)) != len(ids):
                    raise ValueError(f"Duplicate station IDs: {path}")
                if first_ids is None:
                    first_ids, first_capacity = ids, capacity
                    seen = station_sets.setdefault((scenario, tech, snapshot), set())
                    if seen.intersection(ids):
                        raise ValueError(f"Stations repeated across patches: {path}")
                    seen.update(ids)
                elif not np.array_equal(ids, first_ids) or not np.array_equal(capacity, first_capacity):
                    raise ValueError(f"Station fleet changes within snapshot: {path}")
                normal_event = finite_vector(ds, "normal_generation_mwh_all", path)
                for event in ("all", *TECH_EVENTS[tech]):
                    loss = finite_vector(ds, f"net_generation_loss_mwh_{event}", path)
                    hours = finite_vector(ds, f"event_duration_hours_{event}", path)
                    if (hours < 0).any():
                        raise ValueError(f"Negative event duration: {path}")
                    records.append({
                        "scenario": scenario, "tech": tech,
                        "snapshot_year": snapshot, "analysis_year": year,
                        "patch_id": patch, "event": event,
                        "net_loss_mwh": loss.sum(), "capacity_mw": capacity.sum(),
                        "capacity_event_hours_mw_h": np.dot(capacity, hours),
                        "normal_event_generation_mwh": (
                            normal_event.sum() if event == "all" else 0.0),
                        "n_stations": len(ids),
                    })
                del ds
                gc.collect()
                stat = path.stat()
                inventory.append({"path": str(path.resolve()), "size_bytes": stat.st_size,
                                  "mtime_ns": stat.st_mtime_ns})
    LOGGER.info("Read %s / %s / %s", model, scenario, tech)
    return pd.DataFrame(records), pd.DataFrame(inventory), pd.DataFrame(coverage)


def load_model(
    model: str, loss_root: Path, patches: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Original single-process model pipeline, retained for reproducibility."""
    parts = [load_model_unit(model, scenario, tech, loss_root, patches)
             for scenario in SSPS for tech in TECHS]
    return tuple(pd.concat([part[index] for part in parts], ignore_index=True)
                 for index in range(3))


def load_model_unit_worker(task: tuple[str, str, str, Path, list[str]]) -> tuple:
    """Process-pool entry point; all imports and file handles stay per worker."""
    configure_logging()
    model, scenario, tech, loss_root, patches = task
    tables = load_model_unit(model, scenario, tech, loss_root, patches)
    return model, scenario, tech, *tables


def annual_trajectory(patches: pd.DataFrame) -> pd.DataFrame:
    annual = patches[patches.event.eq("all")].groupby(ANNUAL_KEYS, as_index=False).agg(
        net_loss_mwh=("net_loss_mwh", "sum"), capacity_mw=("capacity_mw", "sum"),
        capacity_event_hours_mw_h=("capacity_event_hours_mw_h", "sum"),
        normal_event_generation_mwh=("normal_event_generation_mwh", "sum"),
        n_stations=("n_stations", "sum"), n_patches=("patch_id", "nunique"),
    )
    expected = {(s, t, y, a) for s in SSPS for t in TECHS
                for y in SNAPSHOTS
                for a in range(y, y + int(SNAPSHOT_YEARS))}
    if set(annual[ANNUAL_KEYS].itertuples(index=False, name=None)) != expected:
        raise ValueError("Incomplete global annual coverage")
    if not annual.capacity_mw.gt(0).all():
        raise ValueError("Global installed capacity must be positive")
    annual[UNIT_COLUMN] = annual.net_loss_mwh / annual.capacity_mw
    return annual


def capacity_metrics(annual: pd.DataFrame) -> pd.DataFrame:
    metrics = annual.groupby(ANNUAL_KEYS[:3], as_index=False).agg(
        C_MW=("capacity_mw", "mean"), L_MWh_per_year=("net_loss_mwh", "mean"),
        H_MW_h_per_year=("capacity_event_hours_mw_h", "mean"),
        G0_ev_MWh_per_year=("normal_event_generation_mwh", "mean"),
    )
    if not (metrics.H_MW_h_per_year.gt(0) & metrics.G0_ev_MWh_per_year.gt(0)).all():
        raise ValueError("Positive exposure and event-window normal generation are required")
    metrics["E_h_per_year"] = metrics.H_MW_h_per_year / metrics.C_MW
    metrics["I_MWh_per_MW_h"] = metrics.L_MWh_per_year / metrics.H_MW_h_per_year
    metrics["R_MWh_MW_per_year"] = metrics.L_MWh_per_year / metrics.C_MW
    metrics["cf_ev"] = metrics.G0_ev_MWh_per_year / metrics.H_MW_h_per_year
    metrics["r_ev"] = metrics.L_MWh_per_year / metrics.G0_ev_MWh_per_year
    if not np.allclose(metrics.E_h_per_year * metrics.I_MWh_per_MW_h,
                       metrics.R_MWh_MW_per_year, rtol=1e-12, atol=1e-10):
        raise AssertionError("R = E × I failed")
    if not np.allclose(metrics.cf_ev * metrics.r_ev, metrics.I_MWh_per_MW_h,
                       rtol=1e-12, atol=1e-10):
        raise AssertionError("I = cf_ev × r_ev failed")
    return metrics


def event_composition(patches: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Shares of positive global event net losses, with overlapping categories."""
    events = patches[patches.event.ne("all") & patches.snapshot_year.eq(2050)]
    events = events.groupby(["scenario", "tech", "event"], as_index=False).agg(
        net_loss_mwh_decade=("net_loss_mwh", "sum"),
    )
    capacity = metrics[metrics.snapshot_year.eq(2050)][["scenario", "tech", "C_MW"]]
    events = events.merge(capacity, on=["scenario", "tech"], validate="many_to_one")
    events["net_unit_capacity_loss"] = (
        events.net_loss_mwh_decade / SNAPSHOT_YEARS / events.C_MW
    )
    events["positive_unit_capacity_loss"] = events.net_unit_capacity_loss.clip(lower=0)
    parts = []
    for group, data in (("All events", events),
                        ("Other events", events[events.event.ne("low_resource")])):
        data = data.copy()
        pool = data.groupby(["scenario", "tech"]).positive_unit_capacity_loss.transform("sum")
        if not pool.gt(0).all():
            raise ValueError(f"Empty positive event-loss pool: {group}")
        data["share_pct"] = 100 * data.positive_unit_capacity_loss / pool
        data["group"] = group
        parts.append(data)
    shares = pd.concat(parts, ignore_index=True)
    if not np.allclose(shares.groupby(["scenario", "tech", "group"]).share_pct.sum(), 100):
        raise AssertionError("Event shares do not sum to 100%")
    return shares


def unit_decomposition(metrics: pd.DataFrame) -> pd.DataFrame:
    """Symmetric exact two-factor attribution of target-minus-SSP126 unit loss."""
    records = []
    for tech in TECHS:
        for snapshot in SNAPSHOTS:
            rows = metrics[metrics.tech.eq(tech) & metrics.snapshot_year.eq(snapshot)].set_index("scenario")
            base = rows.loc["ssp126"]
            for target in SSPS[1:]:
                other = rows.loc[target]
                exposure = (other.E_h_per_year - base.E_h_per_year) * (
                    other.I_MWh_per_MW_h + base.I_MWh_per_MW_h) / 2
                intensity = (other.I_MWh_per_MW_h - base.I_MWh_per_MW_h) * (
                    other.E_h_per_year + base.E_h_per_year) / 2
                gap = other.R_MWh_MW_per_year - base.R_MWh_MW_per_year
                if not np.isclose(exposure + intensity, gap, rtol=1e-11, atol=1e-9):
                    raise AssertionError(f"Unit-loss decomposition failed: {tech}/{snapshot}/{target}")
                records.append({
                    "tech": tech, "snapshot_year": str(snapshot),
                    "baseline": "ssp126", "target": target,
                    "baseline_unit_loss": base.R_MWh_MW_per_year,
                    "target_unit_loss": other.R_MWh_MW_per_year,
                    "gap_unit_loss": gap, "exposure_unit_loss": exposure,
                    "intensity_unit_loss": intensity,
                })
    result = pd.DataFrame(records)
    mean = result.groupby(["tech", "baseline", "target"], as_index=False).mean(numeric_only=True)
    mean["snapshot_year"] = MEAN_PERIOD
    return pd.concat([result, mean], ignore_index=True)


def symmetric_contribution(
    delta: float, others: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    """Symmetric (Shapley) contribution of one factor of a three-factor product."""
    (b_target, c_target), (b_base, c_base) = others
    return delta / 6 * (2 * b_target * c_target + 2 * b_base * c_base
                        + b_base * c_target + b_target * c_base)


def unit_decomposition_3f(metrics: pd.DataFrame) -> pd.DataFrame:
    """Symmetric exact three-factor attribution of target-minus-SSP126 unit loss."""
    records = []
    for tech in TECHS:
        for snapshot in SNAPSHOTS:
            rows = metrics[metrics.tech.eq(tech) & metrics.snapshot_year.eq(snapshot)].set_index("scenario")
            base = rows.loc["ssp126"]
            for target in SSPS[1:]:
                other = rows.loc[target]
                exposure = symmetric_contribution(
                    other.E_h_per_year - base.E_h_per_year,
                    ((other.cf_ev, other.r_ev), (base.cf_ev, base.r_ev)))
                resource = symmetric_contribution(
                    other.cf_ev - base.cf_ev,
                    ((other.E_h_per_year, other.r_ev), (base.E_h_per_year, base.r_ev)))
                rate = symmetric_contribution(
                    other.r_ev - base.r_ev,
                    ((other.E_h_per_year, other.cf_ev), (base.E_h_per_year, base.cf_ev)))
                gap = other.R_MWh_MW_per_year - base.R_MWh_MW_per_year
                if not np.isclose(exposure + resource + rate, gap, rtol=1e-11, atol=1e-9):
                    raise AssertionError(f"Three-factor decomposition failed: {tech}/{snapshot}/{target}")
                records.append({
                    "tech": tech, "snapshot_year": str(snapshot),
                    "baseline": "ssp126", "target": target,
                    "baseline_unit_loss": base.R_MWh_MW_per_year,
                    "target_unit_loss": other.R_MWh_MW_per_year,
                    "gap_unit_loss": gap, "exposure_unit_loss": exposure,
                    "resource_unit_loss": resource, "rate_unit_loss": rate,
                })
    result = pd.DataFrame(records)
    mean = result.groupby(["tech", "baseline", "target"], as_index=False).mean(numeric_only=True)
    mean["snapshot_year"] = MEAN_PERIOD
    return pd.concat([result, mean], ignore_index=True)


def model_mean(tables: dict[str, pd.DataFrame], keys: list[str]) -> pd.DataFrame:
    """Require matching keys and four finite model values before averaging."""
    if set(tables) != set(MODELS):
        raise ValueError("The ensemble requires all four models")
    combined = pd.concat([frame.assign(model=model) for model, frame in tables.items()], ignore_index=True)
    if combined.duplicated(["model", *keys]).any():
        raise ValueError("Duplicate model-summary keys")
    grouped = combined.groupby(keys, sort=True)
    if not grouped.model.nunique().eq(len(MODELS)).all():
        raise ValueError("Model-summary keys are not aligned across all four models")
    numeric = combined.select_dtypes(include=np.number).columns.difference(keys)
    if not np.isfinite(combined[numeric].to_numpy()).all():
        raise ValueError("Non-finite model values cannot be averaged")
    mean = grouped[list(numeric)].mean()
    mean["n_models"] = grouped.model.nunique()
    if UNIT_COLUMN in combined:
        mean["model_min"] = grouped[UNIT_COLUMN].min()
        mean["model_max"] = grouped[UNIT_COLUMN].max()
    return mean.reset_index()


def trend_table(annual: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (tech, scenario), data in annual.groupby(["tech", "scenario"]):
        slope, intercept = np.polyfit(data.analysis_year, data[UNIT_COLUMN], 1)
        records.append({"tech": tech, "scenario": scenario,
                        "slope_mwh_per_mw_year_per_year": slope, "intercept": intercept,
                        "n_years": len(data), "start_year": int(data.analysis_year.min()),
                        "end_year": int(data.analysis_year.max())})
    return pd.DataFrame(records)


def save_figure(fig: plt.Figure, output: Path) -> None:
    fig.savefig(output, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_annual_trajectory(annual: pd.DataFrame, output: Path) -> None:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.3), sharey=False)
    for ax, tech in zip(axes, TECHS):
        for scenario in SSPS:
            data = annual[annual.tech.eq(tech) & annual.scenario.eq(scenario)].sort_values("analysis_year")
            x, y = data.analysis_year.to_numpy(), data[UNIT_COLUMN].to_numpy()
            if "model_min" in data:
                ax.fill_between(x, data.model_min.to_numpy(), data.model_max.to_numpy(),
                                color=SSP_COLOR[scenario], alpha=.16, linewidth=0, zorder=1)
            ax.plot(x, y, color=SSP_COLOR[scenario], label=SSP_LABEL[scenario], zorder=3)
            ax.plot(x, np.polyval(np.polyfit(x, y, 1), x), "--", color=SSP_COLOR[scenario], zorder=4)
        ax.set(title=TECH_LABEL[tech], xlabel="Year", ylabel=UNIT_LABEL)
        ax.grid(axis="y", alpha=.2)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", ncol=3)
    note = "Global net loss / installed capacity; dashed lines: least-squares fits."
    if "model_min" in annual:
        note += "\nEqual-weight mean of 4 models; shading: model minimum–maximum."
    fig.text(.5, .01, note, ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .07, 1, .91))
    save_figure(fig, output)


def plot_event_composition(events: pd.DataFrame, output: Path) -> None:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, tech in zip(axes, TECHS):
        data = events[events.tech.eq(tech)]
        for group, offset in (("All events", 0), ("Other events", 4)):
            bottom = np.zeros(3)
            for event in TECH_EVENTS[tech]:
                values = data[data.group.eq(group) & data.event.eq(event)].set_index("scenario")
                values = values.share_pct.reindex(SSPS, fill_value=0).to_numpy()
                ax.bar(np.arange(3) + offset, values, bottom=bottom,
                       color=EVENT_COLOR[event], edgecolor="white", linewidth=.4, zorder=3)
                bottom += values
        ax.set_xticks([0, 1, 2, 4, 5, 6], ["1-2.6", "2-4.5", "5-8.5"] * 2)
        for position, label in ((1, "All events"), (5, "Excluding low resource")):
            ax.text(position, -.15, label, transform=ax.get_xaxis_transform(),
                    ha="center", weight="bold")
        ax.set(ylabel="Positive event-loss pool (%)", ylim=(0, 100))
        ax.set_title(TECH_LABEL[tech], pad=40)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
        ax.legend(handles=[Patch(color=EVENT_COLOR[e], label=EVENT_LABEL[e]) for e in TECH_EVENTS[tech]],
                  loc="lower center", bbox_to_anchor=(.5, 1.015), fontsize=10,
                  ncol=int(np.ceil(len(TECH_EVENTS[tech]) / 2)))
    note = "2050s; positive global event net losses. Each bar totals 100%; event categories can overlap."
    if "n_models" in events:
        note += "\nShares are equal-weight means of the four model-specific shares."
    fig.text(.5, .015, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, .88))
    save_figure(fig, output)


def plot_waterfall(decomposition: pd.DataFrame, output: Path) -> None:
    configure_style()
    mean = decomposition[decomposition.snapshot_year.eq(MEAN_PERIOD)]
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.8))
    edges = [0.0]
    for ax, tech in zip(axes, TECHS):
        labels, positions = [], []
        for group_index, target in enumerate(SSPS[1:]):
            row = mean[mean.tech.eq(tech) & mean.target.eq(target)].iloc[0]
            start, level = group_index * 4, 0.0
            for offset, (value, color, label) in enumerate((
                (row.exposure_unit_loss, EXP_COLOR, "Exposure"),
                (row.intensity_unit_loss, INT_COLOR, "Intensity"),
            )):
                position = start + offset
                ax.bar(position, abs(value), bottom=min(level, level + value), width=.65, color=color, zorder=3)
                ax.annotate(f"{value:+.2f}", (position, max(level, level + value)),
                            xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8)
                level += value
                edges.append(level)
                ax.plot([position + .325, position + .675], [level, level], color="#8F969B", lw=.8)
                positions.append(position)
                labels.append(label)
            position, gap = start + 2, row.gap_unit_loss
            ax.bar(position, gap, width=.65, color=INK, zorder=3)
            ax.annotate(f"{gap:+.2f}", (position, gap), xytext=(0, 4 if gap >= 0 else -4),
                        textcoords="offset points", ha="center", va="bottom" if gap >= 0 else "top",
                        fontsize=8, fontweight="bold")
            positions.append(position)
            labels.append(f"Δ {SSP_LABEL[target]}")
        ax.set_xticks(positions, labels)
        ax.tick_params(axis="x", labelsize=8, length=0, pad=4)
        ax.axhline(0, color="#6D757B", lw=.8)
        ax.grid(axis="y", color="#E4E7E9", lw=.6)
        ax.set_axisbelow(True)
        ax.set_title(TECH_LABEL[tech], loc="left", fontweight="bold")
        ax.set_xlim(-.6, 6.6)
    pad = max(1.0, (max(edges) - min(edges)) * .18)
    for ax in axes:
        ax.set_ylim(min(edges) - pad, max(edges) + pad)
    axes[0].set_ylabel("Contribution to unit-loss gap\n(MWh MW$^{-1}$ yr$^{-1}$)")
    fig.text(.5, .025, "Target minus SSP1-2.6; mean of 2030s, 2040s and 2050s. Unit loss = Exposure × Intensity.",
             ha="center", fontsize=8)
    fig.subplots_adjust(left=.09, right=.985, bottom=.20, top=.86, wspace=.25)
    save_figure(fig, output)


def plot_waterfall_3f(decomposition: pd.DataFrame, output: Path) -> None:
    configure_style()
    mean = decomposition[decomposition.snapshot_year.eq(MEAN_PERIOD)]
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.8))
    edges = [0.0]
    for ax, tech in zip(axes, TECHS):
        labels, positions = [], []
        for group_index, target in enumerate(SSPS[1:]):
            row = mean[mean.tech.eq(tech) & mean.target.eq(target)].iloc[0]
            start, level = group_index * 5, 0.0
            for offset, (value, color, label) in enumerate((
                (row.exposure_unit_loss, EXP_COLOR, "Exposure"),
                (row.resource_unit_loss, RES_COLOR, "Event resource"),
                (row.rate_unit_loss, INT_COLOR, "Event loss rate"),
            )):
                position = start + offset
                ax.bar(position, abs(value), bottom=min(level, level + value), width=.65, color=color, zorder=3)
                ax.annotate(f"{value:+.2f}", (position, max(level, level + value)),
                            xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8)
                level += value
                edges.append(level)
                ax.plot([position + .325, position + .675], [level, level], color="#8F969B", lw=.8)
                positions.append(position)
                labels.append(label)
            position, gap = start + 3, row.gap_unit_loss
            ax.bar(position, gap, width=.65, color=INK, zorder=3)
            ax.annotate(f"{gap:+.2f}", (position, gap), xytext=(0, 4 if gap >= 0 else -4),
                        textcoords="offset points", ha="center", va="bottom" if gap >= 0 else "top",
                        fontsize=8, fontweight="bold")
            positions.append(position)
            labels.append(f"Δ {SSP_LABEL[target]}")
        ax.set_xticks(positions, labels)
        ax.tick_params(axis="x", labelsize=8, length=0, pad=4)
        ax.axhline(0, color="#6D757B", lw=.8)
        ax.grid(axis="y", color="#E4E7E9", lw=.6)
        ax.set_axisbelow(True)
        ax.set_title(TECH_LABEL[tech], loc="left", fontweight="bold")
        ax.set_xlim(-.6, 8.6)
    pad = max(1.0, (max(edges) - min(edges)) * .18)
    for ax in axes:
        ax.set_ylim(min(edges) - pad, max(edges) + pad)
    axes[0].set_ylabel("Contribution to unit-loss gap\n(MWh MW$^{-1}$ yr$^{-1}$)")
    fig.text(.5, .025, "Target minus SSP1-2.6; mean of 2030s, 2040s and 2050s. "
             "Unit loss = Exposure × Event resource × Event loss rate.",
             ha="center", fontsize=8)
    fig.subplots_adjust(left=.09, right=.985, bottom=.20, top=.86, wspace=.25)
    save_figure(fig, output)


def write_outputs(output: Path, tables: dict[str, pd.DataFrame], config: dict) -> None:
    (output / "csv").mkdir(parents=True, exist_ok=True)
    (output / "figures").mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(output / "csv" / f"{name}.csv", index=False)
    (output / "run_config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    plot_annual_trajectory(tables["global_annual_unit_capacity_loss"], output / "figures/global_annual_unit_capacity_loss.png")
    plot_event_composition(tables["global_event_composition_2050"], output / "figures/global_event_composition.png")
    plot_waterfall(tables["global_ssp_waterfall_decomposition"], output / "figures/global_ssp_waterfall_decomposition.png")
    plot_waterfall_3f(tables["global_ssp_waterfall_decomposition_3f"], output / "figures/global_ssp_waterfall_decomposition_3f.png")
    LOGGER.info("Saved: %s", output)


def load_all_single(
    loss_root: Path, patches: list[str],
) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Run the original model-by-model single-process pipeline."""
    LOGGER.info("Starting single-process pipeline")
    return {model: load_model(model, loss_root, patches) for model in MODELS}


def resolve_worker_count(requested: int | None, task_count: int) -> int:
    if requested is not None:
        if requested < 1:
            raise ValueError("--workers must be at least 1")
        return min(requested, task_count)
    slurm_cpus = os.environ.get("SLURM_CPUS_PER_TASK", "")
    if slurm_cpus.isdigit() and int(slurm_cpus) > 0:
        available = int(slurm_cpus)
    else:
        available = min(os.cpu_count() or 1, 4)
    return max(1, min(available, task_count))


def load_all_parallel(
    loss_root: Path, patches: list[str], workers: int | None,
) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Read independent model/SSP/technology units in separate processes."""
    tasks = [(model, scenario, tech, loss_root, patches)
             for model in MODELS for scenario in SSPS for tech in TECHS]
    max_workers = resolve_worker_count(workers, len(tasks))
    LOGGER.info("Starting multi-process pipeline with %d workers for %d tasks",
                max_workers, len(tasks))
    grouped: dict[str, list[list[pd.DataFrame]]] = {
        model: [[], [], []] for model in MODELS
    }
    context = mp.get_context("fork")
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=context) as pool:
        futures = {pool.submit(load_model_unit_worker, task): task for task in tasks}
        for future in as_completed(futures):
            model, scenario, tech, raw, inventory, coverage = future.result()
            grouped[model][0].append(raw)
            grouped[model][1].append(inventory)
            grouped[model][2].append(coverage)
            LOGGER.info("Completed %s / %s / %s", model, scenario, tech)
    return {
        model: tuple(pd.concat(parts, ignore_index=True) for parts in grouped[model])
        for model in MODELS
    }


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loss-root", type=Path, default=LOSS_ROOT)
    parser.add_argument("--patch-manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--execution-mode", choices=("parallel", "single"), default="parallel",
        help="Data-reading pipeline: parallel (default) or single process.",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Maximum worker processes in parallel mode; defaults to SLURM_CPUS_PER_TASK (or 4 outside SLURM).",
    )
    args = parser.parse_args()
    manifest = args.patch_manifest or args.loss_root.resolve().parents[1] / "inputs/patch_manifest.json"
    patches = read_patch_manifest(manifest)
    config = {
        "models": list(MODELS), "scenarios": list(SSPS), "technologies": list(TECHS),
        "snapshots": list(SNAPSHOTS), "years_per_snapshot": 10,
        "execution_mode": args.execution_mode, "workers_requested": args.workers,
        "analysis_scheme": "center-k", "analysis_k": 5,
        "loss_root": str(args.loss_root.resolve()), "patch_ids": patches,
        "patch_manifest": str(manifest.resolve()),
        "patch_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenario_aliases": {"ssp560": "ssp585"},
        "metric": "global annual net loss (MWh) / global snapshot installed capacity (MW)",
        "event_composition": "2050s global event net loss annualized over the ten-year snapshot / capacity; clip at zero, normalize within group",
        "decomposition": "R = E * I; E = sum(capacity * event hours) / capacity / year; I = loss / sum(capacity * event hours)",
        "decomposition_3f": "R = E * cf_ev * r_ev; cf_ev = event-window normal generation / sum(capacity * event hours); r_ev = loss / event-window normal generation",
        "waterfall_aggregation": "exact decomposition per model and snapshot, then equal-weight mean over snapshots and models",
        "ensemble": "equal-weight arithmetic mean of four model-specific metrics, shares and decomposition terms",
        "range": "pointwise minimum–maximum across four models; not a confidence interval",
        "figure_archetype": "quantitative grid", "figure_format": "png", "dpi": 600,
        "figure_sizes_inches": {"annual": [10.5, 4.3], "events": [13, 6],
                                "waterfall": [11.4, 4.8], "waterfall_3f": [13.2, 4.8]},
        "software": {"numpy": np.__version__, "pandas": pd.__version__,
                     "xarray": xr.__version__, "matplotlib": matplotlib.__version__},
    }
    keys = {
        "global_annual_unit_capacity_loss": ANNUAL_KEYS,
        "global_unit_capacity_metrics": ANNUAL_KEYS[:3],
        "global_event_composition_2050": ["scenario", "tech", "event", "group"],
        "global_ssp_waterfall_decomposition": ["tech", "snapshot_year", "baseline", "target"],
        "global_ssp_waterfall_decomposition_3f": ["tech", "snapshot_year", "baseline", "target"],
    }
    results: dict[str, dict[str, pd.DataFrame]] = {}
    if args.execution_mode == "single":
        config["workers_used"] = 1
        loaded = load_all_single(args.loss_root, patches)
    else:
        workers_used = resolve_worker_count(args.workers, len(MODELS) * len(SSPS) * len(TECHS))
        config["workers_used"] = workers_used
        loaded = load_all_parallel(args.loss_root, patches, workers_used)
    for model in MODELS:
        raw, inventory, coverage = loaded[model]
        annual = annual_trajectory(raw)
        metrics = capacity_metrics(annual)
        tables = {
            "global_annual_unit_capacity_loss": annual,
            "global_unit_capacity_metrics": metrics,
            "global_event_composition_2050": event_composition(raw, metrics),
            "global_ssp_waterfall_decomposition": unit_decomposition(metrics),
            "global_ssp_waterfall_decomposition_3f": unit_decomposition_3f(metrics),
            "global_annual_trends": trend_table(annual),
            "input_files": inventory, "patch_coverage": coverage,
        }
        results[model] = {name: tables[name] for name in keys}
        write_outputs(args.output_dir / model, tables, {**config, "model": model})
    mean = {name: model_mean({model: results[model][name] for model in MODELS}, group_keys)
            for name, group_keys in keys.items()}
    mean["global_annual_trends"] = trend_table(mean["global_annual_unit_capacity_loss"])
    write_outputs(args.output_dir / "ensemble_mean", mean, {**config, "model": "ensemble_mean"})


if __name__ == "__main__":
    main()
