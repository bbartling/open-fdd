---
title: Using SQL rules outside Open-FDD
parent: Rules
nav_order: 3
---

# Using SQL rules outside Open-FDD

The 77 rule SQL files are ordinary PostgreSQL 14+. They use no `time_bucket`, hypertables or continuous aggregates. Timescale is
only the runtime that builds the wide `history` input, so any database that can build that table can run them.

## Quick start (DuckDB, no server)

Checked on `generate(seed=0, equips=2, days=3, profile="basic")`: FC1, FC2 and CMD-1 match the pandas reference within 1e-6 h.
Run from a repo checkout (`pip install duckdb pandas numpy pyyaml`).

```python
import json, duckdb, pandas as pd
from open_fdd.parity import generate, reference

ds = generate(seed=0, equips=2, days=3, profile="basic")
data = ds.to_engine_input()
pack = json.load(open("nf-app/rules/pack-postgres.json"))   # rule SQL rendered at default parameters

hist = pd.DataFrame(data["history"])
hist["timestamp_utc"] = pd.to_datetime(hist.pop("ts"), unit="ms", utc=True)
con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
con.register("hist_df", hist)
con.execute("CREATE TABLE history AS SELECT * FROM hist_df")

ref = reference(ds)
rows = con.execute(pack["rules"]["FC1"]["sql"]).fetchall()   # (equipment_id, fault_hours, covered_hours, fault_pct)
print(rows, {e: v["pandas"] for e, v in ref["FC1"].items()})
```

`open_fdd.parity` is missing from the older PyPI releases (4.5.4 and earlier). Until a later release is published, install from git: `pip install "open-fdd[oracle] @ git+https://github.com/bbartling/open-fdd"`.

## Runnable DuckDB and SPARQL tutorial

The [standalone DuckDB tutorial](https://github.com/bbartling/open-fdd/tree/master/tutorials/duckdb_sql_parity) includes executable pandas-versus-SQL assertions for FC1, FC2 and CMD-1, plus SPARQL point discovery joined to a DuckDB long-form historian. Both scripts run locally without an NF server. Follow its README for PowerShell or Linux setup.

## From CSV or a pandas DataFrame to a validated SQL rule

For a local, no-server walkthrough, use the [DuckDB tutorial README](https://github.com/bbartling/open-fdd/blob/master/tutorials/duckdb_sql_parity/README.md). From the repo root on Windows PowerShell:

```powershell
uv venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -e ".[oracle]" duckdb rdflib matplotlib
.\\.venv\\Scripts\\python.exe tutorials/duckdb_sql_parity/explore_data.py
.\\.venv\\Scripts\\python.exe tutorials/duckdb_sql_parity/compare_rules.py
.\\.venv\\Scripts\\python.exe tutorials/duckdb_sql_parity/sparql_samples.py
```

- **Explore**: display DataFrame head, descriptive statistics, missing-value summary, and interactive Matplotlib plots (no PNG files written).
- **Compare**: generate one deterministic AHU dataset, load its history into an in-memory DuckDB `history` table, execute FC1/FC2/CMD-1 SQL extracted from `nf-app/rules/pack-postgres.json`, and independently execute `open_fdd.parity.reference(...)` for the pandas results. The script exits nonzero for missing or unequal fault-hour results (tolerance 1e-6 h).
- **Discover**: use RDFLib SPARQL over example point metadata and query the matching long-form samples with DuckDB.

**Important:** `pack-postgres.json` and `pack-sqlite.json` are **generated deployment artifacts**, not the SQL authoring source. To customize or add a rule, start with [Writing SQL rules](../sql-rules.html), edit `sql/fdd/postgres/rules/*.sql` and metadata, then regenerate and test the packs. DuckDB support varies by SQL dialect and PostgreSQL-only `fdd.*` functions.

## Setup by database

| Database | Rule SQL | Shims |
|---|---|---|
| PostgreSQL 14+ | `nf-app/rules/pack-postgres.json` or `sql/fdd/postgres/rules/*.sql` | Run `sql/fdd/postgres/postgres_helpers.sql` once (`fdd.try_double`, `fdd.mask_sweep_val` and the unit gates); `SET TimeZone = 'UTC'` |
| Timescale | same as PostgreSQL | same; Timescale only supplies `history` |
| DuckDB | the PostgreSQL pack | Define the `fdd.*` helpers as DuckDB macros (plpgsql does not parse); needed only by the occupancy and sensor-sweep rules; `SET TimeZone = 'UTC'` |
| SQLite | `nf-app/rules/pack-sqlite.json` | Built in; use the SQLite pack, not the PostgreSQL one |

`DATE_TRUNC('hour', timestamp_utc)` follows the session time zone, so always set UTC.

## Input contract

Create the tables from `sql/fdd/input_contract.sql` (scratch DDL generated from `sql/fdd/input_contract.json`) and fill them yourself.

| Table | Content |
|---|---|
| `history` | One row per `equipment_id` and `timestamp_utc` (UTC), one `DOUBLE PRECISION` column per role |
| `weather` | As-of weather: `timestamp_utc`, `oa_t`, `web_oa_t`, `web_oa_dp` |
| `sensor_history` | Long form for the sensor sweeps: `equipment_id`, `series_id`, `sensor_role`, `unit`, `timestamp_utc`, `value` |
| `utility_interval`, `utility_monthly` | Only for the `UTIL-*` rules |

Values are SI: °C, Δ°C, Pa, L/s, kW, kWh; commands and positions 0-1; statuses 0/1; relative humidity 0-100 %RH. Rules never convert units
(see the [units convention](sql-cookbook.html#units-convention)).

## If the numbers do not match pandas

Most likely cause first.

| # | Check | Fix |
|---|---|---|
| 1 | Imperial instead of SI, or 0-100 instead of 0-1 fractions | Convert to SI before loading |
| 2 | Naive timestamps or a non-UTC session zone | Store `timestamptz` in UTC; `SET TimeZone = 'UTC'` |
| 3 | Contract column names (`duct_static`) vs Haystack names (`duct-static-pressure`) on the pandas side | Map with `sql/fdd/role_map.json` |
| 4 | `resample().mean()` instead of forward sample-and-hold | Hold each sample forward; a gap over 1 h is unknown |
| 5 | pandas startup holdoff of 600 s; SQL `startup_delay_min` defaults to 0 | Set the same delay on both sides |
| 6 | NULL handling vs `fillna(False)` | Keep unknown as unknown; compare on covered time |
| 7 | `fault_hours` denominator | It is eligible hold time, not calendar hours or a row count |
| 8 | Weather as-of window, duplicate timestamps, gate order | De-duplicate and sort first; `SV-RATE` uses a different algorithm (known divergence) |

Rules that differ on purpose are listed on the [parity](parity.html) page.

## Seeded data and pandas twins

`open_fdd.parity` generates the same SI dataset every time and runs the pandas twin of every rule. Use it as the oracle for your database.

| Call | Use |
|---|---|
| `generate(seed, equips, days, profile)` | Seeded SI history, weather and model; `content_hash()` is stable |
| `reference(ds)` | pandas fault hours per rule and equipment |
| `compare(rows, ref, Policy.default())` | Tolerance 1e-6 h plus the known-difference list |

Full API, profiles and the adapter interface: [parity harness](parity-harness.html). The [pandas cookbook](pandas-cookbook.html) lists every twin.
