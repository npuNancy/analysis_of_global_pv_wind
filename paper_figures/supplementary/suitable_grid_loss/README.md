# 全球适宜网格损失曲线

科学问题：固定适宜网格上的单位装机净损失，在三种气候SSP下如何随2030–2059年变化？不预设趋势或SSP排序。

Python/matplotlib定量双面板：左风电、右光伏。分别输出2030–2059年度曲线，以及2030s、2040s、2050s十年均值曲线。曲线为四模式等权均值，阴影为模式min–max，非置信区间。每张完整图及a、b独立图均保存600 dpi PNG。

## 数据与口径

1866直接读取1775正式入口：
`/work/home/acsep06cn2/generation_loss_suitable_grid/suitable_grid/`。

通过completion → receipt → unit manifest → tiles/files读取，核验manifest及annual_loss.nc的SHA256。1866账号UID403202使用文件只读、目录读取与遍历权限；ACL配置入口为 `utils/data_access/grant_suitable_grid_read.sh`，由1775执行。该脚本保留现有ACL条目和mask，并配置目录默认只读ACL。

每个适宜网格固定1 MW；使用all事件并集的带符号净损失，单位MWh/MW/年，不再除容量或缩放风电数值。没有场站SSP维度。主结果采用跨四模式、三SSP、全部30年净损失和正损失均有效的共同网格集合，另存各年自身有效集合结果。固定1 MW权重等价于网格等权，不代表面积加权或真实装机加权。各年代使用其自身正常CF基线。

## 运行

在1866仓库根目录执行：
```bash
bash paper_figures/prepare/prepare_suitable_grid_loss.sh
# 汇总成功后，绘图仅处理小型汇总表：
source .venv/bin/activate
python -m paper_figures.supplementary.suitable_grid_loss.plot
```

预处理按技术/patch分组，16进程，每次加载一个tile的12组合、三个年代。保存共同网格ID、年度分子/有效数量/覆盖、逐模式年代均值及来源索引；核对全球唯一网格数（风591798、光557406）。已完成分片经输入及输出SHA256校验后可恢复使用。

共享汇总位于 `paper_figures/prepare/outputs/suitable_grid_loss/`；本图PNG、元数据及源表位于 `outputs/`，日志位于 `logs/paper_figures/suitable_grid_loss/`。运行记录见 `paper_figures/prepare/outputs/suitable_grid_loss_run.json`。正式输出以汇总完成标记、图件元数据和实际PNG为准。

## 完成检查

2026-11-01：权限作业47887585与预处理作业47887599完成。334872个年度文件完成读取及SHA256核验，1440行年度汇总和144行逐模式年代汇总通过一致性检查。共同有效网格：风电574922/591798（97.15%）、光伏546978/557406（98.13%）。两张完整组图及四张独立子图已全部检查，图例、标签和裁切正常。详细记录见outputs/validation.json、outputs/visual_qa.json及outputs/caption.md。
