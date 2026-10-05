# RQ1_extreme 极端天气分析图件规划

## 已核对的数据

- 网格 V2 的统一入口为 `/work/share/acjpoxgsdu/extreme_grid/grid_v2/`。后续网格分析使用该目录的 `runtime/authoritative_index.json` 定位输入；结果入口为 `outputs/<model>/<ssp>/<patch>/<tech>/`，包含 `baseline_2015-2024.nc`、10 个时段的 `signals_<start>-<end>.nc`、`audit_2015-2060.json` 及配套元数据。
- 统一索引的 `combinations` 是按 audit unit ID 索引的字典；各组合的 `artifacts[*].unified_output` 和 `unified_audit_output` 指向统一目录。`output`、`audit_output`、`receipt` 保留原始文件路径，`source_run_id` 保留生产运行身份。`runtime/patch_manifest.json` 提供 patch 定义，`runtime/verification.json` 保存汇总检查结果。
- 四模式共 1128 个组合（4 模式 × 3 SSP × 47 patch × 风/光），包括 1128 个基线和 11280 个信号 NetCDF；2026-09-28 汇总检查已核对全部组合、文件可读性、信号文件大小及所有链接，未重读 NetCDF 数组。CANESM5 的 282 个组合来自 `grid_v2_20260922T215235`，其余三个模式的 846 个组合来自 `grid_v2_20260924T165153`；可通过统一目录的 `sources/<RUN_ID>/` 追溯原始运行。统一入口以软链接引用 worker 上的原始文件，原有目录保留原位，后续分析只读这些输入。
- 信号覆盖 2015–2060 年；基线为 2015–2024 年；SSP 为 ssp126、ssp245、ssp585。风电事件为 high_temp、high_wind、hot_humid、icing、low_resource；光伏事件为 cold_highwind、freezing_rain、high_humidity、icing、low_resource、rainstorm。抽查的 sidecar 显示信号变量为 `signal_<event>`，维度含 time、lat、lon 和 `domain_mask`。
- **场站级极端天气提取已完成**，正式入口为 `/work/share/acp6varuz3/extreme_grid/stations_v2/`。后续 `global/station` 与 `country/station` 直接读取该目录的独立场站事件结果。四模式、三 SSP、47 patch、风/光共 1128 个组合，其中 864 个非空组合各有 10 个时段文件，共 **8,640 个 NC**；另 **264 个空组合**已记录跳过证据。
- 场站结果以 `stations_v2/runtime/authoritative_index.json` 为读取入口，其 `kind` 为 `station-event-index`，当前 `schema` 为 `station-extreme-v1`。`combinations` 按 `<model>/<ssp>/<patch>/<tech>` 索引；非空组合的 `status=COMPLETED`，通过 `outputs[*].artifact.path` 定位场站 NC，通过 `outputs[*].period` 确定时段。`outputs[*].source` 记录上游网格来源。统一发布目录为 `outputs/<model>/<ssp>/<patch>/<tech>/signals_<start>-<end>.nc`，附带同名 `.nc.json` 和 `audit_2015-2060.json`；按索引追溯实际文件和来源。
- 空组合的 `status=SKIPPED_NO_STATIONS`、`outputs=[]`，证据由 `audit.path` 指向；这是该组合没有场站的有效状态，不要求补齐 NC，也不解释为零暴露。存在场站但映射或事件数据缺测的情况，按有效性和覆盖率单独处理。
- **验收与读取验证已通过**：`runtime/final_acceptance.json` 状态为 `ACCEPTED`，`runtime/completion_summary.json` 状态为 `COMPLETED`；读取验证作业 `45457474` 的 **48 项检查全部通过**，涵盖 `365_day` 和 `proleptic_gregorian` 日历。报告路径由 `completion_summary.json` 的 `identity.reader_report.path` 给出，进度总表为 `completion_status/progress.md`。本次文档更新核对了这些既有记录、索引和配套表头，未重新扫描全部 NC。
- 场站位置、启用年份及容量以场站发布索引引用的目录为准：`catalogs[ssp].catalogs[tech].path` 指向 `stations.csv.gz`（字段 `lon,lat,activation_year,station_id`），`catalogs[ssp].files` 中的 `capacity_rows.csv.gz` 提供 `capacity_gw,lat,lon,type,year,source_row,station_id`。场站事件与容量按 SSP、技术和 `station_id` 关联，并保留年度容量记录的 `year` 和来源 `source_row`。仓库 `data/stations/` 的原始场站表可用于溯源；SSP5-6.0 场站表仍对应 `ssp585`。国家归属如复用 `utils/country_patch_mapping/generated/stations_<ssp>.csv`，需按坐标和技术核对关联，不能直接把其中的 `station_key` 当作发布结果的 `station_id`。

