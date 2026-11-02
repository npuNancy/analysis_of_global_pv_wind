"""Recompute a three-part SSP story from current exposure and loss source tables."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "outputs"
SOURCE = OUT / "source_data"
MODELS = ("CANESM5", "MPI-ESM1-2-HR", "MRI-ESM2-0", "BCC-CSM2-MR")
SSPS = ("ssp126", "ssp245", "ssp585")
TECHS = ("wind", "solar")

PATHS = {
    "suitable_extreme": REPO / "paper_figures/supplementary/suitable_grid_extreme/outputs/source_data/decadal.csv",
    "suitable_loss": REPO / "paper_figures/prepare/outputs/suitable_grid_loss/decadal.csv",
    "full_grid_extreme": REPO / "paper_figures/main/fig01_extreme_events/outputs/meeting_grid/source_data/annual_models.csv",
    "station_extreme": REPO / "paper_figures/main/fig01_extreme_events/outputs/meeting_station/source_data/global_window_models.csv",
    "station_loss": REPO / "paper_figures/main/fig02_generation_loss/outputs/meeting_loss/source_data/global_all_combinations.csv",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            digest.update(block)
    return digest.hexdigest()


def direction_support(values: pd.Series) -> int:
    values = values.dropna().to_numpy(float)
    mean = values.mean()
    if np.isclose(mean, 0):
        return int(np.count_nonzero(np.isclose(values, 0)))
    return int(np.count_nonzero(np.sign(values) == np.sign(mean)))


def summarize_long(frame: pd.DataFrame, groups: list[str], values: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for keys, group in frame.groupby(groups, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        base = dict(zip(groups, keys))
        for value in values:
            series = group[value].dropna().astype(float)
            rows.append(
                {
                    **base,
                    "metric": value,
                    "mean": series.mean(),
                    "minimum": series.min(),
                    "maximum": series.max(),
                    "n_models": series.size,
                    "support_mean_direction": direction_support(series),
                }
            )
    return pd.DataFrame(rows)


def validate_suitable_support() -> dict:
    extreme = REPO / "paper_figures/supplementary/suitable_grid_extreme/outputs/source_data/patches"
    loss = REPO / "paper_figures/prepare/outputs/suitable_grid_loss/shards"
    rows = []
    for tech in TECHS:
        for mapping_path in sorted((extreme / tech).glob("*/mapping.csv.gz")):
            patch = mapping_path.parent.name
            support_path = loss / tech / patch / "support.csv.gz"
            require(support_path.exists(), f"Missing loss support for {tech}/{patch}")
            mapping = pd.read_csv(mapping_path, usecols=["lon", "lat", "common_valid"])
            support = pd.read_csv(support_path, dtype={"station_id": str})
            ids = pd.Series(
                [f"{tech}:{lon:.6f}:{lat:.6f}" for lon, lat in zip(mapping.lon, mapping.lat)],
                name="station_id",
            )
            event_mask = dict(zip(ids, mapping.common_valid.astype(bool)))
            loss_mask = dict(zip(support.station_id, support.common.astype(bool)))
            require(len(event_mask) == len(mapping), f"Duplicate event IDs: {tech}/{patch}")
            require(len(loss_mask) == len(support), f"Duplicate loss IDs: {tech}/{patch}")
            require(set(event_mask) == set(loss_mask), f"Different IDs: {tech}/{patch}")
            differences = sum(event_mask[key] != loss_mask[key] for key in event_mask)
            require(differences == 0, f"Different common masks: {tech}/{patch}")
            rows.append(
                {
                    "tech": tech,
                    "patch": patch,
                    "catalogue_cells": len(mapping),
                    "common_cells": int(mapping.common_valid.sum()),
                }
            )
    audit = pd.DataFrame(rows)
    require(len(audit) == 87, "Expected 87 technology-patch groups")
    totals = audit.groupby("tech")[["catalogue_cells", "common_cells"]].sum()
    require(int(totals.loc["wind", "catalogue_cells"]) == 591_798, "Wind catalogue count")
    require(int(totals.loc["solar", "catalogue_cells"]) == 557_406, "Solar catalogue count")
    require(int(totals.loc["wind", "common_cells"]) == 574_922, "Wind common count")
    require(int(totals.loc["solar", "common_cells"]) == 546_978, "Solar common count")
    return {
        tech: {
            "patches": int((audit.tech == tech).sum()),
            "catalogue_cells": int(totals.loc[tech, "catalogue_cells"]),
            "common_cells": int(totals.loc[tech, "common_cells"]),
            "coverage_pct": float(100 * totals.loc[tech, "common_cells"] / totals.loc[tech, "catalogue_cells"]),
        }
        for tech in TECHS
    }


def suitable_trajectory() -> tuple[pd.DataFrame, pd.DataFrame]:
    exposure = pd.read_csv(PATHS["suitable_extreme"])
    exposure = exposure[(exposure.event == "all") & (exposure.weighting == "equal")].rename(
        columns={"snapshot": "window_start"}
    )[["tech", "model", "climate_ssp", "window_start", "exposure_days"]]
    loss = pd.read_csv(PATHS["suitable_loss"])
    loss = loss[loss.support == "common"][[
        "tech", "model", "climate_ssp", "window_start", "net_loss_per_mw", "positive_loss_per_mw"
    ]]
    levels = exposure.merge(
        loss, on=["tech", "model", "climate_ssp", "window_start"], validate="one_to_one"
    )
    require(len(levels) == 72, "Incomplete suitable-grid model matrix")
    levels["effective_net_loss_fraction"] = levels.net_loss_per_mw / (24 * levels.exposure_days)
    levels["effective_positive_loss_fraction"] = levels.positive_loss_per_mw / (24 * levels.exposure_days)
    rows = []
    metrics = ("exposure_days", "net_loss_per_mw", "effective_net_loss_fraction")
    for (tech, ssp, model), group in levels.groupby(["tech", "climate_ssp", "model"]):
        indexed = group.set_index("window_start")
        row = {"tech": tech, "climate_ssp": ssp, "model": model}
        for metric in metrics:
            start = float(indexed.at[2030, metric])
            end = float(indexed.at[2050, metric])
            row.update(
                {
                    f"{metric}_2030s": start,
                    f"{metric}_2050s": end,
                    f"{metric}_change": end - start,
                    f"{metric}_change_pct": 100 * (end / start - 1),
                }
            )
        rows.append(row)
    changes = pd.DataFrame(rows)
    return levels, changes


def suitable_change_summary(changes: pd.DataFrame) -> pd.DataFrame:
    value_cols = [
        "exposure_days_change", "exposure_days_change_pct",
        "net_loss_per_mw_change", "net_loss_per_mw_change_pct",
        "effective_net_loss_fraction_change_pct",
    ]
    return summarize_long(changes, ["tech", "climate_ssp"], value_cols)


def suitable_event_mix() -> tuple[pd.DataFrame, pd.DataFrame, float]:
    data = pd.read_csv(PATHS["suitable_extreme"])
    data = data[data.weighting == "equal"]
    rows = []
    for (tech, ssp, event, model), group in data.groupby(["tech", "climate_ssp", "event", "model"]):
        values = group.set_index("snapshot").exposure_days
        rows.append(
            {
                "tech": tech,
                "climate_ssp": ssp,
                "event": event,
                "model": model,
                "change_2050s_minus_2030s_days": float(values[2050] - values[2030]),
            }
        )
    models = pd.DataFrame(rows)
    summary = summarize_long(
        models, ["tech", "climate_ssp", "event"], ["change_2050s_minus_2030s_days"]
    ).drop(columns="metric")
    pivot = summary.pivot_table(
        index=["tech", "climate_ssp"], columns="event", values="mean", aggfunc="first"
    )
    errors = []
    for tech, events in {
        "wind": ("high_temp", "high_wind", "hot_humid", "icing", "low_resource"),
        "solar": ("cold_highwind", "freezing_rain", "high_humidity", "icing", "low_resource", "rainstorm"),
    }.items():
        part = pivot.loc[tech]
        errors.extend((part[list(events)].sum(axis=1) + part.overlap_correction - part["all"]).abs())
    return models, summary, float(max(errors))


def exposure_domain_contrasts() -> tuple[pd.DataFrame, pd.DataFrame]:
    full = pd.read_csv(PATHS["full_grid_extreme"])
    full = full[(full.event == "all") & full.year.between(2050, 2059)]
    full = full.groupby(["tech", "model", "climate_ssp"], as_index=False).exposure_days.mean()
    suitable = pd.read_csv(PATHS["suitable_extreme"])
    suitable = suitable[
        (suitable.event == "all") & (suitable.weighting == "equal") & (suitable.snapshot == 2050)
    ][["tech", "model", "climate_ssp", "exposure_days"]]
    station = pd.read_csv(PATHS["station_extreme"])
    station = station[(station.event == "all") & (station.snapshot == 2050)].copy()
    station["exposure_days"] = station.E / 24
    frames = [("all_land_area_weighted", full), ("suitable_grid_equal_weighted", suitable)]
    frames.extend(
        (f"stations_fixed_{ssp}", station[station.station_ssp == ssp]) for ssp in SSPS
    )
    frames.append(("stations_paired_path", station[station.climate_ssp == station.station_ssp]))
    rows = []
    for domain, frame in frames:
        for (tech, model), group in frame.groupby(["tech", "model"]):
            values = group.set_index("climate_ssp").exposure_days
            require(set(values.index) == set(SSPS), f"Incomplete {domain}/{tech}/{model}")
            rows.append(
                {
                    "domain": domain,
                    "tech": tech,
                    "model": model,
                    "ssp585_minus_ssp126_days": float(values.ssp585 - values.ssp126),
                }
            )
    models = pd.DataFrame(rows)
    summary = summarize_long(models, ["domain", "tech"], ["ssp585_minus_ssp126_days"]).drop(columns="metric")
    return models, summary


def deployment_decomposition() -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    data = pd.read_csv(PATHS["station_loss"])
    data = data[(data.event == "all") & (data.snapshot == 2050)].copy()
    data["exposure_days"] = data.E_loss / 24
    data["effective_net_loss_fraction"] = data.R / data.E_loss
    identity_error = float((data.R - data.E_loss * data.cf_event * data.r_event).abs().max())
    variables = ("R", "exposure_days", "cf_event", "r_event", "effective_net_loss_fraction")
    rows = []
    for (tech, model), group in data.groupby(["tech", "model"]):
        cells = group.set_index(["climate_ssp", "station_ssp"])
        require(len(cells) == 9, f"Incomplete station cross matrix: {tech}/{model}")
        row = {"tech": tech, "model": model}
        for variable in variables:
            value = lambda climate, deployment: float(cells.at[(climate, deployment), variable])
            high, low = "ssp585", "ssp126"
            total = value(high, high) - value(low, low)
            climate = 0.5 * (
                value(high, low) - value(low, low) + value(high, high) - value(low, high)
            )
            deployment = 0.5 * (
                value(low, high) - value(low, low) + value(high, high) - value(high, low)
            )
            row.update(
                {
                    f"{variable}_paired_difference": total,
                    f"{variable}_climate_contribution": climate,
                    f"{variable}_deployment_contribution": deployment,
                    f"{variable}_closure_error": total - climate - deployment,
                }
            )
        rows.append(row)
    models = pd.DataFrame(rows)
    closure = float(models.filter(like="closure_error").abs().max().max())
    values = [column for column in models if column.endswith(("paired_difference", "climate_contribution", "deployment_contribution"))]
    summary = summarize_long(models, ["tech"], values)
    return models, summary, closure, identity_error


def pick(summary: pd.DataFrame, tech: str, ssp: str, metric: str, field: str = "mean") -> float:
    row = summary[(summary.tech == tech) & (summary.climate_ssp == ssp) & (summary.metric == metric)]
    require(len(row) == 1, f"Missing suitable summary: {tech}/{ssp}/{metric}")
    return float(row.iloc[0][field])


def pick_event(summary: pd.DataFrame, tech: str, event: str) -> float:
    row = summary[
        (summary.tech == tech) & (summary.climate_ssp == "ssp585") & (summary.event == event)
    ]
    require(len(row) == 1, f"Missing event summary: {tech}/{event}")
    return float(row.iloc[0]["mean"])


def pick_decomp(summary: pd.DataFrame, tech: str, metric: str) -> tuple[float, int]:
    row = summary[(summary.tech == tech) & (summary.metric == metric)]
    require(len(row) == 1, f"Missing decomposition: {tech}/{metric}")
    return float(row.iloc[0]["mean"]), int(row.iloc[0]["support_mean_direction"])


def write_report(
    suitable: pd.DataFrame,
    events: pd.DataFrame,
    domains: pd.DataFrame,
    decomposition: pd.DataFrame,
    support: dict,
) -> None:
    trajectory_rows = []
    labels = {"wind": "风电", "solar": "光伏"}
    for tech in TECHS:
        for ssp in SSPS:
            trajectory_rows.append(
                "| {tech} | {ssp} | {de:+.2f} ({se}/4) | {dl:+.2f} ({sl}/4) | {di:+.2f}% ({si}/4) |".format(
                    tech=labels[tech],
                    ssp=ssp.upper(),
                    de=pick(suitable, tech, ssp, "exposure_days_change"),
                    se=int(pick(suitable, tech, ssp, "exposure_days_change", "support_mean_direction")),
                    dl=pick(suitable, tech, ssp, "net_loss_per_mw_change"),
                    sl=int(pick(suitable, tech, ssp, "net_loss_per_mw_change", "support_mean_direction")),
                    di=pick(suitable, tech, ssp, "effective_net_loss_fraction_change_pct"),
                    si=int(pick(suitable, tech, ssp, "effective_net_loss_fraction_change_pct", "support_mean_direction")),
                )
            )
    domain_rows = []
    for domain in ("all_land_area_weighted", "suitable_grid_equal_weighted", "stations_fixed_ssp126", "stations_paired_path"):
        row = {tech: domains[(domains.domain == domain) & (domains.tech == tech)].iloc[0] for tech in TECHS}
        domain_rows.append(
            f"| {domain} | {row['wind']['mean']:+.2f} ({int(row['wind']['support_mean_direction'])}/4) | "
            f"{row['solar']['mean']:+.2f} ({int(row['solar']['support_mean_direction'])}/4) |"
        )
    wind_loss_total, wind_loss_support = pick_decomp(decomposition, "wind", "R_paired_difference")
    wind_loss_climate, wind_loss_climate_support = pick_decomp(decomposition, "wind", "R_climate_contribution")
    wind_loss_deploy, wind_loss_deploy_support = pick_decomp(decomposition, "wind", "R_deployment_contribution")
    wind_exp_total, wind_exp_support = pick_decomp(decomposition, "wind", "exposure_days_paired_difference")
    wind_exp_climate, wind_exp_climate_support = pick_decomp(decomposition, "wind", "exposure_days_climate_contribution")
    wind_exp_deploy, wind_exp_deploy_support = pick_decomp(decomposition, "wind", "exposure_days_deployment_contribution")
    wind_int_deploy, wind_int_deploy_support = pick_decomp(
        decomposition, "wind", "effective_net_loss_fraction_deployment_contribution"
    )
    wind_cf_deploy, wind_cf_deploy_support = pick_decomp(
        decomposition, "wind", "cf_event_deployment_contribution"
    )
    wind_r_deploy, wind_r_deploy_support = pick_decomp(
        decomposition, "wind", "r_event_deployment_contribution"
    )
    report = f"""# SSP 暴露—损失故事线（2026-11-02）

