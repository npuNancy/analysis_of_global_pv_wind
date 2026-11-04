"""Eleven global capacity, exposure, loss and generation trend triptychs."""
import hashlib
import json
import os
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, SSPS, SSP_COLORS
from paper_figures.common.plotting import configure, export_panel_png

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DATA = OUT / "source_data"
FIG1 = ROOT / "paper_figures/main/fig01_extreme_events/outputs/source_data"
FIG2 = ROOT / "paper_figures/main/fig02_generation_loss/outputs/source_data"
SUIT = ROOT / "paper_figures/supplementary/suitable_grid_extreme/outputs/source_data"
PREP = ROOT / "paper_figures/prepare/outputs"
TECHS = ["wind+solar", "wind", "solar"]
LABELS = ["Wind + solar", "Wind", "Solar"]
PROVENANCE, RESULTS, FITS = [], [], []
PANEL_Y_STEPS = {
    "grid_exposure": (1., 1., 1.),
    "suitable_grid_exposure": (.5, .5, .5),
    "suitable_grid_unit_loss": (2., 2., 2.),
    "station_loss_fraction": (.25, .25, .25),
    "station_unit_generation": (100., 100., 25.),
}


def read(path):
    d = pd.read_csv(path)
    PROVENANCE.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rows=len(d)))
    return d


def combine(frame, keys, fields):
    assert not frame.duplicated(keys + ["tech"]).any()
    assert frame.groupby(keys).tech.nunique().eq(2).all()
    joint = frame.groupby(keys, as_index=False)[fields].sum(min_count=2)
    joint["tech"] = "wind+solar"
    return pd.concat([frame, joint], ignore_index=True)


def verify(frame, annual, capacity=False):
    times = range(2030, 2060) if annual else (2030, 2040, 2050)
    models = ["catalogue"] if capacity else MODELS
    keys = ["model", "climate_ssp", "tech", "time"]
    assert not frame.duplicated(keys).any()
    assert set(frame[keys].itertuples(index=False, name=None)) == set(product(models, SSPS, TECHS, times))
    assert np.isfinite(frame.value).all()
    assert frame.denominator.gt(0).all()
    np.testing.assert_allclose(frame.value, frame.numerator / frame.denominator, rtol=1e-12)