## 目录与统一口径

```text
RQ1_extreme/
├── global/
│   ├── grid/       # 全球网格分析代码与 PNG/表格结果
│   └── station/    # 全球场站分析代码与 PNG/表格结果
└── country/
    ├── grid/       # 各国网格分析代码与 PNG/表格结果
    ├── station/    # 各国场站分析代码与 PNG/表格结果
    └── distribution_maps/ # 各国网格底色与场站容量圆的分布地图
```

按模型、SSP、技术分别汇总，再对四个模式等权平均，并显示模式范围；不把四模式的格点或场站直接拼成一个总体。主时间窗建议采用 2030–2039、2040–2049、2050–2059 年，与现有损失分析对齐；年度曲线保留 2015–2060 年。二值事件先按时间步求并集，再换算“任一事件暴露天数”；事件类型单独统计时允许同一时间步重复计入，因此类型总和不等于并集。统计只包含有效陆地/国家格点，不把缺测当作零；网格平均按格点面积加权；场站级统一使用单位装机暴露时长，分母仅包含当年有效场站的装机容量。年天数按数据时间坐标确定。

### 场站级指标：单位装机暴露时长

对每个模式、SSP、技术和统计范围（全球、国家或固定队列），先计算单站年度暴露天数，再按装机容量归一化：

$$
D_{i,y} = \sum_{t\in y} \mathbf{1}\!\left(\bigcup_e E_{i,t,e}\right)\Delta t_{\mathrm{day}},
\qquad
T_y = \frac{\sum_{i\in S_y} C_{i,y}D_{i,y}}{\sum_{i\in S_y} C_{i,y}}.
$$

其中，$E_{i,t,e}$ 表示场站 $i$ 在时间步 $t$ 是否遭遇事件 $e$；$\Delta t_{\mathrm{day}}$ 为时间步对应的天数；$S_y$ 为当年已投产且暴露数据、容量均有效的场站集合，$C_{i,y}>0$ 为其装机容量。分子为容量暴露量（GW·天），分母为有效总装机容量（GW）；$T_y$ 表示每单位装机在该年的平均暴露时长，年度图标注为“单位装机暴露时长（天/年）”。单站该指标等于其年暴露天数；跨场站汇总等价于容量加权平均。有效总容量为零时记为缺测。

这一指标采用与单位装机损失（总损失能量 / 有效总装机容量）一致的容量归一化口径。各事件分别计算时，将并集指示量替换为对应事件指示量，分母口径相同。年代值取逐年 $T_y$ 的平均，变化量为未来年代均值减基线均值（天/年）；完成每个模式内的容量归一化后，再对四模式等权汇总。高暴露容量占比和绝对 GW 作为辅助指标。

## 建议图件

