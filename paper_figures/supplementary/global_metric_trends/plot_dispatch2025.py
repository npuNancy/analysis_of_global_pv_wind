"""Add future dispatch-2025 triptychs to the wind/PV data inventory."""
import argparse
import base64
import hashlib
import json
import os
import re
import textwrap
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from paper_figures.config import ROOT, MODELS, SSPS, SSP_COLORS
from paper_figures.common.plotting import configure, export_panel_png, independent_y_ticks
from paper_figures.supplementary.global_metric_trends.plot import TECHS, LABELS, PANEL_Y_STEPS

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DATA = OUT / "source_data"
DEFAULT_ROOT = Path("/work/home/acxujo26gv/dispatch_2025_climate_storage/ssp585")
PREFIX = "dispatch2025_station_"
URL = "../paper_figures/supplementary/global_metric_trends/"
CATEGORIES = {"capacity": "装机量", "exposure": "极端事件（暴露时长）",
              "loss": "损失", "generation": "发电"}
# metric, category, English title, Chinese title, ylabel, unit, numerator, denominator
METRICS = [
    ("capacity", "capacity", "Installed capacity", "总装机容量",
     "Installed capacity (TW)", "TW", "catalogue_capacity_mw", 1e6),
    ("exposure_total", "exposure", "Capacity-weighted exposure total", "装机容量加权暴露总量",
     "Exposure total (MW days yr⁻¹)", "MW days/year", "exposure_mw_days", 1.),
    ("exposure_mean", "exposure", "Capacity-weighted mean exposure", "装机容量加权年均暴露时长",
     "Exposure (days yr⁻¹)", "days/year", "exposure_mw_days", "capacity_mw"),
    ("total_loss", "loss", "Total net generation loss", "总净损失",
     "Net loss (MWh yr⁻¹)", "MWh/year", "net_loss_mwh", 1.),
    ("unit_loss", "loss", "Net loss per unit capacity", "单位装机净损失",
     "Net loss (MWh MW⁻¹ yr⁻¹)", "MWh/MW/year", "net_loss_mwh", "capacity_mw"),
    ("loss_fraction", "loss", "Loss / annual normal generation", "年净损失占全年正常基准电量比例",
     "Annual loss fraction (%)", "%", "net_loss_mwh", "normal_annual_mwh"),
    ("total_generation", "generation", "Total generation", "总发电量",
     "Generation (PWh yr⁻¹)", "PWh/year", "generation_mwh", 1e9),
    ("unit_generation", "generation", "Generation per unit capacity", "单位装机发电量",
     "Generation (MWh MW⁻¹ yr⁻¹)", "MWh/MW/year", "generation_mwh", "capacity_mw"),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def load_inputs(root):
    index_path = root / "runtime/authoritative_index.json"
    completion_path = root / "runtime/completion.json"
    index = json.loads(index_path.read_text())
    completion = json.loads(completion_path.read_text())
    assert index["status"] == completion["status"] == "COMPLETED"
    assert completion["index_sha256"] == sha(index_path)
    frames, sources = {}, []
    for name in ("global_annual_models.csv", "catalogue_capacity.csv"):
        path = root / "source_data" / name
        assert sha(path) == index["summaries"][name]["sha256"], name
        frames[name] = pd.read_csv(path)
        sources.append(dict(path=str(path), sha256=sha(path), rows=len(frames[name])))
    annual = frames["global_annual_models.csv"]
    annual = annual[annual.phase.eq("future") & annual.year.between(2030, 2059)
                    & annual.climate_ssp.eq(annual.station_ssp)].copy()
    available = [ssp for ssp in SSPS if annual.climate_ssp.eq(ssp).any()]
    assert {"ssp126", "ssp245"} <= set(available)
    keys = ["model", "climate_ssp", "tech", "year"]
    assert not annual.duplicated(keys).any()
    assert set(annual[keys].itertuples(index=False, name=None)) == set(
        product(MODELS, available, TECHS, range(2030, 2060)))
    additive = ["capacity_mw", "catalogue_capacity_mw", "exposure_mw_days",
                "net_loss_mwh", "generation_mwh", "normal_annual_mwh"]
    assert np.isfinite(annual[additive]).all().all()
    assert annual[["capacity_mw", "normal_annual_mwh"]].gt(0).all().all()
    assert annual.capacity_coverage.between(0, 1).all()
    group = ["model", "climate_ssp", "year"]
    joint = annual[annual.tech.eq("wind+solar")].set_index(group).sort_index()
    summed = annual[annual.tech.ne("wind+solar")].groupby(group)[additive].sum().sort_index()
    np.testing.assert_allclose(joint[additive], summed, rtol=1e-10)
    for column, numerator, denominator, factor in [
        ("unit_loss_mwh_per_mw", "net_loss_mwh", "capacity_mw", 1),
        ("loss_fraction_pct", "net_loss_mwh", "normal_annual_mwh", 100),
        ("unit_generation_mwh_per_mw", "generation_mwh", "capacity_mw", 1),
        ("exposure_days", "exposure_mw_days", "capacity_mw", 1),
    ]:
        np.testing.assert_allclose(annual[column], factor*annual[numerator]/annual[denominator],
                                   rtol=1e-10)
    annual["snapshot"] = annual.year // 10 * 10
    cap = frames["catalogue_capacity.csv"]
    cap = cap[cap.station_ssp.isin(available) & cap.snapshot.isin([2030, 2040, 2050])].copy()
    capkeys = ["station_ssp", "tech", "snapshot"]
    assert not cap.duplicated(capkeys).any()
    assert set(cap[capkeys].itertuples(index=False, name=None)) == set(
        product(available, ["wind", "solar"], [2030, 2040, 2050]))
    combined = cap.groupby(["station_ssp", "snapshot"], as_index=False).catalogue_capacity_mw.sum()
    combined["tech"] = "wind+solar"
    cap = pd.concat([cap, combined], ignore_index=True)
    cap["climate_ssp"], cap["model"] = cap.station_ssp, "catalogue"
    check = annual.merge(cap[capkeys+["catalogue_capacity_mw"]],
                         on=capkeys, suffixes=("", "_check"), validate="many_to_one")
    np.testing.assert_allclose(check.catalogue_capacity_mw, check.catalogue_capacity_mw_check,
                               rtol=1e-10)
    provenance = dict(root=str(root), index_sha256=sha(index_path),
                      completion_sha256=sha(completion_path), summaries=sources)
    return annual, cap, available, provenance


def metric_tables(spec, annual, cap, available):
    metric, category, _, _, _, unit, numerator, denominator = spec
    is_annual = category in ("loss", "generation")
    is_capacity = metric == "capacity"
    frame = (cap if is_capacity else annual).copy()
    frame["numerator"] = frame[numerator] * (100 if metric == "loss_fraction" else 1)
    frame["denominator"] = frame[denominator] if isinstance(denominator, str) else denominator
    frame["value"] = frame.numerator / frame.denominator
    frame["time"] = frame.year if is_annual else frame.snapshot
    if category == "exposure":
        group = ["model", "station_ssp", "climate_ssp", "tech", "time"]
        assert frame.groupby(group).size().eq(10).all()
        assert frame.groupby(group).capacity_mw.nunique().eq(1).all()
        fields = ["numerator", "denominator", "value", "capacity_mw",
                  "catalogue_capacity_mw", "capacity_coverage"]
        frame = frame.groupby(group, as_index=False)[fields].mean()
    fields = ["model", "station_ssp", "climate_ssp", "tech", "time",
              "numerator", "denominator", "value", "catalogue_capacity_mw"]
    if not is_capacity:
        fields += ["capacity_mw", "capacity_coverage"]
    frame = frame[fields]
    times = range(2030, 2060) if is_annual else [2030, 2040, 2050]
    models = ["catalogue"] if is_capacity else MODELS
    keys = ["model", "climate_ssp", "tech", "time"]
    assert set(frame[keys].itertuples(index=False, name=None)) == set(
        product(models, available, TECHS, times))
    assert not frame.duplicated(keys).any()
    np.testing.assert_allclose(frame.value, frame.numerator/frame.denominator, rtol=1e-12)
    assert np.isfinite(frame.value).all()
    # The full SSP matrix retains missing paths as NaN, never as zero.
    full = pd.MultiIndex.from_product([models, SSPS, TECHS, times], names=keys)
    frame = frame.set_index(keys).reindex(full).reset_index()
    frame["station_ssp"] = frame.climate_ssp
    frame["snapshot"] = frame.time // 10 * 10
    frame["phase"], frame["unit"] = "future", unit
    frame["data_status"] = np.where(frame.value.notna(), "available", "pending")
    display = frame.groupby(["climate_ssp", "tech", "time"]).value.agg(
        mean="mean", minimum="min", maximum="max", n_models="count").reset_index()
    display["data_status"] = np.where(display.n_models.gt(0), "available", "pending")
    display["station_ssp"], display["phase"] = display.climate_ssp, "future"
    assert display.loc[display.climate_ssp.isin(available), "n_models"].eq(len(models)).all()
    pending = display[~display.climate_ssp.isin(available)]
    assert pending.n_models.eq(0).all()
    assert pending[["mean", "minimum", "maximum"]].isna().all().all()
    name = PREFIX + metric
    frame.to_csv(DATA / (name+"_models.csv"), index=False)
    display.to_csv(DATA / (name+"_display.csv"), index=False)
    return display


def draw_axis(ax, display, tech, annual, name):
    fits = []
    for ssp, marker in zip(SSPS, ("o", "s", "^")):
        g = display[display.tech.eq(tech) & display.climate_ssp.eq(ssp)
                    & display.n_models.gt(0)].sort_values("time")
        x, y = g.time.to_numpy(float), g["mean"].to_numpy(float)
        # Empty Line2D keeps the SSP585 curve interface while its data are pending.
        ax.plot(x, y, color=SSP_COLORS[ssp], lw=1.15,
                marker=None if annual else marker, ms=3.5, label=ssp.upper(), gid=ssp)
        if annual and len(x):
            slope, intercept = np.polyfit(x-2030, y, 1)
            predicted = intercept + slope*(x-2030)
            ax.plot(x, predicted, color=SSP_COLORS[ssp], lw=1, ls="--")
            total = float(np.sum((y-y.mean())**2))
            fits.append(dict(figure=name, tech=tech, climate_ssp=ssp, start=2030, end=2059,
                             n_years=len(x), slope_per_year=float(slope),
                             fitted_value_2030=float(intercept),
                             r_squared=float(1-np.sum((y-predicted)**2)/total) if total else None))
    ax.set_title(LABELS[TECHS.index(tech)], fontsize=9, pad=8)
    if annual:
        ax.set_xticks([2030, 2040, 2050, 2059])
        ax.set_xlim(2029, 2060)
        ax.set_xlabel("Year")
    else:
        ax.set_xticks([2030, 2040, 2050], ["2030s", "2040s", "2050s"])
        ax.set_xlim(2028, 2052)
        ax.set_xlabel("Decade")
    ax.grid(axis="y", color=".9", lw=.45)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 5), useMathText=True)
    ax.tick_params(length=3, width=.7)
    return fits


