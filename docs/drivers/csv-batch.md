---
title: CSV batch import
parent: Drivers
nav_order: 5
---

# CSV batch import

CSV is a **headless batch driver** — load pre-shaped telemetry into the historian for DataFusion FDD. Large CSV analysis, merges, and RCx studies belong in the [Pandas cookbook](../rules/cookbook/pandas-cookbook.html) outside the edge app.

## Workflow

1. Prepare CSV off-box (pandas, vendor export, or daily API pull script on the host OS).
2. Drop files into a watched directory or call the import API directly.
3. Preflight validates timestamps, columns, and duplicates (fail-closed).
4. Execute writes Arrow/Feather historian rows with `source_driver: csv`.

## API

| Method | Path |
|--------|------|
| GET | `/api/ingest/contract` |
| POST | `/api/csv/import/preflight` |
| POST | `/api/csv/import/execute` |

Execute requires preflight `verdict: pass` (or `warn` when strict mode allows).

## Host batch (daily pull example)

```bash
# 1) Host script fetches CSV (cron) — outside Open-FDD
curl -fsS -o /data/incoming/site-a-$(date +%F).csv "$EXTERNAL_API_URL"

# 2) Sidecar or integrator calls preflight + execute
./scripts/openfdd_csv_import_sidecar.sh
```

See [import sidecar overview](../archive/import_sidecar/overview.md) for directory layout and profiles.

## Validation (Rust)

Preflight checks include:

- Timestamp column detection and parse quality
- Duplicate keys and row counts
- Equipment/site ID presence
- Unit and column mapping sanity

Bad timestamps or failed preflight **block** execute — no partial historian writes.
