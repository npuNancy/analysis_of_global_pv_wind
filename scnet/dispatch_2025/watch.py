"""Poll dispatch jobs and refill the climate-specific account queues."""
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

HERE = Path(__file__).resolve().parent
BAD = {"FAILED","INCOMPLETE_OUTPUT","DETERMINISTIC_FAILURE","SUBMISSION_FAILED","UNKNOWN","SUBMITTING"}


def ssh(alias, command):
    result = subprocess.run(["ssh","-o","BatchMode=yes","-o","ConnectTimeout=15",alias,command],
        text=True,capture_output=True,timeout=240,env={**os.environ,"LC_ALL":"C","LANG":"C"})
    if result.returncode:
        raise RuntimeError(alias+": "+result.stderr[-1800:]+result.stdout[-1800:])
    return result.stdout


def snapshot(cfg, phase):
    code = "import json;from pathlib import Path;r=Path("+repr(cfg["root"]+"/"+phase)+");print(json.dumps(dict(state=json.loads((r/'runtime/state.json').read_text()) if (r/'runtime/state.json').exists() else {},accepted=(r/'runtime/pilot_accepted.json').exists(),tasks=json.loads((r/'runtime/tasks.json').read_text()))))"
    return json.loads(ssh("scnet-wuzhen-1959","python3 -c "+shlex.quote(code)))


def cycle(cfg, phase, submit, pilot):
    before = snapshot(cfg, phase)
    tasks = before["tasks"]
    pilots = []
    if pilot:
        for climate in cfg["climate_ssps"]:
            for product in cfg["products"] if phase=="future" else ["loss" if phase=="loss_future" else "publish"]:
                for tech in cfg["techs"]:
                    selected=[t for t in tasks if t["climate_ssp"]==climate and t["product"]==product and t["tech"]==tech
                              and (phase=="publish" or t["model"]=="MPI-ESM1-2-HR")]
                    if not selected:
                        raise ValueError("Missing pilot class")
                    pilots.append(max(selected,key=lambda t:(t["n_union"],t["unit"]))["unit"])
    def account(a):
        command = "cd "+shlex.quote(cfg["repo"])+"; source .venv/bin/activate; python -m scnet.lcoe_station_climate.control --root "+shlex.quote(cfg["root"]+"/"+phase)
        can_submit = submit and (pilot or before["accepted"]) and not any(s["state"] in BAD for s in before["state"].values())
        if can_submit:
            command += " --submit --max-submit 20"
            if pilot:
                command += " --pilot "+shlex.join(pilots)
        try:
            return json.loads(ssh(a["alias"],command).strip().splitlines()[-1])
        except Exception as exc:
            return dict(account=a["username"],error=str(exc))
    with ThreadPoolExecutor(max_workers=len(cfg["accounts"])) as pool:
        observations=list(pool.map(account,cfg["accounts"]))
    after=snapshot(cfg,phase)
    stamp=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    status=HERE/"completion_status"/cfg.get("status_subdir","")
    status.mkdir(parents=True,exist_ok=True)
    counts=dict(Counter(s["state"] for s in after["state"].values()))
    lines=["# 全球场站-dispatch-2025 运行进度","",f"Last checked: {stamp}","",
           f"阶段：{phase}；状态：{counts}。每账号所有项目活动作业上限20，按气候SSP分配。","",
           "下一步：完成首批并验收后开放全矩阵；提取全部成功后准备Loss，Loss成功后发布和绘图。","",
           "| 单元 | 账号 | 作业 | 状态 | Slurm / 退出码 | 秒 / MaxRSS | 尝试 | 证据 |",
           "|---|---|---|---|---|---|---:|---|"]
    for task in tasks:
        unit=task["unit"];s=after["state"].get(unit,dict(state="NOT_SUBMITTED"))
        cells=[unit,s.get("account",""),s.get("job_id",""),s["state"],s.get("scheduler_state","")+"/"+s.get("exit_code",""),
               str(s.get("elapsed_seconds",""))+"/"+s.get("max_rss",""),s.get("attempt",0),s.get("evidence","")]
        lines.append("| "+" | ".join(str(c).replace("|","/").replace("\n"," ") for c in cells)+" |")
    for obs in observations:
        if obs.get("error"):
            lines+=["",obs["error"]]
    for filename,value in [(phase+"_state.json",after),("accounts.json",observations)]:
        p=status/filename;tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(value,indent=2)+"\n");tmp.replace(p)
    p=status/"progress.md";tmp=p.with_suffix(".tmp");tmp.write_text("\n".join(lines)+"\n");tmp.replace(p)
    print(stamp,phase,json.dumps(counts),"submitted",sum(len(o.get("submitted",[])) for o in observations),flush=True)
    for obs in observations:
        if obs.get("error"):print(obs,flush=True)
    if not after["state"]:return False
    tracked=[after["state"][p] for p in pilots] if pilot else list(after["state"].values())
    return all(s["state"]=="SUCCEEDED" for s in tracked)


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--config",type=Path,default=HERE/"campaign.json")
    p.add_argument("--phase",choices=["future","loss_future","publish"],default="future")
    p.add_argument("--submit",action="store_true")
    p.add_argument("--pilot",action="store_true")
    p.add_argument("--watch",action="store_true")
    p.add_argument("--interval",type=int,default=60)
    p.add_argument("--hourly",action="store_true",help="Check at each full hour, starting with the next full hour")
    a=p.parse_args();cfg=json.loads(a.config.read_text())
    while True:
        if a.hourly:
            next_check=(int(time.time())//3600+1)*3600
            print("NEXT_CHECK",datetime.fromtimestamp(next_check,ZoneInfo("Asia/Shanghai")).isoformat(),flush=True)
            time.sleep(max(0,next_check-time.time()))
        try:done=cycle(cfg,a.phase,a.submit,a.pilot)
        except Exception as exc:print("MONITOR_ERROR",repr(exc),flush=True);done=False
        if not a.watch or done:break
        if not a.hourly:
            for _ in range(max(1,a.interval)//5):time.sleep(5)

if __name__=="__main__":
    main()
