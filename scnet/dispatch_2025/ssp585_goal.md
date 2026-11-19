# dispatch-2025 SSP585补全目标

## 最终目标
完成4 GCM × 3气候SSP × 3场站SSP × 2技术、2030—2059的CF、Extreme、逐事件及事件并集Loss、全年发电量。交付72个年度档案、3240行逐模式汇总、810行集合汇总，以及三条配对路径的8张三面板图、24张独立PNG、23份源表和更新后的独立报告。

## 分阶段目标
- [x] 输入确认：SSP585 manifest accepted=true，三份0.1° CSV与manifest哈希一致；完整上游验收通过，验收清单代码a4d5a253c78b50f875d896abb4d5d26ea5a55e1b。
- [x] 冻结九份0.1°场站CSV及九份1°校验表、上游manifest/验收报告、代码与配置；核对旧四组合目录及容量一致性。
- [x] 真实CF/Extreme首批与Loss切片验证：12个提取任务、120分片、10组真实Loss切片。
- [x] 完成五个新增气候—场站组合的全量CF/Extreme提取。
- [x] Loss与年度发布；统一索引完整覆盖九组合，复用四组合与原发布值一致。
- [x] 1866绘制三配对路径，检查源表、45条OLS拟合、32张600 dpi PNG和视觉效果。
- [x] 更新document/全球场站-dispatch-2025气候评价.md，共享读取、相对链接及任务范围核对后完成；保护文档保留并行任务的改动，并记录哈希变化来源。

## 工作负载合同
基准发布为/work/home/acxujo26gv/dispatch_2025_climate_storage；索引SHA256为5552bcf1cf4d8427ff6f42aac0b71356309f7b347d40cef1f940e81e163f0e42。新增根为/work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585，最终统一索引为该根runtime/authoritative_index.json，显式引用旧四组合与新五组合。旧code、输入及正式数据保持原路径和身份。
新增配置为scnet/dispatch_2025/campaign_ssp585.json。station_ssps_by_climate选择126→585、245→585、585→126/245/585；完整目标维度为126/245/585两轴。准备阶段构造三场站情景共同空间映射，提取仅输出所选组合。

DAG：输入/ACL/冻结代码 → prepare → 原生CF/Extreme试运行 → 全量提取 → Loss试运行/全量 → publish分组 → finalize完整矩阵 → 绘图 → 报告/访问验收。
提取单元：产品×GCM×气候×技术×patch，30年原生分片逐个读取，选定场站情景共享读取。Loss单元：GCM×气候×场站×技术×patch，保留全部30年与三个十年正常CF窗口。发布单元：气候×场站×技术，四模式共同有效支持。
入口：
- python -m scnet.dispatch_2025.prepare --root /work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585 --config scnet/dispatch_2025/campaign_ssp585.json
- python -m scnet.create_dispatch_2025_jobs --root /work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585/future --module utils.lcoe_station_climate.pipeline
- python -m scnet.dispatch_2025.watch --config scnet/dispatch_2025/campaign_ssp585.json --phase future --pilot --submit --watch --hourly
- python -m utils.dispatch_station_climate.loss --root /work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585 --stage prepare
- python -m utils.dispatch_station_climate.publish --root /work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585 --stage prepare/finalize
- run阶段由生成作业传入--root与--unit；Loss运行root为loss_future，publish运行为publish子目录。

完成证据：任务/代码/来源指纹、源点抽样一致、原生时间/日历、完成回执、Slurm COMPLETED/0:0与文件大小；年度矩阵、容量、缺测支持、能量闭合及正式索引哈希。未提交、活动、失败、产物不完整分别记录；任务锁与原子文件保护恢复，匹配完成回执才能复用，冲突不覆盖。瞬时失败最多重试2次，确定性失败先修复。

## 科学与资源约定
SSP585为新验收的SSP5-8.5部署。选址采用MPI-ESM1-2-HR，评价采用4 GCM。2030/2040/2050为总容量快照，用于对应十年。风电MW、光伏MWp/DC；风电能量scale=1。CF积分全年发电，Loss为有符号净损失，默认展示单位装机损失；事件定义与2015—2024低资源阈值沿用正式网格数据。统计按双情景×技术保留四模型、30年共同有效支持。

