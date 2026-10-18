#!/bin/bash
#SBATCH --job-name=analyze_ssp_station
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14000M
#SBATCH --time=02:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/ssp_station/analyze_ssp_station_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/ssp_station/analyze_ssp_station_%j.out
set -euo pipefail
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
mkdir -p logs/paper_figures/ssp_station
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    exec sbatch "$0" "$@"
fi
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m paper_figures.main.fig01_extreme_events.analyze_ssp_station "$@"
