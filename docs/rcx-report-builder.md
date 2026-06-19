# RCx Report Builder

The **RCx Report Builder** (`/analytics/rcx`) collects a read-only snapshot from the edge bridge and generates a Word document.

## Workflow

1. Choose report window (2 h / 24 h / 7 d).
2. Click **Collect Data / Preview** — calls `POST /api/reports/rcx/preview`.
3. Review available vs disabled charts (disabled charts show missing point roles or no fault data).
4. Select sections and charts.
5. Click **Generate DOCX** — `POST /api/reports/rcx/generate` returns `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

## Implementation

- Preview/readiness: `workspace/api/openfdd_bridge/rcx/chart_preview.py`
- Placeholder hints (BRICK roles → columns → paste instructions): `open_fdd/reports/rcx_placeholders.py`
- DOCX builder: `open_fdd/reports/rcx_docx.py`
- Charts: `open_fdd/reports/charts.py` (matplotlib → BytesIO, no temp PNGs)

Each DOCX placeholder includes system type (AHU/VAV/zone/plant), historian column names from the BRICK model, and disabled-chart gaps in the appendix. FDD rule sections list bound sensor columns per Rule Lab assignment.

## Safety

Report generation is **read-only**. No BACnet writes, commands, overrides, or setpoint changes.

## Dependencies

Bridge API requires `python-docx` and `matplotlib` (see `workspace/api/requirements.txt`).

## Central vs edge

Portfolio Central (`portfolio/central/rcx_report.py`, port 8060) supports multi-site rollups. The edge builder uses local FDD results and building status for single-site RCx exports from the operator UI.
