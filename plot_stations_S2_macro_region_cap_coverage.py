#!/usr/bin/env python3
"""
20 大区 × 3 SSP 装机容量覆盖率：分组堆叠柱状图
==============================================

核心结论：
    项目区域（AREA_DICT 国家框 + NAM-12 域）对全球各大区装机容量的覆盖率
    高度空间不均——北美 / 东亚 / 加勒比 / 西欧近乎完全覆盖，而西非 / 中非 /
    东非接近 0；覆盖主要由「截至 2030 年」的早期布局奠定，后续时段新增贡献
    递减；三个 SSP 情景之间总体覆盖率差异较小。

图型：
    单一 hero 面板（quantitative grid）。横轴为 20 个大区（中文简写），
    每个大区并排 4 根柱：
      - 第 1 根「现状(GRW)」：现状实测装机容量被项目区域覆盖的比例（单柱，不堆叠）；
      - 后 3 根对应 3 个 SSP，每根按时段「截至 2030 / 2030→2040 新增 /
        2040→2050 新增」自底向上堆叠。
    大区排序由 --sort 控制（默认 ssp）：
      - ssp：3 个 SSP 的 2050 覆盖率平均后降序（默认，原排序）；
      - grw：现状(GRW)装机覆盖率降序。
    在 threshold（默认 60%）处画红色横线；SSP1-2.6 的 2050 年覆盖率低于
    该阈值的大区，横坐标名称标红。
    当 3 个 SSP 的 2050 覆盖率均值与现状(GRW)覆盖率相差超过 margin（默认 5%）
    时，大区名后附加箭头：↑=未来明显更高，↓=未来明显更低（由 --margin 控制）。
    图例置于图形右侧（轴外）。

编码（时段贡献分解，使 SSP 柱总高 = 2050 覆盖率 ≤ 100%）：
    设某大区某情景 2050 年总装机为 C₅₀，被项目区域覆盖的装机量在
    2030/2040/2050 分别为 I₃₀/I₄₀/I₅₀（CSV 年份为累积存量，已验证单调），则
      - 底段  = I₃₀        / C₅₀   （截至 2030）
      - 中段  = (I₄₀ - I₃₀) / C₅₀   （2030→2040 新增）
      - 顶段  = (I₅₀ - I₄₀) / C₅₀   （2040→2050 新增）
      - 柱总高 = I₅₀ / C₅₀ = 该大区该情景 2050 年装机容量覆盖率
    色相区分 SSP（现状柱为灰色），明度区分时段（深→浅 = 早→晚）。

数据来源：
    outputs/plot_stations/plot_stations_S1_with_regions/stats_by_macro_region_<ssp>.csv
    （由 plot_stations_S1_with_regions.py 生成；含 year, region_id, region_name,
      cap_total_gw, cap_inside_gw 等列）
    outputs/plot_stations/plot_stations_S1_grw_coverage/grw_coverage_by_macro_region.csv
    （由 plot_stations_S1_grw_coverage.py 生成；提供现状装机逐大区覆盖率 cap_cover_ratio）

用法：
    python plot_stations_S2_macro_region_cap_coverage.py               # 默认仅输出 PNG
    python plot_stations_S2_macro_region_cap_coverage.py --threshold 60 # 阈值（默认 60）
    python plot_stations_S2_macro_region_cap_coverage.py --margin 5     # 箭头差值阈值（默认 5%）
    python plot_stations_S2_macro_region_cap_coverage.py --all-formats  # 额外导出 SVG/PDF/TIFF
"""

import os
import csv
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 上游产物路径（按依赖关系，引用 S1 阶段脚本的输出目录）
STATS_DIR = os.path.join(BASE_DIR, "outputs", "plot_stations", "plot_stations_S1_with_regions")
GRW_COV_CSV = os.path.join(
    BASE_DIR, "outputs", "plot_stations", "plot_stations_S1_grw_coverage", "grw_coverage_by_macro_region.csv"
)
# 本脚本输出目录 = outputs/plot_stations/<本脚本文件名>/
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "plot_stations", os.path.splitext(os.path.basename(__file__))[0])

