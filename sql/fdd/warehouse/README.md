# Generic SQL warehouse version

These 77 templates use CTEs, CASE, window functions, integer masks, explicit ROWS frames and ANSI-style FLOAT(53) casts. They expose five narrow dialect hooks below instead of embedding PostgreSQL functions. This is a porting version with explicit dependencies, not an assertion that all SQL products accept identical syntax.

| Hook | Required behavior | Typical target implementation |
| --- | --- | --- |
| `fdd_try_double(text)` | Parse numeric text, return NULL on invalid/overflow; do not throw for occupancy words | Target safe-cast expression/UDF |
| `fdd_is_nan(number)` | Return integer 1 for NaN, 0 otherwise (including NULL); keep NULL/invalid quality separately | Engine NaN function; ingest quality flag if NaN unsupported |
| `fdd_elapsed_seconds(start,end)` | Fractional seconds from start to end, NULL for NULL endpoint | Timestamp-difference expression with correct units |
| `fdd_hour_bucket_utc(timestamp)` | Truncate an instant to its UTC clock hour | UTC timezone conversion + hour truncation |
| `fdd_month_key_utc(timestamp)` | UTC YYYY-MM string; use the same billing timezone contract in both utility adapters | Format/extract month key |

`dialect_manifest.json` identifies which files require which hooks. If warehouse UDFs are unavailable, have the dialect compiler replace parsed hook calls with reviewed SQL expressions, not unsafe global string substitution against user SQL. Only templates shipped/reviewed with the application are executable.

Map the ANSI float type to the engine's equivalent (BigQuery FLOAT64, SQL Server FLOAT(53), PostgreSQL DOUBLE PRECISION, etc.). Check that `STDDEV_SAMP` is sample standard deviation, and inspect integer/numeric division, CASE type inference, quoted identifiers and UTC timestamp storage. Standard-looking SQL still needs target-engine tests. Generic input relations have exactly the same role/unit contract and tuning metadata as PostgreSQL.

`duckdb_adapter.sql` is an offline hook implementation; `postgres_adapter.sql` implements these hook names in PostgreSQL for testing the generic version there. Other dialects must implement their own hooks. In PostgreSQL install the main `../postgres_helpers.sql` first, then this adapter. The test harness installs helpers in a unique rollback-only scratch schema automatically. Do not treat DuckDB as proof of another warehouse's syntax or numerical behavior.

Render via `python sql/render_rule.py FC1 --dialect warehouse`. Compare via `python parity.py --dialect warehouse --engine duckdb`. Use `--engine postgres` to execute this version through its PostgreSQL adapter on a disposable PostgreSQL database. A new engine adapter must load the same CSV cases and return both aggregate metrics and per-timestamp masks; run the strict tests rather than checking equal hours alone.
