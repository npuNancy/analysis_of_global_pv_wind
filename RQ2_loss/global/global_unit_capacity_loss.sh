#!/bin/bash
#SBATCH --job-name=rq2_loss_global_unit_loss
#SBATCH --partition=wzhctest
#SBATCH -N 1
#SBATCH --ntasks=1
# Eight worker processes at 3.5 GB per core; the Python reader is single-threaded per worker.
#SBATCH --cpus-per-task=8
#SBATCH --mem=28G
#SBATCH --output=/data6/yanxiaokai/project_climate/analysis_of_global_pv_wind/logs/RQ2_loss/global/global_unit_capacity_loss_%j.out
#SBATCH --error=/data6/yanxiaokai/project_climate/analysis_of_global_pv_wind/logs/RQ2_loss/global/global_unit_capacity_loss_%j.out

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

mkdir -p "$REPO_ROOT/logs/RQ2_loss/global"
cd "$REPO_ROOT"

python RQ2_loss/global/global_unit_capacity_loss.py
