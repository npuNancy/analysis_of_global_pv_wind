#!/usr/bin/env python3
"""Recheck the scientific interpretation of SSP loss comparisons."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "outputs"
SOURCE = OUT / "review_source_data"
INPUTS = {
    "stations": REPO / "paper_figures/main/fig02_generation_loss/outputs/meeting_loss/source_data/global_all_combinations.csv",
    "suitable": REPO / "paper_figures/prepare/outputs/suitable_grid_loss/decadal.csv",
}
SSPS = ["ssp126", "ssp245", "ssp585"]
METRICS = ["R", "R_positive", "annual_loss_pct"]


def summarize(frame, keys, value):
    rows = []
    for identity, group in frame.groupby(keys, sort=True):
        if not isinstance(identity, tuple):
            identity = (identity,)
        values = group[value].to_numpy(float)
        if not np.isfinite(values).all() or len(values) != 4:
            raise ValueError(f"Incomplete four-model contrast: {identity}")
        mean = float(values.mean())
        row = dict(zip(keys, identity))
        row.update(
            mean=mean, minimum=float(values.min()), maximum=float(values.max()),
            n_models=len(values),
            positive_models=int((values > 0).sum()),
            negative_models=int((values < 0).sum()),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(INPUTS["stations"])
    data = raw.loc[
        raw.country.eq("GLOBAL") & raw.event.eq("all") & raw.support.eq("common")
    ].copy()
    keys = ["model", "tech", "snapshot", "climate_ssp", "station_ssp"]
    if len(data) != 216 or data.duplicated(keys).any():
        raise ValueError("Expected the complete 4 x 2 x 3 x 3 x 3 station matrix")
    required = pd.MultiIndex.from_product(
        [sorted(data.model.unique()), ["solar", "wind"], [2030, 2040, 2050], SSPS, SSPS],
        names=keys,
    )
    if not data.set_index(keys).index.sort_values().equals(required.sort_values()):
        raise ValueError("Station matrix identities differ from the expected design")
    cap = data.groupby(["model", "tech", "snapshot", "station_ssp"]).capacity_mw
    if ((cap.max() - cap.min()).abs() > 1e-6).any():
        raise ValueError("Capacity changes within a fixed-deployment climate comparison")
    identity_error = float(
        (data.R - data.net_mwh / data.capacity_mw).abs().max()
    )
    ratio_error = float(
        (data.annual_loss_pct - 100 * data.net_mwh / data.normal_annual_mwh).abs().max()
    )
    if max(identity_error, ratio_error) > 1e-10:
        raise ValueError("Loss normalization does not reproduce the source metrics")

    data["normal_generation_per_mw"] = data.normal_annual_mwh / data.capacity_mw
    paired = data.loc[data.climate_ssp.eq(data.station_ssp)].copy()
    paired.to_csv(SOURCE / "paired_levels_models.csv", index=False)
    paired_summary = paired.groupby(["tech", "snapshot", "climate_ssp"], as_index=False)[
        ["R", "R_positive", "annual_loss_pct", "normal_generation_per_mw", "capacity_mw"]
    ].mean()
    paired_summary.to_csv(SOURCE / "paired_levels_summary.csv", index=False)

    rows = []
    for metric in METRICS:
        pivot = data.pivot(
            index=["model", "tech", "snapshot", "station_ssp"],
            columns="climate_ssp", values=metric,
        )
        for high in ["ssp245", "ssp585"]:
            diff = (pivot[high] - pivot.ssp126).rename("difference").reset_index()
            diff["metric"] = metric
            diff["contrast"] = f"{high}_minus_ssp126"
            rows.append(diff)
    climate = pd.concat(rows, ignore_index=True)
    climate_summary = summarize(
        climate, ["tech", "snapshot", "station_ssp", "metric", "contrast"], "difference"
    )
    climate.to_csv(SOURCE / "fixed_deployment_climate_models.csv", index=False)
    climate_summary.to_csv(SOURCE / "fixed_deployment_climate_summary.csv", index=False)

    ranges = []
    for axis, fixed in [("climate_ssp", "station_ssp"), ("station_ssp", "climate_ssp")]:
        pivot = data.pivot(
            index=["model", "tech", "snapshot", fixed], columns=axis, values="R"
        )
        span = (pivot.max(axis=1) - pivot.min(axis=1)).rename("R_range").reset_index()
        span = span.rename(columns={fixed: "fixed_scenario"})
        span["varied_axis"] = axis
        ranges.append(span)
    ranges = pd.concat(ranges, ignore_index=True)
    ranges.to_csv(SOURCE / "conditional_scenario_ranges_models.csv", index=False)
    range_summary = ranges.groupby(
        ["tech", "snapshot", "varied_axis"], as_index=False
    ).agg(median=("R_range", "median"), minimum=("R_range", "min"),
          maximum=("R_range", "max"), n_conditions=("R_range", "size"))
    range_summary.to_csv(SOURCE / "conditional_scenario_ranges_summary.csv", index=False)

    suitable = pd.read_csv(INPUTS["suitable"])
    suitable = suitable.loc[suitable.support.eq("common")]
    sg = []
    for metric in ["net_loss_per_mw", "positive_loss_per_mw"]:
        pivot = suitable.pivot(
            index=["model", "tech", "window_start"], columns="climate_ssp", values=metric
        )
        for high in ["ssp245", "ssp585"]:
            diff = (pivot[high] - pivot.ssp126).rename("difference").reset_index()
            diff["metric"] = metric
            diff["contrast"] = f"{high}_minus_ssp126"
            sg.append(diff)
    sg = pd.concat(sg, ignore_index=True)
    sg_summary = summarize(
        sg, ["tech", "window_start", "metric", "contrast"], "difference"
    )
    sg.to_csv(SOURCE / "suitable_climate_models.csv", index=False)
    sg_summary.to_csv(SOURCE / "suitable_climate_summary.csv", index=False)

    validation = {
        "station_rows": len(data),
        "max_unit_loss_identity_error": identity_error,
        "max_annual_loss_ratio_error": ratio_error,
        "source_sha256": {
            key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in INPUTS.items()
        },
        "station_source_mapping": {
            "ssp126": "stations_SSP1-2.6.csv",
            "ssp245": "stations_SSP2-4.5.csv",
            "ssp585": "stations_SSP5-6.0.csv",
        },
    }
    (OUT / "review_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    wind = paired_summary.loc[
        paired_summary.tech.eq("wind") & paired_summary.snapshot.eq(2050)
    ].set_index("climate_ssp")
    fixed = climate_summary.loc[
        climate_summary.tech.eq("wind") & climate_summary.snapshot.eq(2050)
        & climate_summary.metric.eq("R")
        & climate_summary.contrast.eq("ssp585_minus_ssp126")
    ].set_index("station_ssp")
    table = "\n".join(
        f"| {ssp} | {wind.loc[ssp, 'R']:.2f} | "
        f"{wind.loc[ssp, 'normal_generation_per_mw']:.2f} | "
        f"{wind.loc[ssp, 'annual_loss_pct']:.2f}% |"
        for ssp in SSPS
    )
    fixed_table = "\n".join(
        f"| {ssp} | {fixed.loc[ssp, 'mean']:+.3f} | "
        f"[{fixed.loc[ssp, 'minimum']:+.3f}, {fixed.loc[ssp, 'maximum']:+.3f}] | "
        f"{int(fixed.loc[ssp, 'positive_models'])}/4 |"
        for ssp in SSPS
    )
    text = f"""# SSP 研究问题与证据核查

