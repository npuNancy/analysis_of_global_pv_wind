#!/usr/bin/env python3
"""Analyse combined wind and solar losses using existing summary data."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "outputs"
SOURCE = OUT / "source_data"
FIGURES = REPO / "paper_figures/main/fig02_generation_loss/outputs"
INPUTS = {
    "annual_technologies": FIGURES / "source_data/panel_ab.csv",
    "published_combined": FIGURES / "source_data/combined_loss_models.csv",
    "crossed_pathways": FIGURES / "meeting_loss/source_data/global_all_combinations.csv",
}
SSPS = ["ssp126", "ssp245", "ssp585"]
KEYS = ["model", "climate_ssp", "station_ssp", "snapshot"]
METRICS = ["unit_capacity_loss", "total_loss_pwh", "capacity_tw",
           "normal_per_mw", "annual_loss_pct", "wind_share"]


def summarize(frame, keys, values):
    rows = []
    for identity, group in frame.groupby(keys, sort=True):
        if not isinstance(identity, tuple):
            identity = (identity,)
        if len(group) != 4 or group.model.nunique() != 4:
            raise ValueError(f"Incomplete model group: {identity}")
        for name in values:
            x = group[name].to_numpy(float)
            if not np.isfinite(x).all():
                raise ValueError(f"Nonfinite {name}: {identity}")
            rows.append(dict(
                **dict(zip(keys, identity)), variable=name, mean=float(x.mean()),
                minimum=float(x.min()), maximum=float(x.max()), n_models=4,
                positive_models=int((x > 0).sum()), negative_models=int((x < 0).sum()),
            ))
    return pd.DataFrame(rows)


def contribution(w0, wind0, solar0, w1, wind1, solar1):
    wind = 0.5 * (w0 + w1) * (wind1 - wind0)
    solar = (1 - 0.5 * (w0 + w1)) * (solar1 - solar0)
    mix = 0.5 * (wind0 - solar0 + wind1 - solar1) * (w1 - w0)
    total = w1 * wind1 + (1-w1) * solar1 - w0 * wind0 - (1-w0) * solar0
    return dict(wind=wind, solar=solar, mix=mix, total=total,
                closure=wind + solar + mix - total)


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    annual = pd.read_csv(INPUTS["annual_technologies"])
    annual_keys = KEYS + ["year"]
    if len(annual) != 720 or annual.duplicated(annual_keys + ["tech"]).any():
        raise ValueError("Expected 720 unique annual technology records")
    for key, expected in [("country", "GLOBAL"), ("event", "all"), ("support", "common")]:
        if not annual[key].eq(expected).all():
            raise ValueError(f"Unexpected {key}")
    if not annual.climate_ssp.eq(annual.station_ssp).all():
        raise ValueError("Expected paired annual combinations")
    combined = annual.groupby(annual_keys, as_index=False)[["net_mwh", "capacity_mw"]].sum()
    combined["unit_capacity_loss"] = combined.net_mwh / combined.capacity_mw
    combined["total_loss_pwh"] = combined.net_mwh / 1e9
    published = pd.read_csv(INPUTS["published_combined"])
    metrics = ["unit_capacity_loss", "total_loss_pwh"]
    check = combined.merge(published[annual_keys+metrics], on=annual_keys,
                           suffixes=("_new", "_old"), validate="one_to_one")
    if len(check) != 360:
        raise ValueError("Existing annual source is incomplete")
    recomputation_error = {
        m: float((check[f"{m}_new"]-check[f"{m}_old"]).abs().max()) for m in metrics
    }
    if max(recomputation_error.values()) > 1e-10:
        raise ValueError("Existing figure data do not reproduce")

    matrix = pd.read_csv(INPUTS["crossed_pathways"])
    matrix = matrix.loc[matrix.country.eq("GLOBAL") & matrix.event.eq("all")
                        & matrix.support.eq("common")].copy()
    if len(matrix) != 216 or matrix.duplicated(KEYS+["tech"]).any():
        raise ValueError("Expected 216 technology-by-pathway cells")
    if not matrix.groupby(KEYS).tech.nunique().eq(2).all():
        raise ValueError("Missing a technology")
    summed = matrix.groupby(KEYS, as_index=False)[
        ["net_mwh", "positive_mwh", "normal_annual_mwh", "capacity_mw"]
    ].sum()
    summed["unit_capacity_loss"] = summed.net_mwh / summed.capacity_mw
    summed["positive_unit_capacity_loss"] = summed.positive_mwh / summed.capacity_mw
    summed["total_loss_pwh"] = summed.net_mwh / 1e9
    summed["capacity_tw"] = summed.capacity_mw / 1e6
    summed["normal_per_mw"] = summed.normal_annual_mwh / summed.capacity_mw
    summed["annual_loss_pct"] = 100*summed.net_mwh / summed.normal_annual_mwh
    wind_cap = matrix.loc[matrix.tech.eq("wind"), KEYS+["capacity_mw"]].rename(
        columns={"capacity_mw": "wind_capacity_mw"})
    summed = summed.merge(wind_cap, on=KEYS, validate="one_to_one")
    summed["wind_share"] = summed.wind_capacity_mw / summed.capacity_mw
    if len(summed) != 108:
        raise ValueError("Expected 108 combined scenario cells")
    cap = summed.groupby(["model", "station_ssp", "snapshot"]).capacity_mw
    if (cap.max()-cap.min()).abs().max() > 1e-6:
        raise ValueError("Fixed-deployment capacities differ across climates")
    paired = summed.loc[summed.climate_ssp.eq(summed.station_ssp)].copy()
    decades = combined.groupby(KEYS, as_index=False)[metrics].mean()
    comparison = paired.merge(decades, on=KEYS, suffixes=("_matrix", "_annual"))
    window_error = float(
        (comparison.unit_capacity_loss_matrix-comparison.unit_capacity_loss_annual).abs().max()
    )
    if len(comparison) != 36 or window_error > 1e-10:
        raise ValueError("Annual and decadal products disagree")
    tables = {
        "combined_crossed_pathways_models": summed,
        "technology_crossed_pathways_models": matrix,
        "combined_paired_levels_models": paired,
        "combined_paired_levels_summary": summarize(paired, ["climate_ssp", "snapshot"], METRICS),
    }

    rows = []
    for (model, ssp), group in paired.groupby(["model", "climate_ssp"]):
        ix = group.set_index("snapshot")
        for metric in METRICS:
            start, end = float(ix.loc[2030, metric]), float(ix.loc[2050, metric])
            rows.append(dict(model=model, climate_ssp=ssp, metric=metric, start=start, end=end,
                             difference=end-start, percent_change=100*(end/start-1)))
    changes = pd.DataFrame(rows)
    tables["temporal_changes_models"] = changes
    tables["temporal_changes_summary"] = summarize(
        changes, ["climate_ssp", "metric"], ["difference", "percent_change"])

    rows = []
    end = summed.loc[summed.snapshot.eq(2050)]
    for (model, climate), group in end.groupby(["model", "climate_ssp"]):
        ix = group.set_index("station_ssp")
        for baseline in ["ssp126", "ssp585"]:
            for metric in ["unit_capacity_loss", "annual_loss_pct", "normal_per_mw"]:
                rows.append(dict(
                    model=model, climate_ssp=climate, baseline_station_ssp=baseline,
                    target_station_ssp="ssp245", metric=metric,
                    difference=ix.loc["ssp245", metric]-ix.loc[baseline, metric]))
    fixed = pd.DataFrame(rows)
    tables["fixed_climate_deployment_models"] = fixed
    tables["fixed_climate_deployment_summary"] = summarize(
        fixed, ["climate_ssp", "baseline_station_ssp", "target_station_ssp", "metric"],
        ["difference"])
    temporal, between, standard = [], [], []
    paired_tech = matrix.loc[matrix.climate_ssp.eq(matrix.station_ssp)]
    for model, group in paired_tech.groupby("model"):
        ix = group.set_index(["climate_ssp", "snapshot", "tech"])
        def values(ssp, year):
            w, s = ix.loc[(ssp, year, "wind")], ix.loc[(ssp, year, "solar")]
            return float(w.capacity_mw/(w.capacity_mw+s.capacity_mw)), float(w.R), float(s.R)
        for ssp in SSPS:
            temporal.append(dict(model=model, climate_ssp=ssp,
                                 **contribution(*values(ssp,2030), *values(ssp,2050))))
        for base, target in [("ssp126","ssp245"), ("ssp245","ssp585"), ("ssp126","ssp585")]:
            between.append(dict(model=model, baseline=base, target=target,
                                **contribution(*values(base,2050), *values(target,2050))))
        common_w = values("ssp245",2050)[0]
        for ssp in SSPS:
            w, rw, rs = values(ssp,2050)
            standard.append(dict(
                model=model, climate_ssp=ssp, reference_wind_share=common_w,
                original_wind_share=w, original_R=w*rw+(1-w)*rs,
                standardized_R=common_w*rw+(1-common_w)*rs))
    temporal, between, standard = map(pd.DataFrame, [temporal, between, standard])
    max_closure = max(temporal.closure.abs().max(), between.closure.abs().max())
    if max_closure > 1e-10:
        raise ValueError("Component attribution does not close")
    tables["temporal_technology_contributions_models"] = temporal
    tables["temporal_technology_contributions_summary"] = summarize(
        temporal, ["climate_ssp"], ["wind","solar","mix","total"])
    tables["scenario_technology_contributions_models"] = between
    tables["scenario_technology_contributions_summary"] = summarize(
        between, ["baseline","target"], ["wind","solar","mix","total"])
    tables["common_technology_share_models"] = standard
    tables["common_technology_share_summary"] = summarize(
        standard, ["climate_ssp"], ["original_R","standardized_R"])
    tables["combined_crossed_pathways_2050_summary"] = end.groupby(
        ["climate_ssp","station_ssp"], as_index=False
    )[["unit_capacity_loss","annual_loss_pct","normal_per_mw"]].mean()
    for name, table in tables.items():
        table.to_csv(SOURCE/f"{name}.csv", index=False)
    validation = {
        "input_sha256": {k: hashlib.sha256(v.read_bytes()).hexdigest() for k,v in INPUTS.items()},
        "annual_recomputation_error": recomputation_error,
        "max_decadal_source_error": window_error,
        "max_component_closure_error": float(max_closure),
        "annual_technology_records": len(annual), "combined_cross_cells": len(summed),
        "ssp245_lower_R_at_each_climate_and_model": bool(
            fixed.loc[fixed.metric.eq("unit_capacity_loss"), "difference"].lt(0).all()),
        "ssp245_lower_fraction_than_ssp126_at_each_climate_and_model": bool(
            fixed.loc[fixed.metric.eq("annual_loss_pct") &
                      fixed.baseline_station_ssp.eq("ssp126"), "difference"].lt(0).all()),
        "station_ssp585_source": "stations_SSP5-6.0.csv",
    }
    (OUT/"validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2)+"\n")
    write_report(tables, changes)
    print(f"Written: {OUT/'findings.md'}")
    print(json.dumps(validation, ensure_ascii=False, indent=2))


def write_report(tables, changes):
    paired = tables["combined_paired_levels_models"]
    means = paired.groupby(["climate_ssp","snapshot"])[METRICS].mean()
    rows = []
    for ssp in SSPS:
        a, b = means.loc[(ssp,2030)], means.loc[(ssp,2050)]
        x = changes.loc[changes.climate_ssp.eq(ssp) &
                        changes.metric.eq("unit_capacity_loss"),"difference"]
        support = int(x.gt(0).sum()) if x.mean()>0 else int(x.lt(0).sum())
        rows.append(
            f"| {ssp.upper()} | {a.unit_capacity_loss:.2f} → {b.unit_capacity_loss:.2f} "
            f"| {100*(b.unit_capacity_loss/a.unit_capacity_loss-1):+.1f}% "
            f"| {100*(b.capacity_tw/a.capacity_tw-1):+.1f}% "
            f"| {a.total_loss_pwh:.3f} → {b.total_loss_pwh:.3f} | {support}/4 |")
    heat = tables["combined_crossed_pathways_2050_summary"].pivot(
        index="climate_ssp",columns="station_ssp",values="unit_capacity_loss")
    heat_rows = "\n".join(
        f"| {s.upper()} | {heat.loc[s,'ssp126']:.2f} | {heat.loc[s,'ssp245']:.2f} "
        f"| {heat.loc[s,'ssp585']:.2f} |" for s in SSPS)
    between = tables["scenario_technology_contributions_summary"]
    selected = between.loc[between.baseline.eq("ssp126") &
                           between.target.eq("ssp245")].set_index("variable")
    contrib_rows = "\n".join(
        f"| {label} | {selected.loc[k,'mean']:+.2f} "
        f"| {int(selected.loc[k,'negative_models'] if selected.loc[k,'mean']<0 else selected.loc[k,'positive_models'])}/4 |"
        for k,label in [("wind","风电单位装机损失差异"),("solar","光伏单位装机损失差异"),
                        ("mix","风光装机占比差异"),("total","合计差异")])
    std = tables["common_technology_share_summary"]
    std = std.loc[std.variable.eq("standardized_R")].set_index("climate_ssp")["mean"]
    unit_image = os.path.relpath(FIGURES/"combined_unit_capacity_loss.png", OUT)
    total_image = os.path.relpath(FIGURES/"combined_total_loss.png", OUT)
    report = rf"""# 风电＋光伏合计损失：三个由源数据支持的发现

