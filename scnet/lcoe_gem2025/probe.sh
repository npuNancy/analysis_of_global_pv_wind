#!/usr/bin/env bash
#SBATCH --job-name=gem_probe
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=00:30:00
#SBATCH --output=/work/home/acxujo26gv/lcoe_gem2025_climate_storage/code/logs/gem_probe-%j.log
#SBATCH --error=/work/home/acxujo26gv/lcoe_gem2025_climate_storage/code/logs/gem_probe-%j.log
set -euo pipefail
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/acxujo26gv/lcoe_gem2025_climate_storage/code
python -m scnet.lcoe_gem2025.probe
