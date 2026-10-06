# Fig. 4: climate and deployment counterfactuals

## Figure contract

Test how climate and deployment contributions combine into the paired-path difference, and whether deployment changes the climate response. This is a quantitative six-panel grid: wind left, solar right; all panels use the 2050 capacity snapshot and 2050–2059 annual mean. The interpretation is conditional on the published events and normal-CF baseline.

- **a–b:** nine global climate SSP × station SSP combinations. Cell values are equal-weight means of four model-specific signed net losses per MW; frames identify paired pathways. Both technologies share the absolute color scale.
- **c–d:** symmetric climate and deployment contributions for the global system and the first eight countries in the shared Fig. 3 selection. Positive and negative contributions stack separately; their algebraic sum is the dark diamond. Small dots and the horizontal line show the four model-specific net differences and their minimum–maximum, not a confidence interval. Interaction is already allocated between the two contributions.
- **e–f:** all countries with finite four-model climate contrasts under both deployments and positive SSP126 reference capacity. Both axes are climate 585 minus climate 126; x holds deployment 126 fixed and y holds deployment 585 fixed. Color shows J = y − x. Areas are proportional to SSP126 2050 capacity, with the same scale for both technologies. Grey borders mean fewer than three of four models agree with the nonzero ensemble direction of J. This is direction agreement, not statistical significance. USA, CHN and BRA are labelled; plus signs show the individual models for USA and CHN. Coordinates include every plotted country and displayed model point without clipping.

## Inputs and validation

Reuse the existing `outputs/source_data/panel_ab.csv`, `panel_cd.csv` and `panel_ef.csv`, the shared `prepare/outputs/loss_summary/window.csv.gz`, catalogue capacities, and `prepare/outputs/panel_loss/country_selection.csv`. No upstream product or preparation task is recomputed. The plotting entry point creates only small figure-specific summaries and a coverage extract.

Before rendering, check a representative global wind comparison, the 72 global combination rows, unique model identities, signed net energy/capacity ratios, fixed capacities across climates and models, country contrasts recomputed from the shared combinations, and decomposition closure. The representative cases are United States, China, Brazil, Russia, India, Iran, Kazakhstan and Australia, selected by combined reference capacity; their magnitudes and model agreement are retained in `country_selection_audit.csv`. Global totals retain unassigned/ambiguous stations; the country scatter excludes those non-country classes. China uses the already merged CHN catalogue, including Taiwan.

Common support is fixed across models, climates and all ten years within each station SSP; station IDs are not intersected across different deployments. Missing or zero-capacity comparisons remain undefined and are excluded with explicit reasons. Wind uses the original energy values. The all-event metric is the event union, not a sum of event labels. Finite annual Loss does not demonstrate identical valid timestamps within the year; this remains a limitation of the available annual product.

Station SSP585 retains the upstream source `stations_SSP5-6.0.csv`; the short query label does not imply that the source deployment is SSP5-8.5. Model identities, both SSPs, capacity, snapshot, window, coverage and this source mapping are retained in `model_combinations_coverage.csv`.

## Run

From the repository root on scnet-wuzhen-1866:

```bash
mkdir -p logs/paper_figures/fig04
sbatch paper_figures/main/fig04_climate_deployment/plot.sh
```

The paired SLURM script uses the repository `.venv`, two CPUs and 7 GB on one wzhctest node. It writes stdout and stderr to `logs/paper_figures/fig04/plot_%j.out`.

## Outputs

- `outputs/fig04.png`: full a–f figure, 600 dpi, nominal 183 × 165 mm canvas.
- `outputs/data_audit.json`: scientific checks, coverage, plotted/excluded countries and exclusion reasons.
- `outputs/metadata.json`: input/code SHA256, SLURM job ID, plotting scales, automated checks and visual review.
- `outputs/source_data/panel_*_ensemble.csv`: actual panel means, ranges and model agreement, including excluded scatter cases.
- `outputs/source_data/model_combinations_coverage.csv`: model-resolved combinations with denominators and catalogue coverage.
- `outputs/source_data/country_selection_audit.csv`: shared case selection, contributions, model support and reference capacity.

## Caption

**Climate and deployment contributions to renewable-generation loss in the 2050s.** a,b, Global signed net loss under nine combinations of climate and deployment, averaged across CANESM5, MPI-ESM1-2-HR, MRI-ESM2-0 and BCC-CSM2-MR; outlined diagonal cells denote paired pathways. c,d, Symmetric contributions of climate and deployment to the paired 585 minus 126 path difference for the global system and eight countries selected by reference wind-plus-solar capacity. Diamonds denote the mean net difference; small points and lines denote four models and their range. e,f, Country mean climate contrasts under fixed deployments 126 and 585. The dashed identity line denotes equal climate responses. Color represents interaction J; grey outlines indicate fewer than three models agreeing with the mean direction. Bubble area is proportional to SSP126 reference capacity. All loss metrics are MWh MW⁻¹ yr⁻¹, calculated per model as annual net energy summed over the common valid station set divided by its capacity, then averaged over 2050–2059. No significance test is applied. Missing deployment comparisons are omitted from e,f and explicitly listed in the audit; country counts appear within each panel. Coverage fractions and all underlying model values accompany the figure.
