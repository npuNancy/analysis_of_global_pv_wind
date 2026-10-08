# 图 1：极端事件的空间与年代变化

科学问题：全球网格和场站的事件暴露是否随空间、年代、SSP 和事件类型呈现不同变化？不预设情景排序。

Python/matplotlib，左风电、右光伏，完整图为 183 × 220 mm、600 dpi PNG。同时按 a+b、c+d、e+f 导出独立 PNG，保留原编号及相关图例、色条；两个额外年代差图分别导出 a+b 子图组。

- a–b：2050–2059 年事件并集的气候 SSP585−SSP126 网格差；逐模式相减再等权平均。原生格点面积加权至 1° 展示网格，Plate Carrée 投影。共享 −12.5～12.5 day/年色标，`extend='both'`。该范围覆盖约 94.2% 风电、96.2% 光伏展示格点，超限值用端点颜色表示，源数据不截断。空心圆面积表示 SSP126/2050 总容量，以 3° 网格汇总。
- c–d：每个技术面板叠加全球网格面积加权暴露与场站容量加权暴露，两图各有 6 个纵轴刻度。风电纵轴约为 33.33–56.25 day/年；光伏采用断轴，保留约 22.92–35.42 和 50–60.42 day/年，省略无数据及模式范围的约 35.42–50 区间，并显示断轴符号与区间说明；光伏上下两段每天的纵向比例一致。网格采用四模式均值实线及 min–max 阴影带；场站保留均值符号、min–max 误差棒和连接均值的虚线，三个 SSP 相对年代中心的横向偏移为 −0.06、0、+0.06（相邻年代间距为 1）。2030s、2040s、2050s 分别为完整十年窗口。
- e–f：各事件 2050s−2030s 暴露变化，横向分组柱形表示四模式均值，深灰水平误差棒表示四模式差值的最小值至最大值，两端无端帽（capsize=0），整条为平直线段；同一 SSP 用实心柱表示网格、斜线柱表示场站。柱厚为 0.115，SSP 中心间距为 0.32（均以事件行距为单位）。另输出 2050s−2040s 和 2040s−2030s 两张独立图，三张图、两技术共用变化量坐标范围。

本图及额外年代差图的暴露时长和差值均以 day/年（day yr⁻¹）显示，1 day = 24 h，表示年均累计暴露时长，不是发生事件的日历天数。准备表保留已验收的小时单位，绘图时换算为天并导出带 unit 列的四份展示表：`panel_ab_days.csv.gz`、`panel_cd_display_days.csv`、`panel_event_summary_days.csv`、`panel_event_changes_days.csv`；转换因子和文件哈希记录在 metadata.json。网格采用已验收公共缓存 `grid_events/<tech>/<patch>/period_hours.nc`，覆盖正式 47 patch 的全部有效原生网格，并取四模式、三气候 SSP、三个窗口共同有效空间支持。先汇总面积加权分子、分母再相除，不对展示格点作等权平均。场站复用 `event_summary/window.csv.gz` 的 GLOBAL 配对路径，按对应年代总容量快照加权；年代变化同时含部署与容量权重变化。各类型可能重叠，all 为时间并集。场站 SSP585 来源仍是 SSP5-6.0 部署文件。

`prepare_data.py` 检查已验收 664 项准备结果、完整模式/窗口/事件矩阵、现有场站结果复现、事件并集上界、容量守恒、格点差复现、三组年代差闭合与边界几何。新的网格汇总和派生源数据仅写入本图目录，不修改公共准备结果。输入哈希、色标诊断、覆盖记录写入 `outputs/data_audit.json`。

运行：

```bash
mkdir -p logs/paper_figures/fig01
sbatch paper_figures/main/fig01_extreme_events/plot.sh
```

默认作业先准备并核验数据，再导出完整图与子图组共 8 张 PNG；使用仓库 .venv、wzhctest、4 核/14 GB。可单独提交 `prepare_data.sh`；已有本图核验源数据时，`plot.sh --skip-prepare` 跳过准备，仍核验原始输入哈希。

产物：
- `outputs/fig01.png`
- `outputs/fig01_ab.png`、`fig01_cd.png`、`fig01_ef.png`
- `outputs/event_changes_2050s_minus_2040s.png`
- `outputs/event_changes_2040s_minus_2030s.png`
- `outputs/event_changes_2050s_minus_2040s_ab.png`、`event_changes_2040s_minus_2030s_ab.png`
- `outputs/caption.md`、`metadata.json`、`data_audit.json`
- `outputs/source_data/panel_event_windows.csv`：两类空间对象的逐模式、SSP、技术、年代、事件值及权重。
- `panel_event_changes.csv`：三组逐模式年代差及两端有效面积/容量。
- `panel_cd_display.csv`、`panel_event_summary.csv`：实际绘制的均值及范围。
- `panel_cd_grid.csv`、`panel_cd_coverage.csv`、`grid_coverage.csv`：网格并集与空间覆盖、场站容量覆盖。
- 地图继续复用 `panel_ab.csv.gz`，配套逐模式差与容量气泡表。

模式范围是四个气候模式的描述性离散程度，不是置信区间。气象事件暴露与 Loss 有效窗口不同；全球网格指正式产品有效域，不代表未覆盖区域。视觉检查记录写入 metadata.json。
