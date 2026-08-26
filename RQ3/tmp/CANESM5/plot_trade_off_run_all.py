#!/usr/bin/env python3
"""依次运行 CANESM5 的全部 trade-off 候选绘图脚本。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPTS = [
    "plot_trade_off_quadrant.py",
    "plot_trade_off_rank_reversal.py",
    "plot_trade_off_composition_standardized.py",
    "plot_trade_off_country_capacity_loss.py",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=Path(__file__).resolve().parent.name)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    for filename in SCRIPTS:
        command = [sys.executable, str(here / filename), "--model", args.model]
        if args.output_dir is not None:
            command.extend(["--output-dir", str(args.output_dir)])
        print(f"\n运行：{' '.join(command)}", flush=True)
        subprocess.run(command, check=True)
    print("\n全部 trade-off 候选图已完成。")


if __name__ == "__main__":
    main()
