# 经度带相对损失率分析

本目录是 RQ4 的经度带方案：将全部场站按**全球 6×60° 经度扇区**分为六组，对比各带相对损失率（单位发电损失）轨迹并分解极端事件构成。与 `RQ4/latitude_band_relative_loss_rate`（纬度带）互为镜像。

## 分带定义

- 经度先取模到 `[0, 360)`（`lon % 360`，输入 lon 为 [-180, 180]），再按 60° 分带，自 0°E 起自西向东：

| 带名 | 范围 | 覆盖区域（数据内） |
|---|---|---|
| `000-060E` | 0–60°E | 欧洲、非洲（埃及/南非）、西亚 |
| `060-120E` | 60–120°E | 印度、东南亚、澳洲西部 |
| `120-180E` | 120–180°E | 东亚（日本/韩国）、澳洲东部 |
| `180-120W` | 120°W–180° | 大洋洲东侧海上边界带、墨西哥西部 |
| `120-060W` | 60–120°W | 南美西部（智利/巴西西部）、墨西哥 |
| `060-000W` | 0–60°W | 南美东部（巴西）、西欧海上（英/爱/西/葡） |

- 跨带国家（法国/西班牙/英国跨格林尼治经线、巴西/智利跨 60°W、墨西哥跨 120°W）会按场站经度分属两带，不做整体归属。
- 数据范围内 lon 为 -117.0 ~ 153.5°（`lon % 360` 后为 243~360 与 0~153.5），因此 **`180-120W` 带没有任何场站**，实际有数据的是其余 5 个带；缺失组合在 `csv/band_coverage.csv` 中记 0/NaN。

## 指标口径

数据源：`data/generation_loss_outputs/generation_loss/{model}/aggregate/generation_loss_decade_station.csv`（逐场站十年汇总长表），过滤 `analysis_scheme=center-k`、`analysis_k=5`。

- **带级相对损失率**：每个（经度带，情景，技术，快照十年）组合，取当期全部活跃场站，先汇总分子分母再相除：

```text
relative_loss_rate = 100 × Σ net_generation_loss_mwh / Σ normal_all_generation_mwh
```

能量加权口径：场站组成随快照年代自然演化（2030→2050 场站累积增加），不要求场站跨十年完整，容量越大的场站权重越高。

- **事件构成**：`event ≠ all` 行按（带，情景，技术，快照，事件）汇总十年净损失（负值截断为 0），计算带内损失加权占比 `loss_weighted_share`，以及剔除 `low_resource` 的残差口径 `loss_weighted_residual_share`。

覆盖说明：损失数据只覆盖 26 个国家的 96,257 个场站（`data/stations` 全球部署中有损失结果的子集）；各带国家构成见 `csv/band_coverage.csv`。

## 运行

```bash
.venv/bin/python RQ4/longitude_band_relative_loss_rate/run_all.py
```

结果位于 `outputs/CANESM5/`：

- `csv/band_coverage.csv` — 各带×情景×快照的场站数、装机、损失率（缺组合记 0/NaN）
- `csv/RQ4_lonband_metric_decade.csv` — 带级相对损失率与能量分量
- `csv/RQ4_lonband_event_decade.csv` — 带级事件损失与损失加权占比
- `figures/trajectories_{tech}.png` — 3 SSP 面板内六带轨迹
- `figures/fig_RQ4_lonband_event_composition_{tech}_2050.png` — 带×SSP 事件构成堆叠柱
- `run_config.json` — 参数、输入路径与 sha256、分带定义

当前上游风电能量字段仍按项目约定临时乘以 0.1（分子分母同缩放，不影响相对损失率数值，仅影响输出 CSV 的绝对能量列）；上游修复后需移除该修正并重跑。