def render(spec, display, available):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    metric, category, title, title_zh, ylabel, unit, _, _ = spec
    name, old_name = PREFIX+metric, "station_"+metric
    annual = category in ("loss", "generation")
    independent = old_name in PANEL_Y_STEPS or metric == "unit_loss"
    configure()
    plt.rcParams.update({"font.size": 8})
    fig, axes = plt.subplots(1, 3, figsize=(240/25.4, 85/25.4), sharey=not independent)
    fig.subplots_adjust(left=.10, right=.985, bottom=.23, top=.78,
                        wspace=.32 if independent else .14)
    fits = []
    for ax, tech in zip(axes, TECHS):
        fits.extend(draw_axis(ax, display, tech, annual, name))
    if metric == "unit_loss":
        for ax in axes:
            independent_y_ticks(ax)
        fig.text(.54, .875, "Independent y-axis ranges; 5 intervals per panel",
                 ha="center", fontsize=7, color=".4")
    elif independent:
        for ax, step in zip(axes, PANEL_Y_STEPS[old_name]):
            values = np.concatenate([line.get_ydata() for line in ax.lines])
            padding = max(float(np.ptp(values))*.08, step*.15)
            lower = np.floor((values.min()-padding)/step)*step
            upper = np.ceil((values.max()+padding)/step)*step
            ax.set_yticks(np.arange(lower, upper+step*.5, step))
            ax.set_ylim(lower, upper)
        fig.text(.54, .875, "Independent y-axis ranges", ha="center", fontsize=7, color=".4")
    axes[0].set_ylabel(ylabel, labelpad=7)
    fig.suptitle("Global stations dispatch-2025 | "+title, fontsize=10, y=.97)
    handles = [Line2D([0], [0], color=SSP_COLORS[s], lw=1.5,
                      label=s.upper()+(" (pending)" if s not in available else "")) for s in SSPS]
    if annual:
        handles += [Line2D([0], [0], color=".4", ls="--", lw=1, label="2030–2059 linear fit")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.53, .015),
               ncol=len(handles), fontsize=8)
    fig.canvas.draw()
    axis_metadata = []
    for tech, ax in zip(TECHS, axes):
        values = np.concatenate([line.get_ydata() for line in ax.lines])
        lo, hi = ax.get_ylim()
        assert lo < values.min() and hi > values.max()
        curves = {line.get_gid(): len(line.get_xdata()) for line in ax.lines if line.get_gid()}
        assert curves == {ssp: (30 if annual else 3) if ssp in available else 0 for ssp in SSPS}
        axis_metadata.append(dict(tech=tech, limits=[float(lo), float(hi)],
                                  ticks=ax.get_yticks().tolist(), scenario_points=curves))
    complete = export_panel_png(fig, OUT/(name+".png"))
    panels = []
    for letter, tech, axis in zip("abc", TECHS, axis_metadata):
        solo, ax = plt.subplots(figsize=(110/25.4, 85/25.4))
        solo.subplots_adjust(left=.24, right=.95, bottom=.27, top=.73)
        draw_axis(ax, display, tech, annual, name)
        ax.set_yticks(axis["ticks"])
        ax.set_ylim(axis["limits"])
        ax.set_ylabel(ylabel, labelpad=7)
        solo.suptitle("Global stations dispatch-2025\n"+"\n".join(textwrap.wrap(title, 43)),
                      fontsize=9, y=.98)
        solo.legend(handles=handles, loc="lower center", bbox_to_anchor=(.53, .005),
                    ncol=2, fontsize=8)
        np.testing.assert_allclose(ax.get_ylim(), axis["limits"])
        np.testing.assert_allclose(ax.get_yticks(), axis["ticks"])
        panels.append(export_panel_png(solo, OUT/(name+"_"+letter+".png")))
    if annual:
        pd.DataFrame(fits).to_csv(DATA/(name+"_fits.csv"), index=False)
    print("Rendered "+name, flush=True)
    return dict(name=name, category=category, metric=metric, title=title_zh, unit=unit,
                annual=annual, independent_y=independent, axes=axis_metadata,
                complete=complete, panels=panels, linear_fits=fits,
                model_table="source_data/"+name+"_models.csv",
                display_table="source_data/"+name+"_display.csv")


