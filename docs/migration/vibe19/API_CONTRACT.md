# API contract (SQL rules + future React cutover)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Base: FastAPI app in `fdd_app/backend/app.py`. OpenAPI at `/docs`.

## SQL / DataFusion rules (new)

### `GET /api/sql-rules`

Query: `building_id?`, `equipment_id?`

Response:

```json
{
  "ok": true,
  "building": "BUILDING_100",
  "rust_cache_enabled": true,
  "rules": [{
    "rule_id": "VAV-1",
    "description": "...",
    "required_roles": ["zone_t"],
    "parity_status": "near_parity",
    "dashboard_wired": true,
    "parameters": [{ "key": "zone_t_lo", "label": "...", "default": 68.0, "min": 60, "max": 72, "step": 0.5, "unit": "degF", "control": "slider" }],
    "effective_values": { "zone_t_lo": 68.0 },
    "engine": "sql_datafusion"
  }]
}
```

### `POST /api/sql-rules/preview`

Body: `{ "rule_id", "equipment_id", "params": {}, "use_rust_cache": true }`

Returns cached row from last `run-rules` batch or graceful not-available message.

### `POST /api/sql-rules/save-profile`

Body: `{ "rule_id", "scope": "global|building|equipment", "building_id?", "equipment_id?", "params": {} }`

Requires engineer session. Writes YAML under `rule_tuning/`.

## Existing cookbook (unchanged)

- `GET /api/cookbook/catalog`, `/api/cookbook/{page_id}`, `POST /api/cookbook/equipment/{id}` — pandas oracle path with sliders via `params_by_rule`.

## TypeScript interfaces (future React)

See `FRONTEND_REACT_TYPESCRIPT_PLAN.md` for `RuleRegistry`, `RuleParameter`, `RuleTuningProfile`, `RulePreviewRequest`, `RulePreviewResponse`, `ParityStatus`, `EquipmentSummary`.
