# RQ1 数据预处理说明

脚本：`RQ1/prepare_RQ1_data.py`
输出目录：`data/real/RQ1_generation/`
日志：`RQ1/logs/prepare_RQ1_data.log`

---

## 1. 原始输入数据

### 1.1 场站出力（Station Power Output）

```
data/wind_solar_output/outputs_0p1deg_2030_2040_2050/
  {pv_out | wind_out}/
    NESM3/
      {region}/
        {tech}_stations_out_{region}_NESM3_{ssp}_allmonths.nc
```

- `tech`：`pv`（光伏）或 `wind`（风电）
- `region`：27 个地区目录（如 `Australia`、`china`、`South-Africa`……）
- `ssp`：`ssp126` / `ssp245` / `ssp585`
- 气候模型：**仅 NESM3**

文件名示例：
```
pv_stations_out_Australia_NESM3_ssp126_allmonths.nc
wind_stations_out_Germany_NESM3_ssp245_allmonths.nc
```

> 注：部分地区 × SSP 组合不存在 NC 文件（共 19 个缺失），均为上游选址/计算流程未生成，脚本以 `[MISS-STA]` 记录后跳过。

**NC 文件结构**（覆盖 2030–2050，各目标年数据在同一文件内）：

| 变量 | 形状 | 单位 | 说明 |
|---|---|---|---|
| `time` | (8768,) | days since 2015-01-01 | **3 小时**时步，2030-01-01 → 2050-12-31 |
| `power` | (8768, N) | GW | 各场站逐时步出力（= CF × capacity_gw） |
| `capacity_gw` | (N,) | GW | 各场站装机容量 |
| `activation_year` | (N,) | year | 场站投运年份，取值 2030 / 2040 / 2050 |
| `station_lon` | (N,) | degrees_east | 经度 |
| `station_lat` | (N,) | degrees_north | 纬度 |
| `match_dist_deg` | (N,) | degrees | 场站到最近格点的匹配距离 |

**NaN 含义**：`power = NaN` 表示该时步所在年份 < 场站 `activation_year`（尚未投运）；`power = 0` 是有效值（如光伏夜间）。

---

### 1.2 格点容量因子（Grid-level CF）

```
# 非中国地区
data/cfs/CFs_of_{solar|wind}/NESM3/{region}/
  {tech}_CF_{region}_NESM3_{ssp}_2015-2060_allmonths.nc

# 中国（独立目录，文件直接在 NESM3/ 下）
data/cfs/CFs_of_{solar|wind}_china/NESM3/
  {tech}_CF_china_NESM3_{ssp}_2015-2060_allmonths.nc
```

**NC 文件结构**（覆盖 2015–2060）：

| 变量 | 形状 | 单位 | 说明 |
|---|---|---|---|
| `time` | (134416,) | days since 2015-01-01 | **3 小时**时步 |
| `lat` | (n_lat,) | degrees_north | 格点纬度 |
| `lon` | (n_lon,) | degrees_east | 格点经度 |
| `solar_cf` / `wind_cf` | (134416, n_lat, n_lon) | 1 | 各格点逐时步容量因子（0–1） |

海洋/区域边界外的格点值为 NaN（MaskedArray）。格点分辨率约 0.1°。

---

## 2. 输出数据

四个 CSV 文件，均保存于 `data/real/RQ1_generation/`。

### 2.1 `station_annual_generation.csv`（场站 × 年度，~20 万行）

| 列 | 说明 |
|---|---|
| `station_id` | 场站唯一标识，格式 `{T}{ssp3}_{region}_{idx:05d}`，如 `S126_Australia_00008` |
| `country` | 国家显示名 |
| `technology` | `solar` / `wind` |
| `deploy_ssp` | 部署情景（= `climate_ssp`，均为自洽情景） |
| `climate_ssp` | 气候情景 |
| `target_year` | 2030 / 2040 / 2050 |
| `capacity_mw` | 装机容量（MW） |
| `annual_capacity_factor` | 场站年 CF（0–1），含夜间零值 |
| `annual_generation_mwh` | 场站年发电量（MWh） |

### 2.2 `station_monthly_generation.csv`（场站 × 月度，~240 万行）

在 2.1 基础上增加：

| 列 | 说明 |
|---|---|
| `month` | 月份（1–12） |
| `monthly_capacity_factor` | 当月 CF |
| `monthly_generation_mwh` | 当月发电量（MWh） |

### 2.3 `country_annual_generation.csv`（国家 × 年度，~394 行）

| 列 | 说明 |
|---|---|
| `country` / `technology` / `deploy_ssp` / `climate_ssp` / `target_year` | 分组键 |
| `capacity_mw` | 该国全部场站装机之和（MW） |
| `annual_generation_mwh` | 该国全部场站发电量之和（MWh） |
| `mean_cf` | 该国全部场站 CF 的**算术平均**（各站等权） |

### 2.4 `country_grid_cf.csv`（国家 × 年度格点 CF，~162 行）

由格点 CF NC 文件聚合而来，**独立于场站出力**。用于 `plot_RQ1_cf.py` 的图 a（全球轨迹）、图 c（国家热图）、图 d（涨跌柱图）。

| 列 | 说明 |
|---|---|
| `country` / `technology` / `deploy_ssp` / `climate_ssp` / `target_year` | 分组键 |
| `mean_grid_cf` | 该国边界内所有有效格点的年均 CF 空间均值 |
| `n_grid` | 有效格点数（诊断用） |

