# PR #477 finish and branch cleanup

**Date:** 2026-07-09  
**PR:** [#477 — Integrate Vibe19 Rust/DataFusion engine into master (additive)](https://github.com/bbartling/open-fdd/pull/477)  
**Branch:** `cleanup/integrate-rust-port-into-master`  
**Base:** `master`

## Branch and commits

| Commit | Summary |
| --- | --- |
| `271356ca` | Integrate Vibe19 Rust/DataFusion engine into master additively |
| `45cdd9f5` | Fix Docker builds after workspace adds fdd crates |
| `b230b11e` | Fix RDF store cache keyed by workspace (parallel test races) |
| `b18a1953` | Apply rustfmt to RDF store cache guard |
| *(pending)* | Finish PR 477 review fixes and validation docs |

**Diff vs master:** 96 files, +7308 / −7 lines (additive only).

## Structural verification

| Path | Present | Notes |
| --- | --- | --- |
| `crates/fdd_*` | yes | 7 crates: core, csv, store, sql, rules, bench, cli |
| `sql_rules/` | yes | 19 SQL rules + `registry.yaml` |
| `rule_tuning/` | yes | `defaults.yaml` |
| `tools/python_oracle/` | yes | Oracle/test only |
| `edge/` | yes | Production Rust edge intact |
| `mcp/` | yes | MCP product intact |
| `workspace/dashboard/` | yes | React/TS/Vite source |
| `frontend/` | yes | Compiled static output for Docker |
| `docker/` | yes | Compose stacks intact |
| `.agents/` | yes | Agent config preserved |
| `.cursor/` | yes | Cursor config preserved |
| `.codex/` | yes | Codex config preserved |
| `AGENTS.md` | yes | Agent charter preserved |

**Production code removed accidentally:** no — diff is additive; edge/MCP/Docker/dashboard paths unchanged except `edge/src/model/rdf.rs` cache fix.

## Local validation (2026-07-09)

| Command | Result |
| --- | --- |
| `cargo fmt --all --check` | pass (after fmt) |
| `cargo test -p fdd_core -p fdd_csv -p fdd_store -p fdd_sql -p fdd_rules -p fdd_bench -p fdd_cli` | pass (23 tests) |
| `cargo test -p fdd_store` (weather error test) | pass |
| `cargo run -p fdd_cli -- validate --data-root examples/sample_data --building BUILDING_FIXTURE` | pass |
| Full `cargo test --workspace --all-targets` (Windows) | not run — oxigraph/libclang edge deps fail locally; Linux CI authoritative |

## CodeRabbit review items

| Item | Still valid | Fix applied | Test coverage |
| --- | --- | --- | --- |
| Weather ingest error visibility (`fdd_store/ingest.rs`) | yes | `IngestReport` extended with `weather_ingested`, `weather_rows`, `weather_error`; no more `let _ =` discard | `ingest_records_weather_error_when_path_missing` |
| PyYAML missing in `fdd-engine-ci.yml` | yes | `python3 -m pip install --user PyYAML` before registry validation | CI step |
| Rust MSRV mismatch (`Cargo.toml`) | yes | `rust-version` raised to `1.80` (CI uses 1.95) | CI toolchain |
| Port finish plan wording (`docs/PORT_FINISH_PLAN.md`) | yes | Rewritten: PR #477 additive path; warns against direct `port-vibe19-*` merge | doc only |
| Role mapping doc (`RUST_CORE_STAGE1.md`) | yes | Clarified physical→logical role projection, not header rename | doc only |
| Broken doc links (`COOKBOOK_TO_SQL_RULES.md`) | yes | Fixed relative link to tuning contract | doc only |
| Mixed parity snapshots (`STAGE2_PARITY_AND_WIRING.md`) | yes | Historical disclaimer + link to benchmark report | doc only |
| Parameter schema naming (`SQL_RULE_TUNING_CONTRACT.md` vs `API_CONTRACT.md`) | yes | Canonical field `control`; `frontend_control` documented as legacy alias | doc only |
| Broken links in `RUST_DATAFUSION_ENGINE.md` | no | File has no broken relative links; cookbook link resolves | skipped |

## Blockers before merge

1. Push review-fix commit and confirm CI green on PR branch.
2. `ci.yml` "Rust format and tests" had prior failures (likely stale runs before fmt/RDF fix); re-run after push.
3. Post-merge: `rust-ghcr.yml` needs scheduled cron (Phase 8 on follow-up branch).

## Merge criteria checklist

- [x] Production edge/MCP code intact
- [x] FDD engine crates present
- [x] SQL rules and tuning present
- [x] Python oracle test-only
- [x] Docs consistent (CodeRabbit items addressed)
- [x] FDD crate tests pass locally
- [ ] GitHub Actions all green on latest commit
- [x] CodeRabbit SUCCESS

## After merge

1. Delete `cleanup/integrate-rust-port-into-master` (superseded by master).
2. Delete `port-vibe19-rust-datafusion-engine` after verifying engine on master.
3. Open `fix/nightly-ghcr-and-react-cutover` for cron + frontend docs.
