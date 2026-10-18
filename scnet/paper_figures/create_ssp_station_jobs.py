"""Generate station SSP pilot, full dynamics, reduction and report jobs."""
import argparse
import json
from pathlib import Path
from paper_figures.config import ROOT, OUTPUT
from paper_figures.common.io import write_json
from scnet.paper_figures.create_ssp_dynamics_jobs import shell
from paper_figures.main.fig01_extreme_events.analyze_ssp_station import OUT

def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("--job-dir",type=Path,default=ROOT.parents[1]/"runtime/ssp_station_jobs/20261018")
    p.add_argument("--output-root",type=Path,default=OUT)
    p.add_argument("--batches",type=int,default=20)
    p.add_argument("--workers",type=int,default=16)
    p.add_argument("--dry-run",action="store_true");a=p.parse_args()
    if not 1<=a.batches<=2592 or not 1<=a.workers<=16:p.error("Invalid resources")
    units=[];logs=ROOT/"logs/paper_figures/ssp_station"
    def add(name,module,args,deps,marker,cpus,hours):
        script=a.job_dir/(name+".sh");log=logs/(name+"_%j.out")
        units.append(dict(unit=name,script=str(script),dependencies=deps,marker=str(marker),log_pattern=str(log)))
        if not a.dry_run:
            script.parent.mkdir(parents=True,exist_ok=True)
            text=shell(module,args,name,cpus,hours,log)
            if script.exists() and script.read_text()!=text:raise ValueError("Script collision: "+str(script))
            script.write_text(text)
    dynamics=a.output_root/"dynamics"
    pilot=dynamics/"pilot"
    add("station_pilot","paper_figures.main.fig01_extreme_events.prepare_ssp_station_dynamics",
        ["--models","BCC-CSM2-MR","--ssps","ssp126","--layouts","ssp126","--patches","R02C08","--snapshots","2050","--workers","2","--output-root",str(pilot)],
        [],pilot/"batches/000/complete.json",4,"04:00:00")
    batches=[]
    for i in range(a.batches):
        name=f"station_{i:03d}";batches.append(name)
        add(name,"paper_figures.main.fig01_extreme_events.prepare_ssp_station_dynamics",
            ["--batch",str(i),"--batches",str(a.batches),"--workers",str(a.workers),"--output-root",str(dynamics)],
            ["station_pilot"],dynamics/"batches"/f"{i:03d}"/"complete.json",a.workers,"12:00:00")
    add("station_summary","paper_figures.main.fig01_extreme_events.summarize_ssp_station_dynamics",
        ["--output-root",str(dynamics)],batches,dynamics/"summary/complete.json",8,"04:00:00")
    add("station_report","paper_figures.main.fig01_extreme_events.analyze_ssp_station",
        ["--output-root",str(a.output_root),"--dynamics",str(dynamics/"summary")],["station_summary"],a.output_root/"complete.json",4,"02:00:00")
    units[-1]["external_markers"]=[str(OUT.parent/"ssp_grid/dynamics/summary/complete.json")]
    if not a.dry_run:
        logs.mkdir(parents=True,exist_ok=True)
        write_json(a.job_dir/"jobs.json",dict(prerequisite=str(OUTPUT/"event_summary/complete.json"),units=units,output_root=str(a.output_root),batches=a.batches,workers=a.workers))
    print(json.dumps(dict(total_jobs=len(units),raw_tasks=2592,batches=a.batches,workers=a.workers,dry_run=a.dry_run)))
if __name__=="__main__":main()
