"""
Q1 分析：为什么 plot_stations_S0E2 统计的「气象 0/nan 比例(上排)」和
       「容量因子(CF) 0/nan 比例(下排)」不一致。

原始统计（stats_zero_or_nan_NESM3_ssp126_2050.csv）
-------------------------------------------------
  met wind: 12107 bad / 30479 covered = 39.72%   (上排左)
  met solar: 8656 / 27923 = 31.00%               (上排右)
  cf  wind: 13478 / 58943 = 22.87%               (下排左)
  cf  solar: 10721 / 52553 = 20.40%              (下排右)

为何不一致 —— 三条原因（本脚本逐一量化）
----------------------------------------
(1) 分母(覆盖范围)不同【主因】
    气象(bcsd) 仅覆盖 26 国（China / NAM-12 无气象）→ met 分母 = 26 国场站数。
    CF 覆盖 26 国 + China + NAM-12 → cf 分母 ≈ 是 met 的 1.9 倍。
    两个比例的分母不同，直接比较无意义；China/NAM-12 是大陆主体、CF 正常态占绝大多数，
    把 cf 的异常比例显著稀释。

(2) 分子也不同
    cf bad(13478) > met bad(12107)：cf 多覆盖了 China+NAM-12 的异常场站，这些不计入 met。

(3) 「无数据」的编码方式不同【次因，造成同站少量错配】
    气象用 ERA5-Land 自身 NaN 模式表示无数据（bcsd Step6 part.where(mask_src)）。
    CF 先把输入 NaN 用 nan_to_num 清成 0，再用【独立的 global_land_mask】数据库把海洋
    强制设回 NaN。两者海陆掩码来源不同、分辨率不同 → 海岸带存在同站错配
    (气象有值但 CF=NaN，或气象=NaN 但 CF=0)。

本脚本输出：
  q1_decomposition.csv   —— cf bad 按区域(26国/china/NAM)拆分 + 同口径比例对比
  q1_station_agreement.csv —— 26国同站 met-bad vs cf-bad 对应矩阵(量化原因3)
  q1_ratio_compare.png    —— 三种口径 bad 比例对比柱状图
"""
import os
import sys
import csv
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plot_stations_S0E2_zero_or_nan as P  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
YEAR = P.YEAR

font_path = os.path.join(P.PROJECT_ROOT, "data", "SourceHanSansSC-Normal.otf")
if os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    plt.rcParams["font.family"] = [fm.FontProperties(fname=font_path).get_name()]
plt.rcParams["axes.unicode_minus"] = False


