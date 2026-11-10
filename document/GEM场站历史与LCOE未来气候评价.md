# GEM逐年实际场站与LCOE未来场站气候评价

2015—2025采用GEM逐年回溯场站（historical_snapshot，允许退出和容量变化）；2026—2029固定2025装机；2030—2059采用新的累计LCOE布局。仅含陆上及类型未知风电。

## 数据目录

- 共享根：/work/home/acxujo26gv/lcoe_gem2025_climate_storage；十计算账号可写，1866与其他账号可读。
- 完整索引：/work/home/acxujo26gv/lcoe_gem2025_climate_storage/runtime/authoritative_index.json；验收：/work/home/acxujo26gv/lcoe_gem2025_climate_storage/runtime/completion.json。
- 原生CF/Extreme：/work/home/acxujo26gv/lcoe_gem2025_climate_storage/historical/outputs、/work/home/acxujo26gv/lcoe_gem2025_climate_storage/transition/outputs、/work/home/acxujo26gv/lcoe_gem2025_climate_storage/future/outputs。
- 逐站年度数组：/work/home/acxujo26gv/lcoe_gem2025_climate_storage/station_results；98个NPZ，包括坐标、容量、覆盖标记、CF、暴露、损失和全年发电。
- 年度字段、单位和容量口径：/work/home/acxujo26gv/lcoe_gem2025_climate_storage/station_results/manifest.json；各条记录代表一种技术的一个0.1°网格。
- 完整交叉路径年度CSV：/work/home/acxujo26gv/lcoe_gem2025_climate_storage/source_data/global_annual_models.csv；模式汇总：global_annual_ensemble.csv；覆盖：capacity_coverage.csv。
- 绘图源表：[plot_series.csv](../paper_figures/supplementary/gem_lcoe_history/outputs/source_data/plot_series.csv)；拟合：[linear_fits.csv](../paper_figures/supplementary/gem_lcoe_history/outputs/source_data/linear_fits.csv)。

## 验收记录

已完成历史、过渡期与未来完整交叉矩阵；正式索引包含49,100个原生CF/Extreme文件和98个年度场站NPZ。全球年度逐模式CSV有3,417行，模式汇总CSV有879行。

| 阶段 | 年份 | 逐模式记录数 | 有效容量占完整目录容量 |
|---|---|---:|---:|
| 历史 | 2015—2025 | 33 | 95.63%—98.09% |
| 过渡 | 2026—2029 | 144 | 97.18%—97.95% |
| 未来 | 2030—2059 | 3240 | 96.04%—99.45% |

覆盖范围综合各年份、路径及技术。通过年份与容量匹配、模式数量、CF范围、事件能量关系、文件完整性及读取权限核对。

图件共9张组图和27张独立子图，均为600 dpi PNG；全部完成目视检查。本地同路径副本的图像SHA256与1866正式图件一致。验收记录见[figure_validation.json](../paper_figures/supplementary/gem_lcoe_history/outputs/figure_validation.json)。

原有 document/BCSD_v2数据使用指南.md、document/风电光伏数据.md、document/风电光伏数据.html 的SHA256保持不变。

## 计算与展示口径

