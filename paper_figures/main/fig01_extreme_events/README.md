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

## 国家暴露分布地图

`plot_country_exposure.py/.sh` 在同一目录生成两张 2 行 × 3 列国家地图：行是风电、光伏，列是 SSP126、SSP245、SSP585。完整图为 240 × 133 mm；每张同时导出风电 a–c、光伏 d–f 两个独立组合（240 × 86 mm），全部为 600 dpi PNG。

- 2050年代图：国家底色为有效原生网格的面积加权年均事件并集暴露；圆颜色为场站容量加权年均事件并集暴露。
- 变化图：底色和圆颜色均为 2050–2059 减 2030–2039，先逐模式相减，再对四模式等权平均。场站分别使用2030和2050容量快照，变化包含部署变化。
- 两图的圆面积均与各 SSP、各技术、各国的2050总装机成正比；暴露缺测的装机仍计入面积。沿用参考地图的容量尺度（最大风光合计国家容量对应1000 pt²），圆直径乘0.75，散点面积因子为0.5625。
- 底色和圆严格共用色系与数值范围：绝对值使用 YlOrBr；变化使用以零对称的 RdBu_r，范围按所有国家、技术、情景及两类暴露变化的绝对值95%分位向上取整至2.5天/年。变化色条两端尖角，超限值保持原值写入源数据，数量和极值记录在元数据。
- 投影为 Cartopy Plate Carrée，统一范围为经度 −180–180°、纬度 −60–85°。采用项目边界副本，China/Taiwan在空间归属前合并；不显示南极、UNASSIGNED和AMBIGUOUS，但在源数据中保留后两类。
- 网格复用已验收的 `prepare/outputs/grid_events`，采用四模式、三情景、三个窗口共同有效的原生格点，按格点中心归属国家。面积加权分子、分母在国家内汇总后相除；不是将国家平均暴露再次除面积。
- 场站复用 `prepare/outputs/event_summary/window.csv.gz` 的配对路径和已验收共同有效站点集合，时间覆盖至少99%；国家容量使用 `catalogues/capacity_by_country.csv`。各窗口使用自身快照，记录有效容量及其占目录总容量的比例。
- 暴露单位为 day yr⁻¹，1 day = 24 h；表示累计时长而非事件日历天数。均值要求四模式齐全，源数据另保留模式最小值、最大值；地图不表达显著性。缺测以灰色表示，无装机不画圆。

运行：

```bash
mkdir -p logs/paper_figures/fig01
sbatch paper_figures/main/fig01_extreme_events/plot_country_exposure.sh --pilot
sbatch paper_figures/main/fig01_extreme_events/plot_country_exposure.sh
```

`--pilot` 核对风光各一个代表分块及全部场站汇总表；默认作业重新准备47分块的国家源数据并绘图；`--skip-prepare` 校验本图源数据哈希后重绘。默认4核、14 GB，使用仓库环境与 wzhctest。

产物：

- `outputs/fig01_country_exposure_2050s.png` 及 `_abc.png`、`_def.png`。
- `outputs/fig01_country_exposure_change_2050s_minus_2030s.png` 及 `_abc.png`、`_def.png`。
- `outputs/source_data/country_exposure_grid_windows.csv.gz`、`country_exposure_station_windows.csv.gz`：逐模式、年代、国家的基础分子和分母。
- `outputs/source_data/country_exposure_models.csv.gz`、`country_exposure_display.csv`：逐模式地图指标与完整四模式展示汇总。
- `outputs/country_exposure_data_audit.json`、`country_exposure_metadata.json`：来源哈希、覆盖、守恒检查、色标截断计数、图件及视觉检查记录。

2026-10-08 验证：代表分块作业 46083676、全量准备及绘图作业 46083857、最终排版重绘作业 46084188 均 COMPLETED（0:0）。通过国家/全球面积、暴露及容量守恒和现有全球网格结果复现；六张 PNG 已逐张视觉检查，图件与源数据哈希、600 dpi 和文字边界检查通过。最终绝对值色标0–170天/年，变化色标−10–10天/年。
