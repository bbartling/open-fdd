# SQL input guide (read-only)

## SQLite

1. Sidebar → **SQLite**
2. Path to `.db` file
3. Table name — app runs `SELECT * FROM "table"` in read-only URI mode

## DuckDB

1. Sidebar → **DuckDB SELECT**
2. Path to `.duckdb` file
3. Enter a **SELECT** query only — `INSERT`, `UPDATE`, `DELETE`, `DROP`, etc. are rejected

Results are normalized to a datetime index when a timestamp column is detected.

## Optional Parquet

Sidebar → **Parquet** for convenience reads only — not a production engine.
