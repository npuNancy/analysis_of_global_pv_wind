#!/bin/bash
#SBATCH --job-name=meeting_icing
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7000M
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/meeting_icing_%A_%a_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/meeting_icing_%A_%a_%j.log
set -euo pipefail
REPO=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
cd "$REPO"
source .venv/bin/activate
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    mkdir -p "$REPO/logs/paper_figures"
    python -m paper_figures.main.fig01_extreme_events.meeting_icing_mechanism --prepare
    exec sbatch --array="0-7%8" "$REPO/paper_figures/main/fig01_extreme_events/meeting_icing_mechanism.sh" "$@"
fi
python -m paper_figures.main.fig01_extreme_events.meeting_icing_mechanism "$@"
