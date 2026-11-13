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

## Parquet replay (DuckDB)

`open-fdd nf pull --out history.parquet` exports NF history directly to Parquet (with `pyarrow`), and DuckDB queries `.parquet` files natively via `read_parquet(...)` with no database server:

```python
import json, duckdb, pandas as pd
from open_fdd.parity import generate, reference

ds = generate(seed=0, equips=2, days=3, profile="basic")
pack = json.load(open("nf-app/rules/pack-postgres.json"))
hist = pd.DataFrame(ds.to_engine_input()["history"])
hist["timestamp_utc"] = pd.to_datetime(hist.pop("ts"), unit="ms", utc=True)

con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
con.register("hist_df", hist)
con.execute("COPY hist_df TO '/tmp/history.parquet' (FORMAT PARQUET)")
con.execute("CREATE TABLE history AS SELECT * FROM read_parquet('/tmp/history.parquet')")

ref = reference(ds)
for eq, fh, _cov, _pct in con.execute(pack["rules"]["FC1"]["sql"]).fetchall():
    assert abs(fh - ref["FC1"][eq]["pandas"]) < 1e-6  # deliberately shifting fh raises AssertionError
```

## Published SI fixture sizes

`open_fdd.parity.generate(seed=0, equips, days, profile)` produces deterministic SI tables on a 5-minute grid:

| Profile | Size (`equips x days`) | `history` rows | `sensor_history` rows | `weather` rows | Content hash prefix |
|---|---|---:|---:|---:|---|
| `basic` | `2 x 3` | 1,728 | 25,920 | 216 | `c75a43e4dc93` |
| `basic` | `4 x 3` | 3,456 | 51,840 | 216 | `608fd164bfa0` |
| `basic` | `8 x 7` | 16,128 | 241,920 | 504 | `7e2801387b73` |
| `edge` | `2 x 3` | 1,705 | 25,575 | 216 | `60ed33ab47d3` |
| `edge` | `4 x 3` | 3,403 | 51,045 | 216 | `998f2b5c0d4e` |
| `edge` | `8 x 7` | 16,069 | 241,035 | 504 | `ed82a649d58e` |

## Runnable DuckDB and SPARQL tutorial

The [standalone DuckDB tutorial](https://github.com/bbartling/open-fdd/tree/master/tutorials/duckdb_sql_parity) includes executable pandas-versus-SQL assertions for FC1, FC2 and CMD-1, plus SPARQL point discovery joined to a DuckDB long-form historian. Both scripts run locally without an NF server. Follow its README for PowerShell or Linux setup.

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
