#!/bin/bash
#SBATCH --job-name=rq1_create_extreme_grid_jobs
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=00:10:00
#SBATCH --output=/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/create_extreme_grid_jobs_%j.out
#SBATCH --error=/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/create_extreme_grid_jobs_%j.out

set -euo pipefail
REPO_ROOT="/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
cd "$REPO_ROOT"
python scnet/create_extreme_grid_jobs.py "$@"
