# Fig. S10：覆盖、参考权重与阈值

## 科学问题与面板
检查有效覆盖和展示参照的敏感性。

a–b 固定18国家×九组合最小有效容量覆盖；c–d 原始/共同支持的路径差；e–f 固定可比国家集的高损失国家比例和三种参考容量比例。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_ab.csv、panel_cd.csv、panel_ef.csv、thresholds.csv；always_high_loss_countries.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

覆盖分母为各部署目录容量，取四模式和十年最小值。阈值来自早期固定样本50/75/90分位，并要求R>0；额外容量权重不改变R。始终高于全部阈值的国家另存表。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s10_coverage_weights_thresholds
sbatch paper_figures/supplementary/fig_s10_coverage_weights_thresholds/plot.sh
```

默认输出：`outputs/fig_s10_coverage_weights_thresholds.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