当前状态：撤回“暴露—损失排序反转”作为论文核心观点的表述。以下给出重新计算的证据和下一步待检验的研究问题，不将问题写成已经成立的结论。

## 1. 原论证的缺口

暴露天数计量事件持续时间，单位装机损失计量能量损失。二者排序不同，本身不能证明极端事件定义错误，也不足以建立重要的科学悖论。科学问题需要说明这种差异怎样改变发电收益、建设决策或损失负担。

乘法恒等式与 Shapley 分解只能把已观察到的差异分配给各项，不能独立证明物理机制。机制证据应落实到具体区域、部署变化和气象过程，并构造固定其他因素的比较。

已有三个年代的差异也不能支持“2040s 已出现排序反转”：该年代 SSP5-8.5−SSP1-2.6 的暴露均值差约 +0.09 days/年，损失均值差约 +5.20 MWh/MW/年，方向相同。

## 2. 已核实的事实

### 更高的单位装机净损失不能单独代表更差的部署

2050s 全球风电配对组合，以下均为四模式均值：

| 数据中的配对组合代码 | 单位装机净损失（MWh/MW/年） | 正常发电基准（MWh/MW/年） | 净损失占正常发电量 |
|---|---:|---:|---:|
{table}

代码 ssp585 的场站输入来自 SSP5-6.0，并与气候 SSP5-8.5 组合；它不是独立核实的完整 SSP5-8.5 部署路径。

