# 图 2：全球单位装机损失、双因素分解与事件组成

科学问题：三条配对路径的全球单位装机损失如何随年份变化，SSP585−SSP126 的年代差由暴露与强度贡献多少，以及各事件标签的损失量如何变化？

Python/matplotlib，定量六面板，左风电右光伏，183 × 220 mm、600 dpi PNG。独立导出 a+b、c+d、e+f。

- a–b：复现年度参考图的连续四模式均值实线、min–max 阴影及 2030–2059 年最小二乘趋势虚线。容量快照两侧保持连接。风光纵轴分别设置。
- c–d：每个技术面板包含 2030s、2040s、2050s 三组 E／I／Δ 瀑布条。逐模式执行 R = E × I 的对称双因素分解，再对四模式等权平均。E 为 Loss 有效事件并集暴露天数，I 为单位装机每暴露天净损失；两个贡献及净差单位均为 MWh MW⁻¹ yr⁻¹。风光分别设轴，保留正负贡献及连接线。
- e–f：三个年代各有三根 SSP 柱，柱段为实际事件单位装机净损失，颜色与事件顺序沿用组成参考图。百分比为柱段均值占该柱事件均值之和，占比至少 5% 且最终柱段高度至少 7 pt 才标注；不将柱高归一到 100%。当前 99 个事件均值均为正；模式级负值参与有符号平均，不截零或取绝对值。事件标签可能重叠，柱高不是事件并集损失。
- 原 c–d 移至 Fig. S12a–b，原 e–f 移至 Fig. S12c–d，原始统计与画法保留。

双因素定义：
$$
R = EI,\qquad
\phi_E = (E_{585}-E_{126})(I_{585}+I_{126})/2,\qquad
\phi_I = (I_{585}-I_{126})(E_{585}+E_{126})/2.
$$
每个模式、技术、年代均核验 $\phi_E+\phi_I=R_{585}-R_{126}$。该分解针对气候与部署同时变化的配对路径，不是固定部署的纯气候分解。

## 数据与运行

复用本图已验收的年度及原面板表，以及公共 loss_summary/window.csv.gz。准备脚本核验 664 项准备验收、年度／年代均值一致、分母一致、完整四模式、三个年代、双因素闭合、2050s 旧图复现，并保存容量覆盖。所有损失能量保留原尺度。

在 1866 远程仓库根目录运行：
```bash
bash paper_figures/main/fig02_generation_loss/plot.sh
```
默认先准备数据，再生成 Fig2 和 S12。已有最新核验表时可传 --skip-prepare；单独准备使用 prepare_data.sh。配套作业使用 wzhctest、4 核／14 GB、仓库 .venv，日志在 logs/paper_figures/fig02/。

输出位于 outputs/：fig02.png、fig02_ab.png、fig02_cd.png、fig02_ef.png，及 caption.md、metadata.json、data_audit.json；数值表在 outputs/source_data/。新源表包括 annual_trends.csv、global_window_models.csv、union_factors_models.csv、two_factor_models.csv、two_factor_display.csv、event_composition_models.csv 和 event_composition_display.csv。已验收原始 panel_ab/cd/ef.csv 保留用于追溯；本版面板映射以新表名和图注为准。
