#!/usr/bin/env python3
"""按全球 6×60° 经度带对比场站相对损失率轨迹，并分解带内极端事件。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from common import (
    BAND_COLOR,
    BAND_LABEL,
    BAND_MARKER,
    BAND_WIDTH,
    LON_BANDS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STATION_CSV,
    EVENT_COLOR,
    EVENT_LABEL,
    COMPARE_SSPS,
    SNAPSHOTS,
    SSP_LABEL,
    TECH_LABEL,
    TECHS,
    aggregate_band_rates,
    band_coverage_table,
    band_event_losses,
    configure_style,
    load_source,
    resolve_path,
    save_figure,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="CMIP6 模式名称。")
    parser.add_argument("--station-input-csv", type=Path, default=None, help="场站十年损失长表。")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录。")
    parser.add_argument("--techs", nargs="+", choices=TECHS, default=list(TECHS))
    parser.add_argument("--event-snapshot", type=int, choices=SNAPSHOTS, default=2050)
    return parser.parse_args()


def plot_band_trajectories(
    metrics: pd.DataFrame,
    *,
    tech: str,
    output_dir: Path,
) -> Path:
    """三个 SSP 面板内画各经度带的相对损失率轨迹。"""
    configure_style()
    subset = metrics[metrics["tech"].eq(tech)]
    bands = [band for band in LON_BANDS if (subset["lon_band"] == band).any()]
    fig, axes = plt.subplots(1, len(COMPARE_SSPS), figsize=(7.8, 2.9),
                             squeeze=False, sharex=True, sharey=False)
    for col, scenario in enumerate(COMPARE_SSPS):
        ax = axes[0, col]
        for band in bands:
            group = subset[
                subset["lon_band"].eq(band) & subset["scenario"].eq(scenario)
            ].set_index("snapshot_year").reindex(SNAPSHOTS)
            ax.plot(
                SNAPSHOTS, group["relative_loss_rate"],
                color=BAND_COLOR[band], marker=BAND_MARKER[band], lw=1.6, ms=3,
                label=BAND_LABEL[band],
            )
        ax.set_title(SSP_LABEL[scenario])
        ax.set_xticks(SNAPSHOTS, [str(y) for y in SNAPSHOTS])
        ax.grid(axis="y", alpha=0.2)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.tick_params(axis="y", labelleft=True)
        if col == 0:
            ax.set_ylabel("Relative loss rate (%)")
    handles = [Line2D([0], [0], color=BAND_COLOR[band], marker=BAND_MARKER[band], lw=1.6, ms=3,
                      label=BAND_LABEL[band]) for band in bands]
    fig.legend(handles=handles, loc="upper center", ncol=min(3, len(handles)),
               bbox_to_anchor=(0.5, 1.03))
    fig.suptitle(f"{TECH_LABEL[tech]}: relative loss-rate trajectories by longitude band",
                 fontsize=10, y=1.12)
    fig.subplots_adjust(left=0.08, right=0.99, bottom=0.18, top=0.78, wspace=0.16)
    return save_figure(fig, output_dir, f"trajectories_{tech}")


def plot_band_events(
    summary: pd.DataFrame,
    *,
    tech: str,
    snapshot: int,
    output_dir: Path,
) -> Path:
    """带×SSP 堆叠柱：损失加权事件构成（全事件与剔除 low_resource 残差）。"""
    configure_style()
    data = summary[
        summary["tech"].eq(tech) & summary["snapshot_year"].eq(snapshot)
    ].copy()
    bands = [band for band in LON_BANDS if (data["lon_band"] == band).any()]
    events = [event for event in EVENT_LABEL if event in set(data["event"])]
    residual_events = [event for event in events if event != "low_resource"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6), sharey=False)

    for ax, event_order, column, title in [
        (axes[0], events, "loss_weighted_share", "a  All event types"),
        (axes[1], residual_events, "loss_weighted_residual_share", "b  Other event types"),
    ]:
        positions = []
        labels = []
        bottoms = []
        for band_index, band in enumerate(bands):
            for scenario_index, scenario in enumerate(COMPARE_SSPS):
                positions.append(band_index * (len(COMPARE_SSPS) + 0.6) + scenario_index)
                labels.append(scenario.replace("ssp", ""))
                bottoms.append(0.0)
        bottoms = np.asarray(bottoms)
        for event in event_order:
            values = []
            for band in bands:
                for scenario in COMPARE_SSPS:
                    match = data[
                        data["lon_band"].eq(band)
                        & data["scenario"].eq(scenario)
                        & data["event"].eq(event)
                    ]
                    values.append(float(match[column].iloc[0]) if len(match) else 0.0)
            values_array = np.nan_to_num(np.asarray(values), nan=0.0)
            ax.bar(
                positions,
                values_array * 100.0,
                bottom=bottoms * 100.0,
                width=0.82,
                color=EVENT_COLOR.get(event, "0.65"),
                edgecolor="white",
                linewidth=0.25,
                label=EVENT_LABEL.get(event, event),
            )
            bottoms += values_array
        ax.set_xticks(positions, labels, rotation=45)
        for band_index, band in enumerate(bands):
            center = band_index * (len(COMPARE_SSPS) + 0.6) + (len(COMPARE_SSPS) - 1) / 2
            ax.text(center, -0.18, BAND_LABEL[band], transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontweight="bold")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Positive event-loss pool (%)")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.grid(axis="y", lw=0.35, alpha=0.35)
    handles = [Patch(facecolor=EVENT_COLOR[event], label=EVENT_LABEL[event]) for event in events]
    fig.legend(handles=handles, loc="upper center", ncol=min(5, len(handles)), bbox_to_anchor=(0.5, 0.965))
    fig.suptitle(
        f"{TECH_LABEL[tech]}: event-loss composition by longitude band ({snapshot}s)",
        fontsize=9.5, fontweight="bold", y=1.04,
    )
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.19, top=0.80, wspace=0.28)
    stem = f"fig_RQ4_lonband_event_composition_{tech}_{snapshot}"
    return save_figure(fig, output_dir, stem)


def main() -> None:
    args = parse_args()
    station_csv = args.station_input_csv or resolve_path(DEFAULT_STATION_CSV, args.model)
    if not station_csv.exists():
        raise SystemExit(f"未找到输入文件：{station_csv}")
    run_name = args.model if set(args.techs) == set(TECHS) else args.model + "_" + "_".join(args.techs)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / run_name)
    csv_dir = output_dir / "csv"
    figure_dir = output_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    source = load_source(station_csv, args.model)
    metrics = aggregate_band_rates(source)
    events = band_event_losses(source)
    coverage = band_coverage_table(metrics)
    config = {key: str(value) if isinstance(value, Path) else value
              for key, value in vars(args).items()}
    config["input_csv"] = str(station_csv.resolve())
    config["input_sha256"] = hashlib.sha256(station_csv.read_bytes()).hexdigest()
    config["band_width_deg"] = BAND_WIDTH
    config["lon_bands"] = list(LON_BANDS)
    config["aggregation"] = "100 * sum(net_loss) / sum(normal_generation), energy-weighted within band"
    (output_dir / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    coverage.to_csv(csv_dir / "band_coverage.csv", index=False)
    metrics.to_csv(csv_dir / "RQ4_lonband_metric_decade.csv", index=False)
    events.to_csv(csv_dir / "RQ4_lonband_event_decade.csv", index=False)

    for tech in args.techs:
        tech_metrics = metrics[metrics["tech"].eq(tech)]
        tech_events = events[events["tech"].eq(tech)]
        if tech_metrics.empty:
            print(f"跳过 {tech}：没有可用场站。")
            continue
        plot_band_trajectories(tech_metrics, tech=tech, output_dir=figure_dir)
        plot_band_events(tech_events, tech=tech, snapshot=args.event_snapshot, output_dir=figure_dir)
        n_bands = tech_metrics["lon_band"].nunique()
        print(f"完成 {tech}：{n_bands} 个经度带。")

    print(f"已保存 RQ4 结果：{output_dir}")


if __name__ == "__main__":
    main()
