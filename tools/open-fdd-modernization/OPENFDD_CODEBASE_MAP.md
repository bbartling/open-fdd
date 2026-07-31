# Open-FDD Codebase Map for the Modernization

Snapshot basis: `bbartling/open-fdd` commit
`d56ec14b0f3f92846d664034f50d12803a45ce6e`.

This is an orientation map, not a substitute for call-site inspection at the
implementation commit.

## Repository instruction and architecture truth

| Path | Current role | Required modernization action |
| --- | --- | --- |
| `AGENTS.md` | Container stack, central/UI/fieldbus/MQTT ownership, safety | Add approved React/Rust future state without weakening operations |
| `services/ui/AGENTS.md` | Locks Streamlit UX and DataFusion-via-central execution | Supersede Streamlit-only/“no React” instruction after ADR |
| `services/fieldbus/AGENTS.md` | BACnet socket/write/server rules | Preserve; Phase 3 work must obey it |
| `openfdd_agent_spec/AGENTS.md` | Engineering agent OS and current Python oracle policy | Reconcile the new runtime-exit decision and preserve history |
| `openfdd_agent_spec/MILESTONE_A.md` | Prior unified-library/oracle program | Treat as completed/parallel historical architecture, not Phase 1 |
| `openfdd_agent_spec/DATA_CONTRACT.md` | Existing portable artifact guidance | Extend/replace with Rust-owned browser contracts |
| `docs/architecture/index.md` | Current Streamlit container stack index | Update as milestones become true |
| `docs/architecture/datafusion-first.md` | SQL-first/pandas policy | Keep SQL-first; tighten runtime Python prohibition |
| `docs/architecture/job-workspaces.md` | Durable job source of truth and revisions | Preserve semantics; React consumes central directly |
| `docs/web-app/index.md` | Declares one Streamlit app, not React | Supersede after ADR and update at default cutover |
| `docs/web-app/routes.md` | Historical React/dashboard route vocabulary | Audit for reusable intent; do not assume code still exists |
| `frontend/README.md` | Explicitly says React is retired | Replace only in architecture-authorization PR |

The repository contains historical layers that appear contradictory: current
product documentation says Streamlit-only, while route docs describe an older
dashboard and migration docs contain Rust/DataFusion stages. Agents must label
files CURRENT, HISTORICAL, TARGET, or UNKNOWN before using them as requirements.

## Streamlit product UI

### Entry and package

| Path | Inspect for | Target |
| --- | --- | --- |
| `services/ui/streamlit_app.py` | section order, page config, sidebar, tabs, state initialization, top-level errors | React route/shell and scenario inventory |
| `services/ui/pyproject.toml` | Streamlit/pandas/Plotly/DuckDB/open-fdd dependencies | Delete from product in P2; replace gates first |
| `services/ui/Dockerfile` | runtime, ports, health, asset/package assumptions | React/web delivery image or central-served assets |
| `services/ui/README.md` | stated capabilities and quick start | Update progressively; final removal in P2 |

### Required UI module audit

Inspect every file in `services/ui/app/`, with special attention to:

- central API clients, JWT handling, error translation;
- `job_store.py` and `ui_jobs.py`;
- package/ZIP/CSV ingestion and validation;
- data model/equipment tree and role mapping;
- session configuration and rule parameters;
- rule catalog/cookbook helpers;
- analytics, RCx/FDD plot data, metering, weather;
- findings/report/export/WattLab;
- cache and filesystem helpers;
- feature flags and pandas emergency paths.

Do not build the Python exit matrix from this list alone. Enumerate actual files
and trace dynamic imports, callbacks, and UI-only utilities.

### Streamlit specifications and tests

| Path | Value |
| --- | --- |
| `services/ui/docs/STREAMLIT_AGENT_SPEC.md` | interaction/behavior requirements |
| `services/ui/docs/STREAMLIT_DEMO_SPEC.md` | scenario/demo behavior |
| `services/ui/docs/STREAMLIT_RULE_INVENTORY.md` | rule/tuning inventory |
| `services/ui/app/test_job_store.py` | job semantics |
| `services/ui/app/test_jobs_central_client.py` | central client behavior |
| `scripts/smoke_streamlit_app.py` | existing browser/process smoke |
| `scripts/e2e_streamlit_package_ui.py` | package UI workflow |
| `scripts/release/smoke_streamlit_ui_gates.sh` | release expectations |

Reuse scenario intent and fixtures where correct. Replace Python/UI-specific
assertions with contract and React browser tests before deleting these gates.

