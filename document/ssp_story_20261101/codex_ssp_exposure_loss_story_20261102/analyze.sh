#!/bin/bash
#SBATCH --job-name=ssp_story
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=00:30:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/ssp_story/ssp_story_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/ssp_story/ssp_story_%j.out
set -euo pipefail
REPO=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
mkdir -p "$REPO/logs/paper_figures/ssp_story"
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    exec sbatch "$0" "$@"
fi
source "$REPO/.venv/bin/activate"
cd "$REPO"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python document/ssp_story_20261101/codex_ssp_exposure_loss_story_20261102/analyze.py "$@"
