"""Build a Chinese evidence report from the completed SSP grid analysis."""
import json
from pathlib import Path
import pandas as pd
from paper_figures.config import ROOT
from paper_figures.common.io import write_json, digest

OUT = ROOT / "paper_figures/main/fig01_extreme_events/outputs/ssp_grid"
LABELS = {"wind": "风电事件集合", "solar": "光伏事件集合", "all": "全部事件（时间并集）",
    "high_temp": "高温", "high_wind": "强风", "hot_humid": "湿热", "icing": "覆冰",
    "low_resource": "低资源", "cold_highwind": "低温强风", "freezing_rain": "冻雨",
    "high_humidity": "高湿", "rainstorm": "暴雨", "overlap_correction": "重叠修正"}
CASES = ["CHN", "USA", "IND", "BRA", "AUS", "RUS", "CAN", "SAU", "DEU", "ZAF"]

def table(frame):
    frame = frame.copy()
    for col in ("tech", "event", "largest_increasing_event", "largest_decreasing_event"):
        if col in frame:
            frame[col] = frame[col].map(LABELS).fillna(frame[col])
    return frame.to_html(index=False, border=0, float_format=lambda x: f"{x:.3f}", na_rep="—")

def main():
    audit = json.loads((OUT / "audit.json").read_text())
    if audit["status"] != "PASSED" or audit["pilot"]:
        raise ValueError("A passed full analysis is required")
    levels = pd.read_csv(OUT / "levels.csv")
    diffs = pd.read_csv(OUT / "contrasts.csv")
    drivers = pd.read_csv(OUT / "regional_explanations.csv")
    spatial = pd.read_csv(OUT / "native_spatial_fractions.csv")
    rank = pd.read_csv(OUT / "native_ssp_ordering.csv")
    coverage = pd.read_csv(OUT / "coverage.csv").groupby("tech", as_index=False)[["n_cells", "area_km2"]].sum()
    global_levels = levels.query("scope == 'global' and snapshot == 2050").pivot(
        index=["tech", "event"], columns="climate_ssp", values="mean").reset_index()
    global_diffs = diffs.query("scope == 'global' and snapshot == 2050")[
        ["tech", "event", "high", "low", "mean", "minimum", "maximum", "positive_models", "negative_models"]]
    main_diffs = global_diffs.query("high == 'ssp585' and low == 'ssp126'")
    c = diffs.query("scope == 'latitude' and snapshot == 2050 and high == 'ssp585' and low == 'ssp126'")
    latitude = c.pivot(index=["tech", "region"], columns="event", values="mean").reset_index()
    cases = drivers.query("scope == 'country' and snapshot == 2050 and high == 'ssp585' and low == 'ssp126'")
    selected = cases[cases.region.isin(CASES)]
    cols = ["tech", "region_name", "union_difference", "union_minimum", "union_maximum",
        "positive_models", "negative_models", "largest_increasing_event", "largest_increase",
        "largest_decreasing_event", "largest_decrease", "overlap_correction_difference"]
    sp = spatial.query("snapshot == 2050 and high == 'ssp585' and low == 'ssp126'").pivot(
        index=["tech", "event"], columns="criterion", values="area_fraction").reset_index()
    fractions = sp.select_dtypes("number").columns
    sp[fractions] *= 100
    ordering = rank.query("snapshot == 2050 and event == 'all'").copy()
    ordering["area_percent"] = ordering.area_fraction * 100
    temporal = diffs.query("scope == 'global' and event == 'all'")[
        ["tech", "snapshot", "high", "low", "mean", "minimum", "maximum", "positive_models", "negative_models"]]
    spatial_lookup = sp.set_index(["tech", "event"])
    cases_lookup = cases.set_index(["tech", "region"])
    lat_lookup = latitude.set_index(["tech", "region"])
    ordering_lookup = ordering.set_index(["tech", "ordering"])
    spatial_text = (
        f'<p>风电并集增加的有效面积占{spatial_lookup.loc[("wind", "all"), "mean_positive"]:.1f}%，'
        f'但四模式都增加的面积仅占{spatial_lookup.loc[("wind", "all"), "positive_4of4"]:.1f}%；'
        f'光伏并集减少的面积占{spatial_lookup.loc[("solar", "all"), "mean_negative"]:.1f}%，'
        f'四模式都减少的面积占{spatial_lookup.loc[("solar", "all"), "negative_4of4"]:.1f}%。'
        '全球平均方向与局地一致性应分开解释。</p>')
    latitude_text = (
        f'<p>风电增加最明显的纬度带是0–30°N：并集增加{lat_lookup.loc[("wind", "0-30N"), "all"]:.2f}天/年，'
        f'其中高温标签增加{lat_lookup.loc[("wind", "0-30N"), "high_temp"]:.2f}天/年。'
        f'光伏在60–90°N反而增加{lat_lookup.loc[("solar", "60N-90N"), "all"]:.2f}天/年，'
        '净差为四模式同向；低资源、高湿和覆冰均为增加项。'
        f'南纬0–30°的光伏并集减少{abs(lat_lookup.loc[("solar", "30S-0"), "all"]):.2f}天/年，'
        '主要减少项为高湿。高纬度覆冰增加也说明，不能只用“升温使覆冰减少”解释所有地区，'
        '还需检查温度与湿度的联合越阈概率。</p>')
    case_text = (
        f'<p>区域对照：沙特风电并集增加{cases_lookup.loc[("wind", "SAU"), "union_difference"]:.2f}天/年，'
        f'主要增加项是高温（+{cases_lookup.loc[("wind", "SAU"), "largest_increase"]:.2f}）；'
        f'德国风电并集减少{abs(cases_lookup.loc[("wind", "DEU"), "union_difference"]):.2f}天/年，'
        f'主要减少项是低资源（{cases_lookup.loc[("wind", "DEU"), "largest_decrease"]:.2f}）。'
        '这两个国家的净差均为四模式同向。'
        f'巴西光伏并集减少{abs(cases_lookup.loc[("solar", "BRA"), "union_difference"]):.2f}天/年，'
        '主要来自高湿标签减少，同样四模式同向。中国两种技术的平均净差都接近零，'
        '但存在事件抵消和较大模式分歧，不能解读成SSP没有影响。</p>')
    ordering_text = (
        f'<p>与全球平均排序一致的格点面积，风电SSP126&lt;SSP245&lt;SSP585仅占'
        f'{ordering_lookup.loc[("wind", "ssp126<ssp245<ssp585"), "area_percent"]:.1f}%，'
        f'光伏SSP126&gt;SSP245&gt;SSP585仅占'
        f'{ordering_lookup.loc[("solar", "ssp585<ssp245<ssp126"), "area_percent"]:.1f}%。'
        '因此不能把SSP245预设为各地区都处于另外两路径之间的中间态。</p>')
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>全球网格极端事件：SSP路径对比</title>',
        '<style>body{font:16px/1.7 system-ui,sans-serif;max-width:1400px;margin:40px auto;padding:0 24px;color:#24303d}h1,h2{line-height:1.35}table{border-collapse:collapse;font-size:13px;display:block;overflow:auto;margin:18px 0}th,td{padding:6px 10px;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap}th{background:#f1f4f6}p{max-width:1000px}details{margin:22px 0}.note{background:#eef3f7;padding:15px}a{color:#205b8a}</style>',
        '<h1>全球网格极端事件：SSP路径差异与事件解释</h1>',
        '<p>小凯，本报告将气候SSP作为比较维度。主结果为2050–2059年同一时期的路径对比，2030和2040年代仅用于检查结论稳定性。先逐模式计算，再汇总四模式；不涉及场站布局或装机权重。</p>',
        '<p class="note">所有暴露及差值的单位均为累计天/年：有效事件小时数除以24。不是发生次数、日历天数或气象强度。空间比例以有效原生格点面积为分母。“全球”限于正式产品共同有效域。minimum–maximum是四模式范围，positive_models / negative_models是同向模式数，不是置信区间或显著性。</p>',
        '<h2>1. 各SSP的全球水平：逐事件与并集</h2>', table(global_levels),
        '<p>2050年代，风电并集的全球平均为SSP126 &lt; SSP245 &lt; SSP585；光伏并集为SSP126 &gt; SSP245 &gt; SSP585。这是两套特定事件定义下的暴露排序，不能推论为所有天气灾害或发电损失的排序。</p>',
        '<h2>2. 两端路径差异由哪些事件组成</h2>', table(main_diffs),
        '<p>风电主要表现为高温增加，而低风资源和覆冰减少，部分抵消增加项；光伏主要表现为高湿、冻雨和覆冰减少，低辐射资源增加则起抵消作用。需结合各行的模式范围与同向数区分稳健和不稳定项。</p>',
        '<p>核算关系：并集差异 = 各事件暴露差异之和 + 重叠修正差异。每条路径的重叠修正 = 并集暴露 − 各事件暴露之和。重叠变化单列，避免将重复时间当作新增总暴露；该核算不能唯一分配某事件对并集的独立贡献，也不等同于物理因果归因。</p>',
        '<details><summary>查看全部三组SSP对比</summary>', table(global_diffs), '</details>',
        '<h2>3. 全球均值是否代表多数地区</h2>', spatial_text,
        '<p>下表全部比例为有效面积的百分比。mean_positive / mean_negative指四模式均值的方向；positive_4of4 / negative_4of4要求四模式全部同向；atleast3of4要求至少三模式同向。±1天是额外的幅度描述，不是显著性阈值。</p>', table(sp),
        '<p>下表按每格点的四模式平均暴露，统计三个SSP的完整排序。SSP245不必处在另两条路径之间；tie包括任意相邻值在数值容差内相等。</p>',
        ordering_text, table(ordering[["tech", "ordering", "area_percent"]]),
        '<h2>4. 纬度带：哪里增加、哪里减少</h2>', latitude_text, table(latitude),
        '<p>每列是SSP585−SSP126的对应事件差值；低资源在两种技术中分别指风速与辐射异常。all与各事件之和的区别由overlap_correction闭合。纬度带是有效区域内的面积加权结果，不代表整条纬度带都同向。</p>',
        '<h2>5. 国家尺度的区域解释</h2>', case_text,
        '<p>以下固定展示中国、美国、印度、巴西、澳大利亚、俄罗斯、加拿大、沙特阿拉伯、德国和南非。国家值均来自该国有效网格，不是场站暴露。最大的增加/减少事件只概括标签差异；其余事件与重叠变化也参与净差。完整国家结果在折叠表及CSV中保留。</p>',
        table(selected[cols]),
        '<details><summary>全部可归属国家：2050年代SSP585−SSP126</summary>',
        table(cases[~cases.region.isin(["UNASSIGNED", "AMBIGUOUS"])][cols]), '</details>',
        '<h2>6. SSP差异在其他时期是否保持</h2>', table(temporal),
        '<p>这里仍然比较同一年代内的SSP差异，不把两个年代相减作为主分析。均值方向与四模式范围应一起阅读，不能把未来十年窗口内的情景差全部归因于强迫响应。</p>',
        '<h2>7. “为什么”的证据边界</h2>',
        '<p>已完成的是事件组成与空间抵消的核算。正式事件阈值能够给出待验证的气象解释：风电高温为温度&gt;35°C；湿热还要求相对湿度≥85%；覆冰为温度&lt;−2°C且相对湿度≥85%；光伏高湿为相对湿度≥95%；冻雨标签为温度&lt;3°C且降水率&gt;0.1 mm/h。若温度分布向高值移动，固定高温阈值的越界可增加，而某些低温阈值越界可减少；但相对湿度、降水和风速的联合变化可改变甚至逆转局地结果。这些条件解释并不证明具体地区的物理机制。</p>',
        '<p>低资源事件使用各模式、各SSP自身2015–2024年的资源异常基线及P5阈值。因此当前比较是相对各路径基线的低谷暴露；若要解释绝对资源变化，应另用共同基线或直接比较气象资源。光伏集合没有高温事件，且缺少dust正式输出，所以光伏并集下降不能表述为全部气候风险下降。</p>',
        '<p>进一步验证某个地区的物理原因，需要在相同格点、模式、时期和SSP上检查温度、相对湿度、降水、风速/辐射的分布及联合越阈概率；若要将重叠唯一分配给事件，需要返回三小时联合信号，计算独占时长、组合时长或明确约定的分摊量。本报告不从时期边际汇总反推这些不可识别的信息。</p>',
        '<h2>8. 验证与可追溯数据</h2>', table(coverage),
        f'<p>全量分析作业：{audit["job_id"]}。47分块×2技术，共94份时期缓存。全球结果与已验收表最大差值为{audit["reference_max_error_days"]:.3g}天/年。检查通过：格点唯一性、事件并集上下界、各事件与重叠核算闭合、国家/纬度带与全球守恒、SSP共同支持、四模式完整性和排序分区。float32缓存的并集边界允许1e−4天舍入误差。</p>',
        '<p>源文件SHA-256与完整口径见<a href="audit.json">audit.json</a>；24个模式×SSP×技术代表文件的阈值及各路径基线属性见<a href="event_definitions.json">event_definitions.json</a>。</p>',
        '<ul>' + ''.join(f'<li><a href="{name}">{name}</a></li>' for name in [
            "levels.csv", "levels_models.csv.gz", "contrasts.csv", "contrasts_models.csv.gz",
            "regional_explanations.csv", "native_spatial_fractions.csv", "native_ssp_ordering.csv",
            "grid_1degree_2050_models.csv.gz", "coverage.csv"]) + '</ul>',
        '<p>希望对你有帮助，小凯！</p></html>']
    if (OUT / "dynamics/summary/report.html").exists():
        html.insert(3, '<p><a href="dynamics/summary/report.html">新增分析：事件频次、持续性与空间同步性</a></p>')
    target = OUT / "report.html"
    target.write_text("\n".join(html))
    write_json(OUT / "report_audit.json", dict(status="PASSED", report_sha256=digest(target),
        source_audit_sha256=digest(OUT / "audit.json"), code_sha256=digest(Path(__file__))))
    print(target)

if __name__ == "__main__":
    main()
