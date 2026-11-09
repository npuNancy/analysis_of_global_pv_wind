# LCOE场站CF与极端事件序列

从正式全球网格CF和Extreme产品抽取已有LCOE布局的场站序列。三条场站路径与三条气候路径独立交叉，保留场站SSP560名称，气候使用SSP585。此流程不计算新的气象事件，也不进行电力调度。

输入为九组累计0.1°场站CSV、已完成LCOE损失评价的逐格映射、已发布CF和Extreme索引。匹配位置与损失评价一致，但不应用损失评价的四模式/30年共同有效筛选；所有已映射场站保留各自完整原生序列及缺测。未映射站点和容量在catalogs中单列。

阶段为prepare → 独立run单位 → finalize。一个run单位是产品、模式、气候情景、技术、patch的组合，同一源块读取一次后输出三种场站布局，降低重复I/O。每个结果保留源文件时间、日历、变量属性和事件缺测编码，包含快照容量及首次选中年份。投运前的资源CF与事件信号不屏蔽，分析运营期时自行选择容量快照；CF没有乘装机量。

运行位置和账号由 `scnet/lcoe_station_climate/campaign.json` 配置，任务合同见 `scnet/goal.md`。科学计算使用uv环境，提交前创建共享logs目录。生成器不提交作业：

本批结果实体根为 `/work/home/acxujo26gv/lcoe_station_climate_storage`（1959）；配置中冻结的1775路径是兼容软链接。当前作业资源覆盖记录在 `runtime/resource_overrides.json`，常规4核、内存终止重试8核，均为单进程；重新生成对应脚本时须使用相同的 `--cpus` 参数。

```bash
python -m scnet.create_lcoe_station_climate_jobs --stage prepare
python -m scnet.create_lcoe_station_climate_jobs --stage run --dry-run
python -m scnet.create_lcoe_station_climate_jobs --stage run
python -m scnet.create_lcoe_station_climate_jobs --stage finalize
```

控制器在各账号登录节点运行，统计该账号所有活动作业，并以共享未提交队列动态分配。批量提交前必须存在真实试运行验收标记。监控程序在本地调用十账号控制器，每个Asia/Shanghai整刻15分钟执行一次并刷新本地进度表；日志、作业和科学产物均位于共享目录，运行记录不进入Git。

```bash
python -m scnet.lcoe_station_climate.watch --watch --submit --align-first
```

最终索引为 `runtime/authoritative_index.json`，包含完整情景矩阵与合法空组合。以 `status=COMPLETED` 条目的 `artifacts[].path` 定位文件；`runtime/completion.json` 是最终完成标记。不同产品的源时间偏移保留，不按数组位置直接对齐风、光或CF、事件。

代码参考原项目的 `station_cf_mapping.py`、`station_cf_catalog.py` 与 `grid_extreme_signals/station_extract.py`；当前映射使用LCOE既有同栅格匹配，而不是旧场站产品的全局最近格点规则。源数据不可覆盖。运行中间文件私有于任务，写完并完成直接源点比对后原子发布；已有完成分片检查身份与文件大小后复用。冲突输出保留并报错，由控制端查明原因后恢复，不自动删除。
