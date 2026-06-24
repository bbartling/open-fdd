# LAN hardening

## Ingress

Use **Caddy** as the default LAN-facing ingress (`OPENFDD_CADDY_ENABLED=1`). Modes:

| Mode | Env | Behavior |
|------|-----|----------|
| Direct (dev) | `OPENFDD_CADDY_MODE=off` | Bridge on `127.0.0.1:8080`; auth still required unless loopback-only dev |
| HTTP | `OPENFDD_CADDY_MODE=http` | Caddy :80 → bridge; auth required |
| TLS | `OPENFDD_CADDY_MODE=tls` | Caddy :443, redirect :80→:443, self-signed certs |

## Security headers

The Rust bridge sets CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP, and CORP on API and static responses.

## Auth

- Non-health API routes require JWT auth
- Agent/bootstrap endpoints require `agent` or `admin` role
- Auth cannot be disabled when binding to `0.0.0.0` or behind Caddy LAN ingress
- Rotate `OFDD_AUTH_SECRET` after compromise: `openfdd-edge auth rotate --all`

## Exposure

Caddy proxies only to the internal bridge. MCP/Ollama, BACnet, and Modbus sidecars are not exposed as public HTTP unless explicitly configured.

See also [secrets-auth.md](secrets-auth.md) and [tls-and-certs.md](tls-and-certs.md).
