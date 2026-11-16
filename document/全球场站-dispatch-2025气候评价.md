# 全球场站-dispatch-2025 气候评价

已完成：4个GCM × 2气候SSP × 2场站SSP × 2技术，2030—2059的CF、Extreme、逐事件Loss和全年发电量均已发布。正式数据包含16,320份CF/Extreme分片、1,360份年度逐事件NetCDF和32份完整目录年度NPZ；8张三面板图及24张独立子图全部通过数值、导出和视觉检查。

## 范围与输入

方案名称为 **全球场站-dispatch-2025**。场站来自选址项目的 `results/campaign_runs/capacity_recovery_20261113T222351/MPI-ESM1-2-HR`，使用 SSP126、SSP245 下的六份 `stations_01deg_2030/2040/2050.csv`。原始文件及各路径的验收 manifest 保留于共享根的 `inputs/stations/`，准备作业核对了六份 CSV 的 SHA256、坐标、技术、单位和容量。

布局采用 GEM2025 存量初始化，在 MPI-ESM1-2-HR 未来单年 CF 下优化。气候评价保留四个 GCM：CANESM5、MPI-ESM1-2-HR、MRI-ESM2-0、BCC-CSM2-MR；每个 GCM 均包含两气候 SSP × 两场站 SSP 的完整交叉组合。两技术为风电与光伏；时间仅为2030—2059。2030、2040、2050装机快照分别用于对应完整十年，容量为总量。

光伏容量为 MWp/DC，风电为 MW；风电发电量与损失不缩放。场站 ID 包含方案、场站SSP、技术及0.1°网格ID。不同场站SSP不能直接按行号或站点ID合并。

## 共享位置与权限

结果根：

```text
/work/home/acxujo26gv/dispatch_2025_climate_storage/
├── inputs/                         # 原始布局、参考核、代码与来源清单
├── future/                         # 原生三小时 CF 与 Extreme、目录及映射
├── loss_future/                    # 分块、双SSP、逐事件年度损失和基线
├── station_results/future/         # 完整场站目录的年度汇总档案
├── source_data/                    # 全球逐模式与集合汇总CSV
├── report/                         # 独立报告、图件、源表和对应脚本副本
├── runtime/authoritative_index.json
└── runtime/completion.json
```

共享报告入口为 `report/document/全球场站-dispatch-2025气候评价.md`，包含全部图件、绘图源表、验收记录和对应脚本副本；科学计算使用结果根下的 `code/` 冻结代码。

1959保存结果。1892写入气候SSP126，1520写入气候SSP245，两个账号均使用默认ACL直接写入同一共享根。1866及其他账号可读不可写；已用1866和1870读取正式索引、四份汇总CSV及两技术的CF、Extreme、Loss、年度NPZ代表文件，并确认这些账号没有写权限。新建目录默认给其他用户遍历和读取权限，文件默认可读；不依赖逐个追加读取账号ACL。

正式使用时，先检查 `runtime/completion.json` 和 `runtime/authoritative_index.json` 均为 `COMPLETED`，并核对索引SHA256。计算过程中出现的分片不等于整套数据已经发布。

## 数据口径