## Current Python library surface

| Path | Current role | Phase treatment |
| --- | --- | --- |
| `open_fdd/rules/` | pandas cookbook/oracle | Freeze and version as Phase 1 oracle; production disposition requires decision |
| `open_fdd/analytics/` | reference analytics | Characterize, port deterministic parts to SQL, then non-production disposition |
| `open_fdd/reporting/` | findings/report generation | Inventory formats; replace production use in Rust/selected non-Python tooling |
| `open_fdd/ecm_engineering/` | generic ECM calculations | Inventory separately; port generic production needs to Rust or explicitly defer |
| `open_fdd/contracts` or target contract crate | prior shared contract direction | Prefer Rust `openfdd_contracts` as browser/runtime authority |
| root `pyproject.toml` | PyPI package/extras/CLIs | P2 product/archival decision; do not delete by accident |

The existing root package explicitly describes Python as ECM + pandas oracle
while production FDD is DataFusion/GHCR. The new program goes further by
removing Python from production runtime; it does not automatically erase the
educational/reference package.

Audit workflow `.github/workflows/ecm-python.yml` and all other Python Actions
before deciding which remain as oracle/library CI versus obsolete product CI.

## Rust workspace

Root `Cargo.toml` currently includes:

```text
edge
mcp
crates/fdd_core
crates/fdd_csv
crates/fdd_store
crates/fdd_sql
crates/fdd_rules
crates/fdd_bench
crates/fdd_cli
crates/openfdd_contracts
crates/openfdd_mqtt
services/fieldbus
services/central
```

### FDD/data crates

| Path | Current/expected responsibility | Modernization use |
| --- | --- | --- |
| `crates/fdd_core` | typed models, manifests, role normalization | shared domain types/validation; avoid UI types leaking in |
| `crates/fdd_csv` | CSV header/time health | Rust upload/validation vertical slice |
| `crates/fdd_store` | Arrow/Parquet ingest/cache | canonical package/historian bridge |
| `crates/fdd_sql/src/lib.rs` | DataFusion interface | stable analytics execution surface |
| `crates/fdd_sql/src/session.rs` | session/table/query behavior | resource, schema, and error tests |
| `crates/fdd_rules/src/runner.rs` | registry rule execution | production FDD |
| `crates/fdd_rules/src/oracle_harness.rs` | comparison support | Phase 1/2 parity evidence |
| `crates/fdd_bench` | compare/benchmark | expand normalized evidence, not production fallback |
| `crates/fdd_cli/src/main.rs` | inventory/validate/ingest/query/run/compare tools | operational/dev paths; APIs own browser behavior |
| `crates/openfdd_contracts` | Rust shared contracts | preferred home for versioned domain contracts |

Agents must verify the current crate APIs and whether types belong in a crate or
service-local module. Do not create a cyclic “everything contracts” crate.

### Central service

Inspect:

- `services/central/src/routes.rs`;
- `services/central/src/jobs.rs`;
- `services/central/src/analytics/historian.rs`;
- auth/JWT modules;
- artifact/static-file delivery;
- rule/FDD routes;
- dataset/package routes;
- error and OpenAPI/schema support;
- central integration tests including
  `services/central/tests/zip_package_fdd_integration.rs`.

Central is the target browser backend. Prefer extending coherent existing route
families over building a parallel `/react-api`.

### Edge

Inspect:

- `edge/src/server.rs`;
- `edge/src/fdd/execution.rs`;
- `edge/src/fdd/registry_api.rs`;
- `edge/src/csv_ingest/dataset.rs`;
- edge storage/ingest/health configuration.

Resolve overlap between central and edge before assigning an endpoint. The
browser should use central; edge can retain local/standalone responsibilities
behind the same contracts where appropriate.

### MCP

`mcp/` is an external agent interface to central. React work should not break
API semantics used by MCP. Contract/version changes require consumer tests.
Do not embed an AI chat relay into the UI as part of this modernization.

## DataFusion SQL and rules

| Path | Inspect/use |
| --- | --- |
| `sql_rules/registry.yaml` | canonical execution registry and parity metadata |
| `sql_rules/*.sql` | production rule and rollup expressions |
| `docs/rules/datafusion-sql.md` | workbench/API lifecycle |
| `docs/rules/cookbook/datafusion-sql-cookbook.md` | human-readable SQL patterns |
| `docs/rules/cookbook/parity-matrix.md` | rule-level honesty |
| `docs/migration/MILESTONE_D_RULE_PARITY.md` | historical parity evidence |
| `docs/migration/vibe19/STAGE2_PARITY_AND_WIRING.md` | prior oracle/compare design and known gaps |

