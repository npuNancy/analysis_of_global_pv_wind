"""Embed both GEM figure families and rebuild Markdown from the HTML inventory."""
import base64
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DOC = ROOT / "document"
PREFIX = "../paper_figures/supplementary/global_metric_trends/outputs/"
FAMILIES = [("lcoe2025", "全球场站-LCOE-2025"), ("fixed2025", "固定2025装机")]
CATEGORIES = {
    "capacity": ["capacity"],
    "exposure": ["exposure_total", "exposure_mean"],
    "loss": ["total_loss", "unit_loss", "loss_fraction"],
    "generation": ["total_generation", "unit_generation", "cf"],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def block(name, body):
    return "\n<!-- GEM2025:" + name + " BEGIN -->\n" + body + "\n<!-- GEM2025:" + name + " END -->\n"


def metric_name(record):
    return record["metric"].replace("station_fixed_", "").replace("station_", "")


def figure(record, family):
    name = record["name"]
    title = record["title"].replace("（固定2025装机）", "")
    url = PREFIX + name + ".png"
    caption = family + "：" + title
    encoded = base64.b64encode((OUT/(name+".png")).read_bytes()).decode()
    links = "；".join('<a href="' + PREFIX + name + "_" + letter + '.png">' + letter + "</a>"
                     for letter in "abc")
    return ('<h4 id="figure-' + name + '">' + title + '</h4>\n<figure>\n'
            '<img src="data:image/png;base64,' + encoded + '" data-source="' + url +
            '" alt="' + caption + '">\n<figcaption>' + caption + '</figcaption>\n</figure>\n'
            '<p><a href="' + url + '">完整PNG</a>；独立子图：' + links + '。</p>\n')


class Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "hr", "meta", "link", "input"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def descendants(node, tag):
    found = []
    for child in node.children:
        if isinstance(child, Node):
            if child.tag == tag:
                found.append(child)
            found.extend(descendants(child, tag))
    return found


def markdown(node):
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node)
    tag = node.tag
    content = "".join(markdown(c) for c in node.children).strip()
    if tag in {"h1", "h2", "h3", "h4"}:
        anchor = '<a id="' + node.attrs["id"] + '"></a>\n\n' if "id" in node.attrs else ""
        return "\n\n" + anchor + "#" * int(tag[1]) + " " + content + "\n\n"
    if tag == "a":
        return "[" + content + "](" + node.attrs.get("href", "") + ")"
    if tag == "img":
        return "\n\n![" + node.attrs.get("alt", "") + "](" + node.attrs["data-source"] + ")\n\n"
    if tag in {"strong", "b"}:
        return "**" + content + "**"
    if tag == "code":
        return chr(96) + content + chr(96)
    if tag in {"sub", "sup", "i", "em"}:
        return "<" + tag + ">" + content + "</" + tag + ">"
    if tag == "br":
        return "<br>"
    if tag == "table":
        rows = []
        for row in descendants(node, "tr"):
            cells = [c for c in row.children if isinstance(c, Node) and c.tag in {"td", "th"}]
            rows.append([markdown(c).replace("\n", " ").replace("|", r"\|").strip() for c in cells])
        if not rows:
            return ""
        lines = ["| " + " | ".join(row) + " |" for row in rows]
        lines.insert(1, "| " + " | ".join(["---"] * len(rows[0])) + " |")
        return "\n\n" + "\n".join(lines) + "\n\n"
    if tag == "li":
        return "\n- " + content + "\n"
    if tag in {"ul", "ol", "p", "section", "div", "figure", "figcaption", "main"}:
        return "\n\n" + content + "\n\n"
    return content


