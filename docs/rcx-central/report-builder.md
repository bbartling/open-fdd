# RCx Report Builder (RCx Central)

## Flow

1. Select saved Edge site
2. Choose date range (2h / 24h / 7d)
3. **Collect Data / Preview** — `POST /api/central/rcx/preview`
4. **Preview Charts** — matplotlib PNG as base64 in browser
5. Select chart/section checkboxes
6. **Generate DOCX** — `POST /api/central/rcx/report`

Reports save to `portfolio/data/reports/` when `save_to_volume=true`.

## Fault overlays

Preview charts include severity-colored bands when fault rows exist and overlay toggle is on.

## DOCX

Uses `open_fdd/reports/rcx_docx.py` when available (selectable sections/charts). Falls back to `portfolio/central/rcx_report.py`.

Read-only safety note is included in every report.
