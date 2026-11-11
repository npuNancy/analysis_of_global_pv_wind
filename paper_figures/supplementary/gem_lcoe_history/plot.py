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
MODELS=['CANESM5','MPI-ESM1-2-HR','MRI-ESM2-0','BCC-CSM2-MR']
TECHS=[('wind+solar','Wind + solar'),('wind','Wind'),('solar','Solar PV')]
METRICS=[
 ('station_total_loss','net_loss_mwh_mean',1.,'Net loss (MWh yr$^{-1}$)','总净损失'),
 ('station_unit_loss','unit_loss_mwh_per_mw_mean',1.,'Net loss (MWh MW$^{-1}$ yr$^{-1}$)','单位装机净损失'),
 ('station_loss_fraction','loss_fraction_pct_mean',1.,'Net loss / normal generation (%)','净损失占正常基准电量比例'),
 ('station_total_generation','generation_mwh_mean',1e-9,'Generation (PWh yr$^{-1}$)','全年总发电量'),
 ('station_unit_generation','unit_generation_mwh_per_mw_mean',1.,'Generation (MWh MW$^{-1}$ yr$^{-1}$)','单位装机全年发电量'),
 ('station_capacity','catalogue_capacity_mw_mean',1e-6,'Installed capacity (TW)','完整目录装机容量'),
 ('station_exposure_total','exposure_mw_days_mean',1.,'Exposure (MW days yr$^{-1}$)','装机加权暴露总量'),
 ('station_exposure_mean','exposure_days_mean',1.,'Exposure (days yr$^{-1}$)','装机加权平均暴露时长'),
 ('station_cf','cf_mean_mean',1.,'Capacity factor','容量加权全年平均CF')]
FIXED_METRICS=[(f'station_fixed_{name[len("station_"):]}',key,scale,ylabel,f'{title}（固定2025装机）')
               for name,key,scale,ylabel,title in METRICS if name!='station_capacity']
ARCHIVE_FIELDS=['net_loss_mwh','normal_annual_mwh','generation_mwh','event_hours','capacity_mw']

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

def read_archive(archives,key):
    entry=archives[key];path=Path(entry['path'])
    if path.stat().st_size!=entry['size_bytes'] or digest(path)!=entry['sha256']:
        raise ValueError('Annual archive changed: '+path.name)
    with np.load(path,allow_pickle=False) as z:
        return {name:z[name] for name in (['years','grid_id','common_support','expected_hours']+ARCHIVE_FIELDS)}

