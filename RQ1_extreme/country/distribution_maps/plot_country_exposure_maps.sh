#!/bin/bash
#SBATCH --job-name=rq1_plot_country_exposure_maps
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14G
#SBATCH --time=01:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/country/distribution_maps/plot_country_exposure_maps_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/RQ1_extreme/country/distribution_maps/plot_country_exposure_maps_%j.out

set -euo pipefail
REPO_ROOT="/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$REPO_ROOT"
python RQ1_extreme/country/distribution_maps/plot_country_exposure_maps.py "$@"
