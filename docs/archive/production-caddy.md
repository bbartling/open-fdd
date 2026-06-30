# Production deployment (Caddy + Rust edge)

TLS-terminated edge suitable for LAN pen-tests and controlled remote access.

## Quick start (source checkout)

```bash
# Auth credentials (once)
cd edge && cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local
chmod 600 ../workspace/auth.env.local

docker compose -f docker-compose.prod.yml up -d --build
./scripts/openfdd_prod_validate.sh
```

## Endpoints

| URL | Purpose |
| --- | --- |
| `https://127.0.0.1/` | Dashboard (via Caddy) |
| `https://127.0.0.1/api/health` | Public health |
| `POST /api/auth/login` | JWT login (integrator/agent/operator) |

Default TLS uses Caddy `tls internal` (self-signed). Accept `-k` in curl or install the Caddy root for your lab CA.

## Hardening for pen-tests

- Bind Caddy to a Tailscale IP or firewall-restricted interface
- Keep `workspace/auth.env.local` mode `600`
- Do not expose port 8080 directly — prod compose uses Caddy only
- Review [rust-edge-auth.md](../security/rust-edge-auth.md) for RBAC rules

## GHCR production

Use `docker/compose.edge.rust.yml` from bootstrap for image-only installs. Add a host-level Caddy or reverse proxy in front of `127.0.0.1:8080` using the same `docker/Caddyfile` pattern.
