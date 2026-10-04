# BCSD-v2 数据使用指南

核对日期：2026-10-04。数据账号为 **乌镇1872 / `scnet-wuzhen-1872` / `acjpoxgsdu`**。本文描述已发布的数据及其正式索引，配套查询工具位于 [`utils/data_access`](../utils/data_access/)。

## 1. 数据总览与稳定入口

| 数据 | 含义 | 稳定根目录 | 正式索引入口，相对于根目录 |
|---|---|---|---|
| CF：全球网格 | BCSD-v2 气象驱动得到的风电、光伏容量因子 | `/work/home/acjpoxgsdu/cf_grid/cf_grid_v2/` | `runtime/authoritative_index.json` |
| CF：气候 SSP × 场站 SSP | 将网格 CF 映射到各场站发展情景中的站点 | `/work/home/acjpoxgsdu/cf_stations/cf_stations_v2/` | `index/authoritative_index.json` |
| Extreme：全球网格 | 各网格、各时刻是否发生指定极端事件，以及资源异常判定基线 | `/work/home/acjpoxgsdu/extreme_grid/extreme_grid_v2/` | `runtime/authoritative_index.json` |
| Extreme：气候 SSP × 场站 SSP | 将极端事件信号映射到各场站发展情景中的站点 | `/work/home/acjpoxgsdu/extreme_stations_new/extreme_stations_v2/` | `runtime/authoritative_index.json` |
| Loss：气候 SSP × 场站 SSP | 各容量快照下，逐站点、逐年、逐事件的发电损失及配套正常发电基线 | `/work/home/acjpoxgsdu/generation_loss_stations/loss_stations_v2/` | `runtime/completion.json` → receipt → task manifest |

以上均为运行根目录，**查询工具的 `--root` 应传入根目录，不要追加 `outputs/`**。稳定目录是以下实际运行目录的软链：

| 稳定目录名 | 实际目录 |
|---|---|
| `cf_grid_v2` | `/work/home/acjpoxgsdu/cf_grid/cf_grid_v2_20261001_013720/` |
| `cf_stations_v2` | `/work/home/acjpoxgsdu/cf_stations/station_cf_fast_20261001_132542/` |
| `extreme_grid_v2` | `/work/share/acjpoxgsdu/extreme_grid/grid_v2/` |
| `extreme_stations_v2` | `/work/home/acjpoxgsdu/extreme_stations_new/events_cs_20261001_132437/` |
| `loss_stations_v2` | `/work/home/acjpoxgsdu/generation_loss_stations/loss_cs_20261001_221603/` |

Extreme 全球网格的发布文件已集中在上述 `/work/share/` 目录，`outputs/` 中并非依靠指向多个账号的软链汇总；文件所有者仍可能是不同计算账号。索引中的 `original_output` 是原执行位置，读取时优先用 `unified_output`，兼容 `output`。

索引可以记录带时间戳的绝对路径。稳定入口便于定位，不要求把索引里的绝对路径改写成稳定别名。工具按索引声明读取；`--root` 只改变索引查找位置，**不会自动改写绝对路径**。本地使用需能访问这些路径；仅复制一个索引到本地不能直接读取远程文件，工具不自动建立 SSH 连接或下载数据。

## 2. 共同索引维度

| 维度 | 当前取值 / 解释 |
|---|---|
| `model` | `CANESM5`、`MPI-ESM1-2-HR`、`MRI-ESM2-0`、`BCC-CSM2-MR`，大小写按目录 |
| 气候情景 | `ssp126`、`ssp245`、`ssp585`；网格目录中直接写 SSP，场站目录用 `climate_<ssp>` |
| 场站情景 | `ssp126`、`ssp245`、`ssp585`；场站布局及容量发展情景，目录用 `station_<ssp>` |
| `patch` | 当前发布覆盖 47 个分块，如 `R02C08`；场站任务采用映射后的 **source patch** |
| `tech` | `wind`、`solar`，两者的变量和事件集合不同 |
| 时间 | CF / Extreme 覆盖 2015–2060；Loss 按容量快照和分析年份选择 |

气候 SSP 与场站 SSP 是独立维度，完整场站组合为 4 × 3 × 3 × 47 × 2 = 3384 个任务；网格组合为 4 × 3 × 47 × 2 = 1128 个任务。没有场站的合法空任务不会产生 NetCDF，不能把“无文件”直接当成失败。