- CF / Extreme 从原数据指南声明的全球网格正式索引提取，保留原生三小时时间、模式日历、CF原值和0/1/缺测事件编码。按场站所在0.1°栅格映射至已发布BCSD采样点；目录保留未映射站点及容量。文件名沿用源分片名，实际时间范围以索引 `years` 和NetCDF时间轴为准。
- 原生时间轴核对（覆盖各组合最大分块）：CANESM5、BCC-CSM2-MR采用`365_day`日历，2030—2059共87,600个三小时时刻；MPI-ESM1-2-HR、MRI-ESM2-0采用`proleptic_gregorian`，共87,656个时刻。风电时间戳每天从00:00起，光伏从01:30起。CF和Extreme分片年份边界不同，读取时分别拼接后按原生时间轴对齐。
- CF / Extreme 未施加投运掩膜；三个快照容量作为元数据保存。年度能量按相应年代的实际容量计算，使用时显式筛选正容量。
- Extreme包含风电5类、光伏6类事件，保留原低资源事件的2015—2024资源异常基准。ERA5-Land位于 `/work/home/acbw9wpn5k/bcsd/data/ERA5_land/global/`；本轮不计算历史期。
- Loss正常CF在2030—2039、2040—2049、2050—2059分别排除事件并集后，按月—小时有效CF求和除以样本数，保存12×8槽位的正常CF与样本数。它与低资源事件基准含义不同。
- 各事件及 `all` 的年度损失复用原 `generation_loss.metrics` 公式。`all` 是时间并集；正损失和带符号净损失分别保留。净损失等于同一有效事件时段的正常电量减实际电量。
- 全年发电量由全年CF积分；采用模式原生日历小时数。全年CF覆盖不完整时，全年发电量保持缺测。
- 原核的 `normal_all_generation_mwh_*` 在CF、正常CF和对应事件标记均有效的时刻积分；`loss_valid_count`记录 `all` 并集口径下的有效样本数。净损失比例使用这一有效时间内的正常基准电量。
- 暴露图采用Extreme并集的 `event_hours`，由已知事件标记计时；损失指标中的 `loss_event_hours`／`event_duration_hours_all` 还要求CF和正常CF有效。两类有效样本数分别保存在 `signal_valid_count` 和 `loss_valid_count`。
- 全球汇总使用同一有效集合计算分子、分母。汇总档案采用每个气候SSP×场站SSP×技术内部跨四模式、跨30年的共同有效站点：完整CF、至少99%有效事件时刻、有限净损失及正的全年正常基准。原生年度NetCDF保留映射站点的逐年原始指标及缺测；共同支持筛选只用于汇总档案与图件。
- 单位装机净损失为总净损失除以有效容量；净损失比例为总净损失除以上述有效时间内的全年正常基准电量。先逐模式计算比值，再等权汇总四模式。
- 目录容量、映射容量、最终有效容量及覆盖率分别保存。不能把未映射或无效场站当作零损失，也不能用完整目录容量替换有效分母。

## 读取入口

统一索引的 `entries[]` 提供CF、Extreme，包含 `model`、`climate_scenario`、`station_scenario`、`tech`、`patch`、`status` 和 `artifacts[]`。仅按已完成条目读取；空分块显式标记 `EMPTY_NO_STATIONS`。

`loss_files[]` 提供逐分块年度NetCDF，维度为 `year, station`，另有 `window, month_hour_idx, station` 正常CF基线。变量沿用原Loss的事件后缀，包括：

| 变量 | 含义与单位 |
|---|---|
| `net_generation_loss_mwh_<event>` | 带符号净损失，MWh |
| `generation_loss_mwh_<event>` | 正损失，MWh |
| `net_generation_loss_per_mw_<event>` | 单位装机净损失，MWh/MW |
| `normal_generation_mwh_<event>` / `actual_generation_mwh_<event>` | 事件期正常／实际发电量，MWh |
| `normal_all_generation_mwh_<event>` | 对应有效全年正常基准电量，MWh |
| `event_duration_hours_<event>` / `loss_hours_<event>` | 事件／损失时长，小时 |
| `all_generation_mwh` / `annual_cf` | 全年实际CF积分发电量／年均CF |
| `cf_normal` / `baseline_count` | 三个十年窗口的正常CF／有效样本数 |

波动、相对损失、强度和归一化等原生指标同时保留。各事件可能重叠，不能相加替代 `all`。

`annual_archives[]` 提供32份完整站点年度NPZ，按模式、双SSP和技术定位，保存 `grid_id`、容量、全年发电、净损失、CF、事件小时数及 `common_support`。32份档案的模式、双SSP、技术、站点目录和容量快照均已通过最终校验。

`summaries` 提供全球汇总CSV及SHA256。`global_annual_models.csv` 为1,440行（含风光合并），`global_annual_ensemble.csv` 为360行；完整情景、年份、技术和模式矩阵已通过校验。`capacity_coverage.csv` 保存完整、映射及有效容量，`catalogue_capacity.csv` 保存三个年代的目录容量。

## 汇总覆盖

下表为30年及四模式范围内的有效装机覆盖率。共同有效集合在每个双SSP×技术组内固定；每年正容量站点数仍会随十年快照改变。

| 气候SSP | 场站SSP | 技术 | 有效容量覆盖率 | 年度正容量有效站点数 |
|---|---|---|---:|---:|
| SSP126 | SSP126 | 光伏 | 98.04–98.99% | 30,743–109,043 |
| SSP126 | SSP126 | 风电 | 97.26–99.76% | 10,390–100,200 |
| SSP126 | SSP245 | 光伏 | 98.15–98.77% | 32,516–99,981 |
| SSP126 | SSP245 | 风电 | 97.27–99.32% | 10,536–68,975 |
| SSP245 | SSP126 | 光伏 | 98.04–98.99% | 30,743–109,043 |
| SSP245 | SSP126 | 风电 | 97.26–99.76% | 10,390–100,200 |
| SSP245 | SSP245 | 光伏 | 98.15–98.77% | 32,516–99,981 |
| SSP245 | SSP245 | 风电 | 97.27–99.32% | 10,536–68,971 |

