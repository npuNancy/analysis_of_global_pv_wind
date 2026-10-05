#!/bin/bash
#SBATCH --job-name=rq1_test_grid_extremes
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7G
#SBATCH --time=00:15:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/global/grid/test_grid_extremes_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/global/grid/test_grid_extremes_%j.out

set -euo pipefail
REPO_ROOT="/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$REPO_ROOT"
python RQ1_extreme/global/grid/test_grid_extremes.py
