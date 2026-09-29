#!/bin/bash
#SBATCH --job-name=rq1_global_station
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=00:30:00
#SBATCH --output=/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/global/station/test_global_station_extremes_%j.out
#SBATCH --error=/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/global/station/test_global_station_extremes_%j.out

set -euo pipefail
REPO_ROOT="/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$REPO_ROOT"
python RQ1_extreme/global/station/test_global_station_extremes.py "$@"
