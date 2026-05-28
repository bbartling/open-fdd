---
name: caddy-lan-ingress-auth
description: "Configures Caddy reverse proxy with optional basic auth and path routing to bridge, MCP, UI, and bench sidecars. Use when auth is caddy_lan or caddy_tls_internal."
---

# Caddy LAN ingress auth

## Variants

- `simple` — HTTP :80 reverse proxy
- `cidr` — basic auth + CIDR allowlist templates
- `tls-internal` — internal TLS

## Path routing (legacy Option A)

- `/api/openfdd/*` → 127.0.0.1:8765
- `/api/mcp/*` → 127.0.0.1:8090
- `/api/easyaso/*` → 127.0.0.1:18090
- `/api/diy/*` → 127.0.0.1:8080
- `/` → UI :5173

Env: `OPENFDD_BASIC_AUTH_USER`, `OPENFDD_BASIC_AUTH_HASH` (`caddy hash-password`).

See [references/REFERENCE.md](references/REFERENCE.md).
