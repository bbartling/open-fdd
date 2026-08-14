---
title: CSV batch import
parent: Web App
nav_order: 2
---

# CSV batch import

CSV loading is **API-only** — no dashboard tab. Use host-side scripts or MCP for batch ingest.

| Step | Method | Path |
|------|--------|------|
| Contract | GET | `/api/ingest/contract` |
| Preflight | POST | `/api/csv/import/preflight` |
| Execute | POST | `/api/csv/import/execute` |

For large CSV analysis and FDD rule development, use the [Pandas cookbook](../rules/cookbook/pandas-cookbook.html) outside Open-FDD.

For daily batch loads, see [CSV batch driver](../drivers/csv-batch.html) and the import sidecar scripts.

Hourly IoT-style appends (after a one-time package seed):

```bash
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"'"$OPENFDD_ADMIN_PASSWORD"'"}' | jq -r '.token // .access_token')"

curl -s -X POST http://127.0.0.1:8080/api/csv/import/package/append \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"confirm":true,"building_id":"BUILDING_50","equipment_id":"AHU_1","csv":"timestamp_utc,sat\n2026-01-01T01:00:00Z,55\n"}'
```

Write your own vendor puller; OpenFDD only merges + re-ingests parquet. Same-hour replay is idempotent (last-write-wins on timestamp).

```bash
./scripts/openfdd_csv_preflight.sh /path/to/file.csv
```
