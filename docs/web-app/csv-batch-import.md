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

### AFDD routine after append (real-world pattern)

After each append (or on a schedule), operators tune rules and re-run FDD:

```bash
# Update rule params (confirm_min, etc.)
curl -s -X PUT http://127.0.0.1:8080/api/fdd/session-config \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"schema_version":"openfdd_session_v1","params":{"VAV-1":{"confirm_min":1200}}}'

# Run registry for one building
curl -s -X POST http://127.0.0.1:8080/api/fdd/run \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"mode":"registry","building_id":"BUILDING_50","rule_ids":["VAV-1","ECON-1"]}'
```

**Bench orchestrator:** [`scripts/csv_flood_afdd_routine_sim.py`](../../scripts/csv_flood_afdd_routine_sim.py) with [`scripts/fixtures/b50_afdd_routine.json`](../../scripts/fixtures/b50_afdd_routine.json) — see [CSV flood + AFDD routine](../agent/CSV_FLOOD_AFDD_ROUTINE.md).

```bash
./scripts/openfdd_csv_preflight.sh /path/to/file.csv
```
