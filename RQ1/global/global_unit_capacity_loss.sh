#!/bin/bash
#SBATCH --job-name=rq1_global_unit_loss
#SBATCH --partition=wzhctest
#SBATCH -N 1
#SBATCH --ntasks=1
# Eight worker processes at 3.5 GB per core; the Python reader is single-threaded per worker.
#SBATCH --cpus-per-task=8
#SBATCH --mem=28G
#SBATCH --output=logs/RQ1/global/global_unit_capacity_loss_%j.out
#SBATCH --error=logs/RQ1/global/global_unit_capacity_loss_%j.out

set -euo pipefail

# Slurm does not expand $HOME inside #SBATCH directives, so the log paths above
# stay relative to the submission directory (the repository root); derive the
# repository location from $HOME here so the script works on any cluster account
# that hosts the repo at ~/project_climate_patchify/repos/analysis_of_global_pv_wind.
REPO_ROOT="$HOME/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

mkdir -p "$REPO_ROOT/logs/RQ1/global"
cd "$REPO_ROOT"

python RQ1/global/global_unit_capacity_loss.py