def emit(frame, name, scope, metric, ylabel, unit, annual, method, source, capacity=False):
    frame = frame.copy()
    frame["scope"], frame["metric"], frame["unit"] = scope, metric, unit
    frame["station_ssp"] = frame.climate_ssp if scope == "station" else "not_applicable"
    frame["event"] = "all" if "exposure" in name or "loss" in name else "not_applicable"
    frame["snapshot"] = frame.time // 10 * 10
    frame["aggregation"] = method
    verify(frame, annual, capacity)
    frame.to_csv(DATA / (name + "_models.csv"), index=False)
    display = frame.groupby(["climate_ssp", "tech", "time"]).value.agg(
        mean="mean", minimum="min", maximum="max", n_models="count").reset_index()
    assert display.n_models.eq(1 if capacity else 4).all()
    display.to_csv(DATA / (name + "_display.csv"), index=False)
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    configure()
    plt.rcParams.update({"font.size": 8})
    independent_y = name in PANEL_Y_STEPS
    fig, axes = plt.subplots(1, 3, figsize=(240/25.4, 85/25.4), sharey=not independent_y)
    fig.subplots_adjust(left=.10, right=.985, bottom=.23, top=.78,
                        wspace=.32 if independent_y else .14)
    fits = []
    for ax, tech, title in zip(axes, TECHS, LABELS):
        for ssp, marker in zip(SSPS, ("o", "s", "^")):
            g = display[(display.tech == tech) & (display.climate_ssp == ssp)].sort_values("time")
            x, y = g.time.to_numpy(float), g["mean"].to_numpy(float)
            ax.plot(x, y, color=SSP_COLORS[ssp], lw=1.15,
                    marker=None if annual else marker, ms=3.5)
            if annual:
                slope, intercept = np.polyfit(x - 2030, y, 1)
                pred = intercept + slope * (x - 2030)
                ax.plot(x, pred, color=SSP_COLORS[ssp], lw=1, ls="--")
                residual = np.sum((y-pred)**2); total = np.sum((y-y.mean())**2)
                fits.append(dict(figure=name, tech=tech, climate_ssp=ssp, start=2030, end=2059,
                                 n_years=30, slope_per_year=float(slope), fitted_value_2030=float(intercept),
                                 r_squared=float(1-residual/total) if total > 0 else None))
        ax.set_title(title, fontsize=9, pad=8)
        if annual:
            ax.set_xticks([2030, 2040, 2050, 2059]); ax.set_xlim(2029, 2060)
            ax.set_xlabel("Year")
        else:
            ax.set_xticks([2030, 2040, 2050], ["2030s", "2040s", "2050s"])
            ax.set_xlim(2028, 2052); ax.set_xlabel("Decade")
        ax.grid(axis="y", color=".9", lw=.45)
        ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 5), useMathText=True)
        ax.tick_params(length=3, width=.7)
    axis_metadata = []
    if independent_y:
        for ax, tech, step in zip(axes, TECHS, PANEL_Y_STEPS[name]):
            values = np.concatenate([line.get_ydata() for line in ax.lines])
            padding = max(float(np.ptp(values)) * .08, step * .15)
            lower = np.floor((values.min() - padding) / step) * step
            upper = np.ceil((values.max() + padding) / step) * step
            ax.set_yticks(np.arange(lower, upper + step * .5, step))
            ax.set_ylim(lower, upper)
            assert lower < values.min() and upper > values.max()
            axis_metadata.append(dict(tech=tech, limits=[float(lower), float(upper)], tick_step=step))
        fig.text(.54, .875, "Independent y-axis ranges", ha="center", fontsize=7, color=".4")
    axes[0].set_ylabel(ylabel, labelpad=7)
    scope_title = {"grid":"Global grid", "suitable_grid":"Global suitable grid", "station":"Global stations"}[scope]
    fig.suptitle(scope_title + " | " + metric, fontsize=10, y=.97)
    handles = [Line2D([0],[0],color=SSP_COLORS[s],lw=1.5,label=s.upper()) for s in SSPS]
    if annual:
        handles += [Line2D([0],[0],color=".4",ls="--",lw=1,label="2030–2059 linear fit")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.53,.015),
               ncol=len(handles), fontsize=8)
    qa = export_panel_png(fig, OUT / (name + ".png"))
    if annual:
        pd.DataFrame(fits).to_csv(DATA / (name + "_fits.csv"), index=False)
        FITS.extend(fits)
    RESULTS.append(dict(name=name, scope=scope, metric=metric, unit=unit, annual=annual,
                        status="complete", method=method, original_sources=source,
                        independent_y=independent_y, panel_y_axes=axis_metadata,
                        model_table=str(DATA/(name+"_models.csv")),
                        display_table=str(DATA/(name+"_display.csv")), figure=str(OUT/(name+".png")), qa=qa))
    print("Rendered", name, flush=True)


def ratio(frame, numerator, denominator, time):
    f = frame.copy()
    f["numerator"] = numerator
    f["denominator"] = denominator
    f["value"] = f.numerator / f.denominator
    f["time"] = f[time].astype(int)
    return f


