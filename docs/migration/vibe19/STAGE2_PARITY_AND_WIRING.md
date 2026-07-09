# Stage 2 — Parity and wiring

> **Historical snapshots:** Numbers below are point-in-time BUILDING_100 parity runs. For the current benchmark, see [RUST_DATAFUSION_PARITY_BENCHMARK.md](../../benchmarks/RUST_DATAFUSION_PARITY_BENCHMARK.md) (commit/date labeled there).

> **Stage 3 update (2026-07-09):** VAV_7 `zone_t` ranked resolution + SQL tunable parameters. Snapshot @ 0.5h: **314 pass / 54 fail** (was 228/52 @ `bdb8881`).

Stage 2 adds pandas oracle export, hardened `fdd_cli compare`, role-mapping alignment, poll-interval parameterization, 11 additional P0 SQL rules, optional dashboard Rust cache warmup, and BUILDING_100 numeric parity evidence.

## What Stage 1 had

- Rust workspace (`rust_fdd_core/`) with validate, ingest, query, run-rules, compare, benchmark
- 8 SQL rules in `sql_rules/`
- Python dashboard in `fdd_app/` (oracle path)
- No numeric pandas-vs-SQL parity report

## What Stage 2 adds

| Deliverable | Path |
| --- | --- |
| Pandas oracle export | `fdd_app/export_pandas_oracle.py` → `.cache/oracle/pandas_rules.json` |
| Compare + markdown report | `fdd_bench/compare.rs`, `fdd_cli compare --report` |
| Poll interval substitution | `{{POLL_SECONDS}}` in SQL + `.cache/parquet/manifest.json` |
| Role mapping parity | `fdd_core/columns.rs`, `docs/ROLE_MAPPING_PARITY.md` |
| P0 SQL rules (19 total) | `sql_rules/*.sql`, `registry.yaml` |
| Dashboard warmup | `VIBE19_RUST_CACHE=1` → `rust_fdd_bridge.warmup_cache()` |
| Utf8View fix for compare keys | `fdd_sql/session.rs` |

## BUILDING_100 benchmark (release, 2026-07-09)

| Step | Time | Notes |
| --- | ---: | --- |
| validate | 32 ms | 48 equipment |
| ingest | 3402 ms | ~1.5M rows → Parquet |
| run-rules (19) | 850 ms | 18/19 succeeded |
| poll_seconds | 300 | from manifest `grid_minutes: 5` |

## Parity summary (tolerance 0.5)

| Metric | Value |
| --- | ---: |
| Rules in registry | 19 |
| Equipment compared | 48 |
| Metrics pass | 229 |
| Metrics fail | 49 |
| Skipped (missing roles) | 12 |
| Max abs delta (hours) | 1147.4 |

Full report: [`benchmarks/RUST_DATAFUSION_PARITY_BENCHMARK.md`](../benchmarks/RUST_DATAFUSION_PARITY_BENCHMARK.md)

### Original 8 rules — parity status (2026-07-09 stage 3 pass)

| Rule | Status | Notes |
| --- | --- | --- |
| FAN-RUNTIME-HOURS | **Proven** | Within tolerance |
| AVG-ZONE-TEMP | **Proven** | |
| ZONE-COMFORT-PCT | **Proven** | |
| FAULT-ELAPSED-HOURS | **Proven** | |
| VAV-1 | **Near parity** | Confirm SQL; max delta ~4 h (~1%) on worst VAV |
| ECON-2 | **Proven** | 63°F / 42% + confirm; AHU deltas <1% |
| OAT-METEO | **Near parity** | Weather staging + join; AHU deltas 3–8% |
| FC13-SAT-HIGH | **Partial** | sat_sp fallback; some AHUs still mismatch |

### New P0 rules (Stage 2)

| Rule | SQL run | Parity |
| --- | --- | --- |
| FC2, FC3 | OK | Raw-hours compare pending full confirm alignment |
| FC7 | Skipped AHU (no htg_valve_pct on BUILDING_100) | Blocked |
| FC8–FC12 | OK | Partial — raw SQL vs confirmed pandas |
| FC1 | **Blocked** | `duct_static_sp` not in BUILDING_100 Parquet schema |
| ECON-1, ECON-4 | OK | Partial |
| ECON-5 | Not ported | preheat roles missing |

## Commands

```powershell
# Oracle
cd vibe_code_apps_19
$env:HVAC_DATA_ROOT = ".\data\hvac_systems_CLEANED"
python fdd_app/export_pandas_oracle.py

# Rust pipeline
cd rust_fdd_core
cargo run -p fdd_cli --release -- validate --data-root ..\data\hvac_systems_CLEANED --building BUILDING_100
cargo run -p fdd_cli --release -- ingest --data-root ..\data\hvac_systems_CLEANED --building BUILDING_100 --out ..\.cache\parquet
cargo run -p fdd_cli --release -- run-rules --parquet ..\.cache\parquet --rules-dir ..\sql_rules --out ..\.cache\rule_results
cargo run -p fdd_cli --release -- compare --python-results ..\.cache\oracle\pandas_rules.json --sql-results ..\.cache\rule_results --report ..\vibe19_agent_spec\benchmarks\RUST_DATAFUSION_PARITY_BENCHMARK.md

# Tests
python validate_data.py
cd fdd_app && python -m pytest -q
cd rust_fdd_core && cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings
```

## Dashboard warmup

Set `VIBE19_RUST_CACHE=1` before starting uvicorn. Background thread runs `rust_fdd_bridge.warmup_cache()` (validate + ingest). Failures are logged; Python/Feather path unchanged.

## Known limitations (Stage 3 targets)

1. SQL fault rules use raw sample counts; Python applies `confirm_fault` streaks
2. OAT-METEO needs `wx_oa_t` weather join in SQL
3. ECON-2 SQL thresholds must match cookbook defaults
4. FC1 blocked until `duct_static_sp` mapped on BUILDING_100
5. ECON-3/5 and CHW rules need plant/preheat roles

## Stage 2/3 verdict

**Stage 3 slice complete:** confirm-window SQL (`{{CONFIRM_ROWS}}`), ECON-2 cookbook thresholds, weather staging bridge, duct_static_sp mapping, **19/19 SQL rules run**. BUILDING_100: **234+ metric pass** @ 0.5 tolerance; ECON-2 **<1%** on AHUs; OAT-METEO **3–8%** with weather join. Remaining gaps: FC13 sat_sp, FC2 streak edge cases, VAV-1 ~1% residual.
