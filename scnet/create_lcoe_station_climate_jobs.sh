#!/usr/bin/env bash
#SBATCH --job-name=lcs_create_lcoe_station_climate_jobs
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --output=/work/home/acsep06cn2/lcoe_station_climate_v1/logs/create_lcoe_station_climate_jobs-%j.log
#SBATCH --error=/work/home/acsep06cn2/lcoe_station_climate_v1/logs/create_lcoe_station_climate_jobs-%j.log
set -euo pipefail
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/acsep06cn2/lcoe_station_climate_v1/code
python -m scnet.create_lcoe_station_climate_jobs "$@"