def is_bad(vals):
    """与 plot_stations_S0E2.classify 一致：nan 或 ==0 视为 bad。"""
    return np.isnan(vals) | (vals == 0)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"{'='*60}\n  Q1 分析：气象 vs CF 0/nan 比例不一致（{P.MODEL}/{P.SSP}/{YEAR}）\n{'='*60}")

    print("  预加载 NAM 网格 ...")
    P.get_nam_tree()

    csv_path = os.path.join(P.STATIONS_DIR, P.SSP_STATION_FILE[P.SSP])
    stations = P.load_stations_2050(csv_path)

    decomp_rows = []
    agree_rows = []
    compare = {}  # tech -> {met_26, cf_26, cf_total}

    for tech in ("wind", "solar"):
        lon, lat = stations[tech]
        labels = P.assign_regions(lon, lat)
        met_vals = P.query_met(lon, lat, labels, tech)
        cf_vals = P.query_cf(lon, lat, labels, tech)

        m26 = np.isin(labels, P.COUNTRIES_26)
        mchina = labels == "China"
        mnam = labels == "NAM-12"
        mcf = labels != "outside"          # CF 覆盖 = 26国+china+nam

        # —— 原因1+2：分母/分子拆解 ——
        met_cov = int(m26.sum())
        cf_cov = int(mcf.sum())
        met_bad = int((is_bad(met_vals) & m26).sum())           # 仅26国(=S0E2 上排口径)
        cf_bad_total = int((is_bad(cf_vals) & mcf).sum())
        cf_bad_26 = int((is_bad(cf_vals) & m26).sum())
        cf_bad_china = int((is_bad(cf_vals) & mchina).sum())
        cf_bad_nam = int((is_bad(cf_vals) & mnam).sum())
        decomp_rows.append([
            tech, met_cov, cf_cov,
            met_bad, cf_bad_total, cf_bad_26, cf_bad_china, cf_bad_nam,
            f"{met_bad/max(met_cov,1):.4f}",        # 气象 26国比例(=原图上排)
            f"{cf_bad_total/max(cf_cov,1):.4f}",     # CF 全覆盖比例(=原图下排)
            f"{cf_bad_26/max(met_cov,1):.4f}",       # CF 限定26国 与气象同口径比例
        ])

        # —— 原因3：26国同站对应矩阵 ——
        mb = is_bad(met_vals) & m26
        cb = is_bad(cf_vals) & m26
        both_bad = int((mb & cb).sum())
        met_only = int((mb & ~cb).sum())     # 气象bad但CF正常
        cf_only = int((~mb & cb).sum())      # 气象正常但CF bad
        both_ok = int((~mb & ~cb & m26).sum())
        agree_rows.append([tech, int(m26.sum()), both_bad, met_only, cf_only, both_ok,
                           f"{(both_bad)/max(int((mb|cb).sum()),1):.4f}"])
        compare[tech] = {"met_26": met_bad / max(met_cov, 1),
                         "cf_26": cf_bad_26 / max(met_cov, 1),
                         "cf_total": cf_bad_total / max(cf_cov, 1)}

    # 写 decomposition
    h1 = ["tech", "met_cov(26国)", "cf_cov(26+CN+NAM)",
          "met_bad", "cf_bad_total", "cf_bad_26", "cf_bad_china", "cf_bad_nam",
          "met_ratio_26(上排)", "cf_ratio_total(下排)", "cf_ratio_26(同口径)"]
    p1 = os.path.join(OUT_DIR, "q1_decomposition.csv")
    with open(p1, "w", newline="") as f:
        csv.writer(f).writerow(h1); csv.writer(f).writerows(decomp_rows)
    print(f"\n  [分母/分子拆解] -> {p1}")
    for r in decomp_rows:
        print(f"    {r[0]:<6} met_cov={r[1]:>6} cf_cov={r[2]:>6} | "
              f"met_bad={r[3]:>6} cf_bad={r[4]:>6}(26国{r[5]}+CN{r[6]}+NAM{r[7]}) | "
              f"比例: met_26={r[8]} cf_total={r[9]} cf_26={r[10]}")

    # 写 agreement
    h2 = ["tech", "n_26", "both_bad", "met_bad_only", "cf_bad_only", "both_ok", "agreement"]
    p2 = os.path.join(OUT_DIR, "q1_station_agreement.csv")
    with open(p2, "w", newline="") as f:
        csv.writer(f).writerow(h2); csv.writer(f).writerows(agree_rows)
    print(f"\n  [26国同站对应] -> {p2}")
    for r in agree_rows:
        print(f"    {r[0]:<6} both_bad={r[2]:>6} met_only={r[3]:>5} cf_only={r[4]:>5} "
              f"both_ok={r[5]:>6} 一致率={r[6]}")

    # 绘图：三种口径 bad 比例对比
    fig, ax = plt.subplots(figsize=(9, 5.5))
    techs = ["wind", "solar"]
    x = np.arange(len(techs))
    w = 0.26
    labels3 = ["气象·26国\n(原图上排分母)", "CF·26国\n(与气象同口径)", "CF·26国+中国+NAM\n(原图下排分母)"]
    keys = ["met_26", "cf_26", "cf_total"]
    colors = ["#9aa0a6", "#1f77b4", "#d62728"]
    for i, (k, lab, c) in enumerate(zip(keys, labels3, colors)):
        vals = [compare[t][k] * 100 for t in techs]
        bars = ax.bar(x + (i - 1) * w, vals, w, label=lab, color=c)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}%", ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([{"wind": "风电", "solar": "光伏"}[t] for t in techs])
    ax.set_ylabel("0/nan 异常占比 (%)")
    ax.set_title(f"Q1：气象 vs CF 的 bad 比例口径对比（{P.MODEL}/{P.SSP}/{YEAR}）\n"
                 "「CF·26国(同口径)」≈「气象·26国」→ 不一致主因是分母(覆盖范围)不同")
    ax.legend(fontsize=9, loc="upper right")
    ax.set_ylim(0, max(compare[t]["met_26"] for t in techs) * 120)
    plt.tight_layout()
    p3 = os.path.join(OUT_DIR, "q1_ratio_compare.png")
    plt.savefig(p3, dpi=160)
    plt.close()
    print(f"\n  [比例对比图] -> {p3}")
    print("\n  Q1 完成。")


if __name__ == "__main__":
    main()
