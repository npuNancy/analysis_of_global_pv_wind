#!/bin/bash
#SBATCH --job-name=rq2-summary
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7G
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/rq2_siting_loss/analyze_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/rq2_siting_loss/analyze_%j.log
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export OPENBLAS_NUM_THREADS=1
python paper_figures/supplementary/rq2_siting_loss/analyze.py
