#!/bin/bash
#SBATCH --job-name=rq1-dispatch-overview
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/global_metric_trends/rq1_dispatch_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/global_metric_trends/rq1_dispatch_%j.log
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
export OPENBLAS_NUM_THREADS=1
python -m paper_figures.supplementary.global_metric_trends.plot_dispatch_rq1
