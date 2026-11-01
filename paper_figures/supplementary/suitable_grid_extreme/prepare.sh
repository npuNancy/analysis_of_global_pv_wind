#!/bin/bash
#SBATCH --job-name=suitable_extreme_prepare
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=28672M
#SBATCH --time=12:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/suitable_grid_extreme/prepare_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/suitable_grid_extreme/prepare_%j.out
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python -m paper_figures.supplementary.suitable_grid_extreme.prepare
