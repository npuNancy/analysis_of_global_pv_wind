# RQ3：极端天气导致多少风光场站出力损失 —— 分析角度与图表规划

> 整理日期：2026-08-17
>
> RQ3：极端天气会导致多少风光场站出力损失？
>
> 参考代码：`ref_code/calculate_wind_solar_generation_loss`
>
> 可用数据：`data/generation_loss_outputs`

## 一、数据现状盘点

**可用数据规模**：`generation_loss/CANESM5/{ssp126, ssp245, ssp585}/26国/{2030, 2040, 2050}/{wind, solar}/`，共 1895 个场站级 NetCDF（每年一个文件，如 `wind_generation_loss_station_2033.nc`，2030 快照覆盖 2033–2037，center-k 方案）。

**每个文件包含**：场站坐标（`lon/lat/station_id/capacity_mw/activation_year`）× 事件类型 × 8 类指标：

| 维度 | 内容 |
|---|---|
| **事件类型（风）** | high_temp、high_wind、hot_humid、icing、low_resource、all（并集） |
| **事件类型（光）** | cold_highwind、freezing_rain、high_humidity、icing、low_resource、rainstorm、all |
| **指标族** | 绝对损失 MWh、净损失 MWh、相对损失 %、事件时长/损失小时、损失强度、normalized_generation_loss（占全年正常发电比，即原 risk）、波动量、单位容量损失（MWh/MW） |

另外还有 `baselines/`、`station_cf/`、`station_signals/` 可以下钻。

**注意事项**：

- **aggregate CSV 尚未生成**（aggregate 步骤没跑或没拷出来），分析前要么先跑 `aggregate` 子命令，要么直接读 nc；
- 单模式 CANESM5，结论表述时注意这是单模式结果；
- 已抽查德国 solar，rainstorm/freezing_rain 损失非零，**不受** RQ2 那个 pr 单位 bug 影响（不同链路生成的信号）。

## 二、分析角度

### 角度 1：总量账本 —— "极端天气吞掉多少发电量"

- 绝对损失（MWh）按国别/情景/年代汇总，回答"损失有多大规模"；
- `normalized_generation_loss`：损失占全年应发电量的百分比 → "极端天气吃掉了 X% 的电"，这是最能讲故事的核心指标；
- 容量归一（`net_generation_loss_per_mw`）：剔除装机规模差异，做公平的跨国比较。

### 角度 2：事件归因 —— "哪类极端是主凶"

- 分事件类型分解损失贡献：风电看高温/大风/湿热/覆冰/低资源，光伏看暴雨/冻雨/高湿/覆冰/低资源；
- 风电 vs 光伏的主导事件截然不同（预期：风电低资源+大风，光伏低资源+暴雨），对比本身就有结论价值；
- `all`（并集）vs 各事件之和的差异还能反映事件重叠程度。

### 角度 3：气候演变 —— "未来会更糟吗"

- 2030s → 2040s → 2050s 三个年代的损失演化；
- ssp126/245/585 三情景分化：情景间差距随年代拉大是核心叙事；
- 可细分到"事件类型 × 年代"：比如湿热损失增速远快于覆冰损失。

### 角度 4：空间格局 —— "风险集中在哪里"

- 国别排名与地图分布；
- 纬度/气候带规律：低纬湿热型损失 vs 高纬覆冰型损失的地理分异；
- 场站级粒度直接画点，能看到国界内部分的区域差异。

### 角度 5：场站异质性 —— "谁最脆弱"

- 场站级损失率分布（不是均值，看长尾）；
- Top-N 最脆弱场站画像：容量、位置、主导事件；
- `activation_year` 新旧场站是否有系统性差异。

### 角度 6：损失机制 —— "暴露如何转化为损失"

- `loss_hours / event_duration_hours`：暴露时长中真正转化为损失的比例（转化率）；
- `generation_loss_intensity`：事件期内的损失强度 vs normalized（全年摊薄）对比，区分"频繁小损"与"罕见重损"两种风险形态；
- 波动量（fluctuation）：对电网调度视角，波动本身也是成本。

## 三、可画的图

| # | 图 | 角度 | 说明 |
|---|---|---|---|
| 1 | **全球场站气泡地图**（双面板风/光） | 1+4 | size=容量，color=normalized loss，最直观的主图 |
| 2 | **国别排名条形图** | 1 | per-MW 损失或 normalized loss，26 国排序，可分情景小面板 |
| 3 | **事件类型堆叠条形图** | 2 | 每国损失按事件类型堆叠，或全球总量饼图 |
| 4 | **年代 × 情景热力图** | 3 | 行=国家、列=年代×情景，色=损失变化率或水平 |
| 5 | **全球总量演化折线图**（✅已实现） | 3 | 三情景三条线，2030s→2050s 走势 + 年际 min–max 误差条 |
| 5b | **全球损失率演化折线图**（✅已实现） | 3 | 损失率=损失/应发电量，剔除装机与覆盖差异的公平比较口径 |
| 6 | **风光对比分组条形图** | 2 | 同一国家 wind vs solar 的 normalized loss 肩并肩 |
| 7 | **场站分布箱线图/小提琴图** | 5 | 按国家分组，展示长尾和离群场站 |
| 8 | **强度–频率象限散点图** | 6 | x=事件时长占比，y=损失强度，color=normalized loss，风险矩阵 |
| 9 | **Top-N 脆弱场站标注图** | 5 | 地图上圈出损失最重的场站，附容量和主导事件 |
| 10 | **事件类型年代演化小多组图** | 2+3 | 每类事件一个小面板，损失随年代/情景变化斜率对比 |

