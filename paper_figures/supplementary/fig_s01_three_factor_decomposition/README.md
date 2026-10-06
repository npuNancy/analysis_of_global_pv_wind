# Fig. S01：三因子对称分解

## 科学问题与面板
检验固定部署气候差中暴露、事件期正常 CF 与相对净损失的贡献。

a–b 为全球 E、CF、r 及总差；c–d 为 Fig.4 相同八个国家，两种部署分别正负堆叠，菱形为净差；e–f 为国家暴露差与气候损失差。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_abcdef.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

2050–2059，事件并集，共同有效支持，固定部署 SSP126/585 内气候585减126。六顺序 Shapley 保持加和闭合，再等权汇总四模式。零分母对应的因子保持未定义。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s01_three_factor_decomposition
sbatch paper_figures/supplementary/fig_s01_three_factor_decomposition/plot.sh
```

默认输出：`outputs/fig_s01_three_factor_decomposition.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
