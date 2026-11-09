# LCOE 场站 CF / Extreme 运行目标

## 当前追加目标：Loss完整交叉矩阵

1. [x] 核对配对科学代码与已发布24个场站档案，固定原事件并集净损失口径。
2. [x] 既有1866 outputs目录mv到1959共享根`loss/paired/`；旧路径为软链接，十账号可写、1866及其他账号可读。
3. [x] 准备1224个非配对任务及两个控制；两组配对控制验证新场站CF积分与旧结果等价，风/光交叉任务试运行成功。
4. [ ] 十账号执行，整刻15分钟监控并估计耗时，按全账号20作业上限补交。
5. [ ] 验收九组、发布统一索引、更新指南及提交推送。

Loss合同：`python -m utils.lcoe_station_loss.pipeline --root ROOT --stage prepare/run/finalize`；独立单元为模式×场站SSP×气候SSP×技术×patch，全部30年在一个单元内。run指定`--unit`。输入为已发布适宜网格年度Loss、已验收场站CF与原配对空间映射；原结果与源文件不可覆盖。每单元原子NPZ和完成回执须同时匹配任务/代码指纹，Slurm COMPLETED/0:0才释放最终汇总。年度损失/正常基准读取及容量加权保持旧算法；四模式共同有效集合逐双SSP/技术计算，保留原生CF日历与缺测。输出72个正式NPZ，其中24个复用迁入结果、48个新增；最终逐文件校验哈希、形状、缺测、容量、汇总一致性及权限。

新配置`scnet/lcoe_station_loss/campaign.json`，新生成器`scnet/create_lcoe_station_loss_jobs.py`。共享根`/work/home/acxujo26gv/lcoe_station_climate_storage/loss`，作业/日志/runtime均在此目录；本地状态为`scnet/lcoe_station_loss/completion_status/progress.md`。十账号、共享提交锁与uv环境沿用下文已核定规则。四个试运行作业48705282/48705284/48705287/48705290全部COMPLETED/0:0，峰值182724 KiB；正式run为1核约3.5GB单进程，finalize为2核约7GB单进程。冻结配置保留初始4核，重建脚本须应用 `runtime/resource_overrides.json` 的 `--cpus` 覆盖。失败最多重试两次，先查原因；生成器不提交，准备与真实试运行验收前不得批量提交。

## 目标与阶段

从已发布全球网格抽取LCOE场站CF与极端事件信号，保留源时间、日历、数值、缺测及事件定义。完成条件为完整交叉情景矩阵、各任务Slurm成功及完成回执、抽样源值比对、正式索引、覆盖报告、共享权限验证与指南更新。

- [x] 阶段1：核对原产品代码、正式索引与LCOE映射；冻结工作负载合同。
- [x] 阶段2：建立共享目录与ACL，十账号可写、1866及其他账号可读；结果实体集中1959，1775保留兼容入口。
- [x] 阶段3：CF/Extreme真实试运行，验证源值、坐标、时间、容量语义并测量资源。
- [x] 阶段4：十账号执行批处理，整刻15分钟检查—思考—汇总—执行；补足可用20作业槽位，按剩余工作动态分配。
- [x] 阶段5：汇总验收并交付数据、清单、访问示例和数据指南。

