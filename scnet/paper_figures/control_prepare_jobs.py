"""Explicit submit/monitor controller with an account-wide 20-job cap."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime
from paper_figures.config import ROOT
from paper_figures.common.io import write_json,require_complete

def command(args):
    return subprocess.run(args,text=True,capture_output=True,check=True).stdout

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--submit',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=120);p.add_argument('--max-active',type=int,default=20);a=p.parse_args()
    if not 1<=a.max_active<=20 or a.interval<30:p.error('max-active must be 1..20 and interval >=30')
    j=json.loads(a.manifest.read_text());require_complete(Path(j['prerequisite']).parent)
    status=ROOT/'logs/paper_figures/completion_status';status.mkdir(parents=True,exist_ok=True)
    lock=(status/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    statepath=a.manifest.parent/'state.json';state=json.loads(statepath.read_text()) if statepath.exists() else {}
    user=command(['id','-un']).strip();shared=ROOT/'logs/RQ1_extreme/completion_status/submit.lock';shared.parent.mkdir(parents=True,exist_ok=True)
    for unit in j['units']:state.setdefault(unit['unit'],dict(classification='not_submitted',attempt=0,job_id='',state='',exit='',elapsed='',maxrss='',reason=''))
    def persist():
        now=datetime.now().astimezone().isoformat();write_json(statepath,state)
        counts={c:sum(r['classification']==c for r in state.values()) for c in sorted({r['classification'] for r in state.values()})}
        lines=['# Paper figures preparation','',f'Last checked: {now}','',f'Manifest: {a.manifest}', '',json.dumps(counts),'','| Unit | Job ID | Classification | Slurm | Exit | Elapsed | MaxRSS | Attempt | Evidence / next action |','|---|---|---|---|---|---|---|---|---|']
        for name,r in state.items():lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in [name,r['job_id'],r['classification'],r['state'],r['exit'],r['elapsed'],r['maxrss'],r['attempt'],r['reason']])+' |')
        tmp=status/'progress.tmp.md';tmp.write_text('\n'.join(lines)+'\n');tmp.replace(status/'progress.md');(a.manifest.parent/'progress.md').write_text('\n'.join(lines)+'\n');print(now,counts,flush=True)
    while True:
        active={row.split('|')[0]:row.split('|')[1] for row in command(['squeue','-h','-u',user,'-o','%i|%T']).splitlines()}
        ids=[r['job_id'] for r in state.values() if r['job_id'] and r['classification'] not in ('succeeded','failed','incomplete_output')]
        accounting={}
        if ids:
            for row in command(['sacct','-j',','.join(ids),'-n','-P','--format=JobID,State,ExitCode,Elapsed,MaxRSS']).splitlines():
                fields=row.split('|')
                if len(fields)>=5:accounting[fields[0]]=fields
        for unit in j['units']:
            r=state[unit['unit']];job=r['job_id']
            if not job or r['classification']=='succeeded':continue
            if job in active:r.update(classification='active',state=active[job],reason='wait for terminal accounting');continue
            fact=accounting.get(job)
            if not fact:
                if r['classification'] not in ('failed','incomplete_output'):r.update(classification='unknown',reason='accounting not yet available')
                continue
            batch=accounting.get(job+'.batch',fact);r.update(state=fact[1],exit=fact[2],elapsed=fact[3],maxrss=batch[4])
            if fact[1]=='COMPLETED' and fact[2]=='0:0':
                try:require_complete(Path(unit['marker']).parent)
                except Exception as e:r.update(classification='incomplete_output',reason=str(e))
                else:r.update(classification='succeeded',reason='COMPLETED/0:0 and completion artifacts verified')
            elif any(fact[1].startswith(x) for x in ['FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL']):
                log=Path(unit['log_pattern'].replace('%j',job));tail=''
                if log.exists():tail=' / '.join(log.read_text(errors='replace').splitlines()[-4:])
                r.update(classification='failed',reason=tail or 'inspect log; no automatic retry')
        failures=any(r['classification'] in ('failed','incomplete_output') for r in state.values())
        if a.submit and not failures:
            # Give released reductions and event shards priority; each writer owns one unit.
            ready=[u for u in j['units'] if not state[u['unit']]['job_id'] and all(state[d]['classification']=='succeeded' for d in u['dependencies'])]
            ready.sort(key=lambda u:(0 if 'summary' in u['unit'] or u['unit'].startswith('panels') else 1 if u['unit'].startswith('events_') else 2,u['unit']))
            with shared.open('a') as f:
                acquired=False
                for _ in range(20):
                    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);acquired=True;break
                    except BlockingIOError:time.sleep(.5)
                if not acquired:raise RuntimeError('Shared submission lock unavailable')
                for unit in ready:
                    count=len(command(['squeue','-h','-u',user,'-o','%i']).splitlines())
                    if count>=a.max_active:break
                    job=command(['sbatch','--parsable',unit['script']]).strip().split(';')[0]
                    if not job.isdigit():raise ValueError('Unexpected sbatch response')
                    r=state[unit['unit']];r.update(job_id=job,attempt=r['attempt']+1,classification='active',state='SUBMITTED',reason='waiting for execution')
                    write_json(statepath,state)
        persist()
        if failures:raise SystemExit('Preparation branch failed; controller stopped new submissions. Existing jobs are left running.')
        if not a.watch or all(r['classification']=='succeeded' for r in state.values()):break
        time.sleep(a.interval)
if __name__=='__main__':main()
