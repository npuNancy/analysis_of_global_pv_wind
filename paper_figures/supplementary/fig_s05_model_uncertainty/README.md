# Fig. S05：模式不确定性

## 科学问题与面板
检查九种双SSP组合、事件类别及空间方向的一致性。

a–b 九组合点区间；c–d 事件×三配对路径；e–f 格点暴露方向一致性。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_ab.csv、panel_cd.csv、panel_ef.csv.gz。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

四模式形状固定，空心菱形为均值，线为最小至最大值。地图使用简易圆柱 Plate Carrée，0–4为与集合均值同号的模式数；零均值与缺测独立编码，不表示显著性。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s05_model_uncertainty
sbatch paper_figures/supplementary/fig_s05_model_uncertainty/plot.sh
```

默认输出：`outputs/fig_s05_model_uncertainty.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
