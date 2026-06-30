# Ingest Contract v1 (Agent Playbook)

Open-FDD does **not** ship site-specific ETL. AI agents clean and reshape data in a **gitignored sandbox**, then submit contract-compliant payloads through a **fail-closed Rust validation gate**.

## Machine-readable contract

```http
GET /api/ingest/contract
```

Returns `historian_wide_csv`, `import_plan`, and `commissioning_bundle` profiles plus FDD input catalog and limits.

## Agent sandbox (not committed)

Use `workspace/agent-toolshed/<job-id>/` for scratch scripts (Python, DuckDB, R, etc.). Nothing in this folder is committed to the Open-FDD repo.

## Workflow

1. **Read contract** — `GET /api/ingest/contract` or MCP `openfdd_ingest_contract`
2. **Clean in toolshed** — pivot long Niagara/TADCO CSVs → wide historian CSV
3. **Preview** — `POST /api/csv/import/preview`
4. **Plan** — `POST /api/csv/import/plan`
5. **Preflight (required)** — `POST /api/csv/import/preflight` → `verdict: "pass"`
6. **Execute** — `POST /api/csv/import/execute` (strict by default; `OPENFDD_CSV_STRICT=0` dev escape)
7. **Commissioning (optional)** — `POST /api/model/commissioning-import`
8. **FDD** — `POST /api/fdd-rules/{id}/test-sql` → `POST /api/rules/batch`
9. **Report** — `POST /api/reports/from-fdd-sql-run`

MCP composite: `openfdd_integration_smoke` orchestrates read steps + optional writes with `confirm: true`.

## Historian wide CSV (primary path)

| Column | Required | Notes |
|--------|----------|-------|
| `timestamp` | yes | RFC3339 or naive local + plan timezone |
| `equipment_id` | recommended | `equip:<slug>` e.g. `equip:liberty-100-ahu-1` |
| `site_id` | recommended | `site:<slug>` |
| FDD value columns | yes (≥1 numeric) | `oa_t`, `sat`, `zn_t`, `duct_t`, `sat_sp`, `fan_cmd`, `occ`, … |

### TADCO / Niagara long → wide mapping (example)

| Source `point_role` | Wide column |
|---------------------|-------------|
| outside air temp | `oa_t` |
| zone temp | `zn_t` |
| discharge air temp | `duct_t` |
| cooling setpoint | `sat_sp` |
| supply air temp | `sat` |
| fan command | `fan_cmd` |
| occupancy | `occ` |

Pivot by `equipment_id` + `timestamp`; one row per timestamp per equipment.

## Commissioning bundle

```json
{
  "sites": [{"id": "site:…", "dis": "…", "site": "M"}],
  "equipment": [{"id": "equip:…", "site_id": "site:…", "equip": "M"}],
  "points": [{"id": "point:…", "equip_ref": "equip:…", "fdd_input": "oa_t"}],
  "assignments": [{"haystack_id": "…", "equip_ref": "…", "fdd_input": "…"}],
  "fdd_rules": [{"rule_id": "…", "name": "…", "sql": "SELECT … fault_raw …"}]
}
```

Import is **fail-closed**: invalid `fdd_input`, duplicate IDs, or unsafe SQL → `{ verdict: "fail", checks: [...] }`.

## Preflight validation codes

| Code | Severity | Meaning |
|------|----------|---------|
| `FILE_QUARANTINED` | error | Parse quarantine on staged file |
| `TIMESTAMP_FAILED` | error | Unparseable timestamps |
| `TIMESTAMP_AMBIGUOUS` | error | DST ambiguity |
| `ROW_COUNT_ZERO` | error | Plan produced no rows |
| `NO_NUMERIC_COLUMNS` | error | No value columns |
| `HISTORIAN_SYNC_EMPTY` | error | Rows but no numeric values to sync |
| `COLUMN_UNKNOWN` | warn | No standard FDD alias |
| `EQUIPMENT_ID_MISSING` | warn | Wide CSV without equipment_id |

## Strict mode

Default: **`OPENFDD_CSV_STRICT` unset or non-zero** → execute rejected unless preflight `verdict == "pass"`.

Dev escape: `OPENFDD_CSV_STRICT=0` on edge (integrator migration only).
