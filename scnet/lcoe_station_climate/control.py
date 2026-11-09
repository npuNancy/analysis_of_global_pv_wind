"""One locked account monitor/refiller sharing an unassigned extraction task queue."""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


def command(args):return subprocess.check_output(args,text=True,timeout=90).strip()
def read(p):return json.loads(Path(p).read_text())
def write(p,value):
    p=Path(p);tmp=p.with_name(p.name+f'.{os.getpid()}.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(p)
@contextmanager
def locked(path):
    with Path(path).open('a') as f:
        until=time.monotonic()+60
        while True:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>until:raise TimeoutError('Lock '+str(path))
                time.sleep(.2)
        yield


def active(user):return {line.split('|')[0]:line.split('|')[1] for line in command(['squeue','-h','-u',user,'-o','%i|%T']).splitlines()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--submit',action='store_true');p.add_argument('--pilot',nargs='+');p.add_argument('--retry',nargs='*')
    a=p.parse_args();root=a.root;cfg=read(root/'inputs/campaign.json');user=command(['id','-un'])
    account=next(x for x in cfg['accounts'] if x['username']==user)
    tasks=read(root/'runtime/tasks.json');byid={t['unit']:t for t in tasks};statepath=root/'runtime/state.json'
    globallock=root/'runtime/queue.lock';ownlock=root/'runtime'/('controller_'+user+'.lock')
    with locked(ownlock):
        with locked(globallock):
            state=read(statepath) if statepath.exists() else {t['unit']:dict(state='NOT_SUBMITTED',attempt=0) for t in tasks}
            write(statepath,state)
        observed=active(user)
        ours={k:v for k,v in state.items() if v.get('account')==user and v['state'] not in ['SUCCEEDED','FAILED','INCOMPLETE_OUTPUT','DETERMINISTIC_FAILURE']}
        ids=[v['job_id'] for v in ours.values() if v.get('job_id')]
        facts={}
        if ids:
            for offset in range(0,len(ids),200):
                for line in command(['sacct','-j',','.join(ids[offset:offset+200]),'-n','-P','--format=JobID,State,ExitCode,ElapsedRaw,MaxRSS']).splitlines():
                    parts=line.split('|')
                    if len(parts)>=5:facts[parts[0]]=parts
        updates={}
        for key,row0 in ours.items():
            row=dict(row0);jid=row.get('job_id')
            if not jid:continue
            if jid in observed:row.update(state='ACTIVE',scheduler_state=observed[jid])
            elif jid in facts:
                f=facts[jid];row.update(scheduler_state=f[1],exit_code=f[2],elapsed_seconds=int(f[3] or 0),max_rss=facts.get(jid+'.batch',f)[4])
                if f[1]=='COMPLETED' and f[2]=='0:0':
                    marker=Path(byid[key]['marker'])
                    if marker.exists() and read(marker).get('status')=='COMPLETED':row.update(state='SUCCEEDED',evidence='Slurm COMPLETED/0:0 and completion receipt')
                    else:row.update(state='INCOMPLETE_OUTPUT',evidence='Missing completion receipt')
                elif f[1] in ['RUNNING','PENDING','COMPLETING','CONFIGURING']:row['state']='ACTIVE'
                else:
                    row['state']='FAILED';log=root/'logs'/(key+'-'+jid+'.log')
                    row['evidence']=' / '.join(log.read_text(errors='replace').splitlines()[-8:]) if log.exists() else f[1]
            else:row.update(state='UNKNOWN',evidence='Await accounting')
            row['checked_at']=datetime.now().astimezone().isoformat();updates[key]=row
        with locked(globallock):
            state=read(statepath);state.update(updates)
            for key in a.retry or []:
                row=state[key]
                if row.get('account')==user:
                    if row['state'] not in ['FAILED','INCOMPLETE_OUTPUT'] or row['attempt']>=3:raise ValueError('Retry not eligible '+key)
                    row.setdefault('history',[]).append({k:v for k,v in row.items() if k!='history'})
                    row.update(state='NOT_SUBMITTED');row.pop('job_id',None)
            write(statepath,state)
        submitted=[]
        if a.submit:
            if not a.pilot and not (root/'runtime/pilot_accepted.json').exists():raise ValueError('Pilot acceptance required')
            with locked(account['submit_lock']):
                acknowledged=set()
                while True:
                    now_active=active(user)
                    if len(set(now_active)|acknowledged)>=account['max_active']:break
                    with locked(globallock):
                        state=read(statepath)
                        eligible=[t for t in tasks if state[t['unit']]['state']=='NOT_SUBMITTED' and (not a.pilot or t['unit'] in a.pilot)]
                        if not eligible:break
                        # Largest remaining station groups first to reduce a long tail.
                        eligible.sort(key=lambda t:(-t['n_union'],t['unit']))
                        t=eligible[0];key=t['unit'];row=state[key]
                        row.update(state='SUBMITTING',account=user);write(statepath,state)
                    proc=subprocess.run(['sbatch','--parsable',str(root/'jobs'/(key+'.sh'))],text=True,capture_output=True,timeout=90)
                    with locked(globallock):
                        state=read(statepath);row=state[key]
                        if row['state']!='SUBMITTING' or row['account']!=user:raise RuntimeError('Submission claim changed '+key)
                        if proc.returncode:
                            row.update(state='SUBMISSION_FAILED',evidence=proc.stderr.strip());write(statepath,state);break
                        jid=proc.stdout.strip().split(';')[0]
                        if not jid.isdigit():row.update(state='UNKNOWN',evidence='Ambiguous sbatch response');write(statepath,state);break
                        row.update(state='ACTIVE',scheduler_state='SUBMITTED',job_id=jid,attempt=row['attempt']+1,submitted_at=datetime.now().astimezone().isoformat())
                        write(statepath,state);acknowledged.add(jid);submitted.append(jid)
        with locked(globallock):state=read(statepath)
        counts=Counter(v['state'] for v in state.values())
        result=dict(account=user,active=len(active(user)),submitted=submitted,counts=dict(counts),checked_at=datetime.now().astimezone().isoformat())
        write(root/'runtime'/('account_'+user+'.json'),result)
        print(json.dumps(result))
if __name__=='__main__':main()
