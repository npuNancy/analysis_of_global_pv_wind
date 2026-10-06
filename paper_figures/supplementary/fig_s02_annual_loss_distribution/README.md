# Fig. S02：年际损失超越概率

## 科学问题与面板
比较配对路径下年度单位装机损失分布。

a–b 分别为风电和光伏的经验阶梯超越曲线；实线为四模式均值，阴影为模式最小至最大值。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_ab.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

固定2050容量，每模式2050–2059十个年度；严格采用 R > x，不将四模式40个年度当成独立样本。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s02_annual_loss_distribution
sbatch paper_figures/supplementary/fig_s02_annual_loss_distribution/plot.sh
```

默认输出：`outputs/fig_s02_annual_loss_distribution.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
