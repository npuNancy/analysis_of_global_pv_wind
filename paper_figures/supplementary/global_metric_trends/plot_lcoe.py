"""Render paired LCOE triptychs and embed them in the Markdown/HTML inventory."""
import base64
import json
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd

from paper_figures.common.plotting import configure, export_panel_png
from paper_figures.config import ROOT, SSP_COLORS
from paper_figures.supplementary.global_metric_trends.prepare_lcoe import OUT, DATA, PAIRS, require, sha

TECHS = ["wind+solar", "wind", "solar"]
NAMES = ["lcoe_station_capacity", "lcoe_station_exposure_total", "lcoe_station_exposure_mean"]
TITLES = ["总装机量", "容量加权暴露总量", "容量加权年均暴露时长"]
UNITS = ["TW", "MW·天/年", "天/年"]


ANNUAL_METRICS = [
    ("station_total_loss", "Total net generation loss", "Net loss (MWh yr⁻¹)"),
    ("station_unit_loss", "Net loss per unit capacity", "Net loss (MWh MW⁻¹ yr⁻¹)"),
    ("station_loss_fraction", "Loss / annual normal generation", "Annual loss fraction (%)"),
    ("station_total_generation", "Total generation", "Generation (PWh yr⁻¹)"),
    ("station_unit_generation", "Generation per unit capacity", "Generation (MWh MW⁻¹ yr⁻¹)"),
]


def independent_y_ticks(ax, intervals=5):
    """Fit all displayed curves with padded, round ticks and a fixed interval count."""
    values=np.concatenate([np.asarray(line.get_ydata(),dtype=float) for line in ax.lines])
    require(np.isfinite(values).all(),"Nonfinite plotted values")
    minimum,maximum=float(values.min()),float(values.max())
    span=max(maximum-minimum,abs(maximum)*1e-6,1e-12)
    lower,upper=minimum-.06*span,maximum+.06*span
    exponent=int(np.floor(np.log10((upper-lower)/intervals)))
    for power in range(exponent,exponent+4):
        for factor in (1.,1.25,1.5,2.,2.5,3.,4.,5.,6.,8.):
            step=factor*10.**power
            first=int(np.ceil(upper/step-intervals-1e-10))
            last=int(np.floor(lower/step+1e-10))
            if first>last:
                continue
            anchor=int(np.clip(np.rint((lower+upper)/(2*step)-intervals/2),first,last))
            ticks=(anchor+np.arange(intervals+1,dtype=float))*step
            ticks[np.abs(ticks)<step*1e-10]=0.
            ax.set_yticks(ticks)
            ax.set_ylim(float(ticks[0]),float(ticks[-1]))
            require(ticks[0]<minimum and maximum<ticks[-1],"Clipped curve")
            np.testing.assert_allclose(np.diff(ticks),step,rtol=1e-10)
            return dict(lower=float(ticks[0]),upper=float(ticks[-1]),step=step,
                        intervals=intervals,ticks=ticks.tolist(),
                        data_minimum=minimum,data_maximum=maximum)
    raise ValueError("Unable to choose independent y ticks")


