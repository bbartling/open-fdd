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

```bash
./scripts/openfdd_csv_preflight.sh /path/to/file.csv
```
