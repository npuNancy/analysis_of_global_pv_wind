# Fig. S09：正常CF基线敏感性

## 科学问题与面板
检验反事实贡献对情景自身正常CF参照的依赖。

a–b 原基线与共同基线固定部署气候差散点；c–d 全球及Fig.4八国气候/部署贡献的均值与四模式范围。

## 数据与口径
复用本目录 `outputs/source_data/`：重建后生成 annual.csv.gz、window.csv、contrasts.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

每模式每部署以气候126正常月—小时CF为共同参照，重算全部九组合。两种基线使用相同有效时刻和站点；事件识别保持原样。先复现年度正/净损失，再替换基线，不跨部署匹配站点ID。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s09_baseline_sensitivity
sbatch paper_figures/supplementary/fig_s09_baseline_sensitivity/plot.sh
```

默认输出：`outputs/fig_s09_baseline_sensitivity.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。

新增数据由 `paper_figures/prepare/reconstruct_supplementary.py` 按已验收共同支持读取正式索引；`summarize_supplementary.py` 核验完整性和年度闭合后生成本图源表。各脚本有同名SLURM入口。原始五类产品保持只读。

## 完整计算核验

九种气候×部署组合均已完成。共同有效时刻的最小保留比例为99.20%（逐重建单元、气候、年份统计），两种基线在相同的有效时刻上比较；气候SSP126下两种基线结果的最大差为0。逐单元覆盖及年度复现记录见 `paper_figures/prepare/outputs/supplementary_reconstruction/reproduction.csv.gz`。
