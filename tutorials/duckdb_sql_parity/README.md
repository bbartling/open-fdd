# DuckDB + pandas == SQL tutorial

A standalone, local tutorial for engineers borrowing Open-FDD fault rules.
**No Normal Framework server, PostgreSQL instance, field hardware, or live BACnet
connection is required.** The scripts use Open-FDD's seeded, SI-unit dataset.

## Windows PowerShell quick start

From the root of a cloned `open-fdd` repository:

```powershell
uv venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -e ".[oracle]" duckdb rdflib
.\.venv\Scripts\python.exe tutorials/duckdb_sql_parity/compare_rules.py
.\.venv\Scripts\python.exe tutorials/duckdb_sql_parity/sparql_samples.py
```

Alternatively, after installing dependencies in a virtual environment, use
`python tutorials/duckdb_sql_parity/compare_rules.py` from anywhere.
The parity script locates the SQL pack relative to its own file.

On Linux/macOS, replace `.venv/Scripts/python.exe` with `.venv/bin/python`.
`uv pip install` does **not** require pip to be preinstalled in the venv.

## Lesson 1: prove your borrowed SQL matches pandas

`compare_rules.py` generates **two AHUs × three days**, sampled every five
minutes, using `generate(seed=0, equips=2, days=3, profile="basic")`.
The history is loaded into in-memory DuckDB with UTC timestamps. It runs the
**unchanged, generated** `nf-app/rules/pack-postgres.json` rule SQL and compares
each equipment's `fault_hours` to `open_fdd.parity.reference`.

The default rules are `FC1`, `FC2`, and `CMD-1`. An absent equipment, NULL
value, non-finite result, or difference over **0.000001 hours** fails with a
nonzero exit code. That makes the script useful as a small regression test.

```powershell
.\.venv\Scripts\python.exe tutorials/duckdb_sql_parity/compare_rules.py --rules FC1 FC2 CMD-1
```

The tutorial does **not** imply all PostgreSQL SQL will run in DuckDB:
rules calling PostgreSQL `fdd.*` helper functions need equivalent DuckDB
macros; other PostgreSQL-only syntax might also need porting. This is a
demonstration of the portable subset, not a full DuckDB engine adapter.
If you modify SQL, test equivalence using the same inputs, rule parameters,
coverage semantics, startup holdoffs and UTC time zone.

## Lesson 2: SPARQL point discovery + DuckDB historian

`sparql_samples.py` uses the seeded dataset's `to_core_rows()` to make a
long-form `input_sample` table, and builds a **small tutorial RDF graph** from
the generated point metadata. SPARQL finds `sat` and `duct_static` point keys.
DuckDB then retrieves sample counts and SI ranges for those keys with a
**parameterized query**. The toy graph is not a claim of full Brick/Haystack
ontology coverage or a production NF RDF export.

Both examples use in-memory databases, leave the checkout untouched, and
never use network or building connections.

## When the numbers differ

Check role names, SI units (°C, Pa, L/s, 0–1 commands), UTC timestamps,
duplicate timestamps, missing-data coverage, startup holdoff and the
forward-hold sample semantics. Only the three default rules above are
presented as directly portable; known SQL/pandas divergence is documented
in [the parity page](../../docs/rules/parity.md).

See [Using SQL rules outside Open-FDD](../../docs/rules/borrowing-sql.md)
and [the parity harness](../../docs/rules/parity-harness.md).
