# Fault list and analytics

## UI

Use the **Fault catalog** page (`/faults`) and home dashboard fault cards. Filter by site, family, severity, and status.

## API

| Route | Description |
|-------|-------------|
| `GET /api/faults` | All fault records |
| `GET /api/faults/:fault_id` | Single fault detail |
| `GET /api/faults/summary` | Counts: raw, confirmed, active, cleared |
| `GET /api/faults/export.csv` | CSV export (auth required) |
| `GET /api/faults/status` | Dashboard fault families + traffic light |

Fault records include rule SQL inputs, latest values, minutes in fault, confirmation window, and timestamps (`first_seen_at`, `last_seen_at`, `cleared_at`).

## Status values

- `raw` — condition true, not yet confirmed
- `confirmed` — persisted beyond confirmation minutes
- `cleared` — condition no longer active

Export for spreadsheets: `GET /api/faults/export.csv` or legacy `GET /api/export/faults.csv`.