## 核心观点

高排放路径主要改变风险的组成与空间承载位置，而不是简单增加所有风险指标。风电在潜在适宜空间中出现“暴露增加但损失不增”，进入实际部署路径后又出现“暴露减少但损失增加”；这两个反直觉结果都指向同一机制：事件小时数不能代替事件期的发电价值与损失强度。

## 当前五类计算流程

| 产品 | 格点/场站定义 | 年度指标 | 跨文件与情景汇总 |
|---|---|---|---|
| Extreme：全球网格 | 正式网格事件信号；各技术事件在共同三小时轴上取时间并集 | 有效事件小时 / 24，缺测不置零 | 四模式、三 SSP 和全部产品的共同陆地支持；球面格点面积加权 |
| Extreme：适宜格点 | 1,149,204 行正式映射清单逐格点对齐全网格缓存 | 同上；不重新做适宜性筛选 | 固定跨四模式、三 SSP、30 年的共同格点；等格点权重为主，面积权重为敏感性检验 |
| Extreme：场站 | 气候 SSP × 部署 SSP；按 station_id 对齐，容量快照不累加 | 容量加权事件小时 / 容量 / 24 | 3 × 3 交叉矩阵；对角线为配对路径，气候与部署贡献用对称分解 |
| Loss：适宜格点 | 每个适宜格点固定 1 MW；按 completion → receipt → manifest → tile 读取 | `all` 事件并集上的带符号单位装机净损失 | 对相同共同格点先求和再除以格点数；四模式等权，年代取十年均值 |
| Loss：场站 | 气候 SSP × 部署 SSP；2030/2040/2050 容量快照对应三个十年窗口 | 正常 CF 基线排除事件并集，事件期正常发电减实际发电 | 相同有效场站上的损失能量和 / 容量和；交叉矩阵可分离气候与部署贡献 |

