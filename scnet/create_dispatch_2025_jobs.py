"""Generate dispatch-2025 jobs from prepared tasks; never submit."""
import argparse
import json
from pathlib import Path
import shlex
from scnet.create_lcoe_station_climate_jobs import generate

ROOT = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage")

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--root", type=Path, default=ROOT/"future")
    p.add_argument("--module", default="utils.lcoe_station_climate.pipeline")
    p.add_argument("--cpus", type=int)
    p.add_argument("--job-dir", type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--units", nargs="+")
    a = p.parse_args()
    cfg = json.loads((a.root/"inputs/campaign.json").read_text())
    tasks = json.loads((a.root/"runtime/tasks.json").read_text())
    if a.units:
        tasks = [t for t in tasks if t["unit"] in a.units]
    if not tasks:
        raise ValueError("No selected tasks")
    jobs = generate(cfg, tasks, "run", a.job_dir or Path(cfg.get("job_dir",a.root/"jobs")), True, a.cpus)
    for task, job in zip(tasks, jobs):
        cores = a.cpus or cfg["cpus"]
        log = Path(cfg["repo"])/"logs/dispatch_2025"/a.root.name/(task["unit"]+"-%j.log")
        cmd = ["python", "-m", a.module, "--root", str(a.root), "--stage", "run", "--unit", task["unit"]]
        body = f"""#!/usr/bin/env bash
#SBATCH --job-name=d25_{task['unit']}
#SBATCH --partition={cfg['partition']}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cores}
#SBATCH --time=12:00:00
#SBATCH --output={log}
#SBATCH --error={log}
set -euo pipefail
umask 0022
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd {shlex.quote(cfg['repo'])}
source .venv/bin/activate
{shlex.join(cmd)}
"""
        if not a.dry_run:
            log.parent.mkdir(parents=True, exist_ok=True)
            path = Path(job["script"])
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_text() != body:
                raise FileExistsError(path)
            path.write_text(body)
    print(json.dumps(dict(jobs=len(jobs), cpus=a.cpus or cfg["cpus"], dry_run=a.dry_run)))

if __name__ == "__main__":
    main()