**优先级建议**：主图选 1（地图）+ 5/5b（情景演化折线）+ 3（事件归因堆叠图），这三个分别回答"哪里、多严重、为什么"；2 和 6 作为补充；7/8/9 放附录或支撑分析。

## 四、已实现图表的口径说明

### 4.1 数据与聚合链路（两图共用）

- **输入**：`generation_loss_region.csv`（ref_code aggregate 的 region 级年度长表），`event = all`（全部支持事件的并集）；
- **分析窗口**：center-k（K=2），2030s→2033–2037、2040s→2043–2047、2050s→2053–2057。每个年代点 = 窗口内各年的均值，误差条 = 年际最小–最大值。窗口内分母（应发电量）逐年严格相等（CF-normal 由整个窗口一次算出、96 个"月份×时槽"槽均值，容量取年代快照固定），故逐年波动全部来自分子（真实天气）；
- **覆盖口径**：绝对量按各情景-年实际覆盖国家加总（部分国家在部分情景无 SSP 场站，pipeline 以 SKIPPED_NO_STATIONS 正常跳过；SSP5-8.5 气象强迫使用 SSP5-6.0 部署表）。覆盖国家数随情景与年代变化（风电约 22–26 国、光伏 10–23 国），详见各图脚注与汇总 CSV。

### 4.2 图 5：全球净出力损失总量（`plot_RQ3_generation_loss_global_evolution.py`）

- **指标**：`net_generation_loss_mwh`（净损失）region 级逐年求和（MWh→TWh）；
- **净损失 vs 绝对损失**：绝对损失只累计 cf<normal 的时刻；净损失在全部事件暴露时刻累计 (normal−cf)×cap×Δt，事件期内的出力增益会抵消损失——对系统全年电量账更有意义；
- **输出**：`RQ3/outputs/{MODEL}/fig_RQ3_generation_loss_global_evolution.png` + `csv/RQ3_generation_loss_global_evolution.csv`。

### 4.3 图 5b：全球出力损失率（`plot_RQ3_generation_loss_rate_global_evolution.py`）

- **指标**：

  ```text
  损失率 = Σ_regions net_generation_loss_mwh / Σ_regions normal_all_generation_mwh × 100%
  ```

  分母 `normal_all_generation_mwh` = 全年应发电量（CF-normal × capacity_mw × 全年时间步之和），是反事实口径（"正常年景应发多少电"），非实际发电量；
- **聚合规则（关键）**：必须在 region 级逐年**先累计分子分母、再相除**得逐年全球损失率，然后才取年代均值。不能对 region 级比例直接平均——比例与分母规模负相关（高损失率国多为小体量国），简单平均等于隐式假设各国应发电量相等。实测 ssp126 光伏 2030s：正确口径 2.73% vs 简单平均 3.66%（高估 34%）；
- **输出**：`RQ3/outputs/{MODEL}/fig_RQ3_generation_loss_rate_global_evolution.png` + `csv/RQ3_generation_loss_rate_global_evolution.csv`。

### 4.4 两图的联合结论（CANESM5）

1. **绝对量四倍增长由装机驱动**：风电净损失 2030s→2050s 增长约 4 倍（SSP1-2.6 约 500→2000 TWh/年），与 RQ1 总发电量轨迹高度同构（Pearson r=0.999，损失≈总发电量的稳定比例）；
2. **单位损失率平稳**：风电 9.6–12.5%、光伏 1.9–3.5%，年代间几乎无趋势——气候信号被 SSP 部署差异淹没，绝对量图讲的是"装机故事"，损失率图才回答"单位风险是否恶化"（答案：平稳）；
3. **情景分化顺序继承自部署路径**：SSP1-2.6 > SSP2-4.5 > SSP5-8.5，跨情景比较必须用损失率等归一化口径。

对比留档：`RQ3/outputs/CANESM5/csv/RQ1_gen_vs_RQ3_loss.csv`（发电量 vs 损失、增长倍数、损失/发电量之比）。

**口径提醒**：若要总量口径（MWh），26 国装机差异巨大（澳大利亚、印度等容量悬殊），建议图 2 一律用 per-MW 或 normalized 口径，绝对量只在图 5 的全球总账里出现。
