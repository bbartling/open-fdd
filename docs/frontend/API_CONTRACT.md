# Frontend API contract

Dashboard calls the Rust edge HTTP API on the same origin in production (`/` + `/api/*`).

## Dev proxy

Vite (`workspace/dashboard/vite.config.ts`) proxies:

- `/api` → `http://127.0.0.1:8080`
- `/health` → edge
- `/openfdd-agent` → edge

## Core endpoints (existing edge)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness JSON |
| POST | `/api/auth/login` | Operator session |
| GET | `/api/bacnet/driver/tree` | Driver tree (auth) |

Full edge API surface is defined in edge route modules; extend this doc as FDD endpoints are added.

## Planned FDD endpoints (Rust engine integration)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/fdd/rules` | Registry from `sql_rules/registry.yaml` |
| GET | `/api/fdd/rules/{id}/params` | Tuning schema (`control` field per parameter) |
| POST | `/api/fdd/run` | Ad-hoc SQL (`mode` omitted/`sql`) or registry batch (`{"mode":"registry"}`) against Parquet cache |
| GET | `/api/fdd/cache/status` | Ingest / Parquet sidecar status |
| GET | `/api/fdd/roles` | Column role mappings (legacy planned; prefer `/api/fdd/mapping`) |

## Versioned CSV mapping (Phase 1 / #481)

Persists `{workspace}/data/csv_workbench/column_map.json`. Does **not** invent column→role pairs; empty `column_map` is returned until the operator assigns roles. Saving also mirrors roles into legacy `column_mappings.json` for CSV commit paths.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/fdd/mapping?dataset_id=` | Load versioned mapping (or empty scaffold) |
| PUT | `/api/fdd/mapping` | Validate + save `{ mapping: { version, dataset_id, timezone, timestamp_column, equipment, column_map } }` |

Document shape:

```json
{
  "version": 1,
  "dataset_id": "session-or-source-id",
  "timezone": "America/Chicago",
  "timestamp_column": "timestamp",
  "equipment": "equip:ahu-1",
  "column_map": { "OA Temp": "oa_t", "SAT": "sat" }
}
```

Validation: required meta fields; non-empty roles; **no duplicate roles**. UI: `/csv-workbench` → Open mapping.

## ZIP package import (Phase 1 / #481)

Safe `openfdd_package_v1` ZIP inspect/extract under `{workspace}/data/csv_workbench/packages/{package_id}/`. Rejects traversal, absolute paths, symlinks, unsupported types, duplicate/case-colliding paths, excessive entry count, compressed/uncompressed size, and compression-ratio bombs. Caps: `OPENFDD_MAX_ZIP_MB`, `OPENFDD_MAX_UNCOMPRESSED_MB`, `OPENFDD_MAX_ENTRIES` (defaults 500 / 500 / 2000).

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/csv/import/zip/upload` | Store ZIP (`multipart` or JSON `{ filename, content_base64 }`) → `{ package_id }` |
| POST | `/api/csv/import/zip/inspect` | Upload+inspect **or** `{ package_id }` → package manifest (CSV list, equipment folders, weather, mapping status) |
| POST | `/api/csv/import/zip/plan` | `{ package_id }` → stage CSVs into a CSV import session, apply Phase-1 `column_map.json` when valid, draft UT3 plan |

Workflow: ZIP upload → inspect (manifest) → plan (session) → `/api/fdd/mapping` → preflight/execute.

Fixture (tests only): `edge/tests/fixtures/zip_package/tiny_package.zip` — do **not** commit Building 100 data.

See `docs/migration/vibe19/API_CONTRACT.md` for parameter schema (`control`, not `frontend_control`).

## Rules for UI

- No raw SQL editing in operator dashboard.
- Parameter types come from registry + tuning contract.
- Auth required when `OFDD_AUTH_REQUIRED=true`.
- Mapping UI must not silently invent column→role assignments.