def draw(frame, name, metric, ylabel, capacity=False, annual=False, display=None, fits=None, output=None):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    time="year" if annual else "snapshot"
    keys=["station_ssp","climate_ssp","tech",time]
    require(not frame.duplicated(keys+["model"]).any(), "Duplicate display records")
    if display is None:
        display=frame.groupby(keys).value.agg(mean="mean",minimum="min",maximum="max",n_models="count").reset_index()
    require(len(display)==(270 if annual else 27) and display.n_models.eq(1 if capacity else 4).all(),"Display matrix")
    if not annual:
        frame.to_csv(DATA/(name+"_models.csv"),index=False)
        display.to_csv(DATA/(name+"_display.csv"),index=False)
    configure()
    plt.rcParams.update({"font.size":8})
    fig,axes=plt.subplots(1,3,figsize=(240/25.4,85/25.4),sharey=False)
    fig.subplots_adjust(left=.10,right=.985,bottom=.28,top=.78,wspace=.40)
    for ax,tech,title in zip(axes,TECHS,["Wind + solar","Wind","Solar"]):
        for (s,c),marker in zip(PAIRS.items(),["o","s","^"]):
            g=display[display.tech.eq(tech)&display.station_ssp.eq(s)].sort_values(time)
            ax.plot(g[time],g["mean"],color=SSP_COLORS[c],marker=None if annual else marker,ms=3.5,lw=1.15)
            if annual:
                fit=fits[fits.tech.eq(tech)&fits.station_ssp.eq(s)].iloc[0]
                ax.plot(g.year,fit.fitted_value_2030+fit.slope_per_year*(g.year-2030),
                        color=SSP_COLORS[c],lw=1,ls="--")
        ax.set_title(title,fontsize=9,pad=8)
        if annual:
            ax.set_xticks([2030,2040,2050,2059])
            ax.set_xlim(2029,2060)
            ax.set_xlabel("Year")
        else:
            ax.set_xticks([2030,2040,2050],["2030","2040","2050"] if capacity else ["2030s","2040s","2050s"])
            ax.set_xlim(2028,2052)
            ax.set_xlabel("Capacity snapshot" if capacity else "Decade")
        ax.grid(axis="y",color=".9",lw=.45)
        ax.ticklabel_format(axis="y",style="sci",scilimits=(-3,5),useMathText=True)
        ax.tick_params(length=3,width=.7)
    y_axes=[dict(tech=tech,**independent_y_ticks(ax)) for ax,tech in zip(axes,TECHS)]
    fig.text(.54,.875,"Independent y-axis ranges; 5 intervals per panel",
             ha="center",fontsize=7,color=".4")
    axes[0].set_ylabel(ylabel,labelpad=7)
    fig.suptitle("LCOE global stations | "+metric,fontsize=10,y=.97)
    handles=[Line2D([0],[0],color=SSP_COLORS[c],lw=1.5,marker=None if annual else mk,ms=3.5,
                   label=s.upper()+" / "+c.upper())
             for (s,c),mk in zip(PAIRS.items(),["o","s","^"])]
    if annual:
        handles.append(Line2D([0],[0],color=".4",lw=1,ls="--",label="2030–2059 linear fit"))
    fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.53,.075),
               ncol=len(handles),fontsize=7 if annual else 8)
    fig.text(.53,.025,"Legend: station SSP / climate SSP. "+(
        "Full catalogue capacity." if capacity else
        "Lines: four-GCM mean; dashed: linear fit." if annual else
        "Lines: four-GCM mean; exposure days = accumulated event hours / 24."),
        ha="center",fontsize=6.7,color=".35")
    qa=export_panel_png(fig,output or OUT/(name+".png"))
    return dict(name=name,figure=qa,model_table=str(DATA/(name+"_models.csv")),
                display_table=str(DATA/(name+"_display.csv")),
                y_limits=[list(ax.get_ylim()) for ax in axes],y_axes=y_axes,independent_y_axes=True)


