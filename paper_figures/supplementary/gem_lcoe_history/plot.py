"""Plot annual GEM history and paired LCOE future trajectories from accepted summaries."""
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from paper_figures.common.plotting import configure,export_panel_png,independent_y_ticks
from paper_figures.config import SSP_COLORS

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
ROOT=Path('/work/home/acxujo26gv/lcoe_gem2025_climate_storage')
PAIRS=[('ssp126','ssp126'),('ssp245','ssp245'),('ssp560','ssp585')]
TECHS=[('wind+solar','Wind + solar'),('wind','Wind'),('solar','Solar PV')]
METRICS=[
 ('station_total_loss','net_loss_mwh_mean',1.,'Net loss (MWh yr$^{-1}$)','总净损失',True),
 ('station_unit_loss','unit_loss_mwh_per_mw_mean',1.,'Net loss (MWh MW$^{-1}$ yr$^{-1}$)','单位装机净损失',True),
 ('station_loss_fraction','loss_fraction_pct_mean',1.,'Net loss / normal generation (%)','净损失占正常基准电量比例',True),
 ('station_total_generation','generation_mwh_mean',1e-9,'Generation (PWh yr$^{-1}$)','全年总发电量',True),
 ('station_unit_generation','unit_generation_mwh_per_mw_mean',1.,'Generation (MWh MW$^{-1}$ yr$^{-1}$)','单位装机全年发电量',True),
 ('station_capacity','catalogue_capacity_mw_mean',1e-6,'Installed capacity (TW)','完整目录装机容量',False),
 ('station_exposure_total','exposure_mw_days_mean',1.,'Exposure (MW days yr$^{-1}$)','装机加权暴露总量',False),
 ('station_exposure_mean','exposure_days_mean',1.,'Exposure (days yr$^{-1}$)','装机加权平均暴露时长',False),
 ('station_cf','cf_mean_mean',1.,'Capacity factor','容量加权全年平均CF',False)]

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def check_protected():
    for name,expected in read(HERE/'protected_document_hashes.json').items():
        if digest(REPO/name)!=expected:raise ValueError('Protected document changed: '+name)

def select(frame):
    rows=[];h=frame[frame.phase.eq('historical')].copy();h['pathway']='historical';rows.append(h)
    for station,climate in PAIRS:
        f=frame[(frame.phase.eq('future')&frame.station_ssp.eq(station)&frame.climate_ssp.eq(climate)) |
                (frame.phase.eq('transition')&frame.climate_ssp.eq(climate))].copy()
        f['pathway']=climate;rows.append(f)
    result=pd.concat(rows,ignore_index=True)
    if len(result)!=339:raise ValueError('Incomplete display matrix')
    for (tech,pathway),g in result.groupby(['tech','pathway']):
        expected=np.arange(2015,2026) if pathway=='historical' else np.arange(2026,2060)
        if not np.array_equal(g.sort_values('year').year,expected):raise ValueError((tech,pathway,'years'))
        if not g.n_models.eq(1 if pathway=='historical' else 4).all():raise ValueError('Missing GCM')
    return result

def panel(ax,data,tech,label,letter,metric):
    name,key,scale,ylabel,title,fit=metric
    h=data[data.tech.eq(tech)&data.pathway.eq('historical')].sort_values('year');y=h[key].to_numpy()*scale
    if not np.isfinite(y).all():raise ValueError('Nonfinite history')
    ax.plot(h.year,y,color='#111111',lw=1.3,marker='o',markersize=1.8,zorder=3)
    fits=[]
    for station,climate in PAIRS:
        f=data[data.tech.eq(tech)&data.pathway.eq(climate)].sort_values('year')
        x=np.r_[2025,f.year];v=np.r_[y[-1],f[key].to_numpy()*scale]
        if not np.isfinite(v).all():raise ValueError('Nonfinite future')
        ax.plot(x,v,color=SSP_COLORS[climate],lw=1.15)
        if fit:
            selected=f.year.ge(2030);xx=f.loc[selected,'year'].to_numpy();yy=f.loc[selected,key].to_numpy()*scale
            slope,intercept=np.polyfit(xx-2030,yy,1)
            ax.plot(xx,intercept+slope*(xx-2030),color=SSP_COLORS[climate],lw=.8,ls='--')
            fits.append(dict(metric=name,tech=tech,climate_ssp=climate,station_ssp=station,start=2030,end=2059,
                             slope_per_year=float(slope),intercept_at_2030=float(intercept)))
    ticks=independent_y_ticks(ax,intervals=5)
    ax.axvline(2025,color='.7',lw=.55,ls=':',zorder=0)
    ax.set_xlim(2014,2060);ax.set_xticks([2015,2025,2035,2045,2055]);ax.set_xlabel('Year')
    ax.set_ylabel(ylabel,labelpad=4);ax.set_title(label,pad=9,fontsize=8.5)
    ax.text(-.1,1.06,letter,transform=ax.transAxes,fontweight='bold',fontsize=10,va='bottom')
    ax.tick_params(length=3,width=.65,labelsize=7.5)
    ax.ticklabel_format(axis='y',style='sci',scilimits=(-3,4),useMathText=True)
    ax.yaxis.get_offset_text().set_fontsize(7)
    return ticks,fits

