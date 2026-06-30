# JSON API sources

The JSON API driver is an **HTTP/REST source connector** for current-value polling and **bounded** historical backfill when an upstream API supports time windows.

## Responsibilities

- Register independent JSON API sources (URL, headers, auth via secret references)
- Poll on a configured cadence
- Map JSON fields to normalized point samples
- Write historian rows to Arrow/Feather
- Expose source health in the API/UI

## Not responsible for

- Bulk CSV file ingestion → use the **CSV import sidecar**
- Scheduled spreadsheet exports → use the **CSV export sidecar**
- Direct SQL/data-lake backfill → use the **Postgres read-only connector**
- Excel/XLSX generation → tracked separately (issue #367)

All ingestion paths normalize into the same historian schema. DataFusion SQL rules do not depend on which connector produced the rows.

See also: [Import sidecar](../import_sidecar/overview.md), [Export sidecar](../export_sidecar/overview.md).