完整目录保留未映射及未进入共同有效集合的容量；原生输出保留已映射站点的逐年指标和缺测。全球比值和图件使用上述共同有效集合。

## 图件约定

绘图在1866项目执行，目录为 [dispatch_2025](../paper_figures/supplementary/dispatch_2025/)。已输出8张完整三面板PNG及24张独立子图，600 dpi；三列依次为风光合并、风电、光伏。

装机和暴露展示2030s、2040s、2050s三个点，暴露先对每模式取十年均值。损失和发电展示2030—2059逐年四模式均值，并叠加全30年OLS描述趋势。阴影为四模式最小—最大值，不表示置信区间。配对路径126/126与245/245的差异同时包含气候与部署变化。

### 装机容量

基于已验收的完整场站目录，2030、2040、2050分别代表对应十年的总装机快照。面板a为风光合计，b为风电，c为光伏。容量不随气候评价模式变化。

![dispatch-2025装机容量](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_capacity.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_capacity_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_capacity_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_capacity_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/capacity_display.csv)。

| 场站情景 | 快照 | 风电（TW） | 光伏（TWp/DC） | 风光合计（TW） |
|---|---:|---:|---:|---:|
| SSP126 | 2030 | 1.005 | 1.342 | 2.348 |
| SSP126 | 2040 | 3.886 | 2.193 | 6.080 |
| SSP126 | 2050 | 12.933 | 2.608 | 15.542 |
| SSP245 | 2030 | 1.008 | 1.418 | 2.427 |
| SSP245 | 2040 | 2.129 | 1.742 | 3.872 |
| SSP245 | 2050 | 4.165 | 2.140 | 6.305 |

### 装机加权暴露总量

Extreme事件并集的年度小时数先换算为天，再按有效容量加权求和；每模式取十年平均。单位为MW day yr⁻¹。

![dispatch-2025装机加权暴露总量](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_total.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_total_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_total_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_total_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/exposure_total_display.csv)。

### 装机加权年均暴露时长

暴露总量除以同一有效集合的装机容量，得到每年平均暴露天数；每模式取十年平均。

![dispatch-2025装机加权年均暴露时长](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_mean.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_mean_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_mean_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_exposure_mean_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/exposure_mean_display.csv)。

### 总净损失

展示事件并集的带符号净损失，单位为MWh yr⁻¹。实际发电高于正常基准的事件时段可贡献负净损失。

![dispatch-2025总净损失](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_loss.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_loss_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_loss_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_loss_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/total_loss_display.csv)。

### 单位装机净损失

逐模式总净损失除以同一有效容量，单位为MWh MW⁻¹ yr⁻¹。三个面板使用独立纵轴、各六个等距刻度。

![dispatch-2025单位装机净损失](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_loss.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_loss_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_loss_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_loss_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/unit_loss_display.csv)。

### 净损失占全年正常基准电量比例

逐模式净损失除以相同有效时段的全年正常基准电量，单位为%。三个面板使用独立纵轴。

![dispatch-2025净损失占全年正常基准电量比例](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_loss_fraction.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_loss_fraction_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_loss_fraction_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_loss_fraction_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/loss_fraction_display.csv)。

### 全年总发电量

全年CF按模式日历积分并乘以对应年代容量，单位为PWh yr⁻¹；容量在2040和2050切换为新总量快照。

![dispatch-2025全年总发电量](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_generation.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_generation_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_generation_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_total_generation_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/total_generation_display.csv)。

### 单位装机全年发电量

逐模式全年总发电除以同一有效容量，单位为MWh MW⁻¹ yr⁻¹。三个面板使用独立纵轴。

![dispatch-2025单位装机全年发电量](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_generation.png)

独立子图：[a：风光合计](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_generation_a.png)、[b：风电](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_generation_b.png)、[c：光伏](../paper_figures/supplementary/dispatch_2025/outputs/dispatch2025_unit_generation_c.png)。[数值源表](../paper_figures/supplementary/dispatch_2025/outputs/source_data/unit_generation_display.csv)。


