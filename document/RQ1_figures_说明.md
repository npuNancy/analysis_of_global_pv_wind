# RQ1：未来气候如何改变风光出力 —— 绘图代码与图件说明

本文件说明 RQ1 各绘图脚本的作用、每张图每个子图的含义，以及横轴 / 纵轴 / 颜色等编码。

- **数据目录**：`data_mock/mock_RQ_data/RQ1_future_generation/`
- **输出目录**：`outputs/RQ1_future_generation/`
- **绘图字体**：思源黑体 `Source Han Sans SC`（`data/tracked/SourceHanSansSC-Normal.otf`）

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

## 6. 候选 / 探索图 —— SSP 差异专题（输出在 `outputs/RQ1_future_generation/tmp/`）

以下 6 个脚本专门用于**对比不同 SSP 的差异**，参考 Nature 的画图逻辑，每个脚本单独运行、结果暂存于 `tmp/`，用于挑选最终方案。除特别说明外均：固定部署机队（`deploy=SSP2-4.5`）、仅变化 `climate_ssp`、目标年份 2050。

### 6.1 `plot_RQ1_ssp_fan.py` —— SSP 发散扇形图
[fig_sspfan.png](../outputs/RQ1_future_generation/tmp/fig_sspfan.png) ｜ 单图 2 面板（光伏 / 风电）

![SSP 发散](../outputs/RQ1_future_generation/tmp/fig_sspfan.png)

- 横轴：目标年份；纵轴：CF 相对 2030 的异常值 (%)。
- 实线 = 全球容量加权异常；阴影带 = 28 国异常值的 25–75% 分布；2050 处标注 SSP1-2.6↔SSP5-8.5 差距。
- **可读出**：差异从 0 张开成"扇形"，扇口即 SSP 差异，随时间放大。

### 6.2 `plot_RQ1_deploy_climate_matrix.py` —— 部署×气候 3×3 矩阵 ★
[fig_matrix_solar.png](../outputs/RQ1_future_generation/tmp/fig_matrix_solar.png) ｜ [fig_matrix_wind.png](../outputs/RQ1_future_generation/tmp/fig_matrix_wind.png)（风/光各一张，每张 2 个矩阵）

![部署×气候矩阵（光伏）](../outputs/RQ1_future_generation/tmp/fig_matrix_solar.png)

- 行 = `deploy_ssp`，列 = `climate_ssp`（用满 9 组交叉，2050）。左矩阵=全球发电量(TWh)，右矩阵=容量加权 CF(%)。
- 颜色 = 相对各自矩阵均值的偏差(%)；格内标注原值；黑框 = 自洽情景（对角线）。
- **可读出**：发电量沿**行（部署）**变化大、CF 沿**列（气候）**变化大——两个 SSP 维度作用在不同指标上。

### 6.3 `plot_RQ1_country_dumbbell.py` —— 各国哑铃对比 ★
[fig_dumbbell.png](../outputs/RQ1_future_generation/tmp/fig_dumbbell.png) ｜ 单图 2 栏（光伏 / 风电）

![各国哑铃](../outputs/RQ1_future_generation/tmp/fig_dumbbell.png)

- 横轴：容量加权 CF (%)；纵轴：国家，**按 SSP5-8.5 的 CF 升序**排列（脚本内 `SORT_BY` 可改为 `ssp126`）。
- 每国一条哑铃：蓝点=SSP1-2.6、红点=SSP5-8.5，连线=气候路径造成的差距（红=CF 下降、蓝=上升）。
- **可读出**：逐国 SSP 间 CF 差距与方向，资源由低到高排开。

### 6.4 `plot_RQ1_latitude_profile.py` —— 纬度 / 资源带剖面
[fig_latprofile_solar.png](../outputs/RQ1_future_generation/tmp/fig_latprofile_solar.png) ｜ [fig_latprofile_wind.png](../outputs/RQ1_future_generation/tmp/fig_latprofile_wind.png)（风/光各一张，2 面板）

![纬度剖面（光伏）](../outputs/RQ1_future_generation/tmp/fig_latprofile_solar.png)

- (a) 横轴=纬度带，(b) 横轴=`resource_index` 十分位；纵轴均为场站 CF (%)。3 条 SSP 线 + 25–75% 带。
- 经 `station_id` 把场站 CF（随气候变化）关联到 catalog 的纬度/资源等级（二者不随气候情景变化）。
- **可读出**：SSP 差异沿纬度/资源等级的分布；SSP5-8.5 全程低于 SSP1-2.6。

### 6.5 `plot_RQ1_seasonal_divergence.py` —— 季节循环中的 SSP 分歧
[fig_seasondiv_solar.png](../outputs/RQ1_future_generation/tmp/fig_seasondiv_solar.png) ｜ [fig_seasondiv_wind.png](../outputs/RQ1_future_generation/tmp/fig_seasondiv_wind.png)（风/光各一张，2 面板）

![季节分歧（风电）](../outputs/RQ1_future_generation/tmp/fig_seasondiv_wind.png)

- (a) 横轴=月份、纵轴=容量加权 CF (%)，2050 三情景 + 2030 基准灰线；(b) 横轴=月份、纵轴=逐月 (SSP5-8.5 − SSP1-2.6) 差值。
- **可读出**：气候分歧具有季节结构，(b) 定位差异最大的月份。

### 6.6 `plot_RQ1_stability_complementarity.py` —— 出力稳定性与风光互补 ★
[fig_stability.png](../outputs/RQ1_future_generation/tmp/fig_stability.png) ｜ 单图 3 面板

![稳定性与互补](../outputs/RQ1_future_generation/tmp/fig_stability.png)

- (a)(b) 横轴=SSP、纵轴=场站 12 月 CF 的变异系数 CV(%)（光伏 / 风电）；(c) 横轴=SSP、纵轴=各国月度"风×光发电量"相关系数（越负互补越好）。小提琴 + 中位数。
- **可读出**：超越均值的维度——增暖下出力波动与风光互补如何变化。

> 这些图当前仅存于 `tmp/`（探索阶段）。挑定后再移入正式目录并并入上文章节。

---

## 运行方式

```bash
cd /data6/yanxiaokai/project_energy_climate/analysis_of_global_pv_wind
python3 plot_RQ1_cf.py                     # 风光 CF
python3 plot_RQ1_generation.py            # 风光发电量（自洽情景）
python3 plot_RQ1_generation_cfstyle.py    # 风光发电量（与 CF 图布局一致）
python3 plot_RQ1_synthesis.py             # CF 与发电量综合对比
python3 plot_RQ1_cf_capacity_quadrant.py  # CF vs 装机 四象限

# 候选 / 探索图（SSP 差异专题，输出到 tmp/）
python3 plot_RQ1_ssp_fan.py                    # SSP 发散扇形图
python3 plot_RQ1_deploy_climate_matrix.py      # 部署×气候 3×3 矩阵
python3 plot_RQ1_country_dumbbell.py           # 各国哑铃对比
python3 plot_RQ1_latitude_profile.py           # 纬度 / 资源带剖面
python3 plot_RQ1_seasonal_divergence.py        # 季节循环中的 SSP 分歧
python3 plot_RQ1_stability_complementarity.py  # 出力稳定性与风光互补
```
