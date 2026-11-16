# 全球场站-dispatch-2025 气候评价

## 最终目标
交付4个GCM × 2气候SSP × 2场站SSP × 2技术的CF、Extreme、逐事件Loss和全年发电量，仅覆盖2030—2059；容量使用2030、2040、2050总量快照。输出8张三面板图、24张独立PNG及独立Markdown报告，完成共享读取验收。

## 分阶段目标
- [x] 输入定位与验收：SSP126/245六份0.1°CSV、容量与SHA256。
- [x] 共享目录：1959保存，1892/1520默认ACL写入，1866及其他账号只读。
- [x] 输入与首批验证：原生采样、日历、三十年时间轴和Loss公式。
- [x] CF / Extreme全矩阵：1,360任务、16,320分片。
- [x] Loss全矩阵：1,360任务，1,360逐事件NetCDF及1,360年度中间NPZ。
- [x] 发布验收：8组、32年度NPZ、1,440逐模式行、360集合行。
- [x] 绘图验收：8张组图、24张独立PNG、源表和30条OLS拟合。
- [x] 独立报告共享副本最终访问验收：1866及1870逐文件读取、哈希和52个相对链接通过。
- [x] 指定三个原文档在本地及1866的SHA256不变。

## 科学合同
方案采用capacity_recovery_20261113T222351/MPI-ESM1-2-HR的SSP126/245布局，以GEM2025存量初始化、未来单年CF优化。选址模式与四GCM气候评价是不同维度。三个容量快照是总量，分别用于对应十年；风电为MW，光伏为MWp/DC，风电能量不缩放。
CF/Extreme直接从正式网格产品提取，保留原生三小时步长、模式日历、缺测和事件定义。低资源事件仍用2015—2024基准；本轮没有历史或SSP585输出。
正常CF在三个未来十年内分别排除事件并集后按月—小时计算。Loss保留各事件及并集all的原核指标，净损失带符号；全年发电由CF积分。汇总使用每个双情景×技术组跨四模式、跨30年的共同有效站点，完整目录容量和覆盖率另行保存。

## 运行与资源
共享根为 `/work/home/acxujo26gv/dispatch_2025_climate_storage`；开发和绘图使用1866项目。科学计算使用共享 `code/` 冻结快照和仓库.venv，日志在 `code/logs/dispatch_2025/`。
1892处理气候SSP126，1520处理SSP245；每账号全项目最多20个活动作业，提交时持账号锁并重新计数。wzhctest、单节点、单Python进程；正式提取2核，正式Loss1核，发布首批4核/其余1核，最终验收4核。原始数据处理、Loss和汇总均在Slurm计算节点执行；小型汇总表绘图在1866登录节点执行。

## 完成证据
| 阶段 | 共享根下的证据 |
|---|---|
| 输入与源代码 | `inputs/station_provenance.json`、`inputs/code_manifest.json` |
| 提取 | `future/runtime/extraction_accepted.json` |
| Loss首批/全量 | `loss_future/runtime/pilot_audit.json`、`loss_future/runtime/loss_accepted.json` |
| 发布首批/全量 | `publish/runtime/pilot_audit.json`、`publish/runtime/publication_groups_accepted.json` |
| 正式完成 | `runtime/authoritative_index.json`、`runtime/completion.json` |
| 权限 | `runtime/formal_access.json`、`runtime/report_access.json` |
| 原文档保护 | `runtime/protected_documents_check.json` |

最终验收作业49192173为COMPLETED/0:0。逐文件核对任务/代码身份、输出、原生Loss字段、站点目录、容量快照、完整情景矩阵、能量闭合及共享访问位。

## 图件与报告
图件在 `paper_figures/supplementary/dispatch_2025/outputs/`。Python/matplotlib，600 dpi，仅PNG；三列依次为风光合并、风电、光伏。
容量和暴露采用三个年代点；损失和发电使用2030—2059逐年均值及全30年OLS趋势。阴影为四模式min—max。图件只展示126/126和245/245配对路径，完整交叉情景保留于正式数据。
`manifest.json`记录来源与所有PNG/源表哈希，`figure_validation.json`记录数值、导出和视觉验收。
独立报告为 `document/全球场站-dispatch-2025气候评价.md`；共享副本为结果根 `report/document/全球场站-dispatch-2025气候评价.md`。

重新生成图件：
```bash
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
python -m paper_figures.supplementary.dispatch_2025.plot
```
