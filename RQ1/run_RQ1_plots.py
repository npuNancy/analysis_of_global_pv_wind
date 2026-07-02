#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run RQ1 real-data plotting scripts.

Examples:
  # Generate NESM3 real-data figures under RQ1/outputs/real/NESM3/
  python RQ1/run_RQ1_plots.py

  # Also regenerate cross-CMIP6 comparison figures
  python RQ1/run_RQ1_plots.py --include-cross-model
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

NESM3_COMMANDS = [
    [
        "RQ1/plot_RQ1_cf.py",
        "--model",
        "NESM3",
        "--data-dir",
        "data/cfs/annual_mean_cf/NESM3",
        "--era5land-dir",
        "none",
    ],
    ["RQ1/plot_RQ1_generation.py"],
    ["RQ1/plot_RQ1_country_cf_bar.py"],
    ["RQ1/plot_RQ1_cf_capacity_quadrant.py"],
    ["RQ1/plot_RQ1_violin_cap_cf_gen.py"],
]

CROSS_MODEL_COMMANDS = [
    ["RQ1/plot_RQ1_cross_model_cf_change.py"],
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run RQ1 real-data plotting scripts. Model-specific scripts currently use NESM3."
    )
    parser.add_argument(
        "--model",
        default="NESM3",
        choices=["NESM3"],
        help="CMIP climate model for model-specific RQ1 figures.",
    )
    parser.add_argument(
        "--include-cross-model",
        action="store_true",
        help="Also run the cross-CMIP6 comparison plotting script.",
    )
    return parser.parse_args()


def run_script(args: list[str]) -> None:
    cmd = [sys.executable, *args]
    print("\n>>>", " ".join(cmd), flush=True)
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-rq1")
    Path(env["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def main() -> None:
    args = parse_args()
    print(f"Running RQ1 real-data plots for CMIP model: {args.model}")
    print("Output directory: RQ1/outputs/real/NESM3/")

    for cmd in NESM3_COMMANDS:
        run_script(cmd)

    if args.include_cross_model:
        for cmd in CROSS_MODEL_COMMANDS:
            run_script(cmd)

    print("\nDone.")


if __name__ == "__main__":
    main()
