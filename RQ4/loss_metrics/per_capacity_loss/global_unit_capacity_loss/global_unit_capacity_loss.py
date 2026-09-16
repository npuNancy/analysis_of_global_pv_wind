"""Global unit-capacity loss trajectories, event composition and SSP decomposition."""

from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "CANESM5"
SSPS = ("ssp126", "ssp245", "ssp585")
TECHS = ("wind", "solar")
SNAPSHOTS = (2030, 2040, 2050)
YEARS_PER_SNAPSHOT = 10.0
STATION_CSV = PROJECT_ROOT / (
    "data/generation_loss_outputs/generation_loss/{model}/aggregate/"
    "generation_loss_decade_station.csv"
)
REGION_CSV = PROJECT_ROOT / (
    "data/generation_loss_outputs/generation_loss/{model}/aggregate/"
    "generation_loss_region.csv"
)
OUTPUT_DIR = PACKAGE_ROOT / "global_unit_capacity_loss" / "outputs"
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
CAP_COLOR = "#929EAA"
EXP_COLOR = "#9EC3D3"
INT_COLOR = "#C99581"
INK = "#30363C"


def configure_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "legend.frameon": False,
        "pdf.fonttype": 42, "svg.fonttype": "none",
    })


def read_filtered(path: Path, model: str, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    data = pd.read_csv(path, usecols=columns)
    data = data[
        data["model"].eq(model) & data["scenario"].isin(SSPS)
        & data["tech"].isin(TECHS) & data["snapshot_year"].isin(SNAPSHOTS)
        & data["analysis_scheme"].eq("center-k") & data["analysis_k"].eq(5)
    ].copy()
    if data.empty:
        raise ValueError(f"{path} 中没有匹配 model、SSP、技术和 center-k=5 的数据")
    if data["source"].nunique() != 1:
        raise ValueError(f"{path} 包含多个数据源，不能混合聚合")
    return data


def apply_wind_energy_correction(data: pd.DataFrame) -> pd.DataFrame:
    """Apply the repository's temporary upstream wind-energy correction."""
    data = data.copy()
    wind = data["tech"].eq("wind")
    for column in ("net_generation_loss_mwh", "normal_all_generation_mwh"):
        if column in data:
            data.loc[wind, column] *= 0.1
    return data


def load_station(model: str) -> pd.DataFrame:
    columns = [
        "model", "scenario", "source", "region", "tech", "snapshot_year",
        "analysis_scheme", "analysis_k", "station_id", "event", "capacity_mw",
        "net_generation_loss_mwh", "normal_all_generation_mwh", "event_duration_hours",
    ]
    data = apply_wind_energy_correction(
        read_filtered(Path(str(STATION_CSV).format(model=model)), model, columns)
    )
    keys = ["station_id", "scenario", "tech", "snapshot_year", "event"]
    if data.duplicated(keys).any():
        raise ValueError("场站十年输入存在重复键")
    return data


def load_region(model: str) -> pd.DataFrame:
    columns = [
        "model", "scenario", "source", "region", "tech", "snapshot_year",
        "analysis_scheme", "analysis_k", "analysis_year", "event", "capacity_mw",
        "net_generation_loss_mwh", "normal_all_generation_mwh",
    ]
    data = apply_wind_energy_correction(
        read_filtered(Path(str(REGION_CSV).format(model=model)), model, columns)
    )
    keys = ["region", "scenario", "tech", "snapshot_year", "analysis_year", "event"]
    if data.duplicated(keys).any():
        raise ValueError("国家年度输入存在重复键")
    return data


def capacity_metrics(station: pd.DataFrame) -> pd.DataFrame:
    """Compute C, E, I and R from station-level decade exposure accounting."""
    all_events = station[station["event"].eq("all")]
    rows = []
    for keys, group in all_events.groupby(["scenario", "tech", "snapshot_year"]):
        scenario, tech, snapshot = keys
        capacity = group["capacity_mw"].sum()
        loss = group["net_generation_loss_mwh"].sum() / YEARS_PER_SNAPSHOT
        exposure = (group["capacity_mw"] * group["event_duration_hours"]).sum() / YEARS_PER_SNAPSHOT
        if not np.isfinite([capacity, loss, exposure]).all() or capacity <= 0 or exposure <= 0:
            raise ValueError(f"无效的容量/损失/暴露：{keys}")
        E = exposure / capacity
        I = loss / exposure
        R = loss / capacity
        if not np.isclose(capacity * E * I, loss, rtol=1e-12, atol=1e-8):
            raise AssertionError(f"C×E×I 恒等式未闭合：{keys}")
        rows.append({
            "scenario": scenario, "tech": tech, "snapshot_year": snapshot,
            "C_MW": capacity, "H_MWh_capacity_per_year": exposure,
            "E_h": E, "I": I, "R_MWh_MW_per_year": R,
            "L_MWh_per_year": loss,
        })
    return pd.DataFrame(rows).sort_values(["tech", "scenario", "snapshot_year"])


def annual_trajectory(region: pd.DataFrame) -> pd.DataFrame:
    selected = region[region["event"].eq("all")]
    annual = selected.groupby(
        ["scenario", "tech", "snapshot_year", "analysis_year"], as_index=False
    ).agg(
        net_loss_mwh=("net_generation_loss_mwh", "sum"),
        capacity_mw=("capacity_mw", "sum"),
        n_regions=("region", "nunique"),
    )
    annual["unit_capacity_loss_mwh_per_mw_year"] = np.where(
        annual["capacity_mw"].gt(0), annual["net_loss_mwh"] / annual["capacity_mw"], np.nan
    )
    return annual


def event_composition(station: pd.DataFrame) -> pd.DataFrame:
    events = station[station["event"].ne("all") & station["snapshot_year"].eq(2050)]
    events = events.groupby(["tech", "scenario", "event"], as_index=False).agg(
        net_loss_mwh_decade=("net_generation_loss_mwh", "sum")
    )
    events["positive_net_loss_mwh_decade"] = events["net_loss_mwh_decade"].clip(lower=0)
    events["share_pct"] = events["positive_net_loss_mwh_decade"] / events.groupby(
        ["tech", "scenario"]
    )["positive_net_loss_mwh_decade"].transform("sum") * 100
    return events


def nested_decomposition(metrics: pd.DataFrame) -> pd.DataFrame:
    """Decompose target-minus-SSP126 loss into Capacity, Exposure and Intensity."""
    records = []
    for tech in TECHS:
        for snapshot in SNAPSHOTS:
            base = metrics.query("tech == @tech and scenario == 'ssp126' and snapshot_year == @snapshot").iloc[0]
            for target in ("ssp245", "ssp585"):
                target_row = metrics.query("tech == @tech and scenario == @target and snapshot_year == @snapshot").iloc[0]
                C_N, C_S = base.C_MW, target_row.C_MW
                E_N, E_S = base.E_h, target_row.E_h
                I_N, I_S = base.I, target_row.I
                C_ref = (C_S + C_N) / 2
                phi_C = (C_S - C_N) * (target_row.R_MWh_MW_per_year + base.R_MWh_MW_per_year) / 2
                phi_E = C_ref * (E_S - E_N) * (I_S + I_N) / 2
                phi_I = C_ref * (I_S - I_N) * (E_S + E_N) / 2
                gap = target_row.L_MWh_per_year - base.L_MWh_per_year
                if not np.isclose(phi_C + phi_E + phi_I, gap, rtol=1e-11, atol=1e-6):
                    raise AssertionError(f"分解未闭合：{tech}/{snapshot}/{target}")
                if not np.isclose(phi_E + phi_I, C_ref * (target_row.R_MWh_MW_per_year - base.R_MWh_MW_per_year), rtol=1e-11, atol=1e-6):
                    raise AssertionError(f"Risk 分解未闭合：{tech}/{snapshot}/{target}")
                records.append({
                    "tech": tech, "snapshot_year": snapshot,
                    "baseline": "ssp126", "target": target,
                    "gap_TWh_per_year": gap / 1e6,
                    "capacity_TWh_per_year": phi_C / 1e6,
                    "exposure_TWh_per_year": phi_E / 1e6,
                    "intensity_TWh_per_year": phi_I / 1e6,
                })
    result = pd.DataFrame(records)
    mean = result.groupby(["tech", "baseline", "target"], as_index=False).mean(numeric_only=True)
    mean["snapshot_year"] = "mean_2030s_2050s"
    return pd.concat([result, mean], ignore_index=True)


def plot_annual_trajectory(annual: pd.DataFrame, output: Path) -> None:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.3), sharey=False)
    for ax, tech in zip(axes, TECHS):
        for scenario in SSPS:
            data = annual.query("tech == @tech and scenario == @scenario").sort_values("analysis_year")
            x = data["analysis_year"].to_numpy()
            y = data["unit_capacity_loss_mwh_per_mw_year"].to_numpy()
            ax.plot(x, y, color=SSP_COLOR[scenario], label=SSP_LABEL[scenario])
            if len(x) > 1:
                ax.plot(x, np.polyval(np.polyfit(x, y, 1), x), "--", color=SSP_COLOR[scenario])
        ax.set(title=TECH_LABEL[tech], xlabel="Year", ylabel="Unit-capacity loss (MWh MW$^{-1}$ yr$^{-1}$)")
        ax.grid(axis="y", alpha=0.2)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", ncol=3, frameon=False)
    fig.text(.5, .01, "Global annual net loss divided by global installed capacity; dashed lines are least-squares fits.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .04, 1, .91))
    fig.savefig(output, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_event_composition(events: pd.DataFrame, output: Path) -> None:
    configure_style()
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    for ax, tech in zip(axes, TECHS):
        data = events[events.tech.eq(tech)]
        for index, scenario in enumerate(SSPS):
            subset = data[data.scenario.eq(scenario)].set_index("event")
            bottom = 0.0
            for event in EVENT_LABEL:
                value = float(subset.loc[event, "share_pct"]) if event in subset.index else 0.0
                ax.bar(index, value, bottom=bottom, color=EVENT_COLOR[event], edgecolor="white", linewidth=.35)
                bottom += value
        ax.set_xticks(range(3), [SSP_LABEL[s] for s in SSPS])
        ax.set_ylim(0, 100)
        ax.set_ylabel("Positive event-loss pool (%)")
        ax.set_title(TECH_LABEL[tech])
        ax.grid(axis="y", alpha=.2)
    handles = [Patch(color=EVENT_COLOR[e], label=EVENT_LABEL[e]) for e in EVENT_LABEL]
    fig.legend(handles=handles, loc="upper center", ncol=5, bbox_to_anchor=(.5, 1.04), frameon=False)
    fig.suptitle("2050s event composition of global unit-capacity loss", y=1.10, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, .88))
    fig.savefig(output, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def draw_waterfall(ax: plt.Axes, tech: str, mean_terms: pd.DataFrame) -> list[float]:
    labels = []
    edges = [0.0]
    for group_index, target in enumerate(("ssp245", "ssp585")):
        row = mean_terms.query("tech == @tech and target == @target").iloc[0]
        values = [row.capacity_TWh_per_year, row.exposure_TWh_per_year, row.intensity_TWh_per_year]
        start = group_index * 5
        level = 0.0
        for offset, (value, color, label) in enumerate(zip(values, [CAP_COLOR, EXP_COLOR, INT_COLOR], ["Capacity", "Exposure", "Intensity"])):
            xpos = start + offset
            ax.bar(xpos, abs(value), bottom=min(level, level + value), width=.65, color=color, zorder=3)
            top = max(level, level + value)
            ax.text(xpos, level + value / 2 if abs(value) > 5 else top + 1.4, f"{value:+.2f}", ha="center", va="center" if abs(value) > 5 else "bottom", fontsize=8)
            level += value
            ax.plot([xpos + .325, xpos + .675], [level, level], color="#8F969B", lw=.8)
            labels.append(label)
        gap = row.gap_TWh_per_year
        xpos = start + 3
        ax.bar(xpos, gap, .65, color=INK, zorder=3)
        ax.text(xpos, gap + (1.4 if gap >= 0 else -1.4), f"{gap:+.2f}", ha="center", va="bottom" if gap >= 0 else "top", fontsize=8, fontweight="bold")
        labels.append(f"Δ {SSP_LABEL[target]}")
        edges.extend([row.capacity_TWh_per_year, row.capacity_TWh_per_year + row.exposure_TWh_per_year, gap])
        trans = ax.get_xaxis_transform()
        ax.plot([start + .65, start + .65, start + 2.35, start + 2.35], [-.14, -.19, -.19, -.14], color="#555C62", lw=.8, transform=trans, clip_on=False)
        ax.text(start + 1.5, -.235, "Risk", ha="center", va="top", transform=trans, fontsize=9)
    ax.axhline(0, color="#6D757B", lw=.8)
    ax.set_xticks([0, 1, 2, 3, 5, 6, 7, 8], labels)
    ax.tick_params(axis="x", labelsize=8, length=0, pad=4)
    ax.grid(axis="y", color="#E4E7E9", lw=.6)
    ax.set_axisbelow(True)
    ax.set_title(TECH_LABEL[tech], loc="left", fontweight="bold")
    ax.set_xlim(-.6, 8.6)
    return edges


def plot_waterfall(decomposition: pd.DataFrame, output: Path) -> None:
    configure_style()
    mean_terms = decomposition[decomposition["snapshot_year"].eq("mean_2030s_2050s")]
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.8))
    edges = []
    for ax, tech in zip(axes, TECHS):
        edges.extend(draw_waterfall(ax, tech, mean_terms))
        if tech == "wind":
            ax.set_ylabel("Contribution to loss gap (TWh yr$^{-1}$)")
    span = max(edges) - min(edges)
    pad = max(2.0, span * .14)
    y_lo = np.floor((min(edges) - pad) / 5) * 5
    y_hi = np.ceil((max(edges) + pad) / 5) * 5
    for ax in axes:
        ax.set_ylim(y_lo, y_hi)
        ax.set_yticks(np.arange(np.floor(y_lo / 10) * 10, y_hi + 1, 10))
    fig.subplots_adjust(left=.08, right=.985, bottom=.22, top=.86, wspace=.25)
    fig.savefig(output, dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main(model: str = DEFAULT_MODEL) -> None:
    output = OUTPUT_DIR / model
    (output / "figures").mkdir(parents=True, exist_ok=True)
    (output / "csv").mkdir(parents=True, exist_ok=True)
    station = load_station(model)
    region = load_region(model)
    metrics = capacity_metrics(station)
    annual = annual_trajectory(region)
    events = event_composition(station)
    decomposition = nested_decomposition(metrics)
    metrics.to_csv(output / "csv/global_unit_capacity_metrics.csv", index=False)
    annual.to_csv(output / "csv/global_annual_unit_capacity_loss.csv", index=False)
    events.to_csv(output / "csv/global_event_composition_2050.csv", index=False)
    decomposition.to_csv(output / "csv/global_ssp_waterfall_decomposition.csv", index=False)
    station_path = Path(str(STATION_CSV).format(model=model))
    region_path = Path(str(REGION_CSV).format(model=model))
    (output / "run_config.json").write_text(pd.Series({
        "model": model,
        "station_input_csv": str(station_path.resolve()),
        "region_input_csv": str(region_path.resolve()),
        "station_input_sha256": hashlib.sha256(station_path.read_bytes()).hexdigest(),
        "years_per_snapshot": YEARS_PER_SNAPSHOT,
        "metric": "net loss / installed capacity / year",
        "decomposition": "Loss = C × E × I; target-minus-SSP126 nested decomposition",
    }).to_json(), encoding="utf-8")
    plot_annual_trajectory(annual, output / "figures/global_annual_unit_capacity_loss.png")
    plot_event_composition(events, output / "figures/global_event_composition.png")
    plot_waterfall(decomposition, output / "figures/global_ssp_waterfall_decomposition.png")
    print(f"已保存单位装机损失全球结果：{output}")


if __name__ == "__main__":
    main()
