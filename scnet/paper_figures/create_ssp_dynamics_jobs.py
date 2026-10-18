"""Generate the SSP grid dynamics fan-out and reduction jobs; never submits."""
import argparse
import json
import shlex
from pathlib import Path
from paper_figures.config import ROOT
from paper_figures.common.io import write_json
from paper_figures.main.fig01_extreme_events.prepare_ssp_dynamics import OUT

def shell(module, arguments, job, cpus, hours, log):
    return f"""#!/bin/bash
#SBATCH --job-name={job}
#SBATCH --partition=wzhctest
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={cpus*3500}M
#SBATCH --time={hours}
#SBATCH --output={log}
#SBATCH --error={log}
set -euo pipefail
cd {shlex.quote(str(ROOT))}
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m {module} {shlex.join(arguments)}
"""

def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--job-dir",type=Path,default=ROOT.parents[1]/"runtime/ssp_dynamics_jobs/20261018")
    p.add_argument("--output-root",type=Path,default=OUT)
    p.add_argument("--batches",type=int,default=20)
    p.add_argument("--workers",type=int,default=16)
    p.add_argument("--dry-run",action="store_true")
    a=p.parse_args()
    if not 1 <= a.batches <= 1128 or not 1 <= a.workers <= 16:p.error("Invalid resource dimensions")
    units=[]
    logs=ROOT/"logs/paper_figures/ssp_dynamics"
    for i in range(a.batches):
        unit=f"dynamics_{i:03d}"
        path=a.job_dir/(unit+".sh")
        log=logs/(unit+"_%j.out")
        args=["--batch",str(i),"--batches",str(a.batches),"--workers",str(a.workers),"--output-root",str(a.output_root)]
        units.append(dict(unit=unit,script=str(path),dependencies=[],log_pattern=str(log),
                          marker=str(a.output_root/"batches"/f"{i:03d}"/"complete.json")))
        if not a.dry_run:
            path.parent.mkdir(parents=True,exist_ok=True)
            content=shell("paper_figures.main.fig01_extreme_events.prepare_ssp_dynamics",args,unit,a.workers,"12:00:00",log)
            if path.exists() and path.read_text()!=content:raise ValueError(f"Script collision: {path}")
            path.write_text(content)
    unit="dynamics_summary";path=a.job_dir/(unit+".sh");log=logs/(unit+"_%j.out")
    units.append(dict(unit=unit,script=str(path),dependencies=[u["unit"] for u in units],
                      log_pattern=str(log),marker=str(a.output_root/"summary/complete.json")))
    if not a.dry_run:
        content=shell("paper_figures.main.fig01_extreme_events.summarize_ssp_dynamics",
                      ["--output-root",str(a.output_root)],unit,8,"04:00:00",log)
        if path.exists() and path.read_text()!=content:raise ValueError(f"Script collision: {path}")
        path.write_text(content);logs.mkdir(parents=True,exist_ok=True)
        write_json(a.job_dir/"jobs.json",dict(prerequisite=str(a.output_root/"pilot_fast/validation/complete.json"),
                   units=units,output_root=str(a.output_root),batches=a.batches,workers=a.workers))
    print(json.dumps(dict(total_jobs=len(units),raw_tasks=1128,batches=a.batches,workers=a.workers,dry_run=a.dry_run)))
if __name__=="__main__":
    main()
