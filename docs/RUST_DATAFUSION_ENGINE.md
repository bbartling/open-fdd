# Open-FDD Rust / DataFusion engine

Production-direction deterministic FDD analytics for Open-FDD.

## Stack

| Layer | Technology |
| --- | --- |
| Validation + role map | `fdd_core`, `fdd_csv` |
| Historian ingest | CSV → Apache Arrow → Parquet (`fdd_store`) |
| Rule execution | Apache DataFusion SQL (`fdd_sql`, `fdd_rules`) |
| Benchmark / compare | `fdd_bench` |
| CLI | `openfdd_cli` (`fdd_cli` crate) |

## Data tree contract

```
{data_root}/{building_id}/
  manifest.json          # { "grid_minutes": 5 }
  {equipment_id}/
    columns.csv          # col, point_role
    history_wide.csv     # timestamp_utc + point columns
```

Optional weather: `{building}/weather/history_wide.csv` with `web-outside-air-temp` → `web_oa_t` (OAT-METEO / B100). Product does not bake a city.

Haystack `points` names translate via `haystack_point_to_role` (`discharge-air-temp` → `sat`). Package authoring for agents: [`docs/agent/PACKAGE_AUTHORING.md`](agent/PACKAGE_AUTHORING.md). Aliases: [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](migration/vibe19/ROLE_MAPPING_PARITY.md).

### `timestamp_utc` contract

- ISO-8601 UTC with **`Z` or numeric offset** (`+00:00`) — both accepted.
- Unparseable or empty stamps are **skipped** (never written as epoch 0 / wall-clock now).
- Mixed suffixes in one CSV are fine; gold fixtures and BAS exports both appear in the wild.

### Map JSON shapes

- Package map: `equip` / `equipment` / `devices` must be an **object** of equipment blocks.
- Single-equip Haystack sidecars may set `"equip": "AHU_1"` as a **string** device id — that is metadata; roles come from `points` / `column_roles`.
- Site-specific vendor point names belong in the package preprocess, not in Rust equations.

## CLI

```powershell
cargo run -p fdd_cli --release -- validate --data-root examples/sample_data --building BUILDING_FIXTURE
cargo run -p fdd_cli --release -- ingest --data-root examples/sample_data --building BUILDING_FIXTURE --out .cache/parquet
cargo run -p fdd_cli --release -- run-rules --parquet .cache/parquet --rules-dir sql_rules --out .cache/rule_results
cargo run -p fdd_cli --release -- compare --python-results .cache/oracle/pandas_rules.json --sql-results .cache/rule_results --tolerance 0.5
cargo run -p fdd_cli --release -- benchmark --data-root $env:HVAC_DATA_ROOT --building BUILDING_100
```

Release binary: `target/release/openfdd_cli.exe`

## SQL rules

- Registry: `sql_rules/registry.yaml`
- Rule SQL: `sql_rules/*.sql`
- Tuning YAML: `rule_tuning/` (optional overrides)
- Confirm windows: LAG-based streak CTE matching pandas `confirm_fault()`

## What is NOT in this crate

- Live BACnet/Modbus drivers
- HTTP API / React UI (planned)
- Python pandas as production runtime

See `docs/cookbook/COOKBOOK_TO_SQL_RULES.md` for cookbook cross-links.