## 核心发现

**风光扩张与单位装机净损失增加并非总是同时发生：SSP245 在装机扩张中降低了单位装机净损失，SSP126 与 SSP585 则上升。2050s 的低损失表现主要随部署组合变化，其中风电部分的差异最突出。**

结果来自两张现有曲线的逐模式源数据及气候 SSP × 场站部署 SSP 的完整交叉矩阵。主指标均为风光净损失能量之和除以风光有效容量之和，单位 MWh/MW/年。

## 发现一：扩张与单位损失出现不同方向，SSP126—SSP245 的分化最明确

| 配对组合代码 | 2030s → 2050s 单位装机净损失 | 单位损失变化 | 有效装机变化 | 总净损失（PWh/年） | 单位损失变化同向模式数 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

SSP245 的总损失仍增加，但增幅小于装机增幅；SSP126 与 SSP585 的总损失增加同时包含装机扩张和单位损失上升。表中百分比按四模式均值计算；方向一致性来自逐模式年代差。

![风光合计单位装机净损失]({unit_image})

2050s 的单位装机净损失为 SSP126 94.55、SSP245 82.62、SSP585 93.88 MWh/MW/年。SSP245 相对另外两条路径的低值均为四模式一致；SSP126 与 SSP585 的均值仅差 0.67 MWh/MW/年，模式间排序不一致。因此，当前更有辨识力的主比较是 SSP126 与 SSP245。

