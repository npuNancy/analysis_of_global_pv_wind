#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate mock data for RQ1–RQ5 of the wind/solar SSP-risk study.

Design principle:
- Data are organized by research question, not by figure.
- Each RQ has its own folder.
- Tables are internally coherent enough for testing analysis pipelines.
- Values are mock/synthetic and should not be interpreted as real estimates.

Folder structure:
mock_RQ_data/
  RQ1_future_generation/
  RQ2_extreme_weather_exposure/
  RQ3_generation_losses/
  RQ4_ssp_tradeoff_decomposition/
  RQ5_regional_hotspots/

python generate_mock_data.py

"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

COUNTRIES = [
    "Netherlands",
    "Ireland",
    "South Korea",
    "Denmark",
    "Portugal",
    "Austria",
    "Greece",
    "Romania",
    "United Kingdom",
    "Poland",
    "Germany",
    "Vietnam",
    "Egypt",
    "South Africa",
    "Spain",
    "Italy",
    "Turkey",
    "France",
    "Sweden",
    "Ukraine",
    "Japan",
    "Chile",
    "México",
    "India",
    "Australia",
    "Brazil",
    "China",
    "America",
]

SSPS = ["ssp126", "ssp245", "ssp585"]
YEARS = [2030, 2040, 2050]
TECHS = ["wind", "solar"]

