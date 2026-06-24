# RQ1 数据预处理说明

脚本：`RQ1/prepare_RQ1_data.py`
输出目录：`data/real/RQ1_generation/`

---

## 1. 原始输入数据

### 1.1 位置

```
data/wind_solar_output/outputs_0p1deg_2030_2040_2050/
  {pv_out | wind_out}/
    NESM3/
      {region}/
        {tech}_stations_out_{region}_NESM3_{ssp}_allmonths.nc
```

- `tech`：`pv`（光伏）或 `wind`（风电）
- `region`：27 个地区目录，对应各国（如 `Australia`、`china`、`South-Africa`……）
- `ssp`：`ssp126` / `ssp245` / `ssp585`
- 气候模型：**仅 NESM3**

文件名示例：
```
pv_stations_out_Australia_NESM3_ssp126_allmonths.nc
wind_stations_out_Germany_NESM3_ssp245_allmonths.nc
```

> 注：部分地区 × SSP 组合不存在 NC 文件（共 19 个缺失），均为上游选址/计算流程未生成，脚本以 `[MISS]` 记录后跳过。

### 1.2 NC 文件结构

每个 NC 文件包含一个地区在**全部三个目标年**（2030 / 2040 / 2050）的所有场站出力，维度为：

| 变量 | 形状 | 单位 | 说明 |
|---|---|---|---|
| `time` | (8768,) | days since 2015-01-01 | **3 小时**时间步，覆盖 2030-01-01 → 2050-12-31 |
| `power` | (8768, N) | GW | 各场站逐时步出力（= CF × capacity_gw） |
| `capacity_gw` | (N,) | GW | 各场站装机容量 |
| `activation_year` | (N,) | year | 场站投运年份，取值 2030 / 2040 / 2050 |
| `station_lon` | (N,) | degrees_east | 经度 |
| `station_lat` | (N,) | degrees_north | 纬度 |
| `match_dist_deg` | (N,) | degrees | 场站到最近格点的匹配距离 |

**NaN 的含义**：`power = NaN` 表示该时步对应年份 < 场站 `activation_year`（尚未投运）；`power = 0` 是有效值（如光伏夜间）。

---

## 2. 输出数据

三个 CSV 文件，均保存于 `data/real/RQ1_generation/`。

### 2.1 `station_annual_generation.csv`（场站 × 年度，约 20 万行）

| 列 | 说明 |
|---|---|
| `station_id` | 场站唯一标识，格式 `{T}{ssp3}_{region}_{idx:05d}`，如 `S126_Australia_00008` |
| `country` | 国家显示名（已做目录名 → 标准名映射） |
| `technology` | `solar` / `wind` |
| `deploy_ssp` | 部署情景（= `climate_ssp`，真实数据均为自洽情景） |
| `climate_ssp` | 气候情景 |
| `target_year` | 2030 / 2040 / 2050 |
| `capacity_mw` | 装机容量（MW） |
| `annual_capacity_factor` | 年容量因子（0–1），含夜间零值 |
| `annual_generation_mwh` | 年发电量（MWh） |

### 2.2 `station_monthly_generation.csv`（场站 × 月度，约 240 万行）

在 2.1 基础上增加：

| 列 | 说明 |
|---|---|
| `month` | 月份（1–12） |
| `monthly_capacity_factor` | 当月容量因子 |
| `monthly_generation_mwh` | 当月发电量（MWh） |

### 2.3 `country_annual_generation.csv`（国家 × 年度，394 行）

| 列 | 说明 |
|---|---|
| `country` | 国家 |
| `technology` | `solar` / `wind` |
| `deploy_ssp` / `climate_ssp` | 情景 |
| `target_year` | 2030 / 2040 / 2050 |
| `capacity_mw` | 该国全部场站装机之和（MW） |
| `annual_generation_mwh` | 该国全部场站发电量之和（MWh） |
| `mean_cf` | 该国全部场站 CF 的**算术平均**（各站等权） |

---

## 3. 预处理 Pipeline

