#!/usr/bin/env bash
#SBATCH --job-name=lcs_verify_delivery
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --output=/work/home/acxujo26gv/lcoe_station_climate_storage/logs/verify_delivery-%j.log
#SBATCH --error=/work/home/acxujo26gv/lcoe_station_climate_storage/logs/verify_delivery-%j.log
set -euo pipefail
umask 0022
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/acxujo26gv/lcoe_station_climate_storage/code
python -m utils.lcoe_station_climate.verify_delivery --root /work/home/acxujo26gv/lcoe_station_climate_storage "$@"