def update_documents(coverage, minimum_time_coverage):
    both=coverage[coverage.tech.eq("wind+solar")].capacity_fraction*100
    pct=f"{both.min():.2f}%–{both.max():.2f}%"
    prefix="../paper_figures/supplementary/global_metric_trends/outputs/"
    section="""## 基于 LCOE 选址的装机量与极端事件暴露

三张完整组图均为一行三列，依次为**风电＋光伏、陆上风电、光伏**，仅显示场站SSP／气候SSP配对路径：**126／126、245／245、560／585**。高排放路径的场站布局仍为SSP5-6.0，气候为SSP5-8.5。各子图采用独立Y轴上下限，统一5个刻度间隔（6个刻度值），分别显示数值标签。

- **总装机量（TW）**：分别汇总2030、2040、2050年完整LCOE选址目录的总容量；三个年份为累计快照，不再次相加。
- **容量加权暴露总量（MW·天/年）**：逐场站累计适用事件时间并集的暴露小时，除以24后乘以该年代容量，再全球求和。
- **容量加权年均暴露时长（天/年）**：暴露总量除以相同有效场站的容量总量。风光合计先加总两种技术的容量加权分子、分母，再相除；不将两种技术的均值直接平均。
- 暴露统计覆盖2030–2039、2040–2049、2050–2059，各窗口使用2030、2040、2050年容量快照。先计算单模式十年均值，再对四个气候模式等权平均；图中不绘制线性拟合或置信区间，模式最小／最大值保留在源数据表。
- 风电使用5类、光伏使用6类正式事件的**时间并集**，不累加重叠事件。1天表示24小时累计暴露，不是发生事件的日历天数。保留原生日历，缺测不作无事件，也不外推缺失时段。
- 沿用原文档场站暴露图的有效性口径：采用配对Loss产品的四模式、30年共同有效场站集合，并核验各站点每年事件有效时间至少99%。本批最低时间覆盖率为MINIMUM_TIME%；风光合计有效容量占完整目录的CAPACITY_RANGE。完整装机量图不作此筛选，暴露图也不放大至完整目录容量。

数据入口为[BCSD数据指南第12节](BCSD_v2数据使用指南.md)中1959共享目录的Extreme正式索引；容量与共同有效集合按第11节配对Loss档案核对。配对路径差同时包含气候、部署与容量权重变化。

新增代码与原图代码同目录：[数据汇总](../paper_figures/supplementary/global_metric_trends/prepare_lcoe.py)、[绘图及文档更新](../paper_figures/supplementary/global_metric_trends/plot_lcoe.py)，各有同名SLURM脚本。源数据为该目录outputs/source_data下的lcoe_station_capacity、lcoe_station_exposure_annual_models、lcoe_station_exposure_decadal_models及lcoe_station_exposure_coverage等CSV；输入索引摘要、时间完整性与覆盖校验记录在outputs/lcoe_exposure_validation.json。
""".replace("MINIMUM_TIME",f"{minimum_time_coverage*100:.4f}").replace("CAPACITY_RANGE",pct)
    for number,name,title,unit in zip(range(17,20),NAMES,TITLES,UNITS):
        section+=f"\n### {number}. LCOE全球场站：{title}\n\n![LCOE全球场站：{title}（{unit}）]({prefix}{name}.png)\n"
    md=ROOT/"document/风电光伏数据.md"
    content=md.read_text().replace("数据来源：", "原始指标表来源：", 1)
    if "| LCOE全球场站 |" not in content:
        original=next(line for line in content.splitlines() if line.startswith("| 全球场站 |"))
        content=content.replace(original,original+"\n"+original.replace("| 全球场站 |","| LCOE全球场站 |"),1)
    start="<!-- LCOE_CAPACITY_EXPOSURE_START -->"
    end="<!-- LCOE_CAPACITY_EXPOSURE_END -->"
    block=start+"\n"+section.rstrip()+"\n"+end
    if start in content:
        content=re.sub(re.escape(start)+r".*?"+re.escape(end),lambda _:block,content,flags=re.S)
    else:
        content=content.rstrip()+"\n\n"+block+"\n"
    md.write_text(content)
    html=ROOT/"document/风电光伏数据.html"
    content=html.read_text().replace("数据来源：", "原始指标表来源：", 1)
    if "<td>LCOE全球场站</td>" not in content:
        match=re.search(r"<tr>\s*<td>全球场站</td>.*?</tr>",content,re.S)
        require(match is not None,"Original HTML inventory row missing")
        row=match.group()
        content=content[:match.end()]+"\n"+row.replace("<td>全球场站</td>","<td>LCOE全球场站</td>")+content[match.end():]
    # Convert only the new prose; existing document markup and embedded figures stay byte-identical.
    paragraphs=section.split("\n### 17.")[0].strip().split("\n\n")
    import html as html_lib
    def inline(text):
        text=html_lib.escape(text)
        text=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",text)
        text=re.sub(r"\[([^]]+)\]\(([^)]+)\)",r'<a href="\2">\1</a>',text)
        return text
    body=[]
    for paragraph in paragraphs:
        if paragraph.startswith("## "):
            body.append("<h2>"+inline(paragraph[3:])+"</h2>")
        elif paragraph.startswith("- "):
            body.append("<ul>"+"".join("<li>"+inline(line[2:])+"</li>" for line in paragraph.splitlines())+"</ul>")
        else:
            body.append("<p>"+inline(paragraph)+"</p>")
    for number,name,title,unit in zip(range(17,20),NAMES,TITLES,UNITS):
        encoded=base64.b64encode((OUT/(name+".png")).read_bytes()).decode()
        caption=f"LCOE全球场站：{title}（{unit}）"
        body.append(f'<h3>{number}. LCOE全球场站：{title}</h3>\n<figure>\n'
                    f'  <img src="data:image/png;base64,{encoded}" alt="{caption}">\n'
                    f'  <figcaption>{caption}</figcaption>\n</figure>')
    block='<!-- LCOE_CAPACITY_EXPOSURE_START -->\n'+"\n\n".join(body)+'\n<!-- LCOE_CAPACITY_EXPOSURE_END -->'
    if "<!-- LCOE_CAPACITY_EXPOSURE_START -->" in content:
        content=re.sub(r"<!-- LCOE_CAPACITY_EXPOSURE_START -->.*?<!-- LCOE_CAPACITY_EXPOSURE_END -->",lambda _:block,content,flags=re.S)
    else:
        require(content.count("</body>")==1,"HTML closing body")
        content=content.replace("</body>",block+"\n\n</body>")
    html.write_text(content)


