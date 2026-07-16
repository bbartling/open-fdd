# Frontend API contract

Dashboard calls the Rust edge/central HTTP API on the same origin in production (`/` + `/api/*`).

## Dev proxy

Vite (`workspace/dashboard/vite.config.ts`) proxies:

- `/api` → `http://127.0.0.1:8080`
- `/health` → edge
- `/openfdd-agent` → edge

Standalone stack UI (Caddy) reverse-proxies `/api*` → `central:8080`.

## Core endpoints (existing)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness JSON |
| POST | `/api/auth/login` | Operator session |
| GET | `/api/auth/status` | Whether auth is required |
| GET | `/api/bacnet/driver/tree` | Driver tree (auth) |

## FDD registry endpoints (Rust engine)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/fdd/rules` | Registry from `sql_rules/registry.yaml` |
| GET | `/api/fdd/rules/{id}/params` | Tuning schema (`control` field per parameter) |
| POST | `/api/fdd/run` | Execute registry rules — `{ "mode": "registry", "rule_ids": [...], "params": {...} }` only. **Raw SQL is rejected** (integrator SQL lab: `/api/rules`). |
| GET | `/api/fdd/cache/status` | Parquet ingest / results status |
| GET | `/api/fdd/roles` | Column role mappings |
| GET | `/api/fdd/status` | Registry count + rules dir |

Env:

- `OPENFDD_SQL_RULES_DIR` (default `/app/sql_rules` in images)
- `OPENFDD_PARQUET_ROOT` (default `.cache/parquet`)
- `OPENFDD_RULE_RESULTS_DIR` (default `.cache/rule_results`)

See `docs/migration/vibe19/SQL_RULE_TUNING_CONTRACT.md` for parameter schema (`control`, not only `frontend_control`).

## Rules for UI

- No raw SQL editing in operator dashboard.
- Parameter types come from registry + tuning contract.
- Auth required when JWT secret / `OFDD_AUTH_REQUIRED` is set.
