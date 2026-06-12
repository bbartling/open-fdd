# Dashboard analytics

Engineering analytics pages live under **Analytics** in the operator dashboard (`/analytics`).

## Pages

| Route | Purpose |
|-------|---------|
| `/analytics` | Overview KPIs, fault-hour charts, top faults table |
| `/analytics/faults` | Time-range fault analytics |
| `/analytics/equipment` | AHU / VAV fault-hour summary |
| `/analytics/health` | BACnet / BRICK model health |
| `/analytics/rcx` | RCx Report Builder (preview + DOCX download) |

## API (read-only)

- `GET /api/analytics/overview`
- `GET /api/analytics/faults?hours=24`
- `GET /api/analytics/model-health`
- `POST /api/reports/rcx/preview`
- `POST /api/reports/rcx/generate` → DOCX download

## Fault hours

Elapsed fault hours are estimated from FDD batch run `analytics.estimated_fault_duration_sec` when present, otherwise from flagged/total sample ratio. See `open_fdd/reports/fault_hours.py`.

## Theme

All Plotly charts use `getPlotlyThemeLayout(theme)` from `workspace/dashboard/src/lib/plotly-theme.ts`.

## Tests

```bash
pytest tests/workspace_bridge/test_dashboard_analytics.py open_fdd/tests/test_fault_hours.py
cd workspace/dashboard && npm test
```

Live BACnet is not required. Gate live ACME validation with `OPENFDD_LIVE_ACME=1`.
