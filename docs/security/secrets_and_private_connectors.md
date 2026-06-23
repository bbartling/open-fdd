# Secrets and private connectors

## Never commit

- Customer hostnames, site names, or point catalogs
- Passwords, bearer tokens, connection strings
- Private SQL dumps or CSV exports with real operational data

## Gitignored locations

| Path | Purpose |
|------|---------|
| `workspace/connectors/local/*.local.toml` | Private connector overrides |
| `workspace/connectors/local/*.local.json` | Private JSON connector configs |
| `workspace/connectors/local/sql/*.local.sql` | Private SQL templates |
| `workspace/secrets/openfdd-secrets.local.env` | Secret values referenced by name |
| `workspace/data/` | Historian, registry runtime state |

Public examples under `examples/connectors/` contain no real credentials.

## Secret references

Connector configs reference secrets by name:

```toml
[auth]
secret_ref = "OPENWEATHERMAP_API_KEY"
```

Values live only in `workspace/secrets/openfdd-secrets.local.env`:

```env
OPENWEATHERMAP_API_KEY=your-key-here
```

API responses redact secret fields as `***REDACTED***`.

## No arbitrary Rust upload

Open-FDD does not compile or execute user-supplied Rust from the UI. Custom behavior is limited to:

- Connector configuration files
- JSON path mappings
- Approved SQL templates
- Built-in connector plugins

For sandboxed custom transforms, see GitHub issue proposing a WASM plugin system.

## Roles

| Action | Role |
|--------|------|
| List/read sources | operator, integrator, agent |
| Create/edit sources, poll, backfill | integrator, agent |
| Export historian CSV | authenticated user |

Anonymous source discovery and export are rejected.
