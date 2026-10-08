#!/bin/bash
#SBATCH --job-name=fig04_decades
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=14000M
#SBATCH --time=00:45:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig04/counterfactual_decades_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig04/counterfactual_decades_%j.out
set -euo pipefail
source /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/.venv/bin/activate
cd /work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg
export MPLCONFIGDIR=$PWD/paper_figures/main/fig04_climate_deployment/outputs/.mplconfig
mkdir -p "$MPLCONFIGDIR"
python -m paper_figures.main.fig04_climate_deployment.plot_counterfactual_decades "$@"
