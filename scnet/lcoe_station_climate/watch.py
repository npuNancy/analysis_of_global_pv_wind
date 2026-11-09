"""Aligned quarter-hour multi-account inspection, judgement, reporting and refill."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
from pathlib import Path
import shlex
import subprocess
import time
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
STATUS=HERE/'completion_status'
TZ=ZoneInfo('Asia/Shanghai')

def ssh(alias,script,timeout=600):
    p=subprocess.run(['ssh','-o','ConnectTimeout=15',alias,'export LC_ALL=C LANG=C PYTHONUTF8=1; '+script],text=True,capture_output=True,timeout=timeout,env={**__import__('os').environ,'LC_ALL':'C'})
    if p.returncode:raise RuntimeError(alias+': '+p.stderr[-2000:]+p.stdout[-2000:])
    return p.stdout

def atomic(path,text):
    tmp=path.with_suffix('.tmp');tmp.write_text(text,encoding='utf-8');tmp.replace(path)

def cycle(cfg,submit):
    root=cfg['root'];repo=cfg['repo'];owner=cfg['accounts'][0]['alias'];start=datetime.now(TZ)
    prefix='source '+shlex.quote(cfg['activate'])+'; cd '+shlex.quote(repo)+'; '
    gates=ssh(owner,'for f in prepared.json pilot_accepted.json pilot_accepted.storage_hold.json; do test ! -f '+shlex.quote(root+'/runtime')+'/"$f" || echo "$f"; done').splitlines()
    storage_hold='pilot_accepted.storage_hold.json' in gates
    STATUS.mkdir(parents=True,exist_ok=True)
    if 'prepared.json' not in gates:
        def inspect(account):
            out=ssh(account['alias'],'squeue -h -u '+shlex.quote(account['username'])+' -o '+shlex.quote('%i|%T|%R'))
            return account['username'],out.splitlines()
        with ThreadPoolExecutor(max_workers=len(cfg['accounts'])) as pool:facts=list(pool.map(inspect,cfg['accounts']))
        lines=['# LCOE CF / Extreme进度','',f'Last checked: {start.isoformat()}','',
            '检查：准备阶段尚未完成；已查询全部十账号。',
            '思考：预计剩余3–6小时，加准备作业排队时间；暂无真实试运行速度。',
            '汇总：数据准备和试运行是批量任务的前置依赖。',
            '执行：监控准备作业，暂不提交依赖未满足的抽取任务。','',
            '| 账号 | 活动作业 | 状态 / 原因 | 下一步 |','|---|---:|---|---|']
        for user,rows in facts:lines.append('| '+user+' | '+str(len(rows))+' | '+'; '.join(rows).replace('|',' / ')+' | 等待准备完成 |')
        atomic(STATUS/'progress.md','\n'.join(lines)+'\n')
        print(start.isoformat(),'PREPARATION_PENDING','ETA 3–6小时 + 排队',flush=True)
        return False
    submit=submit and 'pilot_accepted.json' in gates and not storage_hold
    def one(account):
        try:
            # A full result filesystem may also prevent updating its code checkout.
            entry='python -c '+shlex.quote((HERE/'control.py').read_text()) if storage_hold else 'python -m scnet.lcoe_station_climate.control'
            out=ssh(account['alias'],prefix+entry+' --root '+shlex.quote(root)+(' --submit' if submit else '')+(' --read-only' if storage_hold else ''))
            return json.loads(out.strip().splitlines()[-1])
        except Exception as e:return {'account':account['username'],'error':str(e)}
    with ThreadPoolExecutor(max_workers=len(cfg['accounts'])) as pool:accounts=list(pool.map(one,cfg['accounts']))
    raw=ssh(owner,'cat '+shlex.quote(root+'/runtime/state.json'))
    state=json.loads(raw)
    for account in accounts:state.update(account.pop('units',{}))
    counts=Counter(v['state'] for v in state.values())
    completed=[v.get('elapsed_seconds',0) for v in state.values() if v['state']=='SUCCEEDED' and v.get('elapsed_seconds',0)>0]
    remain=len(state)-counts['SUCCEEDED'];active=sum(a.get('active',0) for a in accounts)
    mean=sum(completed)/len(completed) if completed else 1800
    eta=math.ceil(remain/200)*max(900,mean)/3600 if remain else 0
    estimate=f'{eta:.1f}小时（已完成任务均值与200槽估算；排队/尾部任务另计）' if completed else '3–6小时（试运行前暂估）'
    if storage_hold:estimate='存储恢复后'+estimate+'；等待存储方案确认的时间另计'
    lines=['# LCOE CF / Extreme进度','',f'Last checked: {start.isoformat()}','',f'检查：{dict(counts)}；账号活动作业合计{active}。',f'思考：预计剩余{estimate}。',
        '汇总：源文件只读；终态成功需Slurm退出码和任务完成回执。','执行：'+('存储配额已满，停止补交；只读检查，保留已完成分片，等待存储方案确认。' if storage_hold else '已按各账号全量活动数补足可用20槽。' if submit else '本轮仅观察，等待依赖验收。'),'',
        '| 账号 | 活动作业 | 新提交 | 异常 |','|---|---:|---:|---|']
    for a in accounts:lines.append('| '+a['account']+' | '+str(a.get('active','unknown'))+' | '+str(len(a.get('submitted',[])))+' | '+a.get('error','').replace('|','/').replace('\n',' ')+' |')
    lines+=['','| 单位 | 账号 | 作业 | 状态 | Slurm / 退出码 | 耗时秒 / MaxRSS | 尝试 | 证据 / 下一步 |','|---|---|---|---|---|---|---:|---|']
    for k,v in state.items():
        action='完成' if v['state']=='SUCCEEDED' else '等待/补充' if v['state'] in ['ACTIVE','NOT_SUBMITTED'] else '检查原因'
        vals=[k,v.get('account',''),v.get('job_id',''),v['state'],v.get('scheduler_state','')+' / '+v.get('exit_code',''),str(v.get('elapsed_seconds',''))+' / '+v.get('max_rss',''),v['attempt'],v.get('evidence','')+' / '+action]
        lines.append('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in vals)+' |')
    STATUS.mkdir(parents=True,exist_ok=True)
    atomic(STATUS/'state.json',json.dumps(state,indent=2)+'\n');atomic(STATUS/'accounts.json',json.dumps(accounts,indent=2)+'\n')
    atomic(STATUS/'progress.md','\n'.join(lines)+'\n')
    print(start.isoformat(),dict(counts),'ETA',estimate,'active',active,flush=True)
    for a in accounts:print(json.dumps(a),flush=True)
    return remain==0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=HERE/'campaign.json')
    p.add_argument('--submit',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--align-first',action='store_true')
    a=p.parse_args();cfg=json.loads(a.config.read_text());first=True
    while True:
        if not first or a.align_first:
            target=(int(time.time())//900+1)*900
            while time.time()<target:time.sleep(min(30,target-time.time()))
        first=False
        try:done=cycle(cfg,a.submit)
        except Exception as exc:
            print(datetime.now(TZ).isoformat(),'MONITOR_ERROR',repr(exc),flush=True);done=False
        if done or not a.watch:break
if __name__=='__main__':main()
