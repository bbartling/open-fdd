# Slice 8: archive map (central v4 -> `archive/central-v4/`)

Decision: [ADR-014](../../architecture/adr-014-open-fdd-as-nf-plugin.md). Plan: [PLAN.md](PLAN.md) slice 8.
Restore point: git tag `v4.0.11-central`. Moves were plain `mv` (nothing staged); relative paths are preserved
under `archive/central-v4/`. One line of evidence per item. Status: ARCHIVE (moved), KEEP, UNSURE (left in place).

## Rust workspace members (before: 11)

| Item | Status | Evidence |
| --- | --- | --- |
| `services/central` | ARCHIVE | `openfdd-central` binary: NF ingest, own Timescale, REST+JWT, static UI. Depends on every other member. Replaced by `nf-app/`. |
| `edge` | ARCHIVE | `open_fdd_edge_prototype`: only consumer is `services/central` (`default-features = false`) and `mcp`. Auth/CSV/ingest/dashboard modules of the old stack. |
| `mcp` | ARCHIVE | `openfdd-mcp` is a stdio proxy of central's JWT REST (`/api/auth/login`, `/api/csv/import/*`, `/api/fdd-rules`, `OPENFDD_API_BASE`). No central, no server. **Decision for Ben:** an MCP for the NF app would be a new thing (the NF MCP already exists). |
| `crates/openfdd_contracts` | ARCHIVE | Dependents: `services/central` only (ingest/inventory/command envelopes, OpenAPI). |
| `crates/nf_grpc` | ARCHIVE | Dependents: `services/central` only (NF gRPC ingest client). The app uses NF's HTTP/JSON API. |
| `crates/fdd_store` | ARCHIVE | Dependents: `edge`, `central` (AFDD scheduler, historian, analytics cache). |
| `crates/fdd_resources` | ARCHIVE | Dependents: `edge`, `central` (admission/budget/cgroup limits). |
| `crates/fdd_tsdb` | KEEP | DB bootstrapping: `include_str!` of `sql/schema/09,10,12_*.sql`, `package_seed.rs`, `revision.rs`, `incremental_store.rs`, `si_cutover.rs`, `runner.rs`. Depends only on `fdd_core`. Referenced by c3c-sqlqual and si-parity. |
| `crates/fdd_core` | KEEP | Dependency of `fdd_tsdb`/`fdd_rules`; `units_contract.rs` is checked by `scripts/ci/check_unit_contract.py`. |
| `crates/fdd_rules` | KEEP | Registry/params/tuning/quantity validation of `sql/fdd/registry.yaml`; `crates/fdd_rules/fixtures/oracle/**` feeds cookbook-parity; run by pypi-sql-parity and fdd-engine-ci. |
| `crates/fdd_csv` | UNSURE | CSV parsing for the old stack; no Cargo dependents (only `fdd_core`), mentioned as text in `edge`/`mcp`. Left in the workspace (cheap). Archive if CSV import is not coming to the app. |

Remaining workspace: `fdd_core`, `fdd_csv`, `fdd_tsdb`, `fdd_rules`. `Cargo.lock` still lists archived crates' dependencies until the next `cargo` run that rewrites it.

## Directories and top-level files

| Item | Status | Evidence |
| --- | --- | --- |
| `docker/` (all 18 compose files, `caddy/`) | ARCHIVE | All run `central`/`web`/`mcp`/GHCR images (portal, react, csv, standalone-https, qual, ci-browser). `compose.timescale*.yml` only mounts `sql/schema/*` as initdb: superseded by the plugin's full profile running the pack in NF's TimescaleDB; the schema SQL itself stays in `sql/schema/`. |
| `deploy/caddy/` | ARCHIVE | Old standalone HTTPS Caddyfiles for central (`Caddyfile.standalone.https*`). `deploy/nf-caddy/` (NF front door) is untouched and KEEP. |
| `frontend/` | ARCHIVE | One README pointing at `services/central/static/product/`. |
| `Dockerfile.mcp` | ARCHIVE | Builds the `openfdd-mcp` image. |
| `config/nf/` | ARCHIVE | `provider-credentials.env.example` = central's NF provider creds. |
| `archive/product-ui/react-spa-v4`, `archive/ot-edge` | KEEP | Already archived earlier; `security.yml` still asserts the React tree exists. |
| `open_fdd/` (Python package) | KEEP | PyPI package `open-fdd` (`pyproject.toml`; python-package.yml, publish-open-fdd.yml, si-parity.yml paths). |
| `sql/` | KEEP | Rule pack, schema, contracts, verify/parity tooling (off limits). |
| `sql_rules/`, `rule_tuning/`, `fixtures/`, `examples/`, `tests/` (rest), `tools/` | KEEP | Rule/fixture/oracle inputs for the SQL pack and the PyPI package; `tools/rdf-check` serves nf-app-ci. |
| `os/` | UNSURE | "Open-FDD OS (future concept)" design placeholder; mentions central. Harmless, left. |
| `workspace/` | UNSURE | Central's workspace/model templates (`AGENTS.md` "never delete workspace/"). `security.yml` no longer asserts it. Ben to decide. |
| `reports/`, `config/` (now gone), `.env.example` | UNSURE | `.env.example` is central's env template (still referenced by README/guards); `reports/` historical evidence. |
| `openfdd_agent_spec/` | UNSURE | Agent skills/specs mostly written for the central stack (`openfdd-stack-ghcr`, `openfdd-static-ui`, `openfdd-nf-provider`, ...). Only `DATA_CONTRACT.md` got a superseded note. |

