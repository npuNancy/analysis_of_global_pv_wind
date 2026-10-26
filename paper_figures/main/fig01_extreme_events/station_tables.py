"""Extract compact station exposure and loss tables from the accepted preparation summaries.

Annual tables keep the GLOBAL rows of all nine climate x deployment combinations; window tables keep
every country. Loss rows use the common support. Nothing is recomputed here.
"""
import argparse
from pathlib import Path

import pandas as pd

from paper_figures.config import OUTPUT
from paper_figures.common.io import write_csv, require_complete
from paper_figures.main.fig01_extreme_events.meeting_common import OUT

CHUNK_ROWS = 2_000_000


def filtered(path, keep):
    parts = [chunk[keep(chunk)] for chunk in pd.read_csv(path, chunksize=CHUNK_ROWS)]
    return pd.concat(parts, ignore_index=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root', type=Path, default=OUT / 'station_tables')
    a = p.parse_args()
    for stage in ('event_summary', 'loss_summary', 'catalogues'):
        require_complete(OUTPUT / stage)
    out = a.output_root
    write_csv(out / 'events_annual_global.csv.gz',
              filtered(OUTPUT / 'event_summary/annual.csv.gz', lambda d: d.country == 'GLOBAL'))
    write_csv(out / 'events_window.csv.gz', pd.read_csv(OUTPUT / 'event_summary/window.csv.gz'))
    write_csv(out / 'loss_annual_global.csv.gz',
              filtered(OUTPUT / 'loss_summary/annual.csv.gz', lambda d: (d.country == 'GLOBAL') & (d.support == 'common')))
    window = pd.read_csv(OUTPUT / 'loss_summary/window.csv.gz')
    write_csv(out / 'loss_window.csv.gz', window[window.support == 'common'])
    print('written', sorted(x.name for x in out.iterdir()))


if __name__ == '__main__':
    main()
