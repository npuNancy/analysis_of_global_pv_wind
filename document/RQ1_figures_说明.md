# RQ1：未来气候如何改变风光出力 —— 绘图代码与图件说明

本文件说明 RQ1 各绘图脚本的作用、每张图每个子图的含义，以及横轴 / 纵轴 / 颜色等编码。

- **数据目录**：`data_mock/mock_RQ_data/RQ1_future_generation/`
- **输出目录**：`outputs/RQ1_future_generation/`
- **绘图字体**：思源黑体 `Source Han Sans SC`（`/data4/yanxiaokai/SourceHanSansSC-Normal.otf`）

## 通用约定

| 维度 | 取值 |
|---|---|
| 时间 `target_year` | 2030 / 2040 / 2050 |
| 国家 / 区域 `country` | 28 个 |
| SSP 路径 | SSP1-2.6 / SSP2-4.5 / SSP5-8.5 |
| 技术 `technology` | 风电 wind / 光伏 solar |
| 部署情景 `deploy_ssp` | 决定**装机容量**（机队） |
| 气候情景 `climate_ssp` | 决定**气象/容量因子** |

> 关键方法：
> - **容量因子（CF）** 纯由气候驱动 → 固定机队（`deploy_ssp = SSP2-4.5`），仅变化 `climate_ssp`，隔离气候信号。
> - **发电量** = 装机 × CF，同时受装机与气候影响 → 用自洽情景（`deploy_ssp == climate_ssp`）画真实轨迹，并做装机/气候分解。
> - mock 数据无气候模型维度，按要求整体当作 **NESM3** 情形处理。

---

## 1. `plot_RQ1_cf.py` —— 风光容量因子（CF）

风电、光伏各输出一张 4 子图（a/b/c/d）。固定机队、仅变化气候情景，呈现纯气候信号。

- 光伏：[fig_CF_solar.png](../outputs/RQ1_future_generation/fig_CF_solar.png)
- 风电：[fig_CF_wind.png](../outputs/RQ1_future_generation/fig_CF_wind.png)

![风电 CF](../outputs/RQ1_future_generation/fig_CF_wind.png)

| 子图 | 内容 | 横轴 | 纵轴 | 其他编码 |
|---|---|---|---|---|
| **a** | 全球容量因子轨迹 | 目标年份（2030/2040/2050） | 容量加权 CF (%) | 3 条折线 = 3 个 SSP |
| **b** | 场站级 CF 分布（嵌套小提琴） | SSP 情景（3 类） | 场站容量因子 (%) | 同一 SSP 叠放 2030/2040/2050 三年小提琴，宽度∝场站数（场站数逐年增加 → 2050 最宽、包住 2040/2030）；白点=各年中位数 |
| **c** | 各国 CF 变化热图 | SSP 情景（3 列） | 28 个国家（按平均变化排序） | 颜色 = CF 变化率 % (2050 vs 2030)，发散色带以 0 为中心（红=升、蓝=降） |
| **d** | 涨跌幅最大的国家 | CF 变化 % (2050 vs 2030) | 国家（SSP5-8.5 下涨/跌各取 8） | 红=上升、蓝=下降 |

**可读出**：CF 随增暖整体下降，且与排放路径正相关；并能定位受影响最大的国家。

---

## 2. `plot_RQ1_generation.py` —— 风光发电量（出力）

风电、光伏各输出一张 4 子图。采用自洽情景（部署=气候）。

- 光伏：[fig_GEN_solar.png](../outputs/RQ1_future_generation/fig_GEN_solar.png)
- 风电：[fig_GEN_wind.png](../outputs/RQ1_future_generation/fig_GEN_wind.png)

![光伏 发电量](../outputs/RQ1_future_generation/fig_GEN_solar.png)

| 子图 | 内容 | 横轴 | 纵轴 | 其他编码 |
|---|---|---|---|---|
| **a** | 全球发电量轨迹 | 目标年份 | 年发电量 (TWh) | 3 条折线 = 3 个 SSP |
| **b** | 季节循环位移：2030 vs 2050 | 月份（1–12） | 容量加权 CF (%) | 灰=2030 基准；蓝虚线=2050 SSP1-2.6；红=2050 SSP5-8.5 |
| **c** | Top 国家分时段增长（SSP2-4.5） | 年发电量 (TWh) | 发电量最高的 14 国 | 堆叠条：2030 基底 + 2030→2040 增量 + 2040→2050 增量，柱高=2050 总量 |
| **d** | 装机 vs 气候 增量分解 (2030→2050) | SSP 情景 | 发电量增量 (TWh) | 灰=装机增长；红=气候(ΔCF)；浅红=交互项；并标注气候项数值 |

**可读出**：发电量增长由**装机主导**，气候(ΔCF)为二阶且为负；季节循环形态与峰值随增暖改变。

---

## 3. `plot_RQ1_generation_cfstyle.py` —— 风光发电量（与 CF 图四子图保持一致）

与 `plot_RQ1_cf.py` 采用**相同框架**（固定机队 `deploy=SSP2-4.5`，仅变化气候情景）和**相同的四子图布局**，只把指标由 CF 换成发电量，便于与 CF 图逐子图直接对照。

- 光伏：[fig_GENcf_solar.png](../outputs/RQ1_future_generation/fig_GENcf_solar.png)
- 风电：[fig_GENcf_wind.png](../outputs/RQ1_future_generation/fig_GENcf_wind.png)

