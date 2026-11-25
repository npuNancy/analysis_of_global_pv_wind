#!/bin/bash
#SBATCH --job-name=rq2-dispatch-increments
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=6
#SBATCH --mem=21000M
#SBATCH --time=01:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/rq2_siting_loss/dispatch_increments_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/rq2_siting_loss/dispatch_increments_%j.log
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python -m paper_figures.supplementary.rq2_siting_loss.prepare_dispatch_increments