def block(name, content):
    return f"<!-- DISPATCH2025:{name} BEGIN -->\n{content}\n<!-- DISPATCH2025:{name} END -->\n"


def update_html(records, available, data_root=DEFAULT_ROOT):
    path = ROOT / "document/风电光伏数据.html"
    html = path.read_text(encoding="utf-8")
    html = re.sub(r"<!-- DISPATCH2025:(\w+) BEGIN -->\n.*?<!-- DISPATCH2025:\1 END -->\n",
                  "", html, flags=re.S)
    old_images = re.findall(r"<img\b[^>]*>", html)
    existing_figures = len(re.findall(r"<h4\b", html))
    assert len(old_images) == existing_figures
    for category in CATEGORIES:
        nav = f'<li><a href="#{category}-dispatch">全球场站-dispatch</a></li>\n'
        assert html.count(nav) == 1
        html = html.replace(nav, nav+block("nav_"+category,
            f'<li><a href="#{category}-dispatch2025">全球场站-dispatch-2025</a></li>'), 1)
        content = f'<h3 id="{category}-dispatch2025">全球场站-dispatch-2025</h3>\n'
        content += ("<p>未来期2030—2059年；从左至右为风电+光伏、风电、光伏。"
                    "SSP126/245/585沿用深蓝、赭黄、深红。</p>\n")
        for record in (r for r in records if r["category"] == category):
            name = record["name"]
            png = OUT/record["complete"]["path"]
            assert sha(png) == record["complete"]["sha256"]
            data = base64.b64encode(png.read_bytes()).decode("ascii")
            content += f'<h4 id="figure-{name}">{record["title"]}</h4>\n<figure>\n'
            content += (f'<img src="data:image/png;base64,{data}" '
                        f'data-source="{URL}outputs/{png.name}" '
                        f'alt="全球场站-dispatch-2025：{record["title"]}，未来期三面板">\n')
            if record["metric"] == "capacity":
                caption = "2030、2040、2050完整目录容量快照，按2030s、2040s、2050s标注。"
            elif record["annual"]:
                caption = "2030—2059逐年四模式等权均值；虚线为每条路径的全30年线性拟合。"
            else:
                caption = "2030s、2040s、2050s各模式十年均值，再取四模式等权均值。"
            if "ssp585" not in available:
                caption += "SSP585数据待补，保留深红图例和空折线接口，缺测不作零值。"
            links = "；".join(f'<a href="{URL}outputs/{name}_{letter}.png">{label}</a>'
                              for letter, label in zip("abc", ("风光合计", "风电", "光伏")))
            content += f'<figcaption>{caption}独立子图：{links}。</figcaption>\n</figure>\n'
        anchor = f'<h3 id="{category}-lcoe">'
        assert html.count(anchor) == 1
        html = html.replace(anchor, block(category, content.rstrip())+anchor, 1)
    overview = re.search(r"<tr>\s*<td>全球场站-dispatch</td>.*?</tr>", html, re.S)
    assert overview
    row = overview.group().replace("全球场站-dispatch</td>", "全球场站-dispatch-2025</td>", 1)
    html = html[:overview.end()] + block("overview", row) + html[overview.end():]
    rows = []
    for r in records:
        rows.append(f'<tr><td>{CATEGORIES[r["category"]]}</td><td>{r["title"]}</td>'
                    f'<td><a href="{URL}outputs/{r["complete"]["path"]}">PNG</a></td>'
                    f'<td><a href="{URL}outputs/{r["model_table"]}">CSV</a></td>'
                    f'<td><a href="{URL}outputs/{r["display_table"]}">CSV</a></td></tr>')
    inventory = (
        '<h3 id="dispatch2025-results">全球场站-dispatch-2025结果路径</h3>\n'
        '<p>仅未来期2030—2059。正式数据索引和计算口径见'
        '<a href="#dispatch2025-notes">dispatch-2025数据说明</a>。</p>\n'
        '<div class="table-scroll"><table><thead><tr><th>类别</th><th>指标</th>'
        '<th>完整图</th><th>逐模式计算结果</th><th>绘图均值</th></tr></thead><tbody>\n'
        +"\n".join(rows)+"\n</tbody></table></div>")
    anchor = "<!-- GEM2025:results BEGIN -->"
    assert html.count(anchor) == 1
    html = html.replace(anchor, block("results", inventory)+anchor, 1)
    # Existing anchors remain stable when new figures are inserted into each metric group.
    old_to_new, count = {}, 0

    def number_figure(match):
        nonlocal count
        count += 1
        title = match[2]
        old = re.match(r"图\s*(\d+)\.\s*(.*)", title, re.S)
        if old:
            old_to_new[int(old[1])] = count
            title = old[2]
        return match[1]+f"图 {count}. "+title+match[3]

    html = re.sub(r"(<h4\b[^>]*>)(.*?)(</h4>)", number_figure, html, flags=re.S)

    def update_references(match):
        body = re.sub(r"图\s*(\d+(?:、\d+)*)", lambda m: "图"+"、".join(
            str(old_to_new.get(int(n), int(n))) for n in m[1].split("、")), match[2])
        return match[1]+body+match[3]

    html = re.sub(r'(<section[^>]*aria-labelledby="notes"[^>]*>)(.*?)(</section>)',
                  update_references, html, count=1, flags=re.S)
    status = ("SSP585尚无正式数据；源表保留NaN行，图中保留深红图例和空折线接口。"
              "补齐同结构且通过验收的SSP585/SSP585数据后，重新运行即可绘制实线及年度拟合。"
              if "ssp585" not in available else "SSP585配对路径已纳入图表。")
    notes = f"""<h3 id="dispatch2025-notes">全球场站-dispatch-2025：数据及绘图</h3>
<p>使用dispatch-2025正式汇总数据，范围为2030—2059年，气候SSP与场站SSP同名配对。{status}</p>
<ul class="defs">
<li>装机量使用2030、2040、2050完整目录快照（TW），不是新增容量累加；风电单位MW，光伏单位MWp/DC。</li>
<li>其余指标使用每条配对路径、每种技术在四模式和30年内固定的共同有效场站。容量加权暴露总量为容量乘事件并集累计小时除以24后求和；平均暴露为该总量除以相同有效容量。暴露先取模式内十年均值，再对四模式等权平均。</li>
<li>总损失保留事件并集的带符号净损失；单位装机损失除以有效容量。损失占比为净损失除以全年正常基准电量再乘100%，分母不是实际发电量或事件期电量。风电能量使用原始数值。</li>
<li>发电量按原生日历统计全年实际CF对应电量；单位装机发电量除以有效容量。风光合计先加总分子、分母，再求比值。路径差同时包含气候与部署变化。</li>
<li>图式沿用全球场站-dispatch：一行三列，依次风光合计、风电、光伏；装机和暴露显示三个年代点，损失和发电显示逐年均值实线及全30年OLS虚线。四模式最小/最大值保留在CSV，不绘制范围带；装机容量为单一目录值。</li>
<li>单位装机损失、损失占比和单位装机发电采用原dispatch的独立纵轴规则，其余图共用纵轴。共8张完整图和24张独立子图，均为600 dpi PNG，完整图已嵌入本HTML。</li>
</ul>
<p>正式数据根目录：<code>{data_root}</code>；读取<code>runtime/authoritative_index.json</code>、<code>runtime/completion.json</code>与<code>source_data/</code>下的小型汇总CSV，并校验索引和文件哈希。完整数据说明见<a href="全球场站-dispatch-2025气候评价.md">独立评价报告</a>。</p>
<p>同目录代码：<a href="{URL}plot_dispatch2025.py">Python绘图与HTML更新</a>、<a href="{URL}plot_dispatch2025.sh">SLURM脚本</a>；
<a href="{URL}outputs/dispatch2025_figure_manifest.json">图件与输入清单</a>、
<a href="{URL}outputs/dispatch2025_validation.json">数值及导出校验</a>。</p>"""
    anchor = "<h3>网格与全球场站-dispatch：计算定义</h3>"
    assert html.count(anchor) == 1
    html = html.replace(anchor, block("notes", notes)+anchor, 1)
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "Duplicate anchors"
    assert set(re.findall(r'href="#([^"]+)"', html)) <= set(ids), "Missing anchor"
    images = re.findall(r"<img\b[^>]*>", html)
    preserved = [tag for tag in images if f"/{PREFIX}" not in tag]
    assert preserved == old_images, "Existing images changed"
    assert len(images) == count == existing_figures+8
    for record in records:
        tag = next(tag for tag in images if f'/{record["name"]}.png"' in tag)
        payload = re.search(r'src="data:image/png;base64,([^"]+)"', tag)[1]
        assert hashlib.sha256(base64.b64decode(payload)).hexdigest() == record["complete"]["sha256"]
    for match in re.finditer(r"<!-- DISPATCH2025:\w+ BEGIN -->(.*?)<!-- DISPATCH2025:\w+ END -->",
                             html, re.S):
        for url in re.findall(r'href="([^"#]+)"', match[1]):
            assert (path.parent/url).is_file(), url
    path.write_text(html, encoding="utf-8")
    return dict(path=str(path.relative_to(ROOT)), sha256=sha(path), embedded_figures=count,
                added_figures=8, existing_images_preserved=True, unique_anchors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Accepted dispatch-2025 data root, including optional paired SSP585")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("MPLCONFIGDIR", str(OUT/".mplconfig"))
    annual, cap, available, provenance = load_inputs(args.root)
    contract = dict(
        question="How do paired dispatch-2025 future capacity, exposure, loss and generation evolve?",
        backend="Python/matplotlib", archetype="quantitative grid",
        years=[2030, 2059], layout="wind+solar, wind, solar; 1 row x 3 columns",
        reference="plot.py station figures", dimensions_mm=[240, 85],
        scenarios=SSPS, available_scenarios=available,
        pending="NaN source rows; empty colored Line2D and pending legend; no fitted values",
        centre="4-model equal mean; capacity is deterministic catalogue total",
        spread="model min/max retained in source CSV, no uncertainty band",
        fit="one descriptive 2030–2059 OLS per available annual pathway and panel",
        export="8 complete + 24 independent PNG, 600 dpi",
        risks=["paired paths include deployment and climate changes",
               "signed net loss denominator is annual normal baseline generation",
               "intensities use common-support capacity, capacity plot uses full catalogue"])
    write_json(OUT/"dispatch2025_figure_contract.json", contract)
    records = [render(spec, metric_tables(spec, annual, cap, available), available)
               for spec in METRICS]
    fits = [fit for record in records for fit in record["linear_fits"]]
    assert len(fits) == 5*3*len(available)
    pd.DataFrame(fits).to_csv(DATA/"dispatch2025_all_linear_fits.csv", index=False)
    manifest = dict(status="NUMERIC_AND_EXPORT_PASSED", name="全球场站-dispatch-2025",
                    provenance=provenance, available_scenarios=available,
                    pending_scenarios=[s for s in SSPS if s not in available], figures=records)
    write_json(OUT/"dispatch2025_figure_manifest.json", manifest)
    validation = dict(status="NUMERIC_AND_EXPORT_PASSED", figures=8, independent_panels=24,
                      linear_fits=len(fits), years=[2030, 2059], paired_annual_rows=len(annual),
                      capacity_coverage=[float(annual.capacity_coverage.min()),
                                         float(annual.capacity_coverage.max())],
                      checks=["formal index and summary hashes", "complete 4-model future matrix",
                              "wind+solar additive totals", "source metric ratios",
                              "catalogue capacity agreement", "missing SSP NaN matrices",
                              "3 scenario curve objects per panel", "mean and fit bounds",
                              "600 dpi PNG and text bounds", "full/panel axis equality"])
    write_json(OUT/"dispatch2025_validation.json", validation)
    validation["html"] = update_html(records, available, args.root)
    write_json(OUT/"dispatch2025_validation.json", validation)
    print(json.dumps(validation, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
