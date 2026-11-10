"""Generate GEM climate jobs from prepared scientific task manifests."""
import argparse
import json
from pathlib import Path
import shlex

from scnet.create_lcoe_station_climate_jobs import generate


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--root',type=Path,default=Path('/work/home/acxujo26gv/lcoe_gem2025_climate_storage/future'))
    p.add_argument('--module',default='utils.lcoe_station_climate.pipeline')
    p.add_argument('--job-dir',type=Path);p.add_argument('--log-dir',type=Path)
    p.add_argument('--cpus',type=int);p.add_argument('--dry-run',action='store_true')
    p.add_argument('--products',nargs='+');p.add_argument('--models',nargs='+');p.add_argument('--climate-ssps',nargs='+')
    p.add_argument('--techs',nargs='+');p.add_argument('--patches',nargs='+');p.add_argument('--units',nargs='+')
    a=p.parse_args();cfg=json.loads((a.root/'inputs/campaign.json').read_text());tasks=json.loads((a.root/'runtime/tasks.json').read_text())
    for attr,key in [('products','product'),('models','model'),('climate_ssps','climate_ssp'),('techs','tech'),('patches','patch'),('units','unit')]:
        values=getattr(a,attr)
        if values:tasks=[t for t in tasks if t[key] in [v for x in values for v in x.split(',')]]
    if not tasks:raise ValueError('No selected tasks')
    # Reuse the verified scheduler/resource shell contract; this entry never submits.
    jobs=generate(cfg,tasks,'run',a.job_dir or a.root/'jobs',True,a.cpus)
    if not a.dry_run:
        for task,job in zip(tasks,jobs):
            path=Path(job['script']);path.parent.mkdir(parents=True,exist_ok=True)
            cores=a.cpus or cfg['cpus'];log=(a.log_dir or Path(cfg['root'])/'logs')/(task['unit']+'-%j.log')
            cmd=['python','-m',a.module,'--root',cfg['root'],'--stage','run','--unit',task['unit']]
            body=f'''#!/usr/bin/env bash
#SBATCH --job-name=gem_{task['unit']}
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
source {shlex.quote(cfg['activate'])}
cd {shlex.quote(cfg['repo'])}
{shlex.join(cmd)}
'''
            if path.exists() and path.read_text()!=body:raise FileExistsError(path)
            path.write_text(body)
    print(json.dumps(dict(jobs=len(jobs),module=a.module,cpus=a.cpus or cfg['cpus'],dry_run=a.dry_run)))


if __name__=='__main__':main()