def main():
    os.environ.setdefault("MPLBACKEND","Agg")
    os.environ.setdefault("MPLCONFIGDIR",str(OUT/".mplconfig"))
    audit=json.loads((OUT/"lcoe_exposure_validation.json").read_text())
    require(audit["status"]=="PASSED","Unvalidated exposure")
    capacity=pd.read_csv(DATA/"lcoe_station_capacity.csv")
    capacity["value"]=capacity.capacity_mw/1e6;capacity["model"]="catalogue"
    exposure=pd.read_csv(DATA/"lcoe_station_exposure_decadal_models.csv")
    coverage=pd.read_csv(DATA/"lcoe_station_exposure_coverage.csv")
    results=[draw(capacity,NAMES[0],"Installed capacity","Installed capacity (TW)",True)]
    for name,metric,ylabel,total in [
        (NAMES[1],"Capacity-weighted exposure total","Exposure total (MW days yr⁻¹)",True),
        (NAMES[2],"Capacity-weighted mean exposure","Exposure (days yr⁻¹)",False)]:
        frame=exposure.copy()
        frame["value"]=frame.capacity_event_hours/24/(1 if total else frame.capacity_mw)
        results.append(draw(frame,name,metric,ylabel))
    annual_source=Path("/work/home/acxujo26gv/lcoe_station_climate_storage/loss/paired/source_data")
    assets=ROOT/"document/assets/lcoe_station_metrics"
    for stem,metric,ylabel in ANNUAL_METRICS:
        name="lcoe_"+stem
        for suffix in ("models","display","fits"):
            dest=DATA/(name+"_"+suffix+".csv")
            if not dest.exists():
                dest.write_bytes((annual_source/(stem+"_"+suffix+".csv")).read_bytes())
        frame=pd.read_csv(DATA/(name+"_models.csv"))
        display=pd.read_csv(DATA/(name+"_display.csv"))
        fits=pd.read_csv(DATA/(name+"_fits.csv"))
        results.append(draw(frame,name,metric,ylabel,annual=True,display=display,fits=fits,
                            output=assets/(stem+".png")))
    update_documents(coverage,audit["minimum_time_coverage"])
    md=ROOT/"document/风电光伏数据.md"
    text=md.read_text().replace("图片来源：","原始评价数据来源：",1).replace("完整组图副本保存在本文的","按独立Y轴范围重绘的完整组图保存在本文的",1)
    heading="## 基于 LCOE 选址的损失与发电量"
    note="各子图采用独立Y轴上下限，统一5个刻度间隔（6个刻度值），分别显示数值标签。"
    if heading+"\n\n"+note not in text:
        text=text.replace(heading+"\n",heading+"\n\n"+note+"\n",1)
    md.write_text(text)
    html=ROOT/"document/风电光伏数据.html"
    text=html.read_text().replace("图片来源：","原始评价数据来源：",1).replace("完整组图副本保存在本文的","按独立Y轴范围重绘的完整组图保存在本文的",1)
    # Match existing figures by their captions, preserving all other document images.
    for stem,_,_ in ANNUAL_METRICS:
        captions={
            "station_total_loss":"总净损失",
            "station_unit_loss":"单位装机净损失",
            "station_loss_fraction":"年净损失占全年正常基准电量比例",
            "station_total_generation":"总发电量",
            "station_unit_generation":"单位装机发电量"}
        pattern=r'<figure>\s*<img[^>]+>\s*<figcaption>LCOE 全球场站：'+captions[stem]+r'.*?</figcaption>\s*</figure>'
        matches=list(re.finditer(pattern,text,re.S))
        require(len(matches)==1,"Loss figure caption match: "+stem)
        match=matches[0]
        encoded=base64.b64encode((assets/(stem+".png")).read_bytes()).decode()
        figure=re.sub(r'src="[^"]+"',lambda _: 'src="data:image/png;base64,'+encoded+'"',match.group(),count=1)
        text=text[:match.start()]+figure+text[match.end():]
    heading_html="<h2>基于 LCOE 选址的损失与发电量</h2>"
    if heading_html+"\n<p>"+note+"</p>" not in text:
        text=text.replace(heading_html,heading_html+"\n<p>"+note+"</p>",1)
    html.write_text(text)
    manifest=dict(status="PASSED",question="How do LCOE capacity, exposure, losses and generation vary across paired pathways?",
                  archetype="quantitative grid",backend="Python/matplotlib",figures=results,
                  statistics="Exposure: four-GCM mean after decade mean. Annual loss/generation: existing four-GCM means and 2030–2059 OLS fits. Capacity: deterministic.",
                  exposure_validation_sha256=sha(OUT/"lcoe_exposure_validation.json"))
    (OUT/"lcoe_figure_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("Rendered eight independent-axis triptychs and updated Markdown/HTML",flush=True)


if __name__=="__main__":
    main()
