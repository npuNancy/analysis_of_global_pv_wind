#!/usr/bin/env python3
"""依次运行 RQ3/tmp 下的全部临时机制分析图。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPTS = [
    "prepare_station_summaries.py",
    "plot_01_loss_growth_decomposition.py",
    "plot_09_deployment_climate_counterfactual.py",
    "plot_10_ssp126_ssp585_gap_decomposition.py",
    "plot_02_loss_rate_mechanism.py",
    "plot_03_event_mechanism.py",
    "plot_04_wind_scenario_convergence.py",
    "plot_05_country_shift_share.py",
    "plot_06_cohort_and_tail.py",
    "plot_07_exposure_loss_conversion.py",
    "plot_08_system_and_sensitivity.py",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="CANESM5", help="CMIP6 模式名称。")
    parser.add_argument("--output-dir", type=Path, default=None, help="可选输出目录。")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    for name in SCRIPTS:
        command = [sys.executable, str(here / name), "--model", args.model]
        if name == "prepare_station_summaries.py":
            # 强制重建，避免复用未应用临时风电 0.1 修正的旧缓存。
            command.append("--force")
        if args.output_dir is not None:
            command.extend(["--output-dir", str(args.output_dir)])
        print(f"\n运行：{' '.join(command)}", flush=True)
        subprocess.run(command, check=True)
    print("\n全部 RQ3 临时机制分析图已完成。")


if __name__ == "__main__":
    main()
