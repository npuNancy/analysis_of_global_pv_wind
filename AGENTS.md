# Codex Instructions

## Communication

- 默认用英文思考，用中文回答，除非我明确要求用英文回答。
- 回答要直接、具体，避免空泛解释。
- 修改代码前先理解现有结构和约定。
- 每次回复我时，都称呼我为 `小凯`，并且在回复的最后加上 `希望对你有帮助，小凯！`。
- 对话框中的公式必须使用人类可读的纯文本形式；写入 Markdown 文件的公式使用可渲染的 Markdown、LaTeX 等格式。

## 绘图与分析环境

- 默认执行账号：乌镇1866 / `scnet-wuzhen-1866` / `aczlvkl1ac`。
- 远程项目目录：`/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind`；绘图分析代码、结果、缓存和日志均使用该账号的项目目录。
- 五类正式结果数据仍集中存储在乌镇1872 / `scnet-wuzhen-1872` / `acjpoxgsdu`，按 `document/BCSD_v2数据使用指南.md` 的入口只读访问。
- 场站与 Natural Earth 边界使用1866项目中的 `data/stations/` 和 `data/maps/natural_earth/` 数据副本。
- 远程 `.venv` 为软链，目标是 `/work/home/acbw9wpn5k/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv`。
- 论文绘图遵循 `document/主图与子图设计.md` 和 `$pv-wind-paper-figures`。

## Engineering Defaults

- 优先遵循项目已有风格，不引入不必要抽象。
- 修改后尽量运行相关测试、lint 或类型检查。
- 不要重构无关代码。
- 遇到脏工作区时，不要回滚我已有的改动。
- 当前工作区的 python 使用 uv 环境: `.venv`
- 超算节点提供 Git 模块 `apps/git/2.30.2`；使用前执行 `module load apps/git/2.30.2`，再用 `git --version` 检查版本。
- 未特别说明时，“损失”默认指单位装机损失。
- 未特别说明时，图片只保存 PNG；此约定优先于 `nature-figure` 等 SKILL 的导出格式默认值。
- 上游风电数据已修复，发电量与损失能量使用原始数值，不再乘以 0.1。
- 每个可执行的 Python 脚本都要在相同目录提供同名的 SLURM 作业脚本（`.py` 对应 `.sh`）；作业脚本使用仓库 `.venv`，默认参数运行 Python 脚本，并将日志写入仓库 `logs/`。
- SLURM 默认使用 `wzhctest` 队列、1 个节点，按 3.5 GB/核估算内存需求并配置 `--cpus-per-task`；标准输出和错误输出使用相同的绝对日志路径，文件名包含 `%j`。提交前创建日志目录，使用 `source .venv/bin/activate` 激活环境，再进入工作目录运行脚本。
- 按实际资源需求选择执行方式：大内存、计算密集型或大量原始数据读取的分析与绘图任务，通过 SLURM 在计算节点运行，不在登录节点直接执行；仅处理已有小型汇总表的轻量分析、绘图和校验等任务，优先在登录节点激活仓库 `.venv` 后直接运行 Python，无需提交 SLURM。是否提交作业取决于实际计算量和内存需求，不因任务属于绘图或已有配套 `.sh` 就默认提交。

### Scope Discipline

Implement the requested change, not the story behind the change.

Do:
- Make the smallest complete change.
- Keep names, APIs, and docs focused on the final desired state.

Don't:
- Add features, rules, comments, or documentation explaining rejected ideas.
- Preserve removed concepts in names (e.g., "no-X", "without-X").
- Convert a correction into a general design principle.

A fix is a fix, not a new product feature.

## Safety

- 不要执行破坏性 git 命令，除非我明确要求。
- 新增依赖前说明原因。
