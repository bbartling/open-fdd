# Rust edge authentication

Open-FDD on the `master` branch (3.2 Rust edge) implements edge authentication entirely in Rust.

## Credential file

| Item | Value |
| --- | --- |
| Path | `workspace/auth.env.local` |
| Permissions | `chmod 600` on Unix |
| Git | Never commit (workspace is gitignored) |

Generated keys:

- `OFDD_AUTH_SECRET`
- `OFDD_OPERATOR_USER` / `OFDD_OPERATOR_PASSWORD`
- `OFDD_INTEGRATOR_USER` / `OFDD_INTEGRATOR_PASSWORD`
- `OFDD_AGENT_USER` / `OFDD_AGENT_PASSWORD`
- `OFDD_AUTH_REQUIRED` (default true)
- `OFDD_JWT_TTL_SECONDS` (default 28800)
- `OFDD_COOKIE_SECURE` (default false for local HTTP)

## Generate or rotate

```bash
openfdd_edge auth init --path workspace/auth.env.local
openfdd_edge auth init --path workspace/auth.env.local --force
openfdd_edge auth init --path workspace/auth.env.local --show-secrets  # lab only
```

Built from source:

```bash
cd edge && cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local
```

After rotation:

```bash
docker compose up -d --force-recreate
```

Docker Compose loads `workspace/auth.env.local` via `env_file` at container creation time.

## Login API

`POST /api/auth/login`

```json
{"username":"integrator","password":"..."}
```

Roles are derived from validated credentials only. Clients cannot supply `role` or `sub` to mint tokens.

## JWT

- Algorithm: HS256 with `OFDD_AUTH_SECRET`
- Claims: `sub`, `role`, `iat`, `exp`, `iss=open-fdd`, `aud=open-fdd-edge`
- Authorization header: `Bearer <token>`

## RBAC summary

| Role | Capabilities |
| --- | --- |
| operator | Read dashboard, health, driver trees, points, faults, overrides |
| integrator | Operator + configure drivers, commission, scans, exports, diagnostics |
| agent | Read stack/context, safe diagnostics; no direct field writes |

Field bus writes require integrator role **and** explicit human approval (`approved=true`). Auth alone is not write approval.

## Public vs protected routes

Public:

- `GET /api/health`, `GET /health`
- static frontend assets
- `POST /api/auth/login`

Protected (Bearer required):

- `GET /api/health/stack`
- driver, BACnet, Modbus, Haystack, control, agent, and report mutation APIs

## Security headers and CORS

Responses include `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, CSP, and `Cache-Control: no-store` on auth/JSON responses.

CORS is denied by default. Set `OPENFDD_CORS_ORIGIN` for explicit local dev origins only.

## Audit logging

`workspace/logs/auth_audit.jsonl` records login success/failure, forbidden access, and logout summaries. Secrets, passwords, full JWTs, and Authorization headers are never logged.

## Network posture

**Open-FDD is intended for localhost, LAN, OT networks, Tailscale, VPN, or reverse-proxy-controlled deployments. Do not expose the bridge API directly to the public internet.**

| Binding | Default | Override |
|---------|---------|----------|
| Bridge HTTP | `127.0.0.1:8080` | `OPENFDD_BIND_HOST=0.0.0.0` for intentional LAN-only exposure |
| Vite dev UI | `127.0.0.1:5173` | `./scripts/openfdd_ui_dev.sh --lan` |

BACnet/IP and Modbus/TCP must never be forwarded to the internet. Use Caddy TLS (`docker/compose.edge.rust.yml` profile `caddy-tls`) when remote operators need HTTPS.

Public `GET /api/health` returns only `ok`, `version`, `image_tag`, and `auth_required` — no OT hostnames, credentials, or service inventory.

Bind to OT-LAN or localhost. Use VPN/Tailscale/reverse proxy for remote access.
