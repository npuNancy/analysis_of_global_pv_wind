"""Build SSP comparisons of extreme events, losses and country deployment tradeoffs."""
from pathlib import Path
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import hashlib
import json
import re
import shutil
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "paper_figures/analysis/analysis_20261019_005216"
sys.path.insert(0, str(ROOT))
from paper_figures.main.fig02_generation_loss.report import append_fig2, append_country

SOURCE = ROOT / "paper_figures/main/fig01_extreme_events/outputs"
ASSETS = HERE / "assets"
DATA = ASSETS / "data"
DERIVED = ASSETS / "derived"
for directory in [ASSETS / "images", DATA, DERIVED, ASSETS / "provenance"]:
    directory.mkdir(parents=True, exist_ok=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

manifest_path = ASSETS / "provenance/snapshot.json"
if not manifest_path.exists():
    records = []
    def freeze(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append({"origin": str(source.relative_to(ROOT)), "copy": str(destination.relative_to(HERE)),
                        "bytes": destination.stat().st_size, "sha256": sha(destination)})
    for prefix in ["fig01_ssp_grid_2050", "fig01_ssp_station_2050"]:
        for source in sorted(SOURCE.glob(prefix + "*.png")):
            freeze(source, ASSETS / "images" / source.name)
        freeze(SOURCE / (prefix + "_metadata.json"), ASSETS / "provenance" / (prefix + "_metadata.json"))
    for group in ["ssp_grid_2050", "ssp_station_2050"]:
        for source in sorted((SOURCE / "source_data" / group).iterdir()):
            if source.is_file():
                freeze(source, DATA / group / source.name)
    for source, name in [
        (SOURCE / "ssp_grid/dynamics/summary/frequency_duration_decomposition.csv", "grid_frequency_duration_decomposition.csv"),
        (SOURCE / "ssp_grid/native_spatial_fractions.csv", "grid_native_spatial_fractions.csv"),
    ]:
        freeze(source, DATA / name)
    for rel in [
        "document/BCSD_v2数据使用指南.md", "document/主图与子图设计.md",
        "paper_figures/main/fig01_extreme_events/plot_ssp_grid_2050.py",
        "paper_figures/main/fig01_extreme_events/plot_ssp_station_2050.py",
        "paper_figures/main/fig01_extreme_events/summarize_ssp_dynamics.py",
    ]:
        source = ROOT / rel
        freeze(source, ASSETS / "provenance" / source.name)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    manifest_path.write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(), "repo": str(ROOT),
        "git_commit": commit, "scope": "Fig. 01 only; 2050–2059; SSP comparisons",
        "files": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
extra_sources = []
for suffix in ["", "_a", "_b"]:
    name = "fig01_ssp_event_contrasts_2050" + suffix + ".png"
    extra_sources.append((SOURCE / name, ASSETS / "images" / name))
for suffix in ["_metadata.json", "_caption.md"]:
    name = "fig01_ssp_event_contrasts_2050" + suffix
    extra_sources.append((SOURCE / name, ASSETS / "provenance" / name))
for name in ["levels_models.csv", "contrasts_models.csv", "contrasts.csv"]:
    extra_sources.append((SOURCE / "source_data/ssp_event_contrasts_2050" / name,
                          DATA / "ssp_event_contrasts_2050" / name))
for suffix in [".py", ".sh"]:
    name = "plot_ssp_event_contrasts_2050" + suffix
    extra_sources.append((SOURCE.parent / name, ASSETS / "provenance" / name))
FIG02 = ROOT / "paper_figures/main/fig02_generation_loss"
for name in ["fig02.png", "fig02_ab.png", "fig02_cd.png", "fig02_ef.png",
             "fig02_climate_layout_waterfall_2030s_2040s_2050s.png"]:
    extra_sources.append((FIG02 / "outputs" / name, ASSETS / "images" / name))
for source in sorted((FIG02 / "outputs/source_data").glob("*.csv")):
    extra_sources.append((source, DATA / "fig02" / source.name))
for name in ["metadata.json", "data_audit.json"]:
    extra_sources.append((FIG02 / "outputs" / name, ASSETS / "provenance/fig02" / name))
for name in ["caption.md", "plot.py", "plot.sh", "plot_climate_layout_waterfall_decades.py",
             "plot_climate_layout_waterfall_decades.sh", "plot_climate_layout_waterfall.py",
             "plot_climate_layout_waterfall.sh", "report.py", "report.sh",
             "build_analysis_report.py", "build_analysis_report.sh"]:
    extra_sources.append((FIG02 / name, ASSETS / "provenance/fig02" / name))
extra_sources.append((ROOT / "document/主图与子图设计.md", ASSETS / "provenance/fig02/主图与子图设计.md"))
COUNTRY = ROOT / "paper_figures/main/country_deployment_tradeoffs"
for destination in sorted((ASSETS / "images/country_deployment_tradeoffs_top10").glob("*.png")):
    extra_sources.append((COUNTRY / "outputs/top10" / destination.name, destination))
for destination in sorted((DATA / "country_deployment_tradeoffs_top10").glob("*.csv")):
    extra_sources.append((COUNTRY / "outputs/top10/source_data" / destination.name, destination))
extra_sources.append((COUNTRY / "outputs/top10/data_audit.json",
                      DATA / "country_deployment_tradeoffs_top10/data_audit.json"))
for name in ["report.py", "report.sh"]:
    extra_sources.append((COUNTRY / name, ASSETS / "provenance/country" / name))
known = {record["copy"] for record in manifest["files"]}
added = []
for source, destination in extra_sources:
    relative = str(destination.relative_to(HERE))
    if relative not in known:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest["files"].append({"origin": str(source.relative_to(ROOT)), "copy": relative,
                                  "bytes": destination.stat().st_size, "sha256": sha(destination)})
        added.append(relative)
if added:
    manifest.setdefault("updates", []).append({
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "description": "Add requested SSP comparison figures and their evidence.",
        "files": added,
    })
    manifest["scope"] = "Fig. 01 (2050–2059), Fig. 02 (2030–2059), global and Top-10 country deployment comparisons (2050–2059)"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
assert all(sha(HERE / r["copy"]) == r["sha256"] for r in manifest["files"])

def read(group, name):
    return pd.read_csv(DATA / group / (name + ".csv"))

SSPS = ["ssp126", "ssp245", "ssp585"]
PAIRS = [("ssp245", "ssp126"), ("ssp585", "ssp126"), ("ssp585", "ssp245")]
TECH = {"wind": "风电", "solar": "光伏"}
EVENT = {
    "all": "全部事件并集", "high_temp": "高温", "high_wind": "强风",
    "hot_humid": "湿热", "icing": "覆冰", "low_resource": "低资源",
    "cold_highwind": "低温强风", "freezing_rain": "冻雨",
    "high_humidity": "高湿", "rainstorm": "暴雨", "overlap_correction": "重叠校正",
}
EVENT_ORDER = {
    "wind": ["high_temp", "high_wind", "hot_humid", "icing", "low_resource"],
    "solar": ["cold_highwind", "freezing_rain", "high_humidity", "icing", "low_resource", "rainstorm"],
}
COUNTRIES = {"CHN": "中国", "USA": "美国", "IND": "印度", "DEU": "德国", "BRA": "巴西", "RUS": "俄罗斯", "AUS": "澳大利亚"}
REGIONS = {"60N-90N": "60–90°N", "30N-60N": "30–60°N", "0-30N": "0–30°N", "30S-0": "30°S–赤道", "60S-30S": "60–30°S"}
METRICS = ["exposure_days", "starts_per_year", "mean_complete_hours", "p95_pct"]
METRIC_LABEL = {
    "exposure_days": "暴露时长（日/年）", "starts_per_year": "事件频次（次/年）",
    "mean_complete_hours": "平均持续时间（小时/次）", "p95_pct": "P95同步受影响比例（%）",
}
grid_levels = read("ssp_grid_2050", "panel_ab").replace({"metric": {"p95_area_pct": "p95_pct"}})
grid_models = read("ssp_grid_2050", "panel_ab_models").replace({"metric": {"p95_area_pct": "p95_pct"}})
station_levels = read("ssp_station_2050", "global_levels").replace({"metric": {"p95_capacity_pct": "p95_pct"}})
station_models = read("ssp_station_2050", "global_models").replace({"metric": {"p95_capacity_pct": "p95_pct"}})
levels = pd.concat([grid_levels.assign(scope="grid"), station_levels.assign(scope="station")], ignore_index=True)
models = pd.concat([grid_models.assign(scope="grid"), station_models.assign(scope="station")], ignore_index=True)
assert set(models.snapshot) == {2050}
assert set(models.event) == {"all"}
assert set(station_models.climate_ssp) == set(station_models.station_ssp)
assert (station_models.climate_ssp == station_models.station_ssp).all()
assert models.groupby(["scope", "tech", "climate_ssp", "metric"]).size().eq(4).all()

def summarize_pairs(frame, keys, value="value"):
    rows = []
    for group, values in frame.groupby(keys, dropna=False):
        group = group if isinstance(group, tuple) else (group,)
        wide = values.pivot(index="model", columns="climate_ssp", values=value)
        assert len(wide) == 4 and wide[SSPS].notna().all().all()
        for high, low in PAIRS:
            d = wide[high] - wide[low]
            rows.append(dict(zip(keys, group)) | {
                "high": high, "low": low, "mean": d.mean(), "minimum": d.min(),
                "maximum": d.max(), "positive": int((d > 0).sum()),
                "negative": int((d < 0).sum()), "n_models": len(d),
            })
    return pd.DataFrame(rows)

contrasts = summarize_pairs(models, ["scope", "tech", "metric"])
contrasts.to_csv(DERIVED / "global_paired_contrasts.csv", index=False)
levels[["scope", "tech", "climate_ssp", "metric", "mean", "minimum", "maximum", "n_models"]].to_csv(DERIVED / "global_levels.csv", index=False)

def level(scope, tech, metric, ssp):
    return float(levels.loc[(levels.scope == scope) & (levels.tech == tech) &
                           (levels.metric == metric) & (levels.climate_ssp == ssp), "mean"].item())

def delta(scope, tech, metric, high="ssp585", low="ssp126"):
    return contrasts[(contrasts.scope == scope) & (contrasts.tech == tech) &
                     (contrasts.metric == metric) & (contrasts.high == high) & (contrasts.low == low)].iloc[0]

grid_events = read("ssp_grid_2050", "panel_cd_models").rename(columns={"days_per_year": "value"})
station_events = read("ssp_station_2050", "event_models")
events = pd.concat([
    grid_events[["tech", "model", "climate_ssp", "event", "value"]].assign(scope="grid"),
    station_events[["tech", "model", "climate_ssp", "event", "value"]].assign(scope="station"),
], ignore_index=True)
event_pairs = summarize_pairs(events, ["scope", "tech", "event"])
event_pairs.to_csv(DERIVED / "event_paired_contrasts.csv", index=False)
event_figure = read("ssp_event_contrasts_2050", "contrasts").rename(columns={"spatial_level": "scope"})
event_reference = event_pairs[(event_pairs.high == "ssp585") & (event_pairs.low == "ssp126")]
event_check = event_figure.merge(event_reference, on=["scope", "tech", "event", "high", "low"],
                                suffixes=("_figure", "_report"), validate="one_to_one")
assert len(event_check) == len(event_figure) == len(event_reference) == 22
event_figure_error = max(
    (event_check[column + "_figure"] - event_check[column + "_report"]).abs().max()
    for column in ["mean", "minimum", "maximum"])
assert event_figure_error < 1e-9 and event_figure.n_models.eq(4).all()
event_figure_metadata = json.loads(
    (ASSETS / "provenance/fig01_ssp_event_contrasts_2050_metadata.json").read_text())
assert event_figure_metadata["status"] == "PASSED"
for entry in event_figure_metadata["files"]:
    assert sha(ASSETS / "images" / entry["file"]) == entry["sha256"]
event_levels = events.groupby(["scope", "tech", "climate_ssp", "event"], as_index=False).value.mean()
event_levels.to_csv(DERIVED / "event_levels.csv", index=False)
sums = events.groupby(["scope", "tech", "model", "climate_ssp"], as_index=False).value.sum()
unions = models[models.metric == "exposure_days"][["scope", "tech", "model", "climate_ssp", "value"]]
overlap_models = unions.merge(sums, on=["scope", "tech", "model", "climate_ssp"], suffixes=("_union", "_sum"))
overlap_models["value"] = overlap_models.value_union - overlap_models.value_sum
overlap_models["event"] = "overlap_correction"
overlap_pairs = summarize_pairs(overlap_models, ["scope", "tech", "event"])
event_accounts = pd.concat([event_pairs, overlap_pairs], ignore_index=True)
event_accounts.to_csv(DERIVED / "event_difference_accounting.csv", index=False)

lat = read("ssp_grid_2050", "panel_ef")
country = read("ssp_station_2050", "country_contrasts")
lat.to_csv(DERIVED / "latitude_event_contrasts.csv", index=False)
country[country.region.isin(["country:" + c for c in COUNTRIES])].to_csv(DERIVED / "selected_country_event_contrasts.csv", index=False)
spatial = pd.read_csv(DATA / "grid_native_spatial_fractions.csv")
spatial = spatial[(spatial.snapshot == 2050) & (spatial.high == "ssp585") & (spatial.low == "ssp126") & (spatial.event == "all")]
spatial.to_csv(DERIVED / "grid_area_fractions_585_126.csv", index=False)
decomposition = pd.read_csv(DATA / "grid_frequency_duration_decomposition.csv")
decomposition = decomposition[(decomposition.snapshot == 2050) & (decomposition.region == "global:GLOBAL") & (decomposition.event == "all")]
decomposition.to_csv(DERIVED / "grid_frequency_duration_global_2050.csv", index=False)

extra = read("ssp_station_2050", "global_extra_metrics")
extra["capacity_gw"] = extra.capacity_mw / 1000
extra["p95_affected_capacity_gw"] = extra.capacity_gw * extra.p95_capacity_pct / 100
extra["maximum_affected_capacity_gw"] = extra.capacity_gw * extra.maximum_capacity_pct / 100
EXTRA = {
    "capacity_gw": "有效装机容量（GW）",
    "mean_observed_capacity_pct": "时间平均受影响装机比例（%）",
    "p95_capacity_pct": "P95同步受影响装机比例（%）",
    "maximum_capacity_pct": "最大同步受影响装机比例（%）",
    "p95_affected_capacity_gw": "P95同步受影响装机量（GW）",
    "maximum_affected_capacity_gw": "最大同步受影响装机量（GW）",
}
extra_long = extra.melt(id_vars=["tech", "model", "climate_ssp"], value_vars=list(EXTRA), var_name="metric")
extra_pairs = summarize_pairs(extra_long, ["tech", "metric"])
extra_means = extra_long.groupby(["tech", "climate_ssp", "metric"], as_index=False).value.mean()
extra_pairs.to_csv(DERIVED / "station_extent_contrasts.csv", index=False)
extra_means.to_csv(DERIVED / "station_extent_levels.csv", index=False)

# Verify the calculations against the independently exported figure tables.
level_error = max(abs(models.groupby(["scope", "tech", "climate_ssp", "metric"]).value.mean()
                      - levels.set_index(["scope", "tech", "climate_ssp", "metric"])["mean"]))
reference = read("ssp_station_2050", "comparison").replace({"metric": {"p95_capacity_pct": "p95_pct"}})
check = reference.merge(contrasts[contrasts.scope == "station"], on=["tech", "metric", "high", "low"], suffixes=("_ref", "_calc"))
station_error = max(abs(check.mean_ref - check.mean_calc))
check_grid = reference.merge(contrasts[contrasts.scope == "grid"], on=["tech", "metric", "high", "low"], suffixes=("_ref", "_calc"))
grid_error = max(abs(check_grid.grid_mean - check_grid.mean_calc))
closure_errors = []
for (scope, tech, high, low), rows in event_accounts.groupby(["scope", "tech", "high", "low"]):
    closure_errors.append(abs(rows["mean"].sum() - delta(scope, tech, "exposure_days", high, low)["mean"]))
for frame in [lat, country]:
    for _, rows in frame.groupby(["tech", "region", "high", "low"]):
        total = rows.loc[rows.event == "all", "mean"]
        if len(total) == 1:
            closure_errors.append(abs(float(total.item()) - rows.loc[rows.event != "all", "mean"].sum()))
decomp_error = 0
for (tech, high, low), rows in decomposition.groupby(["tech", "high", "low"]):
    total = rows.loc[rows.term == "net_difference_days", "mean"].item()
    decomp_error = max(decomp_error, abs(total - rows.loc[rows.term != "net_difference_days", "mean"].sum()),
                       abs(total - delta("grid", tech, "exposure_days", high, low)["mean"]))
assert max(level_error, station_error, grid_error, max(closure_errors), decomp_error) < 1e-6

def num(v, signed=False, digits=2):
    if pd.isna(v):
        return "—"
    if abs(v) < 0.0000001:
        v = 0.
    return (f"{v:+,.{digits}f}" if signed else f"{v:,.{digits}f}").replace("-", "−")

def signs(row):
    return f'{int(row["positive"])}/4 ↑；{int(row["negative"])}/4 ↓'

def spread(row, digits=2):
    return f'{num(row["minimum"], True, digits)} ～ {num(row["maximum"], True, digits)}'

blocks = []
def h(level, title, anchor=None):
    blocks.append(("heading", level, title, anchor or re.sub(r"\W+", "-", title).strip("-")))
def p(text):
    blocks.append(("paragraph", text))
def note(text):
    blocks.append(("note", text))
def table(headers, rows):
    blocks.append(("table", headers, [[str(x) for x in row] for row in rows]))
def fig(stem, caption):
    blocks.append(("figure", "assets/images/" + stem + ".png", caption))
def data_link(filename, caption="下载复算明细"):
    p(f"[{caption}](assets/derived/{filename}.csv)。")
def overview(scope):
    rows = []
    for tech in ["wind", "solar"]:
        for metric in METRICS:
            d = delta(scope, tech, metric)
            base = level(scope, tech, metric, "ssp126")
            unit = "百分点" if metric == "p95_pct" else ""
            rows.append([TECH[tech], METRIC_LABEL[metric],
                         *[num(level(scope, tech, metric, s)) for s in SSPS],
                         num(d["mean"], True) + unit, num(100 * d["mean"] / base, True) + "%",
                         spread(d), signs(d)])
    table(["技术", "指标", "SSP126", "SSP245", "SSP585", "585−126", "相对126变化", "逐模式差值范围", "模式方向"], rows)

def event_table(scope, tech):
    rows = []
    for event in EVENT_ORDER[tech]:
        v = event_levels[(event_levels.scope == scope) & (event_levels.tech == tech) & (event_levels.event == event)].set_index("climate_ssp").value
        d = event_pairs[(event_pairs.scope == scope) & (event_pairs.tech == tech) & (event_pairs.event == event) &
                        (event_pairs.high == "ssp585") & (event_pairs.low == "ssp126")].iloc[0]
        rows.append([EVENT[event], *[num(v[s], digits=3) for s in SSPS],
                     num(d["mean"], True, 3), spread(d, 3), signs(d)])
    table(["事件", "SSP126", "SSP245", "SSP585", "585−126", "逐模式差值范围", "模式方向"], rows)
    correction = overlap_pairs[(overlap_pairs.scope == scope) & (overlap_pairs.tech == tech) &
                               (overlap_pairs.high == "ssp585") & (overlap_pairs.low == "ssp126")].iloc[0]
    net = delta(scope, tech, "exposure_days")["mean"]
    event_sum = net - correction["mean"]
    p(f'{TECH[tech]}的事件差值求和为{num(event_sum, True, 3)}日/年，加入{num(correction["mean"], True, 3)}日/年的重叠校正变化，才得到并集差{num(net, True, 3)}日/年。重叠校正是扣除重复计数的核算项，不是另一种事件。')

def regional_table(frame, tech, mapping, prefix=""):
    rows = []
    for region, label in mapping.items():
        r = frame[(frame.tech == tech) & (frame.region == prefix + region) & (frame.high == "ssp585") & (frame.low == "ssp126")]
        r245 = frame[(frame.tech == tech) & (frame.region == prefix + region) & (frame.high == "ssp245") & (frame.low == "ssp126")]
        union = r[r.event == "all"].iloc[0]
        actual = r[~r.event.isin(["all", "overlap_correction"])]
        pos = actual[actual["mean"] > 0].nlargest(2, "mean")
        neg = actual[actual["mean"] < 0].nsmallest(2, "mean")
        describe = lambda df: "；".join(EVENT[x.event] + " " + num(x.mean, True) for x in df.itertuples()) or "无"
        overlap = r.loc[r.event == "overlap_correction", "mean"].item()
        shown = pos["mean"].sum() + neg["mean"].sum()
        remaining = actual["mean"].sum() - shown
        pos_col = "positive_models" if "positive_models" in union.index else "positive"
        neg_col = "negative_models" if "negative_models" in union.index else "negative"
        rows.append([label, num(r245.loc[r245.event == "all", "mean"].item(), True),
                     num(union["mean"], True), f'{int(union[pos_col])}/4 ↑；{int(union[neg_col])}/4 ↓',
                     describe(pos), describe(neg), num(remaining, True), num(overlap, True)])
    table(["地区", "并集245−126", "并集585−126", "585−126方向", "主要正向事件差", "主要负向事件差", "其余事件差", "重叠校正差"], rows)

h(1, "不同SSP路径下的风光极端事件、发电损失与国家部署权衡", "top")
p("分析报告 · Fig. 01、Fig. 02与全球及Top-10国家部署 · 同一发电技术内比较SSP126、SSP245、SSP585")
p(f"生成目录：{HERE.name}。本报告收录全球网格与场站两张完整图、各事件路径差对比图及其独立子图，使用图件对应的逐模式汇总表复算路径差。第1–5节比较2050年代极端事件，第6节比较2030s–2050s发电损失，第7节比较2050年代国家部署。各章都以SSP路径差异为主线。")
h(2, "1. 核心结论：路径差异及其事件来源", "findings")
note("全球网格上，SSP585相较SSP126的风电相关极端事件更频繁、暴露更长、P95同步影响面积更大但单次持续略短；光伏总体相反。转换到各路径的装机布局后，风电四项指标均下降，光伏表现为小幅且存在模式分歧的变化，因此网格结论不能直接替代装机暴露结论。")
table(["对象", "SSP585相较SSP126的主要结果", "解释与限制"], [
    ["网格／风电", "暴露+2.40日/年；频次+6.04次/年；平均持续−0.28小时；P95面积比例+0.99个百分点。",
     "四项方向均为4/4模式一致。高温增加是主要正向事件变化，低资源与覆冰减少部分抵消；北半球低纬增加尤为突出。"],
    ["网格／光伏", "暴露−1.22日/年；频次−3.74次/年；平均持续+0.15小时；P95面积比例−0.35个百分点。",
     "四项方向均为4/4模式一致。高湿、冻雨、覆冰减少超过低资源增加；北半球高纬仍可增加。"],
    ["场站／风电", "容量加权暴露−3.20日/年；频次−4.43次/年；平均持续−0.25小时；P95装机比例−1.21个百分点。",
     "四项方向均为4/4模式一致。全球覆冰、低资源和高温暴露均值下降；印度、美国、中国、巴西仍有局部增加。"],
    ["场站／光伏", "容量加权暴露−0.55日/年；频次−1.45次/年；平均持续约不变（+0.01小时）；P95装机比例+0.16个百分点。",
     "暴露、频次下降与P95上升各为3/4模式同向，持续时间2升2降。SSP245的暴露和频次最高，路径排序不是单调关系。"],
])
note("“影响范围增加”需要指定统计量：场站两技术的最大同步受影响装机比例均值都上升（均为3/4模式上升），但风电P95比例下降；两技术的P95及最大绝对受影响装机量均下降。最大比例、P95比例、绝对GW和地理面积不能互换。")
p("建议作为本阶段的一句话结论：2050年代，SSP585相较SSP126使全球网格风电极端事件更频繁、暴露更长且同步影响面积更大，光伏则总体相反；在路径对应的装机布局下，风电暴露反而降低，光伏变化较小且不单调，差异由事件组成、区域分布与装机权重共同决定。")

h(2, "2. 指标和比较口径", "definitions")
table(["项目", "本报告的定义与读法"], [
    ["自变量与时间", "所有结果固定2050–2059年，只比较SSP路径；场站采用2050年总容量快照。重点差值为SSP585−SSP126，同时保留SSP245。"],
    ["全球网格", "共同有效原生格点面积加权；1,526,295个格点，总面积约1.333亿km²。结论适用于当前产品有效覆盖，不能理解为包括全部海洋和南极的整球平均。"],
    ["全球装机／场站", "按各路径有效装机容量加权，不是对场站等权平均。气候SSP与场站SSP配对变化，包含气候、位置及容量权重的共同变化。"],
    ["暴露时长", "全年累计事件小时数折合为24小时日，再按年平均；单位日/年。不是发生过事件的日历天数。"],
    ["事件频次", "已知非事件状态到事件状态的启动次数，按年与面积／容量加权。全事件频次按并集序列重新识别，不能把分类频次相加。"],
    ["平均持续时间", "完整事件持续小时的面积／容量加权汇总；缺少起点或终点的截断片段不进入完整事件均时长。"],
    ["同步影响范围", "每个时刻受事件影响的面积／装机占有效总量的比例，再求时间P95。它描述高影响时段的同步程度，不是曾经发生事件的累计地理覆盖。"],
    ["全部事件", "各类型事件在时间上的并集；重叠事件只计一次。类型和并集差异间必须保留重叠校正。"],
    ["模式与误差线", "BCC-CSM2-MR、CANESM5、MPI-ESM1-2-HR、MRI-ESM2-0四模式等权平均；先逐模式相减，再汇总差值。图中范围为模式最小—最大值，不是置信区间；同号不等于统计显著。"],
    ["SSP标签", "沿用数据产品标签。station_ssp585来自stations_SSP5-6.0.csv的正式映射，不能把部署标签本身解释为气候强迫。"],
    ["相对变化", "常规指标的相对变化为（585均值−126均值）/126均值；比例的绝对差用“百分点”。"],
])
p("同步比例以共同支持总面积／总容量为分母，P95与最大值只使用可用支持比例达到99%的时刻；缺测另有上下界，不直接当作无事件。本报告场站全球源表中，所有模式与路径的时刻接受比例和平均可用容量比例均为100%。")

p("低资源事件使用各模式、各气候SSP自身的2015–2024基线。相关路径差应按这个阈值定义解释，不能直接称为同一固定气候阈值下的资源恶化。所有“为什么”先回答哪些事件增减在核算上组成差异；物理机制与部署因果份额需要另外的反事实和过程诊断。")

h(2, "3. 全球网格：同一技术内的SSP对比", "grid")
fig("fig01_ssp_grid_2050", "全球网格完整图。左列风电、右列光伏；a–b整体指标，c–d分类事件，e–f纬带事件差，g–h空间地图。")
h(3, "3.1 a–b：整体排序与频次—持续性分解", "grid-ab")
fig("fig01_ssp_grid_2050_ab", "网格a–b：每个指标的三个柱子对应三个SSP。纵轴按该技术、该指标的SSP126集合均值归一；柱旁为原单位数值。")
overview("grid")
p("风电暴露、频次与P95面积比例均为126＜245＜585，持续时间为126＞245＞585；光伏暴露、频次与P95面积比例均为126＞245＞585，持续时间为126＜245＜585。这里的排序是四模式集合均值排序；585−126的八项方向均得到四模式一致支持。a–b纵轴从0.90开始，应根据数值和相对变化解读差幅，不能把柱高差当成从零起算的倍数差。")
rows = []
for tech in ["wind", "solar"]:
    d = decomposition[(decomposition.tech == tech) & (decomposition.high == "ssp585") & (decomposition.low == "ssp126")].set_index("term")["mean"]
    rows.append([TECH[tech], *[num(d[k], True, 3) for k in [
        "frequency_contribution_days", "duration_contribution_days", "censored_contribution_days", "net_difference_days"]]])
table(["技术", "完整事件频次贡献", "完整事件持续性贡献", "截断片段贡献", "暴露净差"], rows)
p("分解单位均为日/年。风电完整事件频次增加贡献+3.41日/年，持续时间缩短抵消约1.02日/年；光伏频次减少贡献−1.88日/年，持续时间变长补回约0.65日/年。分解使用完整事件频率与完整事件时长的对称分解，并单独计入截断片段；不能直接拿a–b的全部启动频次乘以完整事件均时长来强求恒等式。")
data_link("grid_frequency_duration_global_2050")
h(3, "3.2 c–d：同一事件下，不同SSP有什么不同", "grid-cd")
fig("fig01_ssp_grid_2050_cd", "网格c–d：同一行比较三个SSP。横轴压缩空白区间，条形保持连续；跨压缩区间的视觉长度不是线性尺度，应读取刻度与以下数值。")
for tech in ["wind", "solar"]:
    h(4, TECH[tech] + "：分类暴露时长（日/年）", "grid-events-" + tech)
    event_table("grid", tech)
p("风电路径差的主要正项为高温（+3.43日/年），湿热虽上升（+0.22）但绝对贡献较小；低资源（−0.70）和覆冰（−0.39）抵消一部分增加，强风接近零。因此，“本来哪类事件暴露最多”和“哪类事件解释SSP差异”是两个问题。")
p("光伏的高湿减少（−1.33日/年）是最大负项，冻雨（−0.44）和覆冰（−0.33）也下降；低资源增加（+0.76）抵消了部分下降。暴雨小幅增加约0.09日/年，不能用全部事件减少推断所有类型都减少。")
data_link("event_difference_accounting", "下载分类事件与重叠校正的完整核算")

h(3, "3.3 e–f：纬度差异由哪些事件组成", "grid-ef")
fig("fig01_ssp_grid_2050_ef", "网格e–f：各纬带的SSP245−SSP126与SSP585−SSP126事件差。并集列与分类列通过重叠校正闭合。")
p("下表全部为日/年。主要正、负项各列出最多两种事件，“其余事件差”补齐剩余类型；主要正项＋主要负项＋其余事件差＋重叠校正差＝并集585−126（显示值经过四舍五入）。")
for tech in ["wind", "solar"]:
    h(4, TECH[tech] + "纬带差异", "grid-regions-" + tech)
    regional_table(lat, tech, REGIONS)
p("风电最明显的增加位于0–30°N：并集+6.00日/年，高温+6.84是主要正项；30°S–赤道也增加+2.55，高温增加超过低资源减少。30–60°N只有+0.21，是高温增加与覆冰、低资源减少相互抵消的结果；60–90°N的增加则主要对应覆冰和低资源，不能统一归为高温驱动。")
p("光伏的南半球低纬下降最明显：30°S–赤道并集−3.59日/年，主要对应高湿减少−3.83；30–60°N并集−2.07，覆冰和冻雨下降明显。60–90°N反而增加+3.81，低资源、高湿和覆冰均增加。0–30°N净差仅−0.56，四模式2升2降，说明全球下降不能概括成各纬带一致下降。")
data_link("latitude_event_contrasts")

h(3, "3.4 g–h：空间上的增加与减少各占多大范围", "grid-gh")
fig("fig01_ssp_grid_2050_gh", "网格g–h：SSP585−SSP126并集暴露差，日/年。圆圈是固定SSP126、2050年装机参考，不参与格点面积加权。")
rows = []
for tech in ["wind", "solar"]:
    values = spatial[spatial.tech == tech].set_index("criterion").area_fraction
    rows.append([TECH[tech], *[num(100 * values[c]) + "%" for c in [
        "mean_positive", "mean_negative", "mean_above_1day", "mean_below_minus1day", "positive_4of4", "negative_4of4"]]])
table(["技术", "均值增加的面积", "均值减少的面积", "增加超过1日/年", "减少超过1日/年", "4/4模式增加的面积", "4/4模式减少的面积"], rows)
p("风电约64.03%的有效面积暴露增加、35.94%减少；但四模式全部增加的面积只有28.71%。光伏约54.32%的面积减少、45.64%增加，四模式全部减少的面积为18.70%。全球平均方向比许多局部方向更稳定，不能把全球4/4同向误读为每个格点都4/4同向。以上比例以原生格点面积计算，分母是全体共同有效面积。")
p("地图与纬带结果共同表明风电增加偏向北半球低纬，光伏减少主要见于部分低纬和中纬区域，同时存在北半球高纬增加区。纬带核算不能直接证明某一国家或某个像素的事件来源；要做更细地域解释，应使用对应地域的分类统计。")
p("两张地图共用±12.5日/年色标，端点颜色包含超限值。地图是1°展示汇总，数值分析仍使用原生格点；相同颜色不表示超过色标端点的两个区域差幅相同。")
data_link("grid_area_fractions_585_126")

h(2, "4. 全球装机／场站：配对路径的差异", "station")
fig("fig01_ssp_station_2050", "场站完整图。左列风电、右列光伏；a–b整体指标，c–d分类事件，e–f国家地图，g–h国家事件热图，i–j网格与场站路径差对照。")
h(3, "4.1 a–b：风电下降明确，光伏路径排序非单调", "station-ab")
fig("fig01_ssp_station_2050_ab", "场站a–b：容量加权并集指标；纵轴相对SSP126集合均值归一，起点0.85。P95指受影响容量比例。")
overview("station")
p("风电暴露、频次与P95装机比例均随126→245→585下降；平均持续时间在245最低，585相较245略回升，因此不能把四项都说成沿三个路径单调下降。585−126四项差异均为四模式一致下降。")
p("光伏的SSP245暴露最高（30.24日/年），高于126的27.81和585的27.26；其频次与P95比例也最高。585−126的暴露差范围跨零（−1.00至+0.64日/年），持续时间差仅约0.01小时且2升2降。“585总体更少”只能指集合均值的585−126对照，不能推导路径强迫越高、场站风险越低。")
data_link("global_paired_contrasts")

h(3, "4.2 c–d：哪些事件构成装机暴露变化", "station-cd")
fig("fig01_ssp_station_2050_cd", "场站c–d：分类事件容量加权暴露。条形连续、仅底部横轴标记压缩区间；须按同一事件比较三个SSP。")
for tech in ["wind", "solar"]:
    h(4, TECH[tech] + "：分类暴露时长（日/年）", "station-events-" + tech)
    event_table("station", tech)
p("风电场站覆冰下降约1.83日/年、低资源下降1.07、高温下降0.94，湿热增加0.26；这与网格高温显著增加形成关键反差。两者统计空间和权重不同，场站路径还改变部署，不应解释成“同一地点的高温在两个数据产品中方向相反”。")
p("光伏场站高湿减少约1.35日/年是最大负项，覆冰和暴雨下降；低资源增加0.65、低温强风增加0.27、冻雨增加0.13抵消了下降。光伏场站冻雨变化与全球网格方向不同，也是空间选择和容量权重可能影响结论的具体例子。")

h(3, "4.3 e–f：国家地图显示哪些地区方向不同", "station-ef")
fig("fig01_ssp_station_2050_ef", "场站e–f：仅SSP585−SSP126的国家单位装机暴露差。地图面填色按国家统计，不是每个位置的格点暴露。")
p("风电全球容量加权均值下降，但印度、巴西、美国和中国的国家均值增加；德国、俄罗斯、澳大利亚下降。光伏中国接近零、印度、美国、澳大利亚增加，德国、巴西、俄罗斯下降。国家符号差异说明全球平均会掩盖相反的地方变化。")
p("国家地图色标与网格地图一致为±12.5日/年。风电151个有值国家中14个超出色标，光伏152个中14个超出；这些是国家个数比例，不能当成面积比例或装机比例。缺值不代表没有事件。中国按China与Taiwan合并单元统计和绘制。")

h(3, "4.4 g–h：用事件核算解释国家差异", "station-gh")
fig("fig01_ssp_station_2050_gh", "场站g–h：七个展示国家的事件热图，保留SSP245−SSP126和SSP585−SSP126。国家选择沿用图件，不能视为所有国家的代表样本。")
for tech in ["wind", "solar"]:
    h(4, TECH[tech] + "国家事件差异（日/年）", "station-countries-" + tech)
    regional_table(country, tech, COUNTRIES, "country:")
p("风电印度增加+5.83日/年，主要对应高温+6.96和湿热+1.46，低资源减少−2.33部分抵消；美国增加+1.36，是高温+5.03超过覆冰−2.14和低资源−1.98后的净结果；中国净增仅+0.66，高温与覆冰增加被低资源下降部分抵消。德国下降−7.62主要对应覆冰−4.51和低资源−4.12；澳大利亚下降−4.29主要对应容量加权高温暴露下降−4.76。")
p("光伏印度增加+3.54日/年，高湿+2.21与低资源+1.45是主要正项；澳大利亚增加+1.41，低资源和高湿上升。巴西减少−5.13几乎由高湿减少−5.06主导；俄罗斯减少−7.26，覆冰−5.24、冻雨−2.02和高湿−1.80共同贡献，并伴随+1.72的重叠校正变化。中国净差−0.27很小，低资源增加与高湿减少几乎抵消。")
p("这里的事件差是各路径本国容量加权均值之差，是对国家结果的事件组成解释。它还不能区分气候改变、站点位置迁移与容量权重调整各占多少；尤其不能仅凭澳大利亚高温暴露下降推断当地变冷。各国单位装机差也不能直接相加得到全球差，因为路径间国家容量占比本身变化。")
data_link("selected_country_event_contrasts")

h(3, "4.5 i–j：网格平均与装机暴露为何不能互换", "station-ij")
fig("fig01_ssp_station_2050_ij", "场站i–j：同一技术、同一指标下比较三个路径差；网格按面积加权、场站按容量加权。比例指标的单位均为百分点，但分母分别是面积与装机。")
rows = []
for tech in ["wind", "solar"]:
    for high, low in PAIRS:
        for metric in METRICS:
            dg = delta("grid", tech, metric, high, low)
            ds = delta("station", tech, metric, high, low)
            rows.append([TECH[tech], high.upper() + "−" + low.upper(), METRIC_LABEL[metric],
                         num(dg["mean"], True), num(ds["mean"], True), signs(dg), signs(ds)])
table(["技术", "路径对照", "指标（比例差为百分点）", "网格差", "场站差", "网格方向", "场站方向"], rows)
p("最突出的反差是风电585−126：网格暴露增加2.40日/年、场站减少3.20日/年；频次和P95同步比例的方向也相反，只有平均持续时间同为缩短。光伏245−126也存在暴露反向：网格减少0.49日/年，场站增加2.44日/年，双方均为四模式一致。")
p("当前图件直接证明的是：SSP路径差对空间样本和权重敏感。网格并不按装机分布加权，场站配对路径又同时改变气候和部署，因此这类反差与事件区域差异、装机空间分布及容量占比变化相容。要量化“多少来自气候、多少来自部署”，需另做固定部署的跨气候对照；本报告不从这些配对图中估计因果份额。")

h(3, "4.6 各类事件的SSP585−SSP126差：网格与装机直接对照", "event-contrasts")
fig("fig01_ssp_event_contrasts_2050", "各类极端事件暴露时长的SSP585−SSP126差值，2050–2059年。a为风电，b为光伏；灰色条为全球网格面积加权结果，蓝色斜线条为全球装机容量加权结果。")
p("每类事件的两根条表示相同路径对照下的不同空间加权结果。正值表示SSP585暴露更长，负值表示更短；条形及标签为四模式差值均值，细线为模式最小—最大范围，单位日/年。风光共用−6至+6的线性坐标范围，强风差值很小，因此保留四位小数。")
p("[风电独立子图a](assets/images/fig01_ssp_event_contrasts_2050_a.png) · [光伏独立子图b](assets/images/fig01_ssp_event_contrasts_2050_b.png) · [图注](assets/provenance/fig01_ssp_event_contrasts_2050_caption.md)")
p("风电最明确的反向变化是高温：网格增加3.43日/年，装机减少0.94日/年，两者各自均为四模式同向。覆冰在两类空间对象上都减少，但装机下降更大（−1.83对−0.39日/年）；低资源也均减少（装机−1.07、网格−0.70）。湿热均增加，强风变化接近零。高温的方向反转与覆冰降幅的扩大，是理解网格并集暴露增加、装机并集暴露减少的重要事件线索。")
p("光伏高湿在网格与装机上都减少，幅度接近（−1.33与−1.35日/年）；覆冰也均减少，低资源均增加。低温强风由网格−0.06变为装机+0.27，冻雨由−0.44变为+0.13，暴雨由+0.09变为−0.15日/年。这三类反向均指集合均值：网格低温强风、装机冻雨及网格暴雨的模式范围跨零，不能说反向变化得到所有模式一致支持。")
p("该图直接比较分类事件的路径差；事件可能重叠，不能把各条相加当作并集差。装机结果使用各路径对应的2050年布局与容量，包含气候和部署共同变化；与网格结果的差距不能直接当作部署的因果贡献。")
p("[分类路径差汇总CSV](assets/data/ssp_event_contrasts_2050/contrasts.csv) · [逐模式路径差CSV](assets/data/ssp_event_contrasts_2050/contrasts_models.csv) · [逐模式原始水平CSV](assets/data/ssp_event_contrasts_2050/levels_models.csv)。新增图的22组事件对比已与本报告冻结源数据复算结果逐项核对一致。")

h(2, "5. 补充核对：“受影响比例下降，但影响范围增加”如何表达", "extent")
p("本节使用与场站图相同分析输出中的global_extra_metrics.csv补充P95之外的时间平均和最大值；这些最大值不是a–b已经展示的指标。绝对受影响装机量先逐模式以有效装机容量乘以该模式受影响比例计算，再取四模式均值。")
rows = []
for tech in ["wind", "solar"]:
    for metric, label in EXTRA.items():
        v = extra_means[(extra_means.tech == tech) & (extra_means.metric == metric)].set_index("climate_ssp").value
        d = extra_pairs[(extra_pairs.tech == tech) & (extra_pairs.metric == metric) &
                        (extra_pairs.high == "ssp585") & (extra_pairs.low == "ssp126")].iloc[0]
        rows.append([TECH[tech], label, *[num(v[s]) for s in SSPS], num(d["mean"], True), signs(d)])
table(["技术", "统计量", "SSP126", "SSP245", "SSP585", "585−126（比例差为百分点）", "方向"], rows)
p("风电的时间平均比例与P95比例都下降，而最大比例从26.65%升至29.47%（+2.82个百分点）；光伏时间平均比例下降、P95略升，最大比例从24.18%升至25.97%（+1.79个百分点）。两种技术的最大比例均为3/4模式上升，不能说所有模式都支持峰值增加。平均、P95和最大值刻画分布的不同位置，出现不同方向并不矛盾；仅有这三个统计量也不足以断言整个分布的形状如何改变。")
p("在有效容量口径下，风电总装机由12,557.70 GW降至1,215.85 GW，光伏由9,349.80 GW降至2,306.86 GW。因此即使最大受影响比例上升，最大受影响装机量仍分别从3,347.12降至358.31 GW、从2,261.17降至599.18 GW。这反映输入部署路径的差异，不能把比例增加表述为更多绝对装机受到影响。")
note("可采用的场站结论：SSP585相较SSP126，风电的容量加权暴露、频次、平均持续时间和P95受影响装机比例均下降，但最大同步受影响装机比例的集合均值上升；光伏的暴露与频次均值略降、平均持续时间近似不变、P95与最大同步比例略升，且多数差异存在模式分歧。两技术绝对受影响装机量均下降。")
data_link("station_extent_levels", "下载同步影响指标的三个SSP水平")
data_link("station_extent_contrasts", "下载同步影响指标的逐模式路径差汇总")

fig02_validation = append_fig2(h, p, note, table, fig, HERE)
country_validation = append_country(h, p, note, table, blocks, HERE)

h(2, "8. 证据边界与解释范围", "limits")
table(["当前可以回答", "当前尚不能据此断言"], [
    ["2050年代三个SSP的事件水平、配对路径差及四模式方向。", "差值具有统计显著性，或四模式集合代表全部不确定性。"],
    ["全部事件并集变化可由分类事件差和重叠校正闭合。", "某一事件的差值是可独立相加的物理因果效应。"],
    ["全球网格的纬带事件来源，以及图示七个国家的场站事件来源。", "纬带均值适用于带内每个国家；国家容量均值等于国土每个位置的变化。"],
    ["P95、时间均值、最大同步比例和绝对GW可以不同方向变化。", "同步受影响容量比例上升就等于受影响面积、站点数量或发电损失上升。"],
    ["场站配对SSP结论包含气候和部署共同变化。", "将网格与场站差值之差直接当作部署效应。"],
])
p("本目录保存极端事件、发电损失与国家部署分析。Fig. 01的气象暴露与Fig. 02损失有效事件窗口不同，不能直接互换；单位装机损失无法替代总损失与正常发电能力比较。国家部署结果只比较给定配置，不构成国家最优SSP或政策建议。")

h(2, "9. 图件、源数据与复算记录", "evidence")
p(f"图件源目录：paper_figures/main/下的fig01_extreme_events、fig02_generation_loss和country_deployment_tradeoffs。初始报告所用代码提交：{manifest['git_commit']}；新增图件的代码与文件哈希见快照清单。报告使用已完成的图件与小型汇总表，在1866仓库虚拟环境中构建；未重新读取原始三小时网格数据。")
p("[快照清单与SHA256](assets/provenance/snapshot.json) · [报告核验结果](validation.json) · [网格图元数据](assets/provenance/fig01_ssp_grid_2050_metadata.json) · [场站图元数据](assets/provenance/fig01_ssp_station_2050_metadata.json) · [复现脚本快照](assets/provenance/fig02/build_analysis_report.py) · [配套SLURM脚本快照](assets/provenance/fig02/build_analysis_report.sh)")
table(["证据", "文件"], [
    ["网格整体逐模式指标", "[panel_ab_models.csv](assets/data/ssp_grid_2050/panel_ab_models.csv)"],
    ["网格分类事件逐模式暴露", "[panel_cd_models.csv](assets/data/ssp_grid_2050/panel_cd_models.csv)"],
    ["网格纬带分类差", "[panel_ef.csv](assets/data/ssp_grid_2050/panel_ef.csv)"],
    ["网格地图展示数据", "[panel_gh.csv.gz](assets/data/ssp_grid_2050/panel_gh.csv.gz)"],
    ["场站整体逐模式指标", "[global_models.csv](assets/data/ssp_station_2050/global_models.csv)"],
    ["场站分类事件逐模式暴露", "[event_models.csv](assets/data/ssp_station_2050/event_models.csv)"],
    ["场站全部国家事件差", "[country_contrasts.csv](assets/data/ssp_station_2050/country_contrasts.csv)"],
    ["场站同步影响补充指标", "[global_extra_metrics.csv](assets/data/ssp_station_2050/global_extra_metrics.csv)"],
    ["场站覆盖与有效容量", "[capacity_coverage.csv](assets/data/ssp_station_2050/capacity_coverage.csv)"],
    ["统计定义与设计", "[数据使用指南](assets/provenance/BCSD_v2数据使用指南.md)；[主图与子图设计](assets/provenance/主图与子图设计.md)"],
])
p("正文包含极端事件图、Fig. 02完整图与三组子图、七张国家部署图。极端事件路径差图的风电、光伏独立子图链接见4.6节。以下为场站十个单独子图的原始PNG，可直接打开：")
p(" · ".join(f"[{letter}](assets/images/fig01_ssp_station_2050_{letter}.png)" for letter in "abcdefghij"))
p("复算方式：在1866项目根目录执行 source .venv/bin/activate，再运行 python -m paper_figures.main.fig02_generation_loss.report；使用已冻结的assets，不依赖之后的源图更新。也可使用同名.sh，运行前在仓库logs/paper_figures下创建日志目录。报告不含外部字体、脚本或CDN依赖，移动时请保留HTML、Markdown与assets的相对位置。")

def inline(text):
    # Report text uses ordinary Markdown links and optional bold spans only.
    text = escape(str(text))
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

md, body = [], []
nav = []
for block in blocks:
    kind = block[0]
    if kind == "heading":
        _, level_no, title, anchor = block
        md.extend([f'<a id="{anchor}"></a>', "#" * level_no + " " + title, ""])
        body.append(f'<h{level_no} id="{anchor}">{escape(title)}</h{level_no}>')
        if level_no == 2 or anchor == "event-contrasts":
            nav.append(f'<a href="#{anchor}">{escape(title)}</a>')
    elif kind in ("paragraph", "note"):
        text = block[1]
        md.extend([("> " if kind == "note" else "") + text, ""])
        body.append(f'<{"aside" if kind == "note" else "p"}>{inline(text)}</{"aside" if kind == "note" else "p"}>')
    elif kind == "figure":
        _, path, caption = block
        md.extend([f"![{caption}]({path})", "", caption, ""])
        body.append(f'<figure><a href="{escape(path)}"><img loading="lazy" src="{escape(path)}" alt="{escape(caption)}"></a><figcaption>{escape(caption)} 点击查看完整分辨率。</figcaption></figure>')
    elif kind == "table":
        _, headers, rows = block
        md.append("| " + " | ".join(headers) + " |")
        md.append("| " + " | ".join(["---"] * len(headers)) + " |")
        md.extend("| " + " | ".join(row) + " |" for row in rows)
        md.append("")
        head = "<thead><tr>" + "".join("<th>" + inline(c) + "</th>" for c in headers) + "</tr></thead>"
        content = "<tbody>" + "".join("<tr>" + "".join("<td>" + inline(c) + "</td>" for c in row) + "</tr>" for row in rows) + "</tbody>"
        body.append('<div class="table-wrap"><table>' + head + content + "</table></div>")
css = """
:root{color-scheme:light;--ink:#193048;--muted:#536679;--line:#dce4ec;--accent:#09677d}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:22px}
body{margin:0;background:#eef2f6;color:var(--ink);font:16px/1.85 system-ui,-apple-system,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
.layout{max-width:1640px;margin:auto;display:grid;grid-template-columns:250px minmax(0,1fr);gap:24px;padding:30px}
nav{position:sticky;top:24px;align-self:start;padding:20px;background:white;border:1px solid var(--line);border-radius:12px;font-size:14px}
nav strong{display:block;margin-bottom:12px}nav a{display:block;padding:8px 0;line-height:1.6}
main{background:white;padding:42px;min-width:0;overflow-wrap:anywhere;border:1px solid var(--line);border-radius:12px}
h1{font-size:32px;line-height:1.4;margin:0 0 18px}h2{font-size:24px;border-top:2px solid var(--line);padding-top:28px;margin-top:48px}
h3{font-size:20px;margin-top:36px}h4{font-size:17px;margin:24px 0 12px}p{margin:15px 0}
a{color:var(--accent);text-decoration:none;overflow-wrap:anywhere}a:hover{text-decoration:underline}
aside{padding:20px 24px;border-left:5px solid var(--accent);background:#eef7f8;margin:24px 0;line-height:1.9}
figure{margin:24px 0;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fff}
img{display:block;max-width:100%;height:auto;margin:auto}figcaption{font-size:14px;color:var(--muted);margin:12px 4px 0}
.table-wrap{overflow-x:auto;margin:20px 0;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.65}th,td{text-align:left;vertical-align:top;padding:11px 12px;border-bottom:1px solid var(--line);min-width:95px}
th{background:#edf3f7;color:#223d55;font-weight:650}tr:nth-child(even) td{background:#f8fafc}tr:last-child td{border-bottom:0}
footer{color:var(--muted);font-size:13px;margin-top:40px;border-top:1px solid var(--line);padding-top:16px}
@media(max-width:1000px){.layout{display:block;padding:12px}nav{position:static;margin-bottom:16px}nav a{display:inline-block;margin-right:16px}main{padding:22px}h1{font-size:26px}}
@media print{body{background:white}.layout{display:block;padding:0}nav{display:none}main{border:0;padding:0}h2{break-before:page}figure,aside{break-inside:avoid}a{color:inherit}.table-wrap{overflow:visible}table{font-size:9px}th,td{min-width:0;padding:5px}}
"""
(HERE / "report.md").write_text("\n".join(md), encoding="utf-8")
document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SSP路径对比｜极端事件、发电损失与国家部署</title><style>' + css + '</style></head><body><div class="layout"><nav aria-label="报告目录"><strong>SSP路径对比 · 风光发电</strong>' + "".join(nav) + '<a href="report.md">Markdown版</a><a href="#top">返回顶部</a></nav><main>' + "\n".join(body) + '<footer>Fig. 01、Fig. 02与国家部署分析快照 · 数据与图件均来自1866项目仓库 · 四模式集合 · HTML与Markdown共用同一份内容结构</footer></main></div></body></html>'
(HERE / "report.html").write_text(document, encoding="utf-8")

class AuditParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.images = [], set(), []
    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if "id" in attr:
            assert attr["id"] not in self.ids, attr["id"]
            self.ids.add(attr["id"])
        for key in ["href", "src"]:
            if key in attr:
                self.links.append(attr[key])
        if tag == "img":
            self.images.append(attr["src"])

parser = AuditParser()
parser.feed(document)
validation = {
    "status": "PASSED", "created_utc": datetime.now(timezone.utc).isoformat(),
    "period": [2030, 2059], "fig01_and_country_period": [2050, 2059], "scenarios": SSPS, "model_count": 4,
    "image_files": len(list((ASSETS / "images").rglob("*.png"))), "embedded_image_count": len(parser.images),
    "snapshot_file_count": len(manifest["files"]), "source_hashes": "PASSED",
    "level_recalculation_max_error": float(level_error),
    "station_contrast_max_error": float(station_error),
    "grid_contrast_max_error": float(grid_error),
    "event_accounting_max_error_days": float(max(closure_errors)),
    "frequency_duration_accounting_max_error_days": float(decomp_error),
    "event_contrast_figure_max_error_days": float(event_figure_error),
    "fig02": fig02_validation, "country": country_validation,
    "html_md_content": "same structured content",
    "html_local_links": "PASSED",
}
# validation.json is itself a linked report artifact.
(HERE / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for link in parser.links:
    if link.startswith("#"):
        assert link[1:] in parser.ids, link
    else:
        assert not re.match(r"https?://", link), link
        assert (HERE / link).is_file(), link
assert validation["image_files"] == 36
assert validation["embedded_image_count"] == 23
print(json.dumps(validation, ensure_ascii=False, indent=2))
print("REPORT:", HERE)