适宜格点 Extreme 与 Loss 的格点 ID 和共同有效掩膜逐 patch 完全一致：风电 {support['wind']['common_cells']:,}/{support['wind']['catalogue_cells']:,}（{support['wind']['coverage_pct']:.2f}%），光伏 {support['solar']['common_cells']:,}/{support['solar']['catalogue_cells']:,}（{support['solar']['coverage_pct']:.2f}%）。因此可以把单位装机净损失除以同一格点集合的暴露小时，得到“每暴露小时的有效净损失比例”。

## 结论 1：高排放使风、光风险轨迹分叉，但暴露与损失只在光伏上同向

下表均为 2050s 减 2030s；括号为与四模式均值同方向的模式数。

| 技术 | SSP | 暴露变化（day yr⁻¹） | 净损失变化（MWh MW⁻¹ yr⁻¹） | 每暴露小时有效净损失比例变化 |
|---|---|---:|---:|---:|
{chr(10).join(trajectory_rows)}

SSP585 下，风电暴露增加 {pick(suitable, 'wind', 'ssp585', 'exposure_days_change'):.2f} day yr⁻¹（4/4 模式），单位装机净损失仅变化 {pick(suitable, 'wind', 'ssp585', 'net_loss_per_mw_change'):+.2f} MWh MW⁻¹ yr⁻¹，且模式方向为 2/4；光伏暴露减少 {abs(pick(suitable, 'solar', 'ssp585', 'exposure_days_change')):.2f} day yr⁻¹、净损失减少 {abs(pick(suitable, 'solar', 'ssp585', 'net_loss_per_mw_change')):.2f} MWh MW⁻¹ yr⁻¹，两者均为 4/4。相对 SSP126，SSP585 将风电暴露增幅再扩大 {pick(suitable, 'wind', 'ssp585', 'exposure_days_change') - pick(suitable, 'wind', 'ssp126', 'exposure_days_change'):.2f} day yr⁻¹，却只使损失变化增加 {pick(suitable, 'wind', 'ssp585', 'net_loss_per_mw_change') - pick(suitable, 'wind', 'ssp126', 'net_loss_per_mw_change'):.2f} MWh MW⁻¹ yr⁻¹；光伏则额外减少 {abs(pick(suitable, 'solar', 'ssp585', 'exposure_days_change') - pick(suitable, 'solar', 'ssp126', 'exposure_days_change')):.2f} day yr⁻¹ 暴露和 {abs(pick(suitable, 'solar', 'ssp585', 'net_loss_per_mw_change') - pick(suitable, 'solar', 'ssp126', 'net_loss_per_mw_change')):.2f} MWh MW⁻¹ yr⁻¹ 损失。气候强迫扩大的是两种技术之间的响应差异，而不是统一抬升可再生能源风险。

