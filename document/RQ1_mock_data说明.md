# RQ1 数据文件说明与脚本-数据依赖关系

本文件说明 `data_mock/mock_RQ_data/RQ1_future_generation/` 下各数据文件的字段含义，以及所有 `plot_RQ1_*.py` 脚本读取哪些文件。

> 当前所有绘图脚本均使用 **mock 数据**（随机生成）。待实际数据生成后需替换 `DATA` 路径。
> 替换逻辑见本文末尾"数据替换说明"一节。

---

## 一、数据文件字段说明

数据目录：`data_mock/mock_RQ_data/RQ1_future_generation/`

### 1. `country_annual_generation.csv` — 国家级年度汇总

| 字段 | 类型 | 含义 |
|------|------|------|
| `country` | str | 国家/区域名，共 28 个 |
| `technology` | str | `solar`（光伏）或 `wind`（风电） |
| `deploy_ssp` | str | 部署情景，决定**机队（装机容量）**：`ssp126 / ssp245 / ssp585` |
| `climate_ssp` | str | 气候情景，决定**气象驱动与容量因子**：`ssp126 / ssp245 / ssp585` |
| `target_year` | int | 目标年份快照：2030 / 2040 / 2050 |
| `capacity_mw` | float | 该国该年装机容量（MW），由 `deploy_ssp` 决定，与 `climate_ssp` 无关 |
| `annual_generation_mwh` | float | 年发电量（MWh）= 装机 × CF × 8760 |
| `capacity_weighted_cf` | float | 容量加权年均容量因子（无量纲，0–1） |

**关键点**：该表覆盖 `deploy_ssp × climate_ssp` 的全部 9 种组合（含"固定机队换气候"的交叉情景，不仅限于自洽情景）。

---

### 2. `station_annual_generation.csv` — 场站级年度汇总

| 字段 | 类型 | 含义 |
|------|------|------|
| `station_id` | str | 场站唯一编号（如 `S0000001`） |
| `country` | str | 所属国家 |
| `technology` | str | `solar` / `wind` |
| `deploy_ssp` | str | 部署情景（决定该场站是否存在及其装机容量） |
| `climate_ssp` | str | 气候情景 |
| `target_year` | int | 目标年份：2030 / 2040 / 2050 |
| `capacity_mw` | float | 该场站装机容量（MW） |
| `annual_capacity_factor` | float | 年均容量因子（0–1） |
| `annual_generation_mwh` | float | 年发电量（MWh） |

**关键点**：同样覆盖 `deploy_ssp × climate_ssp` 全交叉。场站数量随 `deploy_ssp + target_year` 变化（部署越激进、年份越晚，场站越多）。

---

### 3. `station_monthly_generation.csv` — 场站级月度汇总

| 字段 | 类型 | 含义 |
|------|------|------|
| `station_id` | str | 场站唯一编号 |
| `country` | str | 所属国家 |
| `technology` | str | `solar` / `wind` |
| `deploy_ssp` | str | 部署情景 |
| `climate_ssp` | str | 气候情景 |
| `target_year` | int | 目标年份 |
| `month` | int | 月份（1–12） |
| `capacity_mw` | float | 装机容量（MW） |
| `monthly_capacity_factor` | float | 当月容量因子（0–1） |
| `monthly_generation_mwh` | float | 当月发电量（MWh） |

**用途**：季节循环分析（逐月 CF / 发电量变化，风光互补评估）。

---

### 4. `station_catalog.csv` — 场站静态元数据

| 字段 | 类型 | 含义 |
|------|------|------|
| `station_id` | str | 场站唯一编号 |
| `country` | str | 所属国家 |
| `deploy_ssp` | str | 部署情景（决定场站存在与否） |
| `target_year` | int | 目标年份 |
| `technology` | str | `solar` / `wind` |
| `lat` | float | 纬度 |
| `lon` | float | 经度 |
| `capacity_mw` | float | 装机容量（MW） |
| `base_capacity_factor` | float | 基准容量因子（当前气候/历史期） |
| `resource_index` | float | 资源等级指数（归一化，用于区分优劣资源区） |
| `station_extreme_weather_index` | float | 极端天气暴露指数（供 RQ2 使用） |

**用途**：提供场站地理位置（纬度）和资源分级，与动态 CF 数据按 `station_id` 关联（`lat / resource_index` 不随气候情景变化）。

---

## 二、脚本-数据文件依赖关系

> 所有脚本的 `DATA` 路径均指向 `data_mock/mock_RQ_data/RQ1_future_generation/`。