本批于2026-11-09完成：1,296个抽取任务全部成功，汇总作业48696204、验收作业48696352均为COMPLETED/0:0。正式NetCDF共33,048个（CF 14,688、Extreme 18,360），约534.0 GiB；索引6,768个组合中3,672个非空、3,096个合法空组合。最终证据为共享根下 `runtime/completion.json`、`runtime/final_acceptance.json`；使用说明、未映射覆盖及读取示例见[数据指南第12节](../document/BCSD_v2数据使用指南.md#12-cf--extremelcoe气候ssp--场站ssp)。

## 工作负载合同

| 项目 | 合同 |
|---|---|
| 入口 | `python -m utils.lcoe_station_climate.pipeline --root ROOT --stage prepare/run/finalize`，run指定 `--unit` |
| DAG | 输入与权限 → prepare → CF/Extreme试运行 → 独立任务矩阵 → finalize → verify_delivery |
| 独立单位 | 产品 × 模式 × 气候SSP × 技术 × 源patch；同任务汇集三个场站SSP，源块读取一次后分别输出 |
| 共享输入 | 九组累计0.1°布局、既有LCOE损失评价映射、CF/Extreme正式索引；源数据只读 |
| 当前范围 | 四GCM，气候126/245/585 × 场站126/245/560，wind/solar，2015–2060；CLI/config暴露全部维度 |
| 位置 | 沿用LCOE损失映射的同格最近BCSD点；不应用损失评价的共同有效筛选，不跨格填补；未映射目录独立保留 |
| 输出 | 每场站SSP/模式/气候/patch/技术独立NetCDF，CF 8块、Extreme 10块；容量快照与首次选中年为元数据，投运前不清空CF/信号 |
| 完成 | sacct COMPLETED/0:0，加任务完成标记、输入/代码指纹和逐文件输出记录；源点抽样比对、时间坐标完整保留 |
| 重启 | 已完成分片经身份与大小校验后复用；原子临时文件、排他任务锁；冲突文件不覆盖，失败需审查后有界重试 |
| 资源 | 单进程、原生库1线程；初始2核约7GB，恢复批次常规4核约14GB，36个内存终止任务重试8核约28GB；实际覆盖记录见 `runtime/resource_overrides.json` |
| 数据 | 准备后的catalogs、mappings、jobs、logs、runtime及outputs均在仓库外，原始NC不复制 |

## 部署与访问

本地开发、测试、commit/push，通过HTTPS部署独立共享代码checkout；不改写既有1866分析checkout。用户确认结果实体改存1959，根为 `/work/home/acxujo26gv/lcoe_station_climate_storage`。原入口 `/work/home/acsep06cn2/lcoe_station_climate_v1` 是指向该根的兼容软链接，冻结配置、任务和分片回执中的路径继续有效。代码、日志、索引和NetCDF均位于1959实体目录。计算账号见campaign配置。文件所有权保留实际写入账号，默认ACL给十账号写权限、1866读权限，POSIX other为目录r-x/文件r--，供后续账号读取。家目录只要求祖先可遍历；不递归改变既有数据权限。

用户项目uv约定优先于技能conda模板：科学脚本激活已核对可访问的 `/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate`。所有科学读取在SLURM节点；登录节点仅处理清单、作业、权限、Git和调度状态。无需新增依赖。

## 调度与监控

作业生成器 `scnet/create_lcoe_station_climate_jobs.py` 只生成脚本，支持dry-run；生成文件在共享根jobs/，严格shell、wzhctest、单节点、同一stdout/stderr绝对日志。脚本分别设置核心和工作进程，更多核心只用于内存。每个可执行Python配同名sh。

每Asia/Shanghai整刻hh:00/15/30/45采集squeue、sacct、退出码、耗时、MaxRSS、失败日志尾和完成标记，分类后更新本地 `scnet/lcoe_station_climate/completion_status/progress.md`。每轮记录剩余耗时估计；试运行前估计不确定，之后以任务速度和剩余负载更新。

每次提交持账号现有 `/work/home/<user>/.bcsd_submit.lock`，重查该账号全部活动作业（不按项目筛选），最多补至20，包含新确认但尚未出现在squeue的ID。统一未提交队列动态分配给任何有空位账号。上游未通过不释放下游；无就绪任务时不制造占位作业。瞬时失败最多重试2次；OOM、超时按证据调整，确定性失败先修复再提交。最终验收另设计算任务。

Git使用HTTPS默认远程，认证不足才请求已有授权之外的新方式，不复制密钥。原源数据、其他项目与既有结果均保留。运行状态不纳入Git，输入摘要、脚本、测试与此合同纳入Git。
