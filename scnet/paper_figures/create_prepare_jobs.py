"""Generate a preparation DAG without submitting or reading scientific arrays."""
import argparse
import itertools
import json
import shlex
from pathlib import Path
from datetime import datetime
from paper_figures.config import ROOT,OUTPUT,MODELS,SSPS,TECHS,SNAPSHOTS,INDEXES

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job-dir',type=Path,default=ROOT.parent.parent/'runtime/paper_figures_jobs'/datetime.now().strftime('%Y%m%d_%H%M%S'))
    p.add_argument('--output-root',type=Path,default=OUTPUT)
    p.add_argument('--models',nargs='+',choices=MODELS,default=list(MODELS));p.add_argument('--climate-ssps',nargs='+',choices=SSPS,default=list(SSPS));p.add_argument('--station-ssps',nargs='+',choices=SSPS,default=list(SSPS));p.add_argument('--techs',nargs='+',choices=TECHS,default=list(TECHS));p.add_argument('--snapshots',nargs='+',type=int,choices=SNAPSHOTS,default=list(SNAPSHOTS));p.add_argument('--patches',nargs='+');p.add_argument('--event-runs',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    idx=json.loads(INDEXES['extreme_grid'].read_text());valid=sorted({r['patch'] for r in idx['combinations'].values()});a.patches=a.patches or valid
    for key in ['models','climate_ssps','station_ssps','techs','snapshots','patches']:
        v=getattr(a,key)
        if not v or len(set(v))!=len(v):p.error('Empty or duplicate '+key)
    if set(a.patches)-set(valid):p.error('Unknown patch')
    a.job_dir=a.job_dir.expanduser().resolve();a.output_root=a.output_root.expanduser().resolve()
    if a.job_dir==ROOT or ROOT in a.job_dir.parents:p.error('Generated jobs must be outside the checkout')
    base=['--output-root',str(a.output_root),'--models',*a.models,'--climate-ssps',*a.climate_ssps,'--snapshots',*map(str,a.snapshots)]
    figures=ROOT/'paper_figures' if a.output_root==OUTPUT else a.output_root/'figures'
    jobs=[]
    def add(name,module,args,deps,marker,cpus,hours):
        log=ROOT/'logs/paper_figures/prepare'/f'{name}_%j.out'
        command=['python','-m',module,*args]
        text='\n'.join(['#!/bin/bash',f'#SBATCH --job-name=pf_{name}', '#SBATCH --partition=wzhctest','#SBATCH --nodes=1','#SBATCH --ntasks=1',f'#SBATCH --cpus-per-task={cpus}',f'#SBATCH --mem={cpus*3500}M',f'#SBATCH --time={hours}:00:00',f'#SBATCH --output={log}',f'#SBATCH --error={log}','set -euo pipefail',f'cd {shlex.quote(str(ROOT))}','source .venv/bin/activate','export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1',shlex.join(command),''])
        jobs.append(dict(unit=name,script=str(a.job_dir/(name+'.sh')),dependencies=deps,marker=str(marker),cpus=cpus,text=text,log_pattern=str(log)))
    # Catalogue data has its own submitted/verified acceptance gate.
    prerequisite=a.output_root/'catalogues/complete.json'
    for s,t,patch in itertools.product(a.station_ssps,a.techs,a.patches):
        args=[*base,'--station-ssps',s,'--techs',t,'--patches',patch];unit=f'loss_{s}_{t}_{patch}'
        add(unit,'paper_figures.prepare.prepare_loss_tables',args,[],a.output_root/'loss_shards'/s/t/patch/'complete.json',12,48)
        add(f'events_{s}_{t}_{patch}','paper_figures.prepare.prepare_event_tables',args+(['--event-runs'] if a.event_runs else []),[unit],a.output_root/'station_events'/s/t/patch/'complete.json',12,72)
    for t,patch in itertools.product(a.techs,a.patches):
        add(f'grid_{t}_{patch}','paper_figures.prepare.prepare_grid_events',[*base,'--techs',t,'--patches',patch],[],a.output_root/'grid_events'/t/patch/'complete.json',4,6)
    allargs=[*base,'--station-ssps',*a.station_ssps,'--techs',*a.techs,'--patches',*a.patches]
    for stage,prefix in [('loss','loss_'),('events','events_')]:
        name=stage+'_summary';deps=[j['unit'] for j in jobs if j['unit'].startswith(prefix)]
        add(name,'paper_figures.prepare.summarize_tables',[*allargs,'--stage',stage],deps,a.output_root/('loss_summary' if stage=='loss' else 'event_summary')/'complete.json',16,8)
        add('panels_'+stage,'paper_figures.prepare.prepare_panel_tables',[*allargs,'--stage',stage,'--figure-root',str(figures)],[name],a.output_root/('panel_loss' if stage=='loss' else 'panel_events')/'complete.json',8,2)
    add('grid_summary','paper_figures.prepare.summarize_grid',[*allargs,'--figure-root',str(figures)],[j['unit'] for j in jobs if j['unit'].startswith('grid_')],a.output_root/'grid_summary/complete.json',4,2)
    add('acceptance','paper_figures.prepare.validate_preparation',allargs,['panels_loss','panels_events','grid_summary'],a.output_root/'acceptance/complete.json',16,4)
    summary=dict(jobs=len(jobs),patches=len(a.patches),loss_shards=sum(j['unit'].startswith('loss_') for j in jobs)-1,event_shards=sum(j['unit'].startswith('events_') for j in jobs)-1,grid_shards=len(a.techs)*len(a.patches),job_dir=str(a.job_dir),output_root=str(a.output_root))
    print(json.dumps(summary))
    if a.dry_run:return
    configuration={k:getattr(a,k) for k in ['models','climate_ssps','station_ssps','techs','snapshots','patches','event_runs']}
    contract=a.output_root/'campaign.json'
    if contract.exists() and json.loads(contract.read_text())!=configuration:raise ValueError('Existing output root belongs to a different campaign')
    if a.job_dir.exists():raise FileExistsError(a.job_dir)
    a.output_root.mkdir(parents=True,exist_ok=True)
    contract.write_text(json.dumps(configuration,indent=2)+'\n')
    a.job_dir.mkdir(parents=True)
    for j in jobs:Path(j['script']).write_text(j.pop('text'))
    (a.job_dir/'jobs.json').write_text(json.dumps(dict(**summary,prerequisite=str(prerequisite),configuration={k:getattr(a,k) for k in ['models','climate_ssps','station_ssps','techs','snapshots','patches','event_runs']},units=jobs),indent=2)+'\n')
if __name__=='__main__':main()
