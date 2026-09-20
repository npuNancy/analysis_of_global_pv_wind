# 全球单位装机损失

`global_unit_capacity_loss.py` 从 `data/loss_outputs` 下的年度场站 NetCDF 读取结果，
依次生成 CANESM5、MPI-ESM1-2-HR、MRI-ESM2-0、BCC-CSM2-MR 和
`ensemble_mean` 五套输出。无需先运行 RQ4，也无需重新计算上游过程。
所有风电和光伏输入都按上游修复后的原始数值读取，不包含倍率补偿逻辑。

## 运行

在仓库根目录提交 SLURM 作业：

```bash
mkdir -p logs/RQ1/global
sbatch RQ1/global/global_unit_capacity_loss.sh
```

作业使用 `wzhctest` 队列、1 个节点、8 核和 28 GB 内存，以 Python 默认参数运行。
默认启用多进程，按 `model × SSP × technology` 拆成 24 个独立读取任务，worker 数量默认取
`SLURM_CPUS_PER_TASK`。8 核用于按 3.5 GB/核申请内存；SLURM 脚本将数值库线程限制为 1，
避免每个 worker 再创建额外线程。
标准输出和错误输出共用 `logs/RQ1/global/global_unit_capacity_loss_<jobid>.out`。
日志目录必须在提交前存在；环境激活文件为 `.venv/bin/activate`。
作业脚本不包含账号专属绝对路径：`#SBATCH` 日志路径相对仓库根目录（提交目录），
脚本体内的仓库位置由 `$HOME/project_climate_patchify/repos/analysis_of_global_pv_wind`
推导，因此同一脚本可在不同超算账号下直接提交。

Python 脚本可通过 `--loss-root`、`--patch-manifest`、`--output-dir` 指定路径。
`--execution-mode parallel`（默认）启用多进程，`--execution-mode single` 保留原有单进程流程；
`--workers N` 可限制多进程 worker 数量。单进程复现示例：

```bash
.venv/bin/python RQ1/global/global_unit_capacity_loss.py --execution-mode single
```

脚本运行日志统一为 `[时间戳] [日志等级]: [消息]`。
默认 patch 清单来自损失结果所属共享运行目录的 `inputs/patch_manifest.json`。
读取路径为：

```text
data/loss_outputs/
├── generation_loss/<model>/<ssp>/<patch>/<snapshot>/<tech>/<tech>_generation_loss_station_<year>.nc
└── task_status/<model>/<ssp>/<patch>/<tech>/{manifest.json,manifest.json.SKIPPED_NO_STATIONS.json}
```

脚本要求 47 个 patch 的任务记录齐全。上游无场站任务使用
`manifest.json.SKIPPED_NO_STATIONS.json` 标记，脚本会将其规范化为三个无场站快照；只有明确标记为
`SKIPPED_NO_STATIONS` 的快照允许没有结果文件；缺失年份、重复场站、
非有限输入或不匹配的元数据会报错。`ssp560` 规范化为 `ssp585`，同时存在两种目录时
会报错，避免重复计入。分析窗口为 center-k=5，对应 2030–2039、2040–2049、2050–2059。

## 指标和图形

只统计 `normal_all_generation_mwh_all > 0` 的场站：该值为零的场站对应 BCSD 气象输入
缺失（CF 被转换为零），损失与事件时长亦为零，但会计入容量分母并稀释 R 与 E
（依据 `tmp/场站无数据问题/数据覆盖问题独立抽查.md`）。过滤按年度文件逐个执行，
被剔除的场站数和容量占比以 WARNING 记录进日志；`run_config.json` 的
`station_filter` 字段记录该口径。注意 `normal_all_generation_mwh_all` 只用于覆盖判据；
三因子分解中的事件窗口反事实发电量 $G_0^{\mathrm{ev}}$ 使用 `normal_generation_mwh_all`。

图形采用 Python/matplotlib 的 quantitative grid，左风右光。
六类图共同用于比较不同 SSP 下全球单位装机损失的时间变化、事件组成、情景差值来源和年代变化来源；
具体变化方向由实际数据决定。年度图为主要证据，事件组成和瀑布图提供组成与分解信息。
所有图使用白底、无上右边框、无边框图例和参考脚本配色，只导出 600 dpi PNG。

