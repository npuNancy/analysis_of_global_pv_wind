# 全球 country / patch / station 映射

这个目录是基于当前工程输入数据生成的静态映射快照，用于把后续 patchify 结果重新聚合到国家（region）。

## 生成内容

- `stations_ssp126.csv`、`stations_ssp245.csv`、`stations_ssp585.csv`：逐行保留原始场站记录，并新增 `station_key`、`country`、`country_iso3`、`patch_id` 等字段。
- `country_capacity_summary_<ssp>.csv`：按国家、年份、风/光类型汇总场站数和装机容量（GW）。
- `country_patch_capacity_<ssp>.csv`：按国家、年份、类型、patch 汇总场站数和装机容量。
- `country_patch_mapping.csv`：每个国家与 patch 的关系；`geometry_intersects` 表示 Natural Earth 边界与 patch 核心区相交，`station_observed_<ssp>` 表示该 SSP 的场站数据实际出现过该 patch。
- `mapping.json`：国家别名、patch 定义、SSP 文件、源文件哈希和完整国家元数据。
- `patches.json`：单独的 patch 边界快照。
- `mapping.py`：读取静态文件的 Python 查询接口。
- `build_mapping.py`：在输入数据更新后重新生成上述文件。

## 坐标与 patch 规则

patch 定义唯一以 `bcsd/global_bcsd/patches.py` 为准：30°×30° 核心区，去掉该文件中的 `REMOVED_PATCHES`，不把 3° 边界缓冲区算入归属。

- 场站经度输入按 `[0, 360)` 处理，并用 `((lon + 180) % 360) - 180` 转为 Natural Earth 的 `[-180, 180]`。
- 纬度下边界包含、上边界不包含；经度左闭右开。
- 落在已移除 patch 的记录保留 `raw_patch_id`，而 `patch_id` 为空、`patch_active=False`。

国家归属优先采用 Natural Earth admin-0 多边形的点覆盖判断。由于 110m 低分辨率边界会漏掉部分小岛/海岸点，
多边形外且距最近边界不超过 2.5° 的坐标使用最近边界回退，并在 `country_match_method` 中标记为
`nearest_boundary`，距离写入 `country_match_distance_deg`。超过阈值的坐标才标记为 `UNMAPPED`，不会静默丢弃。

按用户约定，中国是 Natural Earth 的中国和台湾两条几何的合并 canonical country：

- `country == "China"`、`country_iso3 == "CHN"`；
- 台湾坐标仍保留 `natural_earth_name == "Taiwan"`，方便追溯边界来源。

## SSP 命名

`mapping.normalize_scenario` 支持 `ssp126`、`ssp 1-2.6`、`SSP 126`、`SSP1-26` 等写法；`ssp560`、`SSP5-6.0` 按要求与 `ssp585` 共用同一份 `stations_ssp585.csv` 映射。

## 使用示例

```python
from country_patch_mapping.mapping import (
    patch_for_point,
    patches_for_country,
    stations_for_country,
    capacity_summary,
)

patch_for_point(338.0, 65.0)                 # 'R01C06'
patches_for_country("中国")                  # Natural Earth 边界覆盖的 patch
patches_for_country("China", "ssp 1-2.6", source="station")
stations_for_country("中国", "SSP126", year=2050, station_type="solar")
capacity_summary("China", "ssp560")
```

重新生成：

```bash
python country_patch_mapping/build_mapping.py
```

生成时间、输入文件 SHA-256 和校验计数写在 `mapping.json` 中。
