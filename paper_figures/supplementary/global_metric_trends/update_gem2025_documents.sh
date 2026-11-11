#!/bin/bash
#SBATCH --job-name=gem2025_docs
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=00:10:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/global_metric_trends/gem2025_docs_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/global_metric_trends/gem2025_docs_%j.out
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
if ! printenv SLURM_JOB_ID >/dev/null; then
    mkdir -p logs/paper_figures/global_metric_trends
    exec sbatch "$0" "$@"
fi
source .venv/bin/activate
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m paper_figures.supplementary.global_metric_trends.update_gem2025_documents "$@"