| 位置 | 优先级 | 图件与问题 | 指标和展示 |
|---|---|---|---|
| `global/grid` | 主图 | 全球网格任一事件暴露轨迹：各 SSP 的气候背景如何变化？ | 风、光分面；年度有效陆地格点的单位面积暴露时长（天/年），四模式均值与模式范围。 |
| `global/grid` | 主图 | 2050 年代暴露变化地图：变化发生在哪里？ | 各格点的 2050–2059 年减 2015–2024 年任一事件年均天数；风、光及 SSP 分面，统一色标；另列有效覆盖率。 |
| `global/grid` | 补图 | 事件类型如何变化？ | 各事件独立的面积加权暴露天数及未来减基线的差值，分组点图或柱图；注明事件重叠。 |
| `global/station` | 主图 | 场站实际暴露轨迹是否不同于网格背景？ | 依据 `stations_v2` 独立结果及映射，关联 2030/2040/2050 容量快照，给出对应年份单位装机任一事件暴露时长（天/年）；风、光和 SSP 分面，与网格年度面积加权轨迹对照，其余容量年份不插补。 |
| `global/station` | 主图 | 固定场站队列会否转入高暴露？ | 固定 2030 位置队列及其 2030 容量权重，给出 2030–2060 年暴露轨迹和到 2040/2050 年的新进入/持续/退出高暴露容量占比；各模式固定使用自身的 2030 容量加权 P80。 |
| `global/station` | 补图 | 首次出现位置的容量暴露如何？ | 2030/2040/2050 首次出现位置队列在对应年份的高暴露容量占比；2030 为基准库存，首次出现不等同于实际投产，不包含已有位置扩容。 |
| `country/grid` | 主图 | 哪些国家的网格背景变化最大？ | 国家 × SSP 热图：2050 年代减基线的国境内有效陆地面积加权任一事件天数，风、光分图；保留国家有效格点面积及覆盖率。 |
| `country/grid` | 补图 | 国家之间的差异是否随时间扩大？ | 重点国家的年度/年代轨迹与四模式范围；固定包含中国、美国、印度、德国、南非、澳大利亚、俄罗斯、巴西，并合并变化排名前 6 的国家、去重；按国家内格点聚合，不以 patch 代表国家。 |
| `country/station` | 主图 | 哪些国家的场站暴露变化最大？ | 国家 × SSP 热图：2050 年代减基线的单位装机任一事件暴露时长变化（天/年）；旁列有效场站数、有效容量及国家覆盖率。 |
| `country/station` | 补图 | 哪些国家的固定队列新增高暴露容量最多？ | 2030 投产队列到 2050 年的新进入高暴露容量占比或绝对 GW，按国家排序；样本量不足的国家单独标记。 |

## 与 `origin/master:RQ2` 的对应关系

- `plot_RQ2_extreme_exposure_timeseries_unweighted.py`、`...capacity_weighted.py`、`...rate_capacity_weighted.py`：借鉴年度轨迹的展示；网格级采用空间面积加权，场站级使用 `stations_v2` 已提取的四模式场站事件结果，关联容量后统一计算单位装机暴露时长。
- `plot_RQ2_extreme_exposure_event_area_capacity_weighted.py`、`...change_stacked.py`：借鉴事件分解及变化问题；本轮按事件分别呈现，明确重复暴露，不把堆叠高度解释为任一事件天数。
- `plot_RQ2_1_cohort_risk_trajectory.py`、`...cohort_transition.py`、`...newbuild_highrisk_share.py`、`...country_heatmap.py`：借鉴固定队列、新建容量和国家热图。旧脚本以 NESM3/区域 Pipeline B 场站文件为默认输入；本轮分析输入为 `stations_v2` 独立场站结果及其配套容量目录。

## 输入衔接与实施状态

1. **网格级分析已实现并完成全量运行**：全球和国家入口分别为 `global/grid/global_grid_extremes.py`、`country/grid/country_grid_extremes.py`。全球年度缓存清单为 `global/grid/outputs/cache_manifest.json`；国家分析复用该缓存，结果见各自 `outputs/`，运行与验证记录见目录 README 和 `VALIDATION.md`。场站与网格对照图可直接引用网格年度汇总表。
2. **场站提取与验收已完成；国家分布地图与全球场站分析已实现，国家场站轨迹和队列分析继续推进**：
   - 从 `/work/share/acp6varuz3/extreme_grid/stations_v2/runtime/authoritative_index.json` 枚举组合，读取 `COMPLETED` 组合的 `outputs[*].artifact.path`；按时段和 `station_id` 对齐，同一场站不因分文件或跨时段而重复计入。对 `SKIPPED_NO_STATIONS` 保留审计状态。
   - 在计算节点分块读取 `signal_<event>`，按原生时间坐标与日历计算单站年度事件天数、任一事件并集天数和有效时间覆盖率。事件并集与分项共用有效时间掩膜，年度有效时间默认沿用网格级 99% 门槛；不将缺测或未成功映射的场站记为零暴露。
   - 关联发布索引中的 `stations.csv.gz`、`capacity_rows.csv.gz`：用 `activation_year` 识别启用年份，结合逐年容量记录确定活跃场站和固定队列。容量记录的 `year` 不直接等同于投产年份；队列按启用年份定义，确认其业务含义后解释为投产队列。按前述公式先在每个模式内计算单位装机暴露时长，再做四模式等权汇总。
   - 全球场站汇总输出年度/年代轨迹、与网格背景的对照及队列分析；国家场站汇总补充国家归属，输出国家热图和队列变化。同步记录有效场站数、有效容量和覆盖率，容量为零或无有效样本时记为缺测。完成单站年度汇总后，全球与国家场站分析可分别复用同一份年度结果。
