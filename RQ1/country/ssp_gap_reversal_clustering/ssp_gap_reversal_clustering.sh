#!/bin/bash
#SBATCH --job-name=rq1_country_reversal
#SBATCH --partition=wzhctest
#SBATCH -N 1
#SBATCH --ntasks=1
# Four worker processes at 3.5 GB per core (one model is loaded at a time, 4 units each).
#SBATCH --cpus-per-task=4
#SBATCH --mem=14G
#SBATCH --output=logs/RQ1/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering_%j.out
#SBATCH --error=logs/RQ1/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering_%j.out

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

mkdir -p "$REPO_ROOT/logs/RQ1/country/ssp_gap_reversal_clustering"
cd "$REPO_ROOT"

python RQ1/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering.py
