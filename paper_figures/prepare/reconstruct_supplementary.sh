#!/bin/bash
#SBATCH --job-name=supp_reconstruct
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=56G
#SBATCH --time=24:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/supplementary/reconstruction/reconstruct_%A_%a_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/supplementary/reconstruction/reconstruct_%A_%a_%j.log
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export PYTHONPATH=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
export OPENBLAS_NUM_THREADS=1
python paper_figures/prepare/reconstruct_supplementary.py --shards "${SUPP_SHARDS:-1}" --workers 16 "$@"
