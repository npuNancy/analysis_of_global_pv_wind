# 装机极端天气 SSP 对比

执行账号为1866，正式输入只读；不使用主图设计或预设路径排序。
同一技术、同一十年窗口内比较三个 SSP，包含所有事件及时间并集。
气候 SSP 与装机 SSP 保留独立维度；配对路径和固定布局的气候对比均输出。

## 计算约定

- 已有共同支持及容量：event_summary、loss_shards/station_support；固定布局内四模式及三个气候 SSP 共用站点，记录相对完整容量的覆盖。
- 2030/2040/2050总装机快照固定应用于相应十年，不能累加。
- 暴露：容量加权累计天/年；频次：容量加权已知事件起点/年；完整平均持时/P90：容量加权事件池。
- 全部事件先合并三小时信号，再识别连续过程。跨文件和跨年延续；窗口及缺测截断单独保留。
- 同步指标：每时刻受影响容量/固定共同容量，合并各分块后计算P95、最大值、超过10/20/30%的时长和最长连续片段。
- 全球、国家、纬度带均保留；所有路径先逐模式作差，再汇总四模式范围及同向数。
- 暴露事件项与重叠修正闭合；完整频次与持时对称分解再加删失差闭合；气候与部署对称分解闭合。
- 各SSP并集P95高值时段的事件构成可相加核算；不把单类事件P95、频次或平均持时相加作为并集归因。
- 图表目的：检验SSP排序是否随事件、区域、容量权重改变。结果表优先；如绘图，仅Python/PNG，地图Plate Carrée。

## 作业图与资源

入口为 paper_figures.main.fig01_extreme_events.prepare_ssp_station_dynamics。
独立输出为技术×模式×气候SSP×装机SSP×源分块，共2592个非空组合；各组合依次计算三个窗口。
试运行：BCC-CSM2-MR/气候ssp126/装机ssp126/R02C08，两技术，2050年代，4核14GB，2进程。
全量：20个批次，每批16进程、16核56GB、12小时。重启只复用输入/代码身份一致的完整分片。
汇总8核28GB，4个spawn进程分别处理独立的技术×模式×双SSP×快照组；最终报告4核14GB。Python/C真实站点等价、旧频次缓存复现、时空容量积分及持时直方图守恒全部通过才写完成标记。
正式输入来自索引；不扫描attempts。新代码、输出和日志均在1866仓库。

生成器 scnet.paper_figures.create_ssp_station_jobs 只生成不提交；默认作业位于仓库外 ../../runtime/ssp_station_jobs/20261018。
控制器 scnet.paper_figures.control_ssp_station 使用账号总活跃数20上限及已有共享提交锁 logs/RQ1_extreme/completion_status/submit.lock。
流程：试运行成功 → 全量批次成功 → 汇总成功 → 网格动态汇总完成后更新最终报告。
状态写入 logs/paper_figures/ssp_station/completion_status/progress.md；检查Slurm终态、退出码、峰值内存及完成文件。
已有网格作业保持运行。确定性失败停止新提交并保留其他活跃作业，不自动无限重试。

## 输出与终止条件

输出根目录 paper_figures/main/fig01_extreme_events/outputs/ssp_station。
report.html与CSV表提供24项完整指标、三组SSP差、固定布局对比、气候与部署分解、地区事件解释及装机/网格对照。
dynamics/shards保留逐站统计、区域直方图及同步时间序列；dynamics/summary为全部动态统计和高值时段事件构成。
最终完成要求所有批次、汇总和网格对照成功，最终report.html及complete.json存在；提交作业不能视为结果完成。

## 完成记录

2026-10-18全部计算及审查完成：装机2592分片、网格1128分片均通过汇总校验。
装机汇总46849275、网格汇总46849039、报告46850484及最终绘图46851334均COMPLETED/0:0。
7项科学计算测试通过；12张PNG已逐张目视检查，24个报告文件引用均有效；三个complete.json均通过完整性检查。
最终入口为outputs/ssp_station/report.html，单位定义见metric_definitions.csv，审查记录见audit.json和figure_audit.json。