## 结论 2：事件替换解释了“风电暴露增加、损失不增”

SSP585 的风电净暴露增量 {pick_event(events, 'wind', 'all'):+.2f} day yr⁻¹，主要由高温 {pick_event(events, 'wind', 'high_temp'):+.2f} 和高温高湿 {pick_event(events, 'wind', 'hot_humid'):+.2f} 推动，同时结冰 {pick_event(events, 'wind', 'icing'):+.2f}、低资源 {pick_event(events, 'wind', 'low_resource'):+.2f} 下降。对应的每暴露小时有效净损失比例下降 {abs(pick(suitable, 'wind', 'ssp585', 'effective_net_loss_fraction_change_pct')):.2f}%（4/4），抵消了暴露增长。

光伏的 {pick_event(events, 'solar', 'all'):+.2f} day yr⁻¹ 变化主要来自高湿 {pick_event(events, 'solar', 'high_humidity'):+.2f}、结冰 {pick_event(events, 'solar', 'icing'):+.2f}、冻雨 {pick_event(events, 'solar', 'freezing_rain'):+.2f} 和低资源 {pick_event(events, 'solar', 'low_resource'):+.2f}；每暴露小时有效净损失比例只变化 {pick(suitable, 'solar', 'ssp585', 'effective_net_loss_fraction_change_pct'):+.2f}%。因此光伏损失下降主要随暴露时间收缩，风电则由事件组合与事件期强度变化控制。

