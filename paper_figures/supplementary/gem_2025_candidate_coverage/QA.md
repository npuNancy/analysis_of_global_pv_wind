# Figure QA — 2026-11-10

Status: passed after inspecting the complete PNG and both independent panels.

- Both technologies use identical PlateCarree projection and extent.
- All 87,955 retained phases lie within the map extent; original GEM coordinates are plotted.
- Offshore records are absent from the plotted/source-data scope.
- Source IDs are unique within technology; counts exactly reproduce 70,196 / 40,509 solar total/outside and 17,759 / 10,076 wind total/outside.
- Non-boundary grid mappings independently agree with Rasterio's affine transform. Boundary convention is recorded in plot.py.
- The original candidate cache is reduced to a set for membership; duplicated cache rows do not duplicate source phases.
- The complete figure and both independent panels have visible panel letters, titles, record totals, latitude/longitude labels and inside/outside legends. No title/legend clipping or overlaps were observed in the final exports.
- Blue/orange equal-size points; deterministic shuffled drawing order; no coordinate jitter, smoothing, selective removal or capacity sizing.
- Densely co-located phases overlap visually; the CSV retains separate records. No statistical inference, uncertainty interval or biological-replicate claim applies.
- 600 dpi PNG export follows the project's format convention.
- Input/output SHA256 values and the declared rendering settings are recorded in outputs/data_audit.json.
- Scope: descriptive candidate-cache coverage. Formal historical/future siting was not executed.

Scientific mapping update: original candidate IDs have a confirmed float32 boundary/floor defect. Rendering and old-cache counts are reproducible, but they do not establish true suitable-area coverage. See grid_mapping_audit.md.
