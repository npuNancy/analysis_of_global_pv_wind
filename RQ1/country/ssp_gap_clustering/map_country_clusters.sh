#!/bin/bash
#SBATCH --job-name=rq1_country_map
#SBATCH --partition=wzhctest
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7G
#SBATCH --output=logs/RQ1/country/ssp_gap_clustering/map_country_clusters_%j.out
#SBATCH --error=logs/RQ1/country/ssp_gap_clustering/map_country_clusters_%j.out

set -euo pipefail

REPO_ROOT="$HOME/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

mkdir -p "$REPO_ROOT/logs/RQ1/country/ssp_gap_clustering"
cd "$REPO_ROOT"
python RQ1/country/ssp_gap_clustering/map_country_clusters.py