![风光总净损失]({total_image})

总损失图刻画需要管理的能量损失规模。它的 SSP126—SSP585 差距主要伴随装机规模差异，不能单独解释为同等装机下的损失差距。

## 发现二：SSP245 的低单位损失随部署组合存在，换成其他气候情景仍然成立

将三套部署分别放入同一气候情景，得到 2050s 风光合计单位装机净损失：

| 固定气候情景 / 部署代码 | ssp126 | ssp245 | ssp585 |
|---|---:|---:|---:|
{heat_rows}

固定气候后，ssp245 部署相对 ssp126 部署低 11.38–11.54 MWh/MW/年，相对 ssp585 部署低 12.07–13.03 MWh/MW/年。这两个比较分别在三个气候情景、四个模式的全部 12 个组合中同向。

这表明，三条配对曲线的差异不能直接称为排放强度的效果。这里的“部署组合”同时包括风光装机比例、国家间容量分配与国内场站位置；交叉矩阵尚未将后两者分开。

对 SSP126—SSP245，差异也存在于“净损失占正常发电量比例”：配对组合分别为 5.59% 与 5.28%，四模式同向。固定气候后，ssp245 部署仍低约 0.27–0.28 个百分点，全部 12 个条件组合同向。

## 发现三：SSP245 的低损失主要来自风电部分，光伏部分反而抵消了一部分降幅

