#!/usr/bin/env bash
#SBATCH --job-name=lcl_create_lcoe_station_loss_jobs
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --output=/work/home/acxujo26gv/lcoe_station_climate_storage/loss/logs/create_lcoe_station_loss_jobs-%j.log
#SBATCH --error=/work/home/acxujo26gv/lcoe_station_climate_storage/loss/logs/create_lcoe_station_loss_jobs-%j.log
set -euo pipefail
umask 0022
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/acxujo26gv/lcoe_station_climate_storage/code
mkdir -p /work/home/acxujo26gv/lcoe_station_climate_storage/loss/logs
python -m scnet.create_lcoe_station_loss_jobs --stage prepare "$@"
