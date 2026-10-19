"""Add Fig. 2 SSP comparisons and the complete country analysis to the report."""
from pathlib import Path
from html.parser import HTMLParser
import runpy
import numpy as np
import pandas as pd

SSPS = ['ssp126', 'ssp245', 'ssp585']
TECH = {'wind': '风电', 'solar': '光伏'}
PAIRS = [('ssp245', 'ssp126'), ('ssp585', 'ssp126'), ('ssp585', 'ssp245')]
EVENT = {'high_temp': '高温', 'high_wind': '强风', 'hot_humid': '湿热',
         'icing': '覆冰', 'low_resource': '低资源', 'cold_highwind': '低温强风',
         'freezing_rain': '冻雨', 'high_humidity': '高湿', 'rainstorm': '暴雨'}
STEM = 'fig02_climate_layout_waterfall_2030s_2040s_2050s'
TERMS = ['climate_exposure', 'climate_normal_cf', 'climate_relative_loss', 'layout', 'gap']


def number(x, signed=False):
    return format(float(x), '+.2f' if signed else '.2f')


def append_fig2(h, p, note, table, fig, here):
    source = here / 'assets/data/fig02'
    derived = here / 'assets/derived'
    windows = pd.read_csv(source / 'global_window_models.csv')
    union = windows[windows.event.eq('all')].copy()
    assert union.shape[0] == 72
    assert union.climate_ssp.eq(union.station_ssp).all()
    assert union.groupby(['tech', 'snapshot', 'climate_ssp']).model.nunique().eq(4).all()
    levels = union.groupby(['tech', 'snapshot', 'climate_ssp']).R.agg(
        mean='mean', minimum='min', maximum='max').reset_index()
    levels.to_csv(derived / 'fig02_path_levels.csv', index=False)
    rows, contrasts = [], []
    for tech in TECH:
        for snapshot in [2030, 2040, 2050]:
            g = union[union.tech.eq(tech) & union.snapshot.eq(snapshot)]
            w = g.pivot(index='model', columns='climate_ssp', values='R')[SSPS]
            means = w.mean()
            for high, low in PAIRS:
                d = w[high] - w[low]
                contrasts.append(dict(tech=tech, snapshot=snapshot, high=high, low=low,
                    mean=d.mean(), minimum=d.min(), maximum=d.max(), positive=int((d > 0).sum()),
                    negative=int((d < 0).sum()), n_models=len(d),
                    pct_of_baseline_mean=100*d.mean()/means[low]))
            rows.append([TECH[tech], f'{snapshot}s', *map(number, means),
                         *[number(means[a]-means[b], True) for a, b in PAIRS]])
    contrasts = pd.DataFrame(contrasts)
    contrasts.to_csv(derived / 'fig02_paired_contrasts.csv', index=False)
    wf = pd.read_csv(source / (STEM + '_models.csv'))
    assert len(wf) == 24 and wf.closure.abs().max() < 1e-9
    means = wf.groupby(['tech', 'snapshot'])[TERMS + ['climate_total']].mean()
    for r in contrasts[contrasts.high.eq('ssp585') & contrasts.low.eq('ssp126')].itertuples():
        assert np.isclose(means.loc[(r.tech, r.snapshot), 'gap'], r.mean, atol=1e-9)
    means.reset_index().to_csv(derived / 'fig02_four_contributions.csv', index=False)

    h(2, '6. Fig. 2：不同SSP路径的单位装机损失及差异来源', 'fig02')
    note('三条路径的单位装机损失不按126、245、585单调排序。风电三个年代均为SSP245最低，'
         'SSP585相对126从2030s略低转为2040s和2050s更高；2050s的正差主要由布局贡献形成。'
         '光伏三个年代均为SSP245最高，585与126的差异小且模式存在分歧，2050s均值仅略高。'
         '这里比较的是各SSP气候与对应部署共同组成的路径。')
    fig('fig02', 'Fig. 2完整图：a–b比较三条配对路径；c–d以四项贡献解释585−126；e–f比较同一事件在不同路径下的损失。')
    p('[a–b年度轨迹](assets/images/fig02_ab.png) · [c–d四贡献瀑布图](assets/images/fig02_cd.png) · '
      '[e–f事件损失](assets/images/fig02_ef.png) · '
      '[三个年代独立瀑布图](assets/images/' + STEM + '.png)')
    table(['面板', '比较对象', '应回答的问题'], [
        ['a 风电／b 光伏', '126、245、585的逐年单位装机损失', '谁更高、差距是否扩大、245是否位于另外两条路径之间？'],
        ['c 风电／d 光伏', '各年代585−126', '气候暴露、事件期正常发电能力、事件期相对损失及布局如何共同形成净差？'],
        ['e 风电／f 光伏', '每个年代、同一事件的126／245／585', '路径差异对应哪些事件标签的损失变化？不能把标签差直接加成并集差。']])
    p('口径：损失为有符号年均净损失，R=损失电量/有效装机，单位MWh/MW/年。'
      '2030s、2040s、2050s分别指2030–2039、2040–2049、2050–2059，使用各年代容量快照。'
      '所有路径差先在同一模式内计算，再对四模式等权平均；区间是四模式min–max，不是置信区间。'
      '相对差百分比为集合平均差除以参考路径集合平均R，不是全年发电损失率。'
      '三条配对路径不是只改变气候的实验。部署585标签的场站来源为SSP5-6.0文件。')

    h(3, '6.1 三条路径的水平、排序与配对差', 'fig02-path-levels')
    table(['技术', '年代', 'SSP126', 'SSP245', 'SSP585', '245−126', '585−126', '585−245'], rows)
    p('风电中，SSP245的年代均值约84–85，三年代几乎不变；126随年代上升，585上升更快。'
      '因此风电的主要路径分化是245与另外两条路径逐渐拉开，而585与126的高低关系在2030s之后反转。'
      '2050s，585、126、245分别为123.09、107.18、84.38；585比126高15.91（14.85%），'
      '245比126低22.79（21.27%），585比245高38.70（45.86%）。'
      '不能把245位于中间的气候强迫解释为必然位于中间的单位装机损失。')
    p('光伏中，SSP245三个年代都最高。585在2030s和2040s低于126，2050s略高于126；'
      '2050s的245、585、126分别为80.69、78.49、77.60。'
      '585−126仅+0.90（+1.16%），明显小于245−126的+3.09（+3.98%）。'
      '因此光伏结果应强调“245相对较高、585与126接近且有模式分歧”，不能写成损失随排放路径单调升高或降低。')
    table(['技术', '年代', '对比', '均值差', '四模式差值范围', '升／降模式数'], [
        [TECH[r.tech], f'{r.snapshot}s', f'{r.high[3:]}−{r.low[3:]}', number(r.mean, True),
         f'{number(r.minimum, True)} 至 {number(r.maximum, True)}', f'{r.positive}/4 ↑；{r.negative}/4 ↓']
        for r in contrasts.itertuples()])
    p('特别是风电585−126在2040s、2050s均为4/4模式上升；2050s范围为+11.65至+20.69。'
      '光伏585−126在2030s、2040s均为3/4模式下降，2050s则2升2降，范围−3.02至+7.77。'
      '光伏2050s正均值不能表述为模式一致的损失增加。其余路径对比的支持程度应按上表逐项读取。')
    p('[路径水平源表](assets/derived/fig02_path_levels.csv) · '
      '[全部配对差、百分比与模式方向](assets/derived/fig02_paired_contrasts.csv)')

    h(3, '6.2 a–b：路径分化随年代如何发展', 'fig02-annual')
    fig('fig02_ab', 'a–b：年度四模式均值、模式min–max及2030–2059线性趋势；比较三条路径的相对位置和变化速度。')
    trends = pd.read_csv(source / 'annual_trends.csv').pivot(index='tech', columns='climate_ssp', values='slope')
    table(['技术', '126斜率', '245斜率', '585斜率', '585−126斜率差', '245−126斜率差'], [
        [TECH[t], *[f'{trends.loc[t, s]:+.3f}' for s in SSPS],
         f'{trends.loc[t, "ssp585"]-trends.loc[t, "ssp126"]:+.3f}',
         f'{trends.loc[t, "ssp245"]-trends.loc[t, "ssp126"]:+.3f}'] for t in TECH])
    p('斜率单位为MWh/MW/年²。风电585斜率+1.484明显高于126的+0.636，245接近零（−0.027），'
      '与年代差距扩大的结论一致。光伏三条路径均为负斜率，585下降较慢，因此585−126的相对差趋向上移，'
      '但这不代表585自身的损失不断增加。')
    p('趋势线是30个集合年度均值的描述性拟合。2040和2050更换容量快照，'
      '尤其风电2050附近的变化包含部署改变；不能把整段斜率或边界跳变全部归因为气候变化，也未据此检验显著性。')

    h(3, '6.3 c–d：585−126差异的四项来源', 'fig02-attribution')
    fig('fig02_cd', 'c–d：上风电、下光伏；每年代依次为气候暴露、气候事件期正常CF、气候事件期相对损失、布局和净差。')
    p('分解为：ΔR=气候—暴露贡献+气候—事件期正常发电能力贡献+气候—事件期相对损失贡献+布局贡献。'
      '固定部署时R=E×CF_event×r_event；E为年均装机加权事件并集小时，CF_event为事件期正常电量/装机加权事件小时，'
      'r_event为事件期净损失/事件期正常电量。先对每种固定部署下的气候变化作三因素六顺序Shapley分解，'
      '再平均部署126和585的相应气候贡献；布局项则平均气候126和585下的部署差。交互作用已分摊，不另加第五项。')
    table(['技术', '年代', '气候暴露', '气候正常CF', '气候相对损失', '气候合计', '布局', '净差'], [
        [TECH[t], f'{y}s', *[number(means.loc[(t, y), k], True) for k in
         ['climate_exposure', 'climate_normal_cf', 'climate_relative_loss', 'climate_total', 'layout', 'gap']]]
        for t in TECH for y in [2030, 2040, 2050]])
    p('风电2030s：气候合计+0.09与布局−2.71形成净差−2.62，585较低主要对应布局负贡献。'
      '到2040s，布局转为+7.29，超过气候合计−2.09，净差转为+5.20。'
      '2050s布局进一步达到+17.71，而气候暴露+3.11和正常CF+3.68被相对损失−8.59抵消，'
      '气候合计为−1.80，最终净差+15.91。'
      '因此“585比126损失更高”在后两个年代主要对应布局正贡献，不能简化成气候导致暴露增加。')
    p('光伏2030s：气候合计+1.78被布局−2.15抵消，净差−0.37。'
      '2040s：气候−1.19与布局−1.51同向降低，净差−2.70。'
      '2050s：暴露−2.98是主要负气候贡献，正常CF+1.34部分抵消，相对损失为−0.49；'
      '气候合计−2.13，但布局转为+3.03，使净差小幅转正为+0.90。'
      '风光都出现布局贡献从2030s负值转向2050s正值，风电转正更早且幅度更大；这是集合结果的跨技术对照。')
    p('风电2040s和2050s的布局正贡献、相对损失负贡献均有4/4模式支持。'
      '光伏布局在前两个年代为4/4负、2050s为4/4正；2050s气候合计却2升2降，'
      '所以不能把每个集合均值项都称作跨模式稳健。四模式逐项数值见源表。')
    p('CF项表示事件发生期间的正常发电机会及事件窗口组成发生变化，不等于全年资源水平或全年发电能力变化。'
      'r项表示事件期损失相对正常发电的变化，并非纯粹的物理灾害强度。'
      '布局项反映归一化容量权重、地点及其有效支持变化；装机总量统一倍增会在R的分子分母中抵消。'
      '因此本图无法回答扩建导致多少总损失；该问题由下一节的总损失分解回答。')
    p('这与Fig. 4气候—部署反事实分析使用相同的受控比较逻辑：先把气候与布局分开，再细分气候项。'
      'c–d只解释585−126；关于245为何不同，应依据三路径水平和事件比较，不将585−126的贡献套用到245。')
    p('[四项贡献均值](assets/derived/fig02_four_contributions.csv) · '
      '[四模式完整分解](assets/data/fig02/' + STEM + '_models.csv) · '
      '[固定部署分解](assets/data/fig02/' + STEM + '_fixed_deployment.csv)')

    h(3, '6.4 e–f：按同一事件比较不同SSP', 'fig02-events')
    fig('fig02_ef', 'e–f：每个年代从左至右为126、245、585。应比较同色柱段的实际损失，百分比仅是事件标签总和中的组成。')
    events = pd.read_csv(source / 'event_composition_models.csv')
    event_levels = events.groupby(['tech', 'snapshot', 'event', 'climate_ssp']).R.mean().unstack('climate_ssp')
    event_rows = []
    for tech in TECH:
        h(4, TECH[tech] + '：各年代事件损失与路径差', 'fig02-events-' + tech)
        erows = []
        for (t, y, event), r in event_levels.iterrows():
            if t != tech:
                continue
            erows.append([f'{y}s', EVENT[event], *[number(r[s]) for s in SSPS],
                          number(r.ssp245-r.ssp126, True), number(r.ssp585-r.ssp126, True)])
            event_rows.append(dict(tech=t, snapshot=y, event=event, **r.to_dict(),
                                  delta245_126=r.ssp245-r.ssp126, delta585_126=r.ssp585-r.ssp126))
        table(['年代', '事件', '126', '245', '585', '245−126', '585−126'], erows)
    pd.DataFrame(event_rows).to_csv(derived / 'fig02_event_path_comparisons.csv', index=False)
    p('风电的路径分化尤其对应低资源标签：585−126的低资源损失差从2030s的−2.49变为2040s的+3.92，'
      '2050s扩大至+17.60。2050s的585高温和覆冰损失反而分别低于126约1.89和2.40，'
      '因此不能将585较高的总体损失笼统解释为高温损失增加。'
      '同一年代245相较126的低资源、高温、覆冰分别降低18.19、3.64、3.96，与245损失最低相呼应。')
    p('光伏2050s，245相较126的六类事件均值全部更高，主要差包括冻雨+1.44、低资源+1.20和高湿+0.74。'
      '585相较126则有升有降：低资源+1.55、冻雨+0.46，而高湿−0.98、覆冰−0.48、暴雨−0.39；'
      '这种混合变化与两条路径总体损失接近相呼应。'
      '2040s的585较低同时伴随低资源−1.13和冻雨−1.52，说明不能把2050s的事件差方向推广到全部年代。')
    note('事件类别存在重叠。e–f的柱高是事件标签损失之和，不等于a–d的全部事件并集损失；'
         '柱内百分比也不是对并集损失的独占归因。上表用于比较同一事件的路径差，'
         '不能把这些差值直接相加来验证a–d净差。')
    p('[事件路径比较源表](assets/derived/fig02_event_path_comparisons.csv) · '
      '[逐模式事件数据](assets/data/fig02/event_composition_models.csv) · '
      '[图注与口径](assets/provenance/fig02/caption.md)')

    h(3, '6.5 可用于论文结果段的综合表述', 'fig02-summary')
    p('不同SSP路径下的全球单位装机损失呈现不同的排序和时间变化。'
      '风电的SSP245在三个年代均最低，而SSP585相对SSP126由2030s的−2.62转为2040s的+5.20和2050s的+15.91 MWh/MW/年；'
      '后两个年代的正差均得到四模式一致支持，并主要对应布局正贡献。'
      '光伏的SSP245在三个年代均最高，SSP585−SSP126则依次为−0.37、−2.70和+0.90，'
      '2050s的微弱正差来自布局正贡献超过气候负贡献，但净差方向存在模式分歧。'
      '这些结果表明，配对路径的损失排序由气候条件与装机布局共同形成，不能直接按SSP强迫水平推断。')
    return {'union_rows': len(union), 'paired_contrasts': len(contrasts),
            'waterfall_rows': len(wf), 'max_closure': float(wf.closure.abs().max())}


