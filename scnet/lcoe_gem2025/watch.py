"""Monitor independent GEM stages and refill account-wide capacity under shared locks."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
STATUS=HERE/'completion_status'
PHASES=['publish','historical','loss_transition','loss_future','era5_met','transition','future']
BAD={'FAILED','INCOMPLETE_OUTPUT','DETERMINISTIC_FAILURE','SUBMISSION_FAILED','UNKNOWN'}


def ssh(alias,command):
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',alias,command],
        text=True,capture_output=True,timeout=300,env={**os.environ,'LC_ALL':'C','LANG':'C'})
    if p.returncode:raise RuntimeError(alias+': '+p.stderr[-1500:]+p.stdout[-1500:])
    return p.stdout


def snapshot(cfg):
    code='''import json
from pathlib import Path
root=Path(ROOT)
result={}
for phase in PHASES:
 p=root/phase/'runtime/state.json'
 if p.exists():
  result[phase]={'state':json.loads(p.read_text()),'accepted':(p.parent/'pilot_accepted.json').exists()}
print(json.dumps(result))
'''.replace('ROOT',repr(cfg['root'])).replace('PHASES',repr(PHASES))
    return json.loads(ssh('scnet-wuzhen-1959','python3 -c '+shlex.quote(code)))


def cycle(cfg,submit):
    before=snapshot(cfg)
    prefix='source '+shlex.quote(cfg['activate'])+'; cd '+shlex.quote(cfg['repo'])+'; '
    def refresh(pair):
        a,phase=pair
        try:
            command=prefix+'python -m scnet.lcoe_station_climate.control --root '+shlex.quote(cfg['root']+'/'+phase)
            return json.loads(ssh(a['alias'],command).strip().splitlines()[-1])
        except Exception as exc:return {'account':a['username'],'phase':phase,'error':str(exc)}
    pending=[(a,phase) for a in cfg['accounts'] for phase,v in before.items()
             if any(s.get('account')==a['username'] and s['state'] not in ['SUCCEEDED'] for s in v['state'].values())]
    with ThreadPoolExecutor(max_workers=10) as pool:observations=list(pool.map(refresh,pending))
    before=snapshot(cfg)
    def account(a):
        results=[];errors=[]
        try:
            preferred=a['preferred_phase']
            order=list(dict.fromkeys([preferred]+PHASES))
            active=0
            for phase in order:
                if phase not in before:continue
                data=before[phase]
                failed=any(v['state'] in BAD for v in data['state'].values())
                can_submit=submit and data['accepted'] and not failed and active<a['max_active']
                has_pending=any(v['state']=='NOT_SUBMITTED' for v in data['state'].values())
                if not (can_submit and has_pending):continue
                command=prefix+'python -m scnet.lcoe_station_climate.control --root '+shlex.quote(cfg['root']+'/'+phase)
                if can_submit:command+=' --submit --max-submit 20'
                out=json.loads(ssh(a['alias'],command).strip().splitlines()[-1]);out['phase']=phase
                results.append(out);active=out['active']
            return dict(account=a['username'],results=results,errors=errors)
        except Exception as exc:return dict(account=a['username'],results=results,errors=[str(exc)])
    with ThreadPoolExecutor(max_workers=10) as pool:accounts=list(pool.map(account,cfg['accounts']))
    after=snapshot(cfg);stamp=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat();STATUS.mkdir(parents=True,exist_ok=True)
    lines=['# GEM 场站气候计算进度','',f'Last checked: {stamp}','',
        '提交前持账号共享锁并重查全账号活动作业；每账号上限20。发现失败的阶段暂停补交，已运行单元继续完成。',
        'ACTIVE为各单元上次核对或提交时的状态；补交期间结束的作业在下一轮更新，因此跨阶段ACTIVE之和不是实时并发数。','',
        '| 阶段 | 状态计数 | 下一步 |','|---|---|---|']
    counts={phase:dict(Counter(v['state'] for v in item['state'].values())) for phase,item in after.items()}
    for phase,count in counts.items():
        action='已完成' if set(count)=={'SUCCEEDED'} else '检查失败证据' if any(k in BAD for k in count) else '计算并补交' if after[phase]['accepted'] else '等待首批验收'
        lines.append(f'| {phase} | {count} | {action} |')
    estimates=[]
    for phase,item in after.items():
        values=list(item['state'].values());finished=[v.get('elapsed_seconds',0) for v in values if v['state']=='SUCCEEDED']
        active=sum(v['state']=='ACTIVE' for v in values);remaining=sum(v['state']!='SUCCEEDED' for v in values)
        if finished and active:estimates.append(f'{phase}: 约 {np_mean(finished)*remaining/active/3600:.2f} 小时（当前并发与已完成单元均值；I/O竞争及尾部另计）')
        elif remaining:estimates.append(phase+': 等待有效并发与速度估计')
    lines+=['','耗时估计：'+'；'.join(estimates),'',
        '| 阶段 / 单元 | 账号 | 作业 | 状态 | Slurm / 退出码 | 耗时秒 / MaxRSS | 尝试 | 证据 / 下一步 |',
        '|---|---|---|---|---|---|---:|---|']
    for phase,item in after.items():
        for unit,v in item['state'].items():
            action='完成' if v['state']=='SUCCEEDED' else '排队/补交' if v['state'] in ['ACTIVE','NOT_SUBMITTED'] else '审查原因'
            cells=[phase+'/'+unit,v.get('account',''),v.get('job_id',''),v['state'],v.get('scheduler_state','')+'/'+v.get('exit_code',''),
                   str(v.get('elapsed_seconds',''))+'/'+v.get('max_rss',''),v.get('attempt',0),v.get('evidence','')+' / '+action]
            lines.append('| '+' | '.join(str(c).replace('|','/').replace('\n',' ') for c in cells)+' |')
    for filename,value in [('state.json',after),('accounts.json',accounts)]:
        tmp=STATUS/(filename+'.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(STATUS/filename)
    tmp=STATUS/'progress.md.tmp';tmp.write_text('\n'.join(lines)+'\n');tmp.replace(STATUS/'progress.md')
    submitted=sum(len(r['submitted']) for a in accounts for r in a['results'])
    print(stamp,json.dumps(counts),'submitted',submitted,flush=True)
    for a in accounts:
        if a['errors']:print(a['account'],a['errors'],flush=True)
    for result in observations:
        if result.get('error'):print(result,flush=True)
    return set(PHASES).issubset(after) and all(all(v['state']=='SUCCEEDED' for v in p['state'].values()) for p in after.values())


def np_mean(values):return sum(values)/max(1,len(values))


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--config',type=Path,default=HERE/'campaign.json')
    p.add_argument('--submit',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=60)
    a=p.parse_args();cfg=json.loads(a.config.read_text())
    while True:
        try:done=cycle(cfg,a.submit)
        except Exception as exc:print('MONITOR_ERROR',repr(exc),flush=True);done=False
        if not a.watch or done:break
        # Short sleeps keep interruption responsive during long campaigns.
        for _ in range(max(1,a.interval)//5):time.sleep(5)


if __name__=='__main__':main()
