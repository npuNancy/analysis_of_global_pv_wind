# LCOE 场站 CF / Extreme 运行目标

## 目标与阶段

从已发布全球网格抽取LCOE场站CF与极端事件信号，保留源时间、日历、数值、缺测及事件定义。完成条件为完整交叉情景矩阵、各任务Slurm成功及完成回执、抽样源值比对、正式索引、覆盖报告、共享权限验证与指南更新。

1. 核对原产品代码、正式索引与LCOE映射；冻结工作负载合同。
2. 创建1775共享目录与ACL，十账号可写、1866及其他账号可读；部署干净代码与环境。
3. CF/Extreme真实试运行，验证源值、坐标、时间、容量语义并测量资源。
4. 十账号执行批处理，整刻15分钟检查—思考—汇总—执行；补足可用20作业槽位，按剩余工作动态分配。
5. 汇总验收并交付数据、清单、访问示例和数据指南。

## 工作负载合同

| 项目 | 合同 |
|---|---|
| 入口 | `python -m utils.lcoe_station_climate.pipeline --root ROOT --stage prepare/run/finalize`，run指定 `--unit` |
| DAG | 输入与权限 → prepare → CF/Extreme试运行 → 独立任务矩阵 → finalize |
| 独立单位 | 产品 × 模式 × 气候SSP × 技术 × 源patch；同任务汇集三个场站SSP，源块读取一次后分别输出 |
| 共享输入 | 九组累计0.1°布局、既有LCOE损失评价映射、CF/Extreme正式索引；源数据只读 |
| 当前范围 | 四GCM，气候126/245/585 × 场站126/245/560，wind/solar，2015–2060；CLI/config暴露全部维度 |
| 位置 | 沿用LCOE损失映射的同格最近BCSD点；不应用损失评价的共同有效筛选，不跨格填补；未映射目录独立保留 |
| 输出 | 每场站SSP/模式/气候/patch/技术独立NetCDF，CF 8块、Extreme 10块；容量快照与首次选中年为元数据，投运前不清空CF/信号 |
| 完成 | sacct COMPLETED/0:0，加任务完成标记、输入/代码指纹和逐文件输出记录；源点抽样比对、时间坐标完整保留 |
| 重启 | 已完成分片经身份与大小校验后复用；原子临时文件、排他任务锁；冲突文件不覆盖，失败需审查后有界重试 |
| 资源 | 初始2核约7GB、单进程、原生库1线程；读取按时空chunk流式进行，依据试运行MaxRSS/用时调整 |
| 数据 | 准备后的catalogs、mappings、jobs、logs、runtime及outputs均在仓库外，原始NC不复制 |

## 部署与访问

本地开发、测试、commit/push，1775通过HTTPS新建共享只读代码checkout；不改写既有1866分析checkout。共享结果根为 `/work/home/acsep06cn2/lcoe_station_climate_v1`，计算账号见campaign配置。文件所有权保留实际写入账号，默认ACL给十账号写权限、1866读权限，POSIX other为目录r-x/文件r--，供后续账号读取。家目录只要求祖先可遍历；不递归改变既有数据权限。

用户项目uv约定优先于技能conda模板：科学脚本激活已核对可访问的 `/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate`。所有科学读取在SLURM节点；登录节点仅处理清单、作业、权限、Git和调度状态。无需新增依赖。

## 调度与监控

作业生成器 `scnet/create_lcoe_station_climate_jobs.py` 只生成脚本，支持dry-run；生成文件在共享根jobs/，严格shell、wzhctest、单节点、同一stdout/stderr绝对日志。脚本分别设置核心和工作进程，更多核心只用于内存。每个可执行Python配同名sh。

每Asia/Shanghai整刻hh:00/15/30/45采集squeue、sacct、退出码、耗时、MaxRSS、失败日志尾和完成标记，分类后更新本地 `scnet/lcoe_station_climate/completion_status/progress.md`。每轮记录剩余耗时估计；试运行前估计不确定，之后以任务速度和剩余负载更新。

每次提交持账号现有 `/work/home/<user>/.bcsd_submit.lock`，重查该账号全部活动作业（不按项目筛选），最多补至20，包含新确认但尚未出现在squeue的ID。统一未提交队列动态分配给任何有空位账号。上游未通过不释放下游；无就绪任务时不制造占位作业。瞬时失败最多重试2次；OOM、超时按证据调整，确定性失败先修复再提交。最终验收另设计算任务。

Git使用HTTPS默认远程，认证不足才请求已有授权之外的新方式，不复制密钥。原源数据、其他项目与既有结果均保留。运行状态不纳入Git，输入摘要、脚本、测试与此合同纳入Git。