3. **全球场站已采用固定 P80 高暴露阈值**：沿用 `master/RQ2` 的 2030 队列容量加权 P80，应以单站单位装机暴露时长（即该站年暴露天数）为排序变量、装机容量为权重，在每个模式、SSP、技术的 2030 基准队列上计算，并将阈值（天/年）固定到后续年份；高暴露容量占比以对应有效队列容量为分母，另输出阈值表与样本量。网格级不套用场站容量阈值。

所有实际绘图和大文件读取都通过计算节点 SLURM 作业执行；只保存 PNG，汇总表保留 CSV。场站独立结果及读取验证已就绪；国家网格—场站分布地图和全球场站轨迹、队列分析已实现；国家场站轨迹与队列分析仍待实现。

## 国家网格—场站分布地图（country/distribution_maps）

新增代码、说明和结果入口为 [country/distribution_maps](country/distribution_maps/README.md)。制作四张 Cartopy Plate Carrée 世界地图：2050 年代风光分开（2×3）、风光合并（1×3），以及对应的 2050 年代减 2030 年代变化图。

- 绝对值图的底色为国家有效陆地格点的单位面积任一事件暴露时长；风光合并底色为风电值与光伏值相加。
- 圆面积与 2050 年容量快照成正比，圆颜色为这组容量在 2050–2059 年的单位装机任一事件暴露时长。风光合并圆的容量为两者总和，颜色按有效容量加权。
- 变化图只将底色替换为 2050–2059 减 2030–2039 年均值，圆始终保持 2050 年代容量与暴露。这里的 2030 年代基线专用于这组地图。
- 指标单位为天/年；单位面积指标 = 面积暴露量 / 有效面积，单位装机指标 = 容量暴露量 / 有效容量。技术内按事件时间并集计算；合并底色的风光相加允许大于 365 天/年。
- 每个模式先计算年度和完整年代均值，再对四模式等权平均。输出总容量、有效容量、场站数与覆盖率；缺测不作为零。
- 网格底色直接复用 `country/grid/outputs/<model>/csv/country_annual_exposure.csv`。场站映射、容量与元数据来自 `stations_v2` 正式发布索引；核对场站与网格来源、事件集合、映射、坐标及 `activation_mask=off` 后，复用网格年度缓存计算场站年度暴露，并用原始场站事件序列抽查验证。
- 入口为 `prepare_country_exposure.py/.sh`（16 核、56 GB）与 `plot_country_exposure_maps.py/.sh`（4 核、14 GB），均在该目录。四张 PNG 位于 `outputs/figures/`；清洁数据表为 `outputs/csv/country_map_metrics.csv`，包含四模式分别值及 `ensemble_mean`。

## 全球场站分析（global/station）

入口为 [global/station/README.md](global/station/README.md)，主脚本 `global_station_extremes.py/.sh`，默认 16 进程、16 核、56 GB。输出五张四模式均值/范围 PNG：全球场站与网格对照、固定 2030 队列暴露轨迹、2030 队列到 2040/2050 的高暴露状态转变、首次出现位置队列高暴露容量占比、有效容量覆盖率。

本次核对确认发布容量只有 2030/2040/2050 三个快照，`activation_year` 为位置首次出现年份。默认活跃场站图仅画三个快照年份实值；年度表保留 2015–2060，其余容量年份记为缺测。固定 2030 队列用固定 2030 权重展示 2030–2060 年气候暴露。首次出现位置不能直接解释为真实投产；2030 代表基准库存，后续首次出现队列不含已有位置的容量扩张。

高暴露采用各模式、SSP、技术自身的 2030 队列容量加权 P80，严格以“暴露 > P80”分类，阈值固定到后续年份。转变比例按两年均有效的配对位置及其 2030 容量计算，四类相加为 100%，同时记录配对覆盖率。绘图的误差线/阴影为四模式最小–最大范围，不是置信区间。

单站 2015–2060 年度缓存保存在 `global/station/outputs/cache/<model>/<ssp>_<tech>.nc`，附同名来源与原始序列抽查 JSON，可供后续国家场站分析复用。缓存通过发布映射从既有网格年度结果提取，并核对全部 10 段场站文件元数据。全球 2050 年结果与国家分布地图的既有缓存（包括 UNASSIGNED）核对容量和容量暴露量。正式 PNG 位于 `outputs/figures/`，模式分别值及均值/范围 CSV 位于 `outputs/csv/`。