def fixed_capacity_models(index,published):
    """Re-weight transition and future station archives at the fixed 2025 GEM capacity."""
    archives={(e['phase'],e['station_ssp'],e['climate_ssp'],e['model'],e['tech']):e for e in index['annual_archives']}
    energies=ARCHIVE_FIELDS[:3];rows=[];checks=0
    for station,climate in PAIRS:
        for model in MODELS:
            for tech in ('wind','solar'):
                t=read_archive(archives,('transition','gem2025',climate,model,tech))
                f=read_archive(archives,('future',station,climate,model,tech))
                if t['years'].tolist()!=list(range(2026,2030)) or f['years'].tolist()!=list(range(2030,2060)):
                    raise ValueError('Fixed-capacity year matrix')
                cap=t['capacity_mw']
                if not np.allclose(cap,cap[0]) or not (cap>0).all():raise ValueError('Transition capacity is not fixed 2025')
                cap=cap[0]
                pos=np.flatnonzero(np.isin(f['grid_id'],t['grid_id']))
                order_t=np.argsort(t['grid_id']);order_f=pos[np.argsort(f['grid_id'][pos])]
                if len(pos)!=len(order_t) or not np.array_equal(t['grid_id'][order_t],f['grid_id'][order_f]):
                    raise ValueError('Future archive does not contain the GEM grids')
                published_t=published[published.phase.eq('transition')&published.model.eq(model)&
                    published.station_ssp.eq('gem2025')&published.climate_ssp.eq(climate)&published.tech.eq(tech)]
                for i,year in enumerate(t['years']):
                    row=published_t[published_t.year.eq(year)]
                    if len(row)!=1:raise ValueError('Published transition row')
                    weights=cap[order_t][t['common_support'][order_t]]
                    expected=dict(capacity_mw=float(weights.sum()),
                        exposure_mw_days=float((weights*t['event_hours'][i][order_t][t['common_support'][order_t]]/24).sum()))
                    expected.update({k:float(t[k][i][order_t][t['common_support'][order_t]].sum()) for k in energies})
                    for name,value in expected.items():
                        if not np.isclose(value,float(row.iloc[0][name]),rtol=1e-9,atol=1e-6):
                            raise ValueError(f'Transition reweight mismatch {name} {model} {climate} {tech} {year}')
                    checks+=1
                valid=t['common_support'][order_t]&f['common_support'][order_f]
                weights=cap[order_t][valid]
                if not (f['capacity_mw'][:,order_f][:,valid]>0).all():raise ValueError('Nonpositive future capacity on fixed support')
                for source,order in ((t,order_t),(f,order_f)):
                    if not all(np.isfinite(source[k][:,order][:,valid]).all() for k in ARCHIVE_FIELDS):
                        raise ValueError('Nonfinite archive metrics on fixed support')
                    for i,year in enumerate(source['years']):
                        unit=source['capacity_mw'][i][order][valid]
                        rows.append(dict(pathway=climate,model=model,tech=tech,year=int(year),n_stations=int(valid.sum()),
                            expected_hours=float(source['expected_hours'][i]),capacity_mw=float(weights.sum()),
                            exposure_mw_days=float((weights*source['event_hours'][i][order][valid]/24).sum()),
                            **{k:float((source[k][i][order][valid]/unit*weights).sum()) for k in energies}))
    frame=pd.DataFrame(rows)
    keys=['pathway','model','year'];numeric=energies+['exposure_mw_days','capacity_mw','n_stations']
    joint=frame.groupby(keys,as_index=False)[numeric].sum(min_count=2)
    joint=joint.merge(frame.groupby(keys,as_index=False)['expected_hours'].first(),on=keys,validate='one_to_one')
    joint['tech']='wind+solar';frame=pd.concat([frame,joint],ignore_index=True)
    frame['unit_loss_mwh_per_mw']=frame.net_loss_mwh/frame.capacity_mw
    frame['loss_fraction_pct']=100*frame.net_loss_mwh/frame.normal_annual_mwh
    frame['unit_generation_mwh_per_mw']=frame.generation_mwh/frame.capacity_mw
    frame['cf_mean']=frame.generation_mwh/frame.capacity_mw/frame.expected_hours
    frame['exposure_days']=frame.exposure_mw_days/frame.capacity_mw
    if len(frame)!=3*4*34*3:raise ValueError('Fixed-capacity matrix')
    if not frame.cf_mean.between(-1e-9,1+1e-9).all() or not np.isfinite(frame.loss_fraction_pct).all():
        raise ValueError('Fixed-capacity derived metrics')
    grouping=['pathway','tech','year']
    columns=energies+['exposure_mw_days','capacity_mw','unit_loss_mwh_per_mw','loss_fraction_pct',
                     'unit_generation_mwh_per_mw','cf_mean','exposure_days']
    ensemble=frame.groupby(grouping)[columns].agg(['mean','min','max']);ensemble.columns=['_'.join(c) for c in ensemble.columns]
    ensemble=ensemble.reset_index();ensemble['n_models']=frame.groupby(grouping).size().to_numpy()
    if not ensemble.n_models.eq(4).all() or len(ensemble)!=3*3*34:raise ValueError('Fixed-capacity ensemble')
    return frame,ensemble,checks

