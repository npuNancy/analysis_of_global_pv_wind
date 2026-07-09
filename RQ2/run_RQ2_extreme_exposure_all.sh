#!/usr/bin/env bash
set -euo pipefail

# 运行 RQ2 极端暴露相关全部绘图脚本。
# 默认口径：26 个 regional-BCSD 国家、三个 SSP、2030-2060 年。

MODEL="${MODEL:-NESM3}"
SSPS="${SSPS:-ssp126 ssp245 ssp585}"
YEARS="${YEARS:-2030-2060}"
BASELINE_YEARS="${BASELINE_YEARS:-2030-2040}"
FUTURE_YEARS="${FUTURE_YEARS:-2050-2060}"
SOURCES="${SOURCES:-regional_bcsd}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/RQ2/outputs/${MODEL}}"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/RQ2/logs/${MODEL}}"

mkdir -p "${OUT_DIR}" "${LOG_DIR}" /tmp/matplotlib
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/matplotlib}"

echo "[RQ2] model=${MODEL}"
echo "[RQ2] ssps=${SSPS}"
echo "[RQ2] sources=${SOURCES}"
echo "[RQ2] years=${YEARS}"
echo "[RQ2] output=${OUT_DIR}"
echo "[RQ2] logs=${LOG_DIR}"

cd "${ROOT_DIR}"

echo "[RQ2] 1/5 非加权极端暴露时间序列"
python RQ2/plot_RQ2_extreme_exposure_timeseries_unweighted.py \
  --model "${MODEL}" \
  --ssps ${SSPS} \
  --sources ${SOURCES} \
  --years "${YEARS}" \
  --output-dir "${OUT_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_extreme_exposure_timeseries_unweighted.log"

echo "[RQ2] 2/5 容量加权极端暴露时间序列"
python RQ2/plot_RQ2_extreme_exposure_timeseries_capacity_weighted.py \
  --model "${MODEL}" \
  --ssps ${SSPS} \
  --sources ${SOURCES} \
  --years "${YEARS}" \
  --output-dir "${OUT_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_extreme_exposure_timeseries_capacity_weighted.log"

echo "[RQ2] 3/5 容量加权极端暴露率时间序列"
python RQ2/plot_RQ2_extreme_exposure_rate_capacity_weighted.py \
  --model "${MODEL}" \
  --ssps ${SSPS} \
  --sources ${SOURCES} \
  --years "${YEARS}" \
  --output-dir "${OUT_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_extreme_exposure_rate_capacity_weighted.log"

echo "[RQ2] 4/5 不同事件的容量加权极端暴露时间"
python RQ2/plot_RQ2_extreme_exposure_event_area_capacity_weighted.py \
  --model "${MODEL}" \
  --ssps ${SSPS} \
  --sources ${SOURCES} \
  --years "${YEARS}" \
  --output-dir "${OUT_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_extreme_exposure_event_area_capacity_weighted.log"

echo "[RQ2] 5/5 未来期相对基准期的堆叠变化图"
python RQ2/plot_RQ2_extreme_exposure_change_stacked.py \
  --model "${MODEL}" \
  --ssps ${SSPS} \
  --sources ${SOURCES} \
  --baseline-years "${BASELINE_YEARS}" \
  --future-years "${FUTURE_YEARS}" \
  --output-dir "${OUT_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_RQ2_extreme_exposure_change_stacked.log"

echo "[RQ2] done"
echo "[RQ2] figures:"
find "${OUT_DIR}" -maxdepth 1 -type f -name "*.png" | sort
echo "[RQ2] csv:"
find "${OUT_DIR}/csv" -maxdepth 1 -type f -name "*.csv" | sort