- 使用纠正后的0.1°网格编号按同一格匹配ERA5/BCSD源点，不跨格补点。场站网格中心与实际取样点坐标分别保存；原生CF/Extreme不套用投运掩膜，年度指标显式使用当年容量。
- 历史使用ERA5-Land逐小时数据；BCSD保留模式原生三小时日历。光伏装机为MWp/DC，风电为MW；风电能量不乘0.1。全年发电量由全年CF积分。
- 历史每年以当年年末装机容量固定用于全年计算，未按年内投运月份折算；发电量是气候驱动的模型估算，不是实测发电统计。
- 未来布局的原生CF/Extreme按原产品范围保留2015—2060；其年度评价采用2030—2059。历史年度评价另用ERA5及逐年实际装机。
- 历史Loss沿用南北分析的固定全历史期、按月和小时且排除事件并集的正常CF基线方法，本轮窗口为2015—2025。过渡期窗口为2026—2029（中心2027）；未来分别为2030—2039、2040—2049、2050—2059。低资源事件基准期另为2015—2024。
- 历史累计辐射、降水按ERA5-Land重置规则差分为小时量；按valid_time归年。Loss分别用12×24与12×8月—小时基线。历史末尾低资源居中窗口不足的时间保持缺测。
- 损失为事件并集下的带符号净损失；单位装机量先汇总能量再除相同有效集合的容量。净损失比例的分母为全年正常基准电量；暴露不重复累加重叠事件。
- 各阶段、路径、技术内使用跨年份及四模式共同有效站点；缺测不作零。总装机图显示完整目录容量，其余图显示有效集合指标，容量覆盖单独保留。阶段间有效支持可能不同。
- 黑线为2015—2025；彩线为2026—2059四模式均值。场站/气候配对为126/126、245/245、560/585，完整三乘三交叉数据均保存。曲线差同时包含气候与部署变化。
- 每条彩线从黑线2025端点接出，未平移未来数值。虚线仅拟合2030—2059。四模式最小值和最大值保存在源表，不解释为置信区间。各子图Y轴独立，均为5个间隔。

## 读取年度场站结果

```python
import json
from pathlib import Path
import numpy as np
root = Path('/work/home/acxujo26gv/lcoe_gem2025_climate_storage')
index = json.loads((root / "runtime/authoritative_index.json").read_text())
entry = next(e for e in index["annual_archives"]
             if e["phase"] == "future" and e["station_ssp"] == "ssp560"
             and e["climate_ssp"] == "ssp245" and e["model"] == "CANESM5" and e["tech"] == "wind")
with np.load(entry["path"], allow_pickle=False) as z:
    i = int(np.flatnonzero(z["years"] == 2050)[0])
    capacity = z["capacity_mw"][i]
    loss = z["net_loss_mwh"][i]
    valid = z["common_support"] & (capacity > 0) & np.isfinite(loss)
    unit_loss = loss[valid].sum() / capacity[valid].sum()  # MWh/MW/year
```

原生NetCDF通过同一索引的entries筛选phase、product、model、climate_scenario、station_scenario和tech，再读取artifacts中的path；空组合标记EMPTY_NO_STATIONS。

## 图件

### 总净损失

![总净损失](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_loss.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_loss_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_loss_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_loss_c.png)。

### 单位装机净损失

![单位装机净损失](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_loss.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_loss_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_loss_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_loss_c.png)。

### 净损失占正常基准电量比例

![净损失占正常基准电量比例](../paper_figures/supplementary/gem_lcoe_history/outputs/station_loss_fraction.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_loss_fraction_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_loss_fraction_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_loss_fraction_c.png)。

### 全年总发电量

![全年总发电量](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_generation.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_generation_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_generation_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_total_generation_c.png)。

### 单位装机全年发电量

![单位装机全年发电量](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_generation.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_generation_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_generation_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_unit_generation_c.png)。

### 完整目录装机容量

![完整目录装机容量](../paper_figures/supplementary/gem_lcoe_history/outputs/station_capacity.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_capacity_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_capacity_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_capacity_c.png)。

### 装机加权暴露总量

![装机加权暴露总量](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_total.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_total_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_total_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_total_c.png)。

### 装机加权平均暴露时长

![装机加权平均暴露时长](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_mean.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_mean_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_mean_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_exposure_mean_c.png)。

### 容量加权全年平均CF

![容量加权全年平均CF](../paper_figures/supplementary/gem_lcoe_history/outputs/station_cf.png)

独立子图：[a wind+solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_cf_a.png)；[b wind](../paper_figures/supplementary/gem_lcoe_history/outputs/station_cf_b.png)；[c solar](../paper_figures/supplementary/gem_lcoe_history/outputs/station_cf_c.png)。

