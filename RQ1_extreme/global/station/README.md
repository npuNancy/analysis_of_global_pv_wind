# 全球场站极端天气分析

## 图件与问题

使用 Python / matplotlib，风电、光伏为两行，三个 SSP 为三列；每个模式独立汇总，再显示四模式等权均值和最小–最大范围。所有正式图片为 300 dpi PNG、3750×2040 像素，源数据保留 CSV。

| 图片（outputs/figures） | 对应规划及读图方式 |
|---|---|
| global_station_vs_grid.png | 活跃容量的单位装机暴露与全球陆地单位面积暴露对照。橙色为网格年度曲线；蓝色为有容量快照年份的场站实值及四模式范围。 |
| global_station_cohort_exposure.png | 固定 2030 位置队列、固定 2030 容量权重，展示 2030–2060 年的气候暴露。灰色虚线为四模式各自 P80 阈值的均值，实际分类始终使用各模式自己的阈值。 |
| global_station_cohort_transitions.png | 2030 队列到 2040/2050 年的持续非高、新进入高、持续高、退出高四类容量占比；条形为均值，误差线为模式范围。 |
| global_station_newbuild_high_exposure.png | 2030/2040/2050 首次出现位置队列在首次出现年份的高暴露容量占比。2030 为基准库存；标签说明位置出现与实际投产的区别。 |
| global_station_capacity_coverage.png | 活跃快照与固定 2030 队列的有效容量覆盖率，解释映射或事件缺测对分母的影响。 |

这是描述性对照；模式范围不是置信区间，不作显著性检验。国家未分配的有效场站也纳入全球汇总。

## 数据能够支持的时间与队列口径

发布容量目录仅有 **2030、2040、2050 三个年份的快照**，没有 2015–2060 逐年装机序列。按用户确认的三个快照年份口径：

- 全球活跃场站暴露只计算三个容量快照年份；2015–2060 年度 CSV 其余年份保留为缺测，图中不补造容量。
- 网格背景覆盖 2015–2060；固定 2030 位置队列可用不变的 2030 权重评估 2030–2060 逐年气候暴露。
- `activation_year` 对应坐标位置首次出现在发布快照中的年份，无法证明其实际建设/投产年份。2030 队列包含基准库存；2040/2050 队列只计首次出现的位置，不包括已有位置的容量扩张。
- 固定队列采用固定 2030 权重，隔离位置和容量结构变化；不将其解释为已验证的设备寿命、持续运营或退役预测。

## 指标

事件采用技术内 `signal_<event>` 的时间并集 `any`，单站年度暴露按原生日历与时间步计算，年度时间覆盖率至少 99%。技术内事件重叠只算一次。

$$
T_y=\frac{\sum_{i\in S_y} C_iD_{i,y}}{\sum_{i\in S_y}C_i}.
$$

其中 $S_y$ 只含正容量且年度暴露有效的场站，$D_{i,y}$ 单位为天；$T_y$ 是单位装机暴露时长（天/年）。快照图用当年容量，固定队列图用 2030 容量；总容量与有效容量、场站数、覆盖率同时输出，缺测不记为零。

高暴露定义沿用规划与 master/RQ2：

1. 在每个模式、SSP、技术的 2030 队列中，以单站 2030 年暴露为排序值、2030 容量为权重，计算加权经验分布 P80：累计容量首次达到 80% 的暴露值。
2. 后续年份固定该阈值，严格使用“暴露 > P80”；并列值不会被人为拆分，基准高暴露容量占比可小于 20%。
3. 状态转变只使用 2030 和目标年暴露都有效的配对位置，分母为这些位置的 2030 容量。四类比例合计 100%；配对覆盖率另存 CSV。
4. 首次出现队列在对应年份用该快照容量加权，仍使用同模式、同 SSP、同技术的 2030 固定阈值。

## 缓存与输入复用

- 入口：`stations_v2/runtime/authoritative_index.json` 的 1128 个组合；864 个非空组合及 264 个空组合证据。
- 复用 `../grid/outputs/cache_manifest.json` 的 2015–2060 年度格点 `event_days[any]`，按照发布场站的映射索引提取。场站结果的激活掩膜关闭；先核对来源身份、全部 10 段文件元数据、事件集合、映射身份、场站顺序、格点坐标及域归属。
- 新增 24 份单站年度 NetCDF，保存 `station_id`、坐标、patch、首次出现年份、映射状态、三个快照容量、46 年暴露值。缓存保留未应用容量/启用筛选的潜在暴露，具体统计时使用相应容量与队列。
- 每个模式/SSP/技术从实际场站文件抽查一处有效映射与一处无效映射位置，重新计算全部 46 年并与缓存核对。来源及抽查记录写入同名 JSON。
- 缓存指纹包含站点索引、网格清单和提取函数身份，复用时验证 NetCDF 内容哈希。改绘图样式不触发单站缓存重建。
- 与先前国家分布地图的 2050 年年度缓存核对全球总容量、有效容量及 GW·天，包括 UNASSIGNED 行；避免把国家平均值直接平均成全球值。

## 运行

脚本与同名 SLURM：`global_station_extremes.py/.sh`，默认 16 进程、16 核、56 GB，wzhctest，使用仓库 .venv。所有分析和绘图在计算节点执行。

```bash
mkdir -p logs/RQ1_extreme/global/station
job=$(sbatch --parsable RQ1_extreme/global/station/global_station_extremes.sh)
sbatch --dependency=afterok:"$job" RQ1_extreme/global/station/test_global_station_extremes.sh

# 汇总表已生成时只重画，沿用保存的容量口径
sbatch RQ1_extreme/global/station/global_station_extremes.sh --plot-only
```

`test_global_station_extremes.py/.sh` 使用 1 核、3.5 GB，测试加权、P80 并列值、配对分母、四模式完整性及实际结果。

```text
outputs/
├── cache/<model>/<ssp>_<tech>.nc + .json
├── cache_manifest.json
├── run_config.json
├── validation.json
├── csv/
│   ├── annual_by_model.csv / annual_ensemble.csv
│   ├── cohort_by_model.csv / cohort_ensemble.csv
│   ├── transitions_by_model.csv / transitions_ensemble.csv
│   ├── newbuild_by_model.csv / newbuild_ensemble.csv
│   ├── thresholds_by_model.csv / thresholds_ensemble.csv
│   └── grid_comparison_by_model.csv / grid_comparison_ensemble.csv
├── figures/  # 5 张正式 PNG 与 figure_manifest.json
└── qa/       # 等比例预览 PNG
```

运行与图片验收记录见 `VALIDATION.md`。
