# Fig. S04：全国反事实结果

## 科学问题与面板
同时呈现所有容量目录国家的路径差、气候贡献、部署贡献及交互项。

a–b：D；c–d：Phi_C；e–f：Phi_S；g–h：J。每对面板风电在左、光伏在右；每项指标6页，共24页PNG。

## 数据与口径
复用本目录 `outputs/source_data/`：panel_abcdefgh.csv。公共输入使用 `paper_figures/prepare/outputs/`，不重跑已验收的664项准备任务。

三时期均展示168个国家并集，按2050参考风光容量合计排序。每项指标跨技术和跨页共用对称色标。灰色为不足四模式或不可用；点号为模式方向不一致。分页清单在 outputs/page_manifest.json。

## 运行与产物
在远程仓库根目录创建日志目录后提交：

```bash
mkdir -p logs/paper_figures/supplementary/fig_s04_country_counterfactuals
sbatch paper_figures/supplementary/fig_s04_country_counterfactuals/plot.sh
```

默认输出：`outputs/fig_s04_country_counterfactuals_{D|Phi_C|Phi_S|J}_page01.png` 至各指标的 `page06.png`，共24个600 dpi PNG；完整文件清单见 `outputs/page_manifest.json`。

PNG配套 `*_audit.json` 保存输入SHA-256、数值检查和视觉复核记录。全套交叉核验入口为 `paper_figures/supplementary/validate_supplementary.sh`，报告为 `logs/paper_figures/supplementary/validation.json`。
