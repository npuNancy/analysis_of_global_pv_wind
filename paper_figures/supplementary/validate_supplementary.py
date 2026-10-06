"""Cross-source scientific and PNG integrity checks for supplementary figures."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from paper_figures.config import ROOT
from paper_figures.common.io import write_json,write_csv
SUP=ROOT/"paper_figures/supplementary"
def get(n):
    return next(SUP.glob(f"fig_s{n:02d}_*"))
def main():
    audit={}
    factors=pd.read_csv(get(1)/"outputs/source_data/panel_abcdef.csv")
    factors=factors[(factors.snapshot==2050)&(factors.event=="all")&(factors.support=="common")]
    contrast=pd.read_csv(get(4)/"outputs/source_data/panel_abcdefgh.csv")
    contrast=contrast[(contrast.snapshot==2050)&(contrast.event=="all")&(contrast.support=="common")&(contrast.metric=="R")]
    keys=["model","tech","snapshot","country"]
    f=factors.groupby(keys)[["psi_E","psi_CF","psi_r","delta_C"]].mean()
    joint=f.join(contrast.set_index(keys).Phi_C)
    finite=joint.dropna()
    err=float((finite.delta_C-finite.Phi_C).abs().max());assert err<1e-7
    err2=float((finite[["psi_E","psi_CF","psi_r"]].sum(1)-finite.Phi_C).abs().max());assert err2<1e-7
    audit["S01"]={"three_factor_mean_vs_Phi_C":err2,"delta_C_mean_vs_Phi_C":err,"finite_model_country_pairs":len(finite)}
    d=pd.read_csv(get(2)/"outputs/source_data/panel_ab.csv")
    assert d.exceedance_pct.between(0,100).all() and (d.n_years==10).all()
    audit["S02"]={"model_years":10,"percent_bounds":True}
    d=pd.read_csv(get(3)/"outputs/source_data/panel_ab.csv")
    for _,g in d.groupby(["tech","model"]):
        g=g.sort_values("rank");assert np.isclose(g.cumulative_capacity_pct.iloc[-1],100) and np.isclose(g.cumulative_burden_pct.iloc[-1],100)
        assert (np.diff(g.cumulative_burden_pct)>=-1e-8).all()
    audit["S03"]={"monotonic_and_endpoints":True,"interpretation":d.interpretation.unique().tolist()}
    manifest=json.loads((get(4)/"outputs/page_manifest.json").read_text())
    cat=pd.read_csv(ROOT/"paper_figures/prepare/outputs/catalogues/capacity_by_country.csv")
    countries=set(cat.country)-{"GLOBAL","AMBIGUOUS","UNASSIGNED"}
    assert set(manifest["countries"])==countries
    audit["S04"]={"complete_country_union":len(countries),"pages":len(manifest["pages"])}
    d=pd.read_csv(get(5)/"outputs/source_data/panel_ef.csv.gz")
    assert d.agreement.dropna().between(0,4).all()
    audit["S05"]={"agreement_bounds":True,"projection":"Plate Carree"}
    d=pd.read_csv(get(6)/"outputs/source_data/panel_abcd.csv")
    assert set(d.metric)=={"R","R_positive","annual_loss_pct"}
    error=float((d.D-(d.R585-d.R126)).abs().max());assert error<1e-7
    assert d.closure.abs().max()<1e-7
    audit["S06"]={"metrics":sorted(d.metric.unique()),"paired_difference_error":error,
                  "max_decomposition_closure":float(d.closure.abs().max())}
    d=pd.read_csv(get(8)/"outputs/source_data/panel_abcd.csv")
    f=d.capacity_starts/(10*d.capacity_mw)
    v=d.capacity_duration_hours/d.capacity_complete_events
    assert np.allclose(f,d.frequency_per_year,equal_nan=True)
    assert np.allclose(v,d.duration_hours,equal_nan=True)
    audit["S08"]={"frequency_and_duration_definitions":True,"censoring_report":"plotted_frequency_duration.csv"}
    d=pd.read_csv(get(10)/"outputs/source_data/panel_ef.csv")
    assert d.country_pct.between(0,100).all() and d.capacity_pct.between(0,100).all()
    high=[]
    for tech,g in d.groupby("tech"):
        countries=set.intersection(*(set(x.split(";")) for x in g.high_countries))
        high.extend({"tech":tech,"country":c} for c in sorted(countries))
    write_csv(get(10)/"outputs/source_data/always_high_loss_countries.csv",pd.DataFrame(high))
    audit["S10"]={"fixed_population":True,"always_high_loss_countries":high}
    if (get(7)/"outputs/source_data/panel_cd.csv").exists():
        q=pd.read_csv(get(7)/"outputs/source_data/annual_reproduction.csv")
        error=float((q.seasonal_sum-q.R).abs().max());assert error<.002
        e=pd.read_csv(get(7)/"outputs/source_data/panel_ab.csv")
        e=e[(e.country=="GLOBAL")&(e.snapshot==2050)&(e.station_ssp=="ssp126")&e.climate_ssp.isin(["ssp126","ssp585"])]
        keys=["model","climate_ssp","station_ssp","tech","snapshot","country","event"]
        seasonal=e.groupby(keys).E.sum().to_frame("seasonal")
        annual=pd.read_csv(ROOT/"paper_figures/prepare/outputs/event_summary/window.csv.gz")
        annual=annual[(annual.country=="GLOBAL")&(annual.snapshot==2050)&(annual.station_ssp=="ssp126")&annual.climate_ssp.isin(["ssp126","ssp585"])]
        comp=seasonal.join(annual.set_index(keys).E)
        exposure_error=float((comp.seasonal-comp.E).abs().max());assert exposure_error<1e-7
        audit["S07"]={"loss_seasonal_closure":error,"exposure_seasonal_closure":exposure_error}
    if (get(9)/"outputs/source_data/window.csv").exists():
        q=pd.read_csv(get(9)/"outputs/source_data/window.csv")
        assert (q[q.country=="GLOBAL"].groupby(["model","tech","baseline"]).size()==9).all()
        common=q[q.climate_ssp=="ssp126"].pivot(index=["model","station_ssp","tech","country"],columns="baseline",values="R")
        error=float((common.original_common_time-common.fixed_baseline).abs().max());assert error<1e-8
        audit["S09"]={"all_nine_combinations":True,"climate126_baseline_identity_error":error}
    pngs=[]
    for p in sorted(SUP.glob("*/outputs/*.png")):
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            assert min(im.size)>1000
            dpi=im.info.get("dpi");assert dpi and abs(dpi[0]-600)<1
            pngs.append({"path":str(p.relative_to(ROOT)),"dimensions":list(im.size),"dpi":list(dpi),
                         "sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    assert all(f"S{i:02d}" in audit for i in range(1,11)),"Missing figure validation"
    assert len(pngs)==33,"Expected nine single-page figures and 24 S04 pages"
    assert all(len(list(get(i).glob("outputs/*.png")))==(24 if i==4 else 1) for i in range(1,11))
    audit["scope"]="S01-S10"
    audit["S11"]="DEFERRED_BY_USER"
    audit["pngs"]=pngs;audit["status"]="NUMERICAL_AND_PNG_CHECKS_PASSED"
    dest=ROOT/"logs/paper_figures/supplementary"
    write_json(dest/"validation.json",audit)
    print(json.dumps({k:v for k,v in audit.items() if k not in ("pngs","S10")},indent=2),flush=True)
if __name__=="__main__":main()
