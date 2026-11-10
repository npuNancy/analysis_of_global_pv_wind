#!/usr/bin/env bash
#SBATCH --job-name=gem_job_generator
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:15:00
#SBATCH --output=/work/home/acxujo26gv/lcoe_gem2025_climate_storage/code/logs/gem_job_generator-%j.log
#SBATCH --error=/work/home/acxujo26gv/lcoe_gem2025_climate_storage/code/logs/gem_job_generator-%j.log
set -euo pipefail
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/acxujo26gv/lcoe_gem2025_climate_storage/code
python -m scnet.create_gem_station_jobs