开发及绘图位于1866仓库；执行代码冻结到新增根code/.venv（沿用已核对环境）。1892执行气候126，1520执行245，1870执行585；1959持有存储根。仅给新增根加入1870写ACL，1866及其他账号可读。每账号所有项目活动作业上限20，持~/.bcsd_submit.lock并重查后提交。
wzhctest、1节点、1进程、原生库1线程；首批4核约14GB，依据MaxRSS调整正式提取与Loss资源；原批参考为提取2核、Loss1核、station_chunk=256。原始NC计算在Slurm，已汇总小表绘图在1866登录节点。
数据预计为基准约547 GiB的增量，实际空间和任务数以prepare清单及完成索引记录。源数据只读，不复制网格NC；CSV、映射、原生NC、日志与状态不入Git。只同步代码、计划、报告和正式PNG/源表。无需新增依赖。

## 进度记录
本地scnet/dispatch_2025/completion_status/ssp585/progress.md逐轮记录调度状态、作业ID、退出码、MaxRSS与下一动作。以实际完成证据勾选阶段，不以提交完成代替计算完成。

## 绘图约定
待检验问题为三种气候—部署配对路径下全球容量、暴露、损失和发电的时间变化，不预设路径排序。每图三列依次风光合计、风、光；容量和暴露为三年代点，其余逐年2030—2059。四GCM等权均值、min–max范围；单位装机指标先汇总分子分母再求比。延续现有单位及坐标共享约定，SSP585为深红/三角。输出位置不变；只有完整新索引通过验收后才覆盖原32张图和23份源表。

准备作业49201741因旧总容量校验比较了不同分辨率而FAILED/1:0；上游native_capacity_validation.capacity_gw为1°总量。已补入哈希核对的1°校验表，按记录的parent_child_max_error_tw逐父格验证0.1°聚合，分析容量保持CSV原值。最大总量差0.03278765 MW，证据位于新增根runtime/preparation_attempt_1/。

准备重跑49201990已COMPLETED/0:0（115秒，MaxRSS 1176204 KiB），输入目录共1,010,616条快照记录，276,929个技术—网格映射条目。旧两场站情景的ID、映射和三个容量快照全部一致。提取清单2,040任务，三个气候情景各680任务。

首批提取12任务均COMPLETED/0:0，耗时234—522秒，MaxRSS最高638.85 MiB；120分片的源点、日历、时间覆盖及任务指纹通过。真实Loss切片49202678已COMPLETED/0:0（259秒、242044 KiB），10组×4站×30年、全部命名事件/并集及三十年基线通过。验收入口为future/runtime/pilot_accepted.json。正式提取使用jobs_production/中的2核脚本；watch持续按三个账号20作业上限补交。

新增工作量为2,040个提取任务、20,400个原生分片、1,700个Loss任务和10个发布组；最终合并目标为36,720个CF/Extreme分片、3,060个Loss文件及72个年度档案，详见runtime/expected_matrix.json。

SSP585来源追溯：站点优化来自49177195，正式验收来自49197708；manifest确认site_capacities_unchanged=true。case.code_commit记录正式验收版本。三个弃电率上限分别为0.5、0.522、0.5，保留于原manifest。

全量提取已于2026-11-16验收：2,040任务全部Slurm COMPLETED/0:0，20,400分片共584,885,757,415字节；两种原生日历、2030—2059连续覆盖、源点抽样、任务/代码身份及文件大小全部通过。正式验收记录为future/runtime/extraction_accepted.json。单任务运行时间中位数82秒、最长563秒。

Loss首批六个完整分块已全部Slurm COMPLETED/0:0：光伏每分块10,796站、风电4,747站，耗时619—2,185秒，MaxRSS最高1.640827 GiB。独立验收49212245于16秒内COMPLETED/0:0，全部输出哈希、目录ID、容量与时间通过；首/中/末站点的30年NetCDF/NPZ指标、基线及逐事件闭合抽样一致。验收入口为loss_future/runtime/pilot_accepted.json。参考本轮首批及上一完整发布1.810905 GiB峰值，按1.5倍余量和3.5 GB/核配置正式Loss为1核；1,700份jobs_production脚本均通过bash语法检查，正在全量调度。

用户于2026-11-16要求仅逐整点小时监控。调度使用 --watch --hourly，从下一个整点开始，每小时整点检查一次并按账号上限补交；已提交作业继续计算。停止原20秒轮询。后续Loss、发布及其他作业的状态检查同样遵循整点节奏。

2026-11-18完整数据验收作业49290002已COMPLETED/0:0：72年度档案、3240逐模式行、810集合行、36720原生CF/Extreme分片、3060逐事件Loss文件；32张600 dpi PNG、23份源表及45条OLS拟合通过数值与视觉检查。共享只读访问由1866与1775实测通过。

报告共享副本77文件和52相对链接由1866、1775只读实测通过；本地报告、32PNG、23CSV与发布哈希一致。
