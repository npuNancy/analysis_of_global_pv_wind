# 补充图数据核对与绘图约定

本轮使用已通过最终验收的664项数据准备结果，不重跑全套准备。既有验收记录保持在 `logs/paper_figures/completion_status/final_audit.json`；本轮独立核验和作业记录放在 `logs/paper_figures/supplementary/`。

| 图 | 面板 | 现有数据满足情况 | 本轮必要工作 |
|---|---|---|---|
| S01 | a–f | 三因子Shapley、固定部署气候差、国家与模式维度齐全 | 复用源表，核对贡献闭合及两部署平均等于Phi_C，绘制6面板 |
| S02 | a–b | 每模式10年经验超越概率齐全 | 阶梯曲线，模式均值和范围，不做KDE |
| S03 | a–b | 固定排序累计参考容量与正净损失负担齐全 | 保持参考容量加权指数含义，核对端点和单调性 |
| S04 | a–h | 三时期D、Phi_C、Phi_S、J齐全 | 容量目录168国家并集，固定顺序，4指标各6页 |
| S05 | a–f | 九组合全球损失、事件损失、格点模式一致性齐全 | 点区间和Plate Carrée地图 |
| S06 | a–d | 原始净损失、正损失、全年损失率的共同支持差值齐全 | 比较三种指标，容量加权面积编码 |
| S07 | a–b | 四季暴露齐全 | 直接复用 |
| S07 | c–d | 年度Loss不能确定季节损失 | 从CF、Extreme和正常CF重建2050–2059；逐站逐年复现正式损失后按月份季聚合 |
| S08 | a–d | 已有沿原生连续时间提取的次数、完整持时和删失统计 | 复用，不重新提取事件 |
| S09 | a–d | 缺共同正常CF基线实验 | 复用有效站点集合；在同模式同部署下用气候126基线重算全部九组合 |
| S10 | a–f | 覆盖、共同支持差异、固定人口阈值表齐全 | 绘图并保存始终高损失国家名单 |
| S11 | a–b | 未发现与10 km口径一致的较粗尺度实验 | 用户明确暂不制作，本次范围外 |

统一约定：Python、600 dpi PNG；四模式分别计算再等权汇总；模式范围不是置信区间；场站SSP和气候SSP独立；风电能量不乘0.1；缺测与零分开；all为事件时间并集；世界地图采用Plate Carrée和本地Natural Earth中国合并几何。

## 新增重建的核验与调度

入口为 `paper_figures/prepare/reconstruct_supplementary.py`，按已验收共同有效场站，读取正式CF、Extreme、Loss索引及Loss正常CF基线。每个模式、部署、技术、patch单元独立保存检查与中间结果，已完成单元可复用。按240个原生时刻连续读取整个区域，随后在内存中按station_id对齐，逐站核对每个气候和年份的原年度正/净损失，再保存季节损失和两种基线的同支持结果。

完整1128个单元已处理完成，其中864个有共同有效站点、264个为空支持。逐站逐年正/净损失复现的最大单位装机差为7.65e-6 MWh/MW，S07四季损失与正式年度窗口结果的最大差为3.87e-7 MWh/MW。S09两种基线共享有效时刻，逐单元年度最小保留比例为99.20%；气候SSP126下两种基线结果完全一致。汇总核验记录为 `paper_figures/prepare/outputs/supplementary_reconstruction/complete.json`。

队列限制每用户最多提交20个作业，因此把1128个计算单元分到16个SLURM数组作业，每作业16核、56 GB、16个进程。汇总、S07/S09绘图采用afterok依赖，避免使用不完整结果。监控间隔900秒。

## 检查产物

- `validation.json`：跨源数值核对、PNG尺寸、600 dpi和SHA-256。
- `visual_review.json`：逐张查看远程PNG复制件后记录，与远程文件SHA-256匹配。
- `run_manifest.json`：作业ID与本轮复用范围。
- `static_checks.json`：Python语法、可执行脚本的同名SLURM入口。
- 每图 `outputs/*_audit.json`：本图源表SHA-256、数值检查及视觉状态。

全套S04页码清单为 `fig_s04_country_counterfactuals/outputs/page_manifest.json`。各页一起构成完整全国结果，不能只保留第一页。

## 本轮验收状态

S01–S10的33个600 dpi PNG全部完成，并通过数值核验、源表SHA-256核对和逐张视觉检查。完整产物清单见 `logs/paper_figures/supplementary/completion_status.json`，可读报告见同目录 `completion_report.md`。S04全部24页均已检查；S11按用户要求暂不制作。