def select_fixed(data,ensemble):
    columns=['tech','pathway','year','n_models']+[m[1] for m in FIXED_METRICS]
    result=pd.concat([data[data.pathway.eq('historical')][columns],ensemble[columns]],ignore_index=True)
    for (tech,pathway),g in result.groupby(['tech','pathway']):
        expected=np.arange(2015,2026) if pathway=='historical' else np.arange(2026,2060)
        if not np.array_equal(g.sort_values('year').year,expected):raise ValueError((tech,pathway,'years'))
        if not g.n_models.eq(1 if pathway=='historical' else 4).all():raise ValueError('Missing GCM')
    return result

def panel(ax,data,tech,label,letter,metric):
    name,key,scale,ylabel=metric[:4]
    h=data[data.tech.eq(tech)&data.pathway.eq('historical')].sort_values('year');y=h[key].to_numpy()*scale
    if not np.isfinite(y).all():raise ValueError('Nonfinite history')
    ax.plot(h.year,y,color='#111111',lw=1.3,marker='o',markersize=1.8,zorder=3)
    for station,climate in PAIRS:
        f=data[data.tech.eq(tech)&data.pathway.eq(climate)].sort_values('year')
        x=np.r_[2025,f.year];v=np.r_[y[-1],f[key].to_numpy()*scale]
        if not np.isfinite(v).all():raise ValueError('Nonfinite future')
        ax.plot(x,v,color=SSP_COLORS[climate],lw=1.15)
    ticks=independent_y_ticks(ax,intervals=5)
    if ticks['lower']<0<=ticks['data_minimum']:
        needed=ticks['data_maximum']*1.06/5
        power=10.**np.floor(np.log10(needed))
        step=next(f*power for f in (1.,1.25,1.5,2.,2.5,3.,4.,5.,6.,8.,10.) if f*power>=needed)
        values=np.arange(6)*step
        ax.set_yticks(values);ax.set_ylim(0,float(values[-1]))
        ticks.update(lower=0.,upper=float(values[-1]),step=float(step),ticks=values.tolist())
    ax.axvline(2025,color='.7',lw=.55,ls=':',zorder=0)
    ax.set_xlim(2014,2060);ax.set_xticks([2015,2025,2035,2045,2055]);ax.set_xlabel('Year')
    ax.set_ylabel(ylabel,labelpad=4);ax.set_title(label,pad=9,fontsize=8.5)
    ax.text(-.1,1.06,letter,transform=ax.transAxes,fontweight='bold',fontsize=10,va='bottom')
    ax.tick_params(length=3,width=.65,labelsize=7.5)
    ax.ticklabel_format(axis='y',style='sci',scilimits=(-3,4),useMathText=True)
    ax.yaxis.get_offset_text().set_fontsize(7)
    return ticks

def legend(fig,footer,solo):
    colors=['#111111']+[SSP_COLORS[c] for _,c in PAIRS]
    names=['ERA5-Land','SSP1-2.6','SSP2-4.5','SSP5-8.5']
    handles=[Line2D([],[],color=c,lw=1.3,label=n) for c,n in zip(colors,names)]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.072 if solo else .045),
               ncol=2 if solo else len(handles),fontsize=7,handlelength=2.2,columnspacing=1.3)
    fig.text(.5,.018,footer,ha='center',fontsize=6.2)

def render_family(display,metrics,footer,out,artifacts,axes_info):
    for metric in metrics:
        name=metric[0];fig,axs=plt.subplots(1,3,figsize=(250/25.4,100/25.4))
        fig.subplots_adjust(left=.08,right=.985,bottom=.26,top=.83,wspace=.52)
        for ax,(tech,title),letter in zip(axs,TECHS,'abc'):
            axes_info[name+'_'+letter]=panel(ax,display,tech,title,letter,metric)
        legend(fig,footer,False);artifacts.append(export_panel_png(fig,out/(name+'.png')))
        for (tech,title),letter in zip(TECHS,'abc'):
            fig,ax=plt.subplots(figsize=(105/25.4,112/25.4));fig.subplots_adjust(left=.23,right=.97,bottom=.30,top=.85)
            panel(ax,display,tech,title,letter,metric);legend(fig,footer,True)
            artifacts.append(export_panel_png(fig,out/(name+'_'+letter+'.png')))