---

## 3. 预处理 Pipeline

```
┌─────────────────────────────────────────────┐
│ 输入 1：场站出力 NC (power: T×N)            │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │ Step 1  读取变量     │  power, capacity_gw, activation_year
        │         时间解码     │  time → years_arr, months_arr
        └──────────┬──────────┘
                   │ for yr in [2030, 2040, 2050]
        ┌──────────▼──────────┐
        │ Step 2  按年切片     │  yr_power = power[years==yr, :]
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ Step 3  有效站过滤   │  active & has_data & valid_cap
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ Step 4  年度聚合     │  CF, gen_mwh → station_annual
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ Step 5  月度聚合     │  for m in 1..12 → station_monthly
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ Step 6  国家聚合     │  sum(cap, gen), mean(CF)
        │                     │  → country_annual_generation
        └─────────────────────┘

┌─────────────────────────────────────────────┐
│ 输入 2：格点 CF NC (cf: T×lat×lon)          │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │ Step A  时间解码     │  time → years_arr
        └──────────┬──────────┘
                   │ for yr in [2030, 2040, 2050]
        ┌──────────▼──────────┐
        │ Step B  按年切片     │  cf[i0:i1, :, :]  (连续索引，高效)
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ Step C  时间轴均值   │  nanmean(axis=0) → cf_ann (lat×lon)
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │ Step D  空间均值     │  nanmean(cf_ann[~isnan]) → scalar
        │                     │  → country_grid_cf
        └─────────────────────┘
```

---

## 4. 各步骤详解

### Steps 1–3：场站过滤

三个条件取交集：
- **已投运**：`activation_year ≤ yr`（未投运站 power 全为 NaN）
- **数据存在**：该年所有时步不全为 NaN（异常保护）
- **装机 > 0**：避免 CF 除零

### Step 4：站点年度 CF 与发电量

$$\text{CF}_i = \frac{\sum_t P_{t,i}(\text{GW})}{n_{\text{steps}} \times \text{capacity}_i(\text{GW})}$$

$$\text{gen}_i(\text{MWh}) = \sum_t P_{t,i}(\text{GW}) \times 3\,\text{h} \times 1000\,\frac{\text{MW}}{\text{GW}}$$

`nansum` 跳过 NaN（未激活时步），保留夜间零值（对光伏 CF 正确）。

**场站 ID 规则**：`{T}{ssp3}_{region_dir}_{原始下标:05d}`（`T`=`S`/`W`，`ssp3`=`126`/`245`/`585`）

### Step 6：国家级聚合（站点）

按 `[country, technology, deploy_ssp, climate_ssp, target_year]` 分组：
- 装机、发电量取**求和**
- `mean_cf` = 各场站 CF 的**算术平均**（各站等权，不按装机加权）

### Steps B–D：格点 CF 聚合

1. 按目标年找连续时间索引（`i0:i1`），直接切片避免全量加载
2. `nanmean(axis=0)` → 年均格点 CF 图像 `(lat, lon)`
3. `nanmean` of valid cells → 国家年均格点 CF（标量）

格点 CF 直接来源于上游 BCSD 降尺度后的 CF 文件，**不经过场站匹配**，代表整个国家可利用区域的资源平均水平。

---

## 5. 两种 CF 的区别与用途

| | 站点级 CF（`annual_capacity_factor`） | 格点级 CF（`mean_grid_cf`） |
|---|---|---|
| **来源** | 场站出力 NC，由 CF × 装机反推 | 格点 CF NC，直接读取 |
| **空间覆盖** | 选址后的实际建设场站 | 国家边界内所有可利用格点 |
| **用于** | 图 b：场站 CF 分布小提琴图 | 图 a：全球/国家 CF 轨迹<br>图 c：国家热图<br>图 d：涨跌柱图 |
| **全球均值** | — | 各国 `mean_grid_cf` 的算术平均（各国等权） |

---

## 6. 数据规模（当前版本）

| 文件 | 行数 | 说明 |
|---|---|---|
| `station_annual_generation.csv` | ~203,928 | 场站 × 3 目标年 |
| `station_monthly_generation.csv` | ~2,447,136 | 场站 × 3 目标年 × 12 月 |
| `country_annual_generation.csv` | ~394 | 国家 × SSP × 年度 |
| `country_grid_cf.csv` | ~162 | 国家 × SSP × 年度（有数据的组合） |

**场站出力缺失**（19 个）：
- 全部 SSP 缺失：Greece、Japan、South-Korea（光伏）——上游选址结果为空
- 仅 ssp585 缺失：Denmark、Ireland、Poland、Romania、South Africa、Sweden、Turkey、Ukraine（光伏），Austria（风电）——高排放路径场站极少

**格点 CF**：26 × 3 + 中国 × 3 = 81 个文件，全部存在，无缺失。

---

## 7. 注意事项

- **仅自洽情景**：`deploy_ssp` 始终等于 `climate_ssp`
- **零值 CF 场站**：光伏 CF=0 是合法数据（如地理位置差的站点），绘图时 KDE 过滤（`cf > 0`）
- **国家名映射**：`México→Mexico`，`china→China`，`South-Africa→South Africa`，`South-Korea→South Korea`，`United-Kingdom→United Kingdom`
- **日志**：每次运行覆写 `RQ1/logs/prepare_RQ1_data.log`，同时输出到标准输出
