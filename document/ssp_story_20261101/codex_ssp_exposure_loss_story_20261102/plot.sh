#!/bin/bash
#SBATCH --job-name=ssp-story-figures
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=00:20:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/ssp_story_figures_%j.log
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/ssp_story_figures_%j.log

set -euo pipefail

repo=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
mkdir -p "$repo/logs"
cd "$repo"
source .venv/bin/activate
python document/ssp_story_20261101/codex_ssp_exposure_loss_story_20261102/plot.py