SSPS = ["ssp126", "ssp245", "ssp560"]
SSP_LABELS = {"ssp126": "SSP1-2.6", "ssp245": "SSP2-4.5", "ssp560": "SSP5-6.0"}
YEARS = [2030, 2040, 2050]  # 自底向上堆叠顺序（早→晚）
PERIOD_LABELS = ["2030", "2030→2040", "2040→2050"]

# 现状(GRW)单柱配色（灰系，区别于 3 个 SSP 的蓝/橙/红）
GRW_COLOR = "#555555"

# 色相=SSP，明度=时段（index 0..2 对应 2030/2040/2050，深→浅）。
# 与 plot_RQ1_generation.py 的 SSP_SHADES 保持一致（ssp560 复用其 ssp585 红系）。
SSP_COLORS = {
    "ssp126": ["#10254a", "#3a6ea5", "#9cc0e0"],  # 蓝系（深 → 浅）
    "ssp245": ["#b9742a", "#e7a13b", "#f6d28a"],  # 橙系
    "ssp560": ["#6e0f0f", "#c0392b", "#e8a39c"],  # 红系
}

# 20 大区中文简写（编号与 region_id_to_name.json 一致）
REGION_SHORT_CN = {
    1: "北美",
    2: "中美",
    3: "加勒比",
    4: "南美",
    5: "北欧",
    6: "西欧",
    7: "南欧",
    8: "东欧",
    9: "中亚",
    10: "东亚",
    11: "西亚",
    12: "南亚",
    13: "东南亚",
    14: "美拉",
    15: "澳新",
    16: "北非",
    17: "西非",
    18: "中非",
    19: "东非",
    20: "南非",
}

# ══════════════════════════════════════════════════════════════════════
# 出版级 rcParams + 中文字体
# ══════════════════════════════════════════════════════════════════════

mpl.rcParams.update(
    {
        "svg.fonttype": "none",  # SVG 文本可编辑
        "pdf.fonttype": 42,  # PDF 内嵌可编辑 TrueType
        "font.size": 8,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.8,
        "legend.frameon": False,
    }
)

font_path = "data/tracked/SourceHanSansSC-Normal.otf"
if os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    plt.rcParams["font.family"] = [fm.FontProperties(fname=font_path).get_name()]
plt.rcParams["axes.unicode_minus"] = False


# ══════════════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════════════


def load_region_caps(ssp):
    """读取某 SSP 的逐年大区统计，返回 {region_id: {year: (inside, total)}}。

    CSV 可能被工具重新对齐（表头/字段含空格），统一 strip。
    """
    path = os.path.join(STATS_DIR, f"stats_by_macro_region_{ssp}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"未找到大区统计 CSV：{path}\n" f"请先运行 plot_stations_S1_with_regions.py --ssp {ssp}"
        )
    data = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        for row in reader:
            r = {k: v.strip() for k, v in zip(header, row)}
            if r["region_id"] == "ALL":
                continue
            rid, yr = int(r["region_id"]), int(r["year"])
            data.setdefault(rid, {})[yr] = (float(r["cap_inside_gw"]), float(r["cap_total_gw"]))
    return data


