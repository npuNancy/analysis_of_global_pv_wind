#!/usr/bin/env python3
"""图 4：2050s 风电情景收敛的覆盖与权重敏感性。"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    SSP_COLOR, SSP_LABEL, SSPS, add_common_args, configure_style, load_region,
    output_dir, panel_tag, save_figure, write_source,
)


ESTIMATOR_LABEL = {
    "raw": "实际覆盖",
    "common_current": "共同国家\n当期权重",
    "common_fixed": "共同国家\n固定权重",
}


def build_data(model: str) -> pd.DataFrame:
    region = load_region(model)
    data = region[(region["event"] == "all") & (region["tech"] == "wind")].copy()
    country = (
        data.groupby(["scenario", "snapshot_year", "analysis_year", "region"], as_index=False)
        .agg(loss_mwh=("net_generation_loss_mwh", "sum"), normal_mwh=("normal_all_generation_mwh", "sum"))
    )
    countries = None
    for scenario in SSPS:
        current = set(country[(country["scenario"] == scenario) & (country["snapshot_year"] == 2050)]["region"])
        countries = current if countries is None else countries & current
    common = sorted(countries or [])
    if not common:
        raise SystemExit("2050s 三情景没有共同国家，无法进行平衡面板分析。")

    reference = country[(country["snapshot_year"] == 2030) & country["region"].isin(common)]
    weights = reference.groupby("region")["normal_mwh"].mean()
    weights = weights / weights.sum()

    annual_rows = []
    for scenario in SSPS:
        subset = country[(country["scenario"] == scenario) & (country["snapshot_year"] == 2050)]
        for year, annual in subset.groupby("analysis_year"):
            raw = annual["loss_mwh"].sum() / annual["normal_mwh"].sum() * 100.0
            balanced = annual[annual["region"].isin(common)].set_index("region")
            common_current = balanced["loss_mwh"].sum() / balanced["normal_mwh"].sum() * 100.0
            country_rate = balanced["loss_mwh"] / balanced["normal_mwh"] * 100.0
            common_fixed = (country_rate.reindex(weights.index) * weights).sum()
            for estimator, value in [
                ("raw", raw), ("common_current", common_current), ("common_fixed", common_fixed)
            ]:
                annual_rows.append(
                    {
                        "scenario": scenario,
                        "analysis_year": int(year),
                        "estimator": estimator,
                        "loss_rate_pct": value,
                        "n_common_countries": len(common),
                    }
                )
    annual = pd.DataFrame(annual_rows)
    summary = (
        annual.groupby(["scenario", "estimator"], as_index=False)
        .agg(
            loss_rate_pct_mean=("loss_rate_pct", "mean"),
            loss_rate_pct_min=("loss_rate_pct", "min"),
            loss_rate_pct_max=("loss_rate_pct", "max"),
            n_years=("analysis_year", "nunique"),
            n_common_countries=("n_common_countries", "first"),
        )
    )
    reference_annual = annual[annual["scenario"] == "ssp126"][["analysis_year", "estimator", "loss_rate_pct"]].rename(
        columns={"loss_rate_pct": "reference_rate_pct"}
    )
    contrast = annual.merge(reference_annual, on=["analysis_year", "estimator"], how="left")
    contrast["difference_vs_ssp126_pp"] = contrast["loss_rate_pct"] - contrast["reference_rate_pct"]
    contrast_summary = (
        contrast.groupby(["scenario", "estimator"], as_index=False)
        .agg(
            difference_mean=("difference_vs_ssp126_pp", "mean"),
            difference_min=("difference_vs_ssp126_pp", "min"),
            difference_max=("difference_vs_ssp126_pp", "max"),
        )
    )
    return summary.merge(contrast_summary, on=["scenario", "estimator"], how="left")


def main() -> None:
    args = add_common_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    out = output_dir(args.model, args.output_dir)
    configure_style()
    data = build_data(args.model)
    write_source(data, out, "fig04_wind_scenario_convergence.csv")

    estimators = ["raw", "common_current", "common_fixed"]
    x = np.arange(len(estimators))
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.35))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.2, top=0.8, wspace=0.28)
    for scenario in SSPS:
        sub = data[data["scenario"] == scenario].set_index("estimator").reindex(estimators)
        mean = sub["loss_rate_pct_mean"].to_numpy()
        axes[0].errorbar(
            x, mean,
            yerr=[mean - sub["loss_rate_pct_min"].to_numpy(), sub["loss_rate_pct_max"].to_numpy() - mean],
            color=SSP_COLOR[scenario], marker="o", lw=1.5, capsize=2.5, label=SSP_LABEL[scenario],
        )
        diff = sub["difference_mean"].to_numpy()
        axes[1].errorbar(
            x, diff,
            yerr=[diff - sub["difference_min"].to_numpy(), sub["difference_max"].to_numpy() - diff],
            color=SSP_COLOR[scenario], marker="o", lw=1.5, capsize=2.5,
        )
    for ax in axes:
        ax.set_xticks(x, [ESTIMATOR_LABEL[item] for item in estimators])
        ax.grid(axis="y", lw=0.35, alpha=0.4)
    axes[0].set_ylabel("2050s 风电净损失率（%）")
    axes[0].set_title("不同覆盖与权重口径")
    axes[0].legend(loc="best")
    axes[1].axhline(0, color="0.25", lw=0.8, ls="--")
    axes[1].set_ylabel("相对 SSP1-2.6 的差异（百分点）")
    axes[1].set_title("情景差异是否保持")
    panel_tag(axes[0], "a")
    panel_tag(axes[1], "b")
    n_common = int(data["n_common_countries"].dropna().iloc[0])
    fig.suptitle(f"2050s 风电情景收敛的平衡面板检验（{args.model}）", fontsize=10.5, fontweight="bold")
    fig.text(
        0.5, 0.035,
        f"误差条为 2053–2057 年际最小—最大值；共同国家 n={n_common}。固定权重使用三情景 2030s 共同国家平均应发电量权重。",
        ha="center", fontsize=6.2, color="0.4",
    )
    save_figure(fig, out, "fig04_wind_scenario_convergence")


if __name__ == "__main__":
    main()
