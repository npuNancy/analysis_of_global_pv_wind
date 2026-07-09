#!/usr/bin/env bash
set -euo pipefail

# 运行 RQ2.1 高风险转变相关全部绘图脚本。
# 默认口径：
#   - 模式：NESM3
#   - 数据源：regional_bcsd
#   - SSP：ssp126 / ssp245 / ssp585
#   - 年份：2030 / 2040 / 2050
#   - 高风险阈值：2030 年 2030 cohort 风险分布的容量加权 P80
#
# 输出结构：
#   - 图件：RQ2/outputs/${MODEL}/fig_RQ2_1_*.png
#   - CSV： RQ2/outputs/${MODEL}/csv/RQ2_1_*.csv
#   - 日志：RQ2/logs/${MODEL}/plot_RQ2_1_*.log

MODEL="${MODEL:-NESM3}"
SSPS="${SSPS:-ssp126 ssp245 ssp585}"
SOURCES="${SOURCES:-regional_bcsd}"
YEARS="${YEARS:-2030 2040 2050}"
BASELINE_YEAR="${BASELINE_YEAR:-2030}"
COHORT_YEAR="${COHORT_YEAR:-2030}"
HIGH_RISK_QUANTILE="${HIGH_RISK_QUANTILE:-0.8}"
TARGET_YEAR="${TARGET_YEAR:-2050}"
TOP_N="${TOP_N:-14}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/RQ2/outputs/${MODEL}}"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/RQ2/logs/${MODEL}}"

mkdir -p "${OUT_DIR}" "${OUT_DIR}/csv" "${LOG_DIR}" /tmp/matplotlib
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/matplotlib}"

COMMON_ARGS=(
  --model "${MODEL}"
  --ssps ${SSPS}
  --sources ${SOURCES}
  --years ${YEARS}
  --baseline-year "${BASELINE_YEAR}"
  --cohort-year "${COHORT_YEAR}"
  --high-risk-quantile "${HIGH_RISK_QUANTILE}"
  --output-dir "${OUT_DIR}"
)

echo "[RQ2.1] model=${MODEL}"
echo "[RQ2.1] ssps=${SSPS}"
echo "[RQ2.1] sources=${SOURCES}"
echo "[RQ2.1] years=${YEARS}"
echo "[RQ2.1] high-risk threshold=P$(python - <<PY
print(int(float("${HIGH_RISK_QUANTILE}") * 100))
PY
) of ${BASELINE_YEAR} ${COHORT_YEAR} cohort"
echo "[RQ2.1] output=${OUT_DIR}"
echo "[RQ2.1] logs=${LOG_DIR}"

cd "${ROOT_DIR}"

echo "[RQ2.1] 1/4 2030 cohort 风险轨迹"
python RQ2/plot_RQ2_1_cohort_risk_trajectory.py "${COMMON_ARGS[@]}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_1_cohort_risk_trajectory.log"

echo "[RQ2.1] 2/4 2030 cohort 高风险转变"
python RQ2/plot_RQ2_1_cohort_transition.py "${COMMON_ARGS[@]}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_1_cohort_transition.log"

echo "[RQ2.1] 3/4 新增场站高风险容量比例"
python RQ2/plot_RQ2_1_newbuild_highrisk_share.py "${COMMON_ARGS[@]}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_1_newbuild_highrisk_share.log"

echo "[RQ2.1] 4/4 国家尺度热图"
python RQ2/plot_RQ2_1_country_heatmap.py "${COMMON_ARGS[@]}" \
  --target-year "${TARGET_YEAR}" \
  --top-n "${TOP_N}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_1_country_heatmap.log"

echo "[RQ2.1] done"
echo "[RQ2.1] figures:"
find "${OUT_DIR}" -maxdepth 1 -type f -name "fig_RQ2_1_*.png" | sort
echo "[RQ2.1] csv:"
find "${OUT_DIR}/csv" -maxdepth 1 -type f -name "RQ2_1_*.csv" | sort
