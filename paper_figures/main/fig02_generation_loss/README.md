# Fig. 2 — Global generation loss

Scientific question: how do signed global net losses per MW, paired-pathway differences and event-labelled losses vary between wind and solar?

Six-panel quantitative grid; annual trajectories are the primary evidence.
- a–b: 2030–2059 annual net loss per MW; four-model means and min–max. Lines and bands break at capacity snapshots.
- c–d: within-model SSP245−SSP126 and SSP585−SSP126 differences for three ten-year windows; individual models, means and min–max.
- e–f: 2050–2059 event losses; SSP126 circles, SSP245 squares, SSP585 triangles, ordered by descending SSP126 exposure as in Fig. 1.

Python/matplotlib; 183 × 165 mm, 600 dpi PNG only. Units: MWh MW⁻¹ yr⁻¹. Shared ranges between technologies in each row.

## Inputs and definitions

Reuse accepted outputs/source_data/panel_ab.csv, panel_cd.csv and panel_ef.csv without rewriting. Shared prepare/outputs/event_summary/window.csv.gz supplies event order; catalogues/capacity_by_country.csv supplies coverage. No dependency on other figures' output.

Net loss is summed signed energy divided by capacity of the same valid stations. Common support is fixed across models, climate SSPs, events and ten years within each deployment snapshot. Event denominators include all valid capacity. The all-event union is read directly; overlapping event labels are not added. Wind uses original values.

Each pathway pairs climate and deployment SSP; differences include both effects. station_ssp585 uses stations_SSP5-6.0.csv. Four models are equally weighted. Ranges describe model spread, not confidence intervals. Annual Loss support does not establish identical valid three-hourly timestamps.

## Run

From the remote repository root:

```bash
bash paper_figures/main/fig02_generation_loss/plot.sh
```

The wrapper creates logs before submission. The compute job activates the repository environment, audits inputs, supplements only display/coverage tables and renders outputs/fig02.png. Data audit, metadata, caption and separate visual review accompany the PNG.

Review focuses on signed values, snapshot boundaries, within-model pairing, event overlap, coverage and deployment semantics.
