#!/usr/bin/env bash
#SBATCH --job-name=d25_loss
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=12:00:00
#SBATCH --output=/work/home/acxujo26gv/dispatch_2025_climate_storage/code/logs/dispatch_2025/loss-%j.log
#SBATCH --error=/work/home/acxujo26gv/dispatch_2025_climate_storage/code/logs/dispatch_2025/loss-%j.log
set -euo pipefail
umask 0022
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd /work/home/acxujo26gv/dispatch_2025_climate_storage/code
source .venv/bin/activate
python -m utils.dispatch_station_climate.loss "$@"
