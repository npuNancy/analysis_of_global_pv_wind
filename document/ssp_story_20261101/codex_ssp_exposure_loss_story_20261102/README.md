# SSP 研究问题与证据核查

当前入口为 [研究问题与证据核查](outputs/research_questions.md)，包括已验证的情景比较和三个待检验问题。尚未建立新的三条论文结论。

核查使用已有小型汇总表，在 1866 项目根目录运行：

```bash
source .venv/bin/activate
python document/ssp_story_20261101/codex_ssp_exposure_loss_story_20261102/audit_research_questions.py
```

同目录提供配套 SLURM 脚本。逐模式表和四模式汇总写入 `outputs/review_source_data/`，输入哈希及指标校验写入 `outputs/review_validation.json`。
