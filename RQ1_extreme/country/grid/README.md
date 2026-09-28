# 国家网格极端天气分析

`country_grid_extremes.py` 使用全球网格分析生成的年度缓存，计算各国有效陆地面积加权暴露；输出国家×SSP 变化热图及重点国家年度轨迹。逐模式和等权模式均值分别保存，PNG 为 300 dpi，全部国家的年度和时期指标保存为 CSV。

## 输入与统计

- 默认读取 `RQ1_extreme/global/grid/outputs/cache_manifest.json`，自动继承模式、SSP、技术、patch、年份、基线和未来时期；不再读取逐时信号。
- 国界使用仓库 `data/maps/natural_earth/ne_110m_admin_0_countries.shp`。按格点中心与国境相交建立国家掩膜，遵循现有国家命名约定；共边按固定国家顺序仅分配一次，不做邻国填补。国家掩膜按边界文件、坐标和有效陆地掩膜摘要缓存。
- 国家覆盖率分母是所选 patch 范围内能够归入该国的 `domain_mask` 陆地面积，并非完整国土面积。110m 国界可能遗漏小岛，无法归属的域内格点单独记录在 `unassigned_domain.csv`。
- 汇总所有 patch 的加权分子与面积分母后计算国家指标。年度时间有效性沿用全球缓存；模式均值要求全部选定模式有效。模式范围为最大/最小值。
- 热图按平均变化排序，分页展示全部有有效时期比较数据的国家，并列未来有效面积覆盖率；缺测格子标灰。轨迹图固定包含中国、美国、印度、德国、南非、澳大利亚、俄罗斯、巴西，按此顺序优先展示；再合并任一 SSP 中绝对变化最大的 6 个国家并去重，风电与光伏分别筛选。指定国家缺少有效数据时仍保留面板并标注缺测，不将缺测当零。必选名单和最终选国名单记录在配置中。CSV 仍保留全部国家，包括无法完成时期比较的国家。

## 运行

先完成全球网格缓存，再提交国家分析。在仓库根目录提交完整依赖链：

```bash
mkdir -p logs/RQ1_extreme/global/grid logs/RQ1_extreme/country/grid
global_job=$(sbatch --parsable RQ1_extreme/global/grid/global_grid_extremes.sh)
sbatch --dependency=afterok:${global_job} RQ1_extreme/country/grid/country_grid_extremes.sh
```

全球作业已经完成时可直接提交 `country_grid_extremes.sh`。国家作业默认 `wzhctest`、1 节点、4 CPU、14 GB 内存、12 小时时限，使用仓库 `.venv`。`--grid-output-dir` 指定全球缓存位置，`--output-dir` 指定国家结果位置；`--countries-per-page` 控制热图分页；`--top-countries` 控制与 8 个必选国家合并的变化排名国家数（默认 6），不限制必选名单。

```text
outputs/
├── masks/<patch>_<hash>.npz
├── run_config.json
├── <model>/
│   ├── csv/country_annual_exposure.csv
│   ├── csv/country_period_changes.csv
│   ├── csv/unassigned_domain.csv
│   └── figures/
│       ├── country_change_heatmap_<tech>_<page>.png
│       └── country_trajectories_<tech>.png
└── ensemble_mean/
```

真实数据子集验证结果位于 `outputs/validation/`。全量分析、国家栅格匹配与绘图均通过计算节点执行。
