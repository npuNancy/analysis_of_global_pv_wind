"""Generate separately visible LCOE station extraction jobs; never submit."""
import argparse
import json
from pathlib import Path
import re
import shlex


def generate(config,tasks,stage,job_dir,dry_run=False,cpus=None):
    root=Path(config['root']);repo=Path(config['repo']);jobs=[]
    for path in [root,repo,job_dir,Path(config['activate'])]:
        if not path.is_absolute() or any(c.isspace() for c in str(path)):raise ValueError('Absolute whitespace-free paths required')
    units=tasks if stage=='run' else [{'unit':stage}]
    if len({u['unit'] for u in units})!=len(units):raise ValueError('Duplicate job identities')
    for unit in units:
        name=unit['unit']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Unsafe unit')
        path=job_dir/(name+'.sh')
        command=['python','-m','utils.lcoe_station_climate.pipeline','--root',str(root),'--stage',stage]
        if stage=='run':command+=['--unit',name]
        elif stage=='prepare':command+=['--config',str(repo/'scnet/lcoe_station_climate/campaign.json')]
        cores=cpus or config['cpus']
        if cores<1:raise ValueError('cpus must be positive')
        log=root/'logs'/(name+'-%j.log')
        body=f'''#!/usr/bin/env bash
#SBATCH --job-name=lcs_{name}
#SBATCH --partition={config['partition']}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cores}
#SBATCH --time=12:00:00
#SBATCH --output={log}
#SBATCH --error={log}
set -euo pipefail
umask 0022
export LC_ALL=C LANG=C PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
source {shlex.quote(config['activate'])}
cd {shlex.quote(str(repo))}
mkdir -p {shlex.quote(str(root/'logs'))}
{shlex.join(command)}
'''
        if not dry_run:
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists() and path.read_text()!=body:raise FileExistsError(path)
            path.write_text(body)
        jobs.append(dict(unit=name,script=str(path),stage=stage))
    return jobs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path(__file__).parent/'lcoe_station_climate/campaign.json')
    p.add_argument('--tasks',type=Path);p.add_argument('--stage',choices=['prepare','run','finalize'],default='run')
    p.add_argument('--job-dir',type=Path);p.add_argument('--dry-run',action='store_true');p.add_argument('--cpus',type=int)
    p.add_argument('--products',nargs='+');p.add_argument('--models',nargs='+');p.add_argument('--climate-ssps',nargs='+');p.add_argument('--techs',nargs='+');p.add_argument('--patches',nargs='+')
    a=p.parse_args();cfg=json.loads(a.config.read_text());root=Path(cfg['root'])
    tasks=json.loads((a.tasks or root/'runtime/tasks.json').read_text()) if a.stage=='run' else []
    for attr,key in [('products','product'),('models','model'),('climate_ssps','climate_ssp'),('techs','tech'),('patches','patch')]:
        values=getattr(a,attr)
        if values:tasks=[t for t in tasks if t[key] in values]
    if a.stage=='run' and not tasks:raise ValueError('No selected tasks')
    jobs=generate(cfg,tasks,a.stage,a.job_dir or root/'jobs',a.dry_run,a.cpus)
    print(json.dumps({'stage':a.stage,'jobs':len(jobs),'dry_run':a.dry_run}))
if __name__=='__main__':main()
