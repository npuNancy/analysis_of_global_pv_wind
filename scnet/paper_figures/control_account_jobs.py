"""One controller per account; shared outputs and dependency state on Wuzhen1866."""
import argparse
from collections import Counter
import fcntl
import errno
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from datetime import datetime
from paper_figures.config import ROOT
from paper_figures.common.io import write_json,require_complete

STATUS=ROOT/'logs/paper_figures/completion_status'
TERMINAL=('FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','REVOKED')


def command(args):
    p=subprocess.run(args,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(shlex.join(args)+': '+p.stderr.strip())
    return p.stdout


def read_state(path):
    for attempt in range(10):
        try:return json.loads(Path(path).read_text())
        except (OSError,json.JSONDecodeError) as exc:
            if isinstance(exc,OSError) and not isinstance(exc,FileNotFoundError) and exc.errno not in (errno.EIO,errno.ESTALE,errno.EAGAIN,errno.ETIMEDOUT):raise
            if attempt==9:raise RuntimeError('Shared state temporarily unavailable: '+str(path)) from exc
            time.sleep(.1*(attempt+1))


def verify_outputs(folder):
    for attempt in range(10):
        try:return require_complete(folder)
        except (OSError,json.JSONDecodeError,ValueError) as exc:
            if isinstance(exc,OSError) and not isinstance(exc,FileNotFoundError) and exc.errno not in (errno.EIO,errno.ESTALE,errno.EAGAIN,errno.ETIMEDOUT):raise
            if attempt==9:raise
            time.sleep(.1*(attempt+1))


def read_states(manifest):
    result={};base=Path(manifest['job_dir'])/'accounts'
    for a in manifest['accounts']:result.update(read_state(base/a['username']/'state.json'))
    return result


def write_progress(path,manifest,state,notes=()):
    counts=dict(Counter(r['classification'] for r in state.values()));now=datetime.now().astimezone().isoformat()
    lines=['# Paper figures preparation','',f'Last checked: {now}','',f"Manifest: {manifest['job_dir']}/jobs.json",'',json.dumps(counts),'',*notes,'','| Unit | Account | Job ID | Classification | Slurm | Exit | Elapsed | MaxRSS | Attempt | Evidence / next action |','|---|---|---|---|---|---|---|---|---|---|']
    for name,r in state.items():
        vals=[name,r.get('account',''),r['job_id'],r['classification'],r['state'],r['exit'],r['elapsed'],r['maxrss'],r['attempt'],r['reason']]
        lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in vals)+' |')
    tmp=path.with_name(path.name+f'.{os.getpid()}.tmp');tmp.write_text('\n'.join(lines)+'\n');tmp.replace(path)
    return counts


