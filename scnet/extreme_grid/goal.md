# RQ1 extreme grid parallel workflow

## Workload
- Cache unit: model × SSP, processing all selected patches and technologies. Each cache file belongs to exactly one job.
- Full campaign: 12 cache jobs × 94 combinations = 1128; 16 processes, 16 CPUs and 56 GB per cache job.
- Years are processed together to reuse source reads. Completed cache fingerprints and atomic writes allow reuse after interruption.
- Each cache job writes a unique shard manifest. After all succeed, one manifest job validates their coverage and cache metadata.
- Global figures and country analysis both depend on the manifest job and may run concurrently.
- Cache jobs write disjoint annual NetCDF files; only the manifest job writes the full cache_manifest.json.

## Environment and resources
Execution account: scnet-wuzhen-1866 (aczlvkl1ac).
Checkout: /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind.
Published input: /work/share/acjpoxgsdu/extreme_grid/grid_v2; outputs and logs belong to the execution account.
Scientific jobs use repository .venv and wzhctest. Memory is 3.5 GB per CPU.
The confirmed partition QOS allows at most 20 active/submitted jobs per user; count all account jobs under the shared submit lock before each submission.
Lock: repository logs/RQ1_extreme/completion_status/submit.lock.
Global/country figures each use 4 CPUs and 14 GB; plotting is not a 16-process computation.
Manifests use 2 CPUs and 7 GB. Threaded BLAS/OpenMP are limited to one thread per process.

## Generate and submit
Run scnet/extreme_grid/create_extreme_grid_jobs.py --dry-run to inspect the selected workload.
Use --job-dir for a new repository-external directory; the generator never submits jobs or overwrites an existing job directory.
It reads only JSON inventory and generates scripts; it can run on the login node.
Create the requested log directory before submission. Submit cache scripts first, the manifest script with afterok dependencies on all cache jobs, then global/country scripts with afterok on the manifest job.
jobs.json records dependencies and resource requests. Record each sbatch job ID immediately in the runtime status directory.
Do not run competing cache producers over the same combinations; wait for a replaced job to leave the queue before launching replacements.

## Monitor and completion
Check scheduler/accounting state, log tails, cache counts, and completion manifests every 5 minutes.
Update logs/RQ1_extreme/completion_status/progress.md after every check, including failures and next actions.
Success requires zero-exit COMPLETED status plus the expected manifest, CSV and PNG outputs.
Do not infer completion from disappearance from squeue.
If a cache job fails, inspect evidence and retry only that shard when appropriate. Preserve source data and valid caches.
Input NetCDF and symlinks under /work/share/acjpoxgsdu/extreme_grid/grid_v2 are read-only.
All array computation, scientific validation and rendering run on compute nodes.
