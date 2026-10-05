# 论文图件的数据准备

执行位置：乌镇1866仓库。Python 使用项目 `.venv`。正式数据入口见 `document/BCSD_v2数据使用指南.md`，图件设计见 `document/主图与子图设计.md`。

## 职责和运行顺序

1. `config.py` 固定情景、事件、三个十年窗口、单位和路径。
2. `common/` 提供空间归属、缺测安全的比率、配对差、对称分解、模式统计、原子输出和绘图样式。正式读取仍使用 `utils/data_access/`。
3. `prepare_catalogues.py` 核对正式目录哈希与本站CSV，建立站点—容量—国家目录。先单独运行并验收。
4. `prepare_loss_tables.py` 按部署×技术×源分块处理全部选定模式和气候情景。默认4个spawn进程（不超过申请CPU）读取独立年度文件，快照顺序执行；不在进程间共享NetCDF句柄。检查固定部署的容量、坐标及站点集合；若源分块归属不一致则拒绝，防止跨块重复或错误求交。
5. `prepare_event_tables.py` 使用对应Loss共同站点，默认按模式×气候情景使用4个spawn进程，逐块扫描三小时事件，保留月度加权时数、有效时数和覆盖。`--event-runs` 同时统计连续事件，跨文件延续状态；缺测和窗口边界记删失。所有共同站点年度事件覆盖至少99%，不足则停止该分支供人工修订共同支持，不默默扩大分母或补零。
6. `prepare_grid_events.py` 使用已复制的RQ1年缓存，但必须核对缓存指纹、正式源文件大小和修改时间、事件清单和网格。保存原尺度共同域的时期统计，再作1°面积加权展示汇总。
7. `summarize_tables.py` 合并所有声明分块，检查跨块站点唯一性、国家和全球能量及容量守恒、十年覆盖、分解闭合，生成年度/窗口/反事实/三因子/覆盖表。`summarize_grid.py` 合并地图展示网格。
8. `prepare_panel_tables.py` 导出Fig. 1–5以及S1–S6、S7暴露、S8、S10的面板基础表。保留逐模式结果。运行图件绘制前仍须检查源表覆盖、事件行序、案例、阈值与图注。

9. `validate_preparation.py` 独立检查能量比率、容量上限、对称及三因子分解、月度和季节闭合；通过后写入 `acceptance/complete.json`。

各可执行脚本有同名SLURM脚本；从仓库根目录 `sbatch <script>.sh [arguments]`。提交前创建 `logs/paper_figures/prepare/`。大数组处理和科学验证仅在计算节点执行；不在登录节点运行这些分析入口。

## 数据口径

- 三种气候SSP和三种部署SSP独立；配对路径取矩阵对角，反事实使用完整九组合。
- 主损失为带符号净损失能量之和/容量之和，风电原值不缩放。`all` 不由各事件相加。
- 每部署、技术、快照、源块的共同站点，是所有选定模式×气候×十年中所需年度字段有限、正常全年发电量为正的交集。保存original与common两种口径。该标准不证明年内有效时刻完全相同；年度产品未给出可恢复该信息的字段，因此元数据明确记录限制。
- 每个快照单独构造共同支持，窗口内固定容量。主分析窗口比率与年度比率均值一致；original口径在有效容量变化时使用年度比率均值。
- 国家采用Natural Earth，China和Taiwan合并为CHN。未归属与多边界命中分别保存UNASSIGNED/AMBIGUOUS，计入全球守恒，不作为国家比例分母。
- 参考容量是目录内SSP126/2050总容量，与各路径有效容量分开。集中度若二者覆盖不同，只能称参考容量加权指数。
- 事件暴露使用实际有效时刻，不放大到名义全年。正常基线缺失不能由年度输出反推。
- 四模式均值、min–max、方向一致性分别记录。模式方向一致不是显著性检验。

## 产物

`prepare/outputs/catalogues/`：正式版本、容量、国家、事件任务状态。

`loss_shards/<station_ssp>/<tech>/<patch>/`：逐年总量、共同站点和覆盖。

`station_events/<station_ssp>/<tech>/<patch>/`：月度暴露、覆盖和可选事件次数/持时。

`grid_events/<tech>/<patch>/`：原尺度时期NetCDF和面积加权展示表。

`loss_summary/`：`annual.csv.gz`、`window.csv.gz`、`contrasts.csv.gz`、`three_factor.csv.gz`、`capacity_coverage.csv.gz`。

`event_summary/`：年度、时期、季节和频次持时表。`grid_summary/`：展示地图及逐模式差值。

面板数据位于各图 `outputs/source_data/`；试验使用独立output-root和figure-root，不能发布为全球结果。生成器将非默认output-root的面板写到其内部 `figures/`。

所有阶段最后写 `complete.json`，失败时不发布完成标志。当前重用只针对相同固定配置的同一campaign；变更模型、时期或统计规则应使用新output-root。PNG尚不属于本次准备任务的产物。

## 作业编排

```bash
source .venv/bin/activate
python -m scnet.paper_figures.create_prepare_jobs --dry-run
python -m scnet.paper_figures.create_prepare_jobs --event-runs --job-dir /work/home/aczlvkl1ac/project_climate_patchify/runtime/paper_figures_jobs/<campaign>
python -m scnet.paper_figures.control_prepare_jobs /work/home/aczlvkl1ac/project_climate_patchify/runtime/paper_figures_jobs/<campaign>/jobs.json --submit --watch
```

生成器不提交。控制器是轻量调度工具，可在登录节点运行；使用账号已有共享提交锁，计入所有项目作业并保持不超过20个活动作业。仅在前置作业COMPLETED/0:0且完成产物存在后释放依赖。遇到失败停止新提交，保留其他运行中作业，不自动无限重试。状态保存在外部campaign的state.json，阅读记录在 `logs/paper_figures/completion_status/progress.md`。

S7季节损失与S9共同基线必须先另行复现年度损失再运行重建；现有月度暴露不能替代它们。S11需要科学可比的粗尺度实验，当前正式五类产品不包含这个对照。它们不在本准备DAG的完成声明中。
