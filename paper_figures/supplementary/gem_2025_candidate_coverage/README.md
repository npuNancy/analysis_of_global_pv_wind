# GEM 2025 candidate coverage

> 坐标核对更新：原候选缓存的边界取整已确认有误。40,509／10,076 仅反映旧缓存成员关系，不能用于量化真实适宜区覆盖。详见场站图目录中的 grid_mapping_audit.md。本次尚未重建候选或重跑正式选址。

2025 年光伏与陆风／类型未知风电的位置，按其所属 0.1° 格点是否属于原 LCOE 候选缓存分色。计算、图件和文档在乌镇 1866 完成；无正式选址任务运行。

## 图注

a，光伏项目分期；b，陆风及安装类型未知的风电项目分期。蓝色表示所属 0.1° 格点在原有候选缓存内，橙色表示在其外。每个等尺寸点使用 GEM 原始经纬度；共址分期可以重叠。候选外比例按项目分期数计算。光伏候选外 40,509/70,196（57.7%），风电候选外 10,076/17,759（56.7%）。所有海上风电分期已排除。该图显示候选集合对已识别存量的覆盖，不诊断单个场站的物理适宜性。

数据来自 GEM 2026 年 2 月版，筛选 operating 且投运年已知、不晚于 2025；不含投运年缺失记录。光伏输入换算为 MWp/DC；风电为 MW。容量不影响点尺寸。

## 文件

- plot.py：Python / matplotlib / Cartopy 生成脚本。
- plot.sh：同名配套 SLURM 脚本；本次小表分析直接激活环境后运行。
- figure_contract.json：绘图前定义的数据、论点、映射与验收条件。
- outputs/gem_2025_candidate_coverage.png：两子图完整 PNG。
- outputs/gem_2025_candidate_coverage_a.png、_b.png：独立面板。
- outputs/source_data/stations_2025_candidate_membership.csv：87,955 条分期的坐标、容量、换算字段和内外分类。
- outputs/source_data/coverage_summary.csv：四类计数、占比、唯一格点数及容量。
- outputs/data_audit.json：源文件校验和、独立坐标映射检查、缓存重复记录统计和输出校验和。
- 方法说明：../../../document/场站选址相关/GEM2025场站候选覆盖与适宜性方法对比.md（从仓库根目录访问 document 下同名文件）。

## 重现

在乌镇 1866 项目根目录激活 .venv 后运行：

    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m paper_figures.supplementary.gem_2025_candidate_coverage.plot

两个技术共享 PlateCarree 投影及 [-180, 180, -60, 85] 显示范围。Natural Earth 国界按项目函数合并中国图形。PNG 为 600 dpi，完整图 183 × 174 mm，独立面板 183 × 85 mm。颜色为 #0072B2、#D55E00，等尺寸点按固定随机种子改变绘制顺序以平衡遮挡，不改变坐标。

候选成员判定使用原始 child_lin_idx.npy 的唯一 ID；不在图中追加父级 100 MW 门槛，不读取原始 CF 文件，也不重建适宜性掩膜。年均 CF 缓存不参与这张图。