Example discovered SQL files include SAT high, OAT meteo, economizer, VAV
comfort, and fault elapsed-hour logic. The actual registry at the implementation
commit is authoritative.

For every React-facing metric or rule, trace:

```text
registry metadata
  -> SQL inputs/roles/parameters
  -> DataFusion session/table
  -> Rust runner/status/error
  -> central response contract
  -> React display/chart
```

## Migration documents to reconcile

| Path | Why it matters |
| --- | --- |
| `docs/migration/vibe19/PYTHON_REDUCTION_PLAN.md` | prior Python file-level inventory; decisions are historical and often retain Python |
| `docs/migration/vibe19/RUST_CORE_STAGE1.md` | crate responsibilities and earlier CLI-first strategy |
| `docs/migration/vibe19/STAGE2_PARITY_AND_WIRING.md` | oracle export, tolerance, mapping, known rule gaps |
| `docs/migration/vibe19/DASHBOARD_UI_SPEC.md` | earlier visual/page/plot behavior |
| `docs/migration/vibe19_parity_matrix.md` | current capability status hints |
| `docs/migration/VIBE19_VIBE20_OPENFDD_AUDIT.md` | cross-app ownership decisions |
| `docs/architecture/PANDAS_USAGE_INVENTORY.md` | pandas paths and intended boundaries |
| `docs/architecture/FDD_ENGINE_EDGE_INTEGRATION_AUDIT.md` | engine/edge wiring gaps |
| `docs/agent/vibe19-parity-nightly-monster-prompt.md` | prior autonomous loop style |

Agents should update existing current-state matrices when adopted rather than
creating a competing truth indefinitely. The modernization ledgers may start
separate, then become the canonical replacement with redirects/historical
banners.

## Edge/fieldbus/MQTT for Phase 3

### Fieldbus

Inspect:

- `services/fieldbus/src/routes/bacnet.rs`;
- `services/fieldbus/src/services/bacnet_client.rs`;
- `services/fieldbus/src/services/bacnet_server.rs`;
- point catalog/config and smoke tests;
- Modbus/Haystack drivers.

### Edge BACnet

Discovered paths:

- `edge/src/drivers/bacnet.rs`;
- `edge/src/drivers/bacnet_live.rs`;
- `edge/src/drivers/bacnet_server.rs`;
- `edge/src/drivers/bacnet_server_runtime.rs`.

Reconcile ownership with fieldbus; do not start a second BACnet server/socket.

### MQTT and gates

Inspect:

- `crates/openfdd_mqtt`;
- broker/compose configuration;
- `scripts/release/smoke_standalone_mqtts.sh`;
- `scripts/gates/e2e_mqtts_feather.md`;
- `scripts/gates/sole_bacnet_udp_owner.sh`;
- `docs/drivers/bacnet.md`;
- local smoke-profile examples.

These paths inform Phase 3. They are not reasons to expand Phase 1/2 scope.

## Build and release surfaces

Audit:

- `.github/workflows/rust-ci.yml`;
- `.github/workflows/rust-release.yml`;
- `.github/workflows/ecm-python.yml`;
- all UI, docs, container, GHCR, nightly, security, and release workflows;
- `docker/compose.*.yml`;
- image/version manifests;
- build recipes and smoke scripts.

Phase 2 must remove a gate only after an equivalent replacement proves the
same product risk. Final evidence uses immutable `sha-*` images/digests, not
only `nightly`.

## Required first-pass searches

Adapt patterns to the host:

```text
rg -n "streamlit|st\\." services/ui
rg -n "session_state|cache_data|cache_resource|download_button|file_uploader"
rg -n "pandas|numpy|duckdb|python|pip|pytest|uvicorn|fastapi"
rg -n "subprocess|Command::new|python3?|open-fdd"
rg -n "/api/fdd/run|/api/jobs|faults|wattlab|session-config"
rg -n "workspace/jobs|job.json|meta_revision|correlation_key"
rg -n "sql_rules|DataFusion|SessionContext|run_all_rules"
rg -n "BACnet|47808|MQTT|MQTTS|write-dry-run"
rg -n "openfdd-ui|services/ui|streamlit" docker .github scripts docs
```

Also inspect package manifests, lock files, runtime images, and generated client
sources. Search results are inputs to ledgers, not automatic deletion lists.
