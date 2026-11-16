#!/usr/bin/env bash
#SBATCH --job-name=create_jobs
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=12:00:00
#SBATCH --output=/work/home/acxujo26gv/dispatch_2025_climate_storage/code/logs/dispatch_2025/create_jobs-%j.log
#SBATCH --error=/work/home/acxujo26gv/dispatch_2025_climate_storage/code/logs/dispatch_2025/create_jobs-%j.log
set -euo pipefail
umask 0022
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd /work/home/acxujo26gv/dispatch_2025_climate_storage/code
source .venv/bin/activate
python -m scnet.create_dispatch_2025_jobs "$@"
