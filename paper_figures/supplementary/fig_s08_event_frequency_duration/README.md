# Fig. S08：事件次数与完整事件持时

## 科学问题与面板
区分暴露来自事件次数还是持续时间。

a–b 横轴为事件类别、纵轴为容量加权次数；c–d 纵轴为完整事件容量加权平均持时。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_abcd.csv；plotted_frequency_duration.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

2050–2059，三配对路径；四模式点、均值和范围。频次来自连续信号起点，持续时间只计完整观测事件。边界和缺测删失比例保留于绘图源表，不强制次数乘持时等于暴露。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s08_event_frequency_duration
sbatch paper_figures/supplementary/fig_s08_event_frequency_duration/plot.sh
```

默认输出：`outputs/fig_s08_event_frequency_duration.png`，600 dpi PNG。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
