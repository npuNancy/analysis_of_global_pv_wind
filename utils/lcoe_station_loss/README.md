# LCOE年度损失交叉情景

补齐场站SSP126/245/560与气候SSP126/245/585的六组非配对结果，合并已有三组配对结果。事件并集all的带符号净损失、全年正常基准和实际发电量按2030/2040/2050累计装机分别评价2030–2039/2040–2049/2050–2059。风电不乘0.1；单位装机损失为净损失除以容量。

`science.py`保留原`lcoe-station-metrics`分支的年度损失读取及容量加权算法。Loss取正式1 MW适宜网格产品；CF积分使用已经验收的LCOE场站原生三小时序列，严格检查全年时间数、日历、缺测与坐标。两组配对控制任务与旧逐分块结果比对，验证新CF读取路径数值等价。

结果实体在`/work/home/acxujo26gv/lcoe_station_climate_storage/loss/`。原1866 outputs目录已mv到`paired/`，旧位置保留兼容软链接；原24个档案及其清单不改写。新48个档案按`station_results/<station_ssp>/<climate_ssp>/<model>/<tech>.npz`保存。正式统一入口为`runtime/authoritative_index.json`和`runtime/completion.json`，必须均COMPLETED后使用；按索引path读取，不推测配对与非配对的目录结构。

共同有效集合按每个场站SSP、气候SSP、技术分别计算，要求四模式、30年共同有效，与原配对产品一致；不同气候SSP的集合可能不同。完整目录容量保留，未投运及不在共同有效集合的电量为NaN。跨气候定点比较须另取共同有效交集。

`prepare → run → finalize`分别准备1224个非配对单元及两个数值控制、运行独立模式/双SSP/技术/patch单元、汇总验收九组合。以实际准备清单为准。每次提交持账号共享锁，计入所有项目的活动作业，最多20个；十账号共享未提交队列。科学计算4核约14GB、单进程；最终汇总8核约28GB。监控命令：

```bash
python -m scnet.lcoe_station_loss.watch --watch --submit --align-first
```

代码先本地测试、commit/push，再在共享根`code/`干净快进部署。uv环境和账号清单见`scnet/lcoe_station_loss/campaign.json`，生成器只生成作业。源CF、原始损失及已发布配对结果只读。
