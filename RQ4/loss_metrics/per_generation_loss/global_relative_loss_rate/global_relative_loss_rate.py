"""Global energy-weighted annual loss rates and 2050s event-loss composition."""

from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relative_loss_rate_trajectory_clustering"))
from common import EVENT_COLOR, EVENT_LABEL, SSP_LABEL


def main():
    out = Path(__file__).resolve().parent / "outputs"
    for folder in ("figures", "csv"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    base = ROOT / "relative_loss_rate_trajectory_clustering/outputs/CANESM5/csv"
    source = pd.read_csv(base / "RQ4_country_metric_annual.csv")
    source = source[source.event.eq("all")]
    keys = ["scenario", "tech", "snapshot_year", "analysis_year"]
    annual = source.groupby(keys, as_index=False).agg(
        net_loss_mwh=("net_loss_mwh", "sum"),
        normal_all_mwh=("normal_all_mwh", "sum"),
        n_regions=("region", "nunique"),
    )
    annual["loss_rate_pct"] = 100 * annual.net_loss_mwh / annual.normal_all_mwh
    annual.to_csv(out / "csv/global_annual_trajectory.csv", index=False)
    # Save the previous calculation alongside the corrected result for auditing.
    old = source.assign(weighted=source.relative_loss_rate * source.normal_generation_mwh)
    old = old.groupby(keys)[["weighted", "normal_generation_mwh"]].sum()
    old["previous_rate_pct"] = old.weighted / old.normal_generation_mwh
    reference = pd.read_csv(
        ROOT.parent / "RQ3/outputs/CANESM5/csv/RQ3_generation_loss_rate_global_annual_evolution.csv"
    )
    comparison = annual.merge(old[["previous_rate_pct"]].reset_index(), on=keys)
    comparison = comparison.merge(
        reference[keys + ["loss_rate_pct"]], on=keys, suffixes=("", "_rq3"), validate="one_to_one"
    )
    comparison["difference_pp"] = comparison.loss_rate_pct - comparison.loss_rate_pct_rq3
    comparison.to_csv(out / "csv/annual_comparison_with_RQ3.csv", index=False)
    assert len(comparison) == len(annual) == 180
    assert np.allclose(comparison.loss_rate_pct, comparison.loss_rate_pct_rq3)

    colors = ["#234a7c", "#e5a236", "#a52222"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, tech in zip(axes, ["wind", "solar"]):
        for scenario, color in zip(SSP_LABEL, colors):
            data = annual[(annual.tech == tech) & (annual.scenario == scenario)].sort_values("analysis_year")
            x, y = data.analysis_year.to_numpy(), data.loss_rate_pct.to_numpy()
            ax.plot(x, y, color=color, label=SSP_LABEL[scenario])
            ax.plot(x, np.polyval(np.polyfit(x, y, 1), x), "--", color=color)
        ax.set(title=tech.capitalize(), xlabel="Year", ylabel="Relative loss rate (%)")
        ax.grid(axis="y", alpha=0.2)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", ncol=3, frameon=False)
    fig.text(
        0.5,
        0.01,
        "Global net loss / global full-year normal generation; dashed lines: least-squares linear fits.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.92))
    fig.savefig(out / "figures/global_annual_trajectory.png", dpi=250)
    plt.close(fig)

    events = pd.read_csv(base / "RQ4_country_event_decade.csv")
    events = events[events.snapshot_year.eq(2050)]
    # Use all countries, including those without a complete clustering trajectory.
    events = events.groupby(["tech", "scenario", "event"], as_index=False).positive_net_loss_mwh_per_year.sum()
    shares = []
    for group, subset in [("All events", events), ("Other events", events[events.event.ne("low_resource")])]:
        subset = subset.copy()
        total = subset.groupby(["tech", "scenario"]).positive_net_loss_mwh_per_year.transform("sum")
        subset["share_pct"] = 100 * subset.positive_net_loss_mwh_per_year / total
        subset["group"] = group
        shares.append(subset)
    shares = pd.concat(shares, ignore_index=True)
    assert np.allclose(shares.groupby(["tech", "scenario", "group"]).share_pct.sum(), 100)
    shares.to_csv(out / "csv/global_event_composition_2050.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, tech in zip(axes, ["wind", "solar"]):
        data = shares[shares.tech.eq(tech)]
        for group, offset in [("All events", 0), ("Other events", 4)]:
            bottom = np.zeros(3)
            for event in EVENT_LABEL:
                values = (
                    data[(data.group == group) & (data.event == event)]
                    .set_index("scenario")
                    .share_pct.reindex(SSP_LABEL, fill_value=0)
                    .to_numpy()
                )
                ax.bar(
                    np.arange(3) + offset,
                    values,
                    bottom=bottom,
                    color=EVENT_COLOR[event],
                    edgecolor="white",
                    linewidth=0.4,
                )
                bottom += values
        ax.set_xticks([0, 1, 2, 4, 5, 6], ["1-2.6", "2-4.5", "5-8.5"] * 2)
        ax.text(1, -0.15, "All events", transform=ax.get_xaxis_transform(), ha="center", weight="bold")
        ax.text(5, -0.15, "Excluding low resource", transform=ax.get_xaxis_transform(), ha="center", weight="bold")
        ax.set(ylabel="Positive event-loss pool (%)", ylim=(0, 100))
        ax.set_title(tech.capitalize(), pad=40)
        ax.grid(axis="y", alpha=0.2)
    for ax, tech in zip(axes, ["wind", "solar"]):
        present = [e for e in EVENT_LABEL if ((shares.tech == tech) & shares.event.eq(e)).any()]
        ax.legend(
            handles=[Patch(color=EVENT_COLOR[e], label=EVENT_LABEL[e]) for e in present],
            loc="lower center",
            bbox_to_anchor=(0.5, 1.015),
            fontsize=10,
            frameon=False,
            ncol=max(1, int(np.ceil(len(present) / 2))),
        )
    fig.text(
        0.5,
        0.015,
        "2050s; sum of positive country-event losses. Each bar totals 100%; event categories can overlap.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.88))
    fig.savefig(out / "figures/global_event_composition.png", dpi=250)
    plt.close(fig)

    # SSP mechanism decomposition for the global net loss rate.  The two
    # factors are defined so their product is exactly the rate:
    # R = (event hours / normal generation) * (net loss / event hour).
    freq = pd.read_csv(
        ROOT / "latitude_band_relative_loss_rate/outputs/CANESM5/csv/further/further_frequency_intensity.csv"
    )
    # Pool the three available snapshot decades (2030s, 2040s and 2050s).
    mech = freq.groupby(["tech", "scenario"], as_index=False).agg(
        event_hours=("event_hours_decade", "sum"),
        net_loss=("net_loss_mwh_decade", "sum"),
    )
    normal = source.groupby(["tech", "scenario"], as_index=False).agg(
        normal_generation=("normal_all_mwh", "sum"),
        net_loss=("net_loss_mwh", "sum"),
    )
    # Use the net all-event loss as the numerator so the decomposition matches
    # the loss-rate trajectory; event-hour pools are used only as an exposure
    # scale and can contain overlapping event categories.
    mech = mech.drop(columns="net_loss").merge(normal, on=["tech", "scenario"], validate="one_to_one")
    mech["exposure_index_h_per_mwh"] = mech.event_hours / mech.normal_generation
    mech["intensity_mwh_per_event_h"] = mech.net_loss / mech.event_hours
    mech["loss_rate_pct"] = 100 * mech.net_loss / mech.normal_generation
    mech.to_csv(out / "csv/global_ssp_mechanism_factors_all_snapshots.csv", index=False)

    records = []
    for tech in ["wind", "solar"]:
        base_row = mech[(mech.tech == tech) & (mech.scenario == "ssp126")].iloc[0]
        for target in ["ssp245", "ssp585"]:
            target_row = mech[(mech.tech == tech) & (mech.scenario == target)].iloc[0]
            eb, ib, rb = base_row.exposure_index_h_per_mwh, base_row.intensity_mwh_per_event_h, base_row.loss_rate_pct
            et, it, rt = target_row.exposure_index_h_per_mwh, target_row.intensity_mwh_per_event_h, target_row.loss_rate_pct
            e_term = 100 * (et - eb) * (it + ib) / 2
            i_term = 100 * (it - ib) * (et + eb) / 2
            records.append({"tech": tech, "baseline": "ssp126", "target": target,
                            "baseline_rate_pct": rb, "exposure_contribution_pp": e_term,
                            "intensity_contribution_pp": i_term, "target_rate_pct": rt,
                            "identity_error_pp": rb + e_term + i_term - rt})
    decomp = pd.DataFrame(records)
    decomp.to_csv(out / "csv/global_ssp_waterfall_decomposition_all_snapshots.csv", index=False)
    assert decomp.identity_error_pp.abs().max() < 1e-8

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    for ax, tech in zip(axes, ["wind", "solar"]):
        x = 0
        for _, row in decomp[decomp.tech.eq(tech)].iterrows():
            vals = [row.baseline_rate_pct, row.exposure_contribution_pp,
                    row.intensity_contribution_pp, row.target_rate_pct]
            labels = ["SSP126", "Exposure", "Intensity", row.target.upper()]
            level = vals[0]
            ax.bar(x, level, color="#929EAA", width=.72); ax.text(x, level+.04, f"{level:.2f}", ha="center", fontsize=8)
            for j, (value, label, color) in enumerate(zip(vals[1:3], labels[1:3], ["#9EC3D3", "#C99581"]), 1):
                ax.bar(x+j, abs(value), bottom=min(level, level+value), color=color, width=.72)
                ax.text(x+j, max(level, level+value)+(0.04 if value >= 0 else -0.04), f"{value:+.2f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=8)
                level += value
            ax.bar(x+3, vals[3], color="#30363C", width=.72); ax.text(x+3, vals[3]+.04, f"{vals[3]:.2f}", ha="center", fontsize=8, fontweight="bold")
            x += 5
        ax.set_xticks([0, 1, 2, 3, 5, 6, 7, 8], ["SSP126", "Exposure", "Intensity", "SSP245", "SSP126", "Exposure", "Intensity", "SSP585"])
        ax.tick_params(axis="x", labelsize=8, pad=5)
        ax.set_title(tech.capitalize()); ax.set_ylabel("Unit-generation loss rate (%)"); ax.axhline(0, color="#666", lw=.8); ax.grid(axis="y", alpha=.2)
    fig.text(.5, .015, "Pooled 2030s–2050s; SSP126 is the baseline. Exposure = event-hours / normal generation; intensity = net loss / event-hour pool.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .06, 1, .96))
    fig.savefig(out / "figures/global_ssp_waterfall_decomposition.png", dpi=250)
    plt.close(fig)
    print(
        f"Validated {len(comparison)} annual values; max RQ3 difference = {comparison.difference_pp.abs().max():.3g} pp"
    )
    print(
        comparison[(comparison.analysis_year == 2030) & (comparison.scenario == "ssp126")][
            ["tech", "previous_rate_pct", "loss_rate_pct"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
