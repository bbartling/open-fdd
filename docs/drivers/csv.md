---
title: CSV
parent: Drivers
nav_order: 5
---

# CSV import

CSV is the primary path for **offline engineering** — import vendor exports without live BACnet/Modbus.

## Formats

Consult the ingest contract for required columns:

```bash
curl -s http://127.0.0.1:8080/api/ingest/contract | jq .
```

Supported shapes include historian-wide CSV and commissioning JSON (separate endpoint).

## Validation

Preflight checks timestamp columns, units, equipment/site IDs, and duplicate keys. Strict mode (`OPENFDD_CSV_STRICT`, default on) rejects execute on `fail` verdict.

## API

| Method | Path |
|--------|------|
| GET | `/api/ingest/contract` |
| POST | `/api/csv/import/preflight` |
| POST | `/api/csv/import/execute` |

## Dashboard

**CSV Fusion** tab (`/csv`) — visual import, wiresheet merge, append/join workflows.

See [CSV import & preview]({{ site.baseurl }}/web-app/csv-import-and-preview.html).
