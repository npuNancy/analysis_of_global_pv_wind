#!/bin/bash
#SBATCH --job-name=fig04_cf
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14000M
#SBATCH --time=04:00:00
#SBATCH --array=0-15%16
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig04/cf_%A_%a_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig04/cf_%A_%a_%j.out
set -euo pipefail
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m paper_figures.main.fig04_climate_deployment.prepare_cf_counterfactual "$@"