def main():
    report = json.loads((OUT/"gem2025_figure_manifest.json").read_text())
    if report["status"] not in {"NUMERIC_AND_EXPORT_PASSED", "PASSED"}:
        raise ValueError("Figure export is not accepted")
    records = report["figures"]
    for record in records:
        for image in [record["complete"]] + record["panels"]:
            if sha(OUT/image["path"]) != image["sha256"]:
                raise ValueError("Figure bytes changed " + image["path"])
    html_path, md_path = DOC/"风电光伏数据.html", DOC/"风电光伏数据.md"
    html = html_path.read_text()
    html = re.sub(r"\n?<!-- GEM2025:(\w+) BEGIN -->.*?<!-- GEM2025:\1 END -->\n?",
                  "\n", html, flags=re.S)
    # Map pre-existing embedded figures to the same PNGs linked by Markdown.
    image_sources = {}
    for url in re.findall(r"!\[[^]]*\]\(([^)]+)\)", md_path.read_text()):
        path = DOC/url
        if path.is_file():
            image_sources[sha(path)] = url
    def tag_source(match):
        tag = match.group()
        if "data-source=" in tag:
            return tag
        encoded = re.search(r'src="data:image/png;base64,([^"]+)"', tag)
        if not encoded:
            raise ValueError("Unexpected inventory image")
        digest = hashlib.sha256(base64.b64decode(encoded[1])).hexdigest()
        if digest not in image_sources:
            raise ValueError("Existing embedded figure has no matching PNG")
        return tag[:-1] + ' data-source="' + image_sources[digest] + '">'
    html = re.sub(r"<img\b[^>]*>", tag_source, html)
    for category, metrics in CATEGORIES.items():
        sections = []
        for family, label in FAMILIES:
            body = '<h3 id="' + category + "-" + family + '">' + label + "</h3>\n"
            selected = [r for r in records if r["family"] == family and metric_name(r) in metrics]
            selected.sort(key=lambda r: metrics.index(metric_name(r)))
            if not selected:
                body += ("<p>2026—2059年固定2025年末实际场站位置与容量：陆风及类型未知风电"
                         "0.9743 TW、光伏1.2804 TWp；历史2015—2025仍使用各年的实际装机。"
                         "其他指标按共同有效场站计算，详见"
                         '<a href="BCSD_v2数据使用指南.md#lcoe-2025">数据指南第13节</a>。</p>\n')
            else:
                if category == "capacity":
                    body += ("<p>2015—2025为逐年GEM实际装机；2026—2029固定2025装机，"
                             "2030—2059使用累计LCOE布局。容量直接汇总完整场站目录，"
                             "三条彩线对应场站SSP1-2.6、SSP2-4.5、SSP5-6.0。</p>\n")
                else:
                    body += ("<p>2015—2025为ERA5-Land与逐年GEM装机；2026—2059为四模式均值。"
                             + ("2026—2029固定2025装机，2030—2059使用累计LCOE布局。"
                                if family == "lcoe2025" else "2026—2059始终固定2025位置和容量。")
                             + "</p>\n")
                body += "\n".join(figure(r, label) for r in selected)
            sections.append(body)
        pattern = r'(<section[^>]*aria-labelledby="' + category + r'"[^>]*>)(.*?)(</section>)'
        html, n = re.subn(pattern, lambda m: m[1]+m[2]+block(category, "\n".join(sections))+m[3],
                          html, count=1, flags=re.S)
        if n != 1:
            raise ValueError("Missing HTML category " + category)
        nav = "\n".join('<li><a href="#' + category + "-" + f + '">' + label + "</a></li>"
                        for f, label in FAMILIES)
        pattern = r'(<li><a href="#' + category + r'-lcoe">.*?</li>)'
        html, n = re.subn(pattern, lambda m: m[1]+block("nav_"+category, nav), html, count=1)
        if n != 1:
            raise ValueError("Missing category navigation")
    overview = "".join(
        "<tr><td>"+label+"</td><td>"+("完整目录总装机容量（TW）" if family == "lcoe2025"
        else "2026—2059固定2025装机")+"</td><td>容量加权暴露总量（MW·天/年）<br>平均暴露时长（天/年）"
        "</td><td>总净损失（MWh/年）<br>单位装机净损失（MWh/MW/年）<br>正常年电量损失占比（%）"
        "</td><td>总发电（PWh/年）<br>单位装机发电（MWh/MW/年）<br>容量加权CF</td></tr>"
        for family, label in FAMILIES)
    html = html.replace("</tbody>", block("overview", overview)+"</tbody>", 1)
    rows = []
    for family, label in FAMILIES:
        for record in [r for r in records if r["family"] == family]:
            suffix = "fixed_" if family == "fixed2025" else ""
            rows.append("<tr><td>"+label+"</td><td>"+record["title"].replace("（固定2025装机）", "")+
                        '</td><td><a href="'+PREFIX+record["name"]+'.png">PNG</a></td>'
                        '<td><a href="'+PREFIX+"source_data/gem2025_"+suffix+'models.csv">CSV</a></td>'
                        '<td><a href="'+PREFIX+"source_data/gem2025_"+suffix+'display.csv">CSV</a></td></tr>')
    table = ('<h3 id="gem2025-results">LCOE-2025与固定2025装机结果路径</h3>\n'
             '<p>正式CF、Extreme、Loss与全年发电量入口见'
             '<a href="BCSD_v2数据使用指南.md#lcoe-2025">数据指南第13节</a>。'
             '固定装机逐模式表保存2026—2059，历史段见LCOE-2025逐模式表。</p>'
             '<div class="table-scroll"><table><thead><tr><th>口径</th><th>指标</th>'
             '<th>完整图</th><th>逐模式结果</th><th>绘图均值</th></tr></thead><tbody>'
             + "\n".join(rows) + "</tbody></table></div>")
    html = re.sub(r'(<section[^>]*aria-labelledby="tables"[^>]*>)(.*?)(</section>)',
                  lambda m:m[1]+m[2]+block("results", table)+m[3], html, count=1, flags=re.S)
    notes = """<h3>全球场站-LCOE-2025与固定2025装机：数据及绘图</h3>
<p>两组新增图使用GEM 2026年2月版场站数据与修正后的适宜性格点；仅保留陆上及类型未知风电，光伏容量为MWp/DC。历史采用允许退出与容量变化的historical_snapshot逐年资料。2025只代表2025年。</p>
<ul class="defs">
<li>2015—2025黑线：ERA5-Land逐小时气候与当年年末实际装机。容量按全年应用，未按年内投运月份折算；发电量是气候驱动估算。</li>
<li>全球场站-LCOE-2025彩线：2026—2029固定2025装机；2030—2059使用2030、2040、2050累计快照。场站/气候配对为126/126、245/245、560/585。三条气候路径分别按四模式等权平均。</li>
<li>固定2025装机彩线：2026—2059全部采用GEM2025位置与容量；未来逐站能量先除以档案当年容量，再乘2025容量。过渡与未来档案的共同支持集交集在各路径内跨年固定。</li>
<li>装机容量图直接汇总完整场站目录，使用场站SSP标签；其他指标使用共同有效场站，并对四个气候模式等权平均。</li>
<li>两组图各自的彩线从历史2025端点接出；2026—2059数值未平移。逐年画线，不添加趋势拟合。模式最小/最大值保留在源表，不作为置信区间。</li>
<li>Loss正常CF分别按2015—2025、2026—2029及三个未来十年窗口，在各气候路径内排除事件并集后估计。净损失衡量相对同期正常状态的事件偏离，保留符号；风电能量不乘0.1。</li>
<li>暴露按每种技术的事件时间并集去重。风光合计先加总容量加权分子、分母，再求比值；CF为有效容量加权全年平均，全年发电量保留各模式原生日历。</li>
<li>各面板纵轴独立，均为5个等距间隔、6个刻度。原图的1×3布局、字体、SSP配色、浅灰水平网格线与底部图例延续使用；子图从左至右为风光合计、风电、光伏。</li>
<li>共新增17张完整组图和51张独立子图，均为600 dpi PNG。完整图以base64嵌入HTML，Markdown及独立子图通过相对路径引用相同PNG。</li>
</ul>
<p>正式数据及读取示例：<a href="BCSD_v2数据使用指南.md#lcoe-2025">数据指南第13节</a>；
原始评价报告：<a href="GEM场站历史与LCOE未来气候评价.md">GEM场站历史与LCOE未来气候评价</a>。</p>
<p>同目录代码：<a href="../paper_figures/supplementary/global_metric_trends/plot_gem2025.py">两组图绘制</a>、
<a href="../paper_figures/supplementary/global_metric_trends/update_gem2025_documents.py">HTML与Markdown整理</a>，各有同名SLURM脚本。
<a href="../paper_figures/supplementary/global_metric_trends/outputs/gem2025_figure_manifest.json">图件、源表与数值一致性记录</a>。</p>"""
    html = re.sub(r'(<section[^>]*aria-labelledby="notes"[^>]*>)(.*?)(</section>)',
                  lambda m:m[1]+m[2]+block("notes", notes)+m[3], html, count=1, flags=re.S)
    # Preserve figure anchor IDs while numbering figures in their display order.
    old_to_new = {}
    count = 0
    def number_figure(match):
        nonlocal count
        count += 1
        title = match[2]
        old = re.match(r"图\s*(\d+)\.\s*(.*)", title, re.S)
        if old:
            old_to_new[int(old[1])] = count
            title = old[2]
        return match[1]+"图 "+str(count)+". "+title+match[3]
    html = re.sub(r'(<h4\b[^>]*>)(.*?)(</h4>)', number_figure, html, flags=re.S)
    def update_notes(match):
        content = re.sub(r"图\s*(\d+(?:、\d+)*)", lambda m: "图"+"、".join(
            str(old_to_new.get(int(n), int(n))) for n in m[1].split("、")), match[2])
        content = content.replace("各图从左到右依次为风电+光伏、单独风电、单独光伏。",
                                  "原有网格、dispatch与全球场站-LCOE图从左到右依次为风电+光伏、单独风电、单独光伏。")
        return match[1]+content+match[3]
    html = re.sub(r'(<section[^>]*aria-labelledby="notes"[^>]*>)(.*?)(</section>)',
                  update_notes, html, count=1, flags=re.S)
    html = re.sub(r"(<main>)(.*?)(</main>)",
                  lambda m: m[1]+re.sub(r"(?m)[ \t]+$", "", m[2])+m[3], html, flags=re.S)
    parser = DocumentParser()
    parser.feed(re.search(r"<main>(.*?)</main>", html, re.S)[1])
    nodes = parser.root
    images = descendants(nodes, "img")
    if len(images) != 36 or count != 36:
        raise ValueError("Expected 19 original and 17 new figures")
    for node in images:
        raw = base64.b64decode(node.attrs["src"].split(",", 1)[1])
        if hashlib.sha256(raw).hexdigest() != sha(DOC/node.attrs["data-source"]):
            raise ValueError("HTML/PNG mismatch")
    ids = re.findall(r'\bid="([^"]+)"', html)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate HTML anchors")
    for anchor in re.findall(r'href="#([^"]+)"', html):
        if anchor not in ids:
            raise ValueError("Missing HTML anchor " + anchor)
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", markdown(nodes)).strip()+"\n"
    text = re.sub(r"(?m)[ \t]+$", "", text)
    if len(re.findall(r"!\[", text)) != 36 or "data:image" in text:
        raise ValueError("Markdown image structure")
    html_path.write_text(html)
    md_path.write_text(text)
    original = DOC/"GEM场站历史与LCOE未来气候评价.md"
    generator = ROOT/"paper_figures/supplementary/gem_lcoe_history/plot.py"
    old = "原有 document/BCSD_v2数据使用指南.md、document/风电光伏数据.md、document/风电光伏数据.html 的SHA256保持不变。"
    new = ("LCOE-2025数据入口、字段与读取示例已汇总至[BCSD-v2数据使用指南第13节]"
           "(BCSD_v2数据使用指南.md#lcoe-2025)；统一风格图件见[风电光伏数据](风电光伏数据.html)。")
    for path in (original, generator):
        content = path.read_text().replace(old, new)
        content = content.replace("## 固定2025装机对照图", "## 固定2025装机")
        content = content.replace("## 图件", "## 全球场站-LCOE-2025")
        path.write_text(content)
    protected = ROOT/"paper_figures/supplementary/gem_lcoe_history/protected_document_hashes.json"
    names = json.loads(protected.read_text())
    protected.write_text(json.dumps({name: sha(ROOT/name) for name in names},
                                   ensure_ascii=False, indent=2)+"\n")
    validation = dict(status="PASSED", html_figures=len(images), markdown_figures=36,
                      new_triptychs=17, independent_panels=51, anchors=len(ids),
                      documents={p.name: sha(p) for p in (html_path, md_path, DOC/"BCSD_v2数据使用指南.md")})
    (OUT/"gem2025_document_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(validation, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
