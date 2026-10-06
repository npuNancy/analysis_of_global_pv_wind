# Fig. S06：损失指标敏感性

## 科学问题与面板
比较带符号净损失、正损失和全年正常发电量归一口径。

a–b 净损失路径差对正损失路径差；c–d 净损失路径差对全年损失率变化（百分点）。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_abcd.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

2050、共同有效支持。正损失直接来自原始逐时正损失指标，不截断年度净损失代替。国家点面积正比于SSP126参考容量；标记四个重点国家的模式点。仅同单位面板画1:1线。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s06_loss_metric_sensitivity
sbatch paper_figures/supplementary/fig_s06_loss_metric_sensitivity/plot.sh
```

默认输出：`outputs/fig_s06_loss_metric_sensitivity.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