2050s，SSP245 相对 SSP126 的风电单位装机净损失低 22.79 MWh/MW/年，但光伏高 3.09 MWh/MW/年；两项差异均为四模式一致。

在风光加权关系 $L=wL_{{wind}}+(1-w)L_{{solar}}$ 下，采用对称分配得到 SSP245−SSP126 的合计差异：

| 构成项 | 对合计单位损失差异的贡献（MWh/MW/年） | 同向模式数 |
|---|---:|---:|
{contrib_rows}

风光占比变化贡献约 −0.81 MWh/MW/年；风电自身的单位装机损失差异贡献约 −12.51 MWh/MW/年。因而，合计低值主要不是由提高光伏占比得到的。

再统一采用 SSP245 在 2050s 的风电装机占比（52.42%）进行加权，三条配对组合的单位损失分别为 {std.loc['ssp126']:.2f}、{std.loc['ssp245']:.2f}、{std.loc['ssp585']:.2f} MWh/MW/年，SSP245 的低值仍存在。这是对装机占比的标准化比较。

以上分配说明合计差异落在哪个技术部分；风电为何出现这种差异，需要继续识别具体国家、国内位置和气象过程，不能由加权恒等式直接推出。

## 可进一步发展的论文论点

**减排路径与风光系统单位装机损失的改善并不自动同步；在这些情景组合中，部署方式是解释损失分化的关键。**

