"""Generate independent grid-cache jobs and the downstream analysis DAG."""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--input-root", type=Path, default=Path("/work/share/acjpoxgsdu/extreme_grid/grid_v2"))
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--grid-output-dir", type=Path)
    parser.add_argument("--country-output-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--ssps", nargs="+")
    parser.add_argument("--techs", nargs="+", default=["wind", "solar"])
    parser.add_argument("--patches", nargs="+")
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2015, 2061)))
    parser.add_argument("--baseline-years", nargs="+", type=int, default=list(range(2015, 2025)))
    parser.add_argument("--future-years", nargs="+", type=int, default=list(range(2050, 2060)))
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--partition", default="wzhctest")
    parser.add_argument("--time", default="3-00:00:00")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.repo_root = args.repo_root.resolve()
    args.job_dir = (args.job_dir or args.repo_root.parent.parent / "runtime/extreme_grid_jobs").resolve()
    args.grid_output_dir = (args.grid_output_dir or args.repo_root / "RQ1_extreme/global/grid/outputs").resolve()
    args.country_output_dir = (args.country_output_dir or args.repo_root / "RQ1_extreme/country/grid/outputs").resolve()
    args.log_dir = (args.log_dir or args.repo_root / "logs/RQ1_extreme/parallel").resolve()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.repo_root in args.job_dir.parents or args.job_dir == args.repo_root:
        parser.error("--job-dir must be outside the repository")
    for field in ("years", "baseline_years", "future_years"):
        values = getattr(args, field)
        if len(set(values)) != len(values) or any(y < 2015 or y > 2060 for y in values):
            parser.error("Invalid or duplicate years: " + field)
    if not set(args.baseline_years + args.future_years) <= set(args.years):
        parser.error("Period years must be selected in --years")
    return args


def main():
    args = parse_args()
    rows = list(json.loads((args.input_root / "runtime/authoritative_index.json").read_text())["combinations"].values())
    for option, key in (("models", "model"), ("ssps", "scenario"), ("techs", "tech"), ("patches", "patch")):
        allowed = {row[key] for row in rows}
        selected = getattr(args, option) or sorted(allowed)
        if len(selected) != len(set(selected)) or set(selected) - allowed:
            raise ValueError("Invalid or duplicate selection: " + option)
        setattr(args, option, selected)
    expected = set(itertools.product(args.models, args.ssps, args.techs, args.patches))
    actual = [(r["model"], r["scenario"], r["tech"], r["patch"]) for r in rows
              if (r["model"], r["scenario"], r["tech"], r["patch"]) in expected]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Input index does not cover selected combinations uniquely")
    common = ["--input-root", str(args.input_root), "--output-dir", str(args.grid_output_dir),
              "--techs", *args.techs, "--patches", *args.patches,
              "--years", *map(str, args.years),
              "--baseline-years", *map(str, args.baseline_years),
              "--future-years", *map(str, args.future_years)]
    wrapper = args.repo_root / "RQ1_extreme/global/grid/global_grid_extremes.sh"
    jobs = []

    def add(unit, stage, command, dependencies, cpus, walltime):
        log = args.log_dir / (unit + "_%j.out")
        script = "\n".join([
            "#!/bin/bash", "#SBATCH --job-name=rq1_" + unit,
            "#SBATCH --partition=" + args.partition, "#SBATCH --nodes=1", "#SBATCH --ntasks=1",
            "#SBATCH --cpus-per-task=" + str(cpus), "#SBATCH --mem=" + str(math.ceil(cpus * 3.5)) + "G",
            "#SBATCH --time=" + walltime, "#SBATCH --output=" + str(log), "#SBATCH --error=" + str(log),
            "", "set -euo pipefail",
            "source " + shlex.quote(str(args.repo_root / ".venv/bin/activate")),
            "export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1",
            "cd " + shlex.quote(str(args.repo_root)), shlex.join(command), "",
        ])
        jobs.append({"unit": unit, "stage": stage, "script": str(args.job_dir / (unit + ".sh")),
                     "dependencies": dependencies, "cpus": cpus, "memory_gb": math.ceil(cpus * 3.5),
                     "text": script})

    manifests = []
    for model, ssp in itertools.product(args.models, args.ssps):
        unit = "cache_" + model + "_" + ssp
        manifest = args.grid_output_dir / "cache_manifests" / (unit + ".json")
        manifests.append(str(manifest))
        command = ["bash", str(wrapper), *common, "--models", model, "--ssps", ssp,
                   "--workers", str(args.workers), "--phase", "cache", "--manifest-path", str(manifest)]
        add(unit, "cache", command, [], args.workers, args.time)
    shard_units = [j["unit"] for j in jobs]
    all_scope = [*common, "--models", *args.models, "--ssps", *args.ssps]
    add("manifest", "manifest", ["bash", str(wrapper), *all_scope, "--workers", "1",
                                 "--phase", "manifest", "--cache-manifests", *manifests], shard_units, 2, "01:00:00")
    add("global", "global", ["bash", str(wrapper), *all_scope, "--phase", "plot"], ["manifest"], 4, "12:00:00")
    add("country", "country", ["python", str(args.repo_root / "RQ1_extreme/country/grid/country_grid_extremes.py"),
                               "--grid-output-dir", str(args.grid_output_dir),
                               "--output-dir", str(args.country_output_dir)], ["manifest"], 4, "12:00:00")
    summary = {"combinations": len(expected), "cache_jobs": len(shard_units),
               "workers_per_cache_job": args.workers, "total_jobs": len(jobs), "job_dir": str(args.job_dir)}
    print(json.dumps(summary))
    if args.dry_run:
        return
    if args.job_dir.exists():
        raise FileExistsError("Job directory already exists: " + str(args.job_dir))
    args.job_dir.mkdir(parents=True)
    for job in jobs:
        Path(job["script"]).write_text(job.pop("text"))
    (args.job_dir / "jobs.json").write_text(json.dumps({**summary, "jobs": jobs}, indent=2) + "\n")


if __name__ == "__main__":
    main()
