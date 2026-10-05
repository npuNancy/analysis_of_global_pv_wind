#!/bin/bash
#SBATCH --job-name=rq2_loss_country_reversal
#SBATCH --partition=wzhctest
#SBATCH -N 1
#SBATCH --ntasks=1
# Four worker processes at 3.5 GB per core (one model is loaded at a time, 4 units each).
#SBATCH --cpus-per-task=4
#SBATCH --mem=14G
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ2_loss/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ2_loss/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering_%j.out

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

mkdir -p "$REPO_ROOT/logs/RQ2_loss/country/ssp_gap_reversal_clustering"
cd "$REPO_ROOT"

python RQ2_loss/country/ssp_gap_reversal_clustering/ssp_gap_reversal_clustering.py