场站 `station_id` 由场站 SSP、技术和规范化经纬度生成。同一场站 SSP 内可以通过 ID 对齐不同气候 SSP；不同场站 SSP 的 ID 不应直接视为相同站点。原始场站资料的 `ssp560` / SSP5-6.0 在计算流程中归入 `ssp585`，查询使用规范化后的 `ssp585`。

## 3. CF：全球网格

### 目录与索引

```text
cf_grid_v2/
├── inputs/
│   ├── patch_manifest.json
│   ├── release.json
│   └── input_inventory.csv
├── runtime/
│   ├── authoritative_index.json
│   ├── completion.json
│   └── final_expected_manifest.json
└── outputs/<model>/<ssp>/<patch>/<tech>/
    ├── manifest.json
    └── blocks/<identity>/
        ├── cf_<start>-<end>.nc
        └── cf_<start>-<end>.nc.json
```

统一入口为 `/work/home/acjpoxgsdu/cf_grid/cf_grid_v2/runtime/authoritative_index.json`。索引采用 `schema=grid-cf-v1`、`schema_version=1`，整体 `status=COMPLETED`。读取 `entries[]`，按 `model`、`climate_scenario`、`patch`、`tech` 筛选，再从 `blocks[].path` 取文件；查询工具只读取这一份索引，不逐个打开任务 manifest 或扫描输出目录。

| 索引字段 | 内容 |
|---|---|
| `combination_count` / `file_count` | 当前为 1128 个组合、9024 个 NC 分片 |
| `root` / `run_id` / `years` / `generated_at` | 实际运行目录、运行标识、覆盖年与索引生成时间 |
| `sources.completion` / `sources.expected_manifest` | 完成记录与最终任务清单的路径、SHA256 |
| `entries[]` | 模型、气候 SSP、分块、技术、`years`、`status`、`merge_final`、`identity` |
| `entries[].manifest` | 对应任务 manifest 的路径、SHA256，用于追溯 |
| `entries[].blocks[]` | `index`、`start_year`、`end_year`、`status`、`path`、`size_bytes` |

生成器将任务 manifest 中的相对 block 路径按 **manifest 所在目录**解析后写成绝对路径；统一索引若使用相对路径，则以 **运行根目录**解析。`identity` 区分计算配置，只收录当前正式 manifest 声明的分片。

需要重新生成索引时，在能访问该数据的仓库环境运行：

```bash
source .venv/bin/activate
python utils/data_access/build_cf_grid_index.py \
  --root /work/home/acjpoxgsdu/cf_grid/cf_grid_v2

# 也可通过配套 SLURM 脚本生成。
bash utils/data_access/build_cf_grid_index.sh
```

[`build_cf_grid_index.py`](../utils/data_access/build_cf_grid_index.py) 以 `runtime/final_expected_manifest.json` 为任务全集，与 `runtime/completion.json` 核对组合、成功任务数及 NC 文件数；逐项检查任务身份、完成状态、分片年份连续性与完整覆盖，以及文件存在、可读且非空。全部通过后原子写入统一索引，失败时保留已有索引。此操作读取 JSON 与文件元数据，不重新计算或读取完整 NC 数组，也不校验 NC 内容哈希。查询时校验索引状态、数量与分片声明；任务清单或数据更新后需重新生成索引，查询不会自动重建。

当前 `merge_final=false`，正式产品就是分片：2015–2020、2021–2026、2027–2032、2033–2038、2039–2044、2045–2050、2051–2055、2056–2060。每组合 8 个文件，共 9024 个 NC；不要等待一个覆盖全时段的合并文件。

### 数据内容

- 主变量：`wind_cf(time, lat, lon)` 或 `solar_cf(time, lat, lon)`，float32，单位为 1，容量因子通常在 0–1。
- 辅助变量：`domain_mask(lat, lon)` 等；网格为约 0.1° 的原生 BCSD 网格，实际坐标与边界以文件为准。
- `_FillValue` 表示缺测；xarray 默认解码为 NaN，不能按零发电处理。
- 时间采用原生三小时序列，保留模型日历和分钟偏移。不同技术首尾有效时间可能不同，不应硬编码每年时刻数或直接按数组位置对齐风、光数据。

## 4. CF：气候 SSP × 场站 SSP

### 目录与索引

