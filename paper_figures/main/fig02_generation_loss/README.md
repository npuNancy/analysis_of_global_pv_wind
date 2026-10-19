# 图 2：全球单位装机损失、气候—布局分解与事件组成

科学问题：三条配对路径的全球单位装机损失如何随年份变化，SSP585−SSP126 的年代差由气候暴露、事件期正常发电能力、事件期相对损失与布局分别贡献多少，以及各事件标签的损失量如何变化？

Python/matplotlib，定量六面板，a–b与e–f左风电右光伏，c–d上风电下光伏，183 × 270 mm、600 dpi PNG。独立导出 a+b、c+d、e+f。

- a–b：复现年度参考图的连续四模式均值实线、min–max 阴影及 2030–2059 年最小二乘趋势虚线。容量快照两侧保持连接。风光纵轴分别设置。
- c–d：复用三个年代气候机制与布局瀑布图的原生绘制函数。每个技术面板包含2030s、2040s、2050s三组E／CF／r／S／Δ，共15根柱；上风电、下光伏。四项贡献及净差单位均为MWh MW⁻¹ yr⁻¹；分别设轴，保留正负贡献及连接线。
- e–f：三个年代各有三根 SSP 柱，柱段为实际事件单位装机净损失，颜色与事件顺序沿用组成参考图。百分比为柱段均值占该柱事件均值之和，占比至少 5% 且最终柱段高度至少 7 pt 才标注；不将柱高归一到 100%。当前 99 个事件均值均为正；模式级负值参与有符号平均，不截零或取绝对值。事件标签可能重叠，柱高不是事件并集损失。
- 原 c–d 移至 Fig. S12a–b，原 e–f 移至 Fig. S12c–d，原始统计与画法保留。

四项分解采用下文所述气候内三因素Shapley与气候—布局对称分解，逐模式验证四项贡献加总为配对SSP585−SSP126差。布局贡献反映装机权重和位置变化，均匀扩大容量不改变单位装机指标。主图c–d与独立三个年代图共享数据和绘制函数。

## 数据与运行

复用本图已验收的年度及原面板表，以及公共 loss_summary/window.csv.gz。准备脚本核验 664 项准备验收、年度／年代均值一致、分母一致、完整四模式、三个年代、既有双因素校验及四项气候—布局闭合、2050s 旧图复现，并保存容量覆盖。所有损失能量保留原尺度。

在 1866 远程仓库根目录运行：
```bash
bash paper_figures/main/fig02_generation_loss/plot.sh
```
默认先准备数据，再生成 Fig2 和 S12。已有最新核验表时可传 --skip-prepare；单独准备使用 prepare_data.sh。配套作业使用 wzhctest、4 核／14 GB、仓库 .venv，日志在 logs/paper_figures/fig02/。

输出位于 outputs/：fig02.png、fig02_ab.png、fig02_cd.png、fig02_ef.png，及 caption.md、metadata.json、data_audit.json；数值表在 outputs/source_data/。新源表包括 annual_trends.csv、global_window_models.csv、union_factors_models.csv、two_factor_models.csv、two_factor_display.csv、event_composition_models.csv 和 event_composition_display.csv。已验收原始 panel_ab/cd/ef.csv 保留用于追溯；本版面板映射以新表名和图注为准。

## 2050s 气候机制与布局瀑布图

`plot_climate_layout_waterfall.py` 绘制 SSP585−SSP126 的全球单位装机净损失差，左风电、右光伏；使用2050容量快照及2050–2059年均值。依次显示气候—暴露、气候—事件期正常CF、气候—事件期相对损失、布局贡献及净差。

输入为公共 `paper_figures/prepare/outputs/loss_summary/window.csv.gz` 的 GLOBAL、all、common 记录。在每个模式、固定部署内对 E × CF_event × r_event 作六种替换顺序平均的 Shapley 分解，再平均部署126与585的对应贡献；布局项取两种固定气候下布局差的平均。三个气候贡献与布局贡献严格加总为配对路径差，交互作用已分摊。E 使用与 Loss 对应的事件并集小时；CF_event 为事件期正常电量除以装机加权事件小时，r_event 为事件期净损失除以正常电量。

柱形为四模式等权均值，单位 MWh/MW/年；逐模式结果、模式 min–max 和有效容量保留在源数据，图中不显示不确定性区间。风光采用各自纵轴范围，图内明确说明；颜色对应因子，数值标签保留贡献符号。部署585的原始来源为 stations_SSP5-6.0.csv。

仅生成一张183 × 85 mm、600 dpi双子图PNG：
`outputs/fig02_climate_layout_waterfall_2050s.png`。
同名元数据和 `outputs/source_data/fig02_climate_layout_waterfall_2050s_*.csv` 保存输入摘录、固定部署分解、模式结果和显示统计。

本任务只读取汇总表，默认在登录节点激活仓库环境后运行：

```bash
source .venv/bin/activate
mkdir -p logs/paper_figures/fig02
python -m paper_figures.main.fig02_generation_loss.plot_climate_layout_waterfall > logs/paper_figures/fig02/climate_layout_direct.out 2>&1
```

需要SLURM时运行 `bash paper_figures/main/fig02_generation_loss/plot_climate_layout_waterfall.sh`，使用wzhctest、1核、3500 MB，并先创建日志目录再提交。


## 三个年代的气候机制与布局瀑布图

`plot_climate_layout_waterfall_decades.py` 将2030s、2040s、2050s并列为三组，上风电、下光伏，每个子图15根柱。每组依次为气候暴露E、气候事件期正常CF、气候事件期相对损失r、布局S和净差Δ。计算口径与上述2050s图一致；各年代使用相应容量快照和十年窗口，先逐模式分解，再求四模式均值。同一技术三个年代共用纵轴，风光纵轴分别设定。

仅输出一张183 × 150 mm、600 dpi PNG：`outputs/fig02_climate_layout_waterfall_2030s_2040s_2050s.png`。同名元数据及四份`outputs/source_data/`源表保存全部年代结果。

在仓库根目录激活`.venv`后运行：

```bash
python -m paper_figures.main.fig02_generation_loss.plot_climate_layout_waterfall_decades
```

配套SLURM入口为同名`.sh`；该任务仅处理已有小型汇总表，可直接在登录节点运行。

## 路径比较分析报告

report.py 调用同目录build_analysis_report.py构建入口，将Fig. 2三条SSP路径的水平、18组年代配对差、四贡献分解和事件比较写入 paper_figures/analysis/analysis_20261019_005216/report.html 与 report.md，并完整整合该目录的国家部署分析。新分析代码与同名SLURM脚本位于本目录。使用冻结于报告assets的图件和小型汇总表，在仓库根目录激活环境后执行 python -m paper_figures.main.fig02_generation_loss.report。初次构建先运行国家目录的report.py生成国家页面及assets。
