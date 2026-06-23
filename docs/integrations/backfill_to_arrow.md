# Backfill to Arrow historian

Open-FDD backfill jobs chunk large time ranges, write normalized rows to:

- `workspace/data/historian/normalized/telemetry.jsonl`
- `workspace/data/historian/normalized/telemetry.arrow` (Arrow IPC snapshot)

## Job fields

Each job records `job_id`, `source_id`, `start_ts`, `end_ts`, chunk size, rows read/written, errors, and output path.

## Start a backfill

```bash
curl -X POST http://127.0.0.1:8080/api/sources/demo_building_json_feed/backfill \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_ts":"2024-01-01T00:00:00Z","end_ts":"2024-01-02T00:00:00Z","chunk_hours":6}'
```

Poll status:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/sources/demo_building_json_feed/backfill/<job_id>
```

## Dedupe

Rows include a stable `dedupe_key` derived from timestamp, source, point, and run id. Re-running overlapping backfills skips duplicates.

## DataFusion

Normalized historian rows register as the `telemetry` table for DataFusion SQL rules. Validate with existing FDD SQL test endpoints after backfill.
