# 三情景相对损失率轨迹聚类

本目录是独立的 RQ4 方案：只使用国家相对损失率，不使用 SSP 之间的损失差、装机容量或单位场站损失作为聚类输入。

每个国家的聚类特征向量为九维：

```text
[ssp126_2030s, ssp126_2040s, ssp126_2050s,
 ssp245_2030s, ssp245_2040s, ssp245_2050s,
 ssp585_2030s, ssp585_2040s, ssp585_2050s]
```

相对损失率按国家—情景—技术—年份先汇总分子和分母，再计算 `100 × sum(net_generation_loss_mwh) / sum(normal_all_generation_mwh)`。每个九维特征在国家之间分别做 z-score，然后使用 Ward 层次聚类。候选类别数为2–5；在每类至少2个国家的候选中，以平均轮廓系数最高者为主选择，如果候选分数相差不超过0.05，优先选择较小类别数。稳定性通过对九维标准化向量加入5%尺度扰动并重复200次估计。

运行：

```bash
.venv/bin/python RQ4/relative_loss_rate_trajectory_clustering/run_all.py
```

结果位于 `outputs/CANESM5/`，包括原始九维特征、标准化特征、国家完整性、聚类标签、轮廓系数诊断、PNG图和 `run_config.json`（含输入文件哈希与特征顺序）。

当前上游风电能量字段仍按项目约定临时乘以0.1；上游修复后需移除该修正并重跑。方法细节见 [WARD_METHOD.md](WARD_METHOD.md)。