def legend(fig,fit,solo):
    colors=['#111111']+[SSP_COLORS[c] for _,c in PAIRS]
    names=['ERA5-Land','SSP1-2.6','SSP2-4.5','SSP5-8.5']
    handles=[Line2D([],[],color=c,lw=1.3,label=n) for c,n in zip(colors,names)]
    if fit:handles.append(Line2D([],[],color='.4',ls='--',lw=.8,label='2030-2059 fit'))
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.072 if solo else .045),
               ncol=2 if solo else len(handles),fontsize=7,handlelength=2.2,columnspacing=1.3)
    fig.text(.5,.018,'2015-2025: annual GEM / ERA5-Land; future: four-GCM mean.',ha='center',fontsize=6.2)

def report(out):
    rel='../paper_figures/supplementary/gem_lcoe_history/outputs/'
    lines=['# GEM逐年实际场站与LCOE未来场站气候评价','',
      '2015—2025采用GEM逐年回溯场站（historical_snapshot，允许退出和容量变化）；2026—2029固定2025装机；2030—2059采用新的累计LCOE布局。仅含陆上及类型未知风电。','',
      '## 数据目录','',f'- 共享根：{ROOT}；十计算账号可写，1866与其他账号可读。',
      f'- 完整索引：{ROOT}/runtime/authoritative_index.json；验收：{ROOT}/runtime/completion.json。',
      f'- 原生CF/Extreme：{ROOT}/historical/outputs、{ROOT}/transition/outputs、{ROOT}/future/outputs。',
      f'- 逐站年度数组：{ROOT}/station_results；98个NPZ，包括坐标、容量、覆盖标记、CF、暴露、损失和全年发电。',
      f'- 年度字段、单位和容量口径：{ROOT}/station_results/manifest.json；各条记录代表一种技术的一个0.1°网格。',
      f'- 完整交叉路径年度CSV：{ROOT}/source_data/global_annual_models.csv；模式汇总：global_annual_ensemble.csv；覆盖：capacity_coverage.csv。',
      f'- 绘图源表：[plot_series.csv]({rel}source_data/plot_series.csv)；拟合：[linear_fits.csv]({rel}source_data/linear_fits.csv)。','',
      '## 计算与展示口径','',
      '- 使用纠正后的0.1°网格编号按同一格匹配ERA5/BCSD源点，不跨格补点。场站网格中心与实际取样点坐标分别保存；原生CF/Extreme不套用投运掩膜，年度指标显式使用当年容量。',
      '- 历史使用ERA5-Land逐小时数据；BCSD保留模式原生三小时日历。光伏装机为MWp/DC，风电为MW；风电能量不乘0.1。全年发电量由全年CF积分。',
      '- 历史每年以当年年末装机容量固定用于全年计算，未按年内投运月份折算；发电量是气候驱动的模型估算，不是实测发电统计。',
      '- 未来布局的原生CF/Extreme按原产品范围保留2015—2060；其年度评价采用2030—2059。历史年度评价另用ERA5及逐年实际装机。',
      '- 历史Loss沿用南北分析的固定全历史期、按月和小时且排除事件并集的正常CF基线方法，本轮窗口为2015—2025。过渡期窗口为2026—2029（中心2027）；未来分别为2030—2039、2040—2049、2050—2059。低资源事件基准期另为2015—2024。',
      '- 历史累计辐射、降水按ERA5-Land重置规则差分为小时量；按valid_time归年。Loss分别用12×24与12×8月—小时基线。历史末尾低资源居中窗口不足的时间保持缺测。',
      '- 损失为事件并集下的带符号净损失；单位装机量先汇总能量再除相同有效集合的容量。净损失比例的分母为全年正常基准电量；暴露不重复累加重叠事件。',
      '- 各阶段、路径、技术内使用跨年份及四模式共同有效站点；缺测不作零。总装机图显示完整目录容量，其余图显示有效集合指标，容量覆盖单独保留。阶段间有效支持可能不同。',
      '- 黑线为2015—2025；彩线为2026—2059四模式均值。场站/气候配对为126/126、245/245、560/585，完整三乘三交叉数据均保存。曲线差同时包含气候与部署变化。',
      '- 每条彩线从黑线2025端点接出，未平移未来数值。虚线仅拟合2030—2059。四模式最小值和最大值保存在源表，不解释为置信区间。各子图Y轴独立，均为5个间隔。','',
      '## 读取年度场站结果','',
      '```python','import json','from pathlib import Path','import numpy as np',
      f'root = Path({str(ROOT)!r})',
      'index = json.loads((root / "runtime/authoritative_index.json").read_text())',
      'entry = next(e for e in index["annual_archives"]',
      '             if e["phase"] == "future" and e["station_ssp"] == "ssp560"',
      '             and e["climate_ssp"] == "ssp245" and e["model"] == "CANESM5" and e["tech"] == "wind")',
      'with np.load(entry["path"], allow_pickle=False) as z:',
      '    i = int(np.flatnonzero(z["years"] == 2050)[0])',
      '    capacity = z["capacity_mw"][i]',
      '    loss = z["net_loss_mwh"][i]',
      '    valid = z["common_support"] & (capacity > 0) & np.isfinite(loss)',
      '    unit_loss = loss[valid].sum() / capacity[valid].sum()  # MWh/MW/year',
      '```','',
      '原生NetCDF通过同一索引的entries筛选phase、product、model、climate_scenario、station_scenario和tech，再读取artifacts中的path；空组合标记EMPTY_NO_STATIONS。','',
      '## 图件','']
    for name,key,scale,ylabel,title,fit in METRICS:
        lines += [f'### {title}','',f'![{title}]({rel}{name}.png)','',
          '独立子图：'+'；'.join(f'[{letter} {tech}]({rel}{name}_{letter}.png)' for letter,(tech,_) in zip('abc',TECHS))+'。','']
    (REPO/'document/GEM场站历史与LCOE未来气候评价.md').write_text('\n'.join(lines)+'\n')

