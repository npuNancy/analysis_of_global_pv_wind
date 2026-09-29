# 国家极端天气分布地图

## 图件目的与编码

用同一张世界地图对照国家的气候背景暴露与装机位置暴露，并比较三个 SSP 下的 2050 年代及其相对 2030 年代的变化。所有图均为四模式等权均值；描述性对照，不作显著性检验。

参考构图代码：`../../../ref_code/analysis_of_global_south_north/analysis_figtest/fig2_risk/fig2_A.py` 中的 `plot_panel_a()`。本实现使用 Cartopy Plate Carrée，国家底色、代表点圆和共享图例；圆的面积与颜色按本次定义。

| 图件 | 布局 | 国家底色 | 圆面积 | 圆颜色 |
|---|---|---|---|---|
| 2050s 风光分开 | 2 × 3，风/光 × SSP126/245/585 | 2050–2059 年单位面积暴露时长 | 对应技术的 2050 年装机（GW） | 2050–2059 年单位装机暴露时长 |
| 2050s 风光合并 | 1 × 3 | 风电与光伏单位面积暴露时长相加 | 2050 年风光总装机 | 风光按有效容量加权的暴露时长 |
| 变化，风光分开 | 2 × 3 | 2050–2059 减 2030–2039 年的单位面积暴露时长 | 同 2050s 图 | 同 2050s 图 |
| 变化，风光合并 | 1 × 3 | 风光各自变化量相加 | 同 2050s 合并图 | 同 2050s 合并图 |

单位均为天/年。单位面积暴露时长为面积暴露量（km²·天）除以有效面积（km²）；单位装机暴露时长为容量暴露量（GW·天）除以有效装机（GW）。面积和容量已经在分子中加权，不能再用平均天数除一次面积或容量。

- 事件采用技术内所有事件的时间并集 `any`。风光合并的底色为两个技术指标相加，允许超过 365 天/年，不表示风光事件时间并集。
- 圆采用 **2050 年容量快照**：取 `capacity_rows.csv.gz` 的 `year=2050`，同技术、同 `station_id` 的源行容量求和；固定这组容量评估 2050–2059 年暴露，不累加多个年份的容量快照。
- 每个模式内先计算年度指标，再取完整 10 年平均；最后要求四模式齐全并等权平均。某一模式/年度缺少指标时不以更少模式/年份替代。
- 风光合并的圆颜色逐年用“风容量暴露量 + 光容量暴露量”除以“风有效容量 + 光有效容量”，然后取年代和模式均值。各技术无有效暴露的容量不进入颜色分母，保留在圆的总装机面积与覆盖率分母中。
- 国家边界沿用现有 Natural Earth 110m 数据及中国合并口径；网格按格点中心归属，场站按实际经纬度归属。未落入该边界数据的场站保留在 `UNASSIGNED` 审计行，不画成国家。
- 圆面积与容量成正比，无对数变换或最小面积截断；放在国家最大多边形的内部代表点。四张图共用容量比例和场站色标；两张绝对值图共用底色色标，两张变化图共用以零对称的发散色标。
- 灰色表示缺测；有容量但暴露缺测时显示灰圆。容量为零或不可用时无圆。小容量国家的圆可能较小，保留真实面积比例。南极不展示。

## 缓存复用与验证

1. 国家网格直接读取 `../grid/outputs/<model>/csv/country_annual_exposure.csv` 的 `any` 事件，复用 2030s 和 2050s 的年度指标。
2. 场站发布入口为 `/work/share/acp6varuz3/extreme_grid/stations_v2/runtime/authoritative_index.json`。读取已发布场站映射、容量目录、2050–2054/2055–2059 两段结果的元数据。核对场站与网格源索引身份、源文件路径/大小/修改时间、事件集合、映射身份、场站顺序、坐标和格点域归属。
3. 当前场站结果 `activation_mask=off`，同格点各事件时间序列与网格相同。因此从 `../../global/grid/outputs/cache_manifest.json` 定位缓存，按映射的 `source_iy/source_ix` 读取 `event_days[year,any]`，避免重读所有逐时事件。年度有效时间要求至少 99%，使用原生日历。
4. 每个模式/SSP/技术组从实际场站文件抽查一处有容量的有效映射点和一处无效映射点（存在时），重新计算完整 2050–2059 年的事件并集、有效时长与缓存对比。检查记录在每组 JSON 中。
5. 新增 24 份国家场站年度 CSV 缓存；指纹包含来源索引、网格清单、边界与准备脚本 SHA256，并校验 CSV 内容哈希，可重复复用。
6. 汇总表同时保留网格覆盖率、总装机、有效装机、场站数和容量覆盖率。模式分别存储，主图只读取 `ensemble_mean`。

## 文件与运行

- `prepare_country_exposure.py/.sh`：准备数据，默认 16 进程、16 核、56 GB。
- `plot_country_exposure_maps.py/.sh`：生成四张 PNG，4 核、14 GB。
- `test_country_exposure.py/.sh`：容量加权、完整年代/模式、缺测、国家边界和圆面积测试，1 核、3.5 GB。
- 所有脚本使用仓库 `.venv` 和 `wzhctest`，在计算节点执行。默认参数即可运行。

从仓库根目录提交：

```bash
mkdir -p logs/RQ1_extreme/country/distribution_maps
sbatch RQ1_extreme/country/distribution_maps/test_country_exposure.sh
prepare_job=$(sbatch --parsable RQ1_extreme/country/distribution_maps/prepare_country_exposure.sh)
sbatch --dependency=afterok:"$prepare_job" RQ1_extreme/country/distribution_maps/plot_country_exposure_maps.sh
```

输出：

```text
outputs/
├── cache/<model>/<ssp>_<tech>.csv + .json
├── csv/station_country_annual_2050s.csv
├── csv/country_map_metrics.csv
├── run_config.json
└── figures/
    ├── country_exposure_2050s_wind_solar.png
    ├── country_exposure_2050s_combined.png
    ├── country_exposure_change_2050s_minus_2030s_wind_solar.png
    ├── country_exposure_change_2050s_minus_2030s_combined.png
    └── figure_config.json
```

PNG 为 300 dpi，分开图 4320 × 2130 像素，合并图 4320 × 1335 像素。来源表、绘图范围、色标、面积比例和代码哈希一并保存。验证记录见 `VALIDATION.md`。
