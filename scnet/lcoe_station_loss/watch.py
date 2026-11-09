"""Monitor LCOE annual loss tasks using the shared account controller."""
import sys
from pathlib import Path
from scnet.lcoe_station_climate import watch

def main():
    here=Path(__file__).resolve().parent
    watch.STATUS=here/'completion_status'
    atomic=watch.atomic
    def write_status(path,text):
        if path.name=='progress.md':text=text.replace('# LCOE CF / Extreme进度','# LCOE Loss进度')
        atomic(path,text)
    watch.atomic=write_status
    if '--config' not in sys.argv:sys.argv.extend(['--config',str(here/'campaign.json')])
    watch.main()
if __name__=='__main__':main()