```text
cf_stations_v2/
├── prepared.json
├── catalogs/
├── mappings/
├── index/
│   ├── authoritative_index.json
│   ├── coverage_summary.csv
│   ├── unmapped_stations.csv.gz
│   └── validation_summary.json
├── runtime/
└── outputs/<model>/climate_<climate_ssp>/station_<station_ssp>/<source_patch>/<tech>/
    ├── manifest.json
    ├── audit.json
    └── blocks/<identity>/cf_<start>-<end>.nc[.json]
```

以 `index/authoritative_index.json` 的 `entries[]` 为准，按 `model`、`climate_scenario`、`station_scenario`、`source_patch`、`tech` 筛选。条目给出 `manifest.path` 和 `blocks[].path`。当前 block 条目不单列起止年，工具从**索引声明的文件名**解析年份，并核对完整覆盖。

当前 3384 个条目中，2592 个 `COMPLETED`、792 个 `EMPTY_NO_STATIONS`；非空组合仍为上述 8 个 CF 分片，共 20736 个 NC。

### 数据内容与场站语义

- 主变量为 `wind_cf(time, station)` / `solar_cf(time, station)`。
- `station_id`、`lon`、`lat` 定位场站；`first_snapshot_year` 记录首次出现的容量快照年。
- `source_grid_lat/lon`、`source_iy/ix`、`match_dist_deg/km`、`mapping_status` 记录取样来源；`valid_count`、`missing_count` 等记录覆盖情况。
- `mapping_status`：0 为 MATCHED，1 为 OUTSIDE_DOMAIN；2 为 TOO_FAR、3 为 NO_SOURCE_PATCH 的未映射记录可在 `unmapped_stations.csv.gz` 核对。只读取输出 NC 不等于恢复整个原始场站目录。
- 本批 `capacity_time_mask` 关闭：CF 表示站点位置的资源/发电能力序列，不会自动把站点首次出现之前的年份屏蔽。
- 2030、2040、2050 场站容量是各年的**总装机快照**，不是新增装机，不能逐期累计相加。

## 5. Extreme：全球网格

### 目录与索引

```text
extreme_grid_v2/
├── runtime/
│   ├── authoritative_index.json
│   └── patch_manifest.json
└── outputs/<model>/<ssp>/<patch>/<tech>/
    ├── baseline_2015-2024.nc[.json]
    ├── signals_<start>-<end>.nc[.json]
    ├── manifest.json
    └── audit_2015-2060.json
```

索引 `kind=grid-v2-unified-index`、`schema_version=1`；读取 `combinations` 中的 `artifacts[]`。`stage=signals` 为事件信号，`stage=baseline` 为资源异常基线，`years` 给出覆盖区间，路径用 `unified_output`，兼容 `output`。

每组合 1 个 2015–2024 基线，以及 10 个 signals 分片：2015–2019、2020–2024、2025–2029、2030–2034、2035–2039、2040–2044、2045–2049、2050–2054、2055–2059、2060–2060。共 1128 个基线、11280 个信号 NC。

### 变量与基线

| 技术 | 事件变量 |
|---|---|
| wind | `signal_high_temp`、`signal_high_wind`、`signal_hot_humid`、`signal_icing`、`signal_low_resource` |
| solar | `signal_cold_highwind`、`signal_freezing_rain`、`signal_high_humidity`、`signal_icing`、`signal_low_resource`、`signal_rainstorm` |

事件变量维度为 `(time, lat, lon)`，存储编码为 int8：0 未发生、1 发生、-127 缺测；另含 `domain_mask`。xarray 将缺测解码为 NaN。**不要直接把带 NaN 的事件数组转为 bool，也不要把缺测填成 0 后统计发生率。** 光伏当前没有可用的 dust 输出。

基线包含 `clim288(month, hour, lat, lon)`、`p5(lat, lon)` 和 `baseline_valid_count`；month 为 12 个月，hour 为 24 小时。它服务于 2015–2024 参考期的资源异常定义，不是损失计算中的正常 CF 基线。风资源单位为 m/s，光伏辐射资源单位为 W/m²；具体阈值、滚动窗口和有效性处理以计算源码及 NC 属性为准。

事件与 CF 均保留原始时间坐标，比较或关联时要对齐实际时间，保留各模型的 Gregorian / proleptic Gregorian / 365_day / noleap 日历，不强制转成公历。

## 6. Extreme：气候 SSP × 场站 SSP

### 目录与索引

