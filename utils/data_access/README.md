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
