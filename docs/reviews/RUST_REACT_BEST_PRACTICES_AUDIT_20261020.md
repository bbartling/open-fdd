# Rust and React best-practices audit (2026-10-20)

Product Rust and `frontend/web` are clean against the lints this standard turns on. `cargo +1.95.0 clippy --workspace --all-targets -- -D warnings` exits 0. `frontend/web` `npm run lint` exits 0 (13 pre-existing `react-refresh/only-export-components` warnings; that rule stays a warning, and CI does not fail on warnings).

The product surface for this standard is the NF portal API and CSV ingest. MQTT, BACnet, Haystack, Modbus, fieldbus, edge, and dual-write paths are not cleaned here. Archived code lives in `archive/` and is never built.

No version bump. The 4.0.0 → 4.0.1 patch is a later PR after this change, the data-safe-defaults change, and the OT-archive change merge.

## Where the standard lives

- Rust: [`openfdd_agent_spec/docs/RUST_BEST_PRACTICES.md`](../../openfdd_agent_spec/docs/RUST_BEST_PRACTICES.md)
- React: [`openfdd_agent_spec/docs/REACT_BEST_PRACTICES.md`](../../openfdd_agent_spec/docs/REACT_BEST_PRACTICES.md)
- Suppressions only: [`openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md)
- Review skill (only authoring copy): [`openfdd_agent_spec/skills/openfdd-code-review-rust-react/SKILL.md`](../../openfdd_agent_spec/skills/openfdd-code-review-rust-react/SKILL.md)

## Who references it

- Root [`AGENTS.md`](../../AGENTS.md) section "Rust and React best practices"
- [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) rule 6c and rule 19
- [`openfdd_agent_spec/PR_PROTOCOL.md`](../../openfdd_agent_spec/PR_PROTOCOL.md) steps 2 and 7
- Skills `openfdd-react-spa` and `openfdd-architecture`
- Reviewer agents: `.cursor/agents/correctness-reviewer.md`, `performance-analyst.md`, `security-reliability-reviewer.md`, `spec-tracer.md`, `test-verifier.md`, `release-risk-reviewer.md`
- `.cursor/skills/multi-agent-pr-review/SKILL.md`

## What is enforced

Product crates opt into `[workspace.lints.clippy]`: `services/central`, `mcp`, `fdd_core`, `fdd_csv`, `fdd_store`, `fdd_resources`, `fdd_tsdb`, `fdd_rules`, `openfdd_contracts`, `openfdd_connector_runtime`.

Denied: `unwrap_used`, `expect_used`, `await_holding_lock`, `ptr_arg`, `redundant_clone`, `rc_buffer`, `print_stdout`, `print_stderr`, `dbg_macro`.

`clippy.toml` exempts unit tests with `allow-unwrap-in-tests`, `allow-expect-in-tests`, `allow-print-in-tests`, and `allow-dbg-in-tests`. `expect_used` does not read the unwrap switch. Integration binaries under `tests/` are not `cfg(test)`, so each of those files has a file-level allow for the panic and print lints, with that reason. `redundant_clone` is not exempt in tests; those clones were removed.

SPA ESLint errors: `react-hooks/rules-of-hooks`, `react-hooks/exhaustive-deps`, `react/jsx-key`, `react/no-array-index-key`, `react/no-danger`, `@typescript-eslint/no-explicit-any`, `jsx-a11y` recommended, and `no-restricted-syntax` on `document.getElementById`. `react-refresh/only-export-components` stays a warning.

## Counts

| Area | Before | After |
| --- | --- | --- |
| Product-crate Clippy `-D warnings` (workspace, Rust 1.95) | unwrap/expect were not denied | exit 0 |
| `.unwrap(` / `.expect(` lines removed outside the MQTT modules | 64 lines in the diff | 0 new production panics |
| `std` mutex poison recovery (`into_inner`) | request counters panicked on poison | 35 call sites, success path unchanged |
| SPA ESLint errors under the new rules | 6 | 0 |
| SPA `react-refresh` warnings | 13 | 13 (pre-existing, still warnings) |
| Unavoidable production `#[expect]` | — | 8 sites, listed below |
| MQTT module allows | temporary, until #1306 | dropped after the archive merge |

The old raw grep of about 1,600 `.unwrap` hits counted unit tests and `unwrap_or`. It is not the production count.

## What was fixed

### Safety and memory

- Request and ingest counters take a poisoned `std::sync::Mutex` with `lock().unwrap_or_else(PoisonError::into_inner)` in `state.rs`, `routes.rs`, and `afdd_scheduler.rs`. The success path is the same guard. A second panic no longer takes down the caller.
- The compaction coordinator still panics on poison (`crates/fdd_store/src/compaction_coord.rs`). A half-updated scan or compact counter must not continue.
- Static download headers use `HeaderValue::from_static`. Runtime `Content-Disposition` uses `HeaderValue::from_str` and the existing HTTP 500 JSON error.
- CSV export, portal queue budget, ingest schedule floor, fuel analytics, bill import, column mapping, and rule-param parsing use `let-else` or `match` instead of a production unwrap. Missing data returns the function's existing error or skips the row. It does not invent a value the old success path did not return.

### Performance and async

- `redundant_clone` sites that copied a value and then dropped the original now move that value (`capabilities`, `csv_site_export`, `jobs`, `routes`, `ingest_queue`, `fdd_store` tests, `openfdd_contracts` tests, `fdd_resources` watchdog). Ownership after the call is the same.
- `InFlightGuard::spawn` moves the cancel flag and class string into the watchdog. `register_token` already stored its own `Arc` clone.

### API design

- `PreflightInput` is `Copy` (every field already was). Callers that only updated one field no longer clone the struct. Existing by-value callers behave the same.
- Public signatures that would have had to change (`topic() -> String`, `storage() -> &LocalStorage`, `acquire_compute`, MCP `from_env`) kept their types. Those sites are the `#[expect]` list.

### React

- Plotly pages `Reports`, `RCx`, `Inspect`, and `Metering` load with `React.lazy`. `AuthGate` wraps `RouteErrorBoundary` and a `Suspense` fallback (`data-testid="route-loading"` / `route-error`). The success path renders the same page after the chunk loads.
- List keys no longer use the array index (`ProviderBindingsPanel`, `DataTable`, Operations continuity rows).
- `RuleTuningPanel` persist and `RulesPage` refresh include `buildingId`. `WeatherHealthSection` includes `equipment`, which the effect already filters.
- The only `as any` (sidebar CSS variable) is `React.CSSProperties`.
- `npm run typecheck`, `npm test` (331 tests), and `npm run build` pass.

## Unavoidable `#[expect]` (production)

| Site | Why it stays |
| --- | --- |
| `state.rs` `envelope_digest` | `TelemetryEnvelope` is a plain `Serialize` value. An empty digest would collide in the receipt journal. |
| `fdd_store` `compaction_coord.rs` | A poisoned fence means a scan or compact counter was left mid-update. Continuing would overlap compaction with a scan. |
| `parquet_parts.rs` `storage()` | Local-writer accessor. The signature stays `&LocalStorage`. |
| `fdd_resources` `acquire_compute` | The process-wide semaphore is never closed. |
| `openfdd_contracts` `topic()` | Protocol-scoped topic kinds. `Result` would change the topic contract. The archive PR removes this helper with the MQTT stack. |
| `providers/ledger.rs` `axis()` | `assemble` inserts every `AxisId`. `Option` would change the helper contract. |
| `mcp` `BridgeClient::from_env` | `reqwest` fails here only when the TLS backend cannot initialize. `from_env` has no `Result` channel. |
| `mcp` `main` | One `eprintln!` before any tracing subscriber exists, then `exit(1)`. |

`#[cfg(test)]` helpers that hold a process-wide env lock across `.await` keep their existing `#[expect(clippy::await_holding_lock)]`. That lint is not covered by the test unwrap switches, and the expectation is fulfilled.

## File-level allows (not a pattern for new product code)

Integration tests, one line of reason each: `services/central/tests/*.rs` (5 files) and `crates/fdd_resources/tests/admission_pressure_qual.rs`. Clippy's `allow-*-in-tests` does not apply to `tests/` binaries.

After #1306 merged, the module-level allows on `ingest.rs`, `mqtt_monitor.rs`, and `live_historian.rs` are gone. `mqtt_monitor.rs` is only under `archive/`. `ingest.rs` and `live_historian.rs` are the portal and CSV writer and follow the deny set. `archive/` is not a workspace member. The remaining `edge` crate is the package and SQL helper central links. It does not opt into the new restriction lints.

## ESLint disables

| Site | Reason |
| --- | --- |
| `frontend/web/src/main.tsx` | Root `document.getElementById("root")` is outside React. Added for the new ban. |
| `RulesPage.tsx` initial load | Pre-existing. Empty deps so the first fetch does not re-fire when `refresh` changes. |
| `OverviewPopulated.tsx` | Pre-existing exhaustive-deps disable. |
| `DownloadButton.tsx` | Pre-existing `jsx-a11y/anchor-is-valid` disable on the download anchor. |

## Deferred on purpose

- Protocol drivers, the MQTT crate, fieldbus, and the edge wire process. #1306 archived them. This branch does not restyle `archive/`.
- Dual-write and Parquet/DataFusion product paths stay forbidden. This PR does not add a writer. `legacy-datafusion` / `legacy-parquet` stay off. The analytics result cache under `analytics_results/` is still a result cache, not the historian.
- SQL that interpolates identifiers only after `safe_ident`, and wrappers around the shipped `sql/fdd` pack, were not rewritten. Values stay sqlx binds. A grep that flags every `format!` near SQL would also flag those validators.
- `fdd_rules` files that are not in the module tree (`runner.rs`, `oracle_harness.rs`, and the `*_test.rs` siblings) are not compiled. Clippy does not see them.
- No `cargo-deny` job. `cargo audit` is already in `.github/workflows/appsec.yml`.
- No `VERSION` / Cargo / package version bump and no changelog release header.

## Behavior

Success-path results are unchanged. Poisoned request counters no longer panic. A download filename that is not a legal header now returns the existing 500 JSON shape instead of panicking. Lazy routes show "Loading" until the chunk arrives, then the same page.

Local checks on Rust 1.95: workspace Clippy `--all-targets -D warnings` exit 0; `cargo fmt --all --check` exit 0; unit tests for `fdd_core`, `fdd_csv`, `fdd_store`, `fdd_resources`, `fdd_rules`, `fdd_tsdb`, `openfdd_contracts`, `openfdd_connector_runtime`, and `openfdd-mcp` exit 0; `openfdd-central` binary tests 348 passed. SPA: typecheck, 331 tests, and production build exit 0.

Rebase onto `cf6109b1` (#1305) added `services/central/src/db_lifecycle.rs`. Production code in that module has no `.unwrap()` or `.expect()`. Identifier SQL goes through `is_safe_ident` before `format!`. The two `.expect()` calls sit in `#[cfg(test)]` helpers, which `allow-expect-in-tests` covers. `cargo clippy -p openfdd-central --all-targets -- -D warnings` exits 0 with that file included. `scripts/timescale/` is Python lab seed/purge tooling, not a Clippy target. `data_safe.py` decides preserve versus delete without a product dual-write, and seed SQL uses `%s` binds.
