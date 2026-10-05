"""Assign only unsubmitted preparation units to shared-filesystem accounts."""
import argparse
from collections import Counter, defaultdict
import copy
import fcntl
import json
from pathlib import Path
import re
from paper_figures.config import ROOT, OUTPUT
from paper_figures.common.io import write_json


def assign_units(units, state, accounts, coordinator):
    users=[a['username'] for a in accounts]
    if coordinator not in users or len(users)!=len(set(users)):
        raise ValueError('Coordinator must be listed; accounts must be unique')
    assigned={};load=Counter({u:0 for u in users});groups=defaultdict(list)
    for unit in units:
        key=unit['unit'];r=state[key]
        if r['job_id']:
            assigned[key]=coordinator
            if r['classification']!='succeeded':load[coordinator]+=3 if key.startswith('events_') else 1
        elif key.startswith(('loss_ssp','events_ssp')):
            groups[key.split('_',1)[1]].append(key)
        else:assigned[key]=coordinator
    for key,names in sorted(groups.items()):
        owner=min(users,key=lambda u:(load[u],users.index(u)))
        for name in names:
            assigned[name]=owner;load[owner]+=3 if name.startswith('events_') else 1
    return assigned


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--accounts',type=Path,required=True)
    p.add_argument('--job-dir',type=Path,required=True);p.add_argument('--coordinator',default=ROOT.parts[3])
    p.add_argument('--workers',type=int,default=16);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    if a.workers<1:p.error('Positive workers required')
    destination=a.job_dir.expanduser().resolve()
    if destination==ROOT or ROOT in destination.parents:p.error('Jobs must live outside checkout')
    old=json.loads(a.source.read_text());state=json.loads((a.source.parent/'state.json').read_text());accounts=json.loads(a.accounts.read_text())
    for row in accounts:
        if not re.fullmatch(r'[a-z0-9_]+',row['username']) or row.get('max_active',20)!=20:p.error('Invalid account / active limit')
    lock=(ROOT/'logs/paper_figures/completion_status/controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (a.source.parent/'distribution.json').exists():raise FileExistsError('Source already distributed')
    assignment=assign_units(old['units'],state,accounts,a.coordinator)
    print(json.dumps(dict(total=len(assignment),pending=sum(not r['job_id'] for r in state.values()),pending_by_account=dict(Counter(assignment[k] for k,r in state.items() if not r['job_id'])))))
    if a.dry_run:return
    destination.mkdir(parents=True,exist_ok=False)
    units=[]
    for source in old['units']:
        u=copy.deepcopy(source);key=u['unit'];owner=assignment[key];u['account']=owner
        if not state[key]['job_id']:
            text=Path(u['script']).read_text();log=ROOT/'logs/paper_figures/prepare'/owner/f'{key}_%j.out'
            text=re.sub(r'(?m)^#SBATCH --cpus-per-task=.*$',f'#SBATCH --cpus-per-task={a.workers}',text)
            text=re.sub(r'(?m)^#SBATCH --mem=.*$',f'#SBATCH --mem={a.workers*3500}M',text)
            for field in ['output','error']:text=re.sub(r'(?m)^#SBATCH --'+field+r'=.*$',f'#SBATCH --{field}={log}',text)
            text=text.replace('set -euo pipefail','set -euo pipefail\numask 0022\nexport PYTHONDONTWRITEBYTECODE=1')
            if key.startswith(('loss_ssp','events_ssp')):
                text=re.sub(r'(?m)^(python -m paper_figures.prepare.prepare_(?:loss|event)_tables .*)$',lambda m:m.group(1)+f' --workers {a.workers}'+(' --parallel-snapshots' if key.startswith('events_') else ''),text)
            target=destination/(key+'.sh');target.write_text(text);u.update(script=str(target),cpus=a.workers,log_pattern=str(log))
        units.append(u)
    manifest=dict(old,units=units,accounts=accounts,coordinator=a.coordinator,source_manifest=str(a.source.resolve()),job_dir=str(destination),workers=a.workers)
    write_json(destination/'jobs.json',manifest)
    for row in accounts:
        own={k:dict(v,account=assignment[k]) for k,v in state.items() if assignment[k]==row['username']}
        write_json(destination/'accounts'/row['username']/'state.json',own)
    write_json(destination/'state.json',{k:dict(v,account=assignment[k]) for k,v in state.items()})
    write_json(a.source.parent/'distribution.json',dict(manifest=str(destination/'jobs.json')))
    write_json(ROOT/'logs/paper_figures/completion_status/multi_account.json',dict(manifest=str(destination/'jobs.json')))

if __name__=='__main__':main()
