#!/bin/bash
#SBATCH --job-name=data_access_build_cf_grid_index
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7G
#SBATCH --time=00:30:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/data_access/build_cf_grid_index_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/data_access/build_cf_grid_index_%j.log

set -euo pipefail

# Submit from the checkout so the log directory exists before Slurm opens it.
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
    export DATA_ACCESS_REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/../.." && pwd)"
    mkdir -p "$DATA_ACCESS_REPO_ROOT/logs/data_access"
    LOG_PATH="$DATA_ACCESS_REPO_ROOT/logs/data_access/build_cf_grid_index_%j.log"
    exec sbatch --chdir="$DATA_ACCESS_REPO_ROOT" --output="$LOG_PATH" --error="$LOG_PATH" "$SCRIPT_PATH" "$@"
fi

REPO_ROOT="${DATA_ACCESS_REPO_ROOT:-${SLURM_SUBMIT_DIR:-/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind}}"
source "$REPO_ROOT/.venv/bin/activate"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$REPO_ROOT"
python utils/data_access/build_cf_grid_index.py "$@"
