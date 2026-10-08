# Supplementary Fig. S12：全球路径差与事件损失对照

承接原 Fig. 2 c–f，不改变统计量及模式范围：
- a–b：三个年代的 SSP245−SSP126、SSP585−SSP126 配对净损失差，四模式小点、均值符号和 min–max。
- c–d：2050s 的三条 SSP 事件损失哑铃图，保留原事件排序及有符号数据。

单位 MWh MW⁻¹ yr⁻¹；气候和部署配对。Python/matplotlib，183 × 140 mm，600 dpi PNG。Fig2 的 prepare_data.py 同步准备本图独立源表及迁移核验。

完整 Fig2 作业自动生成本图；已准备数据时也可独立运行：
```bash
bash paper_figures/supplementary/fig_s12_global_loss_contrasts/plot.sh
```
输出 outputs/fig_s12.png、fig_s12_ab.png、fig_s12_cd.png，以及源数据、图注和核验记录。
