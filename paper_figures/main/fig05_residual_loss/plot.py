"""Audit accepted Fig. 5 data and render the two country bubble panels."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from PIL import Image

from paper_figures.config import ROOT, OUTPUT, MODELS, TECHS, STATION_FILES, SSP_COLORS
from paper_figures.common.io import digest, require_complete, write_csv, write_json
from paper_figures.common.metrics import ensemble
from paper_figures.common.plotting import configure, save_png

FOLDER = ROOT / "paper_figures/main/fig05_residual_loss"
OUT = FOLDER / "outputs"
SOURCE = OUT / "source_data"
KEYS = ["model", "tech", "country"]
COLORS = {"higher_585": SSP_COLORS["ssp585"],
          "higher_126": SSP_COLORS["ssp126"], "unclear": "#777777"}
INPUTS = {
    "panel": SOURCE / "panel_ab.csv",
    "thresholds": OUTPUT / "panel_loss/residual_thresholds.csv",
    "selection": OUTPUT / "panel_loss/country_selection.csv",
    "windows": OUTPUT / "loss_summary/window.csv.gz",
    "coverage": OUTPUT / "loss_summary/capacity_coverage.csv.gz",
    "capacity": OUTPUT / "catalogues/capacity_by_country.csv",
    "audit": ROOT / "logs/paper_figures/completion_status/final_audit.json",
    "acceptance": OUTPUT / "acceptance/checks.json",
}


def check(condition, message):
    if not bool(condition):
        raise ValueError(message)


def prepare():
    for folder in ("loss_summary", "panel_loss", "acceptance"):
        require_complete(OUTPUT / folder)
    audit = json.loads(INPUTS["audit"].read_text())
    check(audit["verified_output_units"] == 664 and audit["acceptance"]["status"] == "PASSED",
          "Shared preparation is not accepted")
    panel = pd.read_csv(INPUTS["panel"])
    check(not panel.duplicated(KEYS).any(), "Duplicate model-country input")
    check(set(panel.model) == set(MODELS), "Unexpected model set")
    check(panel.snapshot.eq(2050).all() and panel.event.eq("all").all()
          and panel.support.eq("common").all() and panel.metric.eq("R").all(),
          "Unexpected metric or support")
    check("TWN" not in set(panel.country), "China was not merged")
    sample = panel.loc[panel.country.eq("USA") & panel.tech.eq("wind")].iloc[0]
    check(np.isclose(sample.R585 - sample.R126, sample.D), "Representative difference check")
    print("Representative USA/wind model check passed.", flush=True)
    columns = ["model", "climate_ssp", "station_ssp", "tech", "snapshot",
               "country", "event", "support", "net_mwh", "capacity_mw",
               "available_capacity_mw", "n_stations", "R"]
    parts = []
    for chunk in pd.read_csv(INPUTS["windows"], usecols=columns, chunksize=50000):
        use = chunk.event.eq("all") & chunk.support.eq("common") & chunk.snapshot.isin([2030,2050])
        use &= chunk.climate_ssp.eq(chunk.station_ssp) & chunk.climate_ssp.isin(["ssp126","ssp585"])
        parts.append(chunk.loc[use])
    windows = pd.concat(parts, ignore_index=True)
    check(not windows.duplicated(KEYS + ["climate_ssp","snapshot"]).any(), "Duplicate windows")
    finite = windows.capacity_mw.gt(0) & windows.R.notna()
    check(np.allclose(windows.loc[finite,"net_mwh"] / windows.loc[finite,"capacity_mw"],
                      windows.loc[finite,"R"]), "Loss normalization failed")
    for ssp, name in [("ssp126","R126"), ("ssp585","R585")]:
        w = windows[windows.snapshot.eq(2050) & windows.climate_ssp.eq(ssp)]
        joined = panel.merge(w[KEYS+["R"]], on=KEYS, how="left", validate="one_to_one")
        check(np.allclose(joined[name], joined.R, equal_nan=True), f"{name} differs from window")
    check(np.allclose(panel.R585-panel.R126, panel.D, equal_nan=True), "Paired difference failed")
    ens = ensemble(panel, ["tech","country"], "D").rename(
        columns={"mean":"D", "minimum":"D_min", "maximum":"D_max"})
    xens = ensemble(panel, ["tech","country"], "R126")[["tech","country","mean"]].rename(
        columns={"mean":"R126"})
    verified = panel.merge(ens[["tech","country","category","agreement"]],
                          on=["tech","country"], suffixes=("","_checked"), validate="many_to_one")
    check(verified.category.eq(verified.category_checked).all()
          and verified.agreement.eq(verified.agreement_checked).all(), "Direction class mismatch")
    refs = pd.read_csv(INPUTS["capacity"])
    refs = refs[refs.station_ssp.eq("ssp126") & refs.snapshot.eq(2050)][["tech","country","capacity_mw"]]
    refs = refs.rename(columns={"capacity_mw":"reference_capacity_mw"})
    aligned = panel.merge(refs, on=["tech","country"], how="left", suffixes=("","_checked"),
                          validate="many_to_one")
    check(np.allclose(aligned.reference_capacity_mw, aligned.reference_capacity_mw_checked,
                      equal_nan=True), "Reference capacity mismatch")
    countries = ens.merge(xens, on=["tech","country"], validate="one_to_one").merge(
        refs, on=["tech","country"], how="left", validate="one_to_one")
    thresholds = pd.read_csv(INPUTS["thresholds"])
    thresholds = thresholds[thresholds["quantile"].eq(.75)].copy()
    check(set(thresholds.tech) == set(TECHS) and len(thresholds)==2, "Missing thresholds")
    early = windows[windows.snapshot.eq(2030) & windows.climate_ssp.eq("ssp126")]
    early_ens = ensemble(early, ["tech","country"], "R")
    countries["included"] = False
    threshold_rows = []
    for th in thresholds.itertuples():
        names = th.countries.split(";")
        check(len(names)==th.n_countries and len(names)==len(set(names)), "Invalid fixed population")
        e = early_ens[early_ens.tech.eq(th.tech)].set_index("country").reindex(names)
        check(e["mean"].notna().all() and e.n_models.eq(4).all(), "Incomplete early population")
        check(np.isclose(e["mean"].quantile(.75), th.threshold, rtol=1e-12), "Threshold changed")
        check(np.allclose(panel.loc[panel.tech.eq(th.tech),"threshold"], th.threshold), "Panel threshold mismatch")
        use = countries.tech.eq(th.tech) & countries.country.isin(names)
        check(use.sum()==len(names), "Missing late country")
        check(countries.loc[use,["R126","D","reference_capacity_mw"]].notna().all().all()
              and countries.loc[use,"n_models"].eq(4).all()
              and countries.loc[use,"reference_capacity_mw"].gt(0).all(), "Incomplete late population")
        countries.loc[use,"included"] = True
        countries.loc[countries.tech.eq(th.tech),"threshold"] = th.threshold
        threshold_rows.append(early[early.tech.eq(th.tech) & early.country.isin(names)])
    countries["exclusion_reason"] = np.where(countries.included, "", np.where(
        countries.n_models.ne(4), "incomplete_paired_loss", np.where(
        countries.reference_capacity_mw.fillna(0).le(0), "no_reference_capacity",
        "outside_fixed_early_late_population")))
    write_csv(SOURCE/"excluded_countries.csv", countries[~countries.included])
    countries = countries[countries.included].copy()
    countries["reference_capacity_gw"] = countries.reference_capacity_mw / 1000
    countries["relative_high_loss"] = countries.R126.gt(countries.threshold) & countries.R126.gt(0)
    countries["snapshot"] = 2050
    countries["window"] = "2050–2059"
    countries["units"] = "MWh MW-1 yr-1"
    selected = countries[["tech","country"]]
    paired = windows.merge(selected, on=["tech","country"], validate="many_to_one")
    paired = paired[paired.snapshot.eq(2050)].copy()
    paired["window"] = "2050–2059"
    paired["station_source_file"] = paired.station_ssp.map(STATION_FILES)
    paired["units"] = "MWh MW-1 yr-1"
    coverage_parts = []
    for chunk in pd.read_csv(INPUTS["coverage"], chunksize=50000):
        use = chunk.support.eq("common") & chunk.snapshot.eq(2050)
        use &= chunk.climate_ssp.eq(chunk.station_ssp) & chunk.climate_ssp.isin(["ssp126","ssp585"])
        coverage_parts.append(chunk[use].merge(selected, on=["tech","country"], validate="many_to_one"))
    coverage = pd.concat(coverage_parts, ignore_index=True)
    check(coverage.coverage_pct.between(0,100+1e-7).all(), "Invalid coverage percentage")
    check(coverage.groupby(KEYS+["climate_ssp"]).year.nunique().eq(10).all(), "Incomplete annual coverage")
    check(len(coverage)==len(countries)*4*2*10, "Missing coverage records")
    names = pd.read_csv(INPUTS["selection"]).sort_values("order").head(8).country.tolist()
    countries["labelled"] = countries.country.isin(names)
    countries["show_models"] = False
    for tech in TECHS:
        largest = countries[countries.tech.eq(tech)].nlargest(2,"reference_capacity_gw").index
        countries.loc[largest,"show_models"] = True
    labels = countries[countries.labelled][["tech","country"]].copy()
    labels["reason"] = "Fig4_explanation_country"
    for name, frame in [("countries",countries), ("paired_windows",paired), ("coverage",coverage),
                        ("threshold_population",pd.concat(threshold_rows,ignore_index=True)),
                        ("thresholds",thresholds), ("country_labels",labels)]:
        write_csv(SOURCE/f"{name}.csv", frame)
    details = {}
    for tech, g in countries.groupby("tech"):
        cov = coverage[coverage.tech.eq(tech)]
        details[tech] = dict(
            countries=len(g), threshold=float(g.threshold.iloc[0]),
            categories=g.category.value_counts().to_dict(),
            relative_high_loss_countries=int(g.relative_high_loss.sum()),
            reference_capacity_gw=float(g.reference_capacity_gw.sum()),
            minimum_country_annual_coverage_pct=float(cov.coverage_pct.min()),
            model_points_countries=g[g.show_models].country.tolist(),
            labelled_countries=g[g.labelled].country.tolist())
    return panel, countries, details


def render(panel, countries):
    configure()
    plt.rcParams.update({"font.sans-serif":["DejaVu Sans"], "axes.labelsize":7,
                         "xtick.labelsize":6, "ytick.labelsize":6, "legend.fontsize":6})
    fig, axes = plt.subplots(1,2,figsize=(183/25.4,103/25.4),sharex=True,sharey=True)
    fig.subplots_adjust(left=.105,right=.975,bottom=.29,top=.89,wspace=.13)
    area_scale = 270 / countries.reference_capacity_gw.max()
    focus = panel.merge(countries.loc[countries.show_models,["tech","country"]],
                        on=["tech","country"],validate="many_to_one")
    xmin = min(0,countries.R126.min(),focus.R126.min())
    xmax = max(countries.R126.max(),focus.R126.max())
    ymin = min(0,countries.D.min(),focus.D.min())
    ymax = max(0,countries.D.max(),focus.D.max())
    xlim = (xmin-.035*(xmax-xmin), xmax+.09*(xmax-xmin))
    ylim = (ymin-.14*(ymax-ymin), ymax+.17*(ymax-ymin))
    offsets = {
        "wind":{"USA":(8,-13),"CHN":(9,8),"BRA":(-9,10),"RUS":(-22,4),
                "IND":(-13,-13),"IRN":(6,14),"KAZ":(8,7),"AUS":(9,-3)},
        "solar":{"USA":(10,15),"CHN":(4,29),"BRA":(-10,-19),"RUS":(17,4),
                 "IND":(-21,14),"IRN":(7,-25),"KAZ":(9,-11),"AUS":(-18,24)}}
    annotations = []
    for ax,tech,letter,title in zip(axes,TECHS,"ab",["Wind","Solar PV"]):
        g = countries[countries.tech.eq(tech)].sort_values("reference_capacity_gw",ascending=False)
        threshold = float(g.threshold.iloc[0])
        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        ax.axhline(0,color="#777777",lw=.6,zorder=0)
        ax.axvline(threshold,color="#666666",ls=(0,(4,3)),lw=.65,zorder=0)
        if threshold <= 0:
            ax.axvline(0,color="#999999",lw=.5,zorder=0)
        for row in g.itertuples():
            color = COLORS[row.category]
            ax.scatter(row.R126,row.D,s=row.reference_capacity_gw*area_scale,
                       facecolors="white" if row.category=="unclear" else color,
                       edgecolors=color,alpha=1 if row.category=="unclear" else .6,
                       linewidths=.55,zorder=2)
        points = focus[focus.tech.eq(tech)]
        ax.scatter(points.R126,points.D,s=10,marker="x",color="#222222",lw=.65,zorder=3)
        for row in g[g.labelled].itertuples():
            ann = ax.annotate(row.country,(row.R126,row.D),
                              xytext=offsets[tech][row.country],textcoords="offset points",
                              fontsize=6,ha="center",va="center",zorder=4,
                              bbox=dict(facecolor="white",edgecolor="none",alpha=.82,pad=.35),
                              arrowprops=dict(arrowstyle="-",color="#707070",lw=.4,shrinkA=1,shrinkB=3))
            annotations.append(ann)
        ax.text(0,1.035,letter,transform=ax.transAxes,fontweight="bold",fontsize=9)
        ax.text(.065,1.035,title,transform=ax.transAxes,fontweight="bold",fontsize=8)
        ax.text(.98,1.035,f"n = {len(g)}",transform=ax.transAxes,ha="right",fontsize=6.5)
        ax.text(threshold+5,ylim[1]-.055*(ylim[1]-ylim[0]),f"Early P75 = {threshold:.2f}",
                fontsize=6,color="#555555",va="top")
        ax.set_xlabel("SSP126 residual loss (MWh MW⁻¹ yr⁻¹)",labelpad=4)
        ax.tick_params(length=3,width=.6)
    axes[0].set_ylabel("Paired-path difference, SSP585 − SSP126\n(MWh MW⁻¹ yr⁻¹)",labelpad=4)
    fig.text(.105,.97,"2050–2059  |  Four-model country means",fontsize=8,va="top")
    handles = [
        Line2D([],[],marker="o",color="none",markerfacecolor=COLORS["higher_585"],
               markeredgecolor=COLORS["higher_585"],alpha=.65,markersize=5,label="SSP585 higher"),
        Line2D([],[],marker="o",color="none",markerfacecolor=COLORS["higher_126"],
               markeredgecolor=COLORS["higher_126"],alpha=.65,markersize=5,label="SSP126 higher"),
        Line2D([],[],marker="o",color="none",markerfacecolor="white",
               markeredgecolor="#777777",markersize=5,label="Direction unclear"),
        Line2D([],[],marker="x",color="#222222",linestyle="none",markersize=4,
               label="Individual models: USA, CHN")]
    fig.legend(handles=handles,loc="lower left",bbox_to_anchor=(.096,.145),
               ncol=4,handletextpad=.45,columnspacing=1.5,borderaxespad=0)
    fig.text(.105,.129,"Direction colours: ≥3 of 4 models agree with the mean; agreement is not significance.",
             fontsize=6,va="top",color="#444444")
    leg = fig.add_axes([.105,.025,.87,.07]); leg.set_axis_off()
    leg.set_xlim(0,1); leg.set_ylim(0,1)
    leg.text(0,.5,"Reference capacity (GW)",va="center",fontsize=6)
    for x,capacity in zip([.34,.49,.66],[10,100,1000]):
        leg.scatter(x,.5,s=capacity*area_scale,facecolors="none",edgecolors="#555555",lw=.6,clip_on=False)
        leg.text(x+.035,.5,f"{capacity:,}",va="center",fontsize=6)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    overlaps = []
    for i,a in enumerate(annotations):
        for b in annotations[i+1:]:
            if a.axes is b.axes and a.get_bbox_patch().get_window_extent(renderer).overlaps(
                    b.get_bbox_patch().get_window_extent(renderer)):
                overlaps.append([a.get_text(),b.get_text()])
    save_png(fig,OUT/"fig05.png")
    with Image.open(OUT/"fig05.png") as im:
        image_info = {"pixels":list(im.size),"dpi":list(im.info["dpi"])}
    plt.close(fig)
    return dict(x_limits=list(xlim),y_limits=list(ylim),area_points2_per_gw=float(area_scale),
                label_overlap_pairs=overlaps,**image_info)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    panel,countries,details = prepare()
    print(json.dumps(details,indent=2),flush=True)
    rendering = render(panel,countries)
    metadata = dict(
        status="NUMERICAL_CHECKS_PASSED",created_utc=datetime.now(timezone.utc).isoformat(),
        slurm_job_id=os.environ.get("SLURM_JOB_ID"),models=list(MODELS),model_weighting="equal",
        statistics="within-model path differences then ensemble mean",
        support="common across climates and models within each station SSP; fixed early/late countries",
        reference_capacity="SSP126 catalogue, snapshot 2050; circle area proportional to GW",
        comparison="paired climate/deployment paths",
        threshold="country-equal P75 of four-model SSP126 2030–2039 means in fixed population",
        units="MWh MW-1 yr-1",panels=details,rendering=rendering,
        inputs={k:dict(path=str(p),sha256=digest(p)) for k,p in INPUTS.items()},
        script_sha256=digest(Path(__file__)),
        source_data={p.name:digest(p) for p in sorted(SOURCE.glob("*.csv"))},
        checks=["accepted 664-task preparation","representative model/country","within-model pairing",
                "four-model completeness","direction categories","early P75 reproduction",
                "energy/capacity normalization","reference capacities","annual coverage","China aggregation"],
        visual_review="pending")
    write_json(OUT/"metadata.json",metadata)
    print(f"Saved {OUT/'fig05.png'}",flush=True)


if __name__ == "__main__":
    main()