```text
extreme_stations_v2/
├── inputs/
├── runtime/
│   ├── authoritative_index.json
│   ├── coverage_summary.csv.gz
│   └── final_acceptance.json
└── attempts/<task_id>/<job_id>/
    ├── outputs/<model>/climate_<climate_ssp>/station_<station_ssp>/<source_patch>/<tech>/
    │   └── signals_<start>-<end>.nc[.json]
    └── shared/                 # 准备任务的 catalogs / mappings 等
```

**该根目录没有统一的顶层 `outputs/`。** 正式数据保留在成功 attempt 下，应使用 `runtime/authoritative_index.json` 定位，不能自己拼 `root/outputs/...`，也不要递归扫描 attempts 后拼接所有文件。

索引 `kind=station-event-index`、`schema=station-extreme-v2`。在 `combinations` 中筛选模型、双 SSP、`patch` 和技术，检查 `status`，从 `outputs[].artifact.path` 取文件，`outputs[].period` 为年份区间。当前 2592 个 `COMPLETED`、792 个 `SKIPPED_NO_STATIONS`；每非空组合 10 个 signals 文件，共 25920 个 NC。

### 数据内容

事件名称、0/1/缺测语义与网格版一致，主维度改为 `(time, station)`。文件含 `station_id`、经纬度、`activation_year` 和映射信息。最近格点匹配允许每个经纬度轴不超过 0.15°；任务 patch 是源网格分块，可能与场站所在分块不同。

本批 `activation_mask` 关闭；`activation_year` 是元数据，不代表此前事件已被自动清空。分析运营期暴露时需自行应用所需场站/容量规则。配套工具只打开索引中的已发布文件，不重建未映射站点的整套目录。

## 7. Loss：气候 SSP × 场站 SSP

### 目录与正式索引链

```text
loss_stations_v2/
├── runtime/
│   └── completion.json
└── outputs/
    ├── task_status/<model>/climate_<climate_ssp>/station_<station_ssp>/<source_patch>/<tech>/
    │   └── manifest.json
    ├── generation_loss/<model>/climate_<climate_ssp>/station_<station_ssp>/<source_patch>/<snapshot_year>/<tech>/
    │   └── stations_<start:07d>_<stop:07d>/
    │       └── <tech>_generation_loss_station_<analysis_year>.nc
    └── baselines/<model>/climate_<climate_ssp>/station_<station_ssp>/<source_patch>/<snapshot_year>/<tech>/
        └── stations_<start:07d>_<stop:07d>/
            ├── baseline_12x8__exclude_union_selected.nc
            └── manifest.json
```

没有 `authoritative_index.json`，正式读取顺序是：

1. `runtime/completion.json` 的 `receipts[unit_id]`，如 `loss_BCC-CSM2-MR_c126_s126_wind_R02C08`。
2. `receipt_path` 指向完成回执，核对 `receipt_sha256` 和 `scientific_status`。
3. 回执的 `manifest.path` 指向任务清单，核对声明 SHA256、任务身份和完成状态。
4. 从任务清单 `snapshots[].chunks[].outputs[]` 取逐年结果；基线清单及路径也必须在回执 artifacts 中声明。

当前 3384 个任务中，2592 个非空完成、792 个 `SKIPPED_NO_STATIONS`。整体任务完成时，某个容量快照仍可能合法为空。当前完成索引所接受的结果都位于主 `outputs/`，其中 `BCC-CSM2-MR / climate_ssp126 / station_ssp126 / R02C08 / wind` 也已归入上述正常结构，主任务清单为 `COMPLETED`。

`stations_<start>_<stop>` 是场站数组批次，stop 为右开边界，不能当作站点 ID 或年份。每批站点数及具体年度文件以清单为准。

### 容量快照与分析年份

| `snapshot_year`：目录中的容量快照 | 当前 `center-k`、K=5 对应的分析年 |
|---|---|
| 2030 | 2030–2039 |
| 2040 | 2040–2049 |
| 2050 | 2050–2059 |

目录中的 2030 表示固定使用 2030 容量快照；文件名中的 2037 表示该容量布局在 2037 气候条件下的年度结果。CF / Extreme 的 2015–2060 覆盖不意味着 Loss 也覆盖全部这些年份。

### 年度变量与单位装机损失

年度 NC 的主维度为 **`station`，没有 `time` 维度**；年内序列已汇总。包含 `station_id`、`lon`、`lat`、`capacity_mw`，并按事件名及 `all` 后缀保存指标：

