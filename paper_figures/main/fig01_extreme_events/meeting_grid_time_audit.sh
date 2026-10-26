#!/bin/bash
#SBATCH --job-name=meeting_grid_audit
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/meeting_grid_audit_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/meeting_grid_audit_%j.log
set -euo pipefail
REPO=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  mkdir -p "$REPO/logs/paper_figures"
  exec sbatch "$REPO/paper_figures/main/fig01_extreme_events/meeting_grid_time_audit.sh"
fi
cd "$REPO"
source .venv/bin/activate
python -m paper_figures.main.fig01_extreme_events.meeting_grid_time_audit