class Node:
    def __init__(self, tag='', attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []


class CountryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'meta', 'img', 'br', 'hr', 'link', 'input'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def descendants(node, tag):
    result = []
    for child in node.children:
        if isinstance(child, Node):
            if child.tag == tag:
                result.append(child)
            result.extend(descendants(child, tag))
    return result


def node_text(node):
    if isinstance(node, str):
        return node
    text = ''.join(node_text(c) for c in node.children)
    if node.tag == 'a' and node.attrs.get('href') and text:
        href = node.attrs['href']
        if href.startswith('#'):
            href = '#country-' + href[1:]
        return '[' + text + '](' + href + ')'
    if node.tag in {'b', 'strong'}:
        return '**' + text + '**'
    return text


def append_country(h, p, note, table, blocks, here):
    h(2, '7. 全球与Top-10国家：规模、布局和损失的路径权衡', 'country-tradeoffs')
    p('本节完整收录原国家部署分析的五个问题、七张图、全球与十国逐项结果及配对路径绝对量。'
      '图片和数据均保存在本目录assets下。'
      '[单独阅读国家分析](country_deployment_tradeoffs_top10.html)。')
    p('读图顺序：先比较126、245、585配对路径的容量、总损失和正常电量；'
      '再固定气候，用规模与布局分解解释部署之间的差异；'
      '最后比较相同气候下的单位装机损失和相对损失率，并检查这种排名是否跨三种气候及四个模式成立。'
      '这里的“最优部署”只针对所比较的发电损失指标，不等于某国应选择某一社会经济或排放路径。')
    parser = CountryParser()
    parser.feed((here / 'country_deployment_tradeoffs_top10.html').read_text())
    counter = 0

    def emit(node):
        nonlocal counter
        if isinstance(node, str) or node.tag in {'style', 'head', 'title', 'meta', 'script'}:
            return
        if node.tag in {'h1', 'h2', 'h3'}:
            counter += 1
            anchor = 'country-' + node.attrs.get('id', f'section-{counter}')
            h(4 if node.tag == 'h3' else 3, node_text(node), anchor)
        elif node.tag in {'p', 'aside', 'li', 'summary'}:
            text = node_text(node).strip()
            if text and text != '希望对你有帮助，小凯！' and '返回综合报告国家分析章节' not in text:
                (note if node.tag == 'aside' else p)(text)
        elif node.tag == 'table':
            rows = descendants(node, 'tr')
            headers = [node_text(c) for c in rows[0].children if isinstance(c, Node) and c.tag in {'th', 'td'}]
            values = [[node_text(c) for c in r.children if isinstance(c, Node) and c.tag in {'th', 'td'}] for r in rows[1:]]
            table(headers, values)
        elif node.tag == 'img':
            path = node.attrs['src']
            assert path.startswith('assets/') and (here / path).is_file()
            blocks.append(('figure', path, node.attrs.get('alt', '国家部署比较')))
        else:
            for child in node.children:
                emit(child)
    bodies = descendants(parser.root, 'body')
    assert len(bodies) == 1
    emit(bodies[0])
    return {'country_images': len(descendants(bodies[0], 'img')),
            'country_tables': len(descendants(bodies[0], 'table'))}


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('build_analysis_report.py')),
                   run_name='__main__')