EVENTS_BY_TECH = {
    "wind": ["heatwave", "windstorm"],
    "solar": ["rainstorm", "coldwave", "freezing_rain"],
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def make_country_base(rng: np.random.Generator) -> pd.DataFrame:
    """Country-level base features used by all RQs."""
    rows = []
    for country in COUNTRIES:
        # Roughly reflect that China/America/India/Australia/Brazil are larger systems.
        scale_boost = {
            "China": 7.0,
            "America": 6.0,
            "India": 5.0,
            "Australia": 3.0,
            "Brazil": 3.0,
            "Germany": 2.0,
            "France": 1.8,
            "United Kingdom": 1.6,
            "Japan": 1.8,
        }.get(country, 1.0)

        lat_center = rng.uniform(-35, 60)
        lon_center = rng.uniform(-120, 140)

        rows.append(
            {
                "country": country,
                "lat_center": lat_center,
                "lon_center": lon_center,
                "system_scale_index": scale_boost * rng.lognormal(mean=0.0, sigma=0.25),
                "solar_resource_index": np.clip(rng.normal(1.0 + max(0, 30 - abs(lat_center)) / 100, 0.15), 0.65, 1.45),
                "wind_resource_index": np.clip(rng.normal(1.0 + abs(lat_center) / 140, 0.18), 0.65, 1.55),
                "extreme_weather_index": np.clip(rng.normal(1.0 + abs(lat_center) / 120, 0.22), 0.55, 1.75),
            }
        )

    return pd.DataFrame(rows)


def deployment_capacity_multiplier(deploy_ssp: str, year: int) -> float:
    """More renewable deployment under lower-emission pathways."""
    year_factor = {2030: 1.0, 2040: 1.9, 2050: 3.0}[year]
    ssp_factor = {
        "ssp126": 1.45,
        "ssp245": 1.00,
        "ssp585": 0.55,
    }[deploy_ssp]
    return year_factor * ssp_factor


def climate_hazard_multiplier(climate_ssp: str, year: int) -> float:
    """Stronger climate hazards under higher-emission pathways."""
    year_progress = {2030: 0.35, 2040: 0.65, 2050: 1.0}[year]
    ssp_factor = {
        "ssp126": 0.80,
        "ssp245": 1.00,
        "ssp585": 1.35,
    }[climate_ssp]
    return 1.0 + (ssp_factor - 1.0) * year_progress


def climate_cf_multiplier(climate_ssp: str, year: int, tech: str) -> float:
    """
    Mock climate effect on average CF.
    Not necessarily monotonic for all regions in real data.
    Here we impose a weak global tendency.
    """
    year_progress = {2030: 0.35, 2040: 0.65, 2050: 1.0}[year]
    if tech == "solar":
        # Higher warming slightly reduces PV efficiency, but effect is weak.
        ssp_effect = {"ssp126": 0.005, "ssp245": -0.005, "ssp585": -0.025}[climate_ssp]
    else:
        # Wind climate response is uncertain; impose weak negative effect under high emissions.
        ssp_effect = {"ssp126": 0.000, "ssp245": -0.010, "ssp585": -0.035}[climate_ssp]
    return 1.0 + ssp_effect * year_progress


def generate_station_catalog(country_base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    Create station/site catalog for all deployment SSPs and years.
    Each row is a future selected wind/solar station.
    """
    rows = []
    station_counter = 0

    for _, c in country_base.iterrows():
        for deploy_ssp in SSPS:
            for year in YEARS:
                for tech in TECHS:
                    cap_mult = deployment_capacity_multiplier(deploy_ssp, year)
                    resource_idx = c[f"{tech}_resource_index"]

                    expected_n = int(
                        np.clip(c["system_scale_index"] * cap_mult * (4.0 if tech == "solar" else 3.0), 3, 180)
                    )

                    n_sites = rng.poisson(expected_n)
                    n_sites = max(2, n_sites)

                    for _ in range(n_sites):
                        station_counter += 1

                        lat = c["lat_center"] + rng.normal(0, 2.5)
                        lon = c["lon_center"] + rng.normal(0, 3.0)

                        if tech == "solar":
                            capacity_mw = rng.lognormal(mean=np.log(180), sigma=0.55)
                            base_cf = np.clip(rng.normal(0.18 * resource_idx, 0.035), 0.08, 0.34)
                        else:
                            capacity_mw = rng.lognormal(mean=np.log(220), sigma=0.55)
                            base_cf = np.clip(rng.normal(0.32 * resource_idx, 0.065), 0.12, 0.58)

                        rows.append(
                            {
                                "station_id": f"S{station_counter:07d}",
                                "country": c["country"],
                                "deploy_ssp": deploy_ssp,
                                "target_year": year,
                                "technology": tech,
                                "lat": lat,
                                "lon": lon,
                                "capacity_mw": capacity_mw,
                                "base_capacity_factor": base_cf,
                                "resource_index": resource_idx,
                                "station_extreme_weather_index": np.clip(
                                    c["extreme_weather_index"] * rng.lognormal(0, 0.18), 0.3, 2.5
                                ),
                            }
                        )

    return pd.DataFrame(rows)


def generate_rq1(
    outdir: Path,
    stations: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    RQ1: Future wind/solar generation.
    Needed data:
    - station catalog
    - station annual generation under climate SSP
    - monthly CF/generation summaries
    - country annual generation summary
    """
    ensure_dir(outdir)

    station_rows = []
    monthly_rows = []

    for _, s in stations.iterrows():
        for climate_ssp in SSPS:
            cf_mean = s["base_capacity_factor"] * climate_cf_multiplier(
                climate_ssp, int(s["target_year"]), s["technology"]
            )
            cf_mean *= rng.lognormal(0, 0.025)
            cf_mean = float(np.clip(cf_mean, 0.02, 0.72))

            annual_generation_mwh = s["capacity_mw"] * 8760 * cf_mean

            station_rows.append(
                {
                    "station_id": s["station_id"],
                    "country": s["country"],
                    "technology": s["technology"],
                    "deploy_ssp": s["deploy_ssp"],
                    "climate_ssp": climate_ssp,
                    "target_year": s["target_year"],
                    "capacity_mw": s["capacity_mw"],
                    "annual_capacity_factor": cf_mean,
                    "annual_generation_mwh": annual_generation_mwh,
                }
            )

            for month in range(1, 13):
                seasonal = 1.0
                if s["technology"] == "solar":
                    seasonal = 1.0 + 0.18 * np.sin((month - 3) / 12 * 2 * np.pi)
                else:
                    seasonal = 1.0 + 0.12 * np.cos((month - 1) / 12 * 2 * np.pi)

                monthly_cf = np.clip(cf_mean * seasonal * rng.lognormal(0, 0.04), 0.01, 0.85)
                days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
                monthly_generation_mwh = s["capacity_mw"] * days * 24 * monthly_cf

                monthly_rows.append(
                    {
                        "station_id": s["station_id"],
                        "country": s["country"],
                        "technology": s["technology"],
                        "deploy_ssp": s["deploy_ssp"],
                        "climate_ssp": climate_ssp,
                        "target_year": s["target_year"],
                        "month": month,
                        "capacity_mw": s["capacity_mw"],
                        "monthly_capacity_factor": monthly_cf,
                        "monthly_generation_mwh": monthly_generation_mwh,
                    }
                )

    station_generation = pd.DataFrame(station_rows)
    monthly_generation = pd.DataFrame(monthly_rows)

    country_generation = station_generation.groupby(
        ["country", "technology", "deploy_ssp", "climate_ssp", "target_year"], as_index=False
    ).agg(
        capacity_mw=("capacity_mw", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
    )
    country_generation["capacity_weighted_cf"] = country_generation["annual_generation_mwh"] / (
        country_generation["capacity_mw"] * 8760
    )

    stations.to_csv(outdir / "station_catalog.csv", index=False)
    station_generation.to_csv(outdir / "station_annual_generation.csv", index=False)
    monthly_generation.to_csv(outdir / "station_monthly_generation.csv", index=False)
    country_generation.to_csv(outdir / "country_annual_generation.csv", index=False)

    return station_generation, monthly_generation, country_generation


def generate_rq2(
    outdir: Path,
    country_base: pd.DataFrame,
    stations: pd.DataFrame,
    station_generation: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    RQ2: Extreme-weather hazard and station exposure.
    Needed data:
    - country-level hazard statistics
    - station-event exposure
    - country-event exposure aggregation
    """
    ensure_dir(outdir)

    hazard_rows = []
    exposure_rows = []

    event_base = {
        "heatwave": {"base_hours": 95, "base_intensity": 1.8},
        "windstorm": {"base_hours": 45, "base_intensity": 2.4},
        "rainstorm": {"base_hours": 75, "base_intensity": 2.0},
        "coldwave": {"base_hours": 65, "base_intensity": 1.7},
        "freezing_rain": {"base_hours": 22, "base_intensity": 1.5},
    }

    for _, c in country_base.iterrows():
        for climate_ssp in SSPS:
            for year in YEARS:
                hmult = climate_hazard_multiplier(climate_ssp, year)
                for tech in TECHS:
                    for event in EVENTS_BY_TECH[tech]:
                        base = event_base[event]
                        freq_hours = base["base_hours"] * c["extreme_weather_index"] * hmult * rng.lognormal(0, 0.25)
                        freq_hours = float(np.clip(freq_hours, 1, 900))

                        duration_mean_hours = float(np.clip(rng.normal(freq_hours / 18, 3.0), 1.0, 120.0))
                        intensity_index = float(
                            np.clip(
                                base["base_intensity"] * c["extreme_weather_index"] * hmult * rng.lognormal(0, 0.18),
                                0.2,
                                8.0,
                            )
                        )
                        affected_area_km2 = float(
                            c["system_scale_index"] * 5e4 * sigmoid(freq_hours / 120) * rng.lognormal(0, 0.35)
                        )

                        hazard_rows.append(
                            {
                                "country": c["country"],
                                "climate_ssp": climate_ssp,
                                "target_year": year,
                                "technology": tech,
                                "event_type": event,
                                "event_frequency_hours_per_year": freq_hours,
                                "mean_event_duration_hours": duration_mean_hours,
                                "event_intensity_index": intensity_index,
                                "affected_area_km2": affected_area_km2,
                            }
                        )

    hazard = pd.DataFrame(hazard_rows)

    # Station exposure links hazards to deployed stations.
    # Use same deployment SSP and target year from station catalog.
    for _, s in stations.iterrows():
        for climate_ssp in SSPS:
            for event in EVENTS_BY_TECH[s["technology"]]:
                hz = hazard[
                    (hazard["country"] == s["country"])
                    & (hazard["climate_ssp"] == climate_ssp)
                    & (hazard["target_year"] == s["target_year"])
                    & (hazard["technology"] == s["technology"])
                    & (hazard["event_type"] == event)
                ].iloc[0]

                local_exposure_factor = s["station_extreme_weather_index"] * rng.lognormal(0, 0.22)
                exposed_hours = float(np.clip(hz["event_frequency_hours_per_year"] * local_exposure_factor, 0, 1500))

                gen_row = station_generation[
                    (station_generation["station_id"] == s["station_id"])
                    & (station_generation["climate_ssp"] == climate_ssp)
                ].iloc[0]

                exposed_generation_mwh = (
                    gen_row["annual_generation_mwh"] * exposed_hours / 8760 * rng.lognormal(0, 0.10)
                )

                exposure_rows.append(
                    {
                        "station_id": s["station_id"],
                        "country": s["country"],
                        "technology": s["technology"],
                        "deploy_ssp": s["deploy_ssp"],
                        "climate_ssp": climate_ssp,
                        "target_year": s["target_year"],
                        "event_type": event,
                        "capacity_mw": s["capacity_mw"],
                        "exposed_hours": exposed_hours,
                        "exposed_capacity_mw_hours": s["capacity_mw"] * exposed_hours,
                        "exposed_generation_mwh": exposed_generation_mwh,
                        "event_intensity_index": hz["event_intensity_index"],
                    }
                )

    station_exposure = pd.DataFrame(exposure_rows)

    country_exposure = station_exposure.groupby(
        ["country", "technology", "deploy_ssp", "climate_ssp", "target_year", "event_type"], as_index=False
    ).agg(
        exposed_capacity_mw_hours=("exposed_capacity_mw_hours", "sum"),
        exposed_generation_mwh=("exposed_generation_mwh", "sum"),
        mean_exposed_hours=("exposed_hours", "mean"),
        mean_event_intensity_index=("event_intensity_index", "mean"),
    )

    hazard.to_csv(outdir / "country_event_hazard.csv", index=False)
    station_exposure.to_csv(outdir / "station_event_exposure.csv", index=False)
    country_exposure.to_csv(outdir / "country_event_exposure.csv", index=False)

    return hazard, station_exposure, country_exposure


def generate_rq3(
    outdir: Path,
    station_generation: pd.DataFrame,
    station_exposure: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    RQ3: Generation losses caused by extreme weather.
    Needed data:
    - station-event losses
    - country-event loss summary
    """
    ensure_dir(outdir)

    vulnerability_base = {
        "heatwave": 0.08,
        "windstorm": 0.18,
        "rainstorm": 0.14,
        "coldwave": 0.05,
        "freezing_rain": 0.22,
    }

    loss_rows = []

    for _, e in station_exposure.iterrows():
        annual = station_generation[
            (station_generation["station_id"] == e["station_id"])
            & (station_generation["deploy_ssp"] == e["deploy_ssp"])
            & (station_generation["climate_ssp"] == e["climate_ssp"])
        ].iloc[0]

        base_vul = vulnerability_base[e["event_type"]]
        vulnerability = np.clip(
            base_vul * (1.0 + 0.10 * e["event_intensity_index"]) * rng.lognormal(0, 0.25), 0.005, 0.75
        )

        loss_mwh = e["exposed_generation_mwh"] * vulnerability
        loss_rate_annual = loss_mwh / max(annual["annual_generation_mwh"], 1e-9)
        conditional_loss_rate = loss_mwh / max(e["exposed_generation_mwh"], 1e-9)

        cf_normal_event = annual["annual_capacity_factor"] * rng.uniform(0.85, 1.15)
        cf_actual_event = max(cf_normal_event * (1 - conditional_loss_rate), 0.0)

        loss_rows.append(
            {
                "station_id": e["station_id"],
                "country": e["country"],
                "technology": e["technology"],
                "deploy_ssp": e["deploy_ssp"],
                "climate_ssp": e["climate_ssp"],
                "target_year": e["target_year"],
                "event_type": e["event_type"],
                "capacity_mw": e["capacity_mw"],
                "annual_generation_mwh": annual["annual_generation_mwh"],
                "exposed_generation_mwh": e["exposed_generation_mwh"],
                "cf_normal_during_event": cf_normal_event,
                "cf_actual_during_event": cf_actual_event,
                "vulnerability_loss_fraction": vulnerability,
                "loss_mwh": loss_mwh,
                "annual_loss_rate": loss_rate_annual,
                "conditional_loss_rate": conditional_loss_rate,
                "unit_capacity_loss_mwh_per_mw": loss_mwh / max(e["capacity_mw"], 1e-9),
            }
        )

    station_losses = pd.DataFrame(loss_rows)

    country_losses = station_losses.groupby(
        ["country", "technology", "deploy_ssp", "climate_ssp", "target_year", "event_type"], as_index=False
    ).agg(
        capacity_mw=("capacity_mw", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
        exposed_generation_mwh=("exposed_generation_mwh", "sum"),
        loss_mwh=("loss_mwh", "sum"),
    )
    country_losses["annual_loss_rate"] = country_losses["loss_mwh"] / country_losses["annual_generation_mwh"]
    country_losses["conditional_loss_rate"] = country_losses["loss_mwh"] / country_losses[
        "exposed_generation_mwh"
    ].replace(0, np.nan)
    country_losses["unit_capacity_loss_mwh_per_mw"] = country_losses["loss_mwh"] / country_losses["capacity_mw"]

    station_losses.to_csv(outdir / "station_event_losses.csv", index=False)
    country_losses.to_csv(outdir / "country_event_losses.csv", index=False)

    return station_losses, country_losses


def generate_rq4(
    outdir: Path,
    country_losses: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    RQ4: SSP trade-off decomposition.
    Needed data:
    - full W x P risk matrix
    - decomposition of total difference into climate, deployment, interaction effects
    """
    ensure_dir(outdir)

    # Aggregate event-level losses to risk matrix.
    risk_matrix = country_losses.groupby(
        ["country", "technology", "target_year", "climate_ssp", "deploy_ssp"], as_index=False
    ).agg(
        capacity_mw=("capacity_mw", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
        loss_mwh=("loss_mwh", "sum"),
    )

    risk_matrix["loss_rate"] = risk_matrix["loss_mwh"] / risk_matrix["annual_generation_mwh"]
    risk_matrix["unit_capacity_loss_mwh_per_mw"] = risk_matrix["loss_mwh"] / risk_matrix["capacity_mw"]
    risk_matrix["unit_generation_loss_mwh_per_gwh"] = risk_matrix["loss_mwh"] / (
        risk_matrix["annual_generation_mwh"] / 1000
    )

    # Decompose SSP245 and SSP585 relative to SSP126.
    decomp_rows = []
    for (country, tech, year), g in risk_matrix.groupby(["country", "technology", "target_year"]):

        def get_loss(w: str, p: str) -> float:
            row = g[(g["climate_ssp"] == w) & (g["deploy_ssp"] == p)]
            if len(row) == 0:
                return np.nan
            return float(row["loss_mwh"].iloc[0])

        base = get_loss("ssp126", "ssp126")

        for target_ssp in ["ssp245", "ssp585"]:
            total = get_loss(target_ssp, target_ssp) - base
            climate_effect = get_loss(target_ssp, "ssp126") - base
            deployment_effect = get_loss("ssp126", target_ssp) - base
            interaction_effect = total - climate_effect - deployment_effect

            decomp_rows.append(
                {
                    "country": country,
                    "technology": tech,
                    "target_year": year,
                    "reference_ssp": "ssp126",
                    "target_ssp": target_ssp,
                    "risk_metric": "loss_mwh",
                    "baseline_risk": base,
                    "target_total_risk": get_loss(target_ssp, target_ssp),
                    "total_change": total,
                    "climate_effect": climate_effect,
                    "deployment_effect": deployment_effect,
                    "interaction_effect": interaction_effect,
                }
            )

    decomposition = pd.DataFrame(decomp_rows)

    risk_matrix.to_csv(outdir / "ssp_climate_deployment_risk_matrix.csv", index=False)
    decomposition.to_csv(outdir / "risk_decomposition.csv", index=False)

    return risk_matrix, decomposition


def generate_rq5(
    outdir: Path,
    risk_matrix: pd.DataFrame,
    country_losses: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    RQ5: Regional hotspots and technology/event vulnerabilities.
    Needed data:
    - country risk profile
    - country-event contribution
    - country-technology vulnerability
    """
    ensure_dir(outdir)

    # Use diagonal SSP combinations as the "actual SSP pathway" results.
    actual = risk_matrix[risk_matrix["climate_ssp"] == risk_matrix["deploy_ssp"]].copy()
    actual = actual.rename(columns={"climate_ssp": "ssp"})
    actual = actual.drop(columns=["deploy_ssp"])

    country_profile = actual.groupby(["country", "ssp", "target_year"], as_index=False).agg(
        capacity_mw=("capacity_mw", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
        loss_mwh=("loss_mwh", "sum"),
    )
    country_profile["loss_rate"] = country_profile["loss_mwh"] / country_profile["annual_generation_mwh"]
    country_profile["unit_capacity_loss_mwh_per_mw"] = country_profile["loss_mwh"] / country_profile["capacity_mw"]

    # Risk classification by median generation and median loss rate within each SSP-year.
    classes = []
    for (ssp, year), g in country_profile.groupby(["ssp", "target_year"]):
        gen_med = g["annual_generation_mwh"].median()
        risk_med = g["loss_rate"].median()

        for idx, row in g.iterrows():
            high_gen = row["annual_generation_mwh"] >= gen_med
            high_risk = row["loss_rate"] >= risk_med

            if high_gen and high_risk:
                cls = "high_generation_high_risk"
            elif high_gen and not high_risk:
                cls = "high_generation_low_risk"
            elif (not high_gen) and high_risk:
                cls = "low_generation_high_risk"
            else:
                cls = "low_generation_low_risk"

            classes.append((idx, cls))

    class_map = dict(classes)
    country_profile["risk_class"] = country_profile.index.map(class_map)

    # Event contributions under diagonal SSP pathways.
    actual_losses = country_losses[country_losses["climate_ssp"] == country_losses["deploy_ssp"]].copy()
    actual_losses = actual_losses.rename(columns={"climate_ssp": "ssp"})
    actual_losses = actual_losses.drop(columns=["deploy_ssp"])

    event_contribution = actual_losses.groupby(
        ["country", "ssp", "target_year", "technology", "event_type"], as_index=False
    ).agg(
        loss_mwh=("loss_mwh", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
        capacity_mw=("capacity_mw", "sum"),
    )

    total_loss = (
        event_contribution.groupby(["country", "ssp", "target_year"], as_index=False)["loss_mwh"]
        .sum()
        .rename(columns={"loss_mwh": "country_total_loss_mwh"})
    )
    event_contribution = event_contribution.merge(total_loss, on=["country", "ssp", "target_year"], how="left")
    event_contribution["event_loss_contribution_fraction"] = event_contribution["loss_mwh"] / event_contribution[
        "country_total_loss_mwh"
    ].replace(0, np.nan)

    tech_vulnerability = actual_losses.groupby(["country", "ssp", "target_year", "technology"], as_index=False).agg(
        capacity_mw=("capacity_mw", "sum"),
        annual_generation_mwh=("annual_generation_mwh", "sum"),
        exposed_generation_mwh=("exposed_generation_mwh", "sum"),
        loss_mwh=("loss_mwh", "sum"),
    )
    tech_vulnerability["annual_loss_rate"] = (
        tech_vulnerability["loss_mwh"] / tech_vulnerability["annual_generation_mwh"]
    )
    tech_vulnerability["conditional_loss_rate"] = tech_vulnerability["loss_mwh"] / tech_vulnerability[
        "exposed_generation_mwh"
    ].replace(0, np.nan)
    tech_vulnerability["unit_capacity_loss_mwh_per_mw"] = (
        tech_vulnerability["loss_mwh"] / tech_vulnerability["capacity_mw"]
    )

    country_profile.to_csv(outdir / "country_risk_profile.csv", index=False)
    event_contribution.to_csv(outdir / "country_event_contribution.csv", index=False)
    tech_vulnerability.to_csv(outdir / "country_technology_vulnerability.csv", index=False)

    return country_profile, event_contribution, tech_vulnerability


def write_metadata(base_outdir: Path) -> None:
    metadata = {
        "description": "Synthetic mock data for RQ1-RQ5 of SSP wind/solar generation and extreme-weather risk analysis.",
        "note": "Values are randomly generated for workflow testing only. They are not real estimates.",
        "ssps": SSPS,
        "years": YEARS,
        "technologies": TECHS,
        "events_by_technology": EVENTS_BY_TECH,
        "research_questions": {
            "RQ1": "Future wind and solar generation under SSP climate and deployment pathways.",
            "RQ2": "Extreme-weather hazard and station exposure.",
            "RQ3": "Extreme-weather-induced generation losses.",
            "RQ4": "Decomposition of SSP risk differences into climate, deployment, and interaction effects.",
            "RQ5": "Regional hotspots, technology-specific vulnerabilities, and event contribution.",
        },
    }
    with open(base_outdir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", type=str, default="mock_RQ_data")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    base_outdir = Path(args.outdir)
    ensure_dir(base_outdir)

    country_base = make_country_base(rng)
    stations = generate_station_catalog(country_base, rng)

    country_base.to_csv(base_outdir / "country_base_features.csv", index=False)

    rq1_dir = base_outdir / "RQ1_future_generation"
    rq2_dir = base_outdir / "RQ2_extreme_weather_exposure"
    rq3_dir = base_outdir / "RQ3_generation_losses"
    rq4_dir = base_outdir / "RQ4_ssp_tradeoff_decomposition"
    rq5_dir = base_outdir / "RQ5_regional_hotspots"

    station_generation, monthly_generation, country_generation = generate_rq1(rq1_dir, stations, rng)

    hazard, station_exposure, country_exposure = generate_rq2(rq2_dir, country_base, stations, station_generation, rng)

    station_losses, country_losses = generate_rq3(rq3_dir, station_generation, station_exposure, rng)

    risk_matrix, decomposition = generate_rq4(rq4_dir, country_losses)

    country_profile, event_contribution, tech_vulnerability = generate_rq5(rq5_dir, risk_matrix, country_losses)

    write_metadata(base_outdir)

    print(f"[OK] Mock data generated at: {base_outdir.resolve()}")
    print("")
    print("Created folders:")
    for folder in [rq1_dir, rq2_dir, rq3_dir, rq4_dir, rq5_dir]:
        print(f"  - {folder}")

    print("")
    print("Main files:")
    for path in sorted(base_outdir.rglob("*.csv")):
        print(f"  - {path}")


if __name__ == "__main__":
    main()
