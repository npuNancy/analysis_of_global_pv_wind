#!/bin/bash
#SBATCH --job-name=metric_prepare_union
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=28000M
#SBATCH --time=00:45:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/global_metric_trends/prepare_union_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/global_metric_trends/prepare_union_%j.out
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    mkdir -p logs/paper_figures/global_metric_trends
    exec sbatch "$0" "$@"
fi
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m paper_figures.supplementary.global_metric_trends.prepare_union "$@"