| 变量模式 | 含义 / 单位 |
|---|---|
| `generation_loss_mwh_<event>` | 正损失能量，MWh |
| `net_generation_loss_mwh_<event>` | 带符号的净损失能量，MWh |
| `net_generation_loss_per_mw_<event>` | 已按容量归一的净损失，MWh/MW |
| `normal_generation_mwh_<event>` / `actual_generation_mwh_<event>` | 事件期正常 / 实际发电量，MWh |
| `normal_all_generation_mwh_<event>` | 有效全年正常发电量，MWh |
| `generation_fluctuation_mwh_<event>` | 发电波动能量，MWh |
| `event_duration_hours_<event>` / `loss_hours_<event>` | 事件 / 损失持续时间，小时 |
| `relative_generation_loss_pct_<event>` | 发生正损失时刻的相对损失百分比均值；另有对应 sum / count，并非年度能量之比 |
| `generation_loss_intensity_<event>`、`normalized_generation_loss_<event>`、`generation_fluctuation_rate_<event>` | 无量纲派生指标，精确定义见 `generation_loss/metrics.py` |

已核对的年度文件中，部分 `units` 属性与公式量纲不一致：`net_generation_loss_per_mw_all` 标为 `MW`，实际为 MWh/MW；`relative_generation_loss_pct_all` 标为 `1`，数值已乘 100，表示百分比。上表按计算公式解释；读取工具保留原属性，不自动改单位或缩放数值。Loss 事件后缀使用 `high_wind` 等名称，不含 Extreme 变量的 `signal_` 前缀。

本项目默认“损失”指单位装机损失。以下以正损失为例，站点计算为：

\[
L_i = \frac{\mathrm{generation\_loss\_mwh\_all}_i}{\mathrm{capacity\_mw}_i},\qquad \mathrm{capacity\_mw}_i>0.
\]

区域汇总为相同有效站点集合上的“损失能量之和 / 容量之和”，不是各站点单位装机损失的简单平均：

\[
L_{\mathrm{region}} = \frac{\sum_i E_{\mathrm{loss},i}}{\sum_i C_i}.
\]

单位为 MWh/MW。零容量或缺测应屏蔽；`net_generation_loss_per_mw_*` 已归一，不能再除容量。`all` 按选定事件并集计算，不应把各事件损失简单相加替代，避免重叠事件重复计数。**风电发电量与损失直接使用原始值，不再乘 0.1。**

### 正常 CF 基线

`baseline_12x8__exclude_union_selected.nc` 的主变量为 `cf_normal(month_hour_idx, station)` 和 `baseline_count(month_hour_idx, station)`，按分析窗口排除选定事件并集后构造正常 CF。`month_hour_idx = 100 × 月份 + 小时`，例如 100、103、106；共有 12 × 8 个三小时槽，**不是两个独立的 month、hour 维度**。该基线与 Extreme 的 2015–2024 资源基线含义不同。

## 8. 查询与读取工具

### 文件与运行环境

| 脚本 | 数据 | `kind` |
|---|---|---|
| [`read_cf_grid.py`](../utils/data_access/read_cf_grid.py) | CF 全球网格 | `cf` |
| [`read_cf_stations.py`](../utils/data_access/read_cf_stations.py) | CF 场站 | `cf` |
| [`read_extreme_grid.py`](../utils/data_access/read_extreme_grid.py) | Extreme 全球网格 | `signals`（默认）、`baseline` |
| [`read_extreme_stations.py`](../utils/data_access/read_extreme_stations.py) | Extreme 场站 | `signals` |
| [`read_loss_stations.py`](../utils/data_access/read_loss_stations.py) | Loss 场站 | `loss`（默认）、`baseline` |

使用仓库 `.venv`，读取依赖已有的 xarray / netCDF4 / numpy；指定 `chunks` 时使用已有 dask。无需安装新依赖，也无需导入 `ref_code`。在能访问上述共享文件系统的节点、仓库根目录运行：