当前证据最适合沿着“扩张中的单位损失分化 → 固定气候后仍存在的部署差异 → 风电部分的空间来源”推进。下一项有辨识力的分析是：在同一气候与技术占比下，把 SSP126—SSP245 的风电差异分成国家间装机权重与国内位置变化，并同时核算发电收益。

SSP245 也有较低的正常发电基准：2050s 合计为 1563 MWh/MW/年，SSP126 为 1691 MWh/MW/年。因此，低单位损失尚不能等同于总体发电表现或转型路径更优。这里的正常发电量是各窗口排除事件后构造的基准，不是实际全年发电量。

## 时间与情景口径

- 每个年代固定使用对应容量快照：2030–2039、2040–2049、2050–2059。原年度曲线在 2040、2050 附近的变化包含快照切换，不能据此认定气候在这些年份突然跃变。本报告据此采用年代均值比较。
- 气候 SSP 与场站部署 SSP 是独立维度。代码 ssp585 的场站输入来源为 stations_SSP5-6.0.csv，与气候 SSP5-8.5 组合。
- 全部主结果使用带符号净损失、事件时间并集和共同有效支持；风电能量不缩放。四模式方向一致性表示模式间一致，不等同于统计显著性。

## 数据与复现

- [分析脚本](../analyze.py) 与 [SLURM 脚本](../analyze.sh)
- [逐模式配对水准](source_data/combined_paired_levels_models.csv)
- [逐模式年代变化](source_data/temporal_changes_models.csv)
- [完整风光交叉矩阵](source_data/combined_crossed_pathways_models.csv)
- [固定气候的部署比较](source_data/fixed_climate_deployment_summary.csv)
- [技术与占比贡献](source_data/scenario_technology_contributions_summary.csv)
- [统一风光占比比较](source_data/common_technology_share_summary.csv)
- [输入哈希及核验](validation.json)
"""
    (OUT/"findings.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
