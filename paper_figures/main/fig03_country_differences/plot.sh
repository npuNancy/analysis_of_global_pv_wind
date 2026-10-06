#!/bin/bash
#SBATCH --job-name=fig03_plot
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14000M
#SBATCH --time=01:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig03/plot_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig03/plot_%j.out
set -euo pipefail
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLBACKEND=Agg
export MPLCONFIGDIR=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/paper_figures/main/fig03_country_differences/outputs/.mplconfig
mkdir -p "$MPLCONFIGDIR"
python -m paper_figures.main.fig03_country_differences.plot "$@"
