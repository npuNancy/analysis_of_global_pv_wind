#!/usr/bin/env python3
"""图 3：各事件的非加和损失率诊断。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt

from common import (
    EVENT_COLOR, EVENT_LABEL, SSP_LABEL, SSPS, TECH_LABEL, TECHS,
    add_common_args, configure_style, global_annual, load_region, output_dir,
    panel_tag, save_figure, write_source,
)


def build_data(model: str):
    annual = global_annual(load_region(model))
    annual["loss_rate_pct"] = annual["net_loss_mwh"] / annual["normal_all_mwh"] * 100.0
    return (
        annual.groupby(["scenario", "tech", "snapshot_year", "event"], as_index=False)
        .agg(
            loss_rate_pct_mean=("loss_rate_pct", "mean"),
            loss_rate_pct_min=("loss_rate_pct", "min"),
            loss_rate_pct_max=("loss_rate_pct", "max"),
        )
    )


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    data = build_data(args.model)
    write_source(data, out, "fig03_event_mechanism.csv")

    fig, axes = plt.subplots(2, 3, figsize=(7.4, 5.1), sharex=True, sharey="row")
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.18, top=0.86, hspace=0.4, wspace=0.16)
    handles_by_tech = {}
    for row, tech in enumerate(TECHS):
        events = data[data["tech"] == tech]["event"].drop_duplicates().tolist()
        events = sorted(events, key=lambda event: (event != "all", event != "low_resource", event))
        for col, scenario in enumerate(SSPS):
            ax = axes[row, col]
            for event in events:
                sub = data[
                    (data["tech"] == tech) & (data["scenario"] == scenario) & (data["event"] == event)
                ].sort_values("snapshot_year")
                line, = ax.plot(
                    sub["snapshot_year"], sub["loss_rate_pct_mean"],
                    "-o" if event in {"all", "low_resource"} else "-",
                    color=EVENT_COLOR.get(event, "0.6"),
                    lw=2.0 if event == "all" else (1.6 if event == "low_resource" else 0.9),
                    ms=3.2, alpha=1.0 if event in {"all", "low_resource"} else 0.8,
                    label=EVENT_LABEL.get(event, event),
                )
                handles_by_tech.setdefault(tech, {})[event] = line
            ax.set_title(f"{TECH_LABEL[tech]} · {SSP_LABEL[scenario]}")
            ax.set_xticks([2030, 2040, 2050], ["2030s", "2040s", "2050s"])
            ax.grid(axis="y", lw=0.35, alpha=0.4)
            if col == 0:
                ax.set_ylabel("事件净损失率（%）")
            panel_tag(ax, chr(ord("a") + row * 3 + col))
    event_order = [
        "all", "low_resource", "high_temp", "high_wind", "hot_humid",
        "icing", "rainstorm", "cold_highwind", "freezing_rain", "high_humidity",
    ]
    legend_y = {"wind": 0.52, "solar": 0.055}
    for tech in TECHS:
        tech_handles = handles_by_tech[tech]
        ordered = [event for event in event_order if event in tech_handles]
        fig.legend(
            [tech_handles[event] for event in ordered],
            [EVENT_LABEL[event] for event in ordered],
            title=f"{TECH_LABEL[tech]}事件",
            loc="center",
            ncol=len(ordered),
            bbox_to_anchor=(0.5, legend_y[tech]),
        )
    fig.suptitle(f"极端事件类型与净出力损失率演化（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.005,
        "单事件曲线存在事件重叠，彼此不可直接加和；本图用于识别主导事件，严格贡献分配仍需逐时 Shapley/重叠分摊。",
        ha="center", fontsize=6.1, color="0.4",
    )
    save_figure(fig, out, "fig03_event_mechanism")


if __name__ == "__main__":
    main()
