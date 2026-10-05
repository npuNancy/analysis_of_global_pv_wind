# Paper figure preparation

Execute only in the Wuzhen 1866 checkout. Inputs declared by the five published BCSD-v2 indexes are read-only. The project `.venv` and `wzhctest` override generic environment defaults.

The preparation DAG is inventory/catalogues → loss shards → annual/window/counterfactual tables, and inventory/catalogues → station-event shards → exposure tables. Grid-event preparation is independent after inventory. Figure source tables depend on accepted summaries; no scientific conclusion or figure is declared complete merely because a job was submitted.

Loss units keep all selected models and climate SSPs together within one station SSP, technology and source patch so common station support can be computed before regional aggregation. Snapshots are processed sequentially. Table rows preserve model, both SSPs, snapshot, year, event, region and support policy. Signed net loss uses a ratio of energy totals to capacity totals. All events use the same station support; all is the published union, never the sum of event labels. Time completeness of annual Loss is not inferable from finite annual values and is reported separately.

Generated job files live outside the repository under `../../runtime/paper_figures_jobs/`. Outputs are under `paper_figures/prepare/outputs/`; logs and progress under `logs/paper_figures/`. Each unit owns its outputs and writes a completion marker last. Existing successful units are reused only within the same immutable campaign configuration. Failed attempts require inspection before resubmission.

The account-wide limit is 20 active jobs, counting all projects. Submission acquires the existing shared lock `logs/RQ1_extreme/completion_status/submit.lock`, recounts account jobs immediately before each sbatch, and only releases downstream stages after COMPLETED / 0:0 plus expected completion artifacts. Runtime control additionally holds its own campaign lock. Update `logs/paper_figures/completion_status/progress.md` after each monitoring cycle with job IDs, states, exits, elapsed, MaxRSS, artifact evidence and next action. Scientific validation runs on compute nodes.

Pilot runs use isolated output roots. Full preparation is released only after pilot acceptance. No Slurm arrays, automatic cancellation, changes to upstream products, or fabricated missing values. S7/S9 loss reconstruction and S11 scale experiments have separate scientific acceptance requirements.
