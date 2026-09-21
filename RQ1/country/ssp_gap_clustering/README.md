# 国家单位装机损失情景差聚类

`country_unit_loss_clustering.py` 对各国 SSP585−SSP126 单位装机损失差的
年代曲线做 Ward 层次聚类，并输出聚类曲线、国家热差图和聚类事件组成三类图。
输入与 `RQ1/global` 相同的年度场站 NetCDF（`data/loss_outputs`），无需重算上游。

## 分析口径

- 技术：风电、光伏分别聚类。
- 指标：国家单位装机损失（MWh MW⁻¹ yr⁻¹）= 该国年度净损失总和 / 该国过滤后
  装机总和，再对快照内十年取平均；仅使用 `ssp126` 和 `ssp585`。
- 场站过滤：与 `RQ1/global` 相同，逐年剔除 `normal_all_generation_mwh_all <= 0`
  的零覆盖场站（BCSD 气象缺失）。
- 国家归属：场站按 NetCDF 内 `lon/lat` 与
  `utils/country_patch_mapping/generated/stations_<ssp>.csv` 按快照年连接
  （经度转 `[-180,180)`、三维小数匹配）；无法匹配的场站会报错终止。
- 特征：三个年代点的 `unit_loss(ssp585) − unit_loss(ssp126)`，正值表示 SSP585 损失更高。
  仅保留两个情景、三个年代均有完整值的国家。
- 方法：Ward 层次聚类（欧氏距离、optimal_ordering）；在每类至少 2 国的约束下
  以轮廓系数选 k（无有效候选时放宽约束并在诊断表标记）；类别按平均差从高到低编号；
  200 次小扰动重采样给出国家归属稳定率。
- 模式集合：先对四个模式的国家级年代单位损失逐国等权平均，再对平均曲线聚类
  （与逐模式聚类后平均标签不同）。

## 运行

在仓库根目录提交 SLURM 作业：

```bash
mkdir -p logs/RQ1/country
sbatch RQ1/country/ssp_gap_clustering/country_unit_loss_clustering.sh
```

作业使用 `wzhctest` 队列、1 节点、4 核和 14 GB 内存。读取阶段按
`model × SSP × technology`（每模式 4 个单元）并行，worker 数默认取
`SLURM_CPUS_PER_TASK`；一次只加载一个模式，因此 4 核足够。
`#SBATCH` 日志路径相对提交目录（仓库根目录），脚本内仓库位置由
`$HOME/project_climate_patchify/repos/analysis_of_global_pv_wind` 推导，
可在不同超算账号下直接提交。

常用参数（`--k-min/--k-max/--min-cluster-size/--bootstrap/--noise-scale/--seed`）
与 `RQ4/ssp126_ssp585_loss_gap_clustering` 一致，另有 `--workers` 限制并行度。

## 图形

每个模式与 `ensemble_mean` 输出三张图 × 风光两类（PNG，600 dpi）：

1. `country_cluster_trajectories_<tech>.png`：聚类中心折线（粗线）+ 类内国家
   逐年曲线（细线，高透明度）+ 类内逐年代范围着色（同色 alpha=0.18），
   类似 `RQ1/global` 年度图的画法。
2. `country_gap_heatmap_<tech>.png`：国家 × 年代情景差热图（RdBu_r，红=SSP585
   更高），行按聚类再按树图叶序排列，聚类之间用粗黑横线分隔，行标签着聚类色。
3. `country_cluster_event_composition_<tech>.png`：2050s 正净损失事件池组成。
   左图为全部国家的国家等权平均（两柱：SSP126/SSP585）；右图按聚类分组
   （每类两柱）。左右宽度比例随聚类数自适应（1 : 聚类数）。
   事件可重叠，占比为组内正损失池份额，不能相加解释为 all 净损失。
   另有 `country_cluster_event_composition_no_low_resource_<tech>.png`：
   剔除低资源事件后在剩余事件正损失池内重新归一化的同版图（标题标注
   excl. low resource）。

## 输出

```text
RQ1/country/ssp_gap_clustering/outputs/
├── CANESM5/
├── MPI-ESM1-2-HR/
├── MRI-ESM2-0/
├── BCC-CSM2-MR/
└── ensemble_mean/
    ├── csv/
    │   ├── country_unit_loss_decade.csv      # 国家年代单位损失
    │   ├── country_cluster_assignments.csv  # 国家聚类标签与稳定率
    │   ├── country_cluster_summary.csv      # 各类中心范围与成员国
    │   └── cluster_k_diagnostics.csv        # k 候选与轮廓系数
    ├── figures/
    └── run_config.json
```