## 复现与验收

- [阶段目标和运行合同](../scnet/dispatch_2025/goal.md)
- [输入准备](../scnet/dispatch_2025/prepare.py)
- [作业生成器](../scnet/create_dispatch_2025_jobs.py)
- [监控与按账号补交](../scnet/dispatch_2025/watch.py)
- [逐事件Loss](../utils/dispatch_station_climate/loss.py)
- [索引与汇总发布](../utils/dispatch_station_climate/publish.py)
- [绘图代码](../paper_figures/supplementary/dispatch_2025/plot.py)

科学计算使用共享代码快照的 `.venv`。每账号所有项目活动作业上限20，提交前持账号锁并重新计数。登录节点仅作调度、元数据处理和已有小型汇总表绘图。冻结任务、源代码/输入SHA256和逐任务回执保存在共享结果根；本地 `scnet/dispatch_2025/completion_status/` 保存状态镜像。

2026-11-16完成全流程验收：

| 阶段 | 已完成数量 | 验收记录（相对于共享结果根） |
|---|---:|---|
| CF / Extreme提取 | 1,360任务；16,320分片 | `future/runtime/extraction_accepted.json` |
| 逐事件Loss | 1,360任务；1,360 NetCDF及1,360中间NPZ | `loss_future/runtime/loss_accepted.json` |
| 汇总发布 | 8组；32年度NPZ | `publish/runtime/publication_groups_accepted.json` |
| 正式索引 | 1,440逐模式行；360集合行 | `runtime/completion.json` |
| 共享读取 | 1866及1870实测通过 | `runtime/formal_access.json` |
| 独立报告副本 | 文件哈希与相对链接核对 | `report/manifest.json`、`runtime/report_access.json` |

最终验收作业 `49192173` 为Slurm COMPLETED/0:0，核对全部逐事件NetCDF的目录ID、时间、事件字段、维度和单位，以及32份年度NPZ的完整目录、容量快照和支持集合；同时检查全球矩阵、能量闭合和共享访问位。发布时检查了43,894个文件、7,021个目录的其他用户读取/遍历权限。正式索引引用的文件总计587,024,190,067字节（不含分块年度中间NPZ、代码和日志）。

绘图验收见 [figure_validation.json](../paper_figures/supplementary/dispatch_2025/outputs/figure_validation.json) 和 [manifest.json](../paper_figures/supplementary/dispatch_2025/outputs/manifest.json)：8张组图、24张独立子图、600 dpi、全部图值与源表一致、30条OLS拟合、组图/独立图纵轴一致；全部PNG已检查文字裁切、图例、范围和阴影。全量图值见 [source_data/](../paper_figures/supplementary/dispatch_2025/outputs/source_data/)，OLS参数见 [trend_fits.csv](../paper_figures/supplementary/dispatch_2025/outputs/source_data/trend_fits.csv)。

准备、提取、Loss和发布均经过首批验证后再运行全矩阵。正式Loss使用1核、单Python进程；发布首批4核，实测最大1.65 GiB后剩余组使用1核，完整发布最大1.79 GiB。全部任务按气候SSP分配到1892/1520，并遵循每账号全项目20个活动作业上限。

本地和1866的 `document/BCSD_v2数据使用指南.md`、`document/风电光伏数据.md`、`document/风电光伏数据.html` SHA256均与任务开始时相同；证据保存在 `runtime/protected_documents_check.json`。

### 最小读取示例

在能读取共享根的远程账号及仓库Python环境中运行：

```python
import hashlib
import json
from pathlib import Path

root = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage")
completion = json.loads((root / "runtime/completion.json").read_text())
index_path = root / "runtime/authoritative_index.json"
assert completion["status"] == "COMPLETED"
assert hashlib.sha256(index_path.read_bytes()).hexdigest() == completion["index_sha256"]
index = json.loads(index_path.read_text())
archive = next(a for a in index["annual_archives"]
               if a["model"] == "MPI-ESM1-2-HR"
               and a["climate_ssp"] == "ssp245"
               and a["station_ssp"] == "ssp126"
               and a["tech"] == "wind")
print(archive["path"])
```

读取年度NPZ时，`capacity_mw`包含完整目录容量；使用 `common_support` 与当年正容量筛选有效汇总站点。读取逐事件NetCDF时，通过 `loss_files[]` 定位；读取原生CF/Extreme时，通过 `entries[]` 的双情景、模式、技术和分块定位，依据实际时间坐标拼接。