| 脚本 | 读取文件 | 主要用途 |
|------|----------|----------|
| `plot_RQ1_cf.py` | `country_annual_generation.csv`<br>`station_annual_generation.csv` | 子图 a/c/d：国家级 CF 轨迹与变化<br>子图 b：场站级 CF 嵌套小提琴分布 |
| `plot_RQ1_generation.py` | `country_annual_generation.csv`<br>`station_monthly_generation.csv`<br>`station_annual_generation.csv` | 子图 a/c/d：国家级发电量轨迹与 Top 国家对比<br>子图 b：场站月度季节循环<br>子图 e：场站年发电量嵌套小提琴分布 |
| `plot_RQ1_generation_cfstyle.py` | `country_annual_generation.csv`<br>`station_annual_generation.csv` | 子图 a/c/d：国家级发电量（与 CF 图同框架）<br>子图 b：场站级发电量嵌套小提琴（对数轴） |
| `plot_RQ1_synthesis.py` | `country_annual_generation.csv` | 风/光 CF 变化 vs 发电量增量的 2 子图综合对比 |
| `plot_RQ1_cf_capacity_quadrant.py` | `station_annual_generation.csv` | CF vs 装机容量四象限图（3 情景 × 2 技术） |
| `plot_RQ1_ssp_fan.py` | `country_annual_generation.csv` | SSP 发散扇形图（CF 异常随时间张开） |
| `plot_RQ1_deploy_climate_matrix.py` | `country_annual_generation.csv` | deploy × climate 3×3 矩阵（9 种交叉情景，2050） |
| `plot_RQ1_country_dumbbell.py` | `country_annual_generation.csv` | 各国哑铃图（SSP1-2.6 ↔ SSP5-8.5 的 CF 差距） |
| `plot_RQ1_latitude_profile.py` | `station_annual_generation.csv`<br>`station_catalog.csv` | CF 随纬度带 / 资源指数的剖面（关联 `station_id`） |
| `plot_RQ1_seasonal_divergence.py` | `station_monthly_generation.csv` | 逐月 CF 的 SSP 分歧图（季节结构） |
| `plot_RQ1_stability_complementarity.py` | `station_monthly_generation.csv` | 场站 CF 变异系数（稳定性）+ 风光月度相关系数（互补性） |

**按文件汇总**：

| 数据文件 | 使用它的脚本数 | 被哪些脚本使用 |
|----------|--------------|--------------|
| `country_annual_generation.csv` | 7 | cf / generation / generation_cfstyle / synthesis / ssp_fan / deploy_climate_matrix / country_dumbbell |
| `station_annual_generation.csv` | 4 | cf / generation / generation_cfstyle / cf_capacity_quadrant |
| `station_monthly_generation.csv` | 3 | generation / seasonal_divergence / stability_complementarity |
| `station_catalog.csv` | 1 | latitude_profile |

---

## 三、数据维度与过滤约定

绘图脚本中两种常见的情景过滤逻辑：

| 分析目的 | 过滤方式 | 隔离的信号 |
|----------|----------|-----------|
| **隔离气候信号**（资源质量） | 固定 `deploy_ssp = ssp245`，遍历 3 个 `climate_ssp` | 机队不变，仅气候驱动 CF 变化 |
| **真实发电量轨迹** | 自洽情景：`deploy_ssp == climate_ssp` | 装机与气候同步演化 |

`plot_RQ1_cf.py` 与 `plot_RQ1_generation.py` 现均采用第二种（自洽情景）；`plot_RQ1_generation_cfstyle.py` 仍采用第一种（固定机队 `deploy=ssp245`）。

---

## 四、数据替换说明（从 mock 换为实际数据）

实际数据生成后，需构造与上述字段完全一致的 CSV 文件并替换 `DATA` 路径。

**现有数据 → 目标文件的映射关系**：

| 实际数据来源 | 提供的原始格式 | 需生成的目标文件 |
|-------------|--------------|----------------|
| `calculate_bcsd_-cfs/output/CFs_of_{solar,wind}/` | 小时分辨率 NetCDF（`solar_cf(time, lat, lon)` / `wind_cf(time, lat, lon)`），2015–2060 | — |
| `calculate_wind_solar_out/outputs/{pv,wind}_out/` | 小时分辨率 NetCDF（`power(time, id)`），2015–2060 | `station_annual_generation.csv`（年聚合）<br>`station_monthly_generation.csv`（月聚合） |
| 以上两者聚合后 | — | `country_annual_generation.csv`（国家级容量加权） |
| 场站元数据 CSV（`stations_SSP*.csv`） | CSV | `station_catalog.csv` |

**主要处理步骤**：
1. 从逐小时 `power(time, id)` 提取 2030 / 2040 / 2050 各年的年均 CF 和年发电量（建议用各目标年前后 ±2 年的均值平滑气候噪声）。
2. 场站级聚合 → `station_annual_generation.csv`；月度聚合 → `station_monthly_generation.csv`。
3. 按国家做容量加权汇总 → `country_annual_generation.csv`。
4. **维度差距**：现有出力文件仅含自洽情景（`deploy_ssp = climate_ssp`）。若需"固定机队、换气候"的交叉组合（CF 图所需），需在 `calculate_wind_solar_out` 中额外增加交叉情景计算，或直接从 CF NetCDF 乘以场站装机容量推算。
5. 现有 CF 数据有 3 个气候模型（MIROC-ES2H / MPI-ESM1-2-HR / NESM3），需决策是取集合均值还是分模型出图（mock 数据当作单一 NESM3 处理）。
