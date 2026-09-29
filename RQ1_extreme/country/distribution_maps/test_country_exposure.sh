#!/bin/bash
#SBATCH --job-name=rq1_test_country_exposure
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=01:00:00
#SBATCH --output=/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/country/distribution_maps/test_country_exposure_%j.out
#SBATCH --error=/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/country/distribution_maps/test_country_exposure_%j.out

set -euo pipefail
REPO_ROOT="/work/home/acp6varuz3/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$REPO_ROOT"
python RQ1_extreme/country/distribution_maps/test_country_exposure.py "$@"
