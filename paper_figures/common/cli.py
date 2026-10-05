import argparse
from pathlib import Path
from paper_figures.config import OUTPUT,MODELS,SSPS,TECHS,SNAPSHOTS

def parser(description):
    p=argparse.ArgumentParser(description=description)
    p.add_argument('--output-root',type=Path,default=OUTPUT)
    p.add_argument('--models',nargs='+',choices=MODELS,default=list(MODELS))
    p.add_argument('--climate-ssps',nargs='+',choices=SSPS,default=list(SSPS))
    p.add_argument('--station-ssps',nargs='+',choices=SSPS,default=list(SSPS))
    p.add_argument('--techs',nargs='+',choices=TECHS,default=list(TECHS))
    p.add_argument('--snapshots',nargs='+',type=int,choices=SNAPSHOTS,default=list(SNAPSHOTS))
    p.add_argument('--patches',nargs='+')
    return p
