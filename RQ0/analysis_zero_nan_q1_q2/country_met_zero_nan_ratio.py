#!/usr/bin/env python3
"""逐国家统计 BCSD 气象在场站位置的 0/nan 占比。

国家归属复用 RQ0/plot_stations_S0E2_zero_or_nan.py 的 Natural Earth 口径；
气象取值也复用同一脚本的 query_met，确保与 S0E2 图的上排完全同口径。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np


THIS_DIR = Path(__file__).resolve().parent
RQ0_DIR = THIS_DIR.parent
sys.path.insert(0, str(RQ0_DIR))

import plot_stations_S0E2_zero_or_nan as P  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="逐国家统计 BCSD 气象 0/nan 场站占比")
    parser.add_argument("--model", default=P.MODEL, help=f"CMIP6 模式，默认 {P.MODEL}")
    parser.add_argument("--ssp", default=P.SSP, choices=list(P.SSP_STATION_FILE), help=f"情景，默认 {P.SSP}")
    parser.add_argument("--year", type=int, default=P.YEAR, help=f"统计年份，默认 {P.YEAR}")
    parser.add_argument("--stations", default=None, help="场站 CSV；默认按 --ssp 从 data/stations 读取")
    parser.add_argument("--out", default=None, help="输出 CSV；默认写入本目录 outputs/")
    return parser.parse_args()


def bad_stats(vals, mask):
    n_nan = int(np.sum(mask & np.isnan(vals)))
    n_zero = int(np.sum(mask & (~np.isnan(vals)) & (vals == 0)))
    n_bad = n_nan + n_zero
    n_ok = int(np.sum(mask & (~np.isnan(vals)) & (vals > 0)))
    n_covered = n_bad + n_ok
    ratio = n_bad / n_covered if n_covered else 0.0
    return n_nan, n_zero, n_bad, n_ok, n_covered, ratio


def country_has_met_data(country, tech, model, ssp, year):
    """检查该模式/情景/国家是否有对应 BCSD 气象文件。

    wind 需要 uas 与 vas 同时存在；solar 需要 rsds 存在。区域不全的模式中，
    缺失国家不应计入分母，也不应被误算为 100% NaN。
    """
    if tech == "wind":
        variables = ("uas", "vas")
    else:
        variables = ("rsds",)
    for var in variables:
        path = P.met_path(country, var, model, ssp, year)
        if not path or not os.path.isfile(path):
            return False
    return True


def main():
    args = parse_args()
    P.MODEL = args.model
    P.SSP = args.ssp
    P.YEAR = args.year

    csv_path = args.stations or os.path.join(P.STATIONS_DIR, P.SSP_STATION_FILE[args.ssp])
    out_path = Path(args.out) if args.out else (
        THIS_DIR / "outputs" / f"country_met_zero_nan_ratio_{args.model}_{args.ssp}_{args.year}.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stations = P.load_stations_2050(csv_path)
    rows = []

    for tech in ("wind", "solar"):
        lon, lat = stations[tech]
        labels = P.assign_regions(lon, lat, include_nam=False)
        vals = np.full(len(lon), np.nan)
        available_countries = [
            country
            for country in P.COUNTRIES_26
            if country_has_met_data(country, tech, args.model, args.ssp, args.year)
        ]

        for country in available_countries:
            m = labels == country
            if not m.any():
                continue
            grid = P.load_met_grid(country, tech, args.model, args.ssp, args.year)
            if grid is not None:
                vals[m] = P.lookup_1d(lon[m], lat[m], *grid)

        for country in available_countries:
            m = labels == country
            n_nan, n_zero, n_bad, n_ok, n_covered, ratio = bad_stats(vals, m)
            if n_covered == 0:
                continue
            rows.append(
                {
                    "model": args.model,
                    "ssp": args.ssp,
                    "year": args.year,
                    "tech": tech,
                    "country": country,
                    "n_nan": n_nan,
                    "n_zero": n_zero,
                    "n_bad": n_bad,
                    "n_ok": n_ok,
                    "n_covered": n_covered,
                    "bad_ratio": f"{ratio:.6f}",
                }
            )

        m26 = np.isin(labels, available_countries)
        n_nan, n_zero, n_bad, n_ok, n_covered, ratio = bad_stats(vals, m26)
        rows.append(
            {
                "model": args.model,
                "ssp": args.ssp,
                "year": args.year,
                "tech": tech,
                "country": "ALL_26_COUNTRIES",
                "n_nan": n_nan,
                "n_zero": n_zero,
                "n_bad": n_bad,
                "n_ok": n_ok,
                "n_covered": n_covered,
                "bad_ratio": f"{ratio:.6f}",
            }
        )

        missing_countries = [c for c in P.COUNTRIES_26 if c not in available_countries]
        for country in missing_countries:
            n_stations = int(np.sum(labels == country))
            if n_stations:
                rows.append(
                    {
                        "model": args.model,
                        "ssp": args.ssp,
                        "year": args.year,
                        "tech": tech,
                        "country": country,
                        "n_nan": "",
                        "n_zero": "",
                        "n_bad": "",
                        "n_ok": "",
                        "n_covered": "",
                        "bad_ratio": "",
                        "status": "MISSING_BCSD",
                        "n_stations_in_country": n_stations,
                    }
                )

    for row in rows:
        row.setdefault("status", "OK")
        row.setdefault("n_stations_in_country", "")

    header = [
        "model", "ssp", "year", "tech", "country", "status",
        "n_nan", "n_zero", "n_bad", "n_ok", "n_covered", "bad_ratio", "n_stations_in_country",
    ]
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)

    print(f"-> {out_path}")
    for tech in ("wind", "solar"):
        sub = [r for r in rows if r["tech"] == tech and r["country"] != "ALL_26_COUNTRIES" and r["status"] == "OK"]
        sub.sort(key=lambda r: (float(r["bad_ratio"]), int(r["n_bad"])), reverse=True)
        print(f"\n{tech} top countries by bad_ratio:")
        print(f"{'country':<18}{'n_bad':>8}{'n_ok':>8}{'covered':>9}{'ratio':>10}")
        for r in sub[:15]:
            print(
                f"{r['country']:<18}{int(r['n_bad']):>8,}{int(r['n_ok']):>8,}"
                f"{int(r['n_covered']):>9,}{float(r['bad_ratio']):>9.2%}"
            )


if __name__ == "__main__":
    main()
