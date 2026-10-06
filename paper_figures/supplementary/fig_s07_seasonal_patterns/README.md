# Fig. S07：季节贡献

## 科学问题与面板
分辨气候差的年内暴露和净损失贡献。

a–b 事件×DJF/MAM/JJA/SON暴露热图；c–d 相同结构的重建净损失热图。

## 数据与口径
复用本目录 `outputs/source_data/`：已有 panel_ab.csv；新增 panel_cd.csv 和 annual_reproduction.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

固定SSP126部署，2050–2059气候585减126。DJF为同一年1、2、12月；四季加总核对年度值，事件行重叠且不相加为all。损失依照CF、Extreme、cf_normal重建，每站每年核对正式正/净损失后再汇总。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s07_seasonal_patterns
sbatch paper_figures/supplementary/fig_s07_seasonal_patterns/plot.sh
```

默认输出：`outputs/fig_s07_seasonal_patterns.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。

新增数据由 `paper_figures/prepare/reconstruct_supplementary.py` 按已验收共同支持读取正式索引；`summarize_supplementary.py` 核验完整性和年度闭合后生成本图源表。各脚本有同名SLURM入口。原始五类产品保持只读。

## 完整计算核验

四季损失加总与正式年度窗口结果的最大单位装机差为3.87e-7 MWh/MW；四季暴露加总的最大差为3.41e-13小时。逐站逐年原始正/净损失复现检查全部通过。
