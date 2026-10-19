# 全球与国家的部署规模、布局及发电损失

分析2050年装机快照、2050–2059年均结果。全球加SSP126、2050年风电与光伏合计目录容量前k个国家；默认k=10。风光使用同一固定国家名单，分别计算。GLOBAL为正式全球汇总，不是Top-k之和。国家目录排除无法归属或归属不明记录；中国采用已有CHN合并口径。

## 科学问题与图件约定

Python/matplotlib、定量多面板；仅PNG、600 dpi，完整图与逻辑子图组合同时导出。所有量先逐模式计算，再对四模式等权汇总；min–max表示模式范围。

| 问题 | 图件 | 编码 |
|---|---|---|
| 不同规模与总损失/正常发电能力如何共同变化？ | paired_path_overview.png | 三条配对路径的C、L、G0绝对量；点为均值、线为模式范围；全正量使用明确标注的对数轴 |
| 布局能否抵消规模贡献？ | scale_layout_climate126/245/585.png | 固定气候，245−126和585−126；正负贡献条、净差菱形、净差模式范围 |
| 抵消是否伴随正常发电能力降低？ | generation_tradeoff.png | 每对部署按高容量−低容量定向；H0变化%，角标表示四模式均有抵消 |
| 固定气候下哪些部署损失较低？ | deployment_performance.png | 三气候、两部署差的R和ρ；同指标共用色标，保留数值 |
| 上述表现能否跨气候保持？ | deployment_robustness.png | 每气候集合均值最低部署、四模式支持数，以及全部12组合一致最低部署 |

贡献图除以同国家、同技术、同模式、同气候的部署126全年正常电量G0_ref，以参考正常电量百分比表示；不是净损失百分比变化，也不是ρ之差。原始TWh和全部模式值保留源表。分组图保留对应单位、图例、色条和说明。

## 指标与分解

C为共同有效容量，L为事件并集年均净损失，G0为全年正常发电量，R=L/C，H0=G0/C，ρ=L/G0。H0是全年正常等效满发小时，不是事件期CF。所有能量采用原始值，净损失保留符号。

固定气候、技术、年代，对部署A、B：
$$
\Delta L = \Delta C \frac{R_A+R_B}{2} + \frac{C_A+C_B}{2}\Delta R.
$$
两项分别为规模与布局贡献，交互已分摊。配对气候—部署差不能直接套用布局解释。

为描述装机增加，源表另保存高容量−低容量方向；仅当扩张规模贡献为正时定义抵消率。无装机、缺测、容量相同与净损失为零分开处理。

同一正常发电目标Q取该国、技术、模式、气候的部署126 G0：
$$
\frac{C^*}{C_{126}}=\frac{H_{0,126}}{H_{0,\mathrm{target}}}, \qquad L^*=Q\rho_{\mathrm{target}}.
$$
这里的 $\rho$ 为小数。
它是容量线性缩放、保持空间份额的标准化比较，不表示实际供电保证，不验证土地、电网或成本可行性。

逐模式、逐气候分别按R与ρ排名；数值容差内允许并列。严格稳健最低部署须在3气候×4模式全部组合中不劣于另外两部署。模式支持不是概率或统计显著性，不能据此推断国家应选择哪条全球SSP。

## 数据与运行

只读公共汇总：`paper_figures/prepare/outputs/loss_summary/window.csv.gz`、`catalogues/capacity_by_country.csv`、`catalogues/countries.csv`。排名采用目录容量，指标采用各部署内的共同有效容量。正常基线及事件定义遵循正式Loss；年度共同支持不保证逐时支持完全相同。部署585来源仍为SSP5-6.0文件。

在1866仓库根目录：

```bash
source .venv/bin/activate
mkdir -p logs/paper_figures/country_deployment_tradeoffs
python -m paper_figures.main.country_deployment_tradeoffs.prepare_data --top-k 10
python -m paper_figures.main.country_deployment_tradeoffs.plot --top-k 10
python -m paper_figures.main.country_deployment_tradeoffs.report --top-k 10
```

当前任务只读取已有汇总表，优先在登录节点直接运行。每个Python入口均有同名SLURM脚本；用bash调用时先建日志目录再提交，默认wzhctest、1节点，使用仓库.venv。

代码与SLURM脚本位于`paper_figures/main/country_deployment_tradeoffs/`。图件、源表和元数据输出位于本目录的`outputs/top10/`；更改k时三个入口使用相同`--top-k`，结果写入对应`outputs/top{k}/`。包括7张完整PNG及逻辑分组、逐国结果表、模式级与集合源表、输入/输出哈希和验收记录。HTML中文分析报告写入`paper_figures/analysis/analysis_20261019_005216/country_deployment_tradeoffs_top{k}.html`（默认`top10`），图件和源表复制至报告目录assets/images与assets/data的对应top-k子目录，使用相对链接。默认Top-10的完整分析同时整合进同目录report.html与report.md。较大k的绘图按脚本版式处理，不改变国家排名或结果数据。