def active_jobs(user):
    return {r.split('|')[0]:r.split('|')[1] for r in command(['squeue','-h','-u',user,'-o','%i|%T']).splitlines()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path,nargs='?');p.add_argument('--submit',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=900);a=p.parse_args()
    if a.interval<30:p.error('Minimum interval is 30 seconds')
    if a.manifest is None:a.manifest=Path(json.loads((STATUS/'multi_account.json').read_text())['manifest'])
    m=json.loads(a.manifest.read_text());user=command(['id','-un']).strip()
    account=next((x for x in m['accounts'] if x['username']==user),None)
    if account is None:raise ValueError('Execution user is not an assigned account')
    require_complete(Path(m['prerequisite']).parent)
    folder=a.manifest.parent/'accounts'/user;status=STATUS/'accounts'/user
    lock=(status/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    statepath=folder/'state.json';state=read_state(statepath);units=[u for u in m['units'] if u['account']==user]
    Path(status/'controller.pid').write_text(str(os.getpid())+'\n');Path(status/'controller.host').write_text(command(['hostname']))
    shared=Path(account['submit_lock']);shared.parent.mkdir(parents=True,exist_ok=True)
    failures=[];notes=[]
    def persist():
        write_json(statepath,state);counts=write_progress(status/'progress.md',m,state,notes)
        write_progress(folder/'progress.md',m,state,notes)
        if user==m['coordinator']:
            try:combined=read_states(m)
            except RuntimeError as exc:print('Global snapshot deferred:',exc,flush=True)
            else:
                write_json(a.manifest.parent/'state.json',combined)
                write_progress(STATUS/'progress.md',m,combined,notes);write_progress(a.manifest.parent/'progress.md',m,combined,notes)
        print(datetime.now().astimezone().isoformat(),user,counts,flush=True)
    while True:
        notes=[]
        try:
            active=active_jobs(user);ids=[r['job_id'] for r in state.values() if r['job_id'] and r['classification'] not in ('succeeded','failed','incomplete_output')];accounting={}
            if ids:
                for line in command(['sacct','-j',','.join(ids),'-n','-P','--format=JobID,State,ExitCode,Elapsed,MaxRSS']).splitlines():
                    cells=line.split('|')
                    if len(cells)>=5:accounting[cells[0]]=cells
            for u in units:
                r=state[u['unit']];job=r['job_id']
                if not job or r['classification'] in ('succeeded','failed','incomplete_output'):continue
                if job in active:r.update(classification='active',state=active[job],reason='wait for terminal accounting');continue
                fact=accounting.get(job)
                if not fact:r.update(classification='unknown',reason='accounting not yet available');continue
                batch=accounting.get(job+'.batch',fact);r.update(state=fact[1],exit=fact[2],elapsed=fact[3],maxrss=batch[4])
                if fact[1]=='COMPLETED' and fact[2]=='0:0':
                    try:verify_outputs(Path(u['marker']).parent)
                    except Exception as e:r.update(classification='incomplete_output',reason=str(e))
                    else:r.update(classification='succeeded',reason='COMPLETED/0:0 and completion artifacts verified')
                elif fact[1].startswith(TERMINAL):
                    log=Path(u['log_pattern'].replace('%j',job));tail=' / '.join(log.read_text(errors='replace').splitlines()[-5:]) if log.exists() else ''
                    r.update(classification='failed',reason=tail or fact[1])
            write_json(statepath,state);allstate=read_states(m)
            failures=[k for k,r in allstate.items() if r['classification'] in ('failed','incomplete_output')]
            if failures:notes.append('Failed branches blocked: '+', '.join(failures[:10]))
            if a.submit:
                ready=[u for u in units if not state[u['unit']]['job_id'] and state[u['unit']]['classification'] not in ('submission_failed','submission_unknown') and all(allstate[d]['classification']=='succeeded' for d in u['dependencies'])]
                ready.sort(key=lambda u:(0 if 'summary' in u['unit'] or u['unit'].startswith('panels') else 1 if u['unit'].startswith('events_') else 2,u['unit']))
                with shared.open('a') as f:
                    for attempt in range(20):
                        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                        except BlockingIOError:
                            if attempt==19:raise RuntimeError('Submission lock unavailable')
                            time.sleep(.5)
                    known_active=set(active)
                    for u in ready:
                        # Include newly acknowledged IDs during squeue visibility delay.
                        current=active_jobs(user);known_active.update(current)
                        if len(known_active)>=account.get('max_active',20):break
                        r=state[u['unit']]
                        result=subprocess.run(['sbatch','--parsable',u['script']],text=True,capture_output=True)
                        if result.returncode:
                            error=result.stderr.strip();r['submit_errors']=r.get('submit_errors',0)+1;r['reason']=error
                            transient=any(token in error.lower() for token in ['qosmax','maximum number of jobs','job violates accounting/qos policy','temporarily unavailable','socket timed out','connection refused','unable to contact slurm'])
                            ambiguous=any(token in error.lower() for token in ['socket timed out','unable to contact slurm'])
                            if ambiguous:r['classification']='submission_unknown'
                            elif not transient or r['submit_errors']>=3:r['classification']='submission_failed'
                            notes.append('Submission deferred: '+error);write_json(statepath,state);break
                        job=result.stdout.strip().split(';')[0]
                        if not job.isdigit():
                            r.update(classification='submission_unknown',reason='Unexpected sbatch response: '+result.stdout.strip());write_json(statepath,state);break
                        r.update(job_id=job,attempt=r['attempt']+1,classification='active',state='SUBMITTED',reason='waiting for execution');known_active.add(job);write_json(statepath,state)
            persist()
        except (RuntimeError,subprocess.SubprocessError) as e:
            notes.append('Scheduler observation error: '+str(e));persist()
        try:allstate=read_states(m)
        except RuntimeError as exc:
            print('Dependency snapshot deferred:',exc,flush=True);allstate=None
        local_done=all(r['classification'] in ('succeeded','failed','incomplete_output','submission_failed','submission_unknown') for r in state.values())
        if not a.watch or (local_done and (user!=m['coordinator'] or (allstate is not None and all(r['classification'] in ('succeeded','failed','incomplete_output','submission_failed','submission_unknown') for r in allstate.values())))):break
        time.sleep(a.interval)
    lock.close()

if __name__=='__main__':main()
