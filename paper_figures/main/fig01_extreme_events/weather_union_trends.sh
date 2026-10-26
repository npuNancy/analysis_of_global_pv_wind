#!/bin/bash
#SBATCH --job-name=weather_union
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=56000M
#SBATCH --time=12:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig01/weather_union_%A_%a_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig01/weather_union_%A_%a_%j.log
set -euo pipefail
REPO=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source "$REPO/.venv/bin/activate"
cd "$REPO"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    mkdir -p "$REPO/logs/paper_figures/fig01"
    python -m paper_figures.main.fig01_extreme_events.weather_union_trends --mode prepare
    exec sbatch --array="0-7%8" "$REPO/paper_figures/main/fig01_extreme_events/weather_union_trends.sh" "$@"
fi
python -m paper_figures.main.fig01_extreme_events.weather_union_trends "$@"