## 结论 3：部署路径会反转气候信号，并把风电容量移向“更少但更伤”的事件暴露

2050s 的 SSP585 − SSP126 暴露差如下；前两行只改变气候空间或筛选，固定场站行保持 SSP126 部署，最后一行同时采用各自部署路径。

| 空间口径 | 风电（day yr⁻¹） | 光伏（day yr⁻¹） |
|---|---:|---:|
{chr(10).join(domain_rows)}

全陆地、适宜格点和固定部署场站上的风电气候信号均为增加或接近增加；采用配对部署路径后，风电暴露变为 {wind_exp_total:+.2f} day yr⁻¹（{wind_exp_support}/4），而单位装机净损失增加 {wind_loss_total:+.2f} MWh MW⁻¹ yr⁻¹（{wind_loss_support}/4）。对称代数分解表明，气候项贡献暴露 {wind_exp_climate:+.2f} day yr⁻¹（{wind_exp_climate_support}/4）和损失 {wind_loss_climate:+.2f} MWh MW⁻¹ yr⁻¹（{wind_loss_climate_support}/4）；部署项贡献暴露 {wind_exp_deploy:+.2f} day yr⁻¹（{wind_exp_deploy_support}/4）和损失 {wind_loss_deploy:+.2f} MWh MW⁻¹ yr⁻¹（{wind_loss_deploy_support}/4）。部署项同时使事件期正常容量因子增加 {wind_cf_deploy:+.4f}（{wind_cf_deploy_support}/4）、损失比例增加 {wind_r_deploy:+.4f}（{wind_r_deploy_support}/4），从而使每暴露小时有效净损失比例增加 {wind_int_deploy:+.4f}（{wind_int_deploy_support}/4）。

