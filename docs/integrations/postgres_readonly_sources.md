# Postgres read-only sources

The `postgres_readonly` connector type ingests from read-only data lakes using approved SQL templates. It complements JSON API feeds when a curated JSON export is not available.

## Security

- Connection strings must use `connection_secret_ref` pointing to `workspace/secrets/openfdd-secrets.local.env`.
- Only `SELECT` templates are allowed; DDL/DML keywords are rejected.
- Queries require `:start_ts`, `:end_ts`, and `:limit` for history templates.
- Connection strings and passwords are redacted in API responses and logs.

## Local SQL templates

Override public examples by copying into `workspace/connectors/local/sql/*.local.sql` (gitignored).

Public examples:

- `examples/connectors/sql/point_catalog.example.sql`
- `examples/connectors/sql/current_values.example.sql`
- `examples/connectors/sql/history_backfill.example.sql`

## Demo mode

Without a configured DSN secret, the connector serves a sanitized demo catalog and writes deterministic sample rows to the historian. Live Postgres execution requires a local read-only DSN and is not exercised in CI.

## API

- `POST /api/sources/demo_portfolio_postgres/test`
- `GET /api/sources/demo_portfolio_postgres/catalog`
- `POST /api/sources/demo_portfolio_postgres/poll-once` (integrator/agent)
- `POST /api/sources/demo_portfolio_postgres/backfill` (integrator/agent)

SQL connector configuration changes require integrator or agent role.
