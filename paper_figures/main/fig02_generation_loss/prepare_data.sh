#!/bin/bash
#SBATCH --job-name=fig02_prepare
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14000M
#SBATCH --time=00:30:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig02/prepare_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig02/prepare_%j.out
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    mkdir -p logs/paper_figures/fig02
    exec sbatch "$0" "$@"
fi
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLBACKEND=Agg
export MPLCONFIGDIR=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/paper_figures/main/fig02_generation_loss/outputs/.mplconfig
mkdir -p "$MPLCONFIGDIR"
python -m paper_figures.main.fig02_generation_loss.prepare_data "$@"
