# Global metric trends

Scientific question: how do capacity, extreme-event exposure, net losses and CF-based generation change along the three SSP pathways? No pathway ranking is assumed.

Eleven complete 1 × 3 triptychs, ordered wind + solar, wind, solar. Python/matplotlib exports only full 600 dpi PNG figures (240 × 85 mm); no separate panels. SSP colours follow project configuration. Grid exposure, suitable-grid exposure/loss, station loss fraction and unit-capacity generation use independent panel y-axis ranges with visible ticks. The other six figures share y-axis ranges. Tick intervals are specified by PANEL_Y_STEPS in plot.py and recorded with axis limits in results_manifest.json.

## Execution

From the 1866 repository root:

```bash
mkdir -p logs/paper_figures/global_metric_trends
bash paper_figures/supplementary/global_metric_trends/prepare_union.sh
# After cache reduction finishes:
source .venv/bin/activate
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m paper_figures.supplementary.global_metric_trends.plot \
  > logs/paper_figures/global_metric_trends/plot_direct.out 2>&1
```

The union reducer runs on a compute node (8 CPUs / 28 GB, at most 4 workers), with a representative patch checked first. It reads accepted annual grid caches, not raw three-hour signals. The plotting script only reads small summary tables and runs directly on the login node; plot.sh is supplied for optional SLURM execution.

## Computation and conventions

- Capacity: sum country catalogue capacities by technology, SSP and snapshot; total snapshots, not cumulative additions.
- Exposure: three complete decade means (2030–2039, 2040–2049, 2050–2059).
- Combined grid exposure: time union of both technologies, not a pooled technology-area average. Reused caches retain five wind and six solar labels and pair solar t with wind t+1.5 h as the same 3-hour interval, attributing the interval to the solar year.
- Suitable combined exposure: spatial union of suitable cells; area counted once. Singly suitable cells use only that technology; doubly suitable cells use the cross-technology time union. Missing values are not zero; common support is fixed across four models, three SSPs and all 30 years.
- Station exposure total: sum capacity × annual event days, MW days/year. Mean exposure: this total / matching valid capacity, days/year. Combined exposure pools technology station portfolios, not a global time-axis union across distinct locations.
- Suitable loss: 1 MW per technology-grid, equal technology-grid weights; no area weighting. Both technologies at one coordinate represent two 1 MW objects.
- Station losses: signed net event-union energy. Loss fraction: 100 × net loss / annual NORMAL baseline generation, not actual generation or event-period generation.
- Generation: capacity × annual CF × native-calendar year hours on fully observed station-years. Valid capacities match the loss tables.
- Capacity uses the full catalogue; other station denominators use their valid support. Missing stations are not extrapolated.
- Wind energy is not rescaled. Station SSP585 deployment derives from SSP5-6.0.
- Annual station metrics use the 2030/2040/2050 deployment snapshot for the respective decade; slopes describe paired climate/deployment pathways.

## Statistics and source data

Metrics are calculated per model before equal averaging over four GCMs. Capacity has one deterministic catalogue value, not artificial model replicates. Lines show means; min/max and model counts are saved in display CSVs.

Each annual graph has one OLS dashed line per SSP per panel over 30 ensemble-mean values: y = a + b(year − 2030). No significance claim. Decadal graphs have three connected points. Six annual graphs × three technologies × three SSPs = 54 fits.

Each figure has outputs/source_data/<name>_models.csv and <name>_display.csv; annual figures also have <name>_fits.csv. grid_union_annual.csv, grid_union_decadal.csv and grid_union_coverage.csv document new union summaries. union_patches/ preserves patch numerators, denominators and provenance.

outputs/input_provenance.json records input hashes; results_manifest.json maps all metrics to sources and products; figure_contract.json records the visual/statistical contract. union_validation.json and validation.json contain machine checks. Visual inspection is recorded separately after rendering.

The complete Chinese inventory and result paths are in [document/风电光伏数据.md](../../../document/风电光伏数据.md).

## LCOE paired capacity and exposure

Three additional complete triptychs use station/climate pairs 126/126, 245/245 and 560/585. They ask how deployment capacity and event exposure vary across paired pathways, with the same wind + solar / wind / solar columns and shared y-axis convention as the original inventory.

`prepare_lcoe.py` reads the released 1959 Extreme index and paired Loss archives. Capacity uses the complete 2030/2040/2050 LCOE catalogues. Exposure uses the corresponding Loss four-model, 30-year common station cohort; the reducer independently requires at least 99% jointly valid event time for every station-year. It counts the time union of five wind or six solar events, preserves native calendars, and never extrapolates missing time. The combined portfolio adds capacity-event numerators and valid capacities across technologies. Per-model annual and decadal tables retain both scenario labels and coverage. Four models are equally averaged only after the per-model decade mean.

From the 1866 repository root:

```bash
mkdir -p logs/paper_figures/global_metric_trends
bash paper_figures/supplementary/global_metric_trends/prepare_lcoe.sh --pilot
# After the pilot passes:
bash paper_figures/supplementary/global_metric_trends/prepare_lcoe.sh
# After preparation passes, small-table plotting runs on the login node:
source .venv/bin/activate
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m paper_figures.supplementary.global_metric_trends.plot_lcoe
```

Preparation requests 8 Slurm cores / 28 GB and starts four worker processes. The plotting entry point also updates the top inventory row and appends the three figures to `document/风电光伏数据.md` and `.html`; Markdown links PNG files, while HTML embeds the same PNG bytes as base64. Only complete triptychs are exported. Existing inventory figures are preserved.

Outputs: `lcoe_station_capacity.png`, `lcoe_station_exposure_total.png`, `lcoe_station_exposure_mean.png`; source tables are `outputs/source_data/lcoe_*.csv`. `lcoe_exposure_validation.json` records calendar/coverage/conservation checks and indexed input hashes; `lcoe_figure_manifest.json` records figure sizes, text bounds and output hashes. Full source metadata and patch summaries remain in the remote output directory.
