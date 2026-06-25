# Haystack integration (Open-FDD edge)

Open-FDD connects to a **Project Haystack REST server** — typically **Niagara nHaystack** on a local station — using the Rust driver built on [`rusty-haystack-client`](https://github.com/jscott3201/rusty-haystack) (pinned git rev in `edge/Cargo.toml`).

## What you need

| Setting | Description |
|---------|-------------|
| `base_url` | Haystack API root, e.g. `http://<host>:<port>/haystack` |
| Credentials | HTTP Basic (typical for nHaystack) or SCRAM (`auth_mode = "scram"`) |
| TLS | Set `tls_verify = false` only for lab self-signed certs |

**Do not commit passwords or private IPs.** Use environment variables or a gitignored local TOML file.

## Enable locally

1. Copy `workspace/haystack/local.nhaystack.example.toml` → `workspace/haystack/local.nhaystack.toml` (gitignored).
2. Set `OPENFDD_HAYSTACK_USER` and `OPENFDD_HAYSTACK_PASS`, or use `username_env` / `password_env` keys in the TOML.
3. Optionally override with `OPENFDD_HAYSTACK_BASE`.
4. Restart the edge / Docker stack.

For CI and unit tests without a live station, set `OPENFDD_HAYSTACK_FIXTURE=1`.

## Dashboard

**Integrations → Haystack** (`/haystack`):

- Test connection, About, Ops, Browse/Nav, Read, Poll once, Import model
- Tree view for sites/equipment/points with mapping status
- Activity console (raw JSON under Advanced)

## API routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/haystack/status` | Driver status (200 even when disabled) |
| POST | `/api/haystack/test` | Connect + about |
| GET | `/api/haystack/about` | Server metadata |
| GET | `/api/haystack/ops` | Supported ops |
| POST | `/api/haystack/nav` | Browse navigation tree |
| POST | `/api/haystack/read` | Read by ids or filter |
| POST | `/api/haystack/poll-once` | One-shot poll → normalized samples |
| POST | `/api/haystack/import` | Import Haystack records into model |
| GET | `/api/haystack/driver/tree` | UI driver tree |
| GET | `/api/model/haystack` | Imported model grid |
| POST | `/api/model/haystack/import` | Same as import |
| GET | `/api/model/sources` | Normalized sources |
| GET | `/api/model/equipment` | Normalized equipment |
| GET | `/api/model/points` | Normalized points |

When disabled, responses include `"enabled": false` and `"status": "disabled"` — never HTTP 404.

## Manual smoke script

```bash
export OPENFDD_HAYSTACK_BASE="http://127.0.0.1:8080/haystack"
export OPENFDD_HAYSTACK_USER="..."
export OPENFDD_HAYSTACK_PASS="..."
./scripts/openfdd_haystack_smoke.sh
```

## Future BACnet parity

See [haystack_bacnet_parity.md](../validation/haystack_bacnet_parity.md) and the example profile `workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example`.

## Niagara setup (high level)

Enable the **nHaystack** module on your Niagara station and expose the Haystack REST servlet. For a walkthrough example (external), see the [nHaystack Niagara Pi tutorial](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_17/nhaystack-niagara-pi-tutorial).

Live Niagara tests are **local/manual only** for now — CI uses mocked/fixture responses.