## Scripts

| Item | Status | Evidence |
| --- | --- | --- |
| `scripts/openfdd_stack_{lib,pull,up}.sh`, `openfdd_local_repin.sh`, `openfdd_maint_update_resume.sh`, `openfdd_demo_gate.sh`, `openfdd_health_check.sh`, `openfdd_caddy_smoke.sh`, `openfdd_docker_maintenance.sh`, `openfdd_workspace_reset_default.sh`, `openfdd_auth_lib.sh` | ARCHIVE | Drive `docker/compose.*` and central health/auth (`/api/auth`, port 8080). |
| `scripts/openfdd_mcp_stdio.sh`, `openfdd_csv_{export,import}_sidecar.sh`, `openfdd_data_retention_sidecar.sh` | ARCHIVE | Wrap the `openfdd-mcp` image / central CSV + retention APIs. |
| `scripts/ghcr_*.{py,sh}`, `test_ghcr_*`, `test_openfdd_stack_image_tag.sh`, `check_ghcr_tip_*.sh`, `resolve_ghcr_publish_tag.sh`, `ghcr-*-protected-*.txt` | ARCHIVE | GHCR stack image tag/prune/tip tooling; only used by the archived GHCR workflows. |
| `scripts/timescale/run_central_host.sh` | ARCHIVE | Runs the central binary on the host. Rest of `scripts/timescale/` KEEP (`auto_seed`, synthetic parity, data_safe are DB/SQL-pack tooling). |
| `scripts/ci/{real_stack_browser.sh,browser_stack_health.py,playwright_*,seed_static_ui_browser_site.sh,static_ui_*,static_product_guard.sh,check_compose_env_passthrough.sh,check_csp_headers.sh,generate_openapi_router_routes.py,run_ingest_parallel_interaction_rounds.sh,forbid_product_ui_port_3000_docs.sh,forbid_datafusion_product.sh,test_forbid_datafusion_product.sh}` | ARCHIVE | Browser/compose/OpenAPI/ingest guards for central; the DataFusion guard runs `cargo tree -p openfdd-central`. |
| `scripts/gates/` (all) | ARCHIVE | Architecture/MQTT/OpenAPI-central gates; shell scripts around central and `edge`. |
| `scripts/security/` (all), `tests/security/` (all) | ARCHIVE | Stack security harness: central `routes.json` inventory (203 refs), deployment profiles, Caddy TLS, Trivy on GHCR digests. |
| `scripts/qualification/{portal,lib,zap}/`, `run_portal_qualification.sh`, `restore_to_empty.sh`, `run_isolated_zap_af.sh`, `run_wave_c_isolated.sh`, `repro_1483_*.sh`, `zap_*` | ARCHIVE | Portal/ZAP qualification of the compose stack (`lib/portal_stack.sh` boots `docker/compose.portal*`). The matching tests (`test_demo_gate_recipe`, `test_portal_qual_recipe`, `test_portal_runner_integrity`, `test_isolated_zap_*`, `test_zap_*`) and `tests/operations/*` moved with them. |
| `scripts/release/smoke_{csv_central_boot,mcp_central,react_web_image}.sh` | ARCHIVE | Boot central/MCP/web images. `check_version.py` KEEP (PyPI). |
| `scripts/nf/`, `scripts/nf_tools/` | KEEP | NF app tooling (off limits). |
| `scripts/qualification/` (rest: `c3*`, `semantic`, `protocol_connector...`, `write_manifest`) , `scripts/sql_contract`, `scripts/softopen`, `scripts/cookbook_parity_check.py`, `sql_pandas_oracle_check.py`, ... | KEEP | SQL pack qualification and parity (c3c-sqlqual, sql-qual-c3a, si-parity, cookbook-parity, pypi-sql-parity). |
| `scripts/check_version_sync.sh` | KEEP (edited) | Now scans `crates/` and skips crates inheriting `version.workspace`. |
| `scripts/audit_no_private_bench_hardcoding.sh`, `phase2_computation_policy_check.py`, `phase2_shadow_compare.py`, `architecture_*_check.py`, `validate_capabilities_ledger.py`, `scripts/ci/check_no_imperial_product.py`, `scripts/ci/forbid_columnar_product.py`, `scripts/test_data_safe_defaults.sh` | UNSURE | Policy guards that scan `services/central`/`edge` source paths (11-14 refs each). No longer run by any workflow. Retarget at `nf-app/` or archive. |
| `scripts/stress/`, `scripts/eplus_*`, `scripts/vibe21_*`, `scripts/wattlab_*`, `scripts/lessons`, `scripts/dev` | UNSURE | Mostly SQL/oracle/stress tooling; `stress/helpers.py` and `si_cutover/capture_ip_baseline.py` mention central paths. |
| `tests/qualification/` (rest) | UNSURE | SQL/semantic tests, but `test_static_model_probe`, `test_no_equipment_id_heuristics`, `test_capture_ip_baseline` reference central paths; appsec.yml still runs `unittest discover tests/qualification` and may fail on them. |

