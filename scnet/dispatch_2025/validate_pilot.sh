#!/usr/bin/env bash
#SBATCH --job-name=d25_validate_loss
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=01:00:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/dispatch_2025/validate_pilot-%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/dispatch_2025/validate_pilot-%j.log
set -euo pipefail
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
source .venv/bin/activate
python -m scnet.dispatch_2025.validate_pilot "$@"
