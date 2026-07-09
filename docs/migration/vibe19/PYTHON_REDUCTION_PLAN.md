# Python reduction plan

Inventory of Python modules in vibe19 with migration target. **Do not delete** until SQL/Rust parity is documented and tests pass.

**Counts:** 50 cookbook rules in pandas · 8 SQL rules ported · 42 rules remain pandas-only (stage 1)

## Backend (`fdd_app/backend/`)

| File | Current purpose | Pandas? | Rules / calcs | Migration target | Decision | Blocker | Test before removal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cookbook_rules.py` | Canonical 50-rule catalog + compute fns | Yes | All FC/ECON/VAV/SV rules | SQL (`sql_rules/`) + keep defs for oracle | Keep (oracle) | 42 rules not yet SQL | Parity per rule ID |
| `cookbook_engine.py` | Role resolution, confirm_fault, charts | Yes | Rule execution orchestration | Rust role map + SQL batch | Keep temporarily | Haystack resolver | `test_cookbook.py` |
| `cookbook_kpi.py` | Index KPI rollups from cookbook | Yes | SCHED-1, fault hours summary | SQL rollups | Keep temporarily | Depends on engine | `test_cookbook.py` |
| `generate_dashboard.py` | Legacy HTML + inline fault masks | Yes | Inline FC masks, motor stats, zone rollups | SQL + thin report glue | Keep temporarily (oracle) | Large file, chart glue | Dashboard smoke |
| `economizer_fdd_engine.py` | Legacy economizer diagnostics | Yes | ECON-* overlap | SQL ECON rules | Delete after parity | Duplicates cookbook | `test_economizer_diagnostics.py` |
| `sensor_qa_engine.py` | Legacy sensor QA | Yes | SV-* overlap | SQL SV rules | Delete after parity | Duplicates cookbook | `test_sensor_qa.py` |
| `economizer_diagnostics_page.py` | Page wrapper for economizer | Light | Page assembly | Keep (glue) | Keep temporarily | Uses legacy engines | Page smoke |
| `analytics_motors.py` | Motor runtime / excess hours | Yes | MOTOR-*, fan hours | SQL `fan_runtime_hours.sql` | Port to SQL | Oracle compare | `test_analytics_rollups.py` |
| `analytics_rollups.py` | Zone/plant summary stats | Yes | avg/min/max, comfort % | SQL + DuckDB pattern | Port to SQL | Partial DuckDB exists | `test_analytics_rollups.py` |
| `duckdb_rollups.py` | DuckDB analyst rollups | Optional pandas | Zone comfort %, OAT bins | DataFusion SQL (prod) | Keep temporarily | Analyst/debug path | `test_duckdb_rollups.py` |
| `motor_runtime_cache.py` | Batch motor runtime cache | Yes | Fan/pump hours | SQL + Rust ingest | Port to SQL | Cached pandas path | Motor tests |
| `fault_disk_cache.py` | Disk cache for cookbook results | No pandas | Cache layer | Rust result cache | Keep temporarily | Oracle cache | `test_fault_disk_cache.py` |
| `dashboard_cache.py` | HTML/context cache | Light | Cache only | Keep (glue) | Keep | — | `test_page_registry.py` |
| `dashboard_params.py` | Tunable rule params | No | Param schema | Keep (glue) | Keep | — | Occupancy tests |
| `app.py` | FastAPI routes | Light | API glue | Keep (glue) | Keep | — | `test_api_mode.py` |
| `api_models.py` | Pydantic API schemas | No | — | Keep (glue) | Keep | — | API tests |
| `paths.py` | Path helpers | No | — | Keep (glue) | Keep | — | — |
| `page_registry.py` | SPARQL nav / pages | No | — | Keep (glue) | Keep | — | `test_page_registry.py` |
| `package_dashboard.py` | Client zip packaging | No | — | Keep (deploy) | Keep | — | — |
| `build_docker_deploy.py` | Docker deploy helper | No | — | Keep (deploy) | Keep | — | — |
| `engineer_auth.py` | PIN auth | No | — | Keep (glue) | Keep | — | `test_engineer_auth.py` |
| `notes_store.py` | Analyst notes | No | — | Keep (glue) | Keep | — | `test_notes_units.py` |
| `units.py` | Unit conversion | No | — | Keep (glue) | Keep | — | `test_notes_units.py` |
| `ml_lab.py` | ML experiment UI | Yes | sklearn workflows | Keep (ML) | Keep | By design | `test_ml_lab.py` |
| `rules/registry.py` | Custom rule plugin registry | Light | Plugin discovery | Keep (ML/custom) | Keep | — | `test_ml_lab.py` |
| `rules/base.py` | Plugin base types | No | — | Keep (ML/custom) | Keep | — | — |
| `rules/plugins/ml_oat_residual.py` | ML OAT residual | Yes | Custom ML | Keep (ML) | Keep | By design | ML tests |
| `rules/plugins/ml_sat_linear_residual.py` | ML SAT residual | Yes | Custom ML | Keep (ML) | Keep | By design | ML tests |
| `rules/plugins/custom_sat_hunting.py` | Custom hunting rule | Yes | FC4 variant | Keep (ML/custom) | Keep | Complex state machine | Plugin tests |

## Sidecar (`fdd_app/sidecar/`)

| File | Purpose | Decision | Migration |
| --- | --- | --- | --- |
| `historian_export.py` | Logical pivot export for open-fdd | Keep temporarily | Align with Rust Parquet role columns |
| `cookbook_sidecar.py` | HTTP bridge to open-fdd edge | Keep temporarily | Optional: call `fdd_cli run-rules` |
| `cookbook_sql.py` | Dual-backend SQL (5 rules) | Port to `sql_rules/` | Merge registries |
| `cookbook_rules_sql.yaml` | Sidecar SQL catalog | Port to `sql_rules/registry.yaml` | Unify |

## Haystack RDF (`haystack_rdf/`)

| File | Purpose | Decision | Migration |
| --- | --- | --- | --- |
| `feather_cache.py` | CSV→Feather cache | Keep temporarily | Parquet via `fdd_store` |
| `csv_bootstrap.py` | RDF model from CSV | Keep | See Oxigraph eval |
| `model_sparql.py` | SPARQL queries | Keep | Cache hot paths |
| `resolver.py` | Point role resolution | Keep temporarily | Rust role map or cached JSON |
| `fastapi_routes.py` | `/api/rdf/*` | Keep (glue) | — |
| Other `haystack_rdf/*` | Model store, TTL, grid | Keep | — |

## Deletion candidates (confirmed dead)

| Path | Status |
| --- | --- |
| `csv_fdd_dashboard/` | **Deleted** — legacy duplicate of `fdd_app/` (only `server_run.log` may remain if locked by a process) |
| Generated `*.html`, `plotly.min.js` in repo | Deleted / gitignored |

## Policy going forward

- **No new standard FDD rules in pandas** without a row in [`PANDAS_TO_SQL_RULE_MIGRATION.md`](PANDAS_TO_SQL_RULE_MIGRATION.md) explaining why SQL is blocked.
- **ML / custom plugins** stay in `fdd_app/backend/rules/plugins/`.
- **Dashboard glue** stays Python until report generation reads SQL/Parquet outputs.
