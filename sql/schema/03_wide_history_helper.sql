-- Wave-X helper markers. Wide TEMP history is built per-run in Rust/sql_runner
-- (BPS wide_history pattern) — not as a permanent wide hypertable.

CREATE SCHEMA IF NOT EXISTS fdd;

INSERT INTO seed_meta(key, value) VALUES ('schema_version', '3.6.0-wave-x')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
