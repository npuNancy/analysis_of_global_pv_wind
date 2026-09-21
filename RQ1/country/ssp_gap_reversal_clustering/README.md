# 国家单位装机损失情景差反转分类

`ssp_gap_reversal_clustering.py` 按前期（2030s）与后期（2050s）SSP585−SSP126
单位装机损失差的符号把国家分成固定四类，不做 Ward 聚类：

| 类 | 前期 (2030s) | 后期 (2050s) | 含义 |
|---|---|---|---|
| C1 | + | + | SSP585 持续更高 |
| C2 | + | − | 情景差反转为 SSP126 更高 |
| C3 | − | + | 情景差反转为 SSP585 更高 |
| C4 | − | − | SSP585 持续更低 |

差值恰为零按正号处理；2040s 不参与分类（仍出现在轨迹图中）。

数据读取、国家映射、零覆盖场站过滤、事件组成和绘图完全复用
`../ssp_gap_clustering/` 的实现（import 复用，不复制代码）；指标、样本筛选与
模式集合口径与该目录一致（ensemble 为四模式国家年代单位损失先等权平均、
仅保留四模式完整的国家）。

## 运行

在仓库根目录提交 SLURM 作业：

```bash
mkdir -p logs/RQ1/country/ssp_gap_reversal_clustering
sbatch RQ1/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering.sh
```

作业使用 `wzhctest` 队列、1 节点、4 核和 14 GB 内存（与情景差聚类相同）。
`#SBATCH` 日志路径相对提交目录；脚本内仓库位置由 `$HOME` 推导，可在不同
超算账号下直接提交。

## 图形

每个模式与 `ensemble_mean` 输出三类图 × 风光（PNG，600 dpi）：

1. `country_cluster_trajectories_<tech>.png`：四类中心折线（粗线）+ 类内
   国家曲线（细线、高透明度）+ 逐年代范围着色，画法同情景差聚类。
2. `country_cluster_event_composition_<tech>.png`：2050s 正净损失事件池组成。
   左图为全部国家的国家等权平均（两柱：SSP126/SSP585）；右图按四类分组
   （每类两柱），左右宽度比 1 : 4。事件可重叠，占比为组内正损失池份额。
3. `cluster_map_<model>_<tech>.png`：Plate Carrée 世界地图，按类别给国家上色，
   复用 `../ssp_gap_clustering/map_country_clusters.py`；被剔除国家不上色。

空类仍保留编号与颜色（C1 深蓝、C2 红、C3 青、C4 紫），保证跨模式图例一致。

## 输出

```text
ssp_gap_reversal_clustering/outputs/
├── CANESM5/ ... BCC-CSM2-MR/
└── ensemble_mean/
    ├── csv/
    │   ├── country_unit_loss_decade.csv      # 国家年代单位损失（同上游口径）
    │   ├── country_cluster_assignments.csv  # 国家类别标签与符号模式
    │   └── country_cluster_summary.csv      # 各类中心范围与成员国
    ├── figures/
    └── run_config.json
```
