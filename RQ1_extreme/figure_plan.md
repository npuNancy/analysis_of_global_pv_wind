# RQ1_extreme 极端天气分析图件规划

## 已核对的数据

- 网格 V2 的统一入口为 `/work/share/acp6varuz3/extreme_grid/grid_v2/`。后续网格分析与场站取样统一使用该目录的 `runtime/authoritative_index.json` 定位输入；结果入口为 `outputs/<model>/<ssp>/<patch>/<tech>/`，包含 `baseline_2015-2024.nc`、10 个时段的 `signals_<start>-<end>.nc`、`audit_2015-2060.json` 及配套元数据。
- 统一索引的 `combinations` 是按 audit unit ID 索引的字典；各组合的 `artifacts[*].unified_output` 和 `unified_audit_output` 指向统一目录。`output`、`audit_output`、`receipt` 保留原始文件路径，`source_run_id` 保留生产运行身份。`runtime/patch_manifest.json` 提供 patch 定义，`runtime/verification.json` 保存汇总检查结果。
- 四模式共 1128 个组合（4 模式 × 3 SSP × 47 patch × 风/光），包括 1128 个基线和 11280 个信号 NetCDF；2026-09-28 汇总检查已核对全部组合、文件可读性、信号文件大小及所有链接，未重读 NetCDF 数组。CANESM5 的 282 个组合来自 `grid_v2_20260922T215235`，其余三个模式的 846 个组合来自 `grid_v2_20260924T165153`；可通过统一目录的 `sources/<RUN_ID>/` 追溯原始运行。统一入口以软链接引用 worker 上的原始文件，原有目录保留原位，后续分析只读这些输入。
- 信号覆盖 2015–2060 年；基线为 2015–2024 年；SSP 为 ssp126、ssp245、ssp585。风电事件为 high_temp、high_wind、hot_humid、icing、low_resource；光伏事件为 cold_highwind、freezing_rain、high_humidity、icing、low_resource、rainstorm。抽查的 sidecar 显示信号变量为 `signal_<event>`，维度含 time、lat、lon 和 `domain_mask`。
- 场站位置与容量来自远端 `data/stations/stations_SSP1-2.6.csv`、`stations_SSP2-4.5.csv`、`stations_SSP5-6.0.csv`（字段为 year、type、lon、lat、capacity_gw）；`utils/country_patch_mapping/generated/stations_<ssp>.csv` 补充 station_key、国家及 patch。按仓库现有约定，SSP5-6.0 场站表对应 `ssp585`。本轮场站暴露从四模式网格 V2 的二值事件按场站位置取样，不依赖旧的 `data/extreme_event_outputs/station_signals_pipelineB`。

## 目录与统一口径