def main():
    check_protected();completion=read(ROOT/'runtime/completion.json')
    if completion['status']!='COMPLETED' or digest(ROOT/'runtime/authoritative_index.json')!=completion['index_sha256']:
        raise ValueError('Dataset is not accepted')
    index=read(ROOT/'runtime/authoritative_index.json')
    record=index['summaries']['global_annual_ensemble.csv'];source=Path(record['path'])
    if source.stat().st_size!=record['size_bytes'] or digest(source)!=record['sha256']:
        raise ValueError('Published summary changed')
    data=select(pd.read_csv(source))
    out=HERE/'outputs';(out/'source_data').mkdir(parents=True,exist_ok=True)
    data.to_csv(out/'source_data/plot_series.csv',index=False)
    configure();plt.rcParams.update({'font.size':8,'axes.labelsize':8})
    artifacts=[];axes_info={};fits=[]
    for metric in METRICS:
        name=metric[0];fig,axs=plt.subplots(1,3,figsize=(250/25.4,100/25.4))
        fig.subplots_adjust(left=.08,right=.985,bottom=.26,top=.83,wspace=.52)
        for ax,(tech,title),letter in zip(axs,TECHS,'abc'):
            ticks,rows=panel(ax,data,tech,title,letter,metric);axes_info[name+'_'+letter]=ticks;fits.extend(rows)
        legend(fig,metric[-1],False);artifacts.append(export_panel_png(fig,out/(name+'.png')))
        for (tech,title),letter in zip(TECHS,'abc'):
            fig,ax=plt.subplots(figsize=(105/25.4,112/25.4));fig.subplots_adjust(left=.23,right=.97,bottom=.30,top=.85)
            panel(ax,data,tech,title,letter,metric);legend(fig,metric[-1],True)
            artifacts.append(export_panel_png(fig,out/(name+'_'+letter+'.png')))
    pd.DataFrame(fits).to_csv(out/'source_data/linear_fits.csv',index=False)
    report(out);check_protected()
    (out/'figure_validation.json').write_text(json.dumps(dict(status='NUMERIC_AND_EXPORT_PASSED',visual_review='PENDING',
        source=str(source),source_sha256=digest(source),completion=completion,display_rows=len(data),images=artifacts,
        axes=axes_info,protected_documents='UNCHANGED',connection='2025 historical endpoint; unshifted 2026-2059'),indent=2)+'\n')
    print('Rendered',len(artifacts),'PNGs',flush=True)

if __name__=='__main__':main()
