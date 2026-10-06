#!/bin/bash
#SBATCH --job-name=fig05_plot
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=7000M
#SBATCH --time=00:30:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig05/plot_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/fig05/plot_%j.out
set -euo pipefail
project_root=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
mkdir -p "$project_root/logs/paper_figures/fig05"
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    exec sbatch --wait "$0" "$@"
fi
cd "$project_root"
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLBACKEND=Agg
export MPLCONFIGDIR="$project_root/paper_figures/main/fig05_residual_loss/outputs/.mplconfig"
mkdir -p "$MPLCONFIGDIR"
python -m paper_figures.main.fig05_residual_loss.plot "$@"
