# Fig. 5 — Residual loss under SSP126

The figure tests whether residual SSP126 loss and paired-path differences identify different national priorities. Panels a (wind) and b (solar PV) form a quantitative grid, 183 mm wide and approximately 103 mm high, exported only as 600 dpi PNG.

- x: equal-weight four-model mean SSP126 climate × SSP126 deployment net loss in 2050–2059, using the 2050 capacity snapshot.
- y: mean of within-model SSP585 climate × SSP585 deployment minus SSP126 climate × SSP126 deployment losses. Both axes use MWh MW⁻¹ yr⁻¹ and retain signed values.
- Circle area: SSP126 2050 catalogue capacity in GW, one scale across technologies.
- Colour: at least three of four models agree with the nonzero mean path difference; other complete cases are hollow grey.
- Vertical line: pre-established P75 of country-equal four-model mean SSP126 loss in 2030–2039 in the fixed early/late population. Horizontal line: zero path difference.
- Labels: eight Fig. 4 explanation countries from shared selection. Crosses: the four individual models for the two largest reference-capacity countries, USA and China.

## Input audit

Both panels already have model-resolved R126, R585, D, capacity, categories and thresholds in `outputs/source_data/panel_ab.csv`. Shared `panel_loss/residual_thresholds.csv` supplies the fixed lists (147 wind, 149 solar) and thresholds (129.45283084495588 and 96.76119105865192). No raw-product preparation is rerun.

`plot.py` checks these inputs against accepted shared summaries, reproduces the thresholds, and verifies normalization and coverage. Missing figure-specific tables are written to `outputs/source_data/`: countries, paired windows, annual coverage, threshold population, thresholds, excluded countries, and country labels. Inputs and source hashes, numerical checks and sample counts are recorded in `outputs/metadata.json`. The original panel input remains unchanged.

Country aggregation reuses the accepted China–Taiwan union and common station support within each deployment. Values preserve native-calendar annual sums and ten-year averaging. Wind energy is unscaled; all-event union is used directly. Missing comparisons and countries outside the pre-established common early/late population are documented separately.

These are descriptive comparisons with four equally weighted GCMs. Direction agreement is not significance. The axes are mathematically coupled; no regression is fitted. Thresholds are relative comparisons, not reliability limits. Station SSP5-6.0 remains mapped to the formal SSP585 label.

## Run

From the remote repository root:

```bash
bash paper_figures/main/fig05_residual_loss/plot.sh
```

The wrapper creates logs and submits to wzhctest (one node, two CPUs, 7 GB), using the repository .venv. All analysis and drawing run on the compute node. The first check validates a representative country/model before full panel verification.

Output: `outputs/fig05.png`. Figure legend: `caption.md` (also delivered in `outputs/caption.md`). Visual inspection: `outputs/visual_qa.json`.