```text
RQ1_extreme/
├── global/
│   ├── grid/       # 全球网格分析代码与 PNG/表格结果
│   └── station/    # 全球场站分析代码与 PNG/表格结果
└── country/
    ├── grid/       # 各国网格分析代码与 PNG/表格结果
    └── station/    # 各国场站分析代码与 PNG/表格结果
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

这一归一化口径与 `RQ4` 的单位装机损失（总损失能量 / 有效总装机容量）对应。各事件分别计算时，将并集指示量替换为对应事件指示量，分母口径相同。年代值取逐年 $T_y$ 的平均，变化量为未来年代均值减基线均值（天/年）；完成每个模式内的容量归一化后，再对四模式等权汇总。高暴露容量占比和绝对 GW 作为辅助指标。

## 建议图件

| 位置 | 优先级 | 图件与问题 | 指标和展示 |
|---|---|---|---|
| `global/grid` | 主图 | 全球网格任一事件暴露轨迹：各 SSP 的气候背景如何变化？ | 风、光分面；年度有效陆地格点的面积加权暴露天数（天/格点年），四模式均值与模式范围。 |
| `global/grid` | 主图 | 2050 年代暴露变化地图：变化发生在哪里？ | 各格点的 2050–2059 年减 2015–2024 年任一事件年均天数；风、光及 SSP 分面，统一色标；另列有效覆盖率。 |
| `global/grid` | 补图 | 事件类型如何变化？ | 各事件独立的面积加权暴露天数及未来减基线的差值，分组点图或柱图；注明事件重叠。 |
| `global/station` | 主图 | 场站实际暴露轨迹是否不同于网格背景？ | 对网格事件按场站位置和时间取样后，给出活跃场站的单位装机任一事件暴露时长（天/年），风、光和 SSP 分面，与网格面积加权暴露轨迹对照。 |
| `global/station` | 主图 | 固定场站队列会否转入高暴露？ | 2030 年投产队列在 2030/2040/2050 年的单位装机任一事件暴露时长（天/年），以及新进入/持续/退出高暴露的容量占比；固定基准阈值。 |
| `global/station` | 补图 | 新建容量投产时暴露如何？ | 2030/2040/2050 年投产队列在投产年按单位装机暴露时长判定的高暴露容量占比；与固定队列转变分开展示。 |
| `country/grid` | 主图 | 哪些国家的网格背景变化最大？ | 国家 × SSP 热图：2050 年代减基线的国境内有效陆地面积加权任一事件天数，风、光分图；保留国家有效格点面积及覆盖率。 |
| `country/grid` | 补图 | 国家之间的差异是否随时间扩大？ | 重点国家的年度/年代轨迹与四模式范围；固定包含中国、美国、印度、德国、南非、澳大利亚、俄罗斯、巴西，并合并变化排名前 6 的国家、去重；按国家内格点聚合，不以 patch 代表国家。 |
| `country/station` | 主图 | 哪些国家的场站暴露变化最大？ | 国家 × SSP 热图：2050 年代减基线的单位装机任一事件暴露时长变化（天/年）；旁列有效场站数、有效容量及国家覆盖率。 |
| `country/station` | 补图 | 哪些国家的固定队列新增高暴露容量最多？ | 2030 投产队列到 2050 年的新进入高暴露容量占比或绝对 GW，按国家排序；样本量不足的国家单独标记。 |

## 与 `origin/master:RQ2` 的对应关系

- `plot_RQ2_extreme_exposure_timeseries_unweighted.py`、`...capacity_weighted.py`、`...rate_capacity_weighted.py`：借鉴年度轨迹的展示；网格级采用空间面积加权，场站级由本轮四模式网格信号按场站位置取样，统一计算单位装机暴露时长。
- `plot_RQ2_extreme_exposure_event_area_capacity_weighted.py`、`...change_stacked.py`：借鉴事件分解及变化问题；本轮按事件分别呈现，明确重复暴露，不把堆叠高度解释为任一事件天数。
- `plot_RQ2_1_cohort_risk_trajectory.py`、`...cohort_transition.py`、`...newbuild_highrisk_share.py`、`...country_heatmap.py`：借鉴固定队列、新建容量和国家热图。旧脚本以 NESM3/区域 Pipeline B 场站文件为默认输入；四模式 V2 的场站暴露由场站坐标匹配网格事件生成。

## 开始绘图前需要确定的输入

1. 网格级：读取 `/work/share/acp6varuz3/extreme_grid/grid_v2/runtime/authoritative_index.json`，按各组合 `artifacts[*].unified_output` 定位全部网格文件；在计算节点核对 NetCDF 的时间步长、坐标、掩膜和事件值，先生成按年、patch、格点汇总的轻量中间表。跨 patch 边界去重；国家边界应对格点栅格化，不能把跨国 patch 全部归给一个国家。
2. 场站级：以 `data/stations/` 的经纬度、投产年、技术和容量为基础，结合 `stations_<ssp>.csv` 的 station_key、国家和 patch；在计算节点把场站匹配到所属 patch 的有效网格格点，按时间步提取各 `signal_<event>`，生成四模式场站事件序列。二值事件采用格点取样，不做数值插值；核对经度约定、边界归属、格点有效掩膜、场站去重以及 `SSP5-6.0`→`ssp585` 对应关系。网格信号本身不含场站容量；需关联容量后，逐年汇总容量乘暴露时长，再除以对应有效总容量，生成全球、国家及队列的单位装机暴露时长。
3. 高暴露阈值：若采用 `master/RQ2` 的 2030 队列容量加权 P80，应以单站单位装机暴露时长（即该站年暴露天数）为排序变量、装机容量为权重，在每个模式、SSP、技术的 2030 基准队列上计算，并将阈值（天/年）固定到后续年份；高暴露容量占比以对应有效队列容量为分母，另输出阈值表与样本量。网格级不套用场站容量阈值。

所有实际绘图和大文件读取都通过计算节点 SLURM 作业执行；只保存 PNG，汇总表保留 CSV。全球和国家网格分析入口分别为 `global/grid/global_grid_extremes.py` 与 `country/grid/country_grid_extremes.py`，运行说明见各目录 README；国家分析复用全球年度缓存。场站绘图待独立场站事件结果文件准备完成后实现。
