#!/bin/bash
#SBATCH --job-name=rq2_loss_country_map
#SBATCH --partition=wzhctest
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7G
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ2_loss/country/ssp_gap_clustering/map_country_clusters_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ2_loss/country/ssp_gap_clustering/map_country_clusters_%j.out

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

mkdir -p "$REPO_ROOT/logs/RQ2_loss/country/ssp_gap_clustering"
cd "$REPO_ROOT"
python RQ2_loss/country/ssp_gap_clustering/map_country_clusters.py
