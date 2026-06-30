# Haystack integration

Rust driver on [`rusty-haystack-client`](https://github.com/jscott3201/rusty-haystack) (git pin in `edge/Cargo.toml`). Typical target: **Niagara nHaystack** REST.

## Configuration

| Setting | Description |
|---------|-------------|
| `base_url` | e.g. `http://<host>:<port>/haystack` |
| Credentials | HTTP Basic (typical) or SCRAM (`auth_mode = "scram"`) |
| TLS | `tls_verify = false` for lab self-signed certs only |

Use `workspace/haystack/local.nhaystack.toml` (gitignored) or `OPENFDD_HAYSTACK_*` env vars. Set `OPENFDD_HAYSTACK_FIXTURE=1` for CI without a live station.

## Dashboard

**Integrations → Haystack** (`/haystack`): connect, browse, read, poll, import into the Open-FDD model grid.

## Bridge API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/haystack/status` | Status (200 when disabled) |
| POST | `/api/haystack/test` | Connection test |
| POST | `/api/haystack/read` | Read by ids or filter |
| POST | `/api/haystack/nav` | Navigation tree |
| POST | `/api/haystack/import` | Import records → model grid |
| GET | `/api/haystack/driver/tree` | Normalized driver tree |

## Model API (after import)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/haystack` | Haystack grid JSON |
| GET | `/api/model/ttl` | RDF Turtle export |
| GET | `/api/model/sparql/predefined` | SPARQL query catalog |
| POST | `/api/model/sparql` | Execute SELECT |
| GET | `/api/model/tree` | Site equipment + points |
| POST | `/api/model/haystack/import` | Same as haystack import |

SPARQL details: [modeling/haystack_dashboard_model.md](../modeling/haystack_dashboard_model.md)

## Smoke test

```bash
export OPENFDD_HAYSTACK_BASE="http://127.0.0.1:8080/haystack"
export OPENFDD_HAYSTACK_USER="..."
export OPENFDD_HAYSTACK_PASS="..."
./scripts/openfdd_haystack_smoke.sh
```

## References

- [development/local_haystack_niagara.md](../development/local_haystack_niagara.md)
- [validation/haystack_bacnet_parity.md](../validation/haystack_bacnet_parity.md)