```bash
source .venv/bin/activate

python utils/data_access/read_cf_grid.py \
  --model BCC-CSM2-MR --climate-ssp ssp126 --patch R02C08 --tech wind --years 2030 2030

python utils/data_access/read_cf_stations.py \
  --model BCC-CSM2-MR --climate-ssp ssp126 --station-ssp ssp245 \
  --patch R02C08 --tech wind --years 2030 2030

python utils/data_access/read_extreme_grid.py \
  --model BCC-CSM2-MR --climate-ssp ssp126 --patch R02C08 --tech solar --years 2030 2030

python utils/data_access/read_extreme_stations.py \
  --model BCC-CSM2-MR --climate-ssp ssp126 --station-ssp ssp126 \
  --patch R02C08 --tech wind --years 2030 2030

python utils/data_access/read_loss_stations.py \
  --model BCC-CSM2-MR --climate-ssp ssp126 --station-ssp ssp126 \
  --patch R02C08 --tech wind --snapshot-year 2030 --years 2037 2037
```

统一参数说明：

- 默认只查询元数据，输出 JSON，含 `matched_files`、`shown_files`、`records`；不读大数组。无参数查询全部组合，默认只显示前 20 条。
- `--years START END` 两端包含，返回所有与区间相交的文件；它不裁剪文件内容。例如 CF 的 2030 查询会返回 2027–2032 分片。
- `--limit N` 限制显示条数，`--limit 0` 显示全部；该参数不限制索引检索范围，建议先指定模型和情景。
- `--format paths` 每行输出一个文件路径，便于管道处理。
- `--check` 检查**已显示记录**的文件存在且可读；`--inspect` 读取其 NC 维度、变量和属性，不加载数据数组，必须使用 JSON 输出。默认不遍历检查所有 NC，也不校验整份 NC 的内容哈希。
- `--root /path/to/run` 指定其他根目录；`--kind baseline` 查询对应基线。Extreme 基线年份为 2015–2024；Loss 基线按快照的分析窗口筛选。
- 不完整状态、元数据不一致会报错；合法空组合返回零记录。零记录也可能是筛选无匹配，请同时检查筛选条件与覆盖清单。

### Python：先找文件，再按需读取

每个读取模块均提供 `find_records(...)` 和 `open_record(...)`。共同筛选参数为 `model`、`climate_scenario`、`station_scenario`、`patch`、`tech`、`years`、`kind`；Loss 另有 `snapshot_year`。网格没有场站 SSP，CF / Extreme 没有容量快照维度。

```python
from utils.data_access import read_cf_grid, read_cf_stations
from utils.data_access import read_extreme_grid, read_extreme_stations
from utils.data_access import read_loss_stations

grid_query = dict(model="BCC-CSM2-MR", climate_scenario="ssp126",
                  patch="R02C08", tech="wind", years=(2030, 2030))
station_query = dict(grid_query, station_scenario="ssp126")

cf_grid_files = read_cf_grid.find_records(**grid_query)
cf_station_files = read_cf_stations.find_records(**station_query)
event_grid_files = read_extreme_grid.find_records(**grid_query)
event_station_files = read_extreme_stations.find_records(**station_query)
loss_files = read_loss_stations.find_records(**station_query, snapshot_year=2030)

# 网格 CF：先选变量、年份、小空间窗口，再加载选中的数据。
for record in cf_grid_files:
    with read_cf_grid.open_record(record) as ds:
        lat0, lon0 = float(ds.lat.min()), float(ds.lon.min())
    with read_cf_grid.open_record(record, variables=["wind_cf"], years=(2030, 2030),
                                 lat_range=(lat0, lat0 + 0.2),
                                 lon_range=(lon0, lon0 + 0.2)) as ds:
        subset = ds.load()
        # 在这里处理当前分片的小空间窗口。

# 场站：先看该文件的 ID，再选择所需站点；示例只读一个站点。
if cf_station_files:
    with read_cf_stations.open_record(cf_station_files[0]) as ds:
        station_id = str(ds.station_id.values[0])
    with read_cf_stations.open_record(cf_station_files[0], variables="wind_cf",
                                     station_ids=[station_id], years=(2030, 2030)) as ds:
        one_station_cf = ds.load()

# 极端事件：0/1之外的缺测保持 NaN；time聚合须另行处理有效时刻分母。
if event_station_files:
    with read_extreme_stations.open_record(event_station_files[0]) as ds:
        event_station_id = str(ds.station_id.values[0])
    with read_extreme_stations.open_record(event_station_files[0],
                                          variables=["signal_high_wind"],
                                          station_ids=[event_station_id],
                                          years=(2030, 2030)) as ds:
        events = ds.signal_high_wind
        event_fraction = (events == 1).sum("time") / events.notnull().sum("time").where(
            events.notnull().sum("time") > 0)
        event_fraction = event_fraction.load()

# Loss：analysis_year 已在 find_records 中筛选，年度文件没有 time 坐标。
if loss_files:
    with read_loss_stations.open_record(loss_files[0],
                                       variables=["generation_loss_mwh_all", "capacity_mw"]) as ds:
        unit_loss = (ds.generation_loss_mwh_all / ds.capacity_mw.where(ds.capacity_mw > 0)).load()
```