这形成完整逻辑：气候强迫先改变事件组合；事件组合决定暴露是否转化为损失；部署再通过容量的空间权重改变事件期发电价值与损失比例，最终能够反转仅看暴露得到的风险排序。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")


def main() -> None:
    SOURCE.mkdir(parents=True, exist_ok=True)
    support = validate_suitable_support()
    levels, changes = suitable_trajectory()
    suitable_summary = suitable_change_summary(changes)
    event_models, event_summary, event_closure = suitable_event_mix()
    domain_models, domain_summary = exposure_domain_contrasts()
    decomposition_models, decomposition_summary, decomp_closure, factor_identity = deployment_decomposition()

    require(set(changes.model) == set(MODELS), "Suitable model identities")
    require(set(changes.climate_ssp) == set(SSPS), "Suitable SSP identities")
    require(set(changes.tech) == set(TECHS), "Suitable technology identities")
    require(event_closure < 1e-10, "Event overlap closure")
    require(decomp_closure < 1e-12, "Climate/deployment closure")
    require(factor_identity < 1e-8, "R = E x CF x r identity")

    levels.to_csv(SOURCE / "suitable_levels_models.csv", index=False)
    changes.to_csv(SOURCE / "suitable_changes_models.csv", index=False)
    suitable_summary.to_csv(SOURCE / "suitable_changes_summary.csv", index=False)
    event_models.to_csv(SOURCE / "suitable_event_changes_models.csv", index=False)
    event_summary.to_csv(SOURCE / "suitable_event_changes_summary.csv", index=False)
    domain_models.to_csv(SOURCE / "domain_exposure_contrasts_models.csv", index=False)
    domain_summary.to_csv(SOURCE / "domain_exposure_contrasts_summary.csv", index=False)
    decomposition_models.to_csv(SOURCE / "station_decomposition_models.csv", index=False)
    decomposition_summary.to_csv(SOURCE / "station_decomposition_summary.csv", index=False)

    audit = {
        "status": "PASSED",
        "source_sha256": {name: sha256(path) for name, path in PATHS.items()},
        "suitable_support": support,
        "suitable_model_ssp_tech_matrix": {"rows": len(changes), "expected": 24, "complete": len(changes) == 24},
        "event_overlap_closure_max_abs_days": event_closure,
        "station_factor_identity_max_abs": factor_identity,
        "station_climate_deployment_closure_max_abs": decomp_closure,
        "definitions": {
            "exposure": "event-union hours divided by 24; not calendar event days",
            "loss": "signed net generation loss per MW on the all-event union",
            "effective_net_loss_fraction": "net loss per MW divided by event-union exposure hours",
            "model_summary": "equal arithmetic mean; support is number of models with the mean direction",
            "station_decomposition": "symmetric algebraic split of paired SSP585 minus SSP126 into climate and deployment terms",
        },
    }
    (OUT / "validation.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(suitable_summary, event_summary, domain_summary, decomposition_summary, support)
    print(json.dumps(audit, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
