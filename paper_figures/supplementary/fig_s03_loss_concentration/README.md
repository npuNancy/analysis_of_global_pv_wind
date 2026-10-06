# Fig. S03：损失集中度

## 科学问题与面板
检验正净损失的参考容量加权负担如何分布于国家。

a–b 为风电与光伏累计曲线，显示四模式均值、范围及前5/10个国家。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_ab.csv、country_burden_inputs.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

SSP126、2050快照；按国家四模式平均带符号 R 递减固定排序，再逐模式累计 Cref × max(R,0)。这是参考容量加权指数，不能解释为实际损失能量。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s03_loss_concentration
sbatch paper_figures/supplementary/fig_s03_loss_concentration/plot.sh
```

默认输出：`outputs/fig_s03_loss_concentration.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
