---
name: driver-csv-ingest
description: "Builds CSV/TSV ingest into local feather storage with timestamp detection and Grafana-style encodings. Use when drivers include csv or operators import historian exports."
---

# CSV ingest driver

## When to use / When not to use

Use for file upload or path-based CSV ingest into a site shard.

## Prerequisites

- [feather-local-storage](../feather-local-storage/SKILL.md) layout.
- Bridge route `POST /ingest/csv` or `/ingest/csv/upload`.

## Quick start

1. Accept multipart upload or JSON `{ "site_id", "path" }`.
2. Detect encoding (UTF-16 LE BOM, tab-separated Grafana exports).
3. Infer timestamp column; normalize time zones.
4. Write metrics via feather store; return row counts and preview rows.

## Core concepts

Legacy `CsvIngestResult`: rows, dropped_rows, metric_columns, preview_rows.

## Verification

Ingest sample TSV from `open_fdd/tests/fixtures/csv/`; query timeseries endpoint.

## Gotchas

- Large files: stream or chunk if operator requires; legacy read full file.

See [references/REFERENCE.md](references/REFERENCE.md).