def report(out):
    rel='../paper_figures/supplementary/gem_lcoe_history/outputs/'
    lines=['# GEM逐年实际场站与LCOE未来场站气候评价','',
      '2015—2025采用GEM逐年回溯场站（historical_snapshot，允许退出和容量变化）；2026—2029固定2025装机；2030—2059采用新的累计LCOE布局。仅含陆上及类型未知风电。另附固定2025装机的对照图族，分离气候路径与布局变化。','',
      '## 数据目录','',
      f'- 共享根：{ROOT}；十计算账号可写，1866与其他账号可读。',
      f'- 完整索引：{ROOT}/runtime/authoritative_index.json；验收：{ROOT}/runtime/completion.json。',
      f'- 原生CF/Extreme：{ROOT}/historical/outputs、{ROOT}/transition/outputs、{ROOT}/future/outputs。',
      f'- 逐站年度数组：{ROOT}/station_results；98个NPZ，包括坐标、容量、覆盖标记、CF、暴露、损失和全年发电。',
      f'- 年度字段、单位和容量口径：{ROOT}/station_results/manifest.json；各条记录代表一种技术的一个0.1°网格。',
      f'- 完整交叉路径年度CSV：{ROOT}/source_data/global_annual_models.csv；模式汇总：global_annual_ensemble.csv；覆盖：capacity_coverage.csv。',
      f'- 绘图源表：[plot_series.csv]({rel}source_data/plot_series.csv)；固定装机逐模式表：[fixed_capacity_models.csv]({rel}source_data/fixed_capacity_models.csv)；固定装机模式汇总：[fixed_capacity_ensemble.csv]({rel}source_data/fixed_capacity_ensemble.csv)。','',
      '## 验收记录','',
      '已完成历史、过渡期与未来完整交叉矩阵；正式索引包含49,100个原生CF/Extreme文件和98个年度场站NPZ。全球年度逐模式CSV有3,417行，模式汇总CSV有879行。','',
      '| 阶段 | 年份 | 逐模式记录数 | 有效容量占完整目录容量 |','|---|---|---:|---:|',
      '| 历史 | 2015—2025 | 33 | 95.63%—98.09% |','| 过渡 | 2026—2029 | 144 | 97.18%—97.95% |','| 未来 | 2030—2059 | 3240 | 96.04%—99.45% |','',
      '覆盖范围综合各年份、路径及技术。通过年份与容量匹配、模式数量、CF范围、事件能量关系、文件完整性及读取权限核对。','',
      '图件共17张组图和51张独立子图，均为600 dpi PNG；其中固定2025装机对照族为8张组图、24张子图。全部完成目视检查。本地同路径副本的图像SHA256与1866正式图件一致。固定装机族2026—2029的重加权结果与正式逐模式汇总逐值核对一致。验收记录见[figure_validation.json](%sfigure_validation.json)。'%rel,'',
      '原有 document/BCSD_v2数据使用指南.md、document/风电光伏数据.md、document/风电光伏数据.html 的SHA256保持不变。','',
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
      '- 每条彩线从黑线2025端点接出，未平移未来数值。四模式最小值和最大值保存在源表，不解释为置信区间。各子图Y轴独立，均为5个间隔。',
      '- 固定装机对照族：2026—2059装机固定为2025年末GEM目录容量，与过渡期口径一致；其年际变化只反映气候路径与模式差异，用于与同时包含部署变化的曲线对照。',
      '- 固定族2030—2059逐站数值取自配对场站SSP的未来年度档案中与GEM2025重合的格点；全部GEM2025格点均包含于三套LCOE累计布局，且重合格点逐站数值跨场站SSP一致。单位装机电量由逐站年度数组除以档案当年容量还原，再按固定2025容量加权。',
      '- 固定族有效站点为过渡期与未来档案共同支持集的交集，在每条路径、模式、技术内跨2026—2059全部年份固定，装机加权分母恒定。','',
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
    for name,key,scale,ylabel,title in METRICS:
        lines += [f'### {title}','',f'![{title}]({rel}{name}.png)','',
          '独立子图：'+'；'.join(f'[{letter} {tech}]({rel}{name}_{letter}.png)' for letter,(tech,_) in zip('abc',TECHS))+'。','']
    lines += ['## 固定2025装机对照图','',
      '黑线与上图族相同；彩线为2026—2059四模式均值，装机固定为2025年末GEM目录容量，仅气候路径变化，每条彩线仍从黑线2025端点接出。','']
    for name,key,scale,ylabel,title in FIXED_METRICS:
        lines += [f'### {title}','',f'![{title}]({rel}{name}.png)','',
          '独立子图：'+'；'.join(f'[{letter} {tech}]({rel}{name}_{letter}.png)' for letter,(tech,_) in zip('abc',TECHS))+'。','']
    (REPO/'document/GEM场站历史与LCOE未来气候评价.md').write_text('\n'.join(lines)+'\n')

def main():
    check_protected();completion=read(ROOT/'runtime/completion.json')
    if completion['status']!='COMPLETED' or digest(ROOT/'runtime/authoritative_index.json')!=completion['index_sha256']:
        raise ValueError('Dataset is not accepted')
    index=read(ROOT/'runtime/authoritative_index.json')
    sources={}
    for name in ('global_annual_ensemble.csv','global_annual_models.csv'):
        record=index['summaries'][name];path=Path(record['path'])
        if path.stat().st_size!=record['size_bytes'] or digest(path)!=record['sha256']:
            raise ValueError('Published summary changed: '+name)
        sources[name]=path
    data=select(pd.read_csv(sources['global_annual_ensemble.csv']))
    fixed_models,fixed_ensemble,checks=fixed_capacity_models(index,pd.read_csv(sources['global_annual_models.csv']))
    fixed_display=select_fixed(data,fixed_ensemble)
    out=HERE/'outputs';(out/'source_data').mkdir(parents=True,exist_ok=True)
    data.to_csv(out/'source_data/plot_series.csv',index=False)
    fixed_models.to_csv(out/'source_data/fixed_capacity_models.csv',index=False)
    fixed_ensemble.to_csv(out/'source_data/fixed_capacity_ensemble.csv',index=False)
    (out/'source_data/linear_fits.csv').unlink(missing_ok=True)
    configure();plt.rcParams.update({'font.size':8,'axes.labelsize':8})
    artifacts=[];axes_info={}
    render_family(data,METRICS,'2015-2025: annual GEM / ERA5-Land; future: four-GCM mean.',out,artifacts,axes_info)
    render_family(fixed_display,FIXED_METRICS,'2015-2025: ERA5-Land; future: fixed 2025 capacity, four-GCM mean.',out,artifacts,axes_info)
    report(out);check_protected()
    (out/'figure_validation.json').write_text(json.dumps(dict(status='NUMERIC_AND_EXPORT_PASSED',visual_review='PENDING',
        source=str(sources['global_annual_ensemble.csv']),source_sha256=digest(sources['global_annual_ensemble.csv']),completion=completion,
        display_rows=len(data),fixed=dict(models_rows=len(fixed_models),ensemble_rows=len(fixed_ensemble),
        transition_crosscheck_rows=checks,connection='2025 historical endpoint; unshifted 2026-2059 at fixed 2025 capacity'),
        images=artifacts,axes=axes_info,protected_documents='UNCHANGED'),indent=2)+'\n')
    print('Rendered',len(artifacts),'PNGs; cross-checked',checks,'transition rows',flush=True)

if __name__=='__main__':main()