## Workflows

| Workflow | Status | Evidence / change |
| --- | --- | --- |
| `rust-ci.yml` | ARCHIVE | Nearly all jobs test central/edge/mcp/compose. NF app + RDF steps moved unchanged to `nf-app-ci.yml`; surviving SQL checks (rule columns, unit contract, fdd_core/fdd_rules tests, pandas == Timescale parity) carried to new `sql-pack-ci.yml`. |
| `ghcr-openfdd-stack.yml`, `ghcr-candidate-smoke.yml`, `ghcr-tip-completeness.yml`, `ghcr-prune.yml`, `rust-ghcr-mcp.yml`, `rust-release.yml`, `stack-crate-tests-pr.yml` | ARCHIVE | Build/publish/verify GHCR stack + MCP images, release central, test `services/central`. |
| `nf-app-ci.yml` (new) | KEEP | nf-app tests/manifest/rule-catalog + RDF check, Node 22 / Python 3.12, `npm ci` only if `nf-app/package-lock.json` exists. |
| `sql-pack-ci.yml` (new) | KEEP | See rust-ci row. |
| `fdd-engine-ci.yml` | KEEP (edited) | Dropped `services/central` paths, DataFusion-central guard, central clippy and `plot_role_tests`; `fdd_resources` removed from clippy list. |
| `pypi-sql-parity.yml` | KEEP (edited) | Dropped DataFusion-central guard and `cargo test -p openfdd-central plot_role_tests`. |
| `c3c-sqlqual-11-12a.yml` | KEEP (edited) | Removed `services/central` trigger path and `--run-rust-cutover` (that flag ran `cargo test -p openfdd-central t1284_3`). |
| `si-parity.yml` | KEEP (edited) | Removed `services/central/src/...` trigger paths. |
| `security.yml` | KEEP (edited) | Kept the PyPI-shape guard; replaced the central/docker asset checks with NF-app/archive layout checks; dropped the static-UI/React/phase2 policy step. |
| `appsec.yml` | KEEP (edited) | Kept cargo-audit, gitleaks, Trivy fs and the SQL/semantic harness; removed the central UI guard job, the Hadolint job (central/web/MCP Dockerfiles), tests/security, portal-recipe lint, ZAP/Nessus/standalone-HTTPS selftests. |
| `python-package.yml`, `publish-open-fdd.yml`, `docs-pages.yml`, `docs_guard.yml`, `cookbook-parity.yml`, `sql-qual-c3a.yml`, `merged-branch-cleanup.yml` | KEEP | PyPI package, docs, SQL pack; no references to archived paths (verified by path scan). |

## Counts

ARCHIVE: 7 crates/dirs of Rust (central, edge, mcp, 4 crates) + 5 other dirs/files (docker, deploy/caddy, frontend, Dockerfile.mcp, config/nf) + 8 workflows + ~50 scripts/tests. KEEP: 3 crates (+1 UNSURE), NF app, SQL pack, PyPI package, 7+3 workflows. UNSURE: see tables.
- `scripts/qualification/semantic/static_model_probe.py` (+ doc, test): probed central's static `ttl-model.js`; replaced by `tools/rdf-check` on the NF app's `model.js`. ARCHIVE (moved after the agent pass).