- 年度图：全球 `net_generation_loss_mwh_all` 总和除以该快照场站装机总量，
  单位 MWh MW⁻¹ yr⁻¹。装机不按事件重复累加；同一快照十年间要求场站及装机一致。
  虚线是 2030–2059 年全部年度值的最小二乘直线，不代表显著性检验。
- 事件组成：先汇总 2050–2059 年这个十年窗口的全球各事件净损失，并将其年化后除以全球装机，
  再将负值截为零、组内归一化。每个技术面板内为三个 SSP 的“全部事件”和
  “去除低资源事件”两组百分比堆叠柱，风光分别显示适用事件图例。
  事件可以重叠，因此这里是正事件损失池的组成，不能将事件之和解释为 all-event 净损失。
- 瀑布图：目标 SSP 减去 SSP126 的单位装机损失，单位 MWh MW⁻¹ yr⁻¹。
  定义年均净损失 $L$、装机 $C$、年均装机加权事件时长 $H$，令 $E=H/C$、$I=L/H$，故 $R=L/C=E\times I$。
  暴露贡献为 $\Delta E\times(I_{\mathrm{target}}+I_{\mathrm{base}})/2$，强度贡献为 $\Delta I\times(E_{\mathrm{target}}+E_{\mathrm{base}})/2$，
  两者严格相加等于 $\Delta R$。先逐快照分解，再对三个快照等权平均。
- 三因子瀑布图：把强度项 $I$ 拆为事件期资源 $\mathrm{cf}_{\mathrm{ev}}$ 与事件期损失率 $r_{\mathrm{ev}}$，
  即 $I=\mathrm{cf}_{\mathrm{ev}}\times r_{\mathrm{ev}}$，故 $R=E\times\mathrm{cf}_{\mathrm{ev}}\times r_{\mathrm{ev}}$。
  其中 $G_0^{\mathrm{ev}}$ 为场站 `normal_generation_mwh_all` 的全球年均总和（事件窗口内反事实应发电量），
  $\mathrm{cf}_{\mathrm{ev}}=G_0^{\mathrm{ev}}/H$ 是事件窗口内容量因子，
  $r_{\mathrm{ev}}=L/G_0^{\mathrm{ev}}$ 是事件窗口内损失率。三个贡献采用对称 Shapley 归因（六种因子排序取平均），
  严格相加等于 $\Delta R$；同样先逐快照分解、再对三个快照等权平均。
- 年代变化瀑布图：同一 SSP 内 2050s 减 2030s 的单位装机损失差，分解口径与上述瀑布图相同。
  每张图为 3 行（SSP1-2.6 / SSP2-4.5 / SSP5-8.5）× 2 列（风 / 光）共六个子图，
  每个子图展示 Exposure、Intensity（三因子版为 Exposure、Event resource、Event loss rate）
  贡献与总的 $\Delta R$（黑色柱）。注意 2030s 与 2050s 的场站覆盖不同，
  两个快照分别使用各自的过滤后装机作分母。

四模式平均均先逐模式计算指标，再等权平均。年度阴影为同年四个模式的最小值到最大值
（alpha=0.16），不是置信区间。事件图平均各模式的占比；瀑布图平均各模式分解后的贡献。
平均指标表中的 E、I、R、cf_ev、r_ev 各自独立取平均，不能用平均 E×平均 I 代替平均 R。
每个均值记录均检查有且只有四个模式。

## 输出

```text
outputs/
├── CANESM5/
├── MPI-ESM1-2-HR/
├── MRI-ESM2-0/
├── BCC-CSM2-MR/
└── ensemble_mean/
    ├── csv/
    ├── figures/
    └── run_config.json
```

每套 `figures/` 包含年度折线、事件组成、情景差二因子与三因子瀑布、年代变化二因子与三因子瀑布
六张 PNG；`csv/` 包含年度数值、快照指标、事件占比、情景差与年代变化的二因子与三因子分解贡献
和趋势系数。单模式目录另外保存 `input_files.csv`（输入文件路径、大小、修改时间）和
`patch_coverage.csv`（patch 完成状态）。
`run_config.json` 记录指标口径、四模式列表、patch 清单、脚本及清单哈希、软件版本和绘图参数。

本次仅编写代码，没有运行完整分析或绘图；实际图面的文字碰撞、裁切和清晰度需在首次绘图后检查。
