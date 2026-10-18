#!/bin/bash
#SBATCH --job-name=prepare_ssp_station_dynamics
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=56000M
#SBATCH --time=12:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/ssp_station/prepare_ssp_station_dynamics_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/ssp_station/prepare_ssp_station_dynamics_%j.out
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
mkdir -p logs/paper_figures/ssp_station
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    exec sbatch "$0" "$@"
fi
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m paper_figures.main.fig01_extreme_events.prepare_ssp_station_dynamics "$@"
