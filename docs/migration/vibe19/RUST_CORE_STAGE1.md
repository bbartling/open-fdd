# Rust FDD core — stage 1

**Branch target:** `develop`  
**Workspace:** `vibe_code_apps_19/rust_fdd_core/`

## Migration principle

```text
Python = oracle + ML/custom analytics layer
Rust = high-performance data engine
DataFusion SQL = default home for deterministic FDD rules and rollups
Parquet = durable columnar cache/store
Pandas should not receive new standard FDD rules unless documented
```

## What shipped in stage 1

| Crate | Responsibility |
| --- | --- |
| `fdd_core` | Typed models (`HistoryManifest`, `EquipmentHistory`, `RuleDefinition`, …), `validate_building()`, `columns.csv` role normalization |
| `fdd_csv` | Header scan, timestamp health (duplicates, non-monotonic, median Δt) without full file load |
| `fdd_store` | CSV → Arrow RecordBatch → Parquet + `.meta.json` stale-cache metadata |
| `fdd_sql` | DataFusion `SessionContext`, unified `history` table over `**/*.parquet` glob |
| `fdd_rules` | `registry.yaml` loader, tolerant `run_all_rules` (per-rule error capture) |
| `fdd_bench` | End-to-end benchmark + pandas-vs-SQL JSON compare helper |
| `fdd_cli` | `inventory`, `validate`, `ingest`, `query`, `run-rules`, `compare`, `benchmark` |

## CLI quick start

From `rust_fdd_core/`:

```bash
cargo run -p fdd_cli -- validate --data-root <HVAC_DATA_ROOT> --building BUILDING_100
cargo run -p fdd_cli -- ingest --data-root <HVAC_DATA_ROOT> --building BUILDING_100 --out ../.cache/parquet
cargo run -p fdd_cli -- query --parquet ../.cache/parquet --sql-file ../sql_rules/fan_runtime_hours.sql
cargo run -p fdd_cli -- run-rules --parquet ../.cache/parquet --rules-dir ../sql_rules --out ../.cache/rule_results
cargo run -p fdd_cli -- benchmark --data-root <HVAC_DATA_ROOT> --building BUILDING_100
```

Default Parquet output: `vibe_code_apps_19/.cache/parquet/building=<id>/equipment=<id>/history.parquet`

## Column naming

Ingest reads `columns.csv` and **projects** physical CSV headers onto cookbook **logical roles** (`fan_cmd`, `zone_t`, `oa_t`, …): each Parquet column stores the role name, not the raw header. When multiple physical columns map to one role, ingest picks the oracle-preferred column via `fdd_core::score_column_for_role`. SQL rules query the unified `history` table using these logical names.

**Limitation:** Role resolution is simpler than the full Python Haystack SPARQL path (no substring heuristics beyond column ranking). Equipment missing `columns.csv` roles will cause rules to **skip or fail** until mapping is extended.

## PyO3 evaluation (stage 1: defer)

| Candidate | Verdict |
| --- | --- |
| CSV validation | **CLI first** — Python can shell out to `fdd_cli validate` during transition |
| Parquet ingest | **CLI first** — same; avoids GIL + build complexity |
| DataFusion rule batch | **CLI or HTTP sidecar** — open-fdd edge already exposes SQL; vibe19 Rust CLI is local dev path |
| Fast rollups | **Prefer pure SQL** in `sql_rules/` before PyO3 |

Add PyO3 only when CLI subprocess overhead blocks dashboard warmup; keep API surface minimal (`validate`, `ingest`, `run_rules`).

## Tests (stage 1)

```bash
cd rust_fdd_core
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

7 unit/integration tests: manifest validation, column role map, CSV scan, Parquet ingest, DataFusion fan-runtime query, compare tolerance.

## Next slice (recommended PR)

1. Align Rust role resolution with `cookbook_engine.ROLE_CANDIDATES` (or export resolved pivot from `historian_export.py`).
2. Port P0 threshold rules: FC1–FC3, FC7–FC13, ECON-*, CHW-*.
3. Wire dashboard warmup to call `fdd_cli ingest` + cache Parquet mtime alongside Feather.
4. BUILDING_100 parity harness: export pandas oracle JSON per rule → `fdd_cli compare`.
