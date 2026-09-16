# 纬度带单位装机损失分析

本目录是 RQ4 的纬度带方案：抛弃国家维度，将全部场站按**南北半球 × 低/中/高纬度带**分为六组，对比各带单位装机损失轨迹并分解极端事件构成。不做聚类。

## 分带定义

- 半球：`lat ≥ 0` 归北半球（N），`lat < 0` 归南半球（S）；赤道（lat=0）归北。
- 纬度带（按 |lat|）：低 `< 30°`，中 `30°–50°`，高 `≥ 50°`。
- 选择 30°/50° 而非天文分界（23.436°/66.56°）的原因：损失数据纬度范围为 -53.2° ~ 60.0°，天文高纬带（≥66.56°）没有任何场站；30°/50° 下六个带全部有数据（S-high 仅风电，约 142 站，位于巴塔哥尼亚）。

## 指标口径

数据源：`data/generation_loss_outputs/generation_loss/{model}/aggregate/generation_loss_decade_station.csv`（逐场站十年汇总长表），过滤 `analysis_scheme=center-k`、`analysis_k=5`。

- **带级单位装机损失**：每个（纬度带，情景，技术，快照十年）组合，取当期全部活跃场站，按十年净损失除以装机容量并年化：

```text
unit_capacity_loss = Σ net_generation_loss_mwh / Σ capacity_mw / 10
```

能量加权口径：场站组成随快照年代自然演化（2030→2050 场站累积增加），不要求场站跨十年完整，容量越大的场站权重越高。

- **事件构成**：`event ≠ all` 行按（带，情景，技术，快照，事件）汇总十年净损失（负值截断为 0），计算带内损失加权占比 `loss_weighted_share`，以及剔除 `low_resource` 的残差口径 `loss_weighted_residual_share`。

覆盖说明：损失数据只覆盖 26 个国家的 96,257 个场站（`data/stations` 全球部署中有损失结果的子集），纬度范围 -53.2° ~ 60.0°；各纬度带国家构成见 `csv/band_coverage.csv`。S-high 光伏无场站，属数据范围限制而非异常。

## 运行

```bash
.venv/bin/python RQ4/loss_metrics/per_capacity_loss/latitude_band_unit_capacity_loss/run_all.py
```

结果位于 `outputs/CANESM5/`：

- `csv/band_coverage.csv` — 各带×情景×快照的场站数、装机、单位装机损失（缺组合记 0/NaN）
- `csv/RQ4_band_metric_decade.csv` — 带级单位装机损失与能量分量
- `csv/RQ4_band_event_decade.csv` — 带级事件损失与损失加权占比
- `figures/trajectories_{tech}.png` — 3 SSP 面板内六带轨迹
- `figures/fig_RQ4_band_event_composition_{tech}_2050.png` — 带×SSP 事件构成堆叠柱
- `run_config.json` — 参数、输入路径与 sha256、分带定义

当前上游风电能量字段仍按项目约定临时乘以 0.1（分子分母同缩放，不影响单位装机损失数值，仅影响输出 CSV 的绝对能量列）；上游修复后需移除该修正并重跑。

与 `RQ4/loss_metrics/per_capacity_loss/unit_capacity_loss_trajectory_clustering`（国家聚类）的关系：同一指标定义，把分组维度从国家换成纬度带，便于回答"极端损失风险随纬度如何变化"。