def main():
    OUT.mkdir(parents=True, exist_ok=True); DATA.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".mplconfig"))
    keys = ["model", "climate_ssp", "snapshot", "year"]
    cap_path = PREP / "catalogues/capacity_by_country.csv"
    cap = read(cap_path).groupby(["station_ssp","tech","snapshot"],as_index=False).capacity_mw.sum()
    cap = cap[cap.snapshot.isin([2030,2040,2050])].copy()
    cap["climate_ssp"], cap["model"] = cap.station_ssp, "catalogue"
    cap = combine(cap, ["model","climate_ssp","snapshot"], ["capacity_mw"])
    emit(ratio(cap,cap.capacity_mw,1e6,"snapshot"), "station_capacity", "station", "Installed capacity",
         "Installed capacity (TW)", "TW", False, "Total catalogue capacity snapshot; not cumulative additions",
         [str(cap_path)], capacity=True)

    union_path = DATA / "grid_union_decadal.csv"
    union = read(union_path)
    grid_path = FIG1 / "panel_cd_grid.csv"
    grid = read(grid_path)
    assert grid.event.eq("all").all()
    grid = ratio(grid,grid.area_event_hours/24,grid.valid_area_km2,"snapshot")
    u = union[union.scope.eq("grid")].copy()
    grid = pd.concat([grid,ratio(u,u.numerator,u.denominator,"snapshot")],ignore_index=True)
    emit(grid,"grid_exposure","grid","Area-weighted exposure","Exposure (days yr⁻¹)","days/year",False,
         "Native-cell area weights; wind+solar uses paired-interval time union with each cell area counted once",
         [str(grid_path),str(union_path)])

    suitable_path = SUIT / "annual_primary.csv"
    suitable = read(suitable_path)
    suitable = suitable[suitable.event.eq("all") & suitable.weighting.eq("area")].copy()
    suitable = suitable.groupby(["model","climate_ssp","tech","snapshot"],as_index=False)[
        ["numerator","denominator"]].mean()
    u = union[union.scope.eq("suitable_grid")].copy()
    suitable = pd.concat([suitable,u],ignore_index=True)
    emit(ratio(suitable,suitable.numerator,suitable.denominator,"snapshot"),"suitable_grid_exposure",
         "suitable_grid","Area-weighted exposure","Exposure (days yr⁻¹)","days/year",False,
         "Area weighted; suitable spatial union counted once; events restricted to applicable technologies",
         [str(suitable_path),str(union_path)])

    exposure_path = FIG1 / "panel_cd_coverage.csv"
    ex = read(exposure_path)
    assert ex.event.eq("all").all() and ex.country.eq("GLOBAL").all()
    assert ex.climate_ssp.eq(ex.station_ssp).all()
    np.testing.assert_allclose(ex.E,ex.capacity_event_hours/ex.capacity_mw)
    # Catalogue capacity used in the capacity figure; valid capacity used for exposure.
    cap_check = ex.merge(cap[cap.tech.ne("wind+solar")][["climate_ssp","tech","snapshot","capacity_mw"]],
                        on=["climate_ssp","tech","snapshot"],suffixes=("","_catalogue"),validate="many_to_one")
    np.testing.assert_allclose(cap_check.catalogue_capacity_mw,cap_check.capacity_mw_catalogue)
    ex = combine(ex,["model","climate_ssp","snapshot"],
                 ["capacity_mw","capacity_event_hours","catalogue_capacity_mw","capacity_valid_hours"])
    emit(ratio(ex,ex.capacity_event_hours/24,1.,"snapshot"),"station_exposure_total",
         "station","Capacity-weighted exposure total","Exposure total (MW days yr⁻¹)","MW days/year",False,
         "Sum capacity times annual observed event-union days; mean of ten years",
         [str(exposure_path)])
    emit(ratio(ex,ex.capacity_event_hours/24,ex.capacity_mw,"snapshot"),"station_exposure_mean",
         "station","Capacity-weighted mean exposure","Exposure (days yr⁻¹)","days/year",False,
         "Sum capacity-event days divided by matching valid capacity; mean of ten years",
         [str(exposure_path)])

    loss_path = FIG2 / "panel_ab.csv"
    loss = read(loss_path)
    assert loss.support.eq("common").all() and loss.event.eq("all").all()
    assert loss.country.eq("GLOBAL").all() and loss.climate_ssp.eq(loss.station_ssp).all()
    np.testing.assert_allclose(loss.R,loss.net_mwh/loss.capacity_mw)
    np.testing.assert_allclose(loss.annual_loss_pct,100*loss.net_mwh/loss.normal_annual_mwh)
    loss = combine(loss,keys,["net_mwh","capacity_mw","available_capacity_mw","normal_annual_mwh","n_stations"])
    joint = read(FIG2/"combined_loss_models.csv")
    check = loss[loss.tech.eq("wind+solar")].merge(joint,on=keys,suffixes=("","_old"),validate="one_to_one")
    np.testing.assert_allclose(check.net_mwh,check.net_mwh_old)
    np.testing.assert_allclose(check.capacity_mw,check.capacity_mw_old)
    definitions = [
        ("station_total_loss","Total net generation loss","Net loss (MWh yr⁻¹)","MWh/year",loss.net_mwh,1.,
         "Sum signed net event-union energy on common station support"),
        ("station_unit_loss","Net loss per unit capacity","Net loss (MWh MW⁻¹ yr⁻¹)","MWh/MW/year",loss.net_mwh,loss.capacity_mw,
         "Sum signed net loss divided by sum matching valid capacity"),
        ("station_loss_fraction","Loss / annual normal generation","Annual loss fraction (%)","%",100*loss.net_mwh,loss.normal_annual_mwh,
         "100 times signed net loss / annual NORMAL baseline energy; not actual CF generation")]
    for name,title,label,unit,num,den,method in definitions:
        emit(ratio(loss,num,den,"year"),name,"station",title,label,unit,True,method,[str(loss_path)])

    suitable_loss_path = PREP / "suitable_grid_loss/annual.csv.gz"
    sl = read(suitable_loss_path); sl = sl[sl.support.eq("common")].copy()
    sl["snapshot"] = sl.window_start
    sl = combine(sl,keys,["net_sum","n_valid","n_available"])
    emit(ratio(sl,sl.net_sum,sl.n_valid,"year"),"suitable_grid_unit_loss","suitable_grid",
         "Net loss per unit capacity","Net loss (MWh MW⁻¹ yr⁻¹)","MWh/MW/year",True,
         "1 MW per technology-grid; sum losses / number of valid technology-grid entries; no area weights",
         [str(suitable_loss_path)])

    gen_path = FIG2 / "combined_generation_technology_annual.csv"
    gen = read(gen_path)
    assert gen.climate_ssp.eq(gen.station_ssp).all() and gen.country.eq("GLOBAL").all()
    assert gen.min_station_time_coverage.eq(1).all()
    np.testing.assert_allclose(gen.generation_mwh,gen.capacity_cf_mw*gen.expected_hours)
    np.testing.assert_allclose(gen.valid_capacity_hours,gen.capacity_mw*gen.expected_hours)
    gen = combine(gen,keys,["generation_mwh","capacity_mw","available_capacity_mw","n_stations"])
    check = gen.merge(loss[keys+["tech","capacity_mw"]],on=keys+["tech"],suffixes=("","_loss"),validate="one_to_one")
    np.testing.assert_allclose(check.capacity_mw,check.capacity_mw_loss)
    previous = read(FIG2/"combined_generation_annual_models.csv")
    check = gen[gen.tech.eq("wind+solar")].merge(previous,on=keys,suffixes=("","_old"),validate="one_to_one")
    np.testing.assert_allclose(check.generation_mwh,check.generation_mwh_old)
    emit(ratio(gen,gen.generation_mwh,1e9,"year"),"station_total_generation","station",
         "Total generation","Generation (PWh yr⁻¹)","PWh/year",True,
         "Capacity times annual CF times native-calendar annual hours, summed over common station support",[str(gen_path)])
    emit(ratio(gen,gen.generation_mwh,gen.capacity_mw,"year"),"station_unit_generation","station",
         "Generation per unit capacity","Generation (MWh MW⁻¹ yr⁻¹)","MWh/MW/year",True,
         "Actual CF-based annual generation divided by matching valid capacity",[str(gen_path)])
    assert len(RESULTS) == 11 and len(FITS) == 54
    pd.DataFrame(FITS).to_csv(DATA/"all_linear_fits.csv",index=False)
    (OUT/"results_manifest.json").write_text(json.dumps(RESULTS,indent=2,ensure_ascii=False))
    (OUT/"validation.json").write_text(json.dumps(dict(status="PASSED",figures=11,panels=33,
        linear_fits=54,annual_years=[2030,2059],decades=[2030,2040,2050],
        matrix_checks="Each metric: all three technologies, three SSPs, all times; four models except catalogue capacity",
        consistency_checks=["capacity catalogue reproduction","existing loss totals reproduction",
                            "existing generation totals reproduction","loss/generation valid capacities agree",
                            "all values equal numerator/denominator","all finite, no duplicates",
                            "native calendar complete generation coverage","PNG and text bounds"],
        job_id=os.environ.get("SLURM_JOB_ID")),indent=2))
    (OUT/"input_provenance.json").write_text(json.dumps(PROVENANCE,indent=2))
    (OUT/"figure_contract.json").write_text(json.dumps(dict(
        question="How do global capacity, event exposure, losses and generation evolve under three SSP pathways?",
        backend="Python/matplotlib",archetype="quantitative grid",layout="1 row x 3 columns: wind+solar, wind, solar",
        export="600 dpi PNG; full triptychs only",dimensions_mm=[240,85],
        independent_y_tick_steps=PANEL_Y_STEPS,
        centre="Metrics within each model, then equal mean across four GCMs; capacity is deterministic",
        spread="Model min/max retained in source tables; lines show means, no uncertainty band",
        fit="One OLS line per SSP over 30 ensemble-mean annual values; descriptive, no significance inference",
        pathways="Paired climate and station SSP for stations; climate SSP only for grids",
        station_ssp585_source="stations_SSP5-6.0.csv",
        support="Per-input fixed common support; catalogue capacity figure includes catalogue capacity, not only valid analysis stations",
        net_loss="Signed net losses; original wind energy values, no scaling"),indent=2))
    print("All 11 figures and 54 fits PASSED",flush=True)


if __name__ == "__main__":
    main()
