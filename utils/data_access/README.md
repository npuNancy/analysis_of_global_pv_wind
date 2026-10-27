# BCSD-v2 数据索引与读取

完整说明见 [数据使用指南](../../document/BCSD_v2数据使用指南.md)，包括存储入口、目录层级、变量单位、双 SSP、快照与年份含义，以及 Python 使用示例。

每类数据有独立的查询/读取脚本：

| 数据 | 脚本 |
|---|---|
| CF 全球网格 | `read_cf_grid.py` |
| CF 场站 | `read_cf_stations.py` |
| Extreme 全球网格 | `read_extreme_grid.py` |
| Extreme 场站 | `read_extreme_stations.py` |
| Loss 场站 | `read_loss_stations.py` |

在仓库根目录运行，默认只读索引元数据；需能访问乌镇共享文件系统。`--root` 是运行根目录，不是 `outputs/`。例如：

```bash
source .venv/bin/activate
python utils/data_access/read_loss_stations.py --help
python utils/data_access/read_loss_stations.py \
  --model BCC-CSM2-MR --climate-ssp ssp126 --station-ssp ssp126 \
  --patch R02C08 --tech wind --snapshot-year 2030 --years 2030 2030 \
  --limit 1 --check --inspect
```

Python 接口为每个模块的 `find_records(...)` 与 `open_record(...)`。后者按需选择变量、年份、站点和空间范围，返回需要关闭的惰性 xarray Dataset。

全球网格 CF 查询使用 `runtime/authoritative_index.json`，不再扫描任务目录。需要重新生成时：

```bash
python utils/data_access/build_cf_grid_index.py --root /work/home/acjpoxgsdu/cf_grid/cf_grid_v2
```

生成器按最终任务清单验证完整覆盖、完成状态和分片文件，再原子发布索引；失败时保留已有索引。查询不会自动重建，数据或任务清单变化后应显式运行生成器。索引保留原任务 manifest 路径及 SHA256，便于追溯。

同名 `.sh` 可用 `bash utils/data_access/<name>.sh [参数]` 提交 SLURM；提交前自动创建日志目录。大型数组计算应放在计算节点。

测试仅使用临时目录与小型 NetCDF，不修改真实数据：

```bash
.venv/bin/python -m unittest discover -s utils/data_access -p 'test_*.py' -v
```

## 适建网格的 1 MW 参考容量 CSV

`build_suitable_grid_stations.py` 使用光伏适宜性和**单独的陆风分量**，筛选有限且
大于零的像元。固定写入 `year=2015`、`capacity_gw=0.001`；同一位置的风光分别
保留。同技术跨 patch 重复坐标只写一行。容量仅用于归一化，不代表实际装机或容量上限。

```bash
bash utils/data_access/build_suitable_grid_stations.sh \
  --solar-suitability /absolute/path/Global_Solar_Net_Area_Add_Egrid.tif \
  --wind-suitability /absolute/path/Global_Wind_Net_Area_onshore_component.tif
```

默认读取1872正式 CF 索引，输出到1866项目的 `data/stations/suitable_grid_1mw/`。
不覆盖已有输出目录。默认输入位置为项目 `data/suitability/` 下的上述两个文件。
实际输入产物必须先准备好；该脚本不生成适宜性栅格，也不读取优化结果。

坐标来自正式索引内每个技术/patch的2015所在 CF 分片，并核对所有模型、情景的
该分片坐标完全一致。对每个实际 BCSD 格点，将经度规范到 `[-180,180)`，通过
栅格仿射变换查找包含该点的像元；北/西边界包含、南/东边界不包含，像元边界的
浮点误差先吸附到整数索引。此规则与 S06 的格点落入像元规则一致，不把栅格中心
当成 CF 坐标，不做插值。仅筛选适宜性，不读取 CF 时间序列或过滤 CF 缺测；
数据有效域及逐时缺测需在后续损失阶段另行处理。

产物：

- `stations_suitable_1mw.csv`：`year,type,lon,lat,capacity_gw`。
- `grid_mapping.csv.gz`：每个入选点的技术、patch、CF 行列、栅格行列和适宜性百分比；保留 patch 重叠映射。
- `summary.json`：输入哈希、坐标来源、风光数量、每个 patch 数量及未匹配到发布 CF 格点的正值像元数。

光伏现有 S05 权重含历史标定；输出沿用所提供栅格的适宜性定义。陆风输入必须
明确命名或标注 `onshore`，不得用合并海陆风的主栅格代替。

2026-10-27 输入取自 `THU_LM1:/data4/yanxiaokai/project_energy_climate/globally_interconnected_10km/GlobalPotential_10km/outputs/`：
光伏为根目录下主栅格，陆风为 `diagnostics/` 下的 onshore 分量。通过 rsync
复制到1866项目 `data/suitability/`，来源路径与 SHA256 记录在该目录的
`source_manifest.json`。陆风分量未执行主栅格的百分比截断，最大约100.449%；
本流程保留原始值，仅判断有限正值，并在 summary 中记录超过100%的像元数。
