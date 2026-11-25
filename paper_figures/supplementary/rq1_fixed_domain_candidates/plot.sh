#!/bin/bash
#SBATCH --job-name=rq1_fixed_domain
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3500M
#SBATCH --time=00:15:00
#SBATCH --output=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/rq1_fixed_domain_candidates/plot_%j.out
#SBATCH --error=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/rq1_fixed_domain_candidates/plot_%j.out
set -euo pipefail
PROJECT_ROOT=/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind
if ! printenv SLURM_JOB_ID >/dev/null; then
    mkdir -p "$PROJECT_ROOT/logs/paper_figures/rq1_fixed_domain_candidates"
    exec sbatch "$0" "$@"
fi
source "$PROJECT_ROOT/.venv/bin/activate"
cd "$PROJECT_ROOT"
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python paper_figures/supplementary/rq1_fixed_domain_candidates/plot.py "$@"