```
NC 文件 (power: T × N)
    │
    ├─ Step 1：读取变量
    │       power, capacity_gw, activation_year, time → years_arr, months_arr
    │
    ├─ Step 2：按目标年切片（for yr in [2030, 2040, 2050]）
    │       yr_power = power[years_arr == yr, :]     # (T_yr, N)
    │
    ├─ Step 3：有效场站过滤
    │       active    = activation_year <= yr         # 已投运
    │       has_data  = ~all(isnan(yr_power), axis=0) # 数据存在
    │       valid_cap = capacity_gw > 0               # 避免除零
    │       include   = active & has_data & valid_cap
    │
    ├─ Step 4：年度聚合（向量化）
    │       pwr_sum = nansum(yr_power[:, idx], axis=0)
    │       CF      = pwr_sum / (n_steps × capacity_gw[idx])
    │       gen_mwh = pwr_sum × 3h × 1000 MW/GW
    │       → 追加到 station_annual_generation
    │
    ├─ Step 5：月度聚合（向量化）
    │       for m in 1..12:
    │           m_power = yr_power[months_arr==m, idx]
    │           CF_m    = nansum / (n_m_steps × capacity_gw[idx])
    │           → 追加到 station_monthly_generation
    │
    └─ Step 6：国家级聚合
            groupby [country, tech, deploy_ssp, climate_ssp, target_year]
            capacity_mw            = sum(capacity_mw)
            annual_generation_mwh  = sum(annual_generation_mwh)
            mean_cf                = mean(annual_capacity_factor)   ← 算术平均
            → country_annual_generation
```

---

## 4. 各步骤详解

### Step 1：读取变量

用 `netCDF4` 读取 `power`（MaskedArray → 填充 NaN），同时读取 `capacity_gw`、`activation_year`，并将时间戳解码为年份数组 `years_arr` 和月份数组 `months_arr`。

### Step 2：按目标年切片

NC 文件的时间轴覆盖 2030–2050 全部数据，用 `years_arr == yr` 的布尔掩码取出对应年份的 3 小时时步（每年约 2920 步）。

### Step 3：有效场站过滤

三个条件的交集才纳入计算：
- **已投运**：`activation_year ≤ yr`（未投运站的 power 全为 NaN，排除）
- **数据存在**：该年所有时步不全为 NaN（极少数上游数据异常保护）
- **装机 > 0**：避免 CF 计算时除以零

### Step 4：年度 CF 与发电量

$$\text{CF} = \frac{\sum_t P_{t,i}}{n_{\text{steps}} \times \text{capacity}_i(\text{GW})}$$

$$\text{gen}_{i}(\text{MWh}) = \sum_t P_{t,i}(\text{GW}) \times 3\,\text{h} \times 1000\,\frac{\text{MW}}{\text{GW}}$$

`nansum` 跳过 NaN（即激活前时步），保留夜间零值（对光伏 CF 的计算是正确行为）。

**场站 ID 构造规则**：`{T}{ssp3}_{region_dir}_{原始下标:05d}`
- `T`：`S`（solar）或 `W`（wind）
- `ssp3`：SSP 后 3 位数字，如 `126`

### Step 5：月度聚合

在已过滤的场站集合 `idx` 上，对 12 个月分别切片，做与 Step 4 相同的 CF 和发电量计算，记录月份 1–12。

### Step 6：国家级聚合

按 `[country, technology, deploy_ssp, climate_ssp, target_year]` 分组：
- 装机和发电量取**求和**
- CF 取各场站**算术平均**（等权，不按装机加权）

---

## 5. 数据规模（截至当前版本）

| 文件 | 行数 | 说明 |
|---|---|---|
| `station_annual_generation.csv` | ~203,928 | 场站 × 3 目标年 |
| `station_monthly_generation.csv` | ~2,447,136 | 场站 × 3 目标年 × 12 月 |
| `country_annual_generation.csv` | 394 | 国家 × SSP × 年度 |

**覆盖情况**：142 个 NC 文件成功处理；19 个缺失（`[MISS]`）：
- 全部 SSP 缺失：Greece、Japan、South-Korea（光伏）——上游选址结果为空
- 仅 ssp585 缺失：Denmark、Ireland、Poland、Romania、South Africa、Sweden、Turkey、Ukraine（光伏），Austria（风电）——高排放路径下可用场站极少，上游未生成文件

---

## 6. 注意事项

- **仅自洽情景**：`deploy_ssp` 始终等于 `climate_ssp`，无 3×3 交叉情景
- **零值 CF 场站**：光伏场站 CF=0（年出力全为 0）是合法数据，但在 KDE 分布图中会被绘图脚本过滤（`cf > 0`）
- **时区/时步对齐**：原始时间戳为本地太阳时，不做时区转换；月份直接从时间戳提取
- **国家名映射**：`México → Mexico`，`china → China`，`South-Africa → South Africa`，`South-Korea → South Korea`，`United-Kingdom → United Kingdom`