![风电 发电量（CF 式）](../outputs/RQ1_future_generation/fig_GENcf_wind.png)

| 子图 | 内容 | 横轴 | 纵轴 | 其他编码 |
|---|---|---|---|---|
| **a** | 全球发电量轨迹 | 目标年份 | 年发电量 (TWh) | 3 条折线 = 3 个 SSP（固定机队下几乎重合） |
| **b** | 场站级发电量分布（嵌套小提琴） | SSP 情景（3 类） | 场站年发电量 (GWh，对数) | 叠放 2030/2040/2050，宽度∝场站数；白点=各年中位数 |
| **c** | 各国发电量变化热图 | SSP 情景（3 列） | 28 个国家（按平均变化排序） | 颜色 = 发电量变化率 % (2050 vs 2030)，发散色带以 0 为中心 |
| **d** | 变化幅度最大的国家 | 发电量变化 % (2050 vs 2030) | 国家（SSP5-8.5，最高/最低各 8） | 红=增、蓝=减 |

**可读出**：固定机队下三条 SSP 发电量轨迹**几乎重合**——气候对总发电量的影响远小于装机扩张，随时间的增长主要由装机驱动；与 CF 图（气候信号清晰）互为印证。

> 与第 2 节 `plot_RQ1_generation.py` 的区别：第 2 节用自洽情景（部署=气候）讲"真实发电量故事"（季节循环、装机/气候分解）；本节用固定机队隔离气候、并复用 CF 图的四子图模板。两者并存、输出文件名不冲突（`fig_GEN_*` vs `fig_GENcf_*`）。

---

## 4. `plot_RQ1_synthesis.py` —— CF 与发电量综合对比（风电 vs 光伏）

单张图，2 子图（a/b），把"资源信号"与"出力规模"并排对比。

- [fig_synthesis_wind_vs_solar.png](../outputs/RQ1_future_generation/fig_synthesis_wind_vs_solar.png)

![综合对比](../outputs/RQ1_future_generation/fig_synthesis_wind_vs_solar.png)

| 子图 | 内容 | 横轴 | 纵轴 | 其他编码 |
|---|---|---|---|---|
| **a** | 容量因子中的气候信号 | 技术（光伏 / 风电） | 全球 CF 变化 % (2050 vs 2030) | 分组柱，3 色 = 3 个 SSP |
| **b** | 发电量总增长 | 技术（光伏 / 风电） | 发电量增量 (TWh, 2030→2050) | 分组柱，3 色 = 3 个 SSP |

**可读出**：CF 受损程度随增暖单调加深（光伏降幅 > 风电）；发电量增量则受装机规模主导。

---

## 5. `plot_RQ1_cf_capacity_quadrant.py` —— 容量因子 vs 装机容量（四象限）

风电、光伏各输出一张图，含 3 个子图（按 climate_ssp 排列）。固定机队（deploy=SSP2-4.5）、2050 年，仅变化气候情景，因此装机（y）逐面板不变，点云左移即纯气候信号。

> 默认仅保存 PNG；如需可编辑矢量图，调用 `save_fig(fig, name, vector=True)` 额外导出 PDF/SVG。

- 光伏：[fig_CFvsCAP_quadrant_solar.png](../outputs/RQ1_future_generation/fig_CFvsCAP_quadrant_solar.png)
- 风电：[fig_CFvsCAP_quadrant_wind.png](../outputs/RQ1_future_generation/fig_CFvsCAP_quadrant_wind.png)

![风电 象限图](../outputs/RQ1_future_generation/fig_CFvsCAP_quadrant_wind.png)

**每个子图（= 一个 SSP 情景）**

| 编码 | 含义 |
|---|---|
| 横轴 | 容量因子 (%) —— 资源质量 |
| 纵轴 | 装机容量 (MW，对数轴) —— 部署规模 |
| 颜色 | 年发电量 (GWh，对数) —— 实际出力 |
| 竖线 / 横线 | 固定参考线 = 机队 CF 中位数 / 装机中位数（各面板一致） |
| 角标 | 各象限的场站数 `n` 与占本面板发电量比例 |

**四象限**

| 位置 | 名称 | 含义 |
|---|---|---|
| 右上 | 旗舰 | 高 CF + 高装机（优质且重点部署） |
| 右下 | 待开发 | 高 CF + 低装机（优质但未充分开发，扩容机会） |
| 左上 | 低效 | 低 CF + 高装机（资源差却重装机，搁浅资产风险） |
| 左下 | 边缘 | 低 CF + 低装机 |

**可读出**：随增暖加剧，点云整体左移、平均 CF 下降；部分高装机场站由"旗舰"滑向"低效"象限——既有资产发电效率被气候削弱。

---

## 运行方式

```bash
cd /data6/yanxiaokai/project_energy_climate/analysis_of_global_pv_wind
python3 plot_RQ1_cf.py                     # 风光 CF
python3 plot_RQ1_generation.py            # 风光发电量（自洽情景）
python3 plot_RQ1_generation_cfstyle.py    # 风光发电量（与 CF 图布局一致）
python3 plot_RQ1_synthesis.py             # CF 与发电量综合对比
python3 plot_RQ1_cf_capacity_quadrant.py  # CF vs 装机 四象限
```
