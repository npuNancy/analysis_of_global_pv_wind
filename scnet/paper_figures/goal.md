# Paper figure preparation

Execute only in the Wuzhen 1866 checkout. Inputs declared by the five published BCSD-v2 indexes are read-only. The project `.venv` and `wzhctest` override generic environment defaults.

The preparation DAG is inventory/catalogues → loss shards → annual/window/counterfactual tables, and inventory/catalogues → station-event shards → exposure tables. Grid-event preparation is independent after inventory. Figure source tables depend on accepted summaries; no scientific conclusion or figure is declared complete merely because a job was submitted.

Loss units keep all selected models and climate SSPs together within one station SSP, technology and source patch so common station support can be computed before regional aggregation. Snapshots are processed sequentially. Table rows preserve model, both SSPs, snapshot, year, event, region and support policy. Signed net loss uses a ratio of energy totals to capacity totals. All events use the same station support; all is the published union, never the sum of event labels. Time completeness of annual Loss is not inferable from finite annual values and is reported separately.

Generated job files live outside the repository under `../../runtime/paper_figures_jobs/`. Outputs are under `paper_figures/prepare/outputs/`; logs and progress under `logs/paper_figures/`. Each unit owns its outputs and writes a completion marker last. Existing successful units are reused only within the same immutable campaign configuration. Failed attempts require inspection before resubmission.

The account-wide limit is 20 active jobs, counting all projects. Submission acquires the existing shared lock `logs/RQ1_extreme/completion_status/submit.lock`, recounts account jobs immediately before each sbatch, and only releases downstream stages after COMPLETED / 0:0 plus expected completion artifacts. Runtime control additionally holds its own campaign lock. Update `logs/paper_figures/completion_status/progress.md` after each monitoring cycle with job IDs, states, exits, elapsed, MaxRSS, artifact evidence and next action. Scientific validation runs on compute nodes.

Pilot runs use isolated output roots. Full preparation is released only after pilot acceptance. No Slurm arrays, automatic cancellation, changes to upstream products, or fabricated missing values. S7/S9 loss reconstruction and S11 scale experiments have separate scientific acceptance requirements.

## Shared multi-account execution

`accounts.json` lists accounts admitted after read-access checks. The coordinator remains Wuzhen1866. Code, prepared catalogues, outputs, logs, and per-account runtime state use the 1866 repository and runtime directories. Each submitted unit has one immutable execution account and output identity. Previously submitted jobs remain assigned to 1866 with their original Slurm IDs and resources. Only unsubmitted units receive generated 16-CPU / 56,000-MB scripts.

Loss shards use 16 spawn workers. New event shards add `--parallel-snapshots`, making each model × climate SSP × independent ten-year window a process task, up to 16 workers. Each window retains its original boundary censoring and time continuity checks. Reductions use 16 allocated CPUs for memory; their dataframe operations are not claimed to use 16 processes.

Generate a distribution without submission:

```bash
python -m scnet.paper_figures.distribute_prepare_jobs <source-manifest> --accounts scnet/paper_figures/accounts.json --job-dir <external-job-directory> --dry-run
python -m scnet.paper_figures.distribute_prepare_jobs <source-manifest> --accounts scnet/paper_figures/accounts.json --job-dir <external-job-directory>
python -m scnet.paper_figures.configure_shared_access --apply
```

Generation records `distribution.json` beside the original manifest, preventing the original single-account controller from submitting duplicate units. Scripts, accounting state and ACL setup remain separate operations. Verify generated shell syntax and run `check_account_access.sh` on each execution account before starting production. Override that check's stdout/stderr paths to the account's assigned central log directory.

ACLs give each account write access only to its assigned new output, log and runtime-state directories. Default ACLs retain coordinator read/write/traversal access on newly created files and subdirectories and read access for the other admitted accounts. File ownership remains with the execution account. The input products stay read-only. Existing active output directories are unchanged.

Start one controller through each account's existing SSH connection; no SSH credentials are copied between accounts:

```bash
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export PYTHONDONTWRITEBYTECODE=1
python -m scnet.paper_figures.control_account_jobs --submit --watch --interval 900
```

The current manifest is resolved from `logs/paper_figures/completion_status/multi_account.json`. Each account holds its own controller lock and its pre-existing shared submission lock (configured in `accounts.json`). The cap of 20 counts all of that account's active jobs, including other projects and newly acknowledged submissions before they appear in `squeue`.

Per-account state and `progress.md` are updated atomically. The coordinator periodically assembles the global `progress.md` and state snapshot. Downstream work waits for the producing account's COMPLETED/0:0 plus verified completion artifacts. Deterministic failures block their dependency branches; ambiguous submission acknowledgements require investigation to avoid duplicates. Transient unambiguous submission rejections have at most three attempts; stderr is recorded. Existing Slurm jobs are never cancelled by these controllers.

Account status: `logs/paper_figures/completion_status/accounts/<username>/progress.md`. Global status: `logs/paper_figures/completion_status/progress.md`. Controllers may run on login nodes; scientific processing, environment/data smoke checks, and numerical equivalence checks run through Slurm.

Controllers check every 15 minutes (900 seconds). At each check, each account fills available slots with dependency-ready units while other jobs may still be running; there is no whole-batch completion barrier.

Wuzhen1872 is excluded from submission accounts. Historical campaign records retain its completed tasks with `submit_enabled: false`; unfinished cancelled tasks are reassigned with their prior attempt records preserved.
