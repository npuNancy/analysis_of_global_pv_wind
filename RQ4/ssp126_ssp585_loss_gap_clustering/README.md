# RQ4 国家损失 trade-off 聚类

本目录根据各国 SSP126–SSP585 损失差的年代曲线进行层次聚类，并分析各类内部的极端事件损失构成。

## 分析口径

- 技术：风电、光伏分别聚类。
- 指标：绝对损失、相对损失率、单位装机损失、单位场站损失分别聚类。
- 特征：三个年代点的 SSP126–SSP585 对称相对差，正值表示 SSP126 更高。
- 样本：仅使用两个情景和三个年代均有完整数据的国家；缺失值不填零。
- 方法：Ward 层次聚类；在满足每类至少两个国家的前提下，以轮廓系数选择类别数。
- 稳定性：对特征进行小幅随机扰动并重复聚类，输出每个国家的归属稳定率。
- 事件构成：使用各事件的正净损失构造描述性事件池，同时保留原始负净损失数量。由于事件可能重叠，事件池占比不解释为对 `all` 净损失的互斥归因。

当前上游风电能量字段被错误放大10倍，读取正式国家年度表时会将风电发电量和损失能量字段临时乘以0.1。上游数据修复后需移除此修正并重跑。

## 运行

```bash
.venv/bin/python RQ4/ssp126_ssp585_loss_gap_clustering/run_all.py
```

常用参数：

```bash
.venv/bin/python RQ4/ssp126_ssp585_loss_gap_clustering/run_all.py \
  --model CANESM5 \
  --k-min 2 \
  --k-max 5 \
  --min-cluster-size 2 \
  --bootstrap 200 \
  --event-snapshot 2050
```

默认结果位于 `RQ4/ssp126_ssp585_loss_gap_clustering/outputs/{MODEL}/`：

- `csv/RQ4_country_cluster_assignments.csv`：国家聚类标签、模式名称和稳定率；
- `csv/RQ4_country_cluster_summary.csv`：各类中心、成员国和平均稳定率；
- `csv/RQ4_cluster_k_diagnostics.csv`：类别数、最小类规模和轮廓系数；
- `csv/RQ4_cluster_event_composition.csv`：损失加权及国家等权事件构成；
- `figures/fig_RQ4_country_tradeoff_clusters_*`：中心曲线、类别数诊断和国家热图；
- `figures/fig_RQ4_cluster_event_composition_*`：全部事件及非低资源事件构成。

每张图输出 PNG 格式。

## 为什么不同指标的国家数量不同

聚类算法本身不会随机删除国家。`build_feature_matrix` 在聚类前会执行完整样本筛选：一个国家只有在对应技术、指标、SSP126/SSP585 和2030s/2040s/2050s全部有有限值时，才进入该次聚类。不同指标的分母不同，因此有效样本集合也可能不同：

- 绝对损失只需要净损失值；
- 相对损失率还需要正常发电量大于零；
- 单位装机损失还需要装机容量大于零；
- 单位场站损失还需要场站数量大于零。

以当前 CANESM5 结果为例，风电四项指标分别有19、18、19、19个完整国家；光伏四项指标均有9个完整国家。风电相对损失率少的国家是 Sweden，原因是该组合的正常发电量分母无法形成完整有限序列。光伏只有9个国家，是因为 SSP126/SSP585 两个情景和三个年代同时有完整光伏记录的国家较少。

因此，不同指标的聚类结果不能直接比较国家数；比较国家归属时应先限制到各指标的共同有效国家，或将缺失原因作为结果的一部分报告。

## 测试

```bash
.venv/bin/python -m unittest discover -s RQ4/ssp126_ssp585_loss_gap_clustering/tests -v
```
