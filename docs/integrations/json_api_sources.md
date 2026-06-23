# JSON API sources

Open-FDD supports multiple independent JSON API connectors through the source registry (`workspace/connectors/registry.json`).

## Configure a source

1. Copy an example from `examples/connectors/*.example.toml`.
2. Save private overrides under `workspace/connectors/local/<source_id>.local.toml` (gitignored).
3. Store bearer tokens and passwords in `workspace/secrets/openfdd-secrets.local.env` using secret references such as `auth.secret_ref = "DEMO_JSON_BEARER_TOKEN"`.
4. Register the source in `workspace/connectors/registry.json` or `POST /api/sources` (integrator/agent).

## Supported capabilities

- Multiple JSON API sources active simultaneously
- JSON shapes: `array`, `flat`, `nested`
- JSON path mappings for timestamp, value, units, and quality
- Current-value polling into normalized Arrow/JSONL historian
- Historical backfill when endpoints expose time-range parameters (chunked jobs)

## Demo mode

When `OPENFDD_CONNECTOR_DEMO_MODE=1` or no secret is configured, Open-FDD reads sanitized fixtures from `examples/connectors/` instead of calling live URLs. This keeps CI and local dev free of proprietary data.

## Validate

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/sources
curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/sources/demo_building_json_feed/poll-once
```

Export CSV for Excel review:

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/export/historian.csv -o historian.csv
```
