#!/bin/bash
#SBATCH --job-name=fig_s01_three_factor_dec
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14G
#SBATCH --time=04:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/supplementary/fig_s01_three_factor_decomposition/plot_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/supplementary/fig_s01_three_factor_decomposition/plot_%j.log
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export MPLBACKEND=Agg
export PYTHONPATH=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
export OPENBLAS_NUM_THREADS=1
python paper_figures/supplementary/fig_s01_three_factor_decomposition/plot.py
