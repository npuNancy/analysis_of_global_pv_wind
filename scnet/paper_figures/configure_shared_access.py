"""Grant assigned accounts ACL access to their output, log, and state directories."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from paper_figures.config import ROOT,OUTPUT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path,nargs='?');p.add_argument('--apply',action='store_true');a=p.parse_args()
    status=ROOT/'logs/paper_figures/completion_status'
    if a.manifest is None:a.manifest=Path(json.loads((status/'multi_account.json').read_text())['manifest'])
    m=json.loads(a.manifest.read_text());users=[r['username'] for r in m['accounts']]
    if subprocess.check_output(['id','-un'],text=True).strip()!=m['coordinator']:raise PermissionError('ACL setup must run as coordinator')
    targets={}
    for account in m['accounts']:
        user=account['username']
        for folder in [a.manifest.parent/'accounts'/user,status/'accounts'/user,ROOT/'logs/paper_figures/prepare'/user]:targets[folder]=user
    state=json.loads((a.manifest.parent/'state.json').read_text())
    for u in m['units']:
        if state[u['unit']]['job_id']:continue
        folder=Path(u['marker']).parent
        if OUTPUT not in folder.parents:raise ValueError('Output outside preparation root')
        if folder.exists() and any(folder.iterdir()):raise FileExistsError('Unsubmitted unit already has outputs: '+str(folder))
        targets[folder]=u['account']
    print('ACL directories',len(targets))
    if not a.apply:return
    for folder,writer in targets.items():
        folder.mkdir(parents=True,exist_ok=True)
        paths=[folder,*folder.rglob('*')]
        for path in paths:
            if path.is_symlink():raise ValueError('ACL target is a symlink')
            if path.stat().st_uid!=os.getuid():raise PermissionError('ACL target is not coordinator-owned')
            directory=path.is_dir();read='r-x' if directory else 'r--';write='rwx' if directory else 'rw-'
            entries=['u::'+write,'g::---','o::---','m::'+write]
            entries += ['u:'+user+':'+(write if user in [writer,m['coordinator']] else read) for user in users]
            subprocess.run(['setfacl','-m',','.join(entries),str(path)],check=True)
            if directory:
                defaults=['u::rwx','g::---','o::---','m::rwx']+['u:'+user+':'+('rwx' if user in [writer,m['coordinator']] else 'r-x') for user in users]
                subprocess.run(['setfacl','-d','-m',','.join(defaults),str(path)],check=True)

if __name__=='__main__':main()