`open_record` 返回惰性 xarray Dataset，应用 xarray 默认缺测解码；用 `with` 关闭文件，在关闭前对需要保留的数据 `.load()`。`station_ids` 只在当前文件中查找，不跨文件检索，缺失 ID 会明确报错；需要全体站点时遍历该组合的记录，再按 ID 对齐。经纬度范围按文件原坐标筛选，不自动转换经度制或处理跨日期变更线范围。

年份裁剪仅用于有 `time` 坐标的 CF / signals；年度 Loss 和基线在 `find_records` 中筛选年份。工具不会自动拼接全球网格、拼接不同站点批次、套用投运掩膜或计算加权统计。跨文件计算请明确维度、时间日历及有效站点集合，并先验证重叠/缺口。

### SLURM 与检查

五个读取脚本、CF 网格索引生成器及四个测试脚本均有同名 `.sh`。在超算仓库目录通过 `bash` 调用作业脚本，会先创建仓库 `logs/data_access/`，再提交到 `wzhctest`；默认 1 节点、2 核、7 GB，stdout/stderr 写入同一个含 `%j` 的绝对日志路径。脚本自动使用该仓库 `.venv`，不带参数时运行对应 Python 的默认操作：

```bash
bash utils/data_access/read_loss_stations.sh \
  --model BCC-CSM2-MR --climate-ssp ssp126 --station-ssp ssp126 \
  --patch R02C08 --tech wind --snapshot-year 2030 --years 2030 2030 --limit 1 --inspect
```

上述作业执行文件定位/头信息读取。大范围 `.load()`、跨年聚合和绘图请放到自己的 SLURM 分析任务中，并按实际数组大小增加资源，不在登录节点运行。

本地小型测试不需要访问远程数据：

```bash
.venv/bin/python -m unittest discover -s utils/data_access -p 'test_*.py' -v
```

测试覆盖正式索引筛选、空任务、损坏/未完成元数据拒绝、Loss 回执哈希链，以及微型 NetCDF 的年份、空间、站点选择和缺测/日历保留；不能替代全量数据内容审计。

2026-10-04 验证记录：41 项本地测试通过；10 个 SLURM 脚本通过 Bash 语法检查，提交入口的日志目录创建和参数转发已验证。CF 全球网格统一索引已在乌镇1872生成，逐项核验了 1128 个任务和 9024 个 NC 文件的声明及文件元数据。在乌镇1872以 `BCC-CSM2-MR / ssp126 / R02C08 / wind`（场站 SSP 为 `ssp126`）核验了五类真实索引、CLI、文件头及单格点/单站点小切片读取，也核对了两类基线文件头。此验证没有重新计算产品或扫描全量数组。本地 netCDF4 导入出现一次 NumPy 二进制兼容性 RuntimeWarning，小型读写测试均成功；远程实际读取成功。

## 9. 计算源码与进一步追溯

- CF：[`ref_code/calculate_bcsd_cfs`](../ref_code/calculate_bcsd_cfs/)，网格存储见 `grid_cf_io.py`，场站目录、映射和完整场站读取见 `station_cf_catalog.py`、`station_cf_mapping.py`、`station_cf_reader.py`。
- 极端事件：[`ref_code/extreme_event_definitions`](../ref_code/extreme_event_definitions/)，事件阈值、原生网格时间处理、场站映射与索引生成以该仓库实现为准。
- 发电损失：[`ref_code/calculate_wind_solar_generation_loss`](../ref_code/calculate_wind_solar_generation_loss/)，指标见 `generation_loss/metrics.py`，基线见 `generation_loss/baseline.py`，窗口与输出见 `generation_loss/config.py`、`generation_loss/pipeline.py`。

`ref_code` 是计算过程参考；本目录工具按已发布元数据定位文件，不重新计算这些产品。若稳定软链以后切换到新版本，先复核 schema、时间覆盖、快照窗口和完成状态，再复用本文的当前数量与语义。