def load_grw_coverage():
    """读取 GRW 现状装机的逐大区覆盖率，返回 {region_id: cap_cover_ratio}（0-1）。

    来源：plot_stations_S1_grw_coverage.py 的 grw_coverage_by_macro_region.csv。
    """
    if not os.path.exists(GRW_COV_CSV):
        raise FileNotFoundError(
            f"未找到 GRW 现状覆盖 CSV：{GRW_COV_CSV}\n" f"请先运行 plot_stations_S1_grw_coverage.py"
        )
    out = {}
    with open(GRW_COV_CSV, newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        for row in reader:
            r = {k: v.strip() for k, v in zip(header, row)}
            if r["region_id"] == "ALL":
                continue
            out[int(r["region_id"])] = float(r["cap_cover_ratio"])
    return out


def build_segments(sort_by="ssp"):
    """构建现状(GRW)覆盖率与各 SSP、各大区的 3 段时段贡献（占 2050 总装机的比例）。

    sort_by 控制大区排序（详见 region_order）：
      - "ssp"：3 个 SSP 的 2050 覆盖率平均后降序（默认，原排序）
      - "grw"：现状(GRW)装机覆盖率降序

    返回 (order, segments, final_cov, grw_arr):
      - order：大区编号列表，按 sort_by 指定方式降序
      - segments[ssp]：shape (n_region, 3)，列为 [截至2030, 2030→40, 2040→50]
      - final_cov[ssp]：shape (n_region,)，2050 年覆盖率（= 三段之和）
      - grw_arr：shape (n_region,)，现状(GRW)装机覆盖率（0-1），与 order 对齐
    """
    raw = {ssp: load_region_caps(ssp) for ssp in SSPS}
    grw_cov = load_grw_coverage()
    order = region_order(raw, grw_cov, sort_by)
    segments, final_cov = {}, {}
    for ssp in SSPS:
        segs = np.zeros((len(order), 3))
        for i, rid in enumerate(order):
            yv = raw[ssp].get(rid, {})
            i30 = yv.get(2030, (0.0, 0.0))[0]
            i40 = yv.get(2040, (0.0, 0.0))[0]
            i50, c50 = yv.get(2050, (0.0, 0.0))
            if c50 <= 0:
                continue
            segs[i, 0] = i30 / c50
            segs[i, 1] = max(i40 - i30, 0.0) / c50
            segs[i, 2] = max(i50 - i40, 0.0) / c50
        segments[ssp] = segs
        final_cov[ssp] = segs.sum(axis=1)
    grw_arr = np.array([grw_cov.get(rid, 0.0) for rid in order])
    return order, segments, final_cov, grw_arr


def region_order(raw, grw_cov, sort_by="ssp"):
    """按指定方式对大区降序排列，使图自高覆盖向低覆盖读出。

    - sort_by="ssp"：3 个 SSP 的 2050 年装机容量覆盖率（I₅₀/C₅₀）平均后降序（默认，原排序）
    - sort_by="grw"：现状(GRW)装机覆盖率降序
    """
    rids = sorted(REGION_SHORT_CN)
    if sort_by == "grw":
        return sorted(rids, key=lambda r: grw_cov.get(r, 0.0), reverse=True)
    # 默认 "ssp"：原排序——3 个 SSP 平均的 2050 覆盖率降序
    score = {}
    for rid in rids:
        vals = []
        for ssp in SSPS:
            i50, c50 = raw[ssp].get(rid, {}).get(2050, (0.0, 0.0))
            vals.append(i50 / c50 if c50 > 0 else 0.0)
        score[rid] = float(np.mean(vals))
    return sorted(rids, key=lambda r: score[r], reverse=True)


# ══════════════════════════════════════════════════════════════════════
# 绘图
# ══════════════════════════════════════════════════════════════════════


def draw_legend(ax):
    """在轴右侧（轴外）绘制图例：首行=现状(GRW) 单柱，下接 3×3（行=SSP 色相，列=时段 明度）。"""
    # 图例起点在 axes 右边缘外侧（x > 1.0）；clip_on=False 使其可见
    x0, y_top = 0.825, 0.985
    cw, ch = 0.052, 0.052  # 色块宽/高
    gx, gy = 0.004, 0.012  # 色块间距
    lab_w = 0.085  # 左侧文字列宽

    # 背景框
    box_w = lab_w + 3 * cw + 2 * gx + 0.015
    box_h = 4 * ch + 3 * gy + 0.085
    ax.add_patch(
        Rectangle(
            (x0 - 0.012, y_top - box_h),
            box_w,
            box_h,
            transform=ax.transAxes,
            facecolor="white",
            alpha=0.85,
            edgecolor="#bbbbbb",
            linewidth=0.6,
            zorder=9,
            clip_on=False,
        )
    )

    # 首行：现状(GRW) 单柱
    grw_y = y_top - 0.012
    ax.text(
        x0 + lab_w - 0.008,
        grw_y - ch / 2,
        "现状(GRW)",
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=6.5,
        color="#222222",
        zorder=10,
        clip_on=False,
    )
    ax.add_patch(
        Rectangle(
            (x0 + lab_w, grw_y - ch),
            cw,
            ch,
            transform=ax.transAxes,
            facecolor=GRW_COLOR,
            edgecolor="white",
            linewidth=0.4,
            zorder=10,
            clip_on=False,
        )
    )

    # 列标题（时段）
    col_titles = ["2030", "2030\n→2040", "2040\n→2050"]
    title_y = grw_y - (ch + gy)
    for c in range(3):
        cx = x0 + lab_w + c * (cw + gx) + cw / 2
        ax.text(
            cx,
            title_y,
            col_titles[c],
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=5.6,
            color="#333333",
            zorder=10,
            clip_on=False,
        )

    # 行（SSP）：色块 + 标签
    row_y0 = title_y - 0.066
    for r, ssp in enumerate(SSPS):
        ry = row_y0 - r * (ch + gy)
        ax.text(
            x0 + lab_w - 0.008,
            ry - ch / 2,
            SSP_LABELS[ssp],
            transform=ax.transAxes,
            ha="right",
            va="center",
            fontsize=6.5,
            color="#222222",
            zorder=10,
            clip_on=False,
        )
        for c in range(3):
            cx = x0 + lab_w + c * (cw + gx)
            ax.add_patch(
                Rectangle(
                    (cx, ry - ch),
                    cw,
                    ch,
                    transform=ax.transAxes,
                    facecolor=SSP_COLORS[ssp][c],
                    edgecolor="white",
                    linewidth=0.4,
                    zorder=10,
                    clip_on=False,
                )
            )


def plot_figure(
    order,
    segments,
    final_cov,
    grw_arr,
    out_base,
    threshold=60.0,
    margin=5.0,
    sort_desc="按现状覆盖率降序",
    all_formats=False,
):
    n = len(order)
    x = np.arange(n)
    group_w = 0.86
    step = group_w / 4  # 每区 4 根柱：现状 + 3 SSP
    bar_w = step * 0.84

    fig, ax = plt.subplots(figsize=(11.0, 4.4))

    # 交替背景带，辅助区分大区分组
    for i in range(n):
        if i % 2 == 0:
            ax.axvspan(i - 0.5, i + 0.5, color="#f4f4f2", zorder=0)

    # 第 1 根：现状(GRW) 覆盖率（单柱，不堆叠）
    ax.bar(
        x + (0 - 1.5) * step, grw_arr * 100.0, width=bar_w, color=GRW_COLOR, edgecolor="white", linewidth=0.3, zorder=3
    )

    # 后 3 根：各 SSP 时段堆叠柱
    for j, ssp in enumerate(SSPS):
        xpos = x + (j + 1 - 1.5) * step
        base = np.zeros(n)
        for k in range(3):  # 自底向上：2030 / 2040 / 2050
            seg = segments[ssp][:, k] * 100.0
            ax.bar(
                xpos,
                seg,
                bottom=base,
                width=bar_w,
                color=SSP_COLORS[ssp][k],
                edgecolor="white",
                linewidth=0.3,
                zorder=3,
            )
            base += seg

    # 阈值红线（默认 60%）
    ax.axhline(threshold, color="#d62728", lw=1.3, ls="--", zorder=5)
    ax.text(
        n - 0.45,
        threshold + 0.6,
        f"{threshold:.0f}% 阈值",
        color="#d62728",
        ha="right",
        va="bottom",
        fontsize=7.5,
        zorder=6,
    )

    # 坐标轴
    ax.set_ylim(0, 105)
    ax.set_yticks(range(0, 101, 20))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 20)])
    ax.set_ylabel("装机容量覆盖率（被项目区域覆盖）", fontsize=9)
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_xticks(x)
    # 构建带箭头的 x 轴标签：3 SSP 均值 vs 现状(GRW) 相差超过 margin 时加 ↑/↓
    ssp_mean = np.mean([final_cov[ssp] for ssp in SSPS], axis=0) * 100.0
    grw_pct = grw_arr * 100.0
    labels = []
    for i, rid in enumerate(order):
        name = REGION_SHORT_CN[rid]
        if ssp_mean[i] > grw_pct[i] + margin:
            name += "↑"
        elif ssp_mean[i] < grw_pct[i] - margin:
            name += "↓"
        labels.append(name)
    ax.set_xticklabels(labels, fontsize=8.5)
    # SSP1-2.6 的 2050 年覆盖率低于阈值的大区：横坐标名称标红
    ssp126_pct = final_cov["ssp126"] * 100.0
    for tick, sv in zip(ax.get_xticklabels(), ssp126_pct):
        if sv < threshold:
            tick.set_color("#d62728")
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#dddddd", linewidth=0.6, zorder=1)

    ax.set_title("全球 20 大区装机容量覆盖率：现状(GRW) + 3 个 SSP × 时段堆叠" f"（{sort_desc}）", fontsize=10.5, pad=8)

    draw_legend(ax)

    # 留出右侧空间给轴外图例；不用 tight_layout 避免裁剪 clip_on=False 元素
    fig.subplots_adjust(left=0.09, right=0.75, top=0.88, bottom=0.12)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # 默认仅 PNG；--all-formats 时再额外导出 SVG/PDF/TIFF（出版用）
    fig.savefig(f"{out_base}.png", dpi=300, bbox_inches="tight")
    exts = ["png"]
    if all_formats:
        fig.savefig(f"{out_base}.svg", bbox_inches="tight")
        fig.savefig(f"{out_base}.pdf", bbox_inches="tight")
        fig.savefig(f"{out_base}.tiff", dpi=600, bbox_inches="tight")
        exts += ["svg", "pdf", "tiff"]
    plt.close(fig)
    for ext in exts:
        print(f"  -> {out_base}.{ext}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="20 大区：现状(GRW) + 3 SSP 装机容量覆盖率")
    parser.add_argument(
        "--threshold",
        type=float,
        default=60.0,
        help="覆盖率阈值（%%，默认 60）：图中画红线，SSP1-2.6 覆盖率低于该值的大区名称标红",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=5.0,
        help="箭头阈值（百分点，默认 5）：3 SSP 均值与 GRW 现状相差超过该值时加 ↑/↓",
    )
    parser.add_argument(
        "--sort",
        choices=["ssp", "grw"],
        default="ssp",
        help="大区排序：ssp=3 个 SSP 平均 2050 覆盖率降序（默认，原排序）；" "grw=现状(GRW)装机覆盖率降序",
    )
    parser.add_argument("--all-formats", action="store_true", help="额外导出 SVG/PDF/TIFF（默认仅 PNG）")
    args = parser.parse_args()

    print(f"{'=' * 60}\n  20 大区：现状(GRW) + 3 SSP 装机容量覆盖率\n{'=' * 60}")
    order, segments, final_cov, grw_arr = build_segments(sort_by=args.sort)

    # 控制台简报：现状(GRW) 与各 SSP 的 2050 覆盖率
    sort_desc = "现状(GRW)覆盖率降序" if args.sort == "grw" else "3 SSP 平均 2050 覆盖率降序"
    print(f"\n  装机容量覆盖率（按 {sort_desc}）：")
    print(f"  {'大区':<6}{'现状GRW':>9}" + "".join(f"{SSP_LABELS[s]:>10}" for s in SSPS))
    for i, rid in enumerate(order):
        cn = REGION_SHORT_CN[rid]
        vals = "".join(f"{final_cov[s][i]:>9.1%} " for s in SSPS)
        print(f"  {cn:<6}{grw_arr[i]:>8.1%} {vals}")

    out_base = os.path.join(OUTPUT_DIR, "macro_region_cap_coverage_stacked")
    print()
    plot_figure(
        order,
        segments,
        final_cov,
        grw_arr,
        out_base,
        threshold=args.threshold,
        margin=args.margin,
        sort_desc=sort_desc,
        all_formats=args.all_formats,
    )


if __name__ == "__main__":
    main()
