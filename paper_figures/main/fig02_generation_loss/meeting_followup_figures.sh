#!/bin/bash
#SBATCH --job-name=meeting_followup
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig02/meeting_followup_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig02/meeting_followup_%j.out

set -euo pipefail
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
python -m paper_figures.main.fig02_generation_loss.meeting_followup_figures
