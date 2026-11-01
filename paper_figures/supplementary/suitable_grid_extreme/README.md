# 全球适宜网格极端事件暴露

问题：固定适宜网格上的极端事件暴露随年代和 SSP 如何变化；不预设增减方向。Python quantitative grid，左风电、右光伏，主图183×83 mm，独立面板95×83 mm，600 dpi PNG。

权威清单为 `data/stations/suitable_grid_1mw/grid_mapping.csv.gz`，不重算适宜性、不作面积或坡度筛选。按 patch 和经纬度匹配 RQ1 年度缓存，检查技术内部坐标、栅格与 patch 索引唯一性。风光重合位置属于不同技术，分别统计。年度暴露沿用 RQ1 全部适用事件共同有效时间掩膜和99%时间覆盖阈值，保留原生日历，不补齐缺测。主统计固定四模式、三SSP、2030–2059全部年份共同有效格点。先合并patch分子分母，再求全球等权格点平均；面积加权为独立敏感性分析。

all为时间并集，非单事件之和。overlap_correction = all − 单事件之和，是负的重复暴露校正，非独立交集测量。年代点为十个年度值平均，模式均值为四模式等权，阴影为min–max，非置信区间。主图与年度补充图均以day yr⁻¹显示。面积加权对照另存图；单事件补充保存为逐模式年度和年代源表。

准备作业读取既有缓存，不复制原始三小时数据。源缓存身份按清单fingerprint核验；对所有选中共同格点交叉核对period_hours.nc，并从每个模型/SSP/技术/patch抽取2030、2040、2050重现RQ1已验收面积加权分子和分母。浮点snapshot存储允许3×10⁻⁵ day绝对、2×10⁻⁷相对误差。validation.json记录覆盖率、异常和核查；逐patch映射与审计保存在outputs/source_data/patches。

```bash
mkdir -p logs/paper_figures/suitable_grid_extreme
sbatch paper_figures/supplementary/suitable_grid_extreme/prepare.sh
# 预处理成功后，仅小汇总表绘图可在登录节点执行
source .venv/bin/activate
python -m paper_figures.supplementary.suitable_grid_extreme.plot
```

文件组织：prepare.py/prepare.sh 预处理；plot.py/plot.sh 绘图；outputs/source_data 保存逐模式和集合数值、共同支持覆盖率、权重敏感性及单事件表；outputs 保存主图、年度补充图、面积加权对照及各独立面板，以及 metadata.json、validation.json 和 caption.md。缺测保持缺测，不承诺全清单均有有效事件结果。

已完成：预处理作业47896651；数值核查与12张600 dpi PNG视觉检查通过。数值及权重敏感性结论见outputs/results.md，逐项核查见outputs/validation.json。
