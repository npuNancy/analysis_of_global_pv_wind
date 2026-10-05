# 全球网格极端天气分析

`global_grid_extremes.py` 比较三种 SSP 下全球陆地的任一事件暴露轨迹、事件类型变化和未来空间变化。使用仓库 Python `.venv`、matplotlib 和本地国界文件，仅导出 PNG（300 dpi）。默认四模式、三 SSP、47 patch、风/光、2015–2060 年；不预设暴露增减结论。

## 输入与统计

- 默认入口：`/work/share/acjpoxgsdu/extreme_grid/grid_v2/runtime/authoritative_index.json`，按 `artifacts[*].unified_output` 读取。单个组合按时间块读取，工作进程数默认取已分配 CPU 数和 16 的较小值。
- 任一事件先逐时间步求并集；各事件及并集共用有效时间掩膜。仅 0/1 是有效事件信号；缺测不作为零。年度有效时间达到 99% 的格点参与统计，阈值由 `--min-time-coverage` 控制。
- 暴露天数为已观测事件小时除以 24，不补齐缺失时段；模型日历和时间步长从 NetCDF 读取，年度分母按原生日历计算。输出有效时间与有效面积覆盖率，体现部分风电时间轴缺少 2015 年起始 3 小时的情况。
- 使用球面格点面积；patch 核心范围采用西/南闭、东/北开区间，北极端点保留，避免边界格点重复。全球指标先合并各 patch 的加权分子和有效面积，再相除。
- 逐模式汇总后计算等权模式平均。只有全部选定模式都具有有效值时才输出均值及最大/最小值；阴影表示模式范围，不是置信区间。默认均值为四模式，子集验证会明确显示选定模式数。
- 默认比较 2050–2059 与 2015–2024 的年均天数；空间图要求一个格点在两期所有年份、所有选定模式均有效。事件类型允许重叠，事件分图不以类型之和代表并集。

## 运行

在仓库根目录先建立日志目录，再提交作业：

```bash
mkdir -p logs/RQ1_extreme/global/grid
sbatch RQ1_extreme/global/grid/global_grid_extremes.sh
```

作业使用 `wzhctest`、1 节点、16 CPU、56 GB 内存、72 小时时限；脚本激活仓库 `.venv`，以默认参数运行。全量读取及绘图均在计算节点执行。可在计算节点使用 `--phase aggregate` 只生成缓存和表格，或用相同选择参数加 `--phase plot` 从缓存重绘。`--models`、`--ssps`、`--techs`、`--patches`、`--years` 支持子集；基线/未来年份必须同时包含在所选年份中。

输出默认位于当前目录 `outputs/`：

```text
outputs/
├── cache_manifest.json
├── run_config.json
├── <model>/
│   ├── cache/<ssp>/<tech>/<patch>.nc
│   ├── csv/annual_exposure.csv
│   ├── csv/period_changes.csv
│   ├── csv/decadal_exposure.csv       # 所选年份涵盖完整年代时生成
│   ├── csv/patch_coverage.csv
│   ├── csv/map_coverage.csv
│   └── figures/
│       ├── annual_exposure.png
│       ├── event_trajectories.png
│       ├── event_changes.png
│       └── exposure_change_map.png
└── ensemble_mean/                    # 对应的汇总表和图
```

年度格点缓存包含 `event_days`、`valid_hours`、`nominal_hours`、`source_hours`、`domain_mask`、`cell_area_km2` 和坐标，可直接供国家分析使用。缓存身份包含输入路径、大小、mtime、选择范围及归约代码摘要；一致时复用，变化时重算，写入完成后原子替换。`--output-dir` 可指定缓存和结果位置。输入目录及软链接只读。

## 验证

```bash
mkdir -p logs/RQ1_extreme/global/grid
sbatch RQ1_extreme/global/grid/test_grid_extremes.sh
```

`test_grid_extremes.py` 检查事件并集、缺测、日历、面积加权、patch 边界、国家归属、多模式缺项及 NetCDF 缓存回读。真实数据子集验证保存到 `outputs/validation/`，与全量默认结果分开；它只用于验证流程，不代表全球全量分析。

## 多作业并行

`scnet/extreme_grid/create_extreme_grid_jobs.py` 生成独立的 SLURM 脚本和 `jobs.json`，不会自动提交。默认按模式 × SSP 拆成 12 个缓存作业，每作业处理 47 patch × 风/光 = 94 个组合；每作业 16 进程、16 CPU、56 GB，总计最多 192 个缓存计算进程。生成目录必须位于仓库外且尚不存在。

```bash
python scnet/extreme_grid/create_extreme_grid_jobs.py --dry-run
python scnet/extreme_grid/create_extreme_grid_jobs.py --job-dir /work/home/aczlvkl1ac/project_climate_patchify/runtime/extreme_grid_jobs
```

依赖链：12 个缓存作业 → 统一缓存清单 → 全球绘图、国家分析（并行）。缓存作业使用 `--phase cache --manifest-path <独立路径>`，不写全局清单和公共表图；`--phase manifest --cache-manifests ...` 核对并合并全部缓存清单；全球绘图使用 `--phase plot`。默认单作业 `--phase all` 仍可使用。

提交前创建日志目录；每次提交前在共享锁内统计账号全部活动作业，遵守 wzhctest 最多 20 个提交中作业的限制。完整运行与监控约定见 `scnet/extreme_grid/goal.md`。