ssp585 组合的单位装机净损失较高，同时正常发电基准更高，损失占比更低。比较部署优劣需要把收益和损失共同纳入。这里的正常发电量是各自分析窗口排除事件后构造的参考量，不是实际总发电量，也不是跨 SSP 固定的发电基线。

### 固定部署后，没有得到“高排放普遍增加净损失”的全球结果

2050s 全球风电，气候 SSP5-8.5 减去 SSP1-2.6，单位为 MWh/MW/年：

| 固定的场站部署代码 | 四模式均值差 | 四模式范围 | 净损失增加的模式数 |
|---|---:|---:|---:|
{fixed_table}

这组比较固定了场站位置、容量快照和共同有效站点。它回答现有净损失定义下的气候情景差异，不能直接替代总发电变化或供电安全评估。

[适宜网格的独立情景比较](review_source_data/suitable_climate_summary.csv)也显示，2050s 风电 SSP5-8.5−SSP1-2.6 的净损失均值差约 +0.10 MWh/MW/年，模式方向不一致；正损失差约 +2.70 MWh/MW/年，四模式均为正。正损失与净损失回答不同问题，不能挑选其中一个来预设结论。

## 3. 三个待检验的研究问题

可检验的核心假说是：**未来新增风光装机是否集中于气候情景切换后损失增幅更大的地区，而且这种关系在考虑当地发电资源收益后仍然存在？** 目前尚未建立这一事实，因此下面不附预设的 Result。

| 层次 | Question | 必须得到的新增证据 |
|---|---|---|
| RQ1：建立核心事实 | 新增风光装机是否集中在气候情景切换后单位装机损失增幅更大的地区？ | 同一组空间对象上，比较容量增长与固定部署下的 SSP 损失差；区分少数大国的权重、资源收益与净收益抵消的作用。 |
| RQ2：解释形成原因 | 如果这种集中存在，它来自国别容量增长、国内选址，还是资源收益与气象过程的共同变化？ | 固定气候改变部署、固定部署改变气候；进一步区分国家间容量份额变化与国内位置变化，并核查驱动差异的气象过程。 |
| RQ3：检验未来后果 | 相对固定参考布局，未来部署会放大还是减轻气候情景切换带来的损失变化？ | 在同一未来窗口对两条气候 SSP 分别计算未来布局与固定参考布局的结果，量化部署对气候情景差异的放大或缓解，并跟踪其区域分布。 |

三条问题共同检验部署与气候损失变化的空间耦合是否产生额外损失；发电收益是比较部署选择时的必要约束。若 RQ1 未建立可重复的空间事实，就不能把 RQ2、RQ3 写成机制与后果。

当前场站损失产品的 2030、2040、2050 快照分别只配套 2030s、2040s、2050s 气候窗口，现有汇总表不包含“2030 布局在 2050s 气候中”的时间交叉单元。因此 RQ3 需要通过正式网格/场站产品补齐相应反事实，不能用三条年代曲线代替。

## 4. 复现

- [核查脚本](../audit_research_questions.py)
- [配对路径水平均值](review_source_data/paired_levels_summary.csv)
- [固定部署的气候情景比较](review_source_data/fixed_deployment_climate_summary.csv)
- [固定适宜网格的气候情景比较](review_source_data/suitable_climate_summary.csv)
- [各条件下的情景极差](review_source_data/conditional_scenario_ranges_summary.csv)
- [输入哈希与核验记录](review_validation.json)

计算仅使用 1866 已有汇总源数据。净损失按损失能量之和除以有效容量之和计算；先逐模式计算差异，再汇总四模式。模式范围表示模式间差异，不表示置信区间。
"""
    (OUT / "research_questions.md").write_text(text, encoding="utf-8")
    (OUT / "three_conclusions.md").write_text(text, encoding="utf-8")
    print(f"Written: {OUT / 'research_questions.md'}")
    print("Station matrix complete; loss normalization and ratio checks passed.")


if __name__ == "__main__":
    main()
