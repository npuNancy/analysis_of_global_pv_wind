#!/usr/bin/env python3
"""汇总三个 CMIP6 模式的逐国场站气象 0/NaN 统计。

处理顺序：
1. 对每个模式、每个国家，将 wind 与 solar 的计数相加；
2. 用合并后的 n_bad / n_covered 重新计算 bad_ratio；
3. 对各模式的合并结果计算算术均值。

若某模式缺少某国的 BCSD 数据，该模式不作为 0 参与均值，并通过
n_models_available 标明实际参与均值的模式数。
"""

from __future__ import annotations

import csv
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "outputs"
MODELS = ("NESM3", "MIROC-ES2H", "MPI-ESM1-2-HR")
SSP = "ssp126"
YEAR = 2050
METRICS = ("n_bad", "n_ok", "n_covered", "bad_ratio")
OUTPUT_PATH = OUTPUT_DIR / f"country_met_zero_nan_wind_solar_3model_mean_{SSP}_{YEAR}.csv"


def read_model(model: str) -> tuple[list[str], dict[str, dict[str, dict[str, str]]]]:
    """读取单个模式，返回国家顺序和 country -> tech -> row。"""
    path = OUTPUT_DIR / f"country_met_zero_nan_ratio_{model}_{SSP}_{YEAR}.csv"
    countries: list[str] = []
    rows_by_country: dict[str, dict[str, dict[str, str]]] = {}

    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country = row["country"]
            if country == "ALL_26_COUNTRIES":
                continue
            if country not in rows_by_country:
                countries.append(country)
                rows_by_country[country] = {}
            rows_by_country[country][row["tech"]] = row

    return countries, rows_by_country


def combine_technologies(
    rows_by_tech: dict[str, dict[str, str]] | None,
) -> dict[str, int | float] | None:
    """合并该国实际存在的 wind/solar 场站。

    源表不会为场站数为 0 的技术写行，因此该技术按 0 计；但只要已有行明确标记
    MISSING_BCSD，就将该模式-国家记为不可用。
    """
    if not rows_by_tech:
        return None

    rows = list(rows_by_tech.values())
    if any(row.get("status", "OK") != "OK" for row in rows):
        return None
    if any(not row.get(metric, "") for row in rows for metric in ("n_bad", "n_ok", "n_covered")):
        return None

    n_bad = sum(int(row["n_bad"]) for row in rows)
    n_ok = sum(int(row["n_ok"]) for row in rows)
    n_covered = sum(int(row["n_covered"]) for row in rows)
    bad_ratio = n_bad / n_covered if n_covered else 0.0
    return {
        "n_bad": n_bad,
        "n_ok": n_ok,
        "n_covered": n_covered,
        "bad_ratio": bad_ratio,
    }


def main() -> None:
    model_data: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    country_order: list[str] = []

    for model in MODELS:
        countries, rows_by_country = read_model(model)
        model_data[model] = rows_by_country
        for country in countries:
            if country not in country_order:
                country_order.append(country)

    fieldnames = ["country"]
    for model in MODELS:
        fieldnames.extend(f"{model}_{metric}" for metric in METRICS)
    fieldnames.extend(
        [
            "n_models_available",
            "mean_n_bad",
            "mean_n_ok",
            "mean_n_covered",
            "mean_bad_ratio",
        ]
    )

    output_rows = []
    for country in country_order:
        out: dict[str, str | int] = {"country": country}
        combined_by_model = {}

        for model in MODELS:
            combined = combine_technologies(model_data[model].get(country))
            combined_by_model[model] = combined
            for metric in METRICS:
                key = f"{model}_{metric}"
                if combined is None:
                    out[key] = ""
                elif metric == "bad_ratio":
                    out[key] = f"{combined[metric]:.6f}"
                else:
                    out[key] = str(combined[metric])

        available = [result for result in combined_by_model.values() if result is not None]
        out["n_models_available"] = len(available)
        for metric in METRICS:
            values = [float(result[metric]) for result in available]
            mean_value = sum(values) / len(values) if values else float("nan")
            key = f"mean_{metric}"
            if metric == "bad_ratio":
                out[key] = f"{mean_value:.6f}"
            else:
                out[key] = f"{mean_value:.2f}"

        output_rows.append(out)

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"-> {OUTPUT_PATH}")
    print(f"countries: {len(output_rows)}")
    print(
        "model availability: "
        + ", ".join(
            f"{n} models={sum(int(row['n_models_available']) == n for row in output_rows)} countries"
            for n in range(1, len(MODELS) + 1)
        )
    )


if __name__ == "__main__":
    main()
