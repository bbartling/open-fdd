---
title: Plots & reports
parent: Web App
nav_order: 3
---

# Plots & reports

## Plots (`/plot`)

Trend charts from Feather telemetry:

- Select site, equipment, and points
- Optional FDD fault overlays
- Export chart data as CSV

Backed by `/api/timeseries/*` and historian query endpoints.

## Reports (`/reports`)

Model-driven PDF report builder:

1. Create or open a report draft
2. Reorder sections, edit titles
3. Preview content from model, historian, rules, and faults
4. Render and download PDF

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/reports` | List reports |
| POST | `/api/reports/draft` | New draft |
| POST | `/api/reports/{id}/render/pdf` | Generate PDF |
| GET | `/api/reports/{id}/download.pdf` | Download |

Generate from an FDD SQL run:

```http
POST /api/reports/from-fdd-sql-run
```

## Data export (`/exports`)

One-click CSV exports for historian samples, faults, model points, rules, and validation runs — useful before historian purges or for offline analysis.
