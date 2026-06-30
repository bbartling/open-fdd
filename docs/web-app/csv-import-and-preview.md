---
title: CSV import & preview
parent: Web App
nav_order: 2
---

# CSV import & preview

Use the **CSV Fusion** tab (`/csv`) or the REST ingest API for engineering imports.

## UI workflow

1. Drop or select CSV files
2. Preview columns and timestamp mapping
3. Run preflight validation
4. Execute import into the Arrow historian

## API workflow

| Step | Method | Path |
|------|--------|------|
| Contract | GET | `/api/ingest/contract` |
| Preflight | POST | `/api/csv/import/preflight` |
| Plan | POST | `/api/csv/import/plan` |
| Execute | POST | `/api/csv/import/execute` |

Execute is **fail-closed**: preflight must return `verdict: pass` (or `warn` when strict mode allows).

## Workbench

Additional CSV tooling:

- `POST /api/csv-workbench/preview` — column preview
- `POST /api/csv-workbench/quality` — data quality checks
- `GET/PUT /api/csv-workbench/column-mappings` — saved mappings

## Shell helper

```bash
./scripts/openfdd_csv_preflight.sh /path/to/file.csv
```

See [Drivers → CSV]({{ site.baseurl }}/drivers/csv.html) for format expectations.